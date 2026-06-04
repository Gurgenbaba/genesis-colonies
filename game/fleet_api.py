"""Unified JSON helpers for fleet HTTP APIs.

Attack mission combat is resolved in ``game.fleet`` on arrival (``simulate_battle``).
Logistics bulk collect/distribute orchestration lives in ``game.fleet`` (``fleet_movements``).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


def fleet_ok(data: Any = None, *, message_key: str = "fleet_ok", message: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True,
        "message": message or message_key,
        "message_key": message_key,
        "data": data if data is not None else {},
    }
    return out


def fleet_err(error: str, *, message_key: str | None = None, message: str = "", data: Any = None) -> Dict[str, Any]:
    key = message_key or f"fleet_error_{error}"
    out: Dict[str, Any] = {
        "ok": False,
        "error": error,
        "message": message or key,
        "message_key": key,
    }
    if data is not None:
        out["data"] = data
    return out


def fleet_resolve_target_payload(
    player_id: int,
    galaxy: int,
    system: int,
    position: int,
    *,
    conn=None,
) -> Dict[str, Any]:
    """Canonical /api/fleet/resolve-target body (same target matrix as send/preview)."""
    from .fleet import resolve_fleet_target

    target = resolve_fleet_target(
        int(player_id),
        int(galaxy),
        int(system),
        int(position),
        conn=conn,
    )
    return fleet_ok({"target": target}, message_key="fleet_target_ok")


def fleet_mission_target_payload(
    player_id: int,
    mission: str,
    galaxy: int,
    system: int,
    position: int,
    *,
    conn=None,
) -> Dict[str, Any]:
    """Probe mission eligibility for coordinates (preview/send use the same evaluator)."""
    from .fleet import evaluate_fleet_mission_target

    ok, reason, target = evaluate_fleet_mission_target(
        int(player_id),
        mission,
        int(galaxy),
        int(system),
        int(position),
        conn=conn,
    )
    data: Dict[str, Any] = {
        "target": target,
        "mission": str(mission or "").strip().lower(),
        "mission_allowed": bool(ok),
        "mission_block_reason": reason if not ok else "",
    }
    if ok:
        return fleet_ok(data, message_key="fleet_mission_target_ok")
    return fleet_err(reason, message_key=reason, data=data)


def fleet_logistics_collect(
    player_id: int,
    *,
    target_planet_id: int,
    source_planet_ids: Sequence[int],
    ships: Mapping[str, int],
    resources_mode: str = "all",
    resources: Mapping[str, Any] | None = None,
    ships_selection_mode: str = "manual",
    preset_id: int | None = None,
    speed_percent: int = 100,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Run bulk collect logistics (N× ``collect`` movements under one batch)."""
    from .fleet import collect_resources

    return collect_resources(
        player_id=int(player_id),
        target_planet_id=int(target_planet_id),
        source_planet_ids=source_planet_ids,
        ships=ships,
        resources_mode=resources_mode,
        resources=resources,
        ships_selection_mode=ships_selection_mode,
        preset_id=preset_id,
        speed_percent=speed_percent,
        conn=conn,
    )


def fleet_logistics_distribute(
    player_id: int,
    *,
    origin_planet_id: int,
    target_planet_ids: Sequence[int],
    ships: Mapping[str, int],
    resources_mode: str = "equal",
    resources: Mapping[str, Any] | None = None,
    target_resources: Any = None,
    ships_selection_mode: str = "manual",
    preset_id: int | None = None,
    speed_percent: int = 100,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Run bulk distribute logistics (N× ``transport`` movements under one batch)."""
    from .fleet import distribute_resources

    return distribute_resources(
        player_id=int(player_id),
        origin_planet_id=int(origin_planet_id),
        target_planet_ids=target_planet_ids,
        ships=ships,
        resources_mode=resources_mode,
        resources=resources,
        target_resources=target_resources,
        ships_selection_mode=ships_selection_mode,
        preset_id=preset_id,
        speed_percent=speed_percent,
        conn=conn,
    )


def fleet_logistics_collect_from_body(
    player_id: int,
    data: Mapping[str, Any],
    *,
    ships: Mapping[str, int],
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Parse POST body for ``/api/fleet/logistics/collect``."""
    try:
        speed_percent = int(data.get("speed_percent") or 100)
    except (TypeError, ValueError):
        speed_percent = 100
    preset_raw = data.get("preset_id")
    preset_id = int(preset_raw) if preset_raw else None
    return fleet_logistics_collect(
        player_id,
        target_planet_id=int(data.get("target_planet_id") or 0),
        source_planet_ids=[int(x) for x in (data.get("source_planet_ids") or [])],
        ships=ships,
        resources_mode=str(data.get("resources_mode") or "all"),
        resources=data.get("resources"),
        ships_selection_mode=str(data.get("ships_selection_mode") or "manual"),
        preset_id=preset_id,
        speed_percent=speed_percent,
        conn=conn,
    )


def fleet_logistics_distribute_from_body(
    player_id: int,
    data: Mapping[str, Any],
    *,
    ships: Mapping[str, int],
    origin_planet_id: int,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Parse POST body for ``/api/fleet/logistics/distribute``."""
    try:
        speed_percent = int(data.get("speed_percent") or 100)
    except (TypeError, ValueError):
        speed_percent = 100
    preset_raw = data.get("preset_id")
    preset_id = int(preset_raw) if preset_raw else None
    return fleet_logistics_distribute(
        player_id,
        origin_planet_id=int(origin_planet_id),
        target_planet_ids=[int(x) for x in (data.get("target_planet_ids") or [])],
        ships=ships,
        resources_mode=str(data.get("resources_mode") or "equal"),
        resources=data.get("resources"),
        target_resources=data.get("target_resources"),
        ships_selection_mode=str(data.get("ships_selection_mode") or "manual"),
        preset_id=preset_id,
        speed_percent=speed_percent,
        conn=conn,
    )
