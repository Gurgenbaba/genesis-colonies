"""
EPIC-22 / GC-993 — Premium entitlements (Payment Epic writes the same flag).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from .db import table_exists

KIND_BATTLE_PASS_PREMIUM = "battle_pass_premium"


def schema_ready(conn) -> bool:
    return bool(table_exists(conn, "premium_entitlements"))


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))


def has_entitlement(
    player_id: int,
    kind: str,
    *,
    conn,
    season_id: Optional[int] = None,
) -> bool:
    if not schema_ready(conn):
        return False
    pid = int(player_id)
    k = str(kind or "").strip()
    if pid <= 0 or not k:
        return False
    if season_id is None:
        row = conn.execute(
            """
            SELECT 1 FROM premium_entitlements
            WHERE player_id = ? AND kind = ? AND season_id IS NULL
            LIMIT 1;
            """,
            (pid, k),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT 1 FROM premium_entitlements
            WHERE player_id = ? AND kind = ? AND season_id = ?
            LIMIT 1;
            """,
            (pid, k, int(season_id)),
        ).fetchone()
    return bool(row)


def grant_entitlement(
    player_id: int,
    kind: str,
    *,
    conn,
    season_id: Optional[int] = None,
    source: str = "admin",
    metadata: Optional[Mapping[str, Any]] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "entitlements_unavailable", None
    pid = int(player_id)
    k = str(kind or "").strip()
    if pid <= 0 or not k:
        return False, "invalid_entitlement", None
    ts = float(now if now is not None else time.time())
    sid = int(season_id) if season_id is not None else None
    meta = _json_dumps(metadata or {})
    try:
        conn.execute(
            """
            INSERT INTO premium_entitlements (
                player_id, kind, season_id, source, granted_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, kind, season_id) DO UPDATE SET
                source = excluded.source,
                granted_at = excluded.granted_at,
                metadata_json = excluded.metadata_json;
            """,
            (pid, k, sid, str(source or "admin"), ts, meta),
        )
    except Exception:
        # SQLite UNIQUE with NULL season_id may not conflict — fallback update.
        if sid is None:
            existing = conn.execute(
                """
                SELECT id FROM premium_entitlements
                WHERE player_id = ? AND kind = ? AND season_id IS NULL
                LIMIT 1;
                """,
                (pid, k),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE premium_entitlements
                    SET source = ?, granted_at = ?, metadata_json = ?
                    WHERE id = ?;
                    """,
                    (str(source or "admin"), ts, meta, int(existing["id"])),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO premium_entitlements (
                        player_id, kind, season_id, source, granted_at, metadata_json
                    ) VALUES (?, ?, NULL, ?, ?, ?);
                    """,
                    (pid, k, str(source or "admin"), ts, meta),
                )
        else:
            return False, "grant_failed", None

    return True, "ok", {
        "player_id": pid,
        "kind": k,
        "season_id": sid,
        "source": str(source or "admin"),
        "granted_at": ts,
    }
