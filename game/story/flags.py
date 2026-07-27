"""Player story flags (gate / branch truth)."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Mapping, Optional, Set

from ..db import table_exists

FLAGS_TABLE = "player_story_flags"


def flags_schema_ready(conn) -> bool:
    return table_exists(conn, FLAGS_TABLE)


def get_player_flags(player_id: int, *, conn) -> Dict[str, str]:
    if not flags_schema_ready(conn):
        return {}
    rows = conn.execute(
        "SELECT flag_key, flag_value FROM player_story_flags WHERE player_id = ?;",
        (int(player_id),),
    ).fetchall()
    return {str(r["flag_key"]): str(r["flag_value"] or "1") for r in rows}


def has_flag(player_id: int, flag_key: str, *, conn) -> bool:
    key = str(flag_key or "").strip()
    if not key or not flags_schema_ready(conn):
        return False
    row = conn.execute(
        "SELECT 1 FROM player_story_flags WHERE player_id = ? AND flag_key = ? LIMIT 1;",
        (int(player_id), key),
    ).fetchone()
    return row is not None


def set_flag(
    player_id: int,
    flag_key: str,
    *,
    value: str = "1",
    conn,
    now: float | None = None,
) -> bool:
    key = str(flag_key or "").strip()
    if not key or not flags_schema_ready(conn):
        return False
    ts = int(now if now is not None else time.time())
    conn.execute(
        """
        INSERT INTO player_story_flags (player_id, flag_key, flag_value, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id, flag_key) DO UPDATE SET flag_value = excluded.flag_value;
        """,
        (int(player_id), key, str(value or "1"), ts),
    )
    return True


def set_flags(
    player_id: int,
    flags: Iterable[str] | Mapping[str, Any],
    *,
    conn,
    now: float | None = None,
) -> int:
    n = 0
    if isinstance(flags, Mapping):
        for key, val in flags.items():
            if set_flag(player_id, str(key), value=str(val), conn=conn, now=now):
                n += 1
        return n
    for key in flags:
        if set_flag(player_id, str(key), conn=conn, now=now):
            n += 1
    return n


def flags_satisfy(
    player_flags: Mapping[str, str] | Set[str],
    *,
    require_all: Optional[Iterable[str]] = None,
    require_any: Optional[Iterable[str]] = None,
) -> bool:
    owned: Set[str]
    if isinstance(player_flags, set):
        owned = player_flags
    else:
        owned = {str(k) for k, v in player_flags.items() if v}

    all_need = [str(x).strip() for x in (require_all or []) if str(x).strip()]
    any_need = [str(x).strip() for x in (require_any or []) if str(x).strip()]

    if all_need and not all(f in owned for f in all_need):
        return False
    if any_need and not any(f in owned for f in any_need):
        return False
    if not all_need and not any_need:
        return True
    return True
