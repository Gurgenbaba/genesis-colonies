"""
GC-TIMEKEEPER-001 — Imperium time account (single owner).

Time is empire-wide, credited from legacy time items / rewards, debited only via
explicit apply (never automatic). Production % boosters stay in inventory_boosters.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import table_exists
from .inventory_catalog import BOOSTER_TIME_SECONDS

TIMEKEEPER_DOMAINS = frozenset(
    {
        "build",
        "research",
        "shipyard",
        "defense",
        "planet_research",
        "ascension",
    }
)

DOMAIN_ALIASES = {
    "building": "build",
    "buildings": "build",
    "pe_research": "planet_research",
    "planet_evolution": "planet_research",
}

APPLY_MODES = frozenset({"partial", "max", "finish"})


class InsufficientTimekeeperBalance(Exception):
    pass


def schema_ready(conn) -> bool:
    return table_exists(conn, "timekeeper_balances")


def _ensure_balance_row(player_id: int, *, conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO timekeeper_balances (player_id, balance_sec, updated_at)
        VALUES (?, 0, ?);
        """,
        (int(player_id), float(time.time())),
    )


def get_balance(player_id: int, *, conn) -> int:
    if not schema_ready(conn):
        return 0
    _ensure_balance_row(int(player_id), conn=conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT balance_sec FROM timekeeper_balances WHERE player_id = ? LIMIT 1;",
        (int(player_id),),
    )
    row = cur.fetchone()
    return int(row["balance_sec"] or 0) if row else 0


def format_balance_label(balance_sec: int) -> str:
    sec = max(0, int(balance_sec or 0))
    if sec <= 0:
        return "0min"
    hours, rem = divmod(sec, 3600)
    minutes = rem // 60
    if hours > 0 and minutes > 0:
        return f"{hours}h {minutes}min"
    if hours > 0:
        return f"{hours}h"
    if minutes > 0:
        return f"{minutes}min"
    return f"{sec}s"


def serialize_for_client(player_id: int, *, conn) -> Dict[str, Any]:
    balance = get_balance(int(player_id), conn=conn)
    return {
        "ready": schema_ready(conn),
        "balance_sec": balance,
        "label": format_balance_label(balance),
    }


def _record_transaction(
    player_id: int,
    delta_sec: int,
    balance_after: int,
    source: str,
    *,
    conn,
) -> None:
    if not table_exists(conn, "timekeeper_transactions"):
        return
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO timekeeper_transactions (player_id, delta_sec, balance_after, source, created_at)
        VALUES (?, ?, ?, ?, ?);
        """,
        (int(player_id), int(delta_sec), int(balance_after), str(source or "system")[:120], float(time.time())),
    )


def credit(
    player_id: int,
    seconds: int,
    source: str,
    *,
    conn,
) -> int:
    if not schema_ready(conn):
        return 0
    amt = max(0, int(seconds or 0))
    if amt <= 0:
        return get_balance(int(player_id), conn=conn)
    uid = int(player_id)
    _ensure_balance_row(uid, conn=conn)
    now = float(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE timekeeper_balances
        SET balance_sec = balance_sec + ?, updated_at = ?
        WHERE player_id = ?;
        """,
        (amt, now, uid),
    )
    new_bal = get_balance(uid, conn=conn)
    _record_transaction(uid, amt, new_bal, str(source or "credit"), conn=conn)
    return new_bal


def debit(
    player_id: int,
    seconds: int,
    source: str,
    *,
    conn,
) -> int:
    if not schema_ready(conn):
        raise InsufficientTimekeeperBalance("timekeeper_unavailable")
    amt = max(0, int(seconds or 0))
    if amt <= 0:
        return get_balance(int(player_id), conn=conn)
    uid = int(player_id)
    balance = get_balance(uid, conn=conn)
    if balance < amt:
        raise InsufficientTimekeeperBalance("insufficient_timekeeper")
    now = float(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE timekeeper_balances
        SET balance_sec = balance_sec - ?, updated_at = ?
        WHERE player_id = ? AND balance_sec >= ?;
        """,
        (amt, now, uid, amt),
    )
    if int(cur.rowcount or 0) <= 0:
        raise InsufficientTimekeeperBalance("insufficient_timekeeper")
    new_bal = get_balance(uid, conn=conn)
    _record_transaction(uid, -amt, new_bal, str(source or "debit"), conn=conn)
    return new_bal


def credit_from_booster_item(player_id: int, item_key: str, *, conn) -> Optional[Dict[str, Any]]:
    key = str(item_key or "")
    seconds = int(BOOSTER_TIME_SECONDS.get(key) or 0)
    if seconds <= 0:
        return None
    new_bal = credit(int(player_id), seconds, f"item:{key}", conn=conn)
    return {
        "kind": "timekeeper_credit",
        "item_key": key,
        "seconds_credited": seconds,
        "balance_sec": new_bal,
        "label": format_balance_label(new_bal),
    }


def is_legacy_time_booster_item(item_key: str) -> bool:
    return str(item_key or "") in BOOSTER_TIME_SECONDS


def _row_field(row: Any, key: str) -> Any:
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _queue_remaining_seconds(rows: List[Any], *, now: float, finish_col: str) -> float:
    if not rows:
        return 0.0
    last_finish = float(_row_field(rows[-1], finish_col) or 0)
    first_finish = float(_row_field(rows[0], finish_col) or 0)
    remaining = max(0.0, last_finish - now)
    if remaining <= 0 and first_finish > now:
        remaining = max(0.0, first_finish - now)
    return remaining


def _resolve_apply_seconds(
    *,
    balance: int,
    remaining: float,
    mode: str,
    requested_seconds: Optional[int],
) -> int:
    m = str(mode or "partial").strip().lower()
    if m not in APPLY_MODES:
        m = "partial"
    rem = max(0, int(round(remaining)))
    bal = max(0, int(balance))
    if rem <= 0 or bal <= 0:
        return 0
    if m == "finish":
        return min(bal, rem)
    if m == "max":
        return min(bal, rem)
    req = max(0, int(requested_seconds or 0))
    if req <= 0:
        return 0
    return min(bal, rem, req)


def _finish_before_apply(conn, user_id: int, planet_id: Optional[int]) -> None:
    from .inventory_use import _finish_inventory_due_work

    uid = int(user_id)
    if planet_id is not None:
        _finish_inventory_due_work(conn, uid, planet_id=int(planet_id), source="timekeeper_apply")
    else:
        _finish_inventory_due_work(conn, uid, source="timekeeper_apply")


def _apply_domain_shift(
    domain: str,
    user_id: int,
    planet_id: int,
    boost_seconds: int,
    *,
    conn,
    now: float,
) -> Optional[Dict[str, Any]]:
    from .inventory_use import (
        apply_build_queue_booster,
        apply_research_queue_booster,
        apply_shipyard_queue_booster,
        _apply_full_queue_time_shift,
        _finish_inventory_due_work,
    )

    uid = int(user_id)
    pid = int(planet_id)
    boost = max(0, int(boost_seconds))
    if boost <= 0:
        return None

    dom = str(domain or "").strip().lower()
    if dom == "build":
        return apply_build_queue_booster(conn, uid, pid, boost, now=now)
    if dom == "research":
        return apply_research_queue_booster(conn, uid, boost, now=now)
    if dom == "shipyard":
        return apply_shipyard_queue_booster(conn, uid, pid, boost, now=now)

    if dom == "defense":
        from .defense import defense_queue_table_ready, list_defense_queue_rows

        if not defense_queue_table_ready(conn):
            return None
        _finish_inventory_due_work(conn, uid, planet_id=pid, source="timekeeper_apply")
        rows = list(list_defense_queue_rows(pid, conn=conn))
        return _apply_full_queue_time_shift(
            conn,
            rows=rows,
            boost_seconds=boost,
            now=now,
            table="defense_queue",
            id_col="id",
            start_col="started_at",
            finish_col="finish_at",
            target="defense",
        )

    if dom == "planet_research":
        from .planet_evolution.repository import get_planet_research_queue

        _finish_inventory_due_work(conn, uid, planet_id=pid, source="timekeeper_apply")
        rows = list(get_planet_research_queue(pid, conn=conn))
        return _apply_full_queue_time_shift(
            conn,
            rows=rows,
            boost_seconds=boost,
            now=now,
            table="planet_research_queue",
            id_col="id",
            start_col="start_at",
            finish_col="finish_at",
            target="planet_research",
        )

    if dom == "ascension":
        from .planet_evolution.ascension import _get_planet_ascension_queue_row

        _finish_inventory_due_work(conn, uid, planet_id=pid, source="timekeeper_apply")
        row = _get_planet_ascension_queue_row(pid, conn=conn)
        rows = [row] if row else []
        return _apply_full_queue_time_shift(
            conn,
            rows=rows,
            boost_seconds=boost,
            now=now,
            table="planet_ascension_queue",
            id_col="id",
            start_col="start_at",
            finish_col="finish_at",
            target="ascension",
        )

    return None


def _load_domain_rows(domain: str, user_id: int, planet_id: int, *, conn, now: float) -> Tuple[List[Mapping[str, Any]], str]:
    dom = str(domain or "").strip().lower()
    uid = int(user_id)
    pid = int(planet_id)

    if dom == "build":
        from .models import get_build_queue_rows

        return list(get_build_queue_rows(pid, conn=conn)), "finish_time"
    if dom == "research":
        from .models import get_research_queue_rows

        return list(get_research_queue_rows(uid, conn=conn)), "finish_at"
    if dom == "shipyard":
        from .shipyard_queue import list_shipyard_queue_rows, shipyard_queue_table_ready

        if not shipyard_queue_table_ready(conn):
            return [], "finish_at"
        return list(list_shipyard_queue_rows(pid, conn=conn)), "finish_at"
    if dom == "defense":
        from .defense import defense_queue_table_ready, list_defense_queue_rows

        if not defense_queue_table_ready(conn):
            return [], "finish_at"
        return list(list_defense_queue_rows(pid, conn=conn)), "finish_at"
    if dom == "planet_research":
        from .planet_evolution.repository import get_planet_research_queue

        return list(get_planet_research_queue(pid, conn=conn)), "finish_at"
    if dom == "ascension":
        from .planet_evolution.ascension import _get_planet_ascension_queue_row

        row = _get_planet_ascension_queue_row(pid, conn=conn)
        return ([row] if row else []), "finish_at"
    return [], "finish_at"


def apply_timekeeper(
    player_id: int,
    domain: str,
    *,
    planet_id: Optional[int] = None,
    seconds: Optional[int] = None,
    mode: str = "partial",
    conn,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not schema_ready(conn):
        return False, "timekeeper_unavailable", {}

    dom = str(domain or "").strip().lower()
    dom = DOMAIN_ALIASES.get(dom, dom)
    if dom not in TIMEKEEPER_DOMAINS:
        return False, "invalid_domain", {}

    uid = int(player_id)
    if dom in ("build", "shipyard", "defense", "planet_research", "ascension"):
        if planet_id is None:
            return False, "planet_required", {}
        pid = int(planet_id)
    else:
        pid = int(planet_id) if planet_id is not None else 0

    balance = get_balance(uid, conn=conn)
    if balance <= 0:
        return False, "insufficient_timekeeper", {"timekeeper": serialize_for_client(uid, conn=conn)}

    now = float(time.time())
    _finish_before_apply(conn, uid, pid if pid > 0 else None)
    rows, finish_col = _load_domain_rows(dom, uid, pid, conn=conn, now=now)
    if not rows:
        return False, "no_queue", {"timekeeper": serialize_for_client(uid, conn=conn)}

    remaining = _queue_remaining_seconds(rows, now=now, finish_col=finish_col)
    boost_seconds = _resolve_apply_seconds(
        balance=balance,
        remaining=remaining,
        mode=mode,
        requested_seconds=seconds,
    )
    if boost_seconds <= 0:
        return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

    if dom == "research":
        effect = _apply_domain_shift(dom, uid, pid, boost_seconds, conn=conn, now=now)
    else:
        effect = _apply_domain_shift(dom, uid, pid, boost_seconds, conn=conn, now=now)

    if not effect:
        return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

    shifted = int(effect.get("seconds_shifted") or 0)
    if shifted <= 0:
        return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

    try:
        new_bal = debit(uid, shifted, f"apply:{dom}", conn=conn)
    except InsufficientTimekeeperBalance:
        return False, "insufficient_timekeeper", {"timekeeper": serialize_for_client(uid, conn=conn)}

    _finish_before_apply(conn, uid, pid if pid > 0 else None)

    return True, "ok", {
        "timekeeper": serialize_for_client(uid, conn=conn),
        "domain": dom,
        "seconds_applied": shifted,
        "seconds_requested": boost_seconds,
        "mode": str(mode or "partial"),
    }


def recent_transactions(player_id: int, *, conn, limit: int = 12) -> List[Dict[str, Any]]:
    if not table_exists(conn, "timekeeper_transactions"):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT delta_sec, balance_after, source, created_at
        FROM timekeeper_transactions
        WHERE player_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?;
        """,
        (int(player_id), max(1, min(int(limit), 50))),
    )
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        delta = int(row["delta_sec"] or 0)
        out.append(
            {
                "delta_sec": delta,
                "delta_label": format_balance_label(abs(delta)),
                "balance_after": int(row["balance_after"] or 0),
                "source": str(row["source"] or ""),
                "created_at": float(row["created_at"] or 0),
            }
        )
    return out
