"""High-level planet evolution service API."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from ..db import begin_write_transaction, commit, lock_planet_for_update, rollback
from ..models import (
    db,
    get_game_settings,
    get_planets_by_player,
    try_spend_resources_conn,
)
from ..ranking import invalidate_player_score_cache
from .ascension import start_ascension as _start_ascension_impl
from .bootstrap import ensure_planet_evolution
from .definitions import get_policy
from .constants import POLICY_COOLDOWN_HOURS
from .specialization import (
    build_active_specialization_payload,
    eligible_specialization_keys,
    list_specialization_options,
    tier_upgrade_requirements,
)
from .dna import all_trait_keys
from .economy import compute_import_deficits
from .events import PlanetEventEngine
from .history import get_history
from .mechanics import compile_planet_mechanics
from .planet_level import level_progress, xp_threshold_for_level
from .planet_research import get_planet_research_status, queue_planet_research
from .repository import (
    evolution_schema_ready,
    get_active_event,
    get_active_planet_id,
    get_discoveries,
    get_legacy_tags,
    get_locked_choices,
    get_planet_culture,
    get_planet_dna,
    get_planet_mechanics,
    get_planet_row,
    get_policies,
    get_production_chains,
    get_special_resources,
    set_active_planet_id,
)


def _planet_switcher_row(
    planet_row: Dict[str, Any],
    *,
    active_id: int,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    from ..galaxy import GalaxyCoordinateError, get_planet_coordinates
    from .ux_copy import planet_class_label_key

    pid = int(planet_row["id"])
    level, xp, _xp_remaining = level_progress(pid, conn)
    planet_class = str(planet_row.get("planet_class") or "terrestrial")
    coords_formatted = ""
    try:
        coords_formatted = get_planet_coordinates(planet_row)["formatted"]
    except GalaxyCoordinateError:
        coords_formatted = ""

    position = planet_row.get("position")
    try:
        position_i = int(position) if position is not None and position != "" else None
    except (TypeError, ValueError):
        position_i = None

    return {
        "planet_id": pid,
        "name": planet_row.get("name"),
        "is_homeworld": bool(planet_row.get("is_homeworld")),
        "planet_level": level,
        "planet_xp": xp,
        "specialization_key": planet_row.get("specialization_key"),
        "specialization_tier": int(planet_row.get("specialization_tier") or 0),
        "is_active": pid == int(active_id),
        "planet_class": planet_class,
        "planet_class_label_key": planet_class_label_key(planet_class),
        "coordinates_formatted": coords_formatted,
        "position": position_i,
    }


def list_player_planets(player_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        active = get_active_planet_id(int(player_id), conn=conn)
        planets = get_planets_by_player(int(player_id), conn=conn)
        return [
            _planet_switcher_row(p, active_id=active, conn=conn)
            for p in planets
        ]
    finally:
        if own and conn is not None:
            conn.close()


def list_player_planets_for_switcher(
    player_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Header/API planet list with coordinates and class badges."""
    return list_player_planets(player_id, conn=conn)


def get_planet_state_payload(
    planet_id: int,
    player_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_planet_evolution(planet_id, conn)
        planet = get_planet_row(planet_id, conn=conn) or {}
        if player_id is not None and int(planet.get("player_id") or 0) != int(player_id):
            return {"ok": False, "error": "not_owner"}

        level, xp, xp_remaining = level_progress(planet_id, conn)
        dna = get_planet_dna(planet_id, conn=conn) or {}
        reveal = int(planet.get("dna_reveal_tier") or 0)
        mechanics = get_planet_mechanics(planet_id, conn=conn)
        culture = get_planet_culture(planet_id, conn=conn)
        event = get_active_event(planet_id, conn=conn)
        active_event = None
        if event:
            from .definitions import get_event

            edef = get_event(str(event.get("event_key") or "")) or {}
            active_event = dict(event)
            active_event["choices"] = edef.get("choices") or []
            active_event["label_key"] = edef.get("label_key") or event.get("event_key")

        from .dashboard import build_dashboard_extras

        mechanics_payload = {
            "export_slots": mechanics.get("export_slots") or [],
            "active_chains": [c["chain_key"] for c in get_production_chains(planet_id, conn=conn)],
            "import_deficits": compute_import_deficits(planet_id, conn),
            "queues": mechanics.get("queue_limits") or {},
        }
        research_status = get_planet_research_status(planet_id, conn=conn)
        dashboard = build_dashboard_extras(
            planet_id,
            planet=planet,
            dna=dna,
            culture=culture,
            mechanics=mechanics_payload,
            research=research_status,
            active_event=active_event,
            eligible_specializations=eligible_specialization_keys(planet_id, conn),
            conn=conn,
        )

        return {
            "ok": True,
            "planet_id": int(planet_id),
            "name": planet.get("name"),
            "level": level,
            "xp": xp,
            "xp_next_level": xp_threshold_for_level(level + 1) if level < 30 else None,
            "xp_remaining": xp_remaining,
            "specialization": {
                "key": planet.get("specialization_key"),
                "tier": int(planet.get("specialization_tier") or 0),
            },
            "ascension": {
                "key": planet.get("ascension_key"),
                "rank": int(planet.get("ascension_rank") or 0),
            },
            "culture": culture,
            "dna_summary": {
                "rarity": dna.get("rarity_tier"),
                "revealed_traits": all_trait_keys(dna, reveal_tier=max(reveal, 1)),
                "affinities": dna.get("affinity_scores") or {},
                "reveal_tier": reveal,
            },
            "mechanics": mechanics_payload,
            "active_event": active_event,
            "eligible_specializations": eligible_specialization_keys(planet_id, conn),
            "specialization_detail": build_active_specialization_payload(planet_id, conn),
            "specialization_options": list_specialization_options(planet_id, conn),
            "failure_state": planet.get("failure_state"),
            "legacy_tags": get_legacy_tags(planet_id, conn=conn),
            "discoveries": [d["discovery_key"] for d in get_discoveries(planet_id, conn=conn)],
            "locked_choices": get_locked_choices(planet_id, conn=conn),
            "policies": get_policies(planet_id, conn=conn),
            "special_resources": get_special_resources(planet_id, conn=conn),
            "research": research_status,
            "history_preview": get_history(planet_id, limit=5, conn=conn).get("items") or [],
            "dashboard": dashboard,
        }
    finally:
        if own and conn is not None:
            conn.close()


def set_active_planet(player_id: int, planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Tuple[bool, str]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        set_active_planet_id(int(player_id), int(planet_id), conn)
        commit(conn)
        return True, "ok"
    except ValueError as exc:
        rollback(conn)
        return False, str(exc)
    finally:
        if own and conn is not None:
            conn.close()


def pick_specialization(
    planet_id: int,
    spec_key: str,
    player_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        planet = get_planet_row(planet_id, conn=conn) or {}
        if int(planet.get("player_id") or 0) != int(player_id):
            rollback(conn)
            return False, "not_owner", None
        if planet.get("specialization_key"):
            rollback(conn)
            return False, "already_specialized", None
        if int(planet.get("planet_level") or 1) < 8:
            rollback(conn)
            return False, "level_too_low", None
        if spec_key not in eligible_specialization_keys(planet_id, conn):
            rollback(conn)
            return False, "not_eligible", {"offered": eligible_specialization_keys(planet_id, conn)}

        cur = conn.cursor()
        cur.execute(
            """
            UPDATE planets SET specialization_key = ?, specialization_tier = 1
            WHERE id = ?;
            """,
            (str(spec_key), int(planet_id)),
        )
        from .history import append_history

        append_history(
            planet_id,
            "specialization_pick",
            f"spec_{spec_key}",
            history_tag=f"spec_{spec_key}",
            conn=conn,
        )
        compile_planet_mechanics(planet_id, conn)
        commit(conn)
        invalidate_player_score_cache(int(player_id))
        return True, "ok", {"specialization_key": spec_key, "tier": 1}
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def upgrade_specialization_tier(
    planet_id: int,
    player_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        planet = get_planet_row(planet_id, conn=conn) or {}
        if int(planet.get("player_id") or 0) != int(player_id):
            rollback(conn)
            return False, "not_owner", None
        if not planet.get("specialization_key"):
            rollback(conn)
            return False, "no_specialization", None

        ok, missing = tier_upgrade_requirements(planet_id, conn)
        if not ok:
            rollback(conn)
            return False, missing[0] if missing else "cannot_upgrade", {"missing": missing}

        new_tier = int(planet.get("specialization_tier") or 0) + 1
        cur = conn.cursor()
        cur.execute(
            "UPDATE planets SET specialization_tier = ? WHERE id = ?;",
            (int(new_tier), int(planet_id)),
        )
        from .history import append_history

        append_history(
            planet_id,
            "specialization_tier_up",
            f"pe_spec_tier_up_{new_tier}",
            body_key=f"spec_{planet.get('specialization_key')}",
            history_tag=f"spec_tier_{new_tier}",
            conn=conn,
        )
        compile_planet_mechanics(planet_id, conn)
        commit(conn)
        invalidate_player_score_cache(int(player_id))
        return True, "ok", {
            "specialization_key": planet.get("specialization_key"),
            "tier": new_tier,
        }
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def make_locked_choice(
    planet_id: int,
    choice_group: str,
    choice_key: str,
    player_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        planet = get_planet_row(planet_id, conn=conn) or {}
        if int(planet.get("player_id") or 0) != int(player_id):
            rollback(conn)
            return False, "not_owner"

        locked = get_locked_choices(planet_id, conn=conn)
        if choice_group in locked:
            rollback(conn)
            return False, "already_chosen"

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planet_locked_choices (planet_id, choice_group, choice_key, chosen_at)
            VALUES (?, ?, ?, ?);
            """,
            (int(planet_id), str(choice_group), str(choice_key), time.time()),
        )
        from .history import append_history

        append_history(
            planet_id,
            "locked_choice",
            f"choice_{choice_group}_{choice_key}",
            payload={"choice_group": choice_group, "choice_key": choice_key},
            conn=conn,
        )
        compile_planet_mechanics(planet_id, conn)
        commit(conn)
        return True, "ok"
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def activate_policy(
    planet_id: int,
    slot: int,
    policy_key: str,
    player_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        planet = get_planet_row(planet_id, conn=conn) or {}
        if int(planet.get("player_id") or 0) != int(player_id):
            rollback(conn)
            return False, "not_owner"

        pdef = get_policy(policy_key)
        if not pdef:
            rollback(conn)
            return False, "unknown_policy"

        if int(pdef.get("tier") or 1) > int(slot):
            rollback(conn)
            return False, "slot_too_low"

        culture = get_planet_culture(planet_id, conn=conn)
        allowed = pdef.get("archetype_allow") or []
        if allowed and str(culture.get("archetype_key") or "") not in [str(a) for a in allowed]:
            rollback(conn)
            return False, "archetype_not_allowed"

        policies = get_policies(planet_id, conn=conn)
        now = time.time()
        for pol in policies:
            if int(pol["slot"]) == int(slot) and float(pol.get("cooldown_until") or 0) > now:
                rollback(conn)
                return False, "slot_on_cooldown"

        cooldown = float(pdef.get("cooldown_hours") or POLICY_COOLDOWN_HOURS) * 3600
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planet_policies (planet_id, slot, policy_key, activated_at, cooldown_until)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(planet_id, slot) DO UPDATE SET
                policy_key = excluded.policy_key,
                activated_at = excluded.activated_at,
                cooldown_until = excluded.cooldown_until;
            """,
            (int(planet_id), int(slot), str(policy_key), now, now + cooldown),
        )
        compile_planet_mechanics(planet_id, conn)
        commit(conn)
        return True, "ok"
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def resolve_event_choice(
    planet_id: int,
    event_id: int,
    choice_key: str,
    player_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        planet = get_planet_row(planet_id, conn=conn) or {}
        if int(planet.get("player_id") or 0) != int(player_id):
            rollback(conn)
            return False, "not_owner", None

        ok, reason, payload = PlanetEventEngine.resolve_choice(conn, planet_id, event_id, choice_key)
        if not ok:
            rollback(conn)
            return False, reason, payload
        commit(conn)
        invalidate_player_score_cache(int(player_id))
        return True, "ok", payload
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def create_trade_route(
    owner_player_id: int,
    source_planet_id: int,
    target_planet_id: int,
    resource_key: str,
    amount_per_hour: float,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        if source_planet_id == target_planet_id:
            return False, "same_planet", None
        if amount_per_hour <= 0:
            return False, "invalid_amount", None

        begin_write_transaction(conn)
        for pid in (source_planet_id, target_planet_id):
            planet = get_planet_row(pid, conn=conn) or {}
            if int(planet.get("player_id") or 0) != int(owner_player_id):
                rollback(conn)
                return False, "not_owner", None

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planet_trade_routes (
                owner_player_id, source_planet_id, target_planet_id,
                resource_key, amount_per_hour, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?);
            """,
            (
                int(owner_player_id),
                int(source_planet_id),
                int(target_planet_id),
                str(resource_key),
                float(amount_per_hour),
                time.time(),
            ),
        )
        route_id = int(cur.lastrowid)
        commit(conn)
        return True, "ok", {"route_id": route_id}
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def delete_trade_route(
    owner_player_id: int,
    route_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE planet_trade_routes SET is_active = 0
            WHERE id = ? AND owner_player_id = ?;
            """,
            (int(route_id), int(owner_player_id)),
        )
        if cur.rowcount <= 0:
            rollback(conn)
            return False, "route_not_found"
        commit(conn)
        return True, "ok"
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def start_ascension(
    planet_id: int,
    ascension_key: str,
    player_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    if int(planet.get("player_id") or 0) != int(player_id):
        return False, "not_owner", None
    return _start_ascension_impl(planet_id, ascension_key, conn=conn)


def colonize_planet(
    player_id: int,
    *,
    name: str,
    galaxy: int = 1,
    system: Optional[int] = None,
    position: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        if not evolution_schema_ready(conn):
            return False, "schema_missing", None

        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM planets WHERE player_id = ? AND is_homeworld = 0;",
            (int(player_id),),
        )
        colonies = int(cur.fetchone()["c"])
        try:
            settings = get_game_settings(conn=conn)
            max_col = int(settings.get("max_colonies_per_player", 9))
        except Exception:
            max_col = 9
        if colonies >= max_col:
            rollback(conn)
            return False, "max_colonies", None

        from game.galaxy import (
            assign_free_coordinates,
            assert_coordinate_available,
            GalaxyCoordinateError,
        )
        from .dna import generate_planet_dna

        if system is None or position is None:
            galaxy, system, position = assign_free_coordinates(conn, galaxy=int(galaxy))
        else:
            try:
                assert_coordinate_available(conn, int(galaxy), int(system), int(position))
            except GalaxyCoordinateError:
                rollback(conn)
                return False, "coordinate_occupied", None

        dna = generate_planet_dna(galaxy=int(galaxy), system=system, position=position)
        now = time.time()
        cur.execute(
            """
            INSERT INTO planets (
                player_id, name, is_homeworld, metal, crystal, last_update,
                galaxy, system, position, planet_class, dna_seed, created_at, last_evolution_tick
            ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(player_id),
                str(name),
                500.0,
                250.0,
                now,
                int(galaxy),
                int(system),
                int(position),
                str(dna.get("planet_class") or "terrestrial"),
                int(dna.get("dna_seed") or 0),
                now,
                now,
            ),
        )
        planet_id = int(cur.lastrowid)
        cur.execute("INSERT INTO planet_buildings (planet_id) VALUES (?);", (planet_id,))
        ensure_planet_evolution(planet_id, conn)
        commit(conn)
        invalidate_player_score_cache(int(player_id))
        return True, "ok", {"planet_id": planet_id, "name": name}
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()
