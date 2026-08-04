"""Ground troop definitions for Secret Vault Raid (Barracks)."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Mapping, Optional

TROOP_ORDER: List[str] = [
    "militia",
    "breach_team",
    "vault_guard",
]

ACTIVE_TROOP_KEYS: FrozenSet[str] = frozenset(TROOP_ORDER)

TROOPS: Dict[str, Dict[str, Any]] = {
    "militia": {
        "name_key": "troop_militia",
        "description_key": "troop_militia_desc",
        "required_barracks_level": 1,
        # ~cost of a light combat craft component; not disposable spam.
        "train_cost": {"metal": 5000, "crystal": 2000, "fuel_cells": 0},
        "train_seconds": 180,
        "attack": 8,
        "defense": 6,
        "hull": 40,
        "cargo_slots": 1,
        "icon": "img/troops/militia.png",
    },
    "breach_team": {
        "name_key": "troop_breach_team",
        "description_key": "troop_breach_team_desc",
        "required_barracks_level": 3,
        "train_cost": {"metal": 18000, "crystal": 12000, "fuel_cells": 0},
        "train_seconds": 420,
        "attack": 22,
        "defense": 12,
        "hull": 90,
        "cargo_slots": 2,
        "icon": "img/troops/breach_team.png",
    },
    "vault_guard": {
        "name_key": "troop_vault_guard",
        "description_key": "troop_vault_guard_desc",
        "required_barracks_level": 5,
        "train_cost": {"metal": 35000, "crystal": 28000, "fuel_cells": 0},
        "train_seconds": 720,
        "attack": 18,
        "defense": 35,
        "hull": 160,
        "cargo_slots": 2,
        "icon": "img/troops/vault_guard.png",
    },
}


def get_troop(troop_key: str) -> Optional[Dict[str, Any]]:
    key = str(troop_key or "").strip()
    if key not in ACTIVE_TROOP_KEYS:
        return None
    return dict(TROOPS[key])


def is_known_troop_key(troop_key: str) -> bool:
    return str(troop_key or "").strip() in ACTIVE_TROOP_KEYS


def troop_icon_filename(troop_key: str) -> str:
    key = str(troop_key or "").strip()
    return f"{key}.png" if key in ACTIVE_TROOP_KEYS else "militia.png"


def troop_icon_static_path(troop_key: str) -> str:
    return f"/static/img/troops/{troop_icon_filename(troop_key)}"


def troop_display_name(troop_key: str, *, locale: str | None = None) -> str:
    from .i18n import tr

    spec = get_troop(troop_key) or {}
    name_key = str(spec.get("name_key") or f"troop_{troop_key}")
    return tr(name_key, str(troop_key), locale=locale)


def normalize_troops(raw: Any) -> Dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for key, val in raw.items():
        k = str(key or "").strip()
        if k not in ACTIVE_TROOP_KEYS:
            continue
        try:
            qty = int(val or 0)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            out[k] = qty
    return out


def troop_power(troops: Dict[str, int], *, role: str = "attack") -> int:
    """Simple power score for ground raids (server-only)."""
    total = 0
    for key, amount in (troops or {}).items():
        spec = get_troop(str(key))
        if not spec:
            continue
        qty = max(0, int(amount or 0))
        if qty <= 0:
            continue
        atk = int(spec.get("attack") or 0)
        defense = int(spec.get("defense") or 0)
        hull = int(spec.get("hull") or 0)
        if role == "defense":
            total += qty * (defense * 2 + hull + atk)
        else:
            total += qty * (atk * 2 + hull + defense)
    return max(0, int(total))


def troop_cargo_slots(troops: Dict[str, int]) -> int:
    slots = 0
    for key, amount in (troops or {}).items():
        spec = get_troop(str(key))
        if not spec:
            continue
        slots += max(0, int(amount or 0)) * max(1, int(spec.get("cargo_slots") or 1))
    return int(slots)


def fleet_troop_berth_capacity(ships: Mapping[str, int] | None) -> int:
    """Max troop cargo slots a fleet can embark — sum of ship `crew` × count."""
    from .fleet_defs import get_ship

    total = 0
    for key, raw in (ships or {}).items():
        try:
            qty = int(raw or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        spec = get_ship(str(key)) or {}
        total += qty * max(0, int(spec.get("crew") or 0))
    return int(total)


def troops_fit_fleet_berths(
    ships: Mapping[str, int] | None,
    troops: Mapping[str, int] | None,
) -> bool:
    need = troop_cargo_slots(normalize_troops(troops))
    if need <= 0:
        return True
    return need <= fleet_troop_berth_capacity(ships)


def troop_train_cost(troop_key: str) -> Dict[str, int]:
    spec = get_troop(troop_key) or {}
    cost = spec.get("train_cost") or {}
    return {
        "metal": max(0, int(cost.get("metal") or 0)),
        "crystal": max(0, int(cost.get("crystal") or 0)),
        "fuel_cells": max(0, int(cost.get("fuel_cells") or 0)),
    }


def troop_score_value(troop_key: str) -> int:
    """Wealth score per stored troop — canonical resource_score from train_cost."""
    from .resource_score import score_from_cost_dict

    return score_from_cost_dict(troop_train_cost(str(troop_key)))


def barracks_troop_capacity(barracks_level: int) -> int:
    """Barracks ground-troop stock slots.

    Breakpoints (approx): L1≈236, L10≈162k, L25≈6.3M, L50≈100M.
    """
    lvl = max(0, int(barracks_level or 0))
    if lvl <= 0:
        return 0
    return int(20 + lvl * 200 + (lvl ** 4) * 16)
