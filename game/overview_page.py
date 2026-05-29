"""Overview page context — OGame-style colony status (no building/research duplication)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .planet_evolution.ux_copy import planet_class_label_key

# TODO: Persist planet surface temperature in DB; until then derive from planet_class.
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


def _coordinates_display(planet: Dict[str, Any]) -> str:
    galaxy = _safe_int(planet.get("galaxy"), 1)
    system = planet.get("system")
    position = planet.get("position")
    system_txt = str(system) if system not in (None, "") else "?"
    pos_txt = str(position) if position not in (None, "") else "?"
    return f"G{galaxy} · Sektor {system_txt} · Position {pos_txt}"


def build_planet_meta(planet: Dict[str, Any]) -> Dict[str, Any]:
    planet_class = str(planet.get("planet_class") or "terrestrial")
    temp = temperature_range_for_class(planet_class)
    is_homeworld = bool(int(planet.get("is_homeworld") or 0))
    return {
        "planet_id": _safe_int(planet.get("id")),
        "name": str(planet.get("name") or "Kolonie"),
        "is_homeworld": is_homeworld,
        "can_delete": not is_homeworld,
        "planet_class": planet_class,
        "planet_class_label_key": planet_class_label_key(planet_class),
        "coordinates": {
            "galaxy": _safe_int(planet.get("galaxy"), 1),
            "system": planet.get("system"),
            "position": planet.get("position"),
            "display": _coordinates_display(planet),
        },
        "temperature": temp,
    }


def _build_activity_line(
    *,
    key: str,
    state: str,
    summary: str,
    remaining: int = 0,
    finish_at: int = 0,
    href_key: str,
    label_key: str,
) -> Dict[str, Any]:
    return {
        "key": key,
        "state": state,
        "summary": summary,
        "remaining": int(remaining),
        "remaining_display": _format_remaining(remaining) if state == "active" else "",
        "finish_at": int(finish_at or 0),
        "href_key": href_key,
        "label_key": label_key,
    }


def build_activity_lines(
    build_queue: Dict[str, Any],
    research: Dict[str, Any],
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

    # TODO: Wire fleet missions when fleet system ships.
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


def build_overview_warnings(
    *,
    ratio: float,
    energy_total: int,
    metal: float,
    crystal: float,
    storage_caps: Dict[str, Any],
    build_queue: Dict[str, Any],
    research: Dict[str, Any],
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
    if cap_m > 0 and float(metal or 0) >= cap_m * 0.92:
        warnings.append({"key": "storage_metal", "severity": "warning", "label_key": "overview_warning_storage_metal"})
    if cap_c > 0 and float(crystal or 0) >= cap_c * 0.92:
        warnings.append({"key": "storage_crystal", "severity": "warning", "label_key": "overview_warning_storage_crystal"})

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
) -> Dict[str, Any]:
    eff = int(round(float(ratio or 1.0) * 100))
    eff = max(0, min(100, eff))

    metal_ph = _safe_int(prod_per_hour.get("metal_mine") if isinstance(prod_per_hour, dict) else 0)
    crystal_ph = _safe_int(prod_per_hour.get("crystal_mine") if isinstance(prod_per_hour, dict) else 0)

    energy_hint = (
        "zero"
        if int(energy_total or 0) <= 0
        else ("ok" if float(ratio or 1.0) >= 1.0 else "low")
    )

    status: Dict[str, Any] = {
        "planet": build_planet_meta(planet),
        "commander": {
            "id": _safe_int(player_view.get("id")),
            "name": str(player_view.get("name") or "Commander"),
        },
        "resources": {
            "metal": float(player_view.get("metal") or 0),
            "crystal": float(player_view.get("crystal") or 0),
            "metal_cap": _safe_int(storage_caps.get("metal") if isinstance(storage_caps, dict) else 0),
            "crystal_cap": _safe_int(storage_caps.get("crystal") if isinstance(storage_caps, dict) else 0),
            "metal_per_hour": metal_ph,
            "crystal_per_hour": crystal_ph,
        },
        "energy": {
            "total": int(energy_total or 0),
            "used": int(energy_used or 0),
            "ratio": float(ratio or 1.0),
            "efficiency_pct": eff,
            "hint": energy_hint,
        },
        "activities": build_activity_lines(build_queue, research),
        "warnings": build_overview_warnings(
            ratio=float(ratio or 1.0),
            energy_total=int(energy_total or 0),
            metal=float(player_view.get("metal") or 0),
            crystal=float(player_view.get("crystal") or 0),
            storage_caps=storage_caps if isinstance(storage_caps, dict) else {},
            build_queue=build_queue if isinstance(build_queue, dict) else {},
            research=research if isinstance(research, dict) else {},
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
    """Full template context for overview.html."""
    player_view = ctx["player_view"]
    return build_overview_status(
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
        include_log=True,
        conn=conn,
    )
