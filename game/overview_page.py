"""Overview page context — OGame-style colony status (no building/research duplication)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .planet_evolution.ux_copy import planet_class_label_key

# TODO: Persist planet surface temperature in DB; until then derive from galaxy slot (1–15).
_TEMPERATURE_BY_CLASS: Dict[str, tuple[int, int]] = {
    "terrestrial": (5, 35),
    "oceanic": (10, 28),
    "barren": (-50, 20),
    "ice": (-80, -10),
    "volcanic": (180, 420),
    "ruin": (-20, 45),
    "gas_moon": (-120, -40),
}


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        if raw is None or raw == "":
            return int(default)
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def temperature_range_for_class(planet_class: str) -> Dict[str, Any]:
    """Fallback temperature band until real planet climate data exists."""
    cls = str(planet_class or "terrestrial").strip().lower() or "terrestrial"
    lo, hi = _TEMPERATURE_BY_CLASS.get(cls, _TEMPERATURE_BY_CLASS["terrestrial"])
    return {
        "min_c": lo,
        "max_c": hi,
        "display": f"{lo}°C … {hi}°C",
        "is_fallback": True,
    }


def _format_remaining(seconds: int) -> str:
    sec = max(0, int(seconds or 0))
    rh = sec // 3600
    rm = (sec % 3600) // 60
    rs = sec % 60
    if rh > 0:
        return f"{rh}:{rm:02d}:{rs:02d}"
    return f"{rm}:{rs:02d}"


def build_planet_meta(planet: Dict[str, Any], *, conn=None) -> Dict[str, Any]:
    from .galaxy import get_planet_coordinates, get_relocation_client_state, relocation_schema_ready
    from .planet_evolution.dna import effective_planet_class

    planet_class = effective_planet_class(planet)
    coords = get_planet_coordinates(planet)
    position = int(coords.get("position") or 0)
    from .planet_visuals import planet_theme_for_planet, temperature_range_for_position

    temp = temperature_range_for_position(position)
    is_homeworld = bool(int(planet.get("is_homeworld") or 0))
    theme = planet_theme_for_planet({**planet, "position": position})
    climate = theme.get("climate") or {}
    relocation: Dict[str, Any] = {"active": False, "can_start": True}
    if conn is not None and relocation_schema_ready(conn):
        relocation = get_relocation_client_state(int(planet.get("id") or 0), conn=conn)
    return {
        "planet_id": _safe_int(planet.get("id")),
        "name": str(planet.get("name") or "Kolonie"),
        "is_homeworld": is_homeworld,
        "can_delete": not is_homeworld,
        "planet_class": planet_class,
        "planet_class_label_key": planet_class_label_key(planet_class),
        "coordinates": {
            "galaxy": coords["galaxy"],
            "system": coords["system"],
            "position": coords["position"],
            "display": coords["formatted"],
        },
        "temperature": temp,
        "climate": climate,
        "theme": theme,
        "relocation": relocation,
    }


def _build_activity_line(
    *,
    key: str,
    state: str,
    summary: str,
    remaining: int = 0,
    finish_at: int = 0,
    countdown_at: int = 0,
    phase: str = "",
    status_label: str = "",
    movement_id: int = 0,
    href_key: str,
    label_key: str,
) -> Dict[str, Any]:
    end_at = int(countdown_at or finish_at or 0)
    return {
        "key": key,
        "state": state,
        "summary": summary,
        "remaining": int(remaining),
        "remaining_display": _format_remaining(remaining) if state == "active" else "",
        "finish_at": end_at,
        "countdown_at": end_at,
        "phase": str(phase or ""),
        "status_label": str(status_label or ""),
        "movement_id": int(movement_id or 0),
        "href_key": href_key,
        "label_key": label_key,
    }


def build_activity_lines(
    build_queue: Dict[str, Any],
    research: Dict[str, Any],
    *,
    shipyard_queue: Optional[Dict[str, Any]] = None,
    defense_queue: Optional[Dict[str, Any]] = None,
    planet_relocation: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []

    bq_list = build_queue.get("queue") if isinstance(build_queue, dict) else None
    if not isinstance(bq_list, list):
        bq_list = []
    active_build = bq_list[0] if bq_list else None

    if active_build:
        label_key = str(active_build.get("label_key") or f"building_{active_build.get('building_type', '')}")
        target = _safe_int(active_build.get("target_level"))
        current = max(0, target - 1)
        summary = f"L{current} → L{target}"
        lines.append(
            _build_activity_line(
                key="build",
                state="active",
                summary=summary,
                remaining=_safe_int(active_build.get("remaining")),
                finish_at=_safe_int(active_build.get("finish_time")),
                href_key="buildings_view",
                label_key=label_key,
            )
        )
    else:
        lines.append(
            _build_activity_line(
                key="build",
                state="idle",
                summary="",
                href_key="buildings_view",
                label_key="overview_build_idle",
            )
        )

    active_research = research.get("active") if isinstance(research, dict) else None
    if active_research:
        label_key = str(active_research.get("key") or active_research.get("tech_key") or "research")
        cur = _safe_int(active_research.get("current_level"))
        targ = _safe_int(active_research.get("target_level"), cur + 1)
        summary = f"L{cur} → L{targ}"
        lines.append(
            _build_activity_line(
                key="research",
                state="active",
                summary=summary,
                remaining=_safe_int(active_research.get("remaining")),
                finish_at=_safe_int(active_research.get("finish_at")),
                href_key="research_view",
                label_key=label_key,
            )
        )
    else:
        lines.append(
            _build_activity_line(
                key="research",
                state="idle",
                summary="",
                href_key="research_view",
                label_key="overview_research_idle",
            )
        )

    sy_jobs = []
    if isinstance(shipyard_queue, dict):
        raw_jobs = shipyard_queue.get("queue")
        if isinstance(raw_jobs, list):
            sy_jobs = raw_jobs
    if sy_jobs:
        head = sy_jobs[0]
        sk = str(head.get("ship_key") or "")
        amt = _safe_int(head.get("amount"))
        lines.append(
            _build_activity_line(
                key="shipyard",
                state="active",
                summary=f"×{amt}" if amt else "",
                remaining=_safe_int(head.get("remaining")),
                finish_at=_safe_int(head.get("finish_at")),
                href_key="shipyard_view",
                label_key=f"fleet_ship_{sk}" if sk else "overview_activity_shipyard",
            )
        )
    else:
        lines.append(
            _build_activity_line(
                key="shipyard",
                state="idle",
                summary="",
                href_key="shipyard_view",
                label_key="overview_shipyard_idle",
            )
        )

    def_jobs = []
    if isinstance(defense_queue, dict):
        raw_def = defense_queue.get("queue")
        if isinstance(raw_def, list):
            def_jobs = raw_def
    if def_jobs:
        head = def_jobs[0]
        dk = str(head.get("defense_key") or "")
        amt = _safe_int(head.get("amount_remaining") or head.get("amount"))
        lines.append(
            _build_activity_line(
                key="defense",
                state="active",
                summary=f"×{amt}" if amt else "",
                remaining=_safe_int(head.get("remaining")),
                finish_at=_safe_int(head.get("finish_at")),
                href_key="defense_view",
                label_key=f"defense_{dk}" if dk else "overview_activity_defense",
            )
        )
    else:
        lines.append(
            _build_activity_line(
                key="defense",
                state="idle",
                summary="",
                href_key="defense_view",
                label_key="overview_defense_idle",
            )
        )

    reloc = planet_relocation if isinstance(planet_relocation, dict) else {}
    if reloc.get("active"):
        target = str(reloc.get("target") or "")
        lines.append(
            _build_activity_line(
                key="relocation",
                state="active",
                summary=target,
                remaining=_safe_int(reloc.get("remaining_seconds")),
                finish_at=_safe_int(reloc.get("finish_at")),
                href_key="overview",
                label_key="overview_relocation_active",
            )
        )

    return lines


def build_overview_warnings(
    *,
    user_id: int,
    ratio: float,
    energy_total: int,
    metal: float,
    crystal: float,
    fuel_cells: float = 0,
    storage_caps: Dict[str, Any],
    build_queue: Dict[str, Any],
    research: Dict[str, Any],
    fleet_movements: Optional[List[Dict[str, Any]]] = None,
    conn=None,
) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []

    et = int(energy_total or 0)
    r = float(ratio or 1.0)
    if et <= 0:
        warnings.append({"key": "energy_zero", "severity": "critical", "label_key": "overview_hint_energy_zero"})
    elif r < 1.0:
        warnings.append({"key": "energy_low", "severity": "warning", "label_key": "overview_hint_energy_low"})

    cap_m = float(storage_caps.get("metal") or 0)
    cap_c = float(storage_caps.get("crystal") or 0)
    cap_f = float(storage_caps.get("fuel_cells") or 0)
    if cap_m > 0 and float(metal or 0) >= cap_m * 0.92:
        warnings.append({"key": "storage_metal", "severity": "warning", "label_key": "overview_warning_storage_metal"})
    if cap_c > 0 and float(crystal or 0) >= cap_c * 0.92:
        warnings.append({"key": "storage_crystal", "severity": "warning", "label_key": "overview_warning_storage_crystal"})
    if cap_f > 0 and float(fuel_cells or 0) >= cap_f * 0.92:
        warnings.append({"key": "storage_fuel_cells", "severity": "warning", "label_key": "overview_warning_storage_fuel_cells"})

    bq_summary = build_queue.get("summary") if isinstance(build_queue, dict) else {}
    if isinstance(bq_summary, dict):
        count = _safe_int(bq_summary.get("count"))
        limit = _safe_int(bq_summary.get("limit"), 1)
        if limit > 0 and count >= limit:
            warnings.append({"key": "build_queue_full", "severity": "info", "label_key": "overview_warning_queue_full_build"})

    rs_summary = research.get("summary") if isinstance(research, dict) else {}
    if isinstance(rs_summary, dict):
        count = _safe_int(rs_summary.get("count"))
        limit = _safe_int(rs_summary.get("limit"), 1)
        if limit > 0 and count >= limit:
            warnings.append({"key": "research_queue_full", "severity": "info", "label_key": "overview_warning_queue_full_research"})

    try:
        from .options import _player_safety_row

        if conn is not None:
            row = _player_safety_row(int(user_id), conn)
            if bool(int(row.get("vacation_mode_active") or 0)):
                warnings.append(
                    {
                        "key": "vacation_mode",
                        "severity": "info",
                        "label_key": "overview_warning_vacation",
                        "href_key": "options_view",
                    }
                )
    except Exception:
        pass

    fleet_active = 0
    for mv in fleet_movements or []:
        if not isinstance(mv, dict):
            continue
        if str(mv.get("status") or "") in ("outbound", "holding", "returning"):
            fleet_active += 1
    if fleet_active > 0:
        warnings.append(
            {
                "key": "fleet_active",
                "severity": "info",
                "label_key": "overview_warning_fleet_active",
                "href_key": "fleet_view",
                "count": fleet_active,
            }
        )

    try:
        if conn is not None:
            from .vote_rewards import (
                count_pending_vote_rewards,
                count_voteable_providers,
                vote_system_ready,
            )

            uid = int(user_id)
            if vote_system_ready(conn):
                pending = count_pending_vote_rewards(uid, conn=conn)
                voteable = count_voteable_providers(uid, conn=conn)
                if pending > 0:
                    warnings.append(
                        {
                            "key": "vote_rewards_pending",
                            "severity": "info",
                            "label_key": "overview_warning_vote_rewards_pending",
                            "href_key": "vote_center_view",
                            "count": pending,
                        }
                    )
                elif voteable > 0:
                    warnings.append(
                        {
                            "key": "vote_available",
                            "severity": "info",
                            "label_key": "overview_warning_vote_available",
                            "href_key": "vote_center_view",
                            "count": voteable,
                        }
                    )
    except Exception:
        pass

    return warnings


def fetch_recent_log(player_id: int, *, limit: int = 5, conn=None) -> List[Dict[str, Any]]:
    del conn  # list_messages manages its own DB connection.
    try:
        from . import messages as messages_logic

        result = messages_logic.list_messages(int(player_id), limit=limit)
        if not result.get("ok"):
            return []
        data = result.get("data") or {}
        msgs = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(msgs, list):
            return []
        return [
            {
                "id": int(m.get("id") or 0),
                "category": str(m.get("category") or "system"),
                "subject": str(m.get("subject") or ""),
                "created_at": int(m.get("created_at") or 0),
                "time_display": time.strftime(
                    "%d.%m. %H:%M",
                    time.localtime(int(m.get("created_at") or 0)),
                )
                if int(m.get("created_at") or 0) > 0
                else "–",
                "is_read": bool(m.get("is_read")),
            }
            for m in msgs[:limit]
        ]
    except Exception:
        return []


def _load_overview_queue_fleet(
    user_id: int,
    planet_id: int,
    *,
    conn=None,
) -> tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    shipyard_queue: Dict[str, Any] = {}
    defense_queue: Dict[str, Any] = {}
    fleet_movements: List[Dict[str, Any]] = []
    own = conn is None
    if own:
        from .db import db as _db

        conn = _db()
    try:
        from .fleet import fleet_schema_ready, list_active_movements, process_fleet_tick

        if fleet_schema_ready(conn):
            # External conn: caller must run process_fleet_tick + commit before listing.
            if own:
                process_fleet_tick(player_id=int(user_id), conn=conn)
            fleet_movements = list_active_movements(int(user_id), conn=conn)
        from .shipyard import get_shipyard_level
        from .shipyard_queue import shipyard_queue_for_client, shipyard_queue_table_ready

        if shipyard_queue_table_ready(conn):
            sy_level = get_shipyard_level(int(user_id), int(planet_id), conn=conn)
            shipyard_queue = shipyard_queue_for_client(
                int(user_id), int(planet_id), sy_level, conn=conn
            )
        from .defense import defense_queue_for_client, defense_queue_table_ready

        if defense_queue_table_ready(conn):
            defense_queue = defense_queue_for_client(
                int(user_id), int(planet_id), conn=conn
            )
    except Exception:
        pass
    finally:
        if own and conn is not None:
            conn.close()
    return shipyard_queue, defense_queue, fleet_movements


def build_overview_status(
    *,
    user_id: int,
    player_view: Dict[str, Any],
    ratio: float,
    energy_total: int,
    energy_used: int,
    storage_caps: Dict[str, Any],
    prod_per_hour: Dict[str, Any],
    build_queue: Dict[str, Any],
    research: Dict[str, Any],
    planet: Dict[str, Any],
    include_log: bool = True,
    conn=None,
    shipyard_queue: Optional[Dict[str, Any]] = None,
    defense_queue: Optional[Dict[str, Any]] = None,
    fleet_movements: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    metal_ph = _safe_int(prod_per_hour.get("metal_mine") if isinstance(prod_per_hour, dict) else 0)
    crystal_ph = _safe_int(prod_per_hour.get("crystal_mine") if isinstance(prod_per_hour, dict) else 0)

    ratio_f = float(ratio or 1.0)
    if int(energy_total or 0) <= 0:
        energy_hint = "zero"
    elif ratio_f >= 1.0:
        energy_hint = "ok"
    elif ratio_f >= 0.5:
        energy_hint = "low"
    else:
        energy_hint = "critical"

    planet_id = _safe_int(planet.get("id"))
    if shipyard_queue is None or defense_queue is None or fleet_movements is None:
        loaded_sy, loaded_def, loaded_fleet = _load_overview_queue_fleet(
            int(user_id), planet_id, conn=conn
        )
        if shipyard_queue is None:
            shipyard_queue = loaded_sy
        if defense_queue is None:
            defense_queue = loaded_def
        if fleet_movements is None:
            fleet_movements = loaded_fleet

    planet_meta = build_planet_meta(planet, conn=conn)
    status: Dict[str, Any] = {
        "planet": planet_meta,
        "commander": {
            "id": _safe_int(player_view.get("id")),
            "name": str(player_view.get("name") or "Commander"),
        },
        "resources": {
            "metal": float(player_view.get("metal") or 0),
            "crystal": float(player_view.get("crystal") or 0),
            "fuel_cells": float(player_view.get("fuel_cells") or 0),
            "metal_cap": _safe_int(storage_caps.get("metal") if isinstance(storage_caps, dict) else 0),
            "crystal_cap": _safe_int(storage_caps.get("crystal") if isinstance(storage_caps, dict) else 0),
            "fuel_cells_cap": _safe_int(storage_caps.get("fuel_cells") if isinstance(storage_caps, dict) else 0),
            "metal_per_hour": metal_ph,
            "crystal_per_hour": crystal_ph,
            "fuel_cells_per_hour": _safe_int(
                prod_per_hour.get("fuel_cell_plant") if isinstance(prod_per_hour, dict) else 0
            ),
        },
        "energy": {
            "total": int(energy_total or 0),
            "used": int(energy_used or 0),
            "ratio": float(ratio or 1.0),
            "hint": energy_hint,
        },
        "activities": build_activity_lines(
            build_queue,
            research,
            shipyard_queue=shipyard_queue,
            defense_queue=defense_queue,
            planet_relocation=planet_meta.get("relocation"),
        ),
        "warnings": build_overview_warnings(
            user_id=int(user_id),
            ratio=float(ratio or 1.0),
            energy_total=int(energy_total or 0),
            metal=float(player_view.get("metal") or 0),
            crystal=float(player_view.get("crystal") or 0),
            fuel_cells=float(player_view.get("fuel_cells") or 0),
            storage_caps=storage_caps if isinstance(storage_caps, dict) else {},
            build_queue=build_queue if isinstance(build_queue, dict) else {},
            research=research if isinstance(research, dict) else {},
            fleet_movements=fleet_movements,
            conn=conn,
        ),
    }

    if include_log:
        status["recent_log"] = fetch_recent_log(int(user_id), limit=5, conn=conn)

    return status


def build_overview_page_context(
    user_id: int,
    ctx: Dict[str, Any],
    *,
    planet: Dict[str, Any],
    conn=None,
) -> Dict[str, Any]:
    """Full template context for overview.html (SSR/PJAX — no dead API-only slices)."""
    player_view = ctx["player_view"]
    status = build_overview_status(
        user_id=int(user_id),
        player_view=player_view,
        ratio=float(ctx.get("ratio") or 1.0),
        energy_total=int(ctx.get("energy_total") or 0),
        energy_used=int(ctx.get("energy_used") or 0),
        storage_caps=ctx.get("storage_caps") or {},
        prod_per_hour=ctx.get("prod_per_hour") or {},
        build_queue=ctx.get("build_queue") or {},
        research=ctx.get("research") or {},
        planet=planet,
        include_log=False,
        conn=conn,
    )
    return status
