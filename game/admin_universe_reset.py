"""
GC-RESET — Season / universe reset while preserving accounts and inventory.

Owner module for admin universe reset (keep inventory). Legacy wipe remains in game.admin.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from game.db import begin_write_transaction, column_exists, commit, db, resolve_db_path, rollback, table_exists

CONFIRM_PHRASE = "RESET UNIVERSE KEEP INVENTORY"

# Tables that must never be cleared by this reset.
PRESERVED_TABLES: frozenset[str] = frozenset(
    {
        "users",
        "players",
        "player_inventory_items",
        "lootbox_inventory",
        "player_unlocks",
        "game_settings",
        "migration_history",
        "schema_migrations",
        "admin_audit_log",
        "account_audit_log",
        "support_tickets",
        "support_messages",
        "vote_providers",
        "universe_news",
        "player_cards",
        "player_card_badges",
        "player_card_unlocked_badges",
        "player_avatars",
        "player_referral_codes",
        "bans",
        # Static definition catalogs (not per-season state)
        "pe_trait_definitions",
        "pe_research_definitions",
        "pe_specialization_definitions",
        "pe_policy_definitions",
        "pe_event_definitions",
        "pe_discovery_definitions",
        "pe_special_resource_definitions",
        "pe_production_chain_definitions",
        "pe_ascension_definitions",
        "gd_directive_definitions",
        "gd_bloc_definitions",
        "gd_resolution_definitions",
        "gd_emergency_definitions",
        "gd_galaxy_personality_definitions",
    }
)

_INVENTORY_TABLE_HINTS = (
    "inventory",
    "lootbox",
    "player_items",
)

# Delete order: children before parents (FK-safe).
CLEAR_TABLES_ORDER: tuple[str, ...] = (
    "auction_house_bids",
    "auction_house_listings",
    "fleet_movements",
    "fleet_batches",
    "fleet_presets",
    "shipyard_queue",
    "defense_queue",
    "build_queue",
    "research_queue",
    "planet_evolution_queue",
    "planet_ships",
    "planet_defense",
    "planet_conversion_queue",
    "planet_ascension_queue",
    "planet_research_queue",
    "planet_trade_routes",
    "planet_import_demands",
    "planet_events",
    "planet_discoveries",
    "planet_failure_states",
    "planet_history",
    "planet_legacy_tags",
    "planet_special_resources",
    "planet_production_chains",
    "planet_locked_choices",
    "planet_policies",
    "planet_culture",
    "planet_research_levels",
    "planet_mechanics",
    "planet_dna",
    "debris_fields",
    "exchange_log",
    "player_messages",
    "chat_messages",
    "chat_whisper_state",
    "chat_user_state",
    "chat_mutes",
    "chat_bans",
    "chat_room_members",
    "chat_rooms",
    "alliance_members",
    "alliances",
    "combat_hall_of_fame",
    "gd_votes",
    "gd_cycles",
    "gd_resolution_state",
    "gd_emergency_state",
    "gd_galaxy_personality_state",
    "gd_galaxy_state",
    "gd_alliance_blocs",
    "world_claims",
    "world_progress",
    "vote_rewards",
    "referral_reward_claims",
    "player_referrals",
    "research_levels",
    "player_scores",
    "planet_buildings",
    "planets",
    "action_idempotency",
    "runtime_state",
    "container_open_log",
    "messages",
    "combat_reports",
    "logs",
    "battle_logs",
)


def discover_inventory_tables(conn: sqlite3.Connection) -> Set[str]:
    """Return existing tables that store player item ownership (must be preserved)."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name;")
    found: Set[str] = set()
    for row in cur.fetchall():
        name = str(row[0] or "")
        lower = name.lower()
        if name in PRESERVED_TABLES:
            found.add(name)
            continue
        if any(hint in lower for hint in _INVENTORY_TABLE_HINTS):
            if table_exists(conn, name):
                found.add(name)
    return found


def create_pre_reset_backup(
    *,
    db_path: Optional[Path] = None,
    backups_dir: Optional[Path] = None,
) -> Path:
    """Copy the SQLite database to backups/pre_universe_reset_<timestamp>.db."""
    src_path = Path(db_path or resolve_db_path())
    if not src_path.is_file():
        raise FileNotFoundError(f"database not found: {src_path}")

    root = src_path.resolve().parent.parent if src_path.parent.name == "data" else src_path.resolve().parent
    dest_dir = Path(backups_dir or (root / "backups"))
    dest_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest_path = dest_dir / f"pre_universe_reset_{stamp}.db"

    src_conn = sqlite3.connect(str(src_path))
    try:
        dest_conn = sqlite3.connect(str(dest_path))
        try:
            src_conn.backup(dest_conn)
            dest_conn.commit()
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    return dest_path


def _clear_table(cur: sqlite3.Cursor, conn: sqlite3.Connection, table: str) -> int:
    if table in PRESERVED_TABLES:
        return 0
    if not table_exists(conn, table):
        return 0
    cur.execute(f"DELETE FROM {table};")
    return int(cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0)


def _reset_player_progress_columns(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    sets: List[str] = []
    if column_exists(conn, "players", "active_planet_id"):
        sets.append("active_planet_id = NULL")
    if column_exists(conn, "players", "exchange_daily_used"):
        sets.append("exchange_daily_used = 0")
    if column_exists(conn, "players", "exchange_daily_reset_at"):
        sets.append("exchange_daily_reset_at = 0")
    if sets:
        cur.execute(f"UPDATE players SET {', '.join(sets)};")


def _rebuild_homeworlds(conn: sqlite3.Connection) -> List[int]:
    from game.models import ensure_player_and_homeworld, recompute_and_upsert_score
    from game.planet_evolution.repository import set_active_planet_id

    cur = conn.cursor()
    cur.execute("SELECT id, name, is_admin FROM players ORDER BY id ASC;")
    rows = cur.fetchall()
    player_ids: List[int] = []

    for row in rows:
        pid = int(row["id"])
        pname = str(row["name"] or f"Player-{pid}")
        is_admin = int(row["is_admin"] or 0)
        ensure_player_and_homeworld(
            player_id=pid,
            player_name=pname,
            is_admin=is_admin,
            conn=conn,
        )
        cur.execute(
            "SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
            (pid,),
        )
        hw = cur.fetchone()
        if not hw:
            raise RuntimeError(f"homeworld_missing_after_reset player_id={pid}")
        hw_id = int(hw["id"])
        set_active_planet_id(pid, hw_id, conn)
        recompute_and_upsert_score(pid, conn=conn)
        player_ids.append(pid)

    return player_ids


def execute_universe_reset_keep_inventory(
    *,
    skip_backup: bool = False,
    backup_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Season reset: wipe gameplay state, preserve accounts + inventory, rebuild homeworlds.

    Returns summary dict for API response and audit payload.
    """
    backup_path: Optional[str] = None
    if not skip_backup:
        backup_file = create_pre_reset_backup(backups_dir=backup_dir)
        backup_path = str(backup_file)

    conn = db()
    deleted_counts: Dict[str, int] = {}
    inventory_tables = sorted(discover_inventory_tables(conn))
    preserved = set(PRESERVED_TABLES) | set(inventory_tables)

    try:
        begin_write_transaction(conn)
        cur = conn.cursor()

        for table in CLEAR_TABLES_ORDER:
            if table in preserved:
                continue
            deleted_counts[table] = _clear_table(cur, conn, table)

        _reset_player_progress_columns(conn)
        player_ids = _rebuild_homeworlds(conn)

        try:
            from game.ranking import recalculate_ranks

            recalculate_ranks(conn=conn)
        except Exception:
            pass

        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return {
        "action": "universe_reset_keep_inventory",
        "backup_path": backup_path,
        "deleted_tables": deleted_counts,
        "players_reinitialized": len(player_ids),
        "inventory_tables_preserved": inventory_tables,
        "timestamp": int(time.time()),
    }
