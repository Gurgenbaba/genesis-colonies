"""Directive progress from gameplay events (GC-912A/B)."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

from ..db import table_exists
from .definitions import OBJECTIVE_ACCUMULATE, OBJECTIVE_COUNT, directives_schema_ready, get_definition
from .generator import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    daily_period_key,
    ensure_player_directives,
    weekly_period_key,
)

logger = logging.getLogger(__name__)

PROGRESS_TABLE = "directive_progress"


def progress_schema_ready(conn) -> bool:
    return table_exists(conn, PROGRESS_TABLE)


def apply_directive_events(
    player_id: int,
    events: Sequence[Mapping[str, Any]],
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    """Apply gameplay events to active directives (idempotent per source_event_id)."""
    pid = int(player_id)
    if pid <= 0 or not events:
        return {"updated": 0, "completed": 0}

    if not directives_schema_ready(conn):
        return {"updated": 0, "completed": 0}

    ts = float(now if now is not None else time.time())
    ensure_player_directives(pid, conn=conn, now=ts)

    active_rows = _load_active_directives(pid, conn=conn, now=ts)
    if not active_rows:
        return {"updated": 0, "completed": 0}

    updated = 0
    completed = 0
    now_i = int(ts)

    for event in events:
        if not event:
            continue
        for row in active_rows:
            if str(row.get("status") or "") not in (STATUS_ACTIVE,):
                continue
            definition = get_definition(str(row["definition_key"]), conn=conn)
            if not definition:
                continue
            delta = _event_delta(definition, event)
            if delta <= 0:
                continue
            source_event_id = str(event.get("source_event_id") or "").strip()
            if not source_event_id:
                continue
            if not _record_progress_delta(
                int(row["id"]),
                source_event_id=source_event_id,
                delta=delta,
                conn=conn,
                now=now_i,
            ):
                continue
            new_progress = int(row.get("progress_value") or 0) + delta
            target = int(row.get("target_value") or 1)
            new_status = STATUS_ACTIVE
            completed_at: Optional[int] = None
            if new_progress >= target:
                new_progress = target
                new_status = STATUS_COMPLETED
                completed_at = now_i
                completed += 1

            conn.execute(
                """
                UPDATE player_directives
                SET progress_value = ?, status = ?, completed_at = COALESCE(completed_at, ?)
                WHERE id = ? AND status = ?;
                """,
                (
                    int(new_progress),
                    str(new_status),
                    completed_at,
                    int(row["id"]),
                    STATUS_ACTIVE,
                ),
            )
            row["progress_value"] = new_progress
            row["status"] = new_status
            updated += 1

    return {"updated": updated, "completed": completed}


def _load_active_directives(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float,
) -> List[MutableMapping[str, Any]]:
    daily_key = daily_period_key(now)
    weekly_key = weekly_period_key(now)
    rows = conn.execute(
        """
        SELECT id, definition_key, cadence, target_value, progress_value, status, period_key
        FROM player_directives
        WHERE player_id = ?
          AND status IN (?, ?)
          AND period_key IN (?, ?)
          AND expires_at > ?;
        """,
        (
            int(player_id),
            STATUS_ACTIVE,
            STATUS_COMPLETED,
            daily_key,
            weekly_key,
            int(now),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def _record_progress_delta(
    player_directive_id: int,
    *,
    source_event_id: str,
    delta: int,
    conn: sqlite3.Connection,
    now: int,
) -> bool:
    if not progress_schema_ready(conn):
        return True
    try:
        conn.execute(
            """
            INSERT INTO directive_progress (
                player_directive_id, source_event_id, delta, created_at
            ) VALUES (?, ?, ?, ?);
            """,
            (int(player_directive_id), str(source_event_id), int(delta), int(now)),
        )
        return True
    except Exception as exc:
        from ..db import is_integrity_error

        if is_integrity_error(exc):
            return False
        raise


def _event_delta(definition: Mapping[str, Any], event: Mapping[str, Any]) -> int:
    if not _event_applies(definition, event):
        return 0
    kind = str(definition.get("objective_kind") or OBJECTIVE_COUNT).strip().lower()
    if kind == OBJECTIVE_ACCUMULATE:
        amount = int(event.get("amount") or 0)
        if amount <= 0 and str(event.get("kind")) == "resource_spent":
            amount = int(event.get("metal") or 0) + int(event.get("crystal") or 0)
        return max(0, amount)
    return max(0, int(event.get("amount") or 1))


def _event_applies(definition: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
    key = str(definition.get("key") or "")
    kind = str(event.get("kind") or "").strip().lower()
    filters = definition.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}

    if key == "upgrade_buildings":
        return kind == "build_complete"
    if key in ("upgrade_storages", "upgrade_solar_plants", "upgrade_fuel_plants"):
        if kind != "build_complete":
            return False
        allowed = filters.get("building_types") or []
        return str(event.get("building_type") or "") in {str(x) for x in allowed}
    if key == "produce_metal":
        return kind == "resource_produced" and str(event.get("resource")) == "metal"
    if key == "produce_crystal":
        return kind == "resource_produced" and str(event.get("resource")) == "crystal"
    if key == "produce_fuel_cells":
        return kind == "resource_produced" and str(event.get("resource")) == "fuel_cells"
    if key == "spend_resources":
        return kind == "resource_spent" and str(event.get("context") or "build") != "research"
    if key == "start_research":
        return kind == "research_started"
    if key == "complete_research":
        return kind == "research_complete"
    if key in ("upgrade_mining_tech", "upgrade_energy_tech", "upgrade_navigation_tech"):
        if kind != "research_complete":
            return False
        allowed = filters.get("research_keys") or []
        return str(event.get("tech_key") or "") in {str(x) for x in allowed}
    if key == "spend_research_resources":
        return kind == "resource_spent" and str(event.get("context") or "") == "research"
    if key == "launch_expeditions":
        return kind == "fleet_mission_sent" and str(event.get("mission") or "") == "expedition"
    if key == "complete_expeditions":
        return kind == "expedition_complete"
    if key == "send_fleet_missions":
        return kind == "fleet_mission_sent"
    if key == "recycle_debris":
        return kind == "recycle_complete"
    if key == "build_ships":
        return kind == "ship_built"
    if key == "build_combat_ships":
        return kind == "ship_built" and bool(event.get("combat_ship"))
    if key == "win_battles":
        return kind == "battle_won" and bool(event.get("won"))
    if key == "destroy_enemy_ships":
        return kind == "ships_destroyed"
    if key == "destroy_enemy_defense":
        return kind == "defense_destroyed"
    if key == "build_defense":
        return kind == "defense_built"
    if key == "defeat_pirates":
        return kind == "pirate_defeated" and bool(event.get("won"))
    if key == "deal_world_boss_damage":
        return kind == "world_boss_damage"
    if key == "trigger_expedition_events":
        return kind == "expedition_event"
    if key == "find_rare_loot":
        return kind == "expedition_event" and bool(event.get("rare_loot"))
    if key == "recover_ancient_technology":
        return kind == "expedition_event" and str(event.get("event_type") or "") == "ancient_tech"
    if key == "salvage_ancient_ships":
        return kind == "ships_salvaged"
    return False


def _ship_is_combat(ship_key: str) -> bool:
    from ..fleet_defs import get_ship

    spec = get_ship(str(ship_key or "")) or {}
    return str(spec.get("role") or "").strip().lower() == "combat"


def _split_combat_losses(losses: Mapping[str, Any]) -> tuple[int, int]:
    from ..defense_defs import is_known_defense_key
    from ..fleet_defs import is_known_ship_key

    ships = 0
    defense = 0
    for unit_key, qty in dict(losses or {}).items():
        amount = max(0, int(qty or 0))
        if amount <= 0:
            continue
        key = str(unit_key or "")
        if is_known_defense_key(key):
            defense += amount
        elif is_known_ship_key(key):
            ships += amount
    return ships, defense


def emit_build_complete_events(
    player_id: int,
    completions: Iterable[Mapping[str, Any]],
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    events = [
        {
            "kind": "build_complete",
            "building_type": str(item.get("building_type") or ""),
            "amount": 1,
            "source_event_id": str(item.get("source_event_id") or ""),
        }
        for item in completions
        if item.get("source_event_id")
    ]
    if not events:
        return {"updated": 0, "completed": 0}
    return apply_directive_events(int(player_id), events, conn=conn, now=now)


def emit_resource_spent_event(
    player_id: int,
    *,
    metal: int,
    crystal: int,
    source_event_id: str,
    context: str = "build",
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    total = max(0, int(metal)) + max(0, int(crystal))
    if total <= 0:
        return {"updated": 0, "completed": 0}
    event = {
        "kind": "resource_spent",
        "metal": int(metal),
        "crystal": int(crystal),
        "amount": total,
        "context": str(context),
        "source_event_id": str(source_event_id),
    }
    return apply_directive_events(int(player_id), [event], conn=conn, now=now)


def emit_research_started_event(
    player_id: int,
    *,
    tech_key: str,
    metal: int,
    crystal: int,
    job_id: int,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    events = [
        {
            "kind": "research_started",
            "tech_key": str(tech_key),
            "amount": 1,
            "source_event_id": f"research_start:{int(job_id)}",
        },
        {
            "kind": "resource_spent",
            "tech_key": str(tech_key),
            "metal": int(metal),
            "crystal": int(crystal),
            "amount": max(0, int(metal)) + max(0, int(crystal)),
            "context": "research",
            "source_event_id": f"research_spend:{int(job_id)}",
        },
    ]
    return apply_directive_events(int(player_id), events, conn=conn, now=now)


def emit_research_complete_events(
    player_id: int,
    completions: Iterable[Mapping[str, Any]],
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    events = [
        {
            "kind": "research_complete",
            "tech_key": str(item.get("tech_key") or ""),
            "amount": 1,
            "source_event_id": str(item.get("source_event_id") or ""),
        }
        for item in completions
        if item.get("source_event_id")
    ]
    if not events:
        return {"updated": 0, "completed": 0}
    return apply_directive_events(int(player_id), events, conn=conn, now=now)


def emit_resource_produced_events(
    player_id: int,
    *,
    planet_id: int,
    tick_start: float,
    delta_metal: int,
    delta_crystal: int,
    delta_fuel_cells: int,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    tick_key = int(float(tick_start))
    events: List[Dict[str, Any]] = []
    if int(delta_metal) > 0:
        events.append(
            {
                "kind": "resource_produced",
                "resource": "metal",
                "amount": int(delta_metal),
                "source_event_id": f"prod:{int(planet_id)}:{tick_key}:metal",
            }
        )
    if int(delta_crystal) > 0:
        events.append(
            {
                "kind": "resource_produced",
                "resource": "crystal",
                "amount": int(delta_crystal),
                "source_event_id": f"prod:{int(planet_id)}:{tick_key}:crystal",
            }
        )
    if int(delta_fuel_cells) > 0:
        events.append(
            {
                "kind": "resource_produced",
                "resource": "fuel_cells",
                "amount": int(delta_fuel_cells),
                "source_event_id": f"prod:{int(planet_id)}:{tick_key}:fuel",
            }
        )
    if not events:
        return {"updated": 0, "completed": 0}
    return apply_directive_events(int(player_id), events, conn=conn, now=now)


def emit_fleet_mission_sent(
    player_id: int,
    *,
    mission: str,
    fleet_id: int,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    event = {
        "kind": "fleet_mission_sent",
        "mission": str(mission or "").strip().lower(),
        "amount": 1,
        "source_event_id": f"fleet_send:{int(fleet_id)}",
    }
    return apply_directive_events(int(player_id), [event], conn=conn, now=now)


def emit_expedition_complete_event(
    player_id: int,
    *,
    movement_id: int,
    outcome: Mapping[str, Any],
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = [
        {
            "kind": "expedition_complete",
            "amount": 1,
            "source_event_id": f"expedition_complete:{int(movement_id)}",
        }
    ]
    event_key = str(outcome.get("event_key") or "")
    severity = str(outcome.get("severity") or "normal")
    story_tier = str(outcome.get("story_tier") or "")
    lootboxes = list(outcome.get("lootboxes") or [])
    rare_loot = story_tier == "legendary" or severity == "major" or any(
        bool(box.get("jackpot")) for box in lootboxes if isinstance(box, dict)
    )
    ancient_tech = event_key in {"ancient_beacon", "time_anomaly", "spatial_rift"}
    salvaged_total = int(outcome.get("salvaged_total") or 0)
    if salvaged_total <= 0:
        salvaged_total = int(sum(dict(outcome.get("salvaged_ships") or {}).values()))

    events.append(
        {
            "kind": "expedition_event",
            "event_key": event_key,
            "event_type": "ancient_tech" if ancient_tech else "",
            "rare_loot": rare_loot,
            "amount": 1,
            "source_event_id": f"expedition_event:{int(movement_id)}",
        }
    )
    if salvaged_total > 0:
        events.append(
            {
                "kind": "ships_salvaged",
                "amount": salvaged_total,
                "source_event_id": f"expedition_salvage:{int(movement_id)}",
            }
        )
    pirate = dict(outcome.get("pirate_combat") or {})
    if pirate or event_key == "pirate_encounter":
        won = bool(outcome.get("pirate_won") or pirate.get("won"))
        events.append(
            {
                "kind": "pirate_defeated",
                "won": won,
                "amount": 1 if won else 0,
                "source_event_id": f"expedition_pirate:{int(movement_id)}",
            }
        )
    return apply_directive_events(int(player_id), events, conn=conn, now=now)


def emit_recycle_complete_event(
    player_id: int,
    *,
    movement_id: int,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    event = {
        "kind": "recycle_complete",
        "amount": 1,
        "source_event_id": f"recycle_complete:{int(movement_id)}",
    }
    return apply_directive_events(int(player_id), [event], conn=conn, now=now)


def emit_combat_directive_events(
    player_id: int,
    *,
    movement_id: int,
    winner: str,
    defender_losses: Mapping[str, Any],
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    from ..combat import WINNER_ATTACKER

    attacker_won = str(winner or "") == WINNER_ATTACKER
    events: List[Dict[str, Any]] = [
        {
            "kind": "battle_won",
            "won": attacker_won,
            "amount": 1 if attacker_won else 0,
            "source_event_id": f"battle_won:{int(movement_id)}",
        }
    ]
    ships_destroyed, defense_destroyed = _split_combat_losses(defender_losses)
    if ships_destroyed > 0:
        events.append(
            {
                "kind": "ships_destroyed",
                "amount": ships_destroyed,
                "source_event_id": f"ships_destroyed:{int(movement_id)}",
            }
        )
    if defense_destroyed > 0:
        events.append(
            {
                "kind": "defense_destroyed",
                "amount": defense_destroyed,
                "source_event_id": f"defense_destroyed:{int(movement_id)}",
            }
        )
    return apply_directive_events(int(player_id), events, conn=conn, now=now)


def emit_world_boss_damage_event(
    player_id: int,
    *,
    movement_id: int,
    damage: int,
    event_id: int,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    """EPIC-20 — progress Imperial Directive ``deal_world_boss_damage``."""
    amount = max(0, int(damage or 0))
    if amount <= 0:
        return {"ok": True, "applied": 0}
    event = {
        "kind": "world_boss_damage",
        "amount": amount,
        "event_id": int(event_id),
        "source_event_id": f"world_boss_damage:{int(event_id)}:{int(movement_id)}",
    }
    return apply_directive_events(int(player_id), [event], conn=conn, now=now)


def emit_ship_built_events(
    player_id: int,
    *,
    ship_key: str,
    amount: int,
    job_id: int,
    delivered_before: int,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    amt = max(0, int(amount or 0))
    if amt <= 0:
        return {"updated": 0, "completed": 0}
    event = {
        "kind": "ship_built",
        "ship_key": str(ship_key or ""),
        "combat_ship": _ship_is_combat(ship_key),
        "amount": amt,
        "source_event_id": f"shipyard:{int(job_id)}:{int(delivered_before)}:{amt}",
    }
    return apply_directive_events(int(player_id), [event], conn=conn, now=now)


def emit_defense_built_events(
    player_id: int,
    *,
    defense_key: str,
    amount: int,
    job_id: int,
    delivered_before: int,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    amt = max(0, int(amount or 0))
    if amt <= 0:
        return {"updated": 0, "completed": 0}
    event = {
        "kind": "defense_built",
        "defense_key": str(defense_key or ""),
        "amount": amt,
        "source_event_id": f"defense:{int(job_id)}:{int(delivered_before)}:{amt}",
    }
    return apply_directive_events(int(player_id), [event], conn=conn, now=now)
