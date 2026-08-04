"""Command Initiation pack loader (data-driven steps)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

PACKS_DIR = Path(__file__).resolve().parent / "packs"
PACK_FILENAME = "phase1_colony_core.json"


@lru_cache(maxsize=1)
def load_pack() -> Dict[str, Any]:
    path = PACKS_DIR / PACK_FILENAME
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("initiation pack must be an object")
    return data


def flatten_steps(pack: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """Return ordered steps with phase_id attached."""
    root = pack or load_pack()
    out: List[Dict[str, Any]] = []
    for phase in root.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        phase_id = str(phase.get("id") or "")
        phase_title_key = str(phase.get("title_key") or "")
        for step in phase.get("steps") or []:
            if not isinstance(step, dict):
                continue
            row = dict(step)
            row["phase_id"] = phase_id
            row["phase_title_key"] = phase_title_key
            out.append(row)
    return out


def step_at(index: int, pack: Dict[str, Any] | None = None) -> Optional[Dict[str, Any]]:
    steps = flatten_steps(pack)
    if index < 0 or index >= len(steps):
        return None
    return dict(steps[index])


def step_count(pack: Dict[str, Any] | None = None) -> int:
    return len(flatten_steps(pack))


def phase_bounds(pack: Dict[str, Any] | None = None) -> List[Tuple[str, int, int]]:
    """List of (phase_id, start_index, end_index_exclusive)."""
    root = pack or load_pack()
    bounds: List[Tuple[str, int, int]] = []
    idx = 0
    for phase in root.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        phase_id = str(phase.get("id") or "")
        n = len([s for s in (phase.get("steps") or []) if isinstance(s, dict)])
        bounds.append((phase_id, idx, idx + n))
        idx += n
    return bounds


def step_highlight_key(step: Dict[str, Any] | None) -> str:
    """Explicit highlight, or first building_types filter for upgrade objectives."""
    if not step:
        return ""
    explicit = str(step.get("highlight") or "").strip()
    if explicit:
        return explicit
    filters = step.get("filters") if isinstance(step.get("filters"), dict) else {}
    types = filters.get("building_types") or []
    if types:
        return str(types[0] or "").strip()
    tech_keys = filters.get("research_keys") or []
    if tech_keys:
        return str(tech_keys[0] or "").strip()
    return ""


def step_image_path(step: Dict[str, Any] | None) -> str:
    """Static-relative art path for mission cards (img/...)."""
    if not step:
        return "img/buildings/command_center.png"
    explicit = str(step.get("image") or "").strip()
    if explicit:
        return explicit.lstrip("/")
    objective = str(step.get("objective_key") or "")
    highlight = step_highlight_key(step)
    from ..buildings import get_building_icon

    if objective == "upgrade_buildings" and highlight:
        return get_building_icon(highlight)
    if objective == "complete_research":
        return get_building_icon("research_lab")
    if objective == "build_ships":
        return get_building_icon("orbital_shipyard")
    if objective == "build_defense":
        return get_building_icon("defense_factory")
    if objective == "send_fleet_missions":
        from ..fleet_defs import ship_icon_filename

        return f"img/ships/{ship_icon_filename('light_fighter')}"
    if highlight:
        return get_building_icon(highlight)
    return "img/buildings/command_center.png"


def resolve_step_route(step: Dict[str, Any] | None) -> str:
    """Go-href with tab/highlight query so the target page can mark the objective."""
    if not step:
        return ""
    base = str(step.get("route") or "").strip() or "/"
    highlight = step_highlight_key(step)
    if not highlight:
        return base
    if base.startswith("/buildings"):
        from ..buildings import get_building_tab

        tab = get_building_tab(highlight)
        qs = urlencode({"tab": tab, "highlight": highlight})
        return f"/buildings?{qs}"
    if base.startswith("/research"):
        qs = urlencode({"highlight": highlight})
        return f"/research?{qs}"
    # Generic: append highlight for other pages without breaking path.
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{urlencode({'highlight': highlight})}"
