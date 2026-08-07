"""
EPIC-28 — Space Lottery / Chrono Chamber.

Owner: weekly Tombola (progressive TK pool) + Mines + Crash instant games.
Stakes via timekeeper.debit/credit only. Fairness via game.provably_fair.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from game.db import table_exists
from game.provably_fair import gen_server_seed, hash_seed, seeded_rng, uniform01
from game.time_format import format_duration_human
from game.timekeeper import (
    InsufficientTimekeeperBalance,
    credit,
    debit,
    get_balance,
    schema_ready as tk_schema_ready,
    serialize_for_client as tk_serialize,
)

# --- Balance defaults (admin can override via universe settings later) ----------

HOUSE_EDGE = 0.04  # ~96% RTP
TICKET_PRICE_SEC = 300
MIN_BET_SEC = 60
MAX_BET_SEC = 3600
# GC-2809: each game has its own UTC-day volume (no shared 5h pool).
DAILY_WAGER_GAME_TOMBOLA = "tombola"
DAILY_WAGER_GAME_MINES = "mines"
DAILY_WAGER_GAME_CRASH = "crash"
DAILY_WAGER_CAPS_SEC = {
    DAILY_WAGER_GAME_TOMBOLA: 18_000,  # 5h tickets → weekly pool
    DAILY_WAGER_GAME_MINES: 36_000,  # 10h Void Mines
    DAILY_WAGER_GAME_CRASH: 36_000,  # 10h Orbit Crash
}
# Legacy alias (tombola) — prefer DAILY_WAGER_CAPS_SEC[game]
DAILY_WAGER_CAP_SEC = DAILY_WAGER_CAPS_SEC[DAILY_WAGER_GAME_TOMBOLA]
MINES_GRID = 25  # 5x5
MINES_DEFAULT_COUNT = 3
MINES_MIN_COUNT = 1
MINES_MAX_COUNT = 10
CRASH_MAX_MULT = 1000.0  # GC-2810 — rare high crashes capped at 1000×
HISTORY_LIMIT = 12
CRASH_HISTORY_LIMIT = 25
WINNERS_LIMIT = 5
# GC-2807: weekly draw window — Sunday 20:00 UTC (ISO week still that Sunday).
DRAW_HOUR_UTC = 20
DRAW_MINUTE_UTC = 0

GAMES = frozenset({"mines", "crash"})
# Live product gate: only Wochen-Tombola is player-facing until Mines/Crash are cleared.
# Tests unlock all via lottery_db monkeypatch of LIVE_MODES.
LIVE_MODES = frozenset({"tombola"})
ALL_MODES = frozenset({"tombola", "mines", "crash"})
ROUND_ACTIVE = "active"
ROUND_CASHED = "cashed"
ROUND_BUST = "bust"
WEEK_OPEN = "open"
WEEK_PAID = "paid"

SOURCES = {
    "ticket": "lottery:ticket",
    "mines_bet": "lottery:mines_bet",
    "mines_win": "lottery:mines_win",
    "crash_bet": "lottery:crash_bet",
    "crash_win": "lottery:crash_win",
    "tombola_prize": "lottery:tombola_prize",
}


def schema_ready(conn) -> bool:
    return (
        table_exists(conn, "space_lottery_weeks")
        and table_exists(conn, "space_lottery_rounds")
        and table_exists(conn, "space_lottery_daily_game")
        and tk_schema_ready(conn)
    )


def mode_enabled(mode: str) -> bool:
    return str(mode or "") in LIVE_MODES


def live_modes_public() -> Dict[str, Any]:
    return {
        "live": [m for m in ("tombola", "mines", "crash") if m in LIVE_MODES],
        "tombola": mode_enabled("tombola"),
        "mines": mode_enabled("mines"),
        "crash": mode_enabled("crash"),
    }


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _json_loads(raw: Any, default: Any = None) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def current_week_id(now: Optional[float] = None) -> str:
    ts = float(now if now is not None else time.time())
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def parse_week_id(week_id: str) -> Tuple[int, int]:
    raw = str(week_id or "").strip().upper()
    if "-W" not in raw:
        raise ValueError("invalid_week_id")
    year_s, week_s = raw.split("-W", 1)
    return int(year_s), int(week_s)


def week_draw_at(week_id: str) -> float:
    """Unix timestamp for Sunday DRAW_HOUR_UTC of the given ISO week."""
    year, week = parse_week_id(week_id)
    monday = datetime.fromisocalendar(int(year), int(week), 1).replace(tzinfo=timezone.utc)
    sunday = monday + timedelta(days=6)
    draw = sunday.replace(
        hour=int(DRAW_HOUR_UTC),
        minute=int(DRAW_MINUTE_UTC),
        second=0,
        microsecond=0,
    )
    return float(draw.timestamp())


def day_bucket(now: Optional[float] = None) -> int:
    return int(float(now if now is not None else time.time()) // 86400)


def _player_name(conn, user_id: int) -> str:
    if not user_id:
        return ""
    row = conn.execute(
        "SELECT name FROM players WHERE id = ? LIMIT 1;",
        (int(user_id),),
    ).fetchone()
    if not row:
        return f"Commander #{int(user_id)}"
    return str(row["name"] or f"Commander #{int(user_id)}")


def _recent_winners(*, conn, limit: int = WINNERS_LIMIT) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT week_id, pool_sec, winner_player_id, winner_tickets, drawn_at, server_seed_hash
        FROM space_lottery_weeks
        WHERE status = ? AND winner_player_id IS NOT NULL
        ORDER BY drawn_at DESC, week_id DESC
        LIMIT ?;
        """,
        (WEEK_PAID, int(limit)),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    now = float(time.time())
    for row in rows:
        pid = int(row["winner_player_id"] or 0)
        drawn = float(row["drawn_at"] or 0)
        out.append(
            {
                "week_id": str(row["week_id"]),
                "winner_player_id": pid,
                "winner_name": _player_name(conn, pid),
                "pool_sec": int(row["pool_sec"] or 0),
                "pool_label": format_duration_human(int(row["pool_sec"] or 0), max_parts=2),
                "winner_tickets": int(row["winner_tickets"] or 0),
                "drawn_at": drawn,
                "drawn_ago_sec": max(0, int(now - drawn)) if drawn else None,
                "seed_hash": row["server_seed_hash"],
            }
        )
    return out


def _clamp_bet(bet_sec: int) -> Tuple[Optional[int], str]:
    bet = int(bet_sec or 0)
    if bet < MIN_BET_SEC:
        return None, "bet_too_low"
    if bet > MAX_BET_SEC:
        return None, "bet_too_high"
    return bet, ""


def _record_wager(
    player_id: int,
    kind: str,
    delta_sec: int,
    *,
    balance_after: Optional[int],
    ref_type: str,
    ref_id: str,
    request_id: Optional[str],
    conn,
) -> None:
    conn.execute(
        """
        INSERT INTO space_lottery_wagers
            (player_id, kind, delta_sec, balance_after, ref_type, ref_id, request_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            int(player_id),
            str(kind)[:40],
            int(delta_sec),
            int(balance_after) if balance_after is not None else None,
            str(ref_type)[:40],
            str(ref_id)[:64],
            (str(request_id)[:80] if request_id else None),
            float(time.time()),
        ),
    )


def _get_daily_wagered(
    player_id: int,
    game: str,
    *,
    conn,
    now: Optional[float] = None,
) -> int:
    bucket = day_bucket(now)
    g = str(game or "")
    row = conn.execute(
        """
        SELECT wagered_sec FROM space_lottery_daily_game
        WHERE player_id = ? AND day_bucket = ? AND game = ?;
        """,
        (int(player_id), bucket, g),
    ).fetchone()
    return int(row["wagered_sec"] or 0) if row else 0


def _daily_cap_for(game: str) -> int:
    return int(DAILY_WAGER_CAPS_SEC.get(str(game), DAILY_WAGER_CAP_SEC))


def _daily_slice(player_id: int, game: str, *, conn, now: Optional[float] = None) -> Dict[str, Any]:
    wagered = _get_daily_wagered(player_id, game, conn=conn, now=now)
    cap = _daily_cap_for(game)
    remaining = max(0, cap - wagered)
    return {
        "game": str(game),
        "wagered_sec": wagered,
        "cap_sec": cap,
        "remaining_sec": remaining,
        "wagered_label": format_duration_human(wagered, max_parts=2),
        "cap_label": format_duration_human(cap, max_parts=2),
        "remaining_label": format_duration_human(remaining, max_parts=2),
    }


def _add_daily_wager(
    player_id: int,
    game: str,
    amount: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, str]:
    amt = max(0, int(amount or 0))
    if amt <= 0:
        return True, ""
    g = str(game or "")
    if g not in DAILY_WAGER_CAPS_SEC:
        return False, "invalid_daily_game"
    bucket = day_bucket(now)
    current = _get_daily_wagered(player_id, g, conn=conn, now=now)
    cap = _daily_cap_for(g)
    if current + amt > cap:
        return False, "daily_wager_cap"
    conn.execute(
        """
        INSERT INTO space_lottery_daily_game (player_id, day_bucket, game, wagered_sec)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id, day_bucket, game) DO UPDATE SET
            wagered_sec = wagered_sec + excluded.wagered_sec;
        """,
        (int(player_id), bucket, g, amt),
    )
    return True, ""


def _ensure_week(conn, week_id: Optional[str] = None) -> Dict[str, Any]:
    wid = week_id or current_week_id()
    row = conn.execute(
        "SELECT * FROM space_lottery_weeks WHERE week_id = ? LIMIT 1;",
        (wid,),
    ).fetchone()
    if row:
        return dict(row)
    now = float(time.time())
    conn.execute(
        """
        INSERT INTO space_lottery_weeks
            (week_id, pool_sec, status, ticket_price_sec, created_at, updated_at)
        VALUES (?, 0, ?, ?, ?, ?);
        """,
        (wid, WEEK_OPEN, TICKET_PRICE_SEC, now, now),
    )
    row = conn.execute(
        "SELECT * FROM space_lottery_weeks WHERE week_id = ? LIMIT 1;",
        (wid,),
    ).fetchone()
    return dict(row)


def _player_tickets(week_id: str, player_id: int, *, conn) -> int:
    row = conn.execute(
        "SELECT ticket_count FROM space_lottery_tickets WHERE week_id = ? AND player_id = ?;",
        (str(week_id), int(player_id)),
    ).fetchone()
    return int(row["ticket_count"] or 0) if row else 0


def _active_round(player_id: int, game: Optional[str], *, conn) -> Optional[Dict[str, Any]]:
    if game:
        row = conn.execute(
            """
            SELECT * FROM space_lottery_rounds
            WHERE player_id = ? AND game = ? AND status = ?
            ORDER BY id DESC LIMIT 1;
            """,
            (int(player_id), str(game), ROUND_ACTIVE),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM space_lottery_rounds
            WHERE player_id = ? AND status = ?
            ORDER BY id DESC LIMIT 1;
            """,
            (int(player_id), ROUND_ACTIVE),
        ).fetchone()
    return dict(row) if row else None


def _find_by_request(player_id: int, request_id: str, *, conn) -> Optional[Dict[str, Any]]:
    rid = str(request_id or "").strip()
    if not rid:
        return None
    row = conn.execute(
        """
        SELECT * FROM space_lottery_rounds
        WHERE player_id = ? AND request_id = ?
        ORDER BY id DESC LIMIT 1;
        """,
        (int(player_id), rid[:80]),
    ).fetchone()
    return dict(row) if row else None


def mines_multiplier(revealed: int, mine_count: int, grid: int = MINES_GRID, edge: float = HOUSE_EDGE) -> float:
    """Payout multiplier after `revealed` safe cells (0 → 1.0 before edge apply on first?)."""
    r = max(0, int(revealed))
    mines = max(1, int(mine_count))
    total = max(mines + 1, int(grid))
    if r <= 0:
        return 1.0
    fair = 1.0
    for i in range(r):
        cells_left = total - i
        safe_left = total - mines - i
        if safe_left <= 0 or cells_left <= 0:
            break
        fair *= float(cells_left) / float(safe_left)
    return max(1.0, fair * (1.0 - float(edge)))


def crash_point_from_seed(server_seed: str, round_id: int, edge: float = HOUSE_EDGE) -> float:
    u = uniform01(server_seed, "crash", int(round_id))
    # Classic: crash = (1-e)/u floored to 2 decimals, min 1.00
    raw = (1.0 - float(edge)) / u
    mult = math.floor(raw * 100.0) / 100.0
    mult = max(1.0, min(float(CRASH_MAX_MULT), mult))
    return float(mult)


# Client starts the climb RAF after the start response arrives — subtract this so
# cashout timing matches the visible flight instead of punishing network/UI lag.
CRASH_START_LAG_MS = 500.0


def crash_bust_after_ms(crash_point: float) -> int:
    """Animation runway length for a crash point (client sync + server cashout timing)."""
    return int(2200 + math.log(max(1.01, float(crash_point))) * 3200)


def crash_mult_at_progress(crash_point: float, t: float) -> float:
    """
    Fair multiplier at progress t∈[0,1) along the climb toward crash_point.
    Approaches crash_point as t→1; never reaches/exceeds it before bust.
    """
    cp = max(1.01, float(crash_point))
    prog = max(0.0, min(0.999, float(t)))
    eased = math.pow(prog, 1.15)
    mult = 1.0 + (cp - 1.0) * eased
    out = math.floor(mult * 100.0) / 100.0
    # Earliest playable cashout once the climb has begun.
    if prog > 0.0 and out < 1.01 and cp > 1.01:
        return 1.01
    return out


def _layout_mines(server_seed: str, round_id: int, mine_count: int, grid: int = MINES_GRID) -> List[int]:
    rng = seeded_rng(server_seed, "mines", int(round_id), int(mine_count), int(grid))
    cells = list(range(int(grid)))
    rng.shuffle(cells)
    return sorted(cells[: int(mine_count)])


def _public_round(row: Dict[str, Any], *, reveal_seed: bool = False) -> Dict[str, Any]:
    payload = _json_loads(row.get("payload_json"), {}) or {}
    game = str(row.get("game") or "")
    status = str(row.get("status") or "")
    bet_sec = int(row.get("bet_sec") or 0)
    out: Dict[str, Any] = {
        "id": int(row["id"]),
        "game": game,
        "status": status,
        "bet_sec": bet_sec,
        "bet_label": format_duration_human(bet_sec, max_parts=2),
        "payout_sec": int(row.get("payout_sec") or 0),
        "payout_label": format_duration_human(int(row.get("payout_sec") or 0), max_parts=2),
        "seed_hash": str(row.get("seed_hash") or ""),
        "created_at": float(row.get("created_at") or 0),
        "settled_at": float(row["settled_at"]) if row.get("settled_at") is not None else None,
    }
    if reveal_seed or status in (ROUND_CASHED, ROUND_BUST):
        out["seed"] = str(row.get("seed") or "")
    if game == "mines":
        revealed = list(payload.get("revealed") or [])
        mine_count = int(payload.get("mine_count") or MINES_DEFAULT_COUNT)
        grid = int(payload.get("grid") or MINES_GRID)
        max_safe = max(0, grid - mine_count)
        # Hits = safe reveals only (bust row includes the mine cell in `revealed`).
        hit = payload.get("hit")
        if status == ROUND_BUST and hit is not None:
            safe_hits = len([c for c in revealed if int(c) != int(hit)])
        else:
            safe_hits = len(revealed)
        cur_mult = mines_multiplier(safe_hits, mine_count, grid)
        next_hits = min(max_safe, safe_hits + 1)
        next_mult = mines_multiplier(next_hits, mine_count, grid) if safe_hits < max_safe else cur_mult
        pot_mult = mines_multiplier(max_safe, mine_count, grid)
        pot_payout = int(round(bet_sec * pot_mult))
        cur_payout = int(round(bet_sec * cur_mult))
        out["mines"] = {
            "grid": grid,
            "mine_count": mine_count,
            "revealed": revealed,
            "hits": safe_hits,
            "max_safe": max_safe,
            "multiplier": round(cur_mult, 4),
            "next_multiplier": round(next_mult, 4),
            "potential_multiplier": round(pot_mult, 4),
            "payout_sec": cur_payout,
            "payout_label": format_duration_human(cur_payout, max_parts=2),
            "potential_payout_sec": pot_payout,
            "potential_payout_label": format_duration_human(pot_payout, max_parts=2),
        }
        if status in (ROUND_CASHED, ROUND_BUST):
            out["mines"]["mine_positions"] = list(payload.get("mine_positions") or [])
            out["mines"]["hit"] = payload.get("hit")
    elif game == "crash":
        cp = float(payload.get("crash_point") or 0) if payload.get("crash_point") is not None else None
        cashout_mult = payload.get("cashout_mult")
        display_mult = None
        if status == ROUND_CASHED and cashout_mult is not None:
            display_mult = round(float(cashout_mult), 4)
        elif status == ROUND_BUST and cp:
            display_mult = round(float(cp), 4)
        out["crash"] = {
            "crash_point": cp if status in (ROUND_CASHED, ROUND_BUST) else None,
            "cashout_mult": cashout_mult,
            "multiplier": display_mult,
            "max_mult": CRASH_MAX_MULT,
        }
        if status == ROUND_ACTIVE and cp:
            # Animation sync only — cashout still validated against hidden crash_point + elapsed time.
            out["crash"]["bust_after_ms"] = crash_bust_after_ms(cp)
            out["crash"]["seed_committed"] = True
    return out


def _recent_rounds(player_id: int, *, conn, limit: int = HISTORY_LIMIT) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM space_lottery_rounds
        WHERE player_id = ? AND status IN (?, ?)
        ORDER BY id DESC LIMIT ?;
        """,
        (int(player_id), ROUND_CASHED, ROUND_BUST, int(limit)),
    ).fetchall()
    return [_public_round(dict(r), reveal_seed=True) for r in rows]


def _mines_history(player_id: int, *, conn, limit: int = 10, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Settled Void Mines rounds for the left rail (GC-2808)."""
    rows = conn.execute(
        """
        SELECT * FROM space_lottery_rounds
        WHERE player_id = ? AND game = 'mines' AND status IN (?, ?)
        ORDER BY id DESC LIMIT ?;
        """,
        (int(player_id), ROUND_CASHED, ROUND_BUST, int(limit)),
    ).fetchall()
    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for raw in rows:
        pub = _public_round(dict(raw), reveal_seed=True)
        m = pub.get("mines") or {}
        settled = pub.get("settled_at")
        if settled is None:
            settled = pub.get("created_at") or ts
        ago = max(0, int(ts - float(settled)))
        out.append(
            {
                "id": pub["id"],
                "status": pub["status"],
                "bet_sec": pub["bet_sec"],
                "bet_label": pub.get("bet_label"),
                "payout_sec": pub["payout_sec"],
                "payout_label": pub.get("payout_label"),
                "multiplier": m.get("multiplier"),
                "mine_count": m.get("mine_count"),
                "hits": m.get("hits"),
                "ago_sec": ago,
                "seed_hash": pub.get("seed_hash"),
            }
        )
    return out


def _mines_today(player_id: int, *, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """UTC-day stats for Void Mines cashouts (GC-2808)."""
    ts = float(now if now is not None else time.time())
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    day_start = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp()
    rows = conn.execute(
        """
        SELECT * FROM space_lottery_rounds
        WHERE player_id = ? AND game = 'mines' AND status = ?
          AND settled_at IS NOT NULL AND settled_at >= ?
        ORDER BY id DESC;
        """,
        (int(player_id), ROUND_CASHED, float(day_start)),
    ).fetchall()
    won_sec = 0
    best_mult = 0.0
    last_high_mult = 0.0
    for i, raw in enumerate(rows):
        pub = _public_round(dict(raw), reveal_seed=False)
        pay = int(pub.get("payout_sec") or 0)
        won_sec += pay
        mult = float((pub.get("mines") or {}).get("multiplier") or 0)
        if mult > best_mult:
            best_mult = mult
        if i == 0:
            last_high_mult = mult
    return {
        "won_sec": won_sec,
        "won_label": format_duration_human(won_sec, max_parts=2),
        "best_mult": round(best_mult, 4) if best_mult else 0,
        "last_high_mult": round(last_high_mult, 4) if last_high_mult else 0,
    }


def _crash_history(player_id: int, *, conn, limit: int = CRASH_HISTORY_LIMIT, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Settled Orbit Crash rounds for the left rail (GC-2810)."""
    rows = conn.execute(
        """
        SELECT * FROM space_lottery_rounds
        WHERE player_id = ? AND game = 'crash' AND status IN (?, ?)
        ORDER BY id DESC LIMIT ?;
        """,
        (int(player_id), ROUND_CASHED, ROUND_BUST, int(limit)),
    ).fetchall()
    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for raw in rows:
        pub = _public_round(dict(raw), reveal_seed=True)
        c = pub.get("crash") or {}
        settled = pub.get("settled_at")
        if settled is None:
            settled = pub.get("created_at") or ts
        ago = max(0, int(ts - float(settled)))
        out.append(
            {
                "id": pub["id"],
                "status": pub["status"],
                "bet_sec": pub["bet_sec"],
                "bet_label": pub.get("bet_label"),
                "payout_sec": pub["payout_sec"],
                "payout_label": pub.get("payout_label"),
                "multiplier": c.get("multiplier"),
                "crash_point": c.get("crash_point"),
                "cashout_mult": c.get("cashout_mult"),
                "ago_sec": ago,
                "seed_hash": pub.get("seed_hash"),
            }
        )
    return out


def _crash_today(player_id: int, *, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """UTC-day stats for Orbit Crash cashouts (GC-2810)."""
    ts = float(now if now is not None else time.time())
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    day_start = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp()
    rows = conn.execute(
        """
        SELECT * FROM space_lottery_rounds
        WHERE player_id = ? AND game = 'crash' AND status = ?
          AND settled_at IS NOT NULL AND settled_at >= ?
        ORDER BY id DESC;
        """,
        (int(player_id), ROUND_CASHED, float(day_start)),
    ).fetchall()
    won_sec = 0
    best_mult = 0.0
    last_high_mult = 0.0
    for i, raw in enumerate(rows):
        pub = _public_round(dict(raw), reveal_seed=False)
        pay = int(pub.get("payout_sec") or 0)
        won_sec += pay
        mult = float((pub.get("crash") or {}).get("multiplier") or 0)
        if mult > best_mult:
            best_mult = mult
        if i == 0:
            last_high_mult = mult
    return {
        "won_sec": won_sec,
        "won_label": format_duration_human(won_sec, max_parts=2),
        "best_mult": round(best_mult, 4) if best_mult else 0,
        "last_high_mult": round(last_high_mult, 4) if last_high_mult else 0,
    }


def serialize_state(player_id: int, *, conn) -> Dict[str, Any]:
    if not schema_ready(conn):
        return {"ready": False}
    # Lazy-settle weeks whose Sunday 20:00 UTC draw window has passed.
    maybe_settle_due_weeks(conn=conn)
    week = _ensure_week(conn)
    wid = str(week["week_id"])
    tickets = _player_tickets(wid, player_id, conn=conn)
    active = _active_round(player_id, None, conn=conn)
    now = float(time.time())
    ends_at = week_draw_at(wid)
    pool_sec = int(week.get("pool_sec") or 0)
    daily_by_game = {
        g: _daily_slice(player_id, g, conn=conn, now=now)
        for g in DAILY_WAGER_CAPS_SEC
    }
    # Tombola UI still reads top-level daily_* — scoped to tombola module.
    daily_tombola = daily_by_game[DAILY_WAGER_GAME_TOMBOLA]
    ticket_price = int(week.get("ticket_price_sec") or TICKET_PRICE_SEC)
    return {
        "ready": True,
        "server_now": now,
        "house_edge": HOUSE_EDGE,
        "modes": live_modes_public(),
        "caps": {
            "min_bet_sec": MIN_BET_SEC,
            "max_bet_sec": MAX_BET_SEC,
            "daily_wager_cap_sec": daily_tombola["cap_sec"],
            "daily_wagered_sec": daily_tombola["wagered_sec"],
            "daily_wager_cap_label": daily_tombola["cap_label"],
            "daily_wagered_label": daily_tombola["wagered_label"],
            "by_game": daily_by_game,
        },
        "tombola": {
            "week_id": wid,
            "status": str(week.get("status") or WEEK_OPEN),
            "pool_sec": pool_sec,
            "pool_label": format_duration_human(pool_sec, max_parts=2),
            "ticket_price_sec": ticket_price,
            "ticket_price_label": format_duration_human(ticket_price, max_parts=2),
            "my_tickets": tickets,
            "ends_at": ends_at,
            "ends_in_sec": max(0, int(ends_at - now)),
            "draw_label": f"Sunday {DRAW_HOUR_UTC:02d}:00 UTC",
            "seed_hash": week.get("server_seed_hash"),
            "seed": week.get("server_seed") if str(week.get("status")) == WEEK_PAID else None,
            "winner_player_id": week.get("winner_player_id"),
            "winner_tickets": week.get("winner_tickets"),
            "drawn_at": week.get("drawn_at"),
            "recent_winners": _recent_winners(conn=conn),
        },
        "mines_defaults": {
            "grid": MINES_GRID,
            "mine_count": MINES_DEFAULT_COUNT,
            "min_mines": MINES_MIN_COUNT,
            "max_mines": MINES_MAX_COUNT,
            "max_safe": MINES_GRID - MINES_DEFAULT_COUNT,
            "potential_multiplier": round(
                mines_multiplier(MINES_GRID - MINES_DEFAULT_COUNT, MINES_DEFAULT_COUNT, MINES_GRID),
                4,
            ),
            "potential_by_mines": {
                str(mc): round(mines_multiplier(MINES_GRID - mc, mc, MINES_GRID), 4)
                for mc in range(MINES_MIN_COUNT, MINES_MAX_COUNT + 1)
            },
            "next_by_mines": {
                str(mc): round(mines_multiplier(1, mc, MINES_GRID), 4)
                for mc in range(MINES_MIN_COUNT, MINES_MAX_COUNT + 1)
            },
        },
        "mines_history": _mines_history(player_id, conn=conn, now=now),
        "mines_today": _mines_today(player_id, conn=conn, now=now),
        "crash_defaults": {
            "max_mult": CRASH_MAX_MULT,
        },
        "crash_history": _crash_history(player_id, conn=conn, now=now),
        "crash_today": _crash_today(player_id, conn=conn, now=now),
        "active_round": _public_round(active) if active else None,
        "history": _recent_rounds(player_id, conn=conn),
        "timekeeper": tk_serialize(player_id, conn=conn),
    }


def buy_tombola_tickets(
    player_id: int,
    count: int,
    *,
    conn,
    request_id: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "lottery_unavailable", None
    n = int(count or 0)
    if n < 1 or n > 50:
        return False, "invalid_ticket_count", None
    week = _ensure_week(conn)
    if str(week.get("status")) != WEEK_OPEN:
        return False, "week_closed", None
    price = int(week.get("ticket_price_sec") or TICKET_PRICE_SEC)
    cost = price * n
    ok_cap, reason_cap = _add_daily_wager(player_id, DAILY_WAGER_GAME_TOMBOLA, cost, conn=conn)
    if not ok_cap:
        return False, reason_cap, None
    try:
        bal = debit(player_id, cost, SOURCES["ticket"], conn=conn)
    except InsufficientTimekeeperBalance as exc:
        return False, str(exc.args[0] if exc.args else "insufficient_timekeeper"), None
    now = float(time.time())
    wid = str(week["week_id"])
    conn.execute(
        """
        INSERT INTO space_lottery_tickets (week_id, player_id, ticket_count, spent_sec, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(week_id, player_id) DO UPDATE SET
            ticket_count = ticket_count + excluded.ticket_count,
            spent_sec = spent_sec + excluded.spent_sec,
            updated_at = excluded.updated_at;
        """,
        (wid, int(player_id), n, cost, now),
    )
    conn.execute(
        """
        UPDATE space_lottery_weeks
        SET pool_sec = pool_sec + ?, updated_at = ?
        WHERE week_id = ? AND status = ?;
        """,
        (cost, now, wid, WEEK_OPEN),
    )
    _record_wager(
        player_id,
        "ticket",
        -cost,
        balance_after=bal,
        ref_type="week",
        ref_id=wid,
        request_id=request_id,
        conn=conn,
    )
    return True, "ok", serialize_state(player_id, conn=conn)


def draw_week(week_id: str, *, conn) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Settle one week: pick winner proportional to tickets, credit pool."""
    if not schema_ready(conn):
        return False, "lottery_unavailable", None
    week = conn.execute(
        "SELECT * FROM space_lottery_weeks WHERE week_id = ? LIMIT 1;",
        (str(week_id),),
    ).fetchone()
    if not week:
        return False, "week_not_found", None
    week = dict(week)
    if str(week.get("status")) == WEEK_PAID:
        return True, "already_paid", week
    if str(week.get("status")) != WEEK_OPEN:
        return False, "week_not_open", None

    # Current ISO week: only after Sunday 20:00 UTC. Past weeks: always drawable.
    now = float(time.time())
    wid = str(week_id)
    if wid == current_week_id(now) and now < week_draw_at(wid):
        return False, "week_still_active", None

    tickets = conn.execute(
        """
        SELECT player_id, ticket_count FROM space_lottery_tickets
        WHERE week_id = ? AND ticket_count > 0
        ORDER BY player_id ASC;
        """,
        (wid,),
    ).fetchall()
    pool = int(week.get("pool_sec") or 0)
    if not tickets or pool <= 0:
        conn.execute(
            """
            UPDATE space_lottery_weeks
            SET status = ?, server_seed_hash = COALESCE(server_seed_hash, ?),
                server_seed = COALESCE(server_seed, ?), drawn_at = ?, updated_at = ?
            WHERE week_id = ?;
            """,
            (WEEK_PAID, hash_seed("empty"), "empty", now, now, wid),
        )
        return True, "empty_pool", dict(week)

    seed = gen_server_seed()
    seed_h = hash_seed(seed)
    weights: List[Tuple[int, int]] = [(int(r["player_id"]), int(r["ticket_count"])) for r in tickets]
    total_t = sum(w for _, w in weights)
    rng = seeded_rng(seed, "tombola", str(week_id), total_t)
    pick = rng.randrange(total_t)
    cursor = 0
    winner_id = weights[0][0]
    winner_t = weights[0][1]
    for pid, tc in weights:
        cursor += tc
        if pick < cursor:
            winner_id = pid
            winner_t = tc
            break

    bal = credit(winner_id, pool, SOURCES["tombola_prize"], conn=conn)
    _record_wager(
        winner_id,
        "tombola_prize",
        pool,
        balance_after=bal,
        ref_type="week",
        ref_id=str(week_id),
        request_id=None,
        conn=conn,
    )
    conn.execute(
        """
        UPDATE space_lottery_weeks
        SET status = ?, server_seed = ?, server_seed_hash = ?,
            winner_player_id = ?, winner_tickets = ?, drawn_at = ?, updated_at = ?
        WHERE week_id = ? AND status = ?;
        """,
        (WEEK_PAID, seed, seed_h, int(winner_id), int(winner_t), now, now, str(week_id), WEEK_OPEN),
    )
    week = conn.execute(
        "SELECT * FROM space_lottery_weeks WHERE week_id = ?;",
        (str(week_id),),
    ).fetchone()
    return True, "ok", dict(week) if week else None


def maybe_settle_due_weeks(*, conn) -> int:
    """Close open weeks whose Sunday 20:00 UTC draw window has passed (or past ISO weeks)."""
    if not schema_ready(conn):
        return 0
    rows = conn.execute(
        "SELECT week_id FROM space_lottery_weeks WHERE status = ?;",
        (WEEK_OPEN,),
    ).fetchall()
    n = 0
    for row in rows:
        ok, reason, _ = draw_week(str(row["week_id"]), conn=conn)
        if ok and reason in ("ok", "empty_pool", "already_paid"):
            n += 1
    return n


def start_mines(
    player_id: int,
    bet_sec: int,
    *,
    mine_count: int = MINES_DEFAULT_COUNT,
    conn,
    request_id: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not mode_enabled("mines"):
        return False, "mode_disabled", None
    if not schema_ready(conn):
        return False, "lottery_unavailable", None
    if _active_round(player_id, None, conn=conn):
        return False, "round_active", None
    if request_id:
        existing = _find_by_request(player_id, request_id, conn=conn)
        if existing:
            return True, "ok", serialize_state(player_id, conn=conn)

    bet, err = _clamp_bet(bet_sec)
    if err:
        return False, err, None
    mines = int(mine_count or MINES_DEFAULT_COUNT)
    if mines < MINES_MIN_COUNT or mines > MINES_MAX_COUNT:
        return False, "invalid_mine_count", None
    if mines >= MINES_GRID:
        return False, "invalid_mine_count", None

    ok_cap, reason_cap = _add_daily_wager(player_id, DAILY_WAGER_GAME_MINES, bet, conn=conn)
    if not ok_cap:
        return False, reason_cap, None
    try:
        bal = debit(player_id, bet, SOURCES["mines_bet"], conn=conn)
    except InsufficientTimekeeperBalance as exc:
        return False, str(exc.args[0] if exc.args else "insufficient_timekeeper"), None

    seed = gen_server_seed()
    seed_h = hash_seed(seed)
    now = float(time.time())
    # mine positions committed but hidden until settle
    # Use placeholder round id 0 for layout then rewrite — insert first then layout with real id.
    payload = {
        "grid": MINES_GRID,
        "mine_count": mines,
        "revealed": [],
        "mine_positions": [],  # filled after insert
    }
    cur = conn.execute(
        """
        INSERT INTO space_lottery_rounds
            (player_id, game, status, bet_sec, payout_sec, seed_hash, seed, payload_json, request_id, created_at)
        VALUES (?, 'mines', ?, ?, 0, ?, ?, ?, ?, ?);
        """,
        (
            int(player_id),
            ROUND_ACTIVE,
            int(bet),
            seed_h,
            seed,
            _json_dumps(payload),
            (str(request_id)[:80] if request_id else None),
            now,
        ),
    )
    rid = int(cur.lastrowid)
    positions = _layout_mines(seed, rid, mines, MINES_GRID)
    payload["mine_positions"] = positions
    conn.execute(
        "UPDATE space_lottery_rounds SET payload_json = ? WHERE id = ?;",
        (_json_dumps(payload), rid),
    )
    _record_wager(
        player_id,
        "mines_bet",
        -int(bet),
        balance_after=bal,
        ref_type="round",
        ref_id=str(rid),
        request_id=request_id,
        conn=conn,
    )
    return True, "ok", serialize_state(player_id, conn=conn)


def reveal_mines_cell(
    player_id: int,
    cell: int,
    *,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    row = _active_round(player_id, "mines", conn=conn)
    if not row:
        return False, "no_active_round", None
    payload = _json_loads(row.get("payload_json"), {}) or {}
    grid = int(payload.get("grid") or MINES_GRID)
    idx = int(cell)
    if idx < 0 or idx >= grid:
        return False, "invalid_cell", None
    revealed = list(payload.get("revealed") or [])
    if idx in revealed:
        return False, "already_revealed", None
    mines = set(int(x) for x in (payload.get("mine_positions") or []))
    if idx in mines:
        payload["revealed"] = revealed + [idx]
        payload["hit"] = idx
        now = float(time.time())
        conn.execute(
            """
            UPDATE space_lottery_rounds
            SET status = ?, payout_sec = 0, payload_json = ?, settled_at = ?
            WHERE id = ? AND status = ?;
            """,
            (ROUND_BUST, _json_dumps(payload), now, int(row["id"]), ROUND_ACTIVE),
        )
        return True, "bust", serialize_state(player_id, conn=conn)

    revealed.append(idx)
    payload["revealed"] = revealed
    conn.execute(
        "UPDATE space_lottery_rounds SET payload_json = ? WHERE id = ? AND status = ?;",
        (_json_dumps(payload), int(row["id"]), ROUND_ACTIVE),
    )
    # Auto-cashout if all safe cells revealed
    mine_count = int(payload.get("mine_count") or 0)
    if len(revealed) >= grid - mine_count:
        return cashout_mines(player_id, conn=conn)
    return True, "ok", serialize_state(player_id, conn=conn)


def cashout_mines(player_id: int, *, conn) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    row = _active_round(player_id, "mines", conn=conn)
    if not row:
        return False, "no_active_round", None
    payload = _json_loads(row.get("payload_json"), {}) or {}
    revealed = list(payload.get("revealed") or [])
    if not revealed:
        return False, "nothing_to_cashout", None
    mine_count = int(payload.get("mine_count") or MINES_DEFAULT_COUNT)
    grid = int(payload.get("grid") or MINES_GRID)
    mult = mines_multiplier(len(revealed), mine_count, grid)
    payout = int(round(int(row["bet_sec"]) * mult))
    payout = max(0, payout)
    bal = credit(player_id, payout, SOURCES["mines_win"], conn=conn) if payout > 0 else get_balance(player_id, conn=conn)
    now = float(time.time())
    conn.execute(
        """
        UPDATE space_lottery_rounds
        SET status = ?, payout_sec = ?, payload_json = ?, settled_at = ?
        WHERE id = ? AND status = ?;
        """,
        (ROUND_CASHED, payout, _json_dumps(payload), now, int(row["id"]), ROUND_ACTIVE),
    )
    _record_wager(
        player_id,
        "mines_win",
        payout,
        balance_after=bal,
        ref_type="round",
        ref_id=str(row["id"]),
        request_id=None,
        conn=conn,
    )
    return True, "ok", serialize_state(player_id, conn=conn)


def start_crash(
    player_id: int,
    bet_sec: int,
    *,
    conn,
    request_id: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not mode_enabled("crash"):
        return False, "mode_disabled", None
    if not schema_ready(conn):
        return False, "lottery_unavailable", None
    if _active_round(player_id, None, conn=conn):
        return False, "round_active", None
    if request_id:
        existing = _find_by_request(player_id, request_id, conn=conn)
        if existing:
            return True, "ok", serialize_state(player_id, conn=conn)

    bet, err = _clamp_bet(bet_sec)
    if err:
        return False, err, None
    ok_cap, reason_cap = _add_daily_wager(player_id, DAILY_WAGER_GAME_CRASH, bet, conn=conn)
    if not ok_cap:
        return False, reason_cap, None
    try:
        bal = debit(player_id, bet, SOURCES["crash_bet"], conn=conn)
    except InsufficientTimekeeperBalance as exc:
        return False, str(exc.args[0] if exc.args else "insufficient_timekeeper"), None

    seed = gen_server_seed()
    seed_h = hash_seed(seed)
    now = float(time.time())
    payload = {"crash_point": None, "cashout_mult": None}
    cur = conn.execute(
        """
        INSERT INTO space_lottery_rounds
            (player_id, game, status, bet_sec, payout_sec, seed_hash, seed, payload_json, request_id, created_at)
        VALUES (?, 'crash', ?, ?, 0, ?, ?, ?, ?, ?);
        """,
        (
            int(player_id),
            ROUND_ACTIVE,
            int(bet),
            seed_h,
            seed,
            _json_dumps(payload),
            (str(request_id)[:80] if request_id else None),
            now,
        ),
    )
    rid = int(cur.lastrowid)
    point = crash_point_from_seed(seed, rid)
    payload["crash_point"] = point
    conn.execute(
        "UPDATE space_lottery_rounds SET payload_json = ? WHERE id = ?;",
        (_json_dumps(payload), rid),
    )
    _record_wager(
        player_id,
        "crash_bet",
        -int(bet),
        balance_after=bal,
        ref_type="round",
        ref_id=str(rid),
        request_id=request_id,
        conn=conn,
    )
    return True, "ok", serialize_state(player_id, conn=conn)


def cashout_crash(
    player_id: int,
    multiplier: float,
    *,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    row = _active_round(player_id, "crash", conn=conn)
    if not row:
        return False, "no_active_round", None
    payload = _json_loads(row.get("payload_json"), {}) or {}
    crash_at = float(payload.get("crash_point") or 0)
    now = float(time.time())
    # Seed can land on 1.00 — classic instant bust, not an invalid round.
    if crash_at < 1.01:
        payload["cashout_mult"] = float(multiplier) if multiplier is not None else crash_at
        payload["bust"] = True
        payload["elapsed_ms"] = max(0.0, (now - float(row.get("created_at") or now)) * 1000.0)
        conn.execute(
            """
            UPDATE space_lottery_rounds
            SET status = ?, payout_sec = 0, payload_json = ?, settled_at = ?
            WHERE id = ? AND status = ?;
            """,
            (ROUND_BUST, _json_dumps(payload), now, int(row["id"]), ROUND_ACTIVE),
        )
        return True, "bust", serialize_state(player_id, conn=conn)

    created = float(row.get("created_at") or now)
    elapsed_ms = max(0.0, (now - created) * 1000.0)
    # Align with visible climb: client RAF starts after start HTTP round-trip.
    effective_ms = max(0.0, elapsed_ms - float(CRASH_START_LAG_MS))
    bust_ms = float(crash_bust_after_ms(crash_at))
    # Server SoT: payout from effective progress — ignore inflated client display.
    if effective_ms >= bust_ms:
        payload["cashout_mult"] = float(multiplier) if multiplier is not None else crash_at
        payload["bust"] = True
        payload["elapsed_ms"] = elapsed_ms
        payload["effective_ms"] = effective_ms
        conn.execute(
            """
            UPDATE space_lottery_rounds
            SET status = ?, payout_sec = 0, payload_json = ?, settled_at = ?
            WHERE id = ? AND status = ?;
            """,
            (ROUND_BUST, _json_dumps(payload), now, int(row["id"]), ROUND_ACTIVE),
        )
        return True, "bust", serialize_state(player_id, conn=conn)

    t = effective_ms / bust_ms if bust_ms > 0 else 0.0
    mult = crash_mult_at_progress(crash_at, t)
    # Client may send a lower request; never pay above fair progress or crash point.
    try:
        client_mult = float(multiplier)
    except (TypeError, ValueError):
        client_mult = mult
    client_mult = math.floor(max(0.0, client_mult) * 100.0) / 100.0
    if client_mult >= 1.01:
        mult = min(mult, client_mult)
    if mult < 1.01:
        return False, "multiplier_too_low", None
    if mult >= crash_at:
        payload["cashout_mult"] = mult
        payload["bust"] = True
        payload["elapsed_ms"] = elapsed_ms
        payload["effective_ms"] = effective_ms
        conn.execute(
            """
            UPDATE space_lottery_rounds
            SET status = ?, payout_sec = 0, payload_json = ?, settled_at = ?
            WHERE id = ? AND status = ?;
            """,
            (ROUND_BUST, _json_dumps(payload), now, int(row["id"]), ROUND_ACTIVE),
        )
        return True, "bust", serialize_state(player_id, conn=conn)

    payout = int(round(int(row["bet_sec"]) * mult))
    payload["cashout_mult"] = mult
    payload["elapsed_ms"] = elapsed_ms
    payload["effective_ms"] = effective_ms
    bal = credit(player_id, payout, SOURCES["crash_win"], conn=conn) if payout > 0 else get_balance(player_id, conn=conn)
    conn.execute(
        """
        UPDATE space_lottery_rounds
        SET status = ?, payout_sec = ?, payload_json = ?, settled_at = ?
        WHERE id = ? AND status = ?;
        """,
        (ROUND_CASHED, payout, _json_dumps(payload), now, int(row["id"]), ROUND_ACTIVE),
    )
    _record_wager(
        player_id,
        "crash_win",
        payout,
        balance_after=bal,
        ref_type="round",
        ref_id=str(row["id"]),
        request_id=None,
        conn=conn,
    )
    return True, "ok", serialize_state(player_id, conn=conn)


def bust_crash(player_id: int, *, conn) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Client reports animation reached crash without cashout — settle as bust."""
    row = _active_round(player_id, "crash", conn=conn)
    if not row:
        return False, "no_active_round", None
    payload = _json_loads(row.get("payload_json"), {}) or {}
    payload["bust"] = True
    now = float(time.time())
    conn.execute(
        """
        UPDATE space_lottery_rounds
        SET status = ?, payout_sec = 0, payload_json = ?, settled_at = ?
        WHERE id = ? AND status = ?;
        """,
        (ROUND_BUST, _json_dumps(payload), now, int(row["id"]), ROUND_ACTIVE),
    )
    return True, "bust", serialize_state(player_id, conn=conn)


def verify_round(round_id: int, *, conn) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    row = conn.execute(
        "SELECT * FROM space_lottery_rounds WHERE id = ? LIMIT 1;",
        (int(round_id),),
    ).fetchone()
    if not row:
        return False, "round_not_found", None
    row = dict(row)
    if str(row.get("status")) == ROUND_ACTIVE:
        return False, "round_not_settled", None
    seed = str(row.get("seed") or "")
    if hash_seed(seed) != str(row.get("seed_hash") or ""):
        return False, "seed_mismatch", None
    payload = _json_loads(row.get("payload_json"), {}) or {}
    game = str(row.get("game") or "")
    result: Dict[str, Any] = {
        "round_id": int(row["id"]),
        "game": game,
        "seed": seed,
        "seed_hash": row.get("seed_hash"),
        "ok": True,
    }
    if game == "mines":
        expected = _layout_mines(seed, int(row["id"]), int(payload.get("mine_count") or 0), int(payload.get("grid") or MINES_GRID))
        actual = sorted(int(x) for x in (payload.get("mine_positions") or []))
        result["mine_positions"] = expected
        result["matches"] = expected == actual
        if not result["matches"]:
            return False, "layout_mismatch", result
    elif game == "crash":
        expected = crash_point_from_seed(seed, int(row["id"]))
        actual = float(payload.get("crash_point") or 0)
        result["crash_point"] = expected
        result["matches"] = abs(expected - actual) < 1e-9
        if not result["matches"]:
            return False, "crash_mismatch", result
    return True, "ok", result
