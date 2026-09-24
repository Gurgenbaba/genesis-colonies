"""Closed-universe, one-shot UNI 1 prelaunch normalization.

This is intentionally an operator-only boot action. It preserves account/network
identity and paid/meta ownership, removes gameplay progress, purges reserved
Pirate AI accounts, rebuilds homeworlds, and normalizes existing linked humans to
the same starter baseline future first-entry players receive.
"""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any, Dict, List

from .db import begin_write_transaction, commit, db, rollback, table_exists
from .network_auth import (
    NETWORK_LINK_TABLE,
    current_universe_key,
    universe_is_open,
    _starter_resource_multiplier,
    _starter_timekeeper_seconds,
)
from .runtime_state import get_runtime_value

PRELAUNCH_TOKEN_ENV = "GC_UNI1_PRELAUNCH_RESET_TOKEN"
PRELAUNCH_TOKEN_KEY = "uni1_prelaunch_reset_token"
PRELAUNCH_SUMMARY_KEY = "uni1_prelaunch_reset_summary"
PRELAUNCH_FREEZE_KEY = "uni1_prelaunch_freeze_token"
_FALSEY = {"0", "false", "no", "off"}


def _env_hard_off(name: str) -> bool:
    raw = os.environ.get(str(name))
    return raw is not None and str(raw).strip().lower() in _FALSEY


def _validate_prelaunch_environment(token: str) -> None:
    if str(current_universe_key() or "").lower() != "uni1":
        raise RuntimeError("uni1_prelaunch_wrong_universe")
    if universe_is_open("uni1"):
        raise RuntimeError("uni1_prelaunch_requires_closed_universe")
    if not _env_hard_off("GC_PIRATE_AI_ENABLED"):
        raise RuntimeError("uni1_prelaunch_requires_pirate_ai_hard_off")
    if not _env_hard_off("GC_INACTIVE_AUTOPLAY_ENABLED"):
        raise RuntimeError("uni1_prelaunch_requires_inactive_autoplay_hard_off")
    if str(os.environ.get("GC_UNIVERSE_SPEED_PROFILE") or "").strip().lower() != "x1":
        raise RuntimeError("uni1_prelaunch_requires_x1_profile")
    if str(os.environ.get("GC_ENDGAME_ECONOMY_MODE") or "").strip().lower() != "active":
        raise RuntimeError("uni1_prelaunch_requires_active_endgame_economy")
    if str(os.environ.get("GC_ENDGAME_PRODUCTION_PIVOT") or "").strip() != "120":
        raise RuntimeError("uni1_prelaunch_requires_pivot_120")
    if str(os.environ.get("GC_ENDGAME_PRODUCTION_TAIL_POWER") or "").strip() != "3":
        raise RuntimeError("uni1_prelaunch_requires_q3")
    if int(_starter_resource_multiplier()) != 10:
        raise RuntimeError("uni1_prelaunch_requires_start_resource_multiplier_10")
    if int(_starter_timekeeper_seconds()) != 72 * 3600:
        raise RuntimeError("uni1_prelaunch_requires_start_timekeeper_72h")
    from .mine_evolution.ruleset import ASCENSION_RULESET

    if ASCENSION_RULESET != "nodebuster-v1":
        raise RuntimeError("uni1_prelaunch_requires_nodebuster_v1")
    if len(str(token or "").strip()) < 8:
        raise RuntimeError("uni1_prelaunch_token_too_short")


def _purge_reserved_ai() -> Dict[str, Any]:
    from .pirates.cleanup import (
        purge_pirate_runtime_state,
        purge_reserved_pirate_accounts,
    )

    conn = db()
    try:
        begin_write_transaction(conn)
        accounts = purge_reserved_pirate_accounts(conn=conn)
        runtime = purge_pirate_runtime_state(conn=conn)
        commit(conn)
        return {"accounts": accounts, "runtime": runtime}
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def _linked_human_ids(conn) -> List[int]:
    if not table_exists(conn, NETWORK_LINK_TABLE):
        raise RuntimeError("uni1_prelaunch_network_links_missing")
    from .pirates.accounts import PIRATE_BOT_USERNAMES

    hidden = tuple(sorted(str(name) for name in PIRATE_BOT_USERNAMES))
    params: tuple[Any, ...] = ()
    pirate_clause = ""
    if hidden:
        pirate_clause = " AND u.username NOT IN (" + ",".join("?" for _ in hidden) + ")"
        params = hidden
    rows = conn.execute(
        f"""
        SELECT DISTINCT l.local_user_id AS player_id
        FROM {NETWORK_LINK_TABLE} l
        INNER JOIN users u ON u.id = l.local_user_id
        INNER JOIN players p ON p.id = l.local_user_id
        WHERE COALESCE(u.is_admin, 0) = 0
        {pirate_clause}
        ORDER BY l.local_user_id ASC;
        """,
        params,
    ).fetchall()
    return [int(row["player_id"]) for row in rows]


def _strict_runtime_set(conn, key: str, value: str) -> None:
    """Persist a destructive-operation marker; lock/errors must propagate."""
    now = float(time.time())
    conn.execute(
        """
        INSERT INTO runtime_state (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at;
        """,
        (str(key), str(value), now),
    )
    row = conn.execute(
        "SELECT value FROM runtime_state WHERE key = ? LIMIT 1;",
        (str(key),),
    ).fetchone()
    persisted = str(row["value"]) if row else ""
    if persisted != str(value):
        raise RuntimeError(f"uni1_prelaunch_marker_not_persisted:{key}")


def _activate_prelaunch_freeze(token: str) -> None:
    conn = db()
    try:
        begin_write_transaction(conn)
        _strict_runtime_set(conn, PRELAUNCH_FREEZE_KEY, str(token))
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def _normalize_existing_linked_humans(token: str) -> Dict[str, Any]:
    from .models import get_game_settings, get_homeworld, resource_db_param
    from .ranking import recalculate_all_rankings
    from .timekeeper import credit, get_balance, schema_ready as tk_schema_ready

    now = int(time.time())
    multiplier = int(_starter_resource_multiplier())
    tk_target = int(_starter_timekeeper_seconds())

    conn = db()
    try:
        begin_write_transaction(conn)
        settings = get_game_settings(conn)
        start = {
            "metal": int(Decimal(str(settings.get("start_metal", "150000")))) * multiplier,
            "crystal": int(Decimal(str(settings.get("start_crystal", "100000")))) * multiplier,
            "fuel_cells": int(Decimal(str(settings.get("start_fuel_cells", "25000")))) * multiplier,
        }

        player_ids = _linked_human_ids(conn)
        tk_topups: Dict[str, int] = {}
        homeworlds: Dict[str, int] = {}

        for player_id in player_ids:
            home = get_homeworld(int(player_id), conn=conn)
            if not home:
                raise RuntimeError(f"uni1_prelaunch_homeworld_missing:{player_id}")
            home_id = int(home["id"])
            homeworlds[str(player_id)] = home_id
            conn.execute(
                """
                UPDATE planets
                SET metal = ?, crystal = ?, fuel_cells = ?, last_update = ?
                WHERE id = ? AND player_id = ?;
                """,
                (
                    resource_db_param(start["metal"]),
                    resource_db_param(start["crystal"]),
                    resource_db_param(start["fuel_cells"]),
                    float(now),
                    home_id,
                    int(player_id),
                ),
            )

            # Existing early testers should not launch already classified as
            # inactive/farmable simply because they entered the closed universe.
            conn.execute(
                "UPDATE players SET last_seen = ? WHERE id = ?;",
                (now, int(player_id)),
            )
            if table_exists(conn, "player_presence"):
                conn.execute(
                    """
                    INSERT INTO player_presence (player_id, last_seen, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        updated_at = excluded.updated_at;
                    """,
                    (int(player_id), now, now),
                )

            if tk_target > 0 and tk_schema_ready(conn):
                current = int(get_balance(int(player_id), conn=conn))
                missing = max(0, tk_target - current)
                if missing:
                    credit(
                        int(player_id),
                        missing,
                        "uni1_prelaunch_starter_normalize",
                        conn=conn,
                    )
                tk_topups[str(player_id)] = missing

        ranking = recalculate_all_rankings(refresh_scores=True, conn=conn)
        if isinstance(ranking, dict) and not ranking.get("ok", True):
            raise RuntimeError("uni1_prelaunch_ranking_rebuild_failed")

        summary = {
            "token": str(token),
            "at": now,
            "linked_humans": len(player_ids),
            "player_ids": player_ids,
            "homeworlds": homeworlds,
            "starter_resources": start,
            "starter_multiplier": multiplier,
            "timekeeper_target_sec": tk_target,
            "timekeeper_topups": tk_topups,
            "ranking": ranking,
        }
        _strict_runtime_set(conn, PRELAUNCH_TOKEN_KEY, str(token))
        _strict_runtime_set(
            conn,
            PRELAUNCH_SUMMARY_KEY,
            json.dumps(summary, ensure_ascii=False, sort_keys=True),
        )
        marker = conn.execute(
            "SELECT value FROM runtime_state WHERE key = ? LIMIT 1;",
            (PRELAUNCH_TOKEN_KEY,),
        ).fetchone()
        if not marker or str(marker["value"]) != str(token):
            raise RuntimeError("uni1_prelaunch_completion_marker_missing")
        commit(conn)
        return summary
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def prelaunch_reset_completed() -> bool:
    """True only after a successful normalization wrote its durable marker."""
    marker = str(get_runtime_value(PRELAUNCH_TOKEN_KEY) or "").strip()
    return bool(marker)


def prelaunch_requests_frozen() -> bool:
    """Block closed-UNI1 gameplay once the destructive launch reset begins.

    The durable freeze remains while UNI1 is closed. This makes a two-deploy
    rollout safe: already-running instances that contain this code observe the
    shared DB marker and stop accepting gameplay writes while the synchronous
    reset is executing. Opening UNI1 releases the freeze automatically.
    """
    if str(current_universe_key() or "").lower() != "uni1":
        return False
    if universe_is_open("uni1"):
        return False
    return bool(str(get_runtime_value(PRELAUNCH_FREEZE_KEY) or "").strip())


def require_prelaunch_reset_for_open_uni1() -> None:
    """Fail closed when Production tries to boot an open UNI1 before reset."""
    if str(current_universe_key() or "").lower() != "uni1":
        return
    if not universe_is_open("uni1"):
        return
    if not prelaunch_reset_completed():
        raise RuntimeError("uni1_open_before_prelaunch_reset")


def run_uni1_prelaunch_reset_once(token: str) -> Dict[str, Any]:
    """Execute the final closed-universe reset once for a unique operator token."""
    token_n = str(token or "").strip()
    _validate_prelaunch_environment(token_n)

    previous = get_runtime_value(PRELAUNCH_TOKEN_KEY)
    if previous == token_n:
        return {"ok": True, "skipped": True, "reason": "token_already_applied", "token": token_n}

    # Commit the shared DB freeze before any destructive phase. Once #400 code
    # is already deployed closed without a token, older serving instances from
    # the next Railway rollout observe this marker and reject gameplay writes.
    _activate_prelaunch_freeze(token_n)

    pirate_cleanup = _purge_reserved_ai()

    from .admin_universe_reset import execute_universe_reset_keep_inventory

    reset = execute_universe_reset_keep_inventory(
        skip_backup=True,
        reset_options=None,
        preserve_runtime_keys={PRELAUNCH_FREEZE_KEY},
    )

    normalized = _normalize_existing_linked_humans(token_n)
    return {
        "ok": True,
        "skipped": False,
        "token": token_n,
        "pirate_cleanup": pirate_cleanup,
        "universe_reset": reset,
        "normalized": normalized,
    }
