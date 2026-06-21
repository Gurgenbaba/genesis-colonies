"""Overview page context — OGame-style colony status (no building/research duplication)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .fleet_calc import enrich_movement_timing
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


def _format_fleet_countdown(seconds: int) -> str:
    """Match client formatCountdownRemain (fleet page + overview fleet rows)."""
    sec = max(0, int(seconds or 0))
    rh = sec // 3600
    rm = (sec % 3600) // 60
    rs = sec % 60
    if rh > 0:
        return f"{rh}h {rm}m"
    if rm > 0:
        return f"{rm}m {rs}s"
    return f"{rs}s"


def build_planet_meta(planet: Dict[str, Any]) -> Dict[str, Any]:
    from .galaxy import get_planet_coordinates
    from .planet_evolution.dna import effective_planet_class

    planet_class = effective_planet_class(planet)
    coords = get_planet_coordinates(planet)
    position = int(coords.get("position") or 0)
    from .planet_visuals import planet_theme_for_planet, temperature_range_for_position

    temp = temperature_range_for_position(position)
    is_homeworld = bool(int(planet.get("is_homeworld") or 0))
    theme = planet_theme_for_planet({**planet, "position": position})
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
        "theme": theme,
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


def _fleet_movement_activity_lines(
    movements: List[Dict[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    ts = float(now if now is not None else time.time())
    lines: List[Dict[str, Any]] = []
    for mv in movements or []:
        if not isinstance(mv, dict):
            continue
        status = str(mv.get("status") or "")
        if status not in ("outbound", "holding", "returning"):
            continue
        enriched = enrich_movement_timing(mv, now=ts)
        end_at = int(enriched.get("countdown_at") or 0)
        remaining = int(enriched.get("remaining_seconds") or 0)
        mission = str(mv.get("mission_type") or "transport")
        target = str(mv.get("target_coords") or "")
        ship_count = sum(int(v) for v in (mv.get("ships") or {}).values())
        phase = str(enriched.get("phase") or enriched.get("leg_phase") or "")
        status_label = str(enriched.get("status_label") or enriched.get("leg_label_key") or "")
        summary = f"{target} · {ship_count}"
        lines.append(
            _build_activity_line(
                key=f"fleet_{_safe_int(mv.get('id'))}",
                state="active",
                summary=summary,
                remaining=remaining,
                finish_at=end_at,
                countdown_at=end_at,
                phase=phase,
                status_label=status_label,
                movement_id=_safe_int(mv.get("id")),
                href_key="fleet_view",
                label_key=f"fleet_mission_{mission}",
            )
        )
        lines[-1]["remaining_display"] = _format_fleet_countdown(remaining)
    if not lines:
        lines.append(
            _build_activity_line(
                key="fleet",
                state="idle",
                summary="",
                href_key="fleet_view",
                label_key="overview_fleet_idle",
            )
        )
    return lines


def build_activity_lines(
    build_queue: Dict[str, Any],
    research: Dict[str, Any],
    *,
    shipyard_queue: Optional[Dict[str, Any]] = None,
    defense_queue: Optional[Dict[str, Any]] = None,
    fleet_movements: Optional[List[Dict[str, Any]]] = None,
    now: Optional[float] = None,
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

    lines.extend(_fleet_movement_activity_lines(fleet_movements or [], now=now))
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
            from .vote_rewards import count_voteable_providers, vote_system_ready

            if vote_system_ready(conn) and count_voteable_providers(int(user_id), conn=conn) > 0:
                warnings.append(
                    {
                        "key": "vote_available",
                        "severity": "info",
                        "label_key": "overview_warning_vote_available",
                        "href_key": "vote_center_view",
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

    status: Dict[str, Any] = {
        "planet": build_planet_meta(planet),
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
            fleet_movements=fleet_movements,
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
    galaxy_id = _safe_int((status.get("planet") or {}).get("coordinates", {}).get("galaxy"))
    if galaxy_id <= 0:
        galaxy_id = _safe_int(planet.get("galaxy"))
    from .galactic_directives.banner import build_galactic_directive_banner
    from .galactic_diplomacy.banner import build_galactic_diplomacy_banner

    status["galactic_directive_banner"] = build_galactic_directive_banner(
        galaxy_id,
        conn=conn,
    )
    status["galactic_diplomacy_banner"] = build_galactic_diplomacy_banner(
        galaxy_id,
        conn=conn,
    )
    return status
