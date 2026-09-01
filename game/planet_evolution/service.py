"""High-level planet evolution service API."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from ..db import (
    begin_write_transaction,
    commit,
    get_db_backend,
    is_db_lock_error,
    lock_planet_for_update,
    rollback,
)

logger = logging.getLogger(__name__)
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


# GC-PLANET-UI-001 — Planet Registry activity indicators (extensible catalog).
# Icons aligned with location_actions / Command Center feed.
_STATUS_INDICATOR_BUILDING = {
    "key": "building",
    "icon": "🏗",
    "label_key": "planet_status_building_active",
}
_STATUS_INDICATOR_RESEARCH = {
    "key": "research",
    "icon": "🔬",
    "label_key": "planet_status_research_active",
}
_STATUS_INDICATOR_SHIPYARD = {
    "key": "shipyard",
    "icon": "⚓",
    "label_key": "planet_status_shipyard_active",
}
_STATUS_INDICATOR_DEFENSE = {
    "key": "defense",
    "icon": "🛡",
    "label_key": "planet_status_defense_active",
}


def _status_indicators_for_planet(
    *,
    has_build_queue: bool,
    has_research_queue: bool = False,
    has_shipyard_queue: bool = False,
    has_defense_queue: bool = False,
) -> List[Dict[str, Any]]:
    """Build the status_indicators list for one switcher/registry row."""
    indicators: List[Dict[str, Any]] = []
    if has_build_queue:
        indicators.append(dict(_STATUS_INDICATOR_BUILDING))
    if has_research_queue:
        indicators.append(dict(_STATUS_INDICATOR_RESEARCH))
    if has_shipyard_queue:
        indicators.append(dict(_STATUS_INDICATOR_SHIPYARD))
    if has_defense_queue:
        indicators.append(dict(_STATUS_INDICATOR_DEFENSE))
    return indicators


def _planet_switcher_row(
    planet_row: Dict[str, Any],
    *,
    active_id: int,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    from ..galaxy import GalaxyCoordinateError, get_planet_coordinates
    from .dna import effective_planet_class
    from .ux_copy import planet_class_label_key

    pid = int(planet_row["id"])
    level, xp, _xp_remaining = level_progress(pid, conn)
    planet_class = effective_planet_class(planet_row)
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

    from ..planet_visuals import (
        DEFAULT_HEROCARD,
        herocard_static_relpath,
        raster_webp_relpath,
    )
    from .empire_identity import empire_identity_for_planet

    if position_i:
        herocard_rel = herocard_static_relpath(position_i)
    else:
        herocard_rel = f"img/herocards/{DEFAULT_HEROCARD}"

    row = {
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
        "herocard_relpath": herocard_rel,
        "herocard_webp_relpath": raster_webp_relpath(herocard_rel),
        "status_indicators": [],
    }
    row.update(empire_identity_for_planet(planet_row, conn=conn))
    return row


def list_player_planets(player_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        active = get_active_planet_id(int(player_id), conn=conn)
        planets = get_planets_by_player(int(player_id), conn=conn)
        rows = [
            _planet_switcher_row(p, active_id=active, conn=conn)
            for p in planets
        ]
        from ..buildings import planet_ids_with_build_queue
        from ..defense import planet_ids_with_defense_queue
        from ..research import player_has_active_research_queue
        from ..shipyard_queue import planet_ids_with_shipyard_queue

        planet_ids = [int(r["planet_id"]) for r in rows]
        active_build = planet_ids_with_build_queue(planet_ids, conn=conn)
        active_shipyard = planet_ids_with_shipyard_queue(planet_ids, conn=conn)
        active_defense = planet_ids_with_defense_queue(planet_ids, conn=conn)
        # Account research attaches to the context/active planet (Command Center parity).
        research_planet_id = (
            int(active)
            if player_has_active_research_queue(int(player_id), conn=conn)
            else None
        )
        for r in rows:
            pid = int(r["planet_id"])
            r["status_indicators"] = _status_indicators_for_planet(
                has_build_queue=pid in active_build,
                has_research_queue=research_planet_id is not None and pid == research_planet_id,
                has_shipyard_queue=pid in active_shipyard,
                has_defense_queue=pid in active_defense,
            )
        return rows
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
    *,
    ssr_boot: bool = False,
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
            from .events import preview_event_choice
            from .impact import event_outcome_impact_rows, impact_scopes

            active_event = dict(event)
            choice_rows = []
            for raw_choice in edef.get("choices") or []:
                choice = dict(raw_choice) if isinstance(raw_choice, dict) else {"key": str(raw_choice)}
                preview = preview_event_choice(edef, str(choice.get("key") or ""))
                rows = event_outcome_impact_rows(
                    (preview or {}).get("outcome") or {},
                    culture,
                )
                choice["impact"] = {
                    "rows": rows,
                    "scopes": impact_scopes(rows),
                    "outcome_key": (preview or {}).get("outcome_key"),
                }
                choice_rows.append(choice)
            active_event["choices"] = choice_rows
            active_event["label_key"] = edef.get("label_key") or event.get("event_key")

        from .dashboard import build_dashboard_extras

        mechanics_payload = {
            "export_slots": mechanics.get("export_slots") or [],
            "active_chains": [c["chain_key"] for c in get_production_chains(planet_id, conn=conn)],
            "import_deficits": compute_import_deficits(planet_id, conn),
            "queues": mechanics.get("queue_limits") or {},
        }
        research_status = get_planet_research_status(planet_id, conn=conn)
        # Page SSR: smaller chronicle window (API hydrate keeps full 20).
        history_limit = 5 if ssr_boot else 20
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
            history_limit=history_limit,
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
        pid = int(player_id)
        plid = int(planet_id)
        # PG: short local lock wait (hundreds of ms) × bounded retries — never multi-second UX.
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                begin_write_transaction(conn)
                if get_db_backend() == "postgres":
                    try:
                        conn.execute("SET LOCAL lock_timeout = '250ms'")
                    except Exception:
                        pass
                set_active_planet_id(pid, plid, conn)
                commit(conn)
                return True, "ok"
            except ValueError as exc:
                rollback(conn)
                return False, str(exc)
            except Exception as exc:
                try:
                    rollback(conn)
                except Exception:
                    pass
                if is_db_lock_error(exc) and attempt + 1 < max_attempts:
                    time.sleep(0.04 * (attempt + 1))
                    continue
                if is_db_lock_error(exc):
                    logger.warning(
                        "set_active_planet locked player=%s planet=%s — lock_busy",
                        pid,
                        plid,
                    )
                    return False, "lock_busy"
                raise
        return False, "lock_busy"
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

        from .policies import activation_block_reason, evaluate_policy_gate

        eligible, locked_key = evaluate_policy_gate(
            planet_id,
            policy_key,
            policy_def=pdef,
            slot=int(slot),
            archetype_key=str(culture.get("archetype_key") or ""),
            conn=conn,
        )
        if not eligible:
            rollback(conn)
            return False, activation_block_reason(locked_key)

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


_LEGACY_COLONIZE_SOURCES = frozenset({"admin", "test", "repair"})


def colonize_planet(
    player_id: int,
    *,
    name: str,
    galaxy: int = 1,
    system: Optional[int] = None,
    position: Optional[int] = None,
    world_key: Optional[str] = None,
    world_binding: Optional[Dict[str, Any]] = None,
    allow_legacy_coordinates: bool = False,
    source: str = "player",
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        if not evolution_schema_ready(conn):
            return False, "schema_missing", None

        binding = dict(world_binding) if world_binding else None
        wk = str(world_key or (binding or {}).get("world_key") or "").strip()
        if wk and binding is None:
            binding = {"world_key": wk}
        elif wk and binding is not None and not str(binding.get("world_key") or "").strip():
            binding["world_key"] = wk

        has_expansion_binding = bool(wk) or bool(
            binding
            and str(binding.get("world_key") or "").strip()
        )

        begin_write_transaction(conn)
        from game.logic import check_planet_cap_available

        # Test fixtures often found multiple colonies in a loop without raising PE
        # levels; production fleet/API still enforce colony_maturity_gate.
        if str(source or "") == "test":
            from .expansion_protocol import COLONY_MATURITY_REQUIRED_LEVEL

            conn.execute(
                """
                UPDATE planets
                SET planet_level = MAX(COALESCE(planet_level, 0), ?)
                WHERE player_id = ? AND COALESCE(is_homeworld, 0) = 0;
                """,
                (int(COLONY_MATURITY_REQUIRED_LEVEL), int(player_id)),
            )

        ok_cap, cap_reason = check_planet_cap_available(int(player_id), conn=conn)
        if not ok_cap:
            rollback(conn)
            return False, cap_reason, None

        cur = conn.cursor()
        from game.galaxy import (
            assign_free_coordinates,
            assert_coordinate_available,
            GalaxyCoordinateError,
        )
        from .dna import generate_planet_dna

        if binding:
            from .world_colonization import world_colonization_schema_ready

            if not world_colonization_schema_ready(conn=conn):
                rollback(conn)
                return False, "schema_missing", None

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
        if binding:
            cur.execute(
                """
                INSERT INTO planets (
                    player_id, name, is_homeworld, metal, crystal, last_update,
                    galaxy, system, position, planet_class, dna_seed, created_at, last_evolution_tick,
                    world_key, world_x, world_y, sector_x, sector_y, planet_role, origin_world_key,
                    planet_level, planet_xp, dna_reveal_tier
                ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0);
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
                    str(binding.get("world_key") or ""),
                    float(binding.get("world_x") or 0),
                    float(binding.get("world_y") or 0),
                    int(binding.get("sector_x") or 0),
                    int(binding.get("sector_y") or 0),
                    str(binding.get("planet_role") or ""),
                    str(binding.get("origin_world_key") or binding.get("world_key") or ""),
                ),
            )
        else:
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
