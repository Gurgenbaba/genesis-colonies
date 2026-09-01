"""Daily/weekly directive generation (GC-911A)."""

from __future__ import annotations

import datetime
import hashlib
import random
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .definitions import (
    CADENCE_DAILY,
    CADENCE_WEEKLY,
    DAILY_DIRECTIVE_COUNT,
    RARITY_WEIGHTS_DAILY,
    RARITY_WEIGHTS_WEEKLY,
    STATUS_ACTIVE,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_EXPIRED,
    WEEKLY_DIRECTIVE_COUNT,
    definition_is_rollable,
    directives_schema_ready,
    effective_base_target,
    get_definition,
    list_definitions_for_cadence,
    rarity_for_roll,
)
from .balancing import compute_directive_target, is_directive_target_stale
from .rewards import build_reward_payload, reward_json_dumps


def _utc_dt(ts: float) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc)


def daily_period_key(ts: float | None = None) -> str:
    dt = _utc_dt(ts if ts is not None else time.time())
    return f"daily:{dt.strftime('%Y-%m-%d')}"


def weekly_period_key(ts: float | None = None) -> str:
    dt = _utc_dt(ts if ts is not None else time.time())
    iso = dt.isocalendar()
    return f"weekly:{iso.year}-W{iso.week:02d}"


def previous_daily_period_key(ts: float | None = None) -> str:
    dt = _utc_dt(ts if ts is not None else time.time()) - datetime.timedelta(days=1)
    return f"daily:{dt.strftime('%Y-%m-%d')}"


def previous_weekly_period_key(ts: float | None = None) -> str:
    dt = _utc_dt(ts if ts is not None else time.time()) - datetime.timedelta(days=7)
    iso = dt.isocalendar()
    return f"weekly:{iso.year}-W{iso.week:02d}"


def daily_expires_at(ts: float | None = None) -> int:
    dt = _utc_dt(ts if ts is not None else time.time())
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day = start + datetime.timedelta(days=1)
    return int(next_day.timestamp())


def weekly_expires_at(ts: float | None = None) -> int:
    dt = _utc_dt(ts if ts is not None else time.time())
    start_of_week = dt - datetime.timedelta(days=dt.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    next_monday = start_of_week + datetime.timedelta(days=7)
    return int(next_monday.timestamp())


def _rng_for_period(player_id: int, period_key: str) -> random.Random:
    seed_material = f"{int(player_id)}:{period_key}".encode("utf-8")
    seed = int(hashlib.sha256(seed_material).hexdigest()[:12], 16)
    return random.Random(seed)


def _roll_rarity(rng: random.Random, weights: Mapping[str, int]) -> str:
    pool: List[str] = []
    for rarity, weight in weights.items():
        pool.extend([rarity] * max(0, int(weight)))
    if not pool:
        return "common"
    return rng.choice(pool)


def _weighted_pick_definitions(
    rng: random.Random,
    candidates: Sequence[Mapping[str, Any]],
    count: int,
    *,
    exclude_keys: Sequence[str],
    prefer_category_diversity: bool = False,
    seed_categories: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    blocked = {str(k) for k in exclude_keys}
    pool = [
        dict(row)
        for row in candidates
        if str(row.get("key")) not in blocked and int(row.get("weight") or 0) > 0
    ]
    picked: List[Dict[str, Any]] = []
    used_categories: set[str] = {
        str(c) for c in (seed_categories or ()) if str(c or "").strip()
    }
    while pool and len(picked) < count:
        if prefer_category_diversity:
            diverse = [
                row
                for row in pool
                if str(row.get("category") or "") not in used_categories
            ]
            pick_from = diverse if diverse else pool
        else:
            pick_from = pool
        weights = [max(1, int(row.get("weight") or 1)) for row in pick_from]
        choice = rng.choices(pick_from, weights=weights, k=1)[0]
        picked.append(choice)
        used_categories.add(str(choice.get("category") or ""))
        pool = [row for row in pool if row.get("key") != choice.get("key")]
    return picked


def _player_total_score(player_id: int, *, conn: sqlite3.Connection) -> int:
    try:
        from ..ranking import get_player_score_cached

        snapshot = get_player_score_cached(int(player_id), read_only=True, conn=conn)
        return max(0, int(snapshot.get("total") or 0))
    except Exception:
        row = conn.execute(
            "SELECT total_score FROM player_scores WHERE player_id = ? LIMIT 1;",
            (int(player_id),),
        ).fetchone()
        if not row:
            return 0
        return max(0, int(row["total_score"] or 0))


def _existing_period_keys(
    player_id: int,
    cadence: str,
    period_key: str,
    *,
    conn: sqlite3.Connection,
) -> List[str]:
    rows = conn.execute(
        """
        SELECT definition_key
        FROM player_directives
        WHERE player_id = ? AND cadence = ? AND period_key = ?;
        """,
        (int(player_id), str(cadence), str(period_key)),
    ).fetchall()
    return [str(row["definition_key"]) for row in rows]


def _insert_player_directive(
    *,
    player_id: int,
    definition: Mapping[str, Any],
    cadence: str,
    period_key: str,
    expires_at: int,
    rarity: str,
    target_value: int,
    reward_json: str,
    now: int,
    conn: sqlite3.Connection,
) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO player_directives (
            player_id, definition_key, cadence, rarity,
            target_value, progress_value, status, reward_json,
            period_key, expires_at, completed_at, claimed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, NULL, NULL, ?);
        """,
        (
            int(player_id),
            str(definition["key"]),
            str(cadence),
            str(rarity),
            int(target_value),
            STATUS_ACTIVE,
            str(reward_json),
            str(period_key),
            int(expires_at),
            int(now),
        ),
    )
    return int(cur.lastrowid)


def _player_scaling_context(player_id: int, *, conn: sqlite3.Connection) -> Dict[str, Any]:
    score = _player_total_score(player_id, conn=conn)
    daily = {"metal": 0, "crystal": 0, "fuel_cells": 0, "combined": 0}
    try:
        from ..logic import get_building_production_per_hour
        from ..models import get_planet_buildings

        rows = conn.execute(
            "SELECT id FROM planets WHERE player_id = ?;",
            (int(player_id),),
        ).fetchall()
        for row in rows:
            planet_id = int(row["id"])
            buildings = get_planet_buildings(planet_id, conn=conn)
            prod = get_building_production_per_hour(
                buildings,
                1.0,
                user_id=int(player_id),
                conn=conn,
            )
            daily["metal"] += max(0, int(prod.get("metal") or 0))
            daily["crystal"] += max(0, int(prod.get("crystal") or 0))
            daily["fuel_cells"] += max(0, int(prod.get("fuel_cells") or 0))
        daily["combined"] = daily["metal"] + daily["crystal"] + daily["fuel_cells"]
        for key in ("metal", "crystal", "fuel_cells", "combined"):
            daily[key] *= 24
    except Exception:
        pass
    return {"total_score": score, "daily_production": daily}


def _directive_row_stale(row: Mapping[str, Any], *, conn: sqlite3.Connection) -> bool:
    """True when an active row should be replaced (missing/disabled def or over hard cap)."""
    status = str(row.get("status") or STATUS_ACTIVE)
    if status in (STATUS_CLAIMED, STATUS_COMPLETED):
        return False
    definition_key = str(row.get("definition_key") or "").strip()
    if not definition_key:
        return True
    definition = get_definition(definition_key, conn=conn)
    if not definition:
        return True
    if not definition_is_rollable(definition):
        return True
    cadence = str(row.get("cadence") or CADENCE_DAILY)
    return is_directive_target_stale(
        definition_key,
        int(row.get("target_value") or 0),
        cadence=cadence,
    )


def generate_directives_for_cadence(
    player_id: int,
    cadence: str,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
    force: bool = False,
) -> List[Dict[str, Any]]:
    """
    Ensure the player has the required directive count for the current period.

    Idempotent per (player_id, cadence, period_key) unless force=True.
    """
    if not directives_schema_ready(conn):
        return []

    ts = float(now if now is not None else time.time())
    now_i = int(ts)
    cadence_norm = str(cadence or CADENCE_DAILY).strip().lower()
    if cadence_norm == CADENCE_DAILY:
        period_key = daily_period_key(ts)
        expires_at = daily_expires_at(ts)
        required = DAILY_DIRECTIVE_COUNT
        rarity_weights = RARITY_WEIGHTS_DAILY
    elif cadence_norm == CADENCE_WEEKLY:
        period_key = weekly_period_key(ts)
        expires_at = weekly_expires_at(ts)
        required = WEEKLY_DIRECTIVE_COUNT
        rarity_weights = RARITY_WEIGHTS_WEEKLY
    else:
        return []

    existing_rows = _fetch_player_directives(
        player_id,
        cadence_norm,
        period_key,
        conn=conn,
    )

    if not force:
        stale_ids = [
            int(row["id"])
            for row in existing_rows
            if _directive_row_stale(row, conn=conn)
        ]
        if stale_ids:
            placeholders = ",".join("?" * len(stale_ids))
            conn.execute(
                f"DELETE FROM player_directives WHERE id IN ({placeholders});",
                stale_ids,
            )
            existing_rows = [
                row for row in existing_rows if int(row["id"]) not in stale_ids
            ]

    existing_keys = [str(row["definition_key"]) for row in existing_rows]
    if not force and len(existing_keys) >= required:
        return existing_rows

    if force and existing_keys:
        conn.execute(
            """
            DELETE FROM player_directives
            WHERE player_id = ? AND cadence = ? AND period_key = ?;
            """,
            (int(player_id), cadence_norm, period_key),
        )
        existing_keys = []

    missing = required - len(existing_keys)
    if missing <= 0:
        return _fetch_player_directives(player_id, cadence_norm, period_key, conn=conn)

    if cadence_norm == CADENCE_DAILY:
        prev_period = previous_daily_period_key(ts)
    else:
        prev_period = previous_weekly_period_key(ts)
    anti_repeat_keys = _existing_period_keys(
        player_id,
        cadence_norm,
        prev_period,
        conn=conn,
    )
    exclude = list(dict.fromkeys([*existing_keys, *anti_repeat_keys]))
    seed_categories: List[str] = []
    for row in existing_rows:
        defn = get_definition(str(row.get("definition_key") or ""), conn=conn)
        if defn:
            seed_categories.append(str(defn.get("category") or ""))

    candidates = list_definitions_for_cadence(cadence_norm, conn=conn)
    rng = _rng_for_period(player_id, period_key)
    diversify = cadence_norm == CADENCE_DAILY
    picks = _weighted_pick_definitions(
        rng,
        candidates,
        missing,
        exclude_keys=exclude,
        prefer_category_diversity=diversify,
        seed_categories=seed_categories,
    )
    # If anti-repeat emptied the pool too far, retry without previous-period excludes.
    if len(picks) < missing and anti_repeat_keys:
        soft_exclude = list(existing_keys) + [str(p.get("key")) for p in picks]
        seed_after = list(seed_categories) + [
            str(p.get("category") or "") for p in picks
        ]
        picks.extend(
            _weighted_pick_definitions(
                rng,
                candidates,
                missing - len(picks),
                exclude_keys=soft_exclude,
                prefer_category_diversity=diversify,
                seed_categories=seed_after,
            )
        )

    scaling_ctx = _player_scaling_context(player_id, conn=conn)
    created: List[Dict[str, Any]] = []

    for definition in picks:
        rolled = _roll_rarity(rng, rarity_weights)
        rarity = rarity_for_roll(
            rolled,
            min_rarity=str(definition.get("min_rarity") or "common"),
            max_rarity=str(definition.get("max_rarity") or "legendary"),
            cadence=cadence_norm,
        )
        target_value = compute_directive_target(
            definition,
            rarity=rarity,
            cadence=cadence_norm,
            context=scaling_ctx,
        )
        reward_payload = build_reward_payload(rarity=rarity, cadence=cadence_norm)
        directive_id = _insert_player_directive(
            player_id=player_id,
            definition=definition,
            cadence=cadence_norm,
            period_key=period_key,
            expires_at=expires_at,
            rarity=rarity,
            target_value=target_value,
            reward_json=reward_json_dumps(reward_payload),
            now=now_i,
            conn=conn,
        )
        created.append(
            {
                "id": directive_id,
                "definition_key": definition["key"],
                "cadence": cadence_norm,
                "rarity": rarity,
                "target_value": target_value,
                "period_key": period_key,
            }
        )

    return _fetch_player_directives(player_id, cadence_norm, period_key, conn=conn)


def _fetch_player_directives(
    player_id: int,
    cadence: str,
    period_key: str,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, player_id, definition_key, cadence, rarity,
               target_value, progress_value, status, reward_json,
               period_key, expires_at, completed_at, claimed_at, created_at
        FROM player_directives
        WHERE player_id = ? AND cadence = ? AND period_key = ?
        ORDER BY id ASC;
        """,
        (int(player_id), str(cadence), str(period_key)),
    ).fetchall()
    return [dict(row) for row in rows]


def ensure_player_directives(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    """
    Lazy-generate daily (3) and weekly (1) directives for the player.

    Returns summary with both cadences and reset timestamps.
    """
    ts = float(now if now is not None else time.time())
    daily = generate_directives_for_cadence(
        player_id,
        CADENCE_DAILY,
        conn=conn,
        now=ts,
    )
    weekly = generate_directives_for_cadence(
        player_id,
        CADENCE_WEEKLY,
        conn=conn,
        now=ts,
    )
    claimable = sum(
        1
        for row in daily + weekly
        if str(row.get("status") or "") == STATUS_COMPLETED
    )
    return {
        "ready": True,
        "daily_reset_at": daily_expires_at(ts),
        "weekly_reset_at": weekly_expires_at(ts),
        "daily_period_key": daily_period_key(ts),
        "weekly_period_key": weekly_period_key(ts),
        "claimable_count": claimable,
        "daily": daily,
        "weekly": weekly,
    }
