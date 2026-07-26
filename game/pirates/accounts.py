"""Faction bot accounts for pirate raids (EPIC-21).

Reserved human-visible AI commanders: ranking, galaxy, player card.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# player_mode shown on PlayerCard / ranking / galaxy
PLAYER_MODE_AI_PIRATE = "ai_pirate"
AI_KIND_PIRATE_FACTION = "pirate_faction"

# Discoverable homeworlds (Galaxy 1 — distributed, not one campable belt).
FACTION_HOMEWORLDS: Dict[str, Tuple[int, int, int]] = {
    "crimson_corsairs": (1, 100, 8),
    "iron_collective": (1, 200, 9),
    "void_cult": (1, 300, 8),
    "nomad_swarm": (1, 400, 9),
    "ash_raiders": (1, 450, 7),
    "salt_cartel": (1, 480, 6),
}

FACTION_BOTS: Dict[str, Dict[str, str]] = {
    "crimson_corsairs": {
        "username": "gc_pirate_crimson",
        "display_name": "Crimson Corsairs",
        "name_key": "pirate_faction_crimson_corsairs",
        "commander_key": "pirate_commander_crimson",
        "desc_key": "pirate_faction_crimson_corsairs_desc",
        "personality": "aggressive",
        "mode_key": "pirate_ai_mode_aggressive",
    },
    "iron_collective": {
        "username": "gc_pirate_iron",
        "display_name": "Iron Collective",
        "name_key": "pirate_faction_iron_collective",
        "commander_key": "pirate_commander_iron",
        "desc_key": "pirate_faction_iron_collective_desc",
        "personality": "turtle",
        "mode_key": "pirate_ai_mode_turtle",
    },
    "void_cult": {
        "username": "gc_pirate_void",
        "display_name": "Void Cult",
        "name_key": "pirate_faction_void_cult",
        "commander_key": "pirate_commander_void",
        "desc_key": "pirate_faction_void_cult_desc",
        "personality": "spy",
        "mode_key": "pirate_ai_mode_spy",
    },
    "nomad_swarm": {
        "username": "gc_pirate_nomad",
        "display_name": "Nomad Swarm",
        "name_key": "pirate_faction_nomad_swarm",
        "commander_key": "pirate_commander_nomad",
        "desc_key": "pirate_faction_nomad_swarm_desc",
        "personality": "swarm",
        "mode_key": "pirate_ai_mode_swarm",
    },
    "ash_raiders": {
        "username": "gc_pirate_ash",
        "display_name": "Ash Raiders",
        "name_key": "pirate_faction_ash_raiders",
        "commander_key": "pirate_commander_ash",
        "desc_key": "pirate_faction_ash_raiders_desc",
        "personality": "elite",
        "mode_key": "pirate_ai_mode_aggressive",
    },
    "salt_cartel": {
        "username": "gc_pirate_salt",
        "display_name": "Salt Cartel",
        "name_key": "pirate_faction_salt_cartel",
        "commander_key": "pirate_commander_salt",
        "desc_key": "pirate_faction_salt_cartel_desc",
        "personality": "economy",
        "mode_key": "pirate_ai_mode_turtle",
    },
}

PIRATE_BOT_USERNAMES = frozenset(v["username"] for v in FACTION_BOTS.values())
_USERNAME_TO_FACTION = {v["username"]: k for k, v in FACTION_BOTS.items()}


def is_pirate_bot_player(player_id: int, *, conn) -> bool:
    cur = conn.execute(
        """
        SELECT u.username FROM users u
        WHERE u.id = ? LIMIT 1;
        """,
        (int(player_id),),
    )
    row = cur.fetchone()
    if not row:
        return False
    return str(row["username"] or "") in PIRATE_BOT_USERNAMES


def faction_key_for_username(username: str) -> Optional[str]:
    return _USERNAME_TO_FACTION.get(str(username or "").strip())


def get_pirate_ai_profile(player_id: int, *, conn) -> Optional[Dict[str, Any]]:
    """Public AI identity for ranking / galaxy / player card. None if human."""
    profiles = pirate_ai_profiles_by_ids([int(player_id)], conn=conn)
    return profiles.get(int(player_id))


def pirate_ai_profiles_by_ids(
    player_ids: Sequence[int],
    *,
    conn,
) -> Dict[int, Dict[str, Any]]:
    """Batch-resolve pirate AI profiles (empty dict for humans)."""
    ids = sorted({int(p) for p in player_ids if int(p) > 0})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(
        f"""
        SELECT u.id AS player_id, u.username, p.name AS display_name
        FROM users u
        LEFT JOIN players p ON p.id = u.id
        WHERE u.id IN ({placeholders})
          AND u.username IN ({",".join("?" for _ in PIRATE_BOT_USERNAMES)});
        """,
        tuple(ids) + tuple(sorted(PIRATE_BOT_USERNAMES)),
    )
    out: Dict[int, Dict[str, Any]] = {}
    for row in cur.fetchall():
        username = str(row["username"] or "")
        faction_key = faction_key_for_username(username)
        if not faction_key:
            continue
        meta = FACTION_BOTS[faction_key]
        personality = meta["personality"]
        try:
            from .bot_state import ensure_bot_state

            state = ensure_bot_state(
                conn, bot_player_id=int(row["player_id"]), faction_key=faction_key
            )
            if state.get("personality"):
                personality = str(state["personality"])
        except Exception:
            pass
        mode_key = {
            "aggressive": "pirate_ai_mode_aggressive",
            "turtle": "pirate_ai_mode_turtle",
            "spy": "pirate_ai_mode_spy",
            "swarm": "pirate_ai_mode_swarm",
            "elite": "pirate_ai_mode_aggressive",
            "economy": "pirate_ai_mode_turtle",
        }.get(personality, meta["mode_key"])
        out[int(row["player_id"])] = {
            "is_ai": True,
            "player_mode": PLAYER_MODE_AI_PIRATE,
            "ai_kind": AI_KIND_PIRATE_FACTION,
            "faction_key": faction_key,
            "username": username,
            "display_name": str(row["display_name"] or meta["display_name"]),
            "name_key": meta["name_key"],
            "commander_key": meta["commander_key"],
            "desc_key": meta["desc_key"],
            "personality": personality,
            "mode_key": mode_key,
            "badge_key": "pirate_ai_badge",
            "badge_title_key": "pirate_ai_badge_title",
            "player_mode_label_key": "pirate_ai_player_mode",
            "allows_chat": False,
            "allows_messages": False,
            "can_edit_card": False,
        }
    return out


def _touch_bot_presence(conn, player_id: int) -> None:
    """Keep AI commanders out of inactive ranking/galaxy styling."""
    now = time.time()
    try:
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id = ?;",
            (now, int(player_id)),
        )
    except Exception:
        logger.exception("pirate bot last_seen touch failed player=%s", player_id)


def _ensure_public_ai_card(conn, player_id: int, faction_key: str) -> None:
    """Public PlayerCard: AI identity is rendered via i18n keys, never raw keys in bio."""
    try:
        from ..playercard import ensure_player_card

        ensure_player_card(int(player_id), conn=conn)
        now = int(time.time())
        # Clear title/bio — template uses ai_* i18n keys (mode/faction/desc), not free text.
        conn.execute(
            """
            UPDATE player_cards
            SET is_public = 1,
                title = '',
                bio = '',
                updated_at = ?
            WHERE player_id = ?;
            """,
            (now, int(player_id)),
        )
        _ = faction_key
    except Exception:
        logger.exception("pirate AI playercard ensure failed player=%s", player_id)


def _try_place_homeworld(conn, planet_id: int, faction_key: str) -> None:
    """Move homeworld to the pirate belt when the slot is free."""
    coords = FACTION_HOMEWORLDS.get(str(faction_key))
    if not coords:
        return
    g, s, p = coords
    try:
        cur = conn.execute(
            """
            SELECT id FROM planets
            WHERE galaxy = ? AND system = ? AND position = ? AND id != ?
            LIMIT 1;
            """,
            (int(g), int(s), int(p), int(planet_id)),
        )
        if cur.fetchone():
            return
        conn.execute(
            """
            UPDATE planets
            SET galaxy = ?, system = ?, position = ?
            WHERE id = ?;
            """,
            (int(g), int(s), int(p), int(planet_id)),
        )
    except Exception:
        logger.exception("pirate homeworld place failed planet=%s", planet_id)


def ensure_faction_bot(faction_key: str, *, conn) -> Optional[Dict[str, Any]]:
    """Ensure reserved faction account + homeworld. Returns player/planet ids."""
    meta = FACTION_BOTS.get(str(faction_key))
    if not meta:
        return None
    from ..models import ensure_player_and_homeworld, get_planets_by_player, hash_password
    from ..ranking import ensure_player_score_row

    username = meta["username"]
    display = meta["display_name"]
    cur = conn.execute("SELECT id FROM users WHERE username = ? LIMIT 1;", (username,))
    row = cur.fetchone()
    if row:
        player_id = int(row["id"])
    else:
        cur = conn.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, email, email_verified)
            VALUES (?, ?, 0, NULL, 1);
            """,
            (username, hash_password(secrets.token_hex(24))),
        )
        player_id = int(cur.lastrowid)
        ensure_player_and_homeworld(
            player_id,
            player_name=display,
            conn=conn,
            homeworld_placement="random",
        )
        ensure_player_score_row(player_id, conn=conn)

    ensure_player_and_homeworld(player_id, player_name=display, conn=conn)
    conn.execute("UPDATE players SET name = ? WHERE id = ?;", (display, player_id))
    try:
        from .bot_state import ensure_bot_state

        ensure_bot_state(conn, bot_player_id=player_id, faction_key=faction_key)
    except Exception:
        logger.exception("ensure_bot_state failed faction=%s", faction_key)
    planets = get_planets_by_player(player_id, conn=conn) or []
    if not planets:
        return None
    home = planets[0]
    _try_place_homeworld(conn, int(home["id"]), faction_key)
    # Reload coords after possible move.
    planets = get_planets_by_player(player_id, conn=conn) or planets
    home = planets[0]
    # One-time Soft-On fuel seed only (GC-P27) — later fuel comes from production.
    try:
        from .bot_state import ensure_bot_state
        import json

        state = ensure_bot_state(conn, bot_player_id=player_id, faction_key=faction_key)
        mood = dict(state.get("mood") or {})
        if not mood.get("fuel_seeded"):
            cur = conn.execute(
                "SELECT COALESCE(fuel_cells, 0) AS fuel_cells FROM planets WHERE id = ?;",
                (int(home["id"]),),
            )
            fuel = int((cur.fetchone() or {"fuel_cells": 0})["fuel_cells"] or 0)
            if fuel < 500_000:
                conn.execute(
                    "UPDATE planets SET fuel_cells = ? WHERE id = ?;",
                    (500_000, int(home["id"])),
                )
            mood["fuel_seeded"] = True
            conn.execute(
                "UPDATE pirate_bot_state SET mood_json = ?, updated_at = ? WHERE bot_player_id = ?;",
                (json.dumps(mood), time.time(), player_id),
            )
    except Exception:
        logger.exception("pirate fuel seed failed player=%s", player_id)
    _touch_bot_presence(conn, player_id)
    _ensure_public_ai_card(conn, player_id, faction_key)
    ensure_player_score_row(player_id, conn=conn)
    return {
        "player_id": player_id,
        "planet_id": int(home["id"]),
        "faction_key": faction_key,
        "username": username,
        "display_name": display,
        "galaxy": int(home.get("galaxy") or 1),
        "system": int(home.get("system") or 1),
        "position": int(home.get("position") or 1),
        "player_mode": PLAYER_MODE_AI_PIRATE,
        "ai_kind": AI_KIND_PIRATE_FACTION,
    }


def ensure_all_faction_bots(*, conn) -> List[Dict[str, Any]]:
    out = []
    for key in FACTION_BOTS:
        bot = ensure_faction_bot(key, conn=conn)
        if bot:
            out.append(bot)
    return out


# Utility floor only (GC-P21+). Combat ships come from shipyard economy — no cheat restock.
HOME_PROBE_MIN = 8
HOME_RECLAIMER_MIN = 2
HOME_HAULER_MIN = 2
HOME_SEED_ARK_MIN = 1
# HW PE level 10 unlocks 2 colony slots → soft cap home+2 (GC-P20).
BOT_HOMEWORLD_LEVEL_FLOOR = 10


def ensure_bot_expansion_ready(conn, bot: Dict[str, Any]) -> Dict[str, Any]:
    """Raise homeworld PE level so classic colonize slots unlock (Expansion Protocol)."""
    from ..planet_evolution.planet_level import xp_threshold_for_level

    planet_id = int(bot.get("planet_id") or 0)
    if planet_id <= 0:
        return {"ok": False, "error": "no_planet"}
    cur = conn.execute(
        "SELECT COALESCE(planet_level, 1) AS planet_level, COALESCE(planet_xp, 0) AS planet_xp "
        "FROM planets WHERE id = ? LIMIT 1;",
        (planet_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "planet_missing"}
    level = int(row["planet_level"] or 1)
    if level >= BOT_HOMEWORLD_LEVEL_FLOOR:
        return {"ok": True, "raised": False, "planet_level": level}
    xp = max(int(row["planet_xp"] or 0), xp_threshold_for_level(BOT_HOMEWORLD_LEVEL_FLOOR))
    conn.execute(
        "UPDATE planets SET planet_level = ?, planet_xp = ? WHERE id = ?;",
        (BOT_HOMEWORLD_LEVEL_FLOOR, xp, planet_id),
    )
    return {"ok": True, "raised": True, "planet_level": BOT_HOMEWORLD_LEVEL_FLOOR}


def _bot_has_active_fleets(conn, player_id: int) -> bool:
    cur = conn.execute(
        """
        SELECT 1 FROM fleet_movements
        WHERE player_id = ? AND status IN ('outbound', 'holding', 'returning')
        LIMIT 1;
        """,
        (int(player_id),),
    )
    return cur.fetchone() is not None


def _home_ship_count(conn, planet_id: int) -> Dict[str, int]:
    cur = conn.execute(
        "SELECT ship_key, amount FROM planet_ships WHERE planet_id = ? AND amount > 0;",
        (int(planet_id),),
    )
    return {str(r["ship_key"]): int(r["amount"] or 0) for r in cur.fetchall()}


def _utility_home_stacks() -> Dict[str, int]:
    """Spy / recycle / colonize utility floor only — no combat template restock."""
    return {
        "veil_probe": HOME_PROBE_MIN,
        "harvest_reclaimer": HOME_RECLAIMER_MIN,
        "atlas_hauler": HOME_HAULER_MIN,
        "seed_ark": HOME_SEED_ARK_MIN,
    }


def ensure_bot_utility_fleet(
    conn,
    bot: Dict[str, Any],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """One-time Soft-On utility seed only (GC-P27). Never restocks every tick."""
    import json

    from .bot_state import ensure_bot_state

    player_id = int(bot["player_id"])
    faction_key = str(bot.get("faction_key") or "")
    state = ensure_bot_state(conn, bot_player_id=player_id, faction_key=faction_key)
    mood = dict(state.get("mood") or {})
    if mood.get("utility_seeded") and not force:
        return {"ok": True, "skipped": "already_seeded", "stocked": False}

    planet_id = int(bot["planet_id"])
    if not force and _bot_has_active_fleets(conn, player_id):
        return {"ok": True, "skipped": "fleets_active", "stocked": False}

    current = _home_ship_count(conn, planet_id)
    from ..fleet import set_planet_ships
    from ..ranking import recompute_and_upsert_score

    stacks = _utility_home_stacks()
    merged: Dict[str, int] = dict(current)
    for k, v in stacks.items():
        merged[k] = max(int(merged.get(k) or 0), int(v))
    set_planet_ships(planet_id, player_id, merged, conn=conn)
    mood["utility_seeded"] = True
    mood["utility_seeded_at"] = time.time()
    try:
        conn.execute(
            "UPDATE pirate_bot_state SET mood_json = ?, updated_at = ? WHERE bot_player_id = ?;",
            (json.dumps(mood), time.time(), player_id),
        )
    except Exception:
        pass
    try:
        recompute_and_upsert_score(player_id, conn=conn)
    except Exception:
        logger.exception("pirate utility fleet score refresh failed player=%s", player_id)
    _touch_bot_presence(conn, player_id)
    return {"ok": True, "stocked": True, "ships": merged}


def ensure_bot_home_fleet(
    conn,
    bot: Dict[str, Any],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Backward-compatible alias → utility floor only (GC-P21)."""
    return ensure_bot_utility_fleet(conn, bot, force=force)


def ensure_bot_planet_floor(conn, bot: Dict[str, Any]) -> Dict[str, Any]:
    """Guarantee faction bots always keep ≥1 planet (never vanish from the game)."""
    from ..models import ensure_player_and_homeworld, get_planets_by_player
    from .log import log_pirate_action

    player_id = int(bot["player_id"])
    faction_key = str(bot["faction_key"])
    planets = get_planets_by_player(player_id, conn=conn) or []
    if planets:
        home = planets[0]
        bot["planet_id"] = int(home["id"])
        bot["galaxy"] = int(home.get("galaxy") or 1)
        bot["system"] = int(home.get("system") or 1)
        bot["position"] = int(home.get("position") or 1)
        return {"ok": True, "restored": False, "planet_id": int(home["id"])}

    display = str(bot.get("display_name") or FACTION_BOTS.get(faction_key, {}).get("display_name") or faction_key)
    ensure_player_and_homeworld(player_id, player_name=display, conn=conn)
    planets = get_planets_by_player(player_id, conn=conn) or []
    if not planets:
        return {"ok": False, "error": "homeworld_missing"}
    home = planets[0]
    _try_place_homeworld(conn, int(home["id"]), faction_key)
    planets = get_planets_by_player(player_id, conn=conn) or planets
    home = planets[0]
    bot["planet_id"] = int(home["id"])
    bot["galaxy"] = int(home.get("galaxy") or 1)
    bot["system"] = int(home.get("system") or 1)
    bot["position"] = int(home.get("position") or 1)
    _touch_bot_presence(conn, player_id)
    try:
        ensure_bot_utility_fleet(conn, bot, force=True)
    except Exception:
        logger.exception("floor utility fleet restock failed faction=%s", faction_key)
    log_pirate_action(
        conn,
        kind="bot_planet_floor",
        faction_key=faction_key,
        bot_player_id=player_id,
        message=f"restored homeworld planet={bot['planet_id']}",
        severity="warn",
        payload={"planet_id": bot["planet_id"], "coords": [bot["galaxy"], bot["system"], bot["position"]]},
    )
    return {"ok": True, "restored": True, "planet_id": int(bot["planet_id"])}


def bootstrap_faction_bots(*, conn) -> List[Dict[str, Any]]:
    """Ensure all faction bots exist with utility fleets + economy seed (Soft-On / tick)."""
    bots = ensure_all_faction_bots(conn=conn)
    out: List[Dict[str, Any]] = []
    for bot in bots:
        try:
            ensure_bot_planet_floor(conn, bot)
        except Exception:
            logger.exception(
                "ensure_bot_planet_floor failed faction=%s", bot.get("faction_key")
            )
        try:
            ensure_bot_expansion_ready(conn, bot)
        except Exception:
            logger.exception(
                "ensure_bot_expansion_ready failed faction=%s", bot.get("faction_key")
            )
        try:
            from .economy import ensure_bot_resource_seed

            ensure_bot_resource_seed(conn, bot)
        except Exception:
            logger.exception(
                "ensure_bot_resource_seed failed faction=%s", bot.get("faction_key")
            )
        try:
            ensure_bot_utility_fleet(conn, bot, force=False)
        except Exception:
            logger.exception(
                "ensure_bot_utility_fleet failed faction=%s", bot.get("faction_key")
            )
        out.append(bot)
    return out


def list_bot_roster(*, conn) -> List[Dict[str, Any]]:
    """Admin Bot-Log roster: presence + outbound fleets."""
    out: List[Dict[str, Any]] = []
    for key in FACTION_BOTS:
        meta = FACTION_BOTS[key]
        cur = conn.execute(
            """
            SELECT u.id AS player_id, u.username, p.name AS display_name,
                   COALESCE(p.last_seen, 0) AS last_seen
            FROM users u
            LEFT JOIN players p ON p.id = u.id
            WHERE u.username = ?
            LIMIT 1;
            """,
            (meta["username"],),
        )
        row = cur.fetchone()
        if not row:
            out.append(
                {
                    "faction_key": key,
                    "username": meta["username"],
                    "display_name": meta["display_name"],
                    "exists": False,
                    "player_id": None,
                    "planet_id": None,
                    "galaxy": None,
                    "system": None,
                    "position": None,
                    "last_seen": None,
                    "ship_count": 0,
                    "outbound_fleets": 0,
                    "planet_count": 0,
                }
            )
            continue
        player_id = int(row["player_id"])
        from ..models import get_planets_by_player

        planets = get_planets_by_player(player_id, conn=conn) or []
        home = planets[0] if planets else None
        planet_id = int(home["id"]) if home else None
        ships = _home_ship_count(conn, planet_id) if planet_id else {}
        cur2 = conn.execute(
            """
            SELECT COUNT(*) AS c FROM fleet_movements
            WHERE player_id = ? AND status IN ('outbound', 'holding', 'returning');
            """,
            (player_id,),
        )
        fleets = int((cur2.fetchone() or {"c": 0})["c"] or 0)
        out.append(
            {
                "faction_key": key,
                "username": str(row["username"] or meta["username"]),
                "display_name": str(row["display_name"] or meta["display_name"]),
                "exists": True,
                "player_id": player_id,
                "planet_id": planet_id,
                "galaxy": int(home["galaxy"]) if home else None,
                "system": int(home["system"]) if home else None,
                "position": int(home["position"]) if home else None,
                "last_seen": float(row["last_seen"] or 0) or None,
                "ship_count": sum(ships.values()),
                "outbound_fleets": fleets,
                "planet_count": len(planets),
            }
        )
    return out