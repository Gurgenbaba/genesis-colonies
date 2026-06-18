"""Galaxy personality scoring and state (GC-721D)."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional

from ..db import begin_write_transaction, commit, db
from .blocs import normalize_galaxy
from .definitions import (
    PERSONALITY_KEYS,
    get_personality_definition,
    normalize_personality_key,
    schema_ready,
)

# Directive primary winners → personality trait buckets.
DIRECTIVE_TO_PERSONALITY: Dict[str, str] = {
    "scientific": "academia_prime",
    "military": "forge_of_war",
    "industrial": "forge_of_war",
    "exploration": "frontier_space",
    "expansion": "frontier_space",
    "logistics": "trade_nexus",
    "defensive": "bastion_sector",
}


def _empty_scores() -> Dict[str, int]:
    return {key: 0 for key in PERSONALITY_KEYS}


def score_directive_history(directive_keys: List[Any]) -> Dict[str, int]:
    """Count personality trait scores from an ordered directive history (newest last)."""
    scores = _empty_scores()
    for raw in directive_keys or []:
        directive = str(raw or "").strip().lower()
        personality = DIRECTIVE_TO_PERSONALITY.get(directive)
        if not personality:
            continue
        scores[personality] = int(scores.get(personality, 0)) + 1
    return scores


def infer_personality_key(scores: Mapping[str, Any]) -> str:
    """Return dominant personality key, or empty string on tie / no dominance."""
    if not scores:
        return ""
    numeric = {str(k): int(v or 0) for k, v in scores.items()}
    max_val = max(numeric.values()) if numeric else 0
    if max_val <= 0:
        return ""
    winners = [key for key, val in numeric.items() if val == max_val]
    if len(winners) != 1:
        return ""
    winner = winners[0]
    return winner if winner in PERSONALITY_KEYS else ""


def _parse_score_json(raw: Any) -> Dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _default_state_row(galaxy_id: int) -> Dict[str, Any]:
    return {
        "galaxy": galaxy_id,
        "personality_key": None,
        "score_json": {},
        "active_since": None,
        "updated_at": 0,
    }


def _fetch_state_row(galaxy_id: int, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM gd_galaxy_personality_state WHERE galaxy = ? LIMIT 1;",
        (int(galaxy_id),),
    ).fetchone()
    return dict(row) if row else None


def _build_personality_payload(
    galaxy_id: int,
    row: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
    source: str,
) -> Dict[str, Any]:
    raw_key = row.get("personality_key")
    personality_key = ""
    if raw_key not in (None, ""):
        personality_key = normalize_personality_key(raw_key) or str(raw_key).strip().lower()

    score_json = _parse_score_json(row.get("score_json"))
    definition = None
    if personality_key:
        defn = get_personality_definition(personality_key, conn=conn)
        definition = dict(defn) if defn else None

    return {
        "galaxy": int(galaxy_id),
        "personality_key": personality_key,
        "definition": definition,
        "scores": dict(score_json.get("directive_scores") or score_json.get("scores") or {}),
        "score_json": score_json,
        "dominance_score": int(score_json.get("dominance_score") or 0),
        "active_since": (
            int(row["active_since"]) if row.get("active_since") not in (None, "") else None
        ),
        "updated_at": int(row.get("updated_at") or 0),
        "source": source,
    }


def ensure_galaxy_personality_state(
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Return personality state row for galaxy, inserting empty default if missing."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        raise ValueError("invalid_galaxy")

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return _build_personality_payload(
                galaxy_id,
                _default_state_row(galaxy_id),
                conn=conn,
                source="fallback",
            )

        existing = _fetch_state_row(galaxy_id, conn)
        if existing is not None:
            return _build_personality_payload(galaxy_id, existing, conn=conn, source="state")

        now = int(time.time())
        begin_write_transaction(conn)
        try:
            conn.execute(
                """
                INSERT INTO gd_galaxy_personality_state (
                    galaxy, personality_key, score_json, active_since, updated_at
                ) VALUES (?, NULL, ?, NULL, ?);
                """,
                (galaxy_id, "{}", now),
            )
            commit(conn)
        except sqlite3.Error:
            pass

        row = _fetch_state_row(galaxy_id, conn)
        if row is None:
            return _build_personality_payload(
                galaxy_id,
                _default_state_row(galaxy_id),
                conn=conn,
                source="fallback",
            )
        return _build_personality_payload(galaxy_id, row, conn=conn, source="default")
    finally:
        if own_conn:
            conn.close()


def get_galaxy_personality(
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Read galaxy personality state (bootstraps default row when missing)."""
    return ensure_galaxy_personality_state(galaxy, conn=conn)


def set_galaxy_personality(
    galaxy: Any,
    personality_key: str,
    score: int = 0,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Persist active personality for a galaxy. Empty key clears to neutral."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        raise ValueError("invalid_galaxy")

    raw_key = str(personality_key or "").strip().lower()
    if raw_key:
        key = normalize_personality_key(raw_key)
        if not key:
            raise ValueError("invalid_personality_key")
    else:
        key = ""

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            raise ValueError("schema_not_ready")

        if key:
            if not get_personality_definition(key, conn=conn):
                raise ValueError("invalid_personality_key")

        ensure_galaxy_personality_state(galaxy_id, conn=conn)
        existing = _fetch_state_row(galaxy_id, conn) or _default_state_row(galaxy_id)
        prior_key = existing.get("personality_key")
        score_json = _parse_score_json(existing.get("score_json"))
        score_json["dominance_score"] = int(score or 0)

        now = int(time.time())
        active_since = existing.get("active_since")
        if key:
            if not prior_key or str(prior_key).strip().lower() != key:
                active_since = now
        else:
            active_since = None

        db_key: Optional[str] = key or None
        begin_write_transaction(conn)
        try:
            conn.execute(
                """
                INSERT INTO gd_galaxy_personality_state (
                    galaxy, personality_key, score_json, active_since, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(galaxy) DO UPDATE SET
                    personality_key = excluded.personality_key,
                    score_json = excluded.score_json,
                    active_since = excluded.active_since,
                    updated_at = excluded.updated_at;
                """,
                (galaxy_id, db_key, json.dumps(score_json), active_since, now),
            )
            commit(conn)
        except sqlite3.Error:
            raise

        row = _fetch_state_row(galaxy_id, conn)
        if row is None:
            raise RuntimeError("galaxy_personality_upsert_failed")
        return _build_personality_payload(galaxy_id, row, conn=conn, source="state")
    finally:
        if own_conn:
            conn.close()
