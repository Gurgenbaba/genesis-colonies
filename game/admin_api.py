"""
Admin Control Center JSON API – business logic for /api/admin/* routes.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from game.admin_audit import list_admin_audit, write_admin_audit
from game.config import get_app_version, is_debug_enabled, is_production
from game.db import db, resolve_db_path, table_exists
from game.health import build_health_report
from game.migrations_util import get_applied_migration_names, list_migration_files, migrations_are_current
from game.models import (
    DEFAULT_GAME_SETTINGS,
    BUILDING_KEYS,
    begin_write_transaction,
    commit,
    delete_build_job,
    delete_research_job,
    ensure_player_and_homeworld,
    get_game_settings,
    get_homeworld,
    get_planet_buildings,
    get_player_rank,
    get_player_score_row,
    get_planets_by_player,
    harden_planets_schema,
    recompute_and_upsert_score,
    rollback,
    save_planet_buildings,
)

MAX_RESOURCE = 1_000_000_000
MAX_BUILDING_LEVEL = 100
SEARCH_LIMIT = 50

CONFIRM_PHRASES: Dict[str, str] = {
    "queue_clear": "CLEAR QUEUE",
    "planet_reset": "RESET PLANET",
    "remove_admin": "REMOVE ADMIN",
    "ban_player": "BAN PLAYER",
    "delete_player": "DELETE PLAYER",
    "run_migrations": "RUN MIGRATIONS",
    "broadcast_messages": "SEND SYSTEM BROADCAST",
    "universe_reset_keep_inventory": "RESET UNIVERSE KEEP INVENTORY",
}


def _err(code: str, message: str = "") -> Dict[str, Any]:
    return {"ok": False, "error": code, "message": message or code}


def _ok(**payload: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True}
    out.update(payload)
    return out


def clamp_resource(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = float(default)
    return max(0.0, min(n, float(MAX_RESOURCE)))


def clamp_building_level(value: Any, default: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = int(default)
    return max(0, min(n, MAX_BUILDING_LEVEL))


def validate_confirm(action_key: str, confirm_text: Any) -> bool:
    expected = CONFIRM_PHRASES.get(action_key)
    if not expected:
        return True
    return str(confirm_text or "").strip() == expected


def _request_meta() -> Tuple[Optional[str], Optional[str]]:
    from flask import request

    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64]
    ua = (request.headers.get("User-Agent") or "")[:256]
    return ip or None, ua or None


def audit(
    admin_id: int,
    action: str,
    *,
    target_type: Optional[str] = None,
    target_id: Optional[str | int] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    ip, ua = _request_meta()
    write_admin_audit(
        int(admin_id),
        action,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
        ip=ip,
        user_agent=ua,
    )


# ---------------------------------------------------------------------------
# Health / migrations / runtime
# ---------------------------------------------------------------------------

def api_health() -> Dict[str, Any]:
    report = build_health_report()
    report["checked_at"] = int(time.time())
    return _ok(health=report)


def api_migrations() -> Dict[str, Any]:
    conn = db()
    try:
        applied = sorted(get_applied_migration_names(conn))
    finally:
        conn.close()
    all_files = [p.name for p in list_migration_files()]
    pending = [n for n in all_files if n not in applied]
    current, _, err = migrations_are_current()
    return _ok(
        migrations={
            "backend": os.environ.get("GC_DB_BACKEND", "sqlite"),
            "db_path": str(resolve_db_path()),
            "applied": applied,
            "pending": pending,
            "current": current,
            "error": err,
            "all": all_files,
        },
    )


def api_runtime() -> Dict[str, Any]:
    from game.runtime_state import get_queue_tick_status

    settings = get_game_settings() or {}
    queue_tick = get_queue_tick_status()
    return _ok(
        runtime={
            "version": get_app_version(),
            "python": sys.version.split()[0],
            "app_env": os.environ.get("APP_ENV", "development"),
            "production": is_production(),
            "debug": is_debug_enabled(),
            "db_backend": os.environ.get("GC_DB_BACKEND", "sqlite"),
            "db_path": str(resolve_db_path()),
            "polling": {
                "interval_active_ms": 4000,
                "interval_idle_ms": 12000,
                "interval_hidden_ms": 60000,
            },
            "settings_snapshot": {
                "production_speed": settings.get("production_speed"),
                "build_speed": settings.get("build_speed"),
                "research_speed": settings.get("research_speed"),
                "queue_limit": settings.get("queue_limit"),
                "research_queue_limit": settings.get("research_queue_limit"),
            },
            "queue_tick": queue_tick,
        },
    )


def api_run_migrations(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    if is_production():
        return _err("forbidden", "Migrations cannot be run from UI in production.")
    if not validate_confirm("run_migrations", body.get("confirm_text")):
        return _err("confirm_required", "Type RUN MIGRATIONS to confirm.")
    try:
        import migrate

        migrate.main()
    except SystemExit as exc:
        if int(getattr(exc, "code", 0) or 0) != 0:
            return _err("migration_failed", str(exc))
    except Exception as exc:
        return _err("migration_failed", str(exc))
    audit(admin_id, "run_migrations", target_type="system", payload={"confirm": True})
    return api_migrations()


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

def search_players(q: str = "", limit: int = SEARCH_LIMIT) -> Dict[str, Any]:
    q = str(q or "").strip()[:64]
    limit = max(1, min(int(limit), SEARCH_LIMIT))
    conn = db()
    try:
        cur = conn.cursor()
        if q.isdigit():
            cur.execute(
                """
                SELECT u.id, u.username, u.is_admin AS user_is_admin,
                       p.name AS player_name, p.is_admin AS player_is_admin,
                       p.last_seen, p.banned_until
                FROM users u
                LEFT JOIN players p ON p.id = u.id
                WHERE u.id = ?
                LIMIT ?;
                """,
                (int(q), limit),
            )
        elif q:
            like = f"%{q}%"
            cur.execute(
                """
                SELECT u.id, u.username, u.is_admin AS user_is_admin,
                       p.name AS player_name, p.is_admin AS player_is_admin,
                       p.last_seen, p.banned_until
                FROM users u
                LEFT JOIN players p ON p.id = u.id
                WHERE u.username LIKE ? OR p.name LIKE ?
                ORDER BY u.id ASC
                LIMIT ?;
                """,
                (like, like, limit),
            )
        else:
            cur.execute(
                """
                SELECT u.id, u.username, u.is_admin AS user_is_admin,
                       p.name AS player_name, p.is_admin AS player_is_admin,
                       p.last_seen, p.banned_until
                FROM users u
                LEFT JOIN players p ON p.id = u.id
                ORDER BY u.id ASC
                LIMIT ?;
                """,
                (limit,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["is_admin"] = 1 if int(r.get("user_is_admin") or 0) or int(r.get("player_is_admin") or 0) else 0
        return _ok(players=rows)
    finally:
        conn.close()


def get_player_detail(player_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.username, u.is_admin AS user_is_admin,
                   p.name AS player_name, p.is_admin AS player_is_admin,
                   p.last_seen, p.banned_until
            FROM users u
            LEFT JOIN players p ON p.id = u.id
            WHERE u.id = ? LIMIT 1;
            """,
            (int(player_id),),
        )
        row = cur.fetchone()
        if not row:
            return _err("not_found", "Player not found.")
        player = dict(row)
        player["is_admin"] = 1 if int(player.get("user_is_admin") or 0) or int(player.get("player_is_admin") or 0) else 0

        planets = get_planets_by_player(int(player_id), conn=conn)
        homeworld = None
        try:
            homeworld = get_homeworld(int(player_id), conn=conn)
        except Exception:
            homeworld = None

        score = get_player_score_row(int(player_id)) or {}
        rank, total = get_player_rank(int(player_id))

        return _ok(
            player=player,
            planets=planets,
            homeworld=homeworld,
            score={
                "total": int(score.get("score_total") or 0),
                "buildings": int(score.get("score_buildings") or 0),
                "research": int(score.get("score_research") or 0),
                "rank": rank,
                "total_players": total,
            },
        )
    finally:
        conn.close()


def get_player_effects_debug(player_id: int) -> Dict[str, Any]:
    """Authoritative effect breakdown for admin debugging."""
    from game.logic import get_effect_debug_snapshot

    try:
        snapshot = get_effect_debug_snapshot(int(player_id))
    except Exception as exc:
        return _err("effects_unavailable", str(exc))
    return _ok(
        effects=snapshot,
        developer_note=(
            "modifiers_active = live gameplay. modifiers_prepared = computed only; "
            "not applied until combat/fleet/scan engines exist. Do not show prepared "
            "values as active bonuses to players."
        ),
    )


def set_player_admin(admin_id: int, player_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    is_admin = 1 if body.get("is_admin") in (True, 1, "1", "true") else 0
    if is_admin == 0 and not validate_confirm("remove_admin", body.get("confirm_text")):
        return _err("confirm_required", "Type REMOVE ADMIN to revoke admin rights.")

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1;", (int(player_id),))
        if not cur.fetchone():
            return _err("not_found", "Player not found.")
        cur.execute("UPDATE users SET is_admin = ? WHERE id = ?;", (is_admin, int(player_id)))
        cur.execute(
            "UPDATE players SET is_admin = ? WHERE id = ?;",
            (is_admin, int(player_id)),
        )
        conn.commit()
    finally:
        conn.close()

    audit(
        admin_id,
        "set_admin" if is_admin else "remove_admin",
        target_type="player",
        target_id=player_id,
        payload={"is_admin": is_admin},
    )
    return get_player_detail(player_id)


def ban_player_api(admin_id: int, player_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    if not validate_confirm("ban_player", body.get("confirm_text")):
        return _err("confirm_required", "Type BAN PLAYER to confirm ban.")

    reason = str(body.get("reason") or "").strip()[:500]
    hours = body.get("hours")
    try:
        hours_val = int(hours) if hours is not None else 24 * 365 * 10
    except (TypeError, ValueError):
        hours_val = 24 * 365 * 10
    if hours_val <= 0:
        banned_until = int(time.time()) + 50 * 365 * 24 * 3600
    else:
        hours_val = min(hours_val, 24 * 365 * 50)
        banned_until = int(time.time()) + hours_val * 3600
    now = int(time.time())

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1;", (int(player_id),))
        if not cur.fetchone():
            return _err("not_found", "Player not found.")
        cur.execute(
            "UPDATE players SET banned_until = ? WHERE id = ?;",
            (banned_until, int(player_id)),
        )
        if table_exists(conn, "bans"):
            cur.execute(
                """
                INSERT INTO bans (player_id, reason, banned_until, created_at)
                VALUES (?, ?, ?, ?);
                """,
                (int(player_id), reason, banned_until, now),
            )
        conn.commit()
    finally:
        conn.close()

    audit(
        admin_id,
        "ban_player",
        target_type="player",
        target_id=player_id,
        payload={"reason": reason, "hours": hours_val},
    )
    return get_player_detail(player_id)


def unban_player_api(admin_id: int, player_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE players SET banned_until = NULL WHERE id = ?;",
            (int(player_id),),
        )
        conn.commit()
    finally:
        conn.close()

    audit(admin_id, "unban_player", target_type="player", target_id=player_id)
    return get_player_detail(player_id)


def delete_player_api(admin_id: int, player_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    if not validate_confirm("delete_player", body.get("confirm_text")):
        return _err("confirm_required", "Type DELETE PLAYER to confirm permanent account deletion.")

    pid = int(player_id)
    if int(admin_id) == pid:
        return _err("cannot_delete_self", "You cannot delete your own account from the admin panel.")

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, is_admin FROM users WHERE id = ? LIMIT 1;",
            (pid,),
        )
        row = cur.fetchone()
        if not row:
            return _err("not_found", "Player not found.")
        if int(row["is_admin"] or 0):
            return _err(
                "cannot_delete_admin",
                "Remove admin rights before permanently deleting this account.",
            )

        expected_username = str(body.get("expected_username") or "").strip()
        actual_username = str(row["username"] or "").strip()
        if not expected_username or expected_username != actual_username:
            return _err(
                "username_mismatch",
                f"Type the exact username to confirm ({actual_username}).",
            )

        begin_write_transaction(conn)
        from game.options import hard_delete_player_account

        summary = hard_delete_player_account(pid, conn=conn)
        commit(conn)
    except ValueError as exc:
        rollback(conn)
        code = str(exc) or "delete_failed"
        return _err(code, code)
    except Exception as exc:
        rollback(conn)
        return _err("delete_failed", str(exc))
    finally:
        conn.close()

    audit(
        admin_id,
        "delete_player",
        target_type="player",
        target_id=pid,
        payload=summary,
    )
    return _ok(deleted=summary)


def set_player_resources(admin_id: int, player_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(body.get("mode") or "add").lower()
    metal = clamp_resource(body.get("metal", 0))
    crystal = clamp_resource(body.get("crystal", 0))
    fuel_cells = clamp_resource(body.get("fuel_cells", 0))

    conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM planets
            WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;
            """,
            (int(player_id),),
        )
        row = cur.fetchone()
        if not row:
            rollback(conn)
            return _err("not_found", "Homeworld not found.")
        planet_id = int(row["id"])

        if mode == "set":
            cur.execute(
                "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
                (metal, crystal, fuel_cells, planet_id),
            )
        else:
            cur.execute(
                """
                UPDATE planets
                SET metal = MIN(?, MAX(0, metal + ?)),
                    crystal = MIN(?, MAX(0, crystal + ?)),
                    fuel_cells = MIN(?, MAX(0, fuel_cells + ?))
                WHERE id = ?;
                """,
                (MAX_RESOURCE, metal, MAX_RESOURCE, crystal, MAX_RESOURCE, fuel_cells, planet_id),
            )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    audit(
        admin_id,
        "player_resources",
        target_type="player",
        target_id=player_id,
        payload={"mode": mode, "metal": metal, "crystal": crystal, "fuel_cells": fuel_cells},
    )
    return get_player_detail(player_id)


# ---------------------------------------------------------------------------
# Planets
# ---------------------------------------------------------------------------

def search_planets(q: str = "", limit: int = SEARCH_LIMIT) -> Dict[str, Any]:
    q = str(q or "").strip()[:64]
    limit = max(1, min(int(limit), SEARCH_LIMIT))
    conn = db()
    try:
        cur = conn.cursor()
        if q.isdigit():
            cur.execute(
                """
                SELECT p.*, u.username AS owner_username
                FROM planets p
                LEFT JOIN users u ON u.id = p.player_id
                WHERE p.id = ? OR p.player_id = ?
                ORDER BY p.id ASC LIMIT ?;
                """,
                (int(q), int(q), limit),
            )
        elif q:
            like = f"%{q}%"
            cur.execute(
                """
                SELECT p.*, u.username AS owner_username
                FROM planets p
                LEFT JOIN users u ON u.id = p.player_id
                WHERE p.name LIKE ? OR u.username LIKE ?
                ORDER BY p.id ASC LIMIT ?;
                """,
                (like, like, limit),
            )
        else:
            cur.execute(
                """
                SELECT p.*, u.username AS owner_username
                FROM planets p
                LEFT JOIN users u ON u.id = p.player_id
                ORDER BY p.id ASC LIMIT ?;
                """,
                (limit,),
            )
        return _ok(planets=[dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


def get_planet_detail(planet_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.*, u.username AS owner_username
            FROM planets p
            LEFT JOIN users u ON u.id = p.player_id
            WHERE p.id = ? LIMIT 1;
            """,
            (int(planet_id),),
        )
        row = cur.fetchone()
        if not row:
            return _err("not_found", "Planet not found.")
        planet = dict(row)
        buildings = get_planet_buildings(int(planet_id), conn=conn)
        cur.execute(
            "SELECT * FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC;",
            (int(planet_id),),
        )
        queue = [dict(r) for r in cur.fetchall()]
        return _ok(planet=planet, buildings=buildings, build_queue=queue)
    finally:
        conn.close()


def set_planet_resources(admin_id: int, planet_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(body.get("mode") or "add").lower()
    metal = clamp_resource(body.get("metal", 0))
    crystal = clamp_resource(body.get("crystal", 0))
    fuel_cells = clamp_resource(body.get("fuel_cells", 0))

    conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute("SELECT id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
        if not cur.fetchone():
            rollback(conn)
            return _err("not_found", "Planet not found.")
        if mode == "set":
            cur.execute(
                "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
                (metal, crystal, fuel_cells, int(planet_id)),
            )
        else:
            cur.execute(
                """
                UPDATE planets
                SET metal = MIN(?, MAX(0, metal + ?)),
                    crystal = MIN(?, MAX(0, crystal + ?)),
                    fuel_cells = MIN(?, MAX(0, fuel_cells + ?))
                WHERE id = ?;
                """,
                (MAX_RESOURCE, metal, MAX_RESOURCE, crystal, MAX_RESOURCE, fuel_cells, int(planet_id)),
            )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    audit(
        admin_id,
        "planet_resources",
        target_type="planet",
        target_id=planet_id,
        payload={"mode": mode, "metal": metal, "crystal": crystal, "fuel_cells": fuel_cells},
    )
    return get_planet_detail(planet_id)


def set_planet_building(admin_id: int, planet_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    building_type = str(body.get("building_type") or "").strip()
    if building_type not in BUILDING_KEYS:
        return _err("invalid_building", "Unknown building type.")
    level = clamp_building_level(body.get("level", 0))

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
        row = cur.fetchone()
        if not row:
            return _err("not_found", "Planet not found.")
        player_id = int(row["player_id"])
        buildings = get_planet_buildings(int(planet_id), conn=conn)
        buildings[building_type] = level
        save_planet_buildings(int(planet_id), buildings)
        recompute_and_upsert_score(player_id, conn=conn)
    finally:
        conn.close()

    audit(
        admin_id,
        "planet_building",
        target_type="planet",
        target_id=planet_id,
        payload={"building_type": building_type, "level": level},
    )
    return get_planet_detail(planet_id)


def repair_homeworld(admin_id: int, player_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        harden_planets_schema(conn)
        ensure_player_and_homeworld(int(player_id), conn=conn)
        conn.commit()
    finally:
        conn.close()
    audit(admin_id, "repair_homeworld", target_type="player", target_id=player_id)
    return get_player_detail(player_id)


def inventory_admin_catalog() -> Dict[str, Any]:
    from game.inventory import admin_grant_catalog, inventory_schema_ready

    conn = db()
    try:
        ready = inventory_schema_ready(conn)
    finally:
        conn.close()
    if not ready:
        return _err("inventory_unavailable", "Inventory schema not ready.")
    return {"ok": True, "containers": admin_grant_catalog()}


def grant_player_inventory(admin_id: int, player_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.inventory import grant_inventory_item, inventory_schema_ready, is_known_item_key

    item_key = str(body.get("item_key") or "").strip()
    try:
        amount = int(body.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0

    if not item_key or not is_known_item_key(item_key):
        return _err("invalid_item", "Unknown inventory item key.")
    if amount < 1 or amount > 999:
        return _err("invalid_amount", "Amount must be between 1 and 999.")

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return _err("inventory_unavailable", "Inventory schema not ready.")
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE id = ? LIMIT 1;", (int(player_id),))
        if not cur.fetchone():
            return _err("not_found", "Player not found.")
        begin_write_transaction(conn)
        if not grant_inventory_item(int(player_id), item_key, amount, conn=conn):
            rollback(conn)
            return _err("grant_failed", "Could not grant inventory item.")
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    audit(
        admin_id,
        "grant_inventory",
        target_type="player",
        target_id=player_id,
        payload={"item_key": item_key, "amount": amount},
    )
    detail = get_player_detail(player_id)
    detail["granted"] = {"item_key": item_key, "amount": amount}
    return detail


def grant_inventory_all_players(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.inventory import grant_inventory_item, inventory_schema_ready, is_known_item_key

    item_key = str(body.get("item_key") or "").strip()
    try:
        amount = int(body.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0

    if not item_key or not is_known_item_key(item_key):
        return _err("invalid_item", "Unknown inventory item key.")
    if amount < 1 or amount > 999:
        return _err("invalid_amount", "Amount must be between 1 and 999.")

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return _err("inventory_unavailable", "Inventory schema not ready.")
        cur = conn.cursor()
        cur.execute("SELECT id FROM players ORDER BY id ASC;")
        player_ids = [int(row["id"]) for row in cur.fetchall()]
        if not player_ids:
            return _err("no_players", "No players found.")

        begin_write_transaction(conn)
        granted_count = 0
        for pid in player_ids:
            if grant_inventory_item(pid, item_key, amount, conn=conn):
                granted_count += 1
        if granted_count <= 0:
            rollback(conn)
            return _err("grant_failed", "Could not grant inventory items.")
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    audit(
        admin_id,
        "grant_inventory_all",
        target_type="global",
        target_id=None,
        payload={
            "item_key": item_key,
            "amount": amount,
            "player_count": len(player_ids),
            "granted_count": granted_count,
        },
    )
    return _ok(
        granted={"item_key": item_key, "amount": amount},
        player_count=len(player_ids),
        granted_count=granted_count,
    )


def lootboxes_admin_state() -> Dict[str, Any]:
    from game.inventory import inventory_schema_ready
    from game.inventory_admin import build_admin_loot_state

    conn = db()
    try:
        ready = inventory_schema_ready(conn)
    finally:
        conn.close()
    if not ready:
        return _err("inventory_unavailable", "Inventory schema not ready.")
    return build_admin_loot_state()


def save_lootbox_pool(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.inventory import inventory_schema_ready
    from game.inventory_admin import validate_loot_pool
    from game.inventory_catalog import CONTAINER_KEYS
    from game import inventory_loot

    container_key = str(body.get("container_key") or "").strip()
    if container_key not in CONTAINER_KEYS:
        return _err("invalid_container", "Unknown container key.")

    ok, reason, entries = validate_loot_pool(body.get("entries"))
    if not ok:
        return _err(reason or "invalid_pool", "Invalid loot pool.")

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return _err("inventory_unavailable", "Inventory schema not ready.")
    finally:
        conn.close()

    inventory_loot.set_container_pool_override(container_key, entries)
    audit(
        admin_id,
        "loot_pool_save",
        target_type="container",
        target_id=container_key,
        payload={"container_key": container_key, "entry_count": len(entries)},
    )
    from game.inventory_admin import build_admin_loot_state

    state = build_admin_loot_state()
    return {
        "ok": True,
        "container_key": container_key,
        "pool": state["pools"].get(container_key),
    }


def reset_lootbox_pool(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.inventory import inventory_schema_ready
    from game.inventory_catalog import CONTAINER_KEYS
    from game import inventory_loot

    container_key = str(body.get("container_key") or "").strip()
    if container_key not in CONTAINER_KEYS:
        return _err("invalid_container", "Unknown container key.")

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return _err("inventory_unavailable", "Inventory schema not ready.")
    finally:
        conn.close()

    inventory_loot.clear_container_pool_override(container_key)
    audit(
        admin_id,
        "loot_pool_reset",
        target_type="container",
        target_id=container_key,
        payload={"container_key": container_key},
    )
    from game.inventory_admin import build_admin_loot_state

    state = build_admin_loot_state()
    return {
        "ok": True,
        "container_key": container_key,
        "pool": state["pools"].get(container_key),
    }


def reset_planet(admin_id: int, planet_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    if not validate_confirm("planet_reset", body.get("confirm_text")):
        return _err("confirm_required", "Type RESET PLANET to confirm.")

    settings = get_game_settings() or {}
    start_metal = clamp_resource(settings.get("start_metal", DEFAULT_GAME_SETTINGS["start_metal"]))
    start_crystal = clamp_resource(settings.get("start_crystal", DEFAULT_GAME_SETTINGS["start_crystal"]))

    conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
        row = cur.fetchone()
        if not row:
            rollback(conn)
            return _err("not_found", "Planet not found.")
        player_id = int(row["player_id"])

        cur.execute(
            "UPDATE planets SET metal = ?, crystal = ?, last_update = ? WHERE id = ?;",
            (start_metal, start_crystal, time.time(), int(planet_id)),
        )
        cur.execute("DELETE FROM build_queue WHERE planet_id = ?;", (int(planet_id),))
        cur.execute(
            f"UPDATE planet_buildings SET {', '.join(f'{k}=0' for k in BUILDING_KEYS)} WHERE planet_id = ?;",
            (int(planet_id),),
        )
        recompute_and_upsert_score(player_id, conn=conn)
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    audit(admin_id, "planet_reset", target_type="planet", target_id=planet_id)
    return get_planet_detail(planet_id)


# ---------------------------------------------------------------------------
# Queues
# ---------------------------------------------------------------------------

def get_queues(filters: Dict[str, Any]) -> Dict[str, Any]:
    player_id = filters.get("player_id")
    planet_id = filters.get("planet_id")
    status = str(filters.get("status") or "all").lower()
    now = time.time()

    conn = db()
    try:
        cur = conn.cursor()
        b_params: List[Any] = []
        r_params: List[Any] = []
        s_params: List[Any] = []
        d_params: List[Any] = []
        b_where = ["1=1"]
        r_where = ["1=1"]
        s_where = ["1=1"]
        d_where = ["1=1"]

        if planet_id is not None:
            try:
                pid = int(planet_id)
                b_where.append("bq.planet_id = ?")
                b_params.append(pid)
                s_where.append("sq.planet_id = ?")
                s_params.append(pid)
                d_where.append("dq.planet_id = ?")
                d_params.append(pid)
            except (TypeError, ValueError):
                pass
        if player_id is not None:
            try:
                uid = int(player_id)
                b_where.append("pl.player_id = ?")
                b_params.append(uid)
                r_where.append("rq.user_id = ?")
                r_params.append(uid)
                s_where.append("sq.player_id = ?")
                s_params.append(uid)
                d_where.append("dq.player_id = ?")
                d_params.append(uid)
            except (TypeError, ValueError):
                pass

        cur.execute(
            f"""
            SELECT bq.*, pl.name AS planet_name, pl.player_id, u.username
            FROM build_queue bq
            JOIN planets pl ON pl.id = bq.planet_id
            LEFT JOIN users u ON u.id = pl.player_id
            WHERE {' AND '.join(b_where)}
            ORDER BY bq.finish_time ASC
            LIMIT 200;
            """,
            b_params,
        )
        build_rows = [dict(r) for r in cur.fetchall()]

        cur.execute(
            f"""
            SELECT rq.*, u.username
            FROM research_queue rq
            LEFT JOIN users u ON u.id = rq.user_id
            WHERE {' AND '.join(r_where)}
            ORDER BY rq.finish_at ASC
            LIMIT 200;
            """,
            r_params,
        )
        research_rows = [dict(r) for r in cur.fetchall()]

        shipyard_rows: List[Dict[str, Any]] = []
        defense_rows: List[Dict[str, Any]] = []
        if table_exists(conn, "shipyard_queue"):
            cur.execute(
                f"""
                SELECT sq.*, pl.name AS planet_name, u.username
                FROM shipyard_queue sq
                JOIN planets pl ON pl.id = sq.planet_id
                LEFT JOIN users u ON u.id = sq.player_id
                WHERE {' AND '.join(s_where)}
                ORDER BY sq.finish_at ASC
                LIMIT 200;
                """,
                s_params,
            )
            shipyard_rows = [dict(r) for r in cur.fetchall()]
        if table_exists(conn, "defense_queue"):
            cur.execute(
                f"""
                SELECT dq.*, pl.name AS planet_name, u.username
                FROM defense_queue dq
                JOIN planets pl ON pl.id = dq.planet_id
                LEFT JOIN users u ON u.id = dq.player_id
                WHERE {' AND '.join(d_where)}
                ORDER BY dq.finish_at ASC
                LIMIT 200;
                """,
                d_params,
            )
            defense_rows = [dict(r) for r in cur.fetchall()]

        def _tag(row: Dict[str, Any], finish_key: str) -> str:
            ft = float(row.get(finish_key) or 0)
            if ft <= now:
                return "finished"
            return "active"

        for row in build_rows:
            row["status"] = _tag(row, "finish_time")
        for row in research_rows:
            row["status"] = _tag(row, "finish_at")
        for row in shipyard_rows:
            row["status"] = _tag(row, "finish_at")
        for row in defense_rows:
            row["status"] = _tag(row, "finish_at")

        if status == "active":
            build_rows = [r for r in build_rows if r["status"] == "active"]
            research_rows = [r for r in research_rows if r["status"] == "active"]
            shipyard_rows = [r for r in shipyard_rows if r["status"] == "active"]
            defense_rows = [r for r in defense_rows if r["status"] == "active"]
        elif status == "finished":
            build_rows = [r for r in build_rows if r["status"] == "finished"]
            research_rows = [r for r in research_rows if r["status"] == "finished"]
            shipyard_rows = [r for r in shipyard_rows if r["status"] == "finished"]
            defense_rows = [r for r in defense_rows if r["status"] == "finished"]

        return _ok(
            build_queue=build_rows,
            research_queue=research_rows,
            shipyard_queue=shipyard_rows,
            defense_queue=defense_rows,
        )
    finally:
        conn.close()


def get_admin_fleets(filters: Dict[str, Any]) -> Dict[str, Any]:
    from game.fleet import fleet_schema_ready, list_admin_fleet_movements

    conn = db()
    try:
        if not fleet_schema_ready(conn):
            return _err("fleet_unavailable", "Fleet schema not ready.")
        player_raw = filters.get("player_id")
        player_id = int(player_raw) if player_raw not in (None, "") else None
        try:
            limit = int(filters.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        movements = list_admin_fleet_movements(
            player_id=player_id,
            status=str(filters.get("status") or "all"),
            limit=limit,
            conn=conn,
        )
        return _ok(movements=movements, count=len(movements))
    finally:
        conn.close()


def advance_admin_fleet(admin_id: int, movement_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.fleet import admin_advance_fleet_movement, fleet_schema_ready

    complete = bool(body.get("complete"))
    conn = db()
    try:
        if not fleet_schema_ready(conn):
            return _err("fleet_unavailable", "Fleet schema not ready.")
        begin_write_transaction(conn)
        result = admin_advance_fleet_movement(
            int(movement_id),
            conn=conn,
            complete=complete,
        )
        if not result.get("ok"):
            rollback(conn)
            code = str(result.get("error") or "advance_failed")
            return _err(code, code)
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    audit(
        admin_id,
        "fleet_advance",
        target_type="fleet_movement",
        target_id=int(movement_id),
        payload={
            "complete": complete,
            "status_before": result.get("status_before"),
            "status_after": result.get("status_after"),
            "steps": result.get("steps"),
        },
    )
    return _ok(**result)


def cancel_queue_job(admin_id: int, queue_type: str, job_id: int) -> Dict[str, Any]:
    qtype = str(queue_type or "").lower()
    if qtype == "build":
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT planet_id FROM build_queue WHERE id = ? LIMIT 1;", (int(job_id),))
            row = cur.fetchone()
            if not row:
                return _err("not_found", "Build job not found.")
            delete_build_job(int(job_id), conn=conn)
            conn.commit()
        finally:
            conn.close()
    elif qtype == "research":
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM research_queue WHERE id = ? LIMIT 1;", (int(job_id),))
            row = cur.fetchone()
            if not row:
                return _err("not_found", "Research job not found.")
            delete_research_job(int(job_id), conn=conn)
            conn.commit()
        finally:
            conn.close()
    elif qtype == "shipyard":
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM shipyard_queue WHERE id = ? LIMIT 1;", (int(job_id),))
            if not cur.fetchone():
                return _err("not_found", "Shipyard job not found.")
            cur.execute("DELETE FROM shipyard_queue WHERE id = ?;", (int(job_id),))
            conn.commit()
        finally:
            conn.close()
    elif qtype == "defense":
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM defense_queue WHERE id = ? LIMIT 1;", (int(job_id),))
            if not cur.fetchone():
                return _err("not_found", "Defense job not found.")
            cur.execute("DELETE FROM defense_queue WHERE id = ?;", (int(job_id),))
            conn.commit()
        finally:
            conn.close()
    else:
        return _err("invalid_type", "Queue type must be build, research, shipyard, or defense.")

    audit(
        admin_id,
        "queue_cancel",
        target_type=qtype,
        target_id=job_id,
        payload={"queue_type": qtype},
    )
    return _ok(cancelled=True, queue_type=qtype, job_id=int(job_id))


def run_queue_tick_admin(admin_id: int) -> Dict[str, Any]:
    """Manual queue tick via tick_runner (batched due scope)."""
    from game.tick_runner import run_tick

    result = run_tick(
        scope="due",
        batch_size=100,
        source="admin_manual",
        persist=True,
    )

    finished = dict(result.get("finished") or {})
    affected = list(result.get("affected_players") or [])
    errors = list(result.get("errors") or [])
    elapsed = int(result.get("tick_elapsed_ms") or result.get("duration_ms") or 0)

    derived_sync_count = int(result.get("derived_sync_count") or 0)

    audit(
        admin_id,
        "queue_tick",
        target_type="system",
        payload={
            "source": "admin_manual",
            "finished": finished,
            "affected_players": len(affected),
            "batches": int(result.get("batches") or 0),
            "duration_ms": elapsed,
            "derived_sync_count": derived_sync_count,
            "errors": len(errors),
        },
    )

    out = _ok(
        finished=finished,
        affected_players=affected,
        batches=int(result.get("batches") or 0),
        tick_elapsed_ms=elapsed,
        derived_sync_count=derived_sync_count,
        errors=errors,
        players_processed=int(result.get("players_processed") or 0),
        score_updates=int(result.get("score_updates") or 0),
        rank_recalculated=bool(result.get("rank_recalculated")),
    )
    if not result.get("ok", True):
        out["ok"] = False
        out["error"] = "tick_failed"
        out["message"] = "; ".join(errors) if errors else "queue_tick_failed"
    return out


def finish_due_queues(admin_id: int) -> Dict[str, Any]:
    from game.queue_engine import finish_due_work

    engine = finish_due_work(source="admin")

    audit(
        admin_id,
        "queues_finish_due",
        target_type="system",
        payload={
            "source": engine.get("source"),
            "finished": engine.get("finished"),
            "affected_players": len(engine.get("affected_players") or []),
            "affected_planets": len(engine.get("affected_planets") or []),
            "score_updates": engine.get("score_updates"),
            "rank_recalculated": engine.get("rank_recalculated"),
            "duration_ms": engine.get("duration_ms"),
            "errors": engine.get("errors"),
        },
    )
    out = _ok()
    out.update(engine)
    return out


def clear_queues(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    if not validate_confirm("queue_clear", body.get("confirm_text")):
        return _err("confirm_required", "Type CLEAR QUEUE to confirm.")

    scope = str(body.get("scope") or "planet").lower()
    planet_id = body.get("planet_id")
    player_id = body.get("player_id")
    queue_type = str(body.get("queue_type") or "both").lower()

    conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        deleted_build = 0
        deleted_research = 0

        if queue_type in ("build", "both"):
            if scope == "planet" and planet_id is not None:
                cur.execute("DELETE FROM build_queue WHERE planet_id = ?;", (int(planet_id),))
            elif scope == "player" and player_id is not None:
                cur.execute(
                    """
                    DELETE FROM build_queue
                    WHERE planet_id IN (SELECT id FROM planets WHERE player_id = ?);
                    """,
                    (int(player_id),),
                )
            deleted_build = cur.rowcount

        if queue_type in ("research", "both"):
            if scope == "player" and player_id is not None:
                cur.execute("DELETE FROM research_queue WHERE user_id = ?;", (int(player_id),))
                deleted_research = cur.rowcount
            elif scope == "planet":
                cur.execute(
                    """
                    DELETE FROM research_queue
                    WHERE user_id IN (SELECT player_id FROM planets WHERE id = ? LIMIT 1);
                    """,
                    (int(planet_id),),
                )
                deleted_research = cur.rowcount

        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    audit(
        admin_id,
        "queue_clear",
        target_type=scope,
        target_id=planet_id or player_id,
        payload={"queue_type": queue_type, "deleted_build": deleted_build, "deleted_research": deleted_research},
    )
    return _ok(deleted_build=deleted_build, deleted_research=deleted_research)


def get_audit_log(filters: Dict[str, Any]) -> Dict[str, Any]:
    rows = list_admin_audit(
        admin_id=filters.get("admin_id"),
        action=str(filters.get("action") or "").strip() or None,
        target_type=str(filters.get("target_type") or "").strip() or None,
        limit=int(filters.get("limit") or 100),
        offset=int(filters.get("offset") or 0),
    )
    return _ok(entries=rows)


# ---------------------------------------------------------------------------
# Balance settings (Admin → Balance tab)
# ---------------------------------------------------------------------------

def api_get_balance_settings() -> Dict[str, Any]:
    from game.admin_balance import get_balance_settings

    return _ok(settings=get_balance_settings())


def api_save_balance_settings(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.admin_balance import build_balance_hud_snapshot, save_balance_settings

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")

    settings, err = save_balance_settings(body)
    if err:
        return _err("invalid_settings", err)

    audit(
        int(admin_id),
        "balance_settings_save",
        target_type="system",
        payload={"keys": sorted(body.keys())},
    )
    hud = build_balance_hud_snapshot(int(admin_id))
    return _ok(settings=settings, hud=hud)


def api_apply_balance_preset_b(admin_id: int) -> Dict[str, Any]:
    from game.admin_balance import apply_preset_b, build_balance_hud_snapshot

    settings = apply_preset_b()
    audit(int(admin_id), "balance_preset_b", target_type="system")
    hud = build_balance_hud_snapshot(int(admin_id))
    return _ok(settings=settings, hud=hud)


# ---------------------------------------------------------------------------
# Server settings, resources, wipe, bans (Admin → Server tab)
# ---------------------------------------------------------------------------

def api_get_universe_news() -> Dict[str, Any]:
    from game.universe_news import list_news, news_metadata

    return _ok(entries=list_news(limit=200, include_drafts=True), meta=news_metadata())


def _news_fields_from_body(body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": str(body.get("title") or "").strip(),
        "body": str(body.get("body") or "").strip(),
        "set_banner": body.get("set_banner") in (True, 1, "1", "true", "on"),
        "is_draft": body.get("is_draft") in (True, 1, "1", "true", "on"),
        "version_tag": str(body.get("version_tag") or "").strip(),
        "category": str(body.get("category") or "").strip(),
        "badge": str(body.get("badge") or "").strip(),
        "image_url": str(body.get("image_url") or "").strip(),
        "is_major_release": body.get("is_major_release") in (True, 1, "1", "true", "on"),
    }


def api_create_universe_news(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.universe_news import create_news

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")
    fields = _news_fields_from_body(body)
    if not fields["body"] and not fields["is_draft"]:
        return _err("body_required", "News body is required")
    try:
        entry = create_news(created_by=int(admin_id), **fields)
    except ValueError:
        return _err("body_required", "News body is required")
    audit(
        int(admin_id),
        "universe_news_create",
        target_type="system",
        payload={"news_id": entry["id"], "title": entry["title"], "version_tag": entry.get("version_tag")},
    )
    return _ok(entry=entry)


def api_update_universe_news(admin_id: int, news_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.universe_news import update_news

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")
    fields = _news_fields_from_body(body)
    publish = body.get("publish") in (True, 1, "1", "true", "on")
    entry = update_news(
        int(news_id),
        title=fields["title"] or None,
        body=fields["body"] if "body" in body else None,
        set_banner=fields["set_banner"] if body.get("set_banner") is not None else None,
        is_draft=fields["is_draft"] if body.get("is_draft") is not None else None,
        version_tag=fields["version_tag"] if "version_tag" in body else None,
        category=fields["category"] if "category" in body else None,
        badge=fields["badge"] if "badge" in body else None,
        image_url=fields["image_url"] if "image_url" in body else None,
        is_major_release=fields["is_major_release"] if "is_major_release" in body else None,
        publish=publish,
    )
    if not entry:
        return _err("not_found", "News entry not found")
    audit(int(admin_id), "universe_news_update", target_type="system", payload={"news_id": entry["id"]})
    return _ok(entry=entry)


def api_import_changelog(admin_id: int) -> Dict[str, Any]:
    from game.universe_news import import_changelog_markdown

    result = import_changelog_markdown(created_by=int(admin_id))
    if not result.get("ok"):
        return _err(str(result.get("error") or "import_failed"), str(result.get("path") or ""))
    audit(
        int(admin_id),
        "universe_news_import_changelog",
        target_type="system",
        payload={"inserted": result.get("inserted"), "skipped_versions": result.get("skipped_versions")},
    )
    return _ok(**result)


def api_import_git_history(admin_id: int) -> Dict[str, Any]:
    from game.universe_news import import_git_history

    result = import_git_history(created_by=int(admin_id))
    if not result.get("ok"):
        return _err(str(result.get("error") or "import_failed"), str(result.get("repo_root") or ""))
    audit(
        int(admin_id),
        "universe_news_import_git",
        target_type="system",
        payload={"inserted": result.get("inserted"), "skipped": result.get("skipped")},
    )
    return _ok(**result)


def api_import_full_history(admin_id: int) -> Dict[str, Any]:
    from game.universe_news import import_full_history

    result = import_full_history(created_by=int(admin_id))
    if not result.get("ok"):
        return _err(str(result.get("error") or "import_failed"), str(result.get("path") or result.get("repo_root") or ""))
    audit(
        int(admin_id),
        "universe_news_import_full",
        target_type="system",
        payload={"inserted": result.get("inserted")},
    )
    return _ok(**result)


def api_reclassify_news_audience(admin_id: int) -> Dict[str, Any]:
    from game.universe_news import reclassify_news_audience, sync_release_dates

    result = reclassify_news_audience()
    dates = sync_release_dates()
    audit(
        int(admin_id),
        "universe_news_reclassify_audience",
        target_type="system",
        payload={"updated": result.get("updated"), "dates_updated": dates.get("updated")},
    )
    return _ok(**result, release_dates=dates)


def api_repository_history_audit(admin_id: int) -> Dict[str, Any]:
    from game.universe_news import repository_history_audit

    return _ok(**repository_history_audit())


def api_set_universe_news_banner(admin_id: int, news_id: int) -> Dict[str, Any]:
    from game.universe_news import set_banner

    entry = set_banner(int(news_id))
    if not entry:
        return _err("not_found", "News entry not found")
    audit(
        int(admin_id),
        "universe_news_banner",
        target_type="system",
        payload={"news_id": entry["id"]},
    )
    return _ok(entry=entry)


def api_delete_universe_news(admin_id: int, news_id: int) -> Dict[str, Any]:
    from game.universe_news import delete_news

    if not delete_news(int(news_id)):
        return _err("not_found", "News entry not found")
    audit(int(admin_id), "universe_news_delete", target_type="system", payload={"news_id": int(news_id)})
    return _ok(deleted=True)


def api_get_server_settings() -> Dict[str, Any]:
    from game.admin import get_admin_settings

    return _ok(settings=get_admin_settings())


def api_save_server_settings(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.admin import get_admin_settings, update_admin_settings

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")
    update_admin_settings(body)
    settings = get_admin_settings()
    audit(
        int(admin_id),
        "server_settings_save",
        target_type="system",
        payload={"keys": sorted(body.keys())},
    )
    return _ok(settings=settings)


def api_apply_resource_tools(admin_id: int, body: Dict[str, Any], actor_user_id: int) -> Dict[str, Any]:
    from game.admin import handle_resource_tools

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")
    handle_resource_tools(body, current_user_id=int(actor_user_id))
    audit(
        int(admin_id),
        "resource_tools",
        target_type="system",
        payload={
            "metal_delta": body.get("metal_delta"),
            "crystal_delta": body.get("crystal_delta"),
            "fuel_cells_delta": body.get("fuel_cells_delta"),
            "apply_all": body.get("resource_apply_all"),
            "player_id": body.get("resource_player_id"),
        },
    )
    return _ok(applied=True)


def api_broadcast_system_messages(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.messages import admin_broadcast_system_message

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")
    confirm = body.get("confirm") or body.get("confirm_text")
    if not validate_confirm("broadcast_messages", confirm):
        return _err("confirm_required", "Type SEND SYSTEM BROADCAST to confirm.")
    result = admin_broadcast_system_message(
        str(body.get("subject") or ""),
        str(body.get("body") or ""),
    )
    if not result.get("ok"):
        err = str(result.get("error") or "error")
        return _err(err, err)
    delivered = int((result.get("data") or {}).get("delivered_count") or 0)
    audit(
        int(admin_id),
        "messages_broadcast",
        target_type="system",
        payload={
            "subject": str(body.get("subject") or "")[:120],
            "delivered_count": delivered,
        },
    )
    return _ok(delivered_count=delivered)


def api_wipe_universe(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Deprecated legacy wipe — dev-only. Use api_universe_reset_keep_inventory in production."""
    from game.admin import wipe_universe

    if is_production():
        return _err(
            "deprecated",
            "Legacy wipe is disabled in production. Use POST /api/admin/universe-reset instead.",
        )
    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")
    if body.get("wipe_confirm") not in (True, 1, "1", "true", "on"):
        return _err("confirm_required", "wipe_confirm required")
    wipe_universe(body)
    audit(
        int(admin_id),
        "universe_wipe",
        target_type="system",
        payload={"keys": sorted(body.keys()), "deprecated": True},
    )
    return _ok(wiped=True, deprecated=True)


def api_universe_reset_keep_inventory(admin_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    from game.admin_universe_reset import execute_universe_reset_keep_inventory

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")
    if not validate_confirm("universe_reset_keep_inventory", body.get("confirm_text")):
        return _err("confirm_required", "Type RESET UNIVERSE KEEP INVENTORY to confirm.")

    try:
        result = execute_universe_reset_keep_inventory()
    except Exception as exc:
        return _err("reset_failed", str(exc))

    audit(
        int(admin_id),
        "universe_reset_keep_inventory",
        target_type="system",
        payload=result,
    )
    return _ok(**result)


def api_get_bans() -> Dict[str, Any]:
    from game.admin import get_ban_list

    return _ok(bans=get_ban_list())


# ---------------------------------------------------------------------------
# Galactic diplomacy test controls (GC-721J)
# ---------------------------------------------------------------------------

def _diplomacy_definition_options(conn: sqlite3.Connection) -> Dict[str, List[Dict[str, str]]]:
    from game.galactic_diplomacy import (
        list_emergency_definitions,
        list_personality_definitions,
        list_resolution_definitions,
    )

    return {
        "personalities": [
            {
                "key": str(row.get("personality_key") or ""),
                "label_key": str(row.get("label_key") or ""),
            }
            for row in list_personality_definitions(conn=conn)
            if row.get("personality_key")
        ],
        "resolutions": [
            {
                "key": str(row.get("resolution_key") or ""),
                "label_key": str(row.get("label_key") or ""),
            }
            for row in list_resolution_definitions(conn=conn)
            if row.get("resolution_key")
        ],
        "emergencies": [
            {
                "key": str(row.get("emergency_key") or ""),
                "label_key": str(row.get("label_key") or ""),
            }
            for row in list_emergency_definitions(conn=conn)
            if row.get("emergency_key")
        ],
    }


def _diplomacy_active_chip(
    *,
    layer: str,
    key: str,
    definition: Optional[Dict[str, Any]],
    started_at: Any = None,
    ends_at: Any = None,
) -> Optional[Dict[str, Any]]:
    item_key = str(key or "").strip().lower()
    if not item_key:
        return None
    defn = definition if isinstance(definition, dict) else {}
    return {
        "type": layer,
        "key": item_key,
        "label_key": str(defn.get("label_key") or ""),
        "started_at": int(started_at) if started_at not in (None, "") else None,
        "ends_at": int(ends_at) if ends_at not in (None, "") else None,
    }


def api_get_galactic_diplomacy_state(galaxy: Any) -> Dict[str, Any]:
    from game.galactic_diplomacy import (
        get_active_emergency,
        get_active_resolution,
        get_galaxy_personality,
        schema_ready,
    )
    from game.galactic_diplomacy.blocs import normalize_galaxy

    conn = db()
    try:
        galaxy_id = normalize_galaxy(galaxy, conn=conn)
        if galaxy_id is None:
            return _err("invalid_galaxy", "invalid_galaxy")
        if not schema_ready(conn=conn):
            return _err("schema_not_ready", "schema_not_ready")

        personality_state = get_galaxy_personality(galaxy_id, conn=conn)
        resolution_state = get_active_resolution(galaxy_id, conn=conn)
        emergency_state = get_active_emergency(galaxy_id, conn=conn)

        personality = _diplomacy_active_chip(
            layer="personality",
            key=str(personality_state.get("personality_key") or ""),
            definition=personality_state.get("definition"),
            started_at=personality_state.get("active_since"),
        )
        resolution = None
        if resolution_state:
            resolution = _diplomacy_active_chip(
                layer="resolution",
                key=str(resolution_state.get("resolution_key") or ""),
                definition=resolution_state.get("definition"),
                started_at=resolution_state.get("started_at"),
                ends_at=resolution_state.get("ends_at"),
            )
        emergency = None
        if emergency_state:
            emergency = _diplomacy_active_chip(
                layer="emergency",
                key=str(emergency_state.get("emergency_key") or ""),
                definition=emergency_state.get("definition"),
                started_at=emergency_state.get("started_at"),
                ends_at=emergency_state.get("ends_at"),
            )

        return _ok(
            galaxy=int(galaxy_id),
            personality=personality,
            resolution=resolution,
            emergency=emergency,
            options=_diplomacy_definition_options(conn),
        )
    finally:
        conn.close()


def _diplomacy_value_error(exc: ValueError) -> Dict[str, Any]:
    code = str(exc.args[0] if exc.args else "invalid_request")
    return _err(code, code)


def api_set_galactic_diplomacy_personality(
    admin_id: int,
    galaxy: Any,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    from game.galactic_diplomacy import set_galaxy_personality

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")

    clear = body.get("clear") in (True, 1, "1", "true", "on")
    personality_key = "" if clear else str(body.get("personality_key") or "").strip()

    conn = db()
    try:
        try:
            result = set_galaxy_personality(
                galaxy,
                personality_key,
                score=int(body.get("score") or 0),
                conn=conn,
            )
        except ValueError as exc:
            return _diplomacy_value_error(exc)

        audit(
            int(admin_id),
            "galactic_diplomacy_clear_personality" if clear else "galactic_diplomacy_set_personality",
            target_type="galaxy",
            target_id=int(result["galaxy"]),
            payload={
                "galaxy": int(result["galaxy"]),
                "personality_key": str(result.get("personality_key") or ""),
                "cleared": clear,
            },
        )
    finally:
        conn.close()

    return api_get_galactic_diplomacy_state(galaxy)


def api_set_galactic_diplomacy_resolution(
    admin_id: int,
    galaxy: Any,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    from game.galactic_diplomacy import clear_active_resolution, set_active_resolution
    from game.galactic_diplomacy.blocs import normalize_galaxy

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")

    clear = body.get("clear") in (True, 1, "1", "true", "on")
    resolution_key = str(body.get("resolution_key") or "").strip()

    conn = db()
    try:
        galaxy_id = normalize_galaxy(galaxy, conn=conn)
        if galaxy_id is None:
            return _err("invalid_galaxy", "invalid_galaxy")
        try:
            if clear:
                clear_active_resolution(galaxy_id, conn=conn)
                active_key = ""
            else:
                active = set_active_resolution(galaxy_id, resolution_key, conn=conn)
                active_key = str(active.get("resolution_key") or "")
        except ValueError as exc:
            return _diplomacy_value_error(exc)

        audit(
            int(admin_id),
            "galactic_diplomacy_clear_resolution" if clear else "galactic_diplomacy_set_resolution",
            target_type="galaxy",
            target_id=int(galaxy_id),
            payload={
                "galaxy": int(galaxy_id),
                "resolution_key": active_key,
                "cleared": clear,
            },
        )
    finally:
        conn.close()

    return api_get_galactic_diplomacy_state(galaxy)


def api_set_galactic_diplomacy_emergency(
    admin_id: int,
    galaxy: Any,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    from game.galactic_diplomacy import clear_active_emergency, set_active_emergency
    from game.galactic_diplomacy.blocs import normalize_galaxy

    if not isinstance(body, dict):
        return _err("invalid_payload", "Expected JSON object")

    clear = body.get("clear") in (True, 1, "1", "true", "on")
    emergency_key = str(body.get("emergency_key") or "").strip()

    conn = db()
    try:
        galaxy_id = normalize_galaxy(galaxy, conn=conn)
        if galaxy_id is None:
            return _err("invalid_galaxy", "invalid_galaxy")
        try:
            if clear:
                clear_active_emergency(galaxy_id, conn=conn)
                active_key = ""
            else:
                active = set_active_emergency(galaxy_id, emergency_key, conn=conn)
                active_key = str(active.get("emergency_key") or "")
        except ValueError as exc:
            return _diplomacy_value_error(exc)

        audit(
            int(admin_id),
            "galactic_diplomacy_clear_emergency" if clear else "galactic_diplomacy_set_emergency",
            target_type="galaxy",
            target_id=int(galaxy_id),
            payload={
                "galaxy": int(galaxy_id),
                "emergency_key": active_key,
                "cleared": clear,
            },
        )
    finally:
        conn.close()

    return api_get_galactic_diplomacy_state(galaxy)

