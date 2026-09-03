"""
GC-TIMEKEEPER-001 — Imperium time account (single owner).

Time is empire-wide, credited from legacy time items / rewards, debited only via
explicit apply (never automatic). Production % boosters stay in inventory_boosters.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import lock_planet_for_update, table_exists
from .inventory_catalog import BOOSTER_QUEUE_TARGET, BOOSTER_TIME_SECONDS

DEPOSIT_DOMAINS = frozenset({"build", "research", "shipyard"})
DEPOSIT_DOMAIN_ALL = "all"

TIMEKEEPER_DOMAINS = frozenset(
    {
        "build",
        "research",
        "shipyard",
        "defense",
        "troops",
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
    cur = conn.cursor()
    cur.execute(
        "SELECT balance_sec FROM timekeeper_balances WHERE player_id = ? LIMIT 1;",
        (int(player_id),),
    )
    row = cur.fetchone()
    return int(row["balance_sec"] or 0) if row else 0


def format_balance_label(balance_sec: int) -> str:
    from .time_format import format_duration_human

    sec = max(0, int(balance_sec or 0))
    if sec <= 0:
        return "0min"
    # TK HUD: prefer compact h/min (skip calendar units for typical balances).
    return format_duration_human(
        sec,
        max_parts=2,
        units=(("h", 3600), ("min", 60), ("s", 1)),
    )


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


def normalize_deposit_domain(domain: str) -> Optional[str]:
    raw = str(domain or "").strip().lower()
    if raw == DEPOSIT_DOMAIN_ALL:
        return DEPOSIT_DOMAIN_ALL
    dom = str(DOMAIN_ALIASES.get(raw, raw) or "")
    if dom in DEPOSIT_DOMAINS:
        return dom
    return None


def deposit_legacy_domain(
    player_id: int,
    domain: str,
    *,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Deposit all owned legacy time boosters for one queue domain into Timekeeper.

    One-click inventory chips (Bau / Forschung / Werft / Alle) call this so +N means
    all N items, not a single SKU use. Domain ``all`` deposits every depositable
    booster SKU into the shared balance.
    """
    from game.inventory import consume_inventory_item, inventory_amount, inventory_schema_ready

    dom = normalize_deposit_domain(domain)
    if not dom:
        return False, "invalid_domain", None
    deposit_all = dom == DEPOSIT_DOMAIN_ALL
    if not schema_ready(conn):
        return False, "timekeeper_unavailable", None
    if not inventory_schema_ready(conn):
        return False, "inventory_unavailable", None

    uid = int(player_id)
    consumed_items: List[Dict[str, Any]] = []
    total_seconds = 0
    total_consumed = 0

    for key, unit_seconds in BOOSTER_TIME_SECONDS.items():
        item_dom = str(BOOSTER_QUEUE_TARGET.get(key) or "")
        if not deposit_all and item_dom != dom:
            continue
        if deposit_all and item_dom not in DEPOSIT_DOMAINS:
            continue
        owned = int(inventory_amount(uid, key, conn=conn) or 0)
        if owned <= 0:
            continue
        credit_sec = int(owned) * int(unit_seconds)
        if not consume_inventory_item(uid, key, owned, conn=conn):
            continue
        credit(uid, credit_sec, f"deposit:{dom}:{key}", conn=conn)
        total_seconds += credit_sec
        total_consumed += owned
        consumed_items.append(
            {
                "item_key": key,
                "amount": owned,
                "seconds_credited": credit_sec,
            }
        )

    if total_seconds <= 0 or total_consumed <= 0:
        return False, "no_depositable_items", None

    new_bal = get_balance(uid, conn=conn)
    effect = {
        "kind": "timekeeper_credit",
        "domain": dom,
        "seconds_credited": total_seconds,
        "balance_sec": new_bal,
        "label": format_balance_label(new_bal),
        "items": consumed_items,
        "count": total_consumed,
    }
    return True, "timekeeper_deposit_ok", {
        "item_key": f"timekeeper_deposit:{dom}",
        "consumed": total_consumed,
        "effects": [effect],
        "effect": effect,
    }


def _row_field(row: Any, key: str) -> Any:
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _active_head_remaining_seconds(rows: List[Any], *, now: float, finish_col: str) -> float:
    """Timekeeper applies only against the active head job — not the full queue tail."""
    if not rows:
        return 0.0
    first_finish = float(_row_field(rows[0], finish_col) or 0)
    if first_finish <= 0:
        return 0.0
    return max(0.0, first_finish - now)


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


def _finish_before_apply(conn, user_id: int, planet_id: Optional[int]) -> Dict[str, Any]:
    from .inventory_use import _finish_inventory_due_work

    uid = int(user_id)
    if planet_id is not None:
        result = _finish_inventory_due_work(
            conn, uid, planet_id=int(planet_id), source="timekeeper_apply"
        )
    else:
        result = _finish_inventory_due_work(conn, uid, source="timekeeper_apply")
    return dict(result or {"ok": True, "errors": []})


def _tk_savepoint_begin(conn) -> None:
    conn.execute("SAVEPOINT gc_tk_apply")


def _tk_savepoint_release(conn) -> None:
    conn.execute("RELEASE SAVEPOINT gc_tk_apply")


def _tk_savepoint_rollback(conn) -> None:
    conn.execute("ROLLBACK TO SAVEPOINT gc_tk_apply")
    conn.execute("RELEASE SAVEPOINT gc_tk_apply")


def _apply_domain_shift(
    domain: str,
    user_id: int,
    planet_id: int,
    boost_seconds: int,
    *,
    conn,
    now: float,
    rows: Optional[List[Mapping[str, Any]]] = None,
    finish_col_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    from .inventory_use import (
        apply_active_head_queue_time_boost,
        _finish_inventory_due_work,
    )

    uid = int(user_id)
    pid = int(planet_id)
    boost = max(0, int(boost_seconds))
    if boost <= 0:
        return None

    dom = str(domain or "").strip().lower()
    table_cfg = {
        "build": ("build_queue", "id", "start_time", "finish_time", "build"),
        "research": ("research_queue", "id", "start_at", "finish_at", "research"),
        "shipyard": ("shipyard_queue", "id", "started_at", "finish_at", "shipyard"),
        "defense": ("defense_queue", "id", "started_at", "finish_at", "defense"),
        "troops": ("troop_queue", "id", "started_at", "finish_at", "troops"),
        "planet_research": ("planet_research_queue", "id", "start_at", "finish_at", "planet_research"),
        "ascension": ("planet_ascension_queue", "id", "start_at", "finish_at", "ascension"),
    }
    cfg = table_cfg.get(dom)
    if not cfg:
        return None

    table, id_col, start_col, finish_col, target = cfg
    if dom == "shipyard":
        from .shipyard_queue import shipyard_queue_table_ready

        if not shipyard_queue_table_ready(conn):
            return None
    if dom == "defense":
        from .defense import defense_queue_table_ready

        if not defense_queue_table_ready(conn):
            return None
    if dom == "troops":
        from .troops import troop_queue_table_ready

        if not troop_queue_table_ready(conn):
            return None

    # GC-PERF-TK-005: apply_timekeeper already finished due work and loaded/synced
    # the canonical queue. Reuse that exact snapshot instead of repeating the
    # domain loader (and shipyard/defense/troops queue sync) inside the shift.
    if rows is None:
        if dom in ("planet_research", "ascension"):
            _finish_inventory_due_work(conn, uid, planet_id=pid, source="timekeeper_apply")
        loaded_rows, loaded_finish_col = _load_domain_rows(dom, uid, pid, conn=conn, now=now)
        rows = loaded_rows
        finish_col = finish_col_override or loaded_finish_col or finish_col
    else:
        finish_col = finish_col_override or finish_col

    if not rows:
        return None

    return apply_active_head_queue_time_boost(
        conn,
        rows=rows,
        boost_seconds=boost,
        now=now,
        table=table,
        id_col=id_col,
        start_col=start_col,
        finish_col=finish_col,
        target=target,
    )


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
        from .shipyard import get_shipyard_level
        from .shipyard_queue import (
            list_shipyard_queue_rows,
            shipyard_queue_table_ready,
            sync_shipyard_queue_finish_times,
        )

        if not shipyard_queue_table_ready(conn):
            return [], "finish_at"
        sy_level = get_shipyard_level(uid, pid, conn=conn)
        sync_shipyard_queue_finish_times(pid, int(sy_level), conn=conn, now=float(now))
        return list(list_shipyard_queue_rows(pid, conn=conn)), "finish_at"
    if dom == "defense":
        from .defense import (
            defense_queue_table_ready,
            list_defense_queue_rows,
            sync_defense_queue_finish_times,
        )

        if not defense_queue_table_ready(conn):
            return [], "finish_at"
        sync_defense_queue_finish_times(pid, conn=conn, now=float(now))
        return list(list_defense_queue_rows(pid, conn=conn)), "finish_at"
    if dom == "troops":
        from .troops import (
            list_troop_queue_rows,
            sync_troop_queue_finish_times,
            troop_queue_table_ready,
        )

        if not troop_queue_table_ready(conn):
            return [], "finish_at"
        sync_troop_queue_finish_times(pid, conn=conn, now=float(now))
        return list(list_troop_queue_rows(pid, conn=conn)), "finish_at"
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
    if dom in ("build", "shipyard", "defense", "troops", "planet_research", "ascension"):
        if planet_id is None:
            return False, "planet_required", {}
        pid = int(planet_id)
    else:
        pid = int(planet_id) if planet_id is not None else 0

    # GC-TK-ATOMIC-DELIVERY-001: every planet-scoped TK mutation takes the
    # canonical planet lock before touching queue rows. Shipyard/worker actions
    # use the same lock, so the background worker can SKIP LOCKED instead of
    # racing a boost and timing out later on queue/inventory rows.
    if pid > 0:
        lock_planet_for_update(conn, pid)

    balance = get_balance(uid, conn=conn)
    if balance <= 0:
        return False, "insufficient_timekeeper", {"timekeeper": serialize_for_client(uid, conn=conn)}

    now = float(time.time())
    pre_finish = _finish_before_apply(conn, uid, pid if pid > 0 else None)
    if pre_finish.get("ok") is False:
        return False, "queue_finish_failed", {
            "errors": list(pre_finish.get("errors") or [])[:5],
            "timekeeper": serialize_for_client(uid, conn=conn),
        }
    rows, finish_col = _load_domain_rows(dom, uid, pid, conn=conn, now=now)
    if not rows:
        return False, "no_queue", {"timekeeper": serialize_for_client(uid, conn=conn)}

    head_id_before = _row_field(rows[0], "id")
    remaining = _active_head_remaining_seconds(rows, now=now, finish_col=finish_col)
    boost_seconds = _resolve_apply_seconds(
        balance=balance,
        remaining=remaining,
        mode=mode,
        requested_seconds=seconds,
    )
    if boost_seconds <= 0:
        return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

    # Queue shift, resulting due delivery, and TK debit form one savepoint.
    # Even if the outer caller later commits after a handled failure, the player
    # can never receive a free shift or lose TK without the authoritative finish.
    _tk_savepoint_begin(conn)
    try:
        effect = _apply_domain_shift(
            dom,
            uid,
            pid,
            boost_seconds,
            conn=conn,
            now=now,
            rows=rows,
            finish_col_override=finish_col,
        )

        if not effect:
            _tk_savepoint_rollback(conn)
            return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

        shifted = int(effect.get("seconds_shifted") or 0)
        if shifted <= 0:
            _tk_savepoint_rollback(conn)
            return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

        post_finish = _finish_before_apply(conn, uid, pid if pid > 0 else None)
        if post_finish.get("ok") is False:
            _tk_savepoint_rollback(conn)
            return False, "queue_finish_failed", {
                "errors": list(post_finish.get("errors") or [])[:5],
                "timekeeper": serialize_for_client(uid, conn=conn),
            }

        try:
            new_bal = debit(uid, shifted, f"apply:{dom}", conn=conn)
        except InsufficientTimekeeperBalance:
            _tk_savepoint_rollback(conn)
            return False, "insufficient_timekeeper", {
                "timekeeper": serialize_for_client(uid, conn=conn)
            }

        # GC-TK-PANEL-REFRESH-001: detect real head completion (not rem/shift rounding).
        now_after = float(time.time())
        rows_after, _ = _load_domain_rows(dom, uid, pid, conn=conn, now=now_after)
        head_id_after = _row_field(rows_after[0], "id") if rows_after else None
        jobs_finished = head_id_before is not None and head_id_before != head_id_after
        _tk_savepoint_release(conn)
    except Exception:
        try:
            _tk_savepoint_rollback(conn)
        except Exception:
            pass
        raise

    return True, "ok", {
        "timekeeper": serialize_for_client(uid, conn=conn),
        "domain": dom,
        "seconds_applied": shifted,
        "seconds_requested": boost_seconds,
        "mode": str(mode or "partial"),
        "jobs_finished": bool(jobs_finished),
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
