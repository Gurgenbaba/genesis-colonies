"""Unified JSON helpers for fleet HTTP APIs.

Attack mission combat is resolved in ``game.fleet`` on arrival (``simulate_battle``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional


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
