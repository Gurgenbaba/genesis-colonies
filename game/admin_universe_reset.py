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
    "chronicle_entries",
    "chat_messages",
    "chat_whisper_state",
    "chat_user_state",
    "chat_mutes",
    "chat_bans",
    "chat_room_members",
    "chat_rooms",
    "alliance_war_events",
    "alliance_war_stats",
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

# Selectable reset domains (admin checkboxes). Every CLEAR_TABLES_ORDER table maps to one domain.
RESET_DOMAIN_ORDER: tuple[str, ...] = (
    "colonies",
    "queues",
    "fleets",
    "account_research",
    "messages",
    "alliances",
    "economy",
    "combat",
    "rankings",
    "diplomacy",
    "referrals",
    "runtime",
)

# Domains that change persisted scores — trigger full recompute + rank refresh after reset.
RANKING_REFRESH_DOMAINS: frozenset[str] = frozenset(
    {
        "colonies",
        "rankings",
        "fleets",
        "combat",
        "account_research",
    }
)

RESET_DOMAIN_LABEL_KEYS: Dict[str, str] = {
    "colonies": "admin_reset_domain_colonies",
    "queues": "admin_reset_domain_queues",
    "fleets": "admin_reset_domain_fleets",
    "account_research": "admin_reset_domain_account_research",
    "messages": "admin_reset_domain_messages",
    "alliances": "admin_reset_domain_alliances",
    "economy": "admin_reset_domain_economy",
    "combat": "admin_reset_domain_combat",
    "rankings": "admin_reset_domain_rankings",
    "diplomacy": "admin_reset_domain_diplomacy",
    "referrals": "admin_reset_domain_referrals",
    "runtime": "admin_reset_domain_runtime",
}

RESET_DOMAIN_DEFAULT_LABELS: Dict[str, str] = {
    "colonies": "Planeten & Kolonien (Gebäude, Schiffe, Verteidigung)",
    "queues": "Warteschlangen (Bau, Forschung, Werft, Verteidigung)",
    "fleets": "Flotten & Flotten-Presets",
    "account_research": "Account-Forschung",
    "messages": "Nachrichten & Chat",
    "alliances": "Allianzen",
    "economy": "Handel, Auktion & Tausch-Logs",
    "combat": "Kampfberichte & Hall of Fame",
    "rankings": "Ranglisten",
    "diplomacy": "Galaktische Diplomatie & Welt-Fortschritt",
    "referrals": "Referrals & Vote-Rewards",
    "runtime": "Runtime-Cache & System-Logs",
}

RESET_DOMAINS: Dict[str, tuple[str, ...]] = {
    "queues": (
        "shipyard_queue",
        "defense_queue",
        "build_queue",
        "research_queue",
        "planet_evolution_queue",
        "planet_conversion_queue",
        "planet_ascension_queue",
        "planet_research_queue",
    ),
    "fleets": (
        "fleet_movements",
        "fleet_batches",
        "fleet_presets",
    ),
    "colonies": (
        "planet_ships",
        "planet_defense",
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
        "planet_buildings",
        "planets",
    ),
    "economy": (
        "auction_house_bids",
        "auction_house_listings",
        "planet_trade_routes",
        "planet_import_demands",
        "exchange_log",
    ),
    "messages": (
        "player_messages",
        "chat_messages",
        "chat_whisper_state",
        "chat_user_state",
        "chat_mutes",
        "chat_bans",
        "chat_room_members",
        "chat_rooms",
        "messages",
    ),
    "alliances": (
        "alliance_members",
        "alliances",
    ),
    "combat": (
        "alliance_war_events",
        "alliance_war_stats",
        "combat_hall_of_fame",
        "chronicle_entries",
        "combat_reports",
        "battle_logs",
    ),
    "diplomacy": (
        "gd_votes",
        "gd_cycles",
        "gd_resolution_state",
        "gd_emergency_state",
        "gd_galaxy_personality_state",
        "gd_galaxy_state",
        "gd_alliance_blocs",
        "world_claims",
        "world_progress",
    ),
    "referrals": (
        "vote_rewards",
        "referral_reward_claims",
        "player_referrals",
    ),
    "account_research": ("research_levels",),
    "rankings": ("player_scores",),
    "runtime": (
        "action_idempotency",
        "runtime_state",
        "container_open_log",
        "logs",
    ),
}


def _assert_reset_domain_coverage() -> None:
    mapped: Dict[str, str] = {}
    for domain, tables in RESET_DOMAINS.items():
        for table in tables:
            if table in mapped:
                raise RuntimeError(f"reset table {table!r} mapped to both {mapped[table]!r} and {domain!r}")
            mapped[table] = domain
    missing = [t for t in CLEAR_TABLES_ORDER if t not in mapped]
    if missing:
        raise RuntimeError(f"reset domains missing tables: {missing}")
    extra = sorted(set(mapped) - set(CLEAR_TABLES_ORDER))
    if extra:
        raise RuntimeError(f"reset domains reference unknown tables: {extra}")


_assert_reset_domain_coverage()


def default_reset_options() -> Dict[str, bool]:
    return {key: True for key in RESET_DOMAIN_ORDER}


def normalize_reset_options(raw: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    if not isinstance(raw, dict) or not raw:
        return default_reset_options()
    out = default_reset_options()
    for key in RESET_DOMAIN_ORDER:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def tables_for_reset_options(options: Dict[str, bool]) -> Set[str]:
    tables: Set[str] = set()
    for domain in RESET_DOMAIN_ORDER:
        if not options.get(domain):
            continue
        tables.update(RESET_DOMAINS.get(domain, ()))
    return tables


def reset_domain_catalog() -> List[Dict[str, str]]:
    return [
        {
            "key": key,
            "label_key": RESET_DOMAIN_LABEL_KEYS[key],
            "default_label": RESET_DOMAIN_DEFAULT_LABELS[key],
        }
        for key in RESET_DOMAIN_ORDER
    ]


def discover_inventory_tables(conn: sqlite3.Connection) -> Set[str]:
    """Return existing tables that store player item ownership (must be preserved)."""
    from game.db import get_db_backend

    found: Set[str] = set()
    if get_db_backend() == "postgres":
        rows = conn.execute(
            """
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name;"
        ).fetchall()
    for row in rows:
        name = str((row["name"] if hasattr(row, "keys") else row[0]) or "")
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
    from game.models import ensure_player_and_homeworld
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
        player_ids.append(pid)

    return player_ids


def ranking_refresh_needed(options: Dict[str, bool]) -> bool:
    return any(options.get(domain) for domain in RANKING_REFRESH_DOMAINS)


def _refresh_rankings_after_universe_reset(
    conn: sqlite3.Connection,
    options: Dict[str, bool],
) -> Optional[Dict[str, Any]]:
    if not ranking_refresh_needed(options):
        return None
    from game.ranking import recalculate_all_rankings

    return recalculate_all_rankings(refresh_scores=True, conn=conn)


def execute_universe_reset_keep_inventory(
    *,
    skip_backup: bool = False,
    backup_dir: Optional[Path] = None,
    reset_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Season reset: wipe selected gameplay domains, preserve accounts + inventory.

    When ``colonies`` is enabled, homeworlds are rebuilt. Returns summary for API/audit.
    """
    options = normalize_reset_options(reset_options)
    if not any(options.values()):
        raise ValueError("at least one reset domain must be selected")

    tables_to_clear = tables_for_reset_options(options)

    backup_path: Optional[str] = None
    if not skip_backup:
        backup_file = create_pre_reset_backup(backups_dir=backup_dir)
        backup_path = str(backup_file)

    conn = db()
    deleted_counts: Dict[str, int] = {}
    inventory_tables = sorted(discover_inventory_tables(conn))
    preserved = set(PRESERVED_TABLES) | set(inventory_tables)
    player_ids: List[int] = []
    ranking_refresh: Optional[Dict[str, Any]] = None
    attack_protection: Optional[Dict[str, Any]] = None

    try:
        begin_write_transaction(conn)
        cur = conn.cursor()

        for table in CLEAR_TABLES_ORDER:
            if table not in tables_to_clear:
                continue
            if table in preserved:
                continue
            deleted_counts[table] = _clear_table(cur, conn, table)

        if options.get("colonies"):
            _reset_player_progress_columns(conn)
            player_ids = _rebuild_homeworlds(conn)

        ranking_refresh = _refresh_rankings_after_universe_reset(conn, options)
        if ranking_refresh and not ranking_refresh.get("ok", True):
            errors = ranking_refresh.get("errors") or []
            raise RuntimeError(
                "ranking refresh failed after universe reset"
                + (f": {errors[0]}" if errors else "")
            )

        from game.fleet_mission_locks import apply_reset_attack_protection

        attack_protection = apply_reset_attack_protection(conn=conn)

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
        "reset_options": options,
        "reset_domains_applied": [k for k in RESET_DOMAIN_ORDER if options.get(k)],
        "players_reinitialized": len(player_ids),
        "inventory_tables_preserved": inventory_tables,
        "ranking_refresh": ranking_refresh,
        "attack_protection": attack_protection,
        "timestamp": int(time.time()),
    }
