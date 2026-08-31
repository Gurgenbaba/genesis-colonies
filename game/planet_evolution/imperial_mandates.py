"""Imperial Mandates — late-game colony capacity beyond Ark slots 1–6.

See docs/IMPERIAL_MANDATES.md. Merge point: expansion_protocol.expansion_gameplay_cap.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import sqlite3

from ..db import column_exists, table_exists
from ..models import get_homeworld, get_planets_by_player
from .expansion_gates import get_homeworld_level

ARK_SLOT_MAX = 6
LATE_SLOT_MAX = 4

MANDATE_ORDER: Tuple[str, ...] = ("survey", "presence", "directive", "apex")

SURVEY_EXPEDITIONS_REQUIRED = 12
PRESENCE_SYSTEMS_REQUIRED = 3

MANDATE_LABEL_KEYS: Dict[str, str] = {
    "survey": "imperial_mandate_survey",
    "presence": "imperial_mandate_presence",
    "directive": "imperial_mandate_directive",
    "apex": "imperial_mandate_apex",
}


def legacy_expansion_slots_unlocked(homeworld_level: int) -> int:
    """Pre-mandate formula including +5 HW extrapolation (migration snapshot only)."""
    from .expansion_protocol import EXPANSION_SLOT_GATES

    hw = max(0, int(homeworld_level or 0))
    unlocked = 0
    for gate in EXPANSION_SLOT_GATES:
        if hw >= int(gate["homeworld_level"]):
            unlocked = int(gate["expansion_index"])
    last = EXPANSION_SLOT_GATES[-1]
    if hw >= int(last["homeworld_level"]):
        extra = (hw - int(last["homeworld_level"])) // 5
        unlocked = int(last["expansion_index"]) + extra
    return unlocked


def _column_ready(conn: sqlite3.Connection, table: str, column: str) -> bool:
    # Owner: game.db.column_exists (PG-safe). Never PRAGMA/sqlite_master on Postgres.
    try:
        return column_exists(conn, table, column)
    except Exception:
        return False


def _table_ready(conn: sqlite3.Connection, table: str) -> bool:
    try:
        return table_exists(conn, table)
    except Exception:
        return False


def ensure_legacy_slots(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    persist: bool = True,
) -> int:
    """Idempotent snapshot of pre-mandate extrapolated ark slots beyond 6."""
    uid = int(player_id)
    if not _column_ready(conn, "players", "expansion_legacy_migrated"):
        return 0
    row = conn.execute(
        """
        SELECT expansion_legacy_slots, expansion_legacy_migrated
        FROM players WHERE id = ? LIMIT 1;
        """,
        (uid,),
    ).fetchone()
    if not row:
        return 0
    if int(row["expansion_legacy_migrated"] or 0) == 1:
        return max(0, int(row["expansion_legacy_slots"] or 0))

    hw = get_homeworld_level(uid, conn=conn)
    old_slots = legacy_expansion_slots_unlocked(hw)
    legacy = max(0, int(old_slots) - ARK_SLOT_MAX)
    if persist:
        conn.execute(
            """
            UPDATE players
            SET expansion_legacy_slots = ?, expansion_legacy_migrated = 1
            WHERE id = ?;
            """,
            (int(legacy), uid),
        )
    return int(legacy)


def list_earned_mandates(player_id: int, *, conn: sqlite3.Connection) -> List[str]:
    if not _table_ready(conn, "player_imperial_mandates"):
        return []
    rows = conn.execute(
        """
        SELECT mandate_key FROM player_imperial_mandates
        WHERE player_id = ?
        ORDER BY earned_at ASC;
        """,
        (int(player_id),),
    ).fetchall()
    earned = {str(r["mandate_key"]) for r in rows}
    return [k for k in MANDATE_ORDER if k in earned]


def count_earned_mandates(player_id: int, *, conn: sqlite3.Connection) -> int:
    return len(list_earned_mandates(player_id, conn=conn))


def _grant_mandate(player_id: int, mandate_key: str, *, conn: sqlite3.Connection, now: float) -> bool:
    if mandate_key not in MANDATE_ORDER:
        return False
    if not _table_ready(conn, "player_imperial_mandates"):
        return False
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO player_imperial_mandates (player_id, mandate_key, earned_at)
        VALUES (?, ?, ?);
        """,
        (int(player_id), str(mandate_key), float(now)),
    )
    return int(cur.rowcount or 0) > 0


def count_lifetime_expeditions(player_id: int, *, conn: sqlite3.Connection) -> int:
    if _table_ready(conn, "expedition_daily_recorded"):
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM expedition_daily_recorded WHERE player_id = ?;",
            (int(player_id),),
        ).fetchone()
        return max(0, int(row["n"] if row else 0))
    return 0


def count_distinct_owned_systems(player_id: int, *, conn: sqlite3.Connection) -> int:
    planets = get_planets_by_player(int(player_id), conn=conn) or []
    systems = set()
    for p in planets:
        g = p.get("galaxy")
        s = p.get("system")
        if g is None or s is None:
            continue
        systems.add((int(g), int(s)))
    return len(systems)


def has_expansion_directive_vote(player_id: int, *, conn: sqlite3.Connection) -> bool:
    if not _table_ready(conn, "gd_votes"):
        return False
    row = conn.execute(
        """
        SELECT 1 FROM gd_votes
        WHERE player_id = ? AND directive_key = 'expansion'
        LIMIT 1;
        """,
        (int(player_id),),
    ).fetchone()
    return row is not None


def has_apex_achievement(player_id: int, *, conn: sqlite3.Connection) -> bool:
    if _table_ready(conn, "world_boss_claims"):
        row = conn.execute(
            "SELECT 1 FROM world_boss_claims WHERE player_id = ? LIMIT 1;",
            (int(player_id),),
        ).fetchone()
        if row:
            return True
    hw = get_homeworld(int(player_id), conn=conn) or {}
    return bool(str(hw.get("ascension_key") or "").strip())


def mandate_progress(
    mandate_key: str,
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Progress for one mandate (current/required/met)."""
    key = str(mandate_key)
    label_key = MANDATE_LABEL_KEYS.get(key, f"imperial_mandate_{key}")
    if key == "survey":
        current = count_lifetime_expeditions(player_id, conn=conn)
        required = SURVEY_EXPEDITIONS_REQUIRED
        return {
            "key": key,
            "label_key": label_key,
            "current": int(current),
            "required": int(required),
            "met": current >= required,
        }
    if key == "presence":
        current = count_distinct_owned_systems(player_id, conn=conn)
        required = PRESENCE_SYSTEMS_REQUIRED
        return {
            "key": key,
            "label_key": label_key,
            "current": int(current),
            "required": int(required),
            "met": current >= required,
        }
    if key == "directive":
        met = has_expansion_directive_vote(player_id, conn=conn)
        return {
            "key": key,
            "label_key": label_key,
            "current": 1 if met else 0,
            "required": 1,
            "met": bool(met),
        }
    if key == "apex":
        met = has_apex_achievement(player_id, conn=conn)
        return {
            "key": key,
            "label_key": label_key,
            "current": 1 if met else 0,
            "required": 1,
            "met": bool(met),
        }
    return {
        "key": key,
        "label_key": label_key,
        "current": 0,
        "required": 1,
        "met": False,
    }


def sync_earned_mandates(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
    legacy_slots: int = 0,
    persist: bool = True,
) -> List[str]:
    """Resolve earned mandates in order; optionally persist newly earned rows."""
    uid = int(player_id)
    ts = float(now if now is not None else time.time())
    legacy_n = min(LATE_SLOT_MAX, max(0, int(legacy_slots)))
    earned = set(list_earned_mandates(uid, conn=conn))
    grants_ready = _table_ready(conn, "player_imperial_mandates")
    for index, key in enumerate(MANDATE_ORDER):
        if key in earned:
            continue
        if index < legacy_n:
            if not grants_ready:
                continue
            if persist:
                if _grant_mandate(uid, key, conn=conn, now=ts) or key in list_earned_mandates(uid, conn=conn):
                    earned.add(key)
            else:
                earned.add(key)
            continue
        prog = mandate_progress(key, uid, conn=conn)
        if not prog.get("met"):
            break
        if not grants_ready:
            break
        if persist:
            if _grant_mandate(uid, key, conn=conn, now=ts) or key in list_earned_mandates(uid, conn=conn):
                earned.add(key)
            else:
                break
        else:
            earned.add(key)
    return [k for k in MANDATE_ORDER if k in earned]


def ensure_player_mandate_state(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    persist: bool = True,
) -> Dict[str, Any]:
    """Lazy migrate + sync grants; returns late-slot breakdown for cap merge."""
    uid = int(player_id)
    legacy = ensure_legacy_slots(uid, conn=conn, persist=persist)
    earned = sync_earned_mandates(
        uid, conn=conn, legacy_slots=legacy, persist=persist
    )
    mandate_count = len(earned)
    # Cap: late = min(4, mandate_count) — legacy is already baked into earned rows.
    late = min(LATE_SLOT_MAX, mandate_count)
    credited = min(LATE_SLOT_MAX, max(0, int(legacy)))
    next_key: Optional[str] = None
    next_prog: Optional[Dict[str, Any]] = None
    for key in MANDATE_ORDER:
        if key in earned:
            continue
        next_key = key
        next_prog = mandate_progress(key, uid, conn=conn)
        break

    return {
        "legacy_slots": int(legacy),
        "mandate_slots": int(mandate_count),
        "earned_mandates": list(earned),
        "late_slots": int(late),
        "late_slot_max": LATE_SLOT_MAX,
        "credited_late_steps": int(credited),
        "next_mandate_key": next_key,
        "next_mandate": next_prog,
        "all_mandates": [
            {
                **mandate_progress(k, uid, conn=conn),
                "earned": k in earned,
                "credited_by_legacy": (MANDATE_ORDER.index(k) < credited),
            }
            for k in MANDATE_ORDER
        ],
    }


def next_mandate_checklist_item(player_id: int, *, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """Checklist row for PE expansion rail when Spätreich is the gate."""
    state = ensure_player_mandate_state(player_id, conn=conn)
    if int(state["late_slots"]) >= LATE_SLOT_MAX:
        return {
            "key": "imperial_mandate",
            "label_key": "imperial_mandate_complete",
            "met": True,
            "current": LATE_SLOT_MAX,
            "required": LATE_SLOT_MAX,
            "mandate_key": "",
        }
    prog = state.get("next_mandate")
    if not prog:
        return None
    return {
        "key": "imperial_mandate",
        "label_key": str(prog.get("label_key") or "imperial_mandate_required"),
        "met": bool(prog.get("met")),
        "current": int(prog.get("current") or 0),
        "required": int(prog.get("required") or 1),
        "mandate_key": str(prog.get("key") or ""),
    }
