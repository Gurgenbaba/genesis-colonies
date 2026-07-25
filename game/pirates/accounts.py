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

# Discoverable homeworlds (Galaxy 1 — pirate belt).
FACTION_HOMEWORLDS: Dict[str, Tuple[int, int, int]] = {
    "crimson_corsairs": (1, 490, 8),
    "iron_collective": (1, 490, 9),
    "void_cult": (1, 491, 8),
    "nomad_swarm": (1, 491, 9),
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
    """Public PlayerCard with AI title/bio so the mode is obvious."""
    meta = FACTION_BOTS.get(str(faction_key)) or {}
    try:
        from ..playercard import ensure_player_card

        ensure_player_card(int(player_id), conn=conn)
        now = int(time.time())
        conn.execute(
            """
            UPDATE player_cards
            SET is_public = 1,
                title = ?,
                bio = ?,
                updated_at = ?
            WHERE player_id = ?;
            """,
            (
                "AI · Pirate Faction",
                f"Autonomous pirate AI ({faction_key}). Not a human player.",
                now,
                int(player_id),
            ),
        )
        # Prefer i18n keys stored as stable markers for UI overlay; title/bio are fallbacks.
        _ = meta
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
    # Keep fuel topped for raid flights.
    cur = conn.execute(
        "SELECT COALESCE(fuel_cells, 0) AS fuel_cells FROM planets WHERE id = ?;",
        (int(home["id"]),),
    )
    fuel = int((cur.fetchone() or {"fuel_cells": 0})["fuel_cells"] or 0)
    if fuel < 2_000_000:
        conn.execute(
            "UPDATE planets SET fuel_cells = ? WHERE id = ?;",
            (2_000_000, int(home["id"])),
        )
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


# Baseline home hangar so Soft-On bots show fleet score + can spy/raid/recycle.
HOME_FLEET_MIN_UNITS = 20
HOME_PROBE_MIN = 8
HOME_RECLAIMER_MIN = 2
HOME_HAULER_MIN = 2
HOME_FLEET_STRENGTH = 1  # same scale as weak base (_scale_stacks strength=1)


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


def _faction_home_stacks(conn, faction_key: str) -> Dict[str, int]:
    """Faction template stacks scaled for home presence (+ probe/reclaimer floors)."""
    from .bases import list_faction_defs

    stacks: Dict[str, int] = {}
    for f in list_faction_defs(conn):
        if f["faction_key"] == str(faction_key):
            # Match bases._scale_stacks(strength=1) without importing private helper.
            mult = 0.5 + 0.5 * max(1, HOME_FLEET_STRENGTH)
            for k, v in dict(f.get("fleet_stacks") or {}).items():
                n = int(max(0, round(int(v or 0) * mult)))
                if n > 0:
                    stacks[str(k)] = n
            break
    # Always keep spy/recycle capability on homeworlds.
    stacks["veil_probe"] = max(int(stacks.get("veil_probe") or 0), HOME_PROBE_MIN)
    stacks["harvest_reclaimer"] = max(
        int(stacks.get("harvest_reclaimer") or 0), HOME_RECLAIMER_MIN
    )
    stacks["atlas_hauler"] = max(int(stacks.get("atlas_hauler") or 0), HOME_HAULER_MIN)
    return {k: v for k, v in stacks.items() if int(v) > 0}


def ensure_bot_home_fleet(
    conn,
    bot: Dict[str, Any],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Stock or refresh a thin home hangar when idle / under-strength.

    Does not replace hangars while fleets are in flight (unless ``force``).
    """
    planet_id = int(bot["planet_id"])
    player_id = int(bot["player_id"])
    faction_key = str(bot["faction_key"])
    if not force and _bot_has_active_fleets(conn, player_id):
        return {"ok": True, "skipped": "fleets_active", "stocked": False}

    current = _home_ship_count(conn, planet_id)
    total = sum(current.values())
    probes = int(current.get("veil_probe") or 0)
    reclaimers = int(current.get("harvest_reclaimer") or 0)
    needs = (
        force
        or total < HOME_FLEET_MIN_UNITS
        or probes < HOME_PROBE_MIN
        or reclaimers < HOME_RECLAIMER_MIN
    )
    if not needs:
        return {"ok": True, "skipped": "adequate", "stocked": False}

    from ..fleet import set_planet_ships
    from ..ranking import recompute_and_upsert_score

    stacks = _faction_home_stacks(conn, faction_key)
    # Merge: never shrink below current when refreshing lightly.
    merged: Dict[str, int] = dict(current)
    for k, v in stacks.items():
        merged[k] = max(int(merged.get(k) or 0), int(v))
    set_planet_ships(planet_id, player_id, merged, conn=conn)
    try:
        recompute_and_upsert_score(player_id, conn=conn)
    except Exception:
        logger.exception("pirate home fleet score refresh failed player=%s", player_id)
    _touch_bot_presence(conn, player_id)
    return {"ok": True, "stocked": True, "ships": merged}


def bootstrap_faction_bots(*, conn) -> List[Dict[str, Any]]:
    """Ensure all faction bots exist with home fleets (Soft-On / tick)."""
    bots = ensure_all_faction_bots(conn=conn)
    for bot in bots:
        try:
            ensure_bot_home_fleet(conn, bot, force=False)
        except Exception:
            logger.exception(
                "ensure_bot_home_fleet failed faction=%s", bot.get("faction_key")
            )
    return bots


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
            }
        )
    return out
