"""Specialization eligibility, presentation, and tier progression."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .constants import MAX_SPECIALIZATION_TIER
from .definitions import get_specialization, get_specializations, get_trait
from .dna import all_trait_keys
from .repository import get_planet_dna, get_planet_row

TIER_LEVEL_REQUIREMENTS = {
    2: 14,
    3: 22,
}


def _spec_trait_labels(spec: Dict[str, Any]) -> List[str]:
    return [str(t) for t in (spec.get("required_traits_any") or [])]


def _synergy_score(spec: Dict[str, Any], traits: set, affinities: Dict[str, Any]) -> int:
    score = 0
    for trait in _spec_trait_labels(spec):
        if trait in traits:
            score += 10
    for key, need in (spec.get("required_affinities") or {}).items():
        have = int(affinities.get(key, 0) or 0)
        if have >= int(need):
            score += 5 + min(5, (have - int(need)) // 5)
    return score


def _ineligible_reason(
    spec_key: str,
    spec: Dict[str, Any],
    *,
    planet_level: int,
    traits: set,
    affinities: Dict[str, Any],
    current_spec: Optional[str],
) -> Optional[str]:
    min_level = int(spec.get("min_planet_level") or 8)
    if planet_level < min_level:
        return "level"

    incompatible = spec.get("incompatible_specs") or []
    if current_spec and str(current_spec) in [str(x) for x in incompatible]:
        return "incompatible"

    req_traits = _spec_trait_labels(spec)
    if req_traits and not any(t in traits for t in req_traits):
        return "traits"

    for key, need in (spec.get("required_affinities") or {}).items():
        if int(affinities.get(key, 0) or 0) < int(need):
            return "affinity"

    return None


def list_specialization_options(
    planet_id: int,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    dna = get_planet_dna(planet_id, conn=conn) or {}
    reveal = int(planet.get("dna_reveal_tier") or 0)
    traits = set(all_trait_keys(dna, reveal_tier=max(reveal, 1)))
    affinities = dna.get("affinity_scores") or {}
    level = int(planet.get("planet_level") or 1)
    current_spec = planet.get("specialization_key")

    options: List[Dict[str, Any]] = []
    for spec_key, spec in get_specializations().items():
        reason = _ineligible_reason(
            spec_key,
            spec,
            planet_level=level,
            traits=traits,
            affinities=affinities,
            current_spec=str(current_spec) if current_spec else None,
        )
        synergy_traits = [t for t in _spec_trait_labels(spec) if t in traits]
        options.append(
            {
                "spec_key": spec_key,
                "label_key": spec.get("label_key") or f"spec_{spec_key}",
                "tagline_key": f"pe_spec_tagline_{spec_key}",
                "eligible": reason is None,
                "locked_reason_key": f"pe_spec_lock_{reason}" if reason else None,
                "synergy_score": _synergy_score(spec, traits, affinities),
                "synergy_traits": synergy_traits,
                "synergy_trait_labels": [
                    (get_trait(t) or {}).get("lore_key") or f"trait_{t}" for t in synergy_traits
                ],
                "tier_preview": build_tier_roadmap(spec_key),
                "event_count": len(spec.get("event_pool") or []),
                "import_preview": _import_preview(spec),
            }
        )

    options.sort(key=lambda o: (-int(o["synergy_score"]), str(o["spec_key"])))
    return options


def eligible_specialization_keys(planet_id: int, conn: sqlite3.Connection) -> List[str]:
    return [o["spec_key"] for o in list_specialization_options(planet_id, conn) if o["eligible"]]


def humanize_unlock_token(token: str) -> Dict[str, Any]:
    raw = str(token or "").strip()
    if raw.startswith("export:"):
        key = raw.split(":", 1)[1]
        return {"type": "export", "label_key": f"resource_{key}", "text_key": f"pe_unlock_export_{key}"}
    if raw.startswith("chain:"):
        key = raw.split(":", 1)[1]
        return {"type": "chain", "label_key": f"chain_{key}", "text_key": f"pe_unlock_chain_{key}"}
    if raw.startswith("policy:"):
        key = raw.split(":", 1)[1]
        return {"type": "policy", "label_key": f"policy_{key}", "text_key": f"pe_unlock_policy_{key}"}
    if raw.startswith("enable_event_pool:"):
        pool = raw.split(":", 1)[1]
        return {"type": "events", "text_key": f"pe_unlock_event_pool_{pool}"}
    if raw.startswith("trade_route_bonus:"):
        return {"type": "trade", "text_key": "pe_unlock_trade_route_bonus"}
    if raw.startswith("trade_route_max:"):
        return {"type": "trade", "text_key": "pe_unlock_trade_route_max"}
    if raw.startswith("discovery_roll_bonus:"):
        return {"type": "discovery", "text_key": "pe_unlock_discovery_bonus"}
    if raw.startswith("experimental_slot:"):
        return {"type": "experimental", "text_key": "pe_unlock_experimental_slot"}
    if raw.startswith("conversion_queue:"):
        return {"type": "queue", "text_key": "pe_unlock_conversion_queue"}
    if raw.startswith("auto_conversion:"):
        return {"type": "automation", "text_key": "pe_unlock_auto_conversion"}
    if raw == "enable_experimental":
        return {"type": "experimental", "text_key": "pe_unlock_enable_experimental"}
    if raw == "defense_mechanic":
        return {"type": "defense", "text_key": "pe_unlock_defense_mechanic"}
    if raw == "deep_core_auto":
        return {"type": "industry", "text_key": "pe_unlock_deep_core_auto"}
    if raw == "crime_sweet_spot_mechanic":
        return {"type": "crime", "text_key": "pe_unlock_crime_sweet_spot"}
    if raw == "market_fee_mechanic":
        return {"type": "trade", "text_key": "pe_unlock_market_fee"}
    if raw == "stability_risk_mechanic":
        return {"type": "risk", "text_key": "pe_unlock_stability_risk"}
    if raw == "loyalty_mechanic_bypass":
        return {"type": "governance", "text_key": "pe_unlock_loyalty_bypass"}
    if raw.startswith("risk:"):
        return {"type": "risk", "text_key": "pe_unlock_spec_risk"}
    return {"type": "other", "text_key": "pe_unlock_generic_mechanic", "raw": raw}


def build_tier_roadmap(spec_key: str) -> List[Dict[str, Any]]:
    spec = get_specialization(spec_key) or {}
    tiers: List[Dict[str, Any]] = []
    for tier in range(1, MAX_SPECIALIZATION_TIER + 1):
        bundle = (spec.get("tier_mechanics") or {}).get(f"tier_{tier}") or {}
        unlocks = []
        for token in bundle.get("unlocks") or []:
            unlocks.append(humanize_unlock_token(str(token)))
        tiers.append(
            {
                "tier": tier,
                "title_key": f"pe_spec_tier_title_{tier}",
                "summary_key": f"pe_spec_t{tier}_{spec_key}",
                "unlocks": unlocks,
                "level_required": TIER_LEVEL_REQUIREMENTS.get(tier, 8 if tier == 1 else None),
            }
        )
    return tiers


def _import_preview(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    preview = []
    tier1 = (spec.get("tier_mechanics") or {}).get("tier_1") or {}
    demands = tier1.get("import_demands") or spec.get("import_demands") or []
    for d in demands:
        if isinstance(d, dict):
            preview.append(
                {
                    "resource_key": d.get("resource_key"),
                    "label_key": f"resource_{d.get('resource_key')}",
                    "required_per_hour": float(d.get("required_per_hour") or 0),
                }
            )
    return preview


def build_active_specialization_payload(
    planet_id: int,
    conn: sqlite3.Connection,
) -> Optional[Dict[str, Any]]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    spec_key = planet.get("specialization_key")
    if not spec_key:
        return None

    spec = get_specialization(str(spec_key)) or {}
    tier = int(planet.get("specialization_tier") or 0)
    level = int(planet.get("planet_level") or 1)
    roadmap = build_tier_roadmap(str(spec_key))

    active_unlocks: List[Dict[str, Any]] = []
    for step in roadmap:
        if int(step["tier"]) <= tier:
            active_unlocks.extend(step.get("unlocks") or [])

    next_tier = tier + 1 if tier < MAX_SPECIALIZATION_TIER else None
    upgrade = None
    if next_tier:
        need_level = TIER_LEVEL_REQUIREMENTS.get(next_tier, 999)
        upgrade = {
            "next_tier": next_tier,
            "required_level": need_level,
            "current_level": level,
            "can_upgrade": level >= need_level,
            "unlocks_preview": (roadmap[next_tier - 1].get("unlocks") if next_tier <= len(roadmap) else []),
            "summary_key": f"pe_spec_t{next_tier}_{spec_key}",
        }

    return {
        "spec_key": spec_key,
        "label_key": spec.get("label_key") or f"spec_{spec_key}",
        "tagline_key": f"pe_spec_tagline_{spec_key}",
        "tier": tier,
        "max_tier": MAX_SPECIALIZATION_TIER,
        "roadmap": roadmap,
        "active_unlocks": active_unlocks,
        "event_pool": spec.get("event_pool") or [],
        "event_labels": [f"event_{e}" for e in (spec.get("event_pool") or [])],
        "import_demands": _import_preview(spec),
        "upgrade": upgrade,
        "identity_key": f"pe_spec_identity_{spec_key}",
    }


def tier_upgrade_requirements(planet_id: int, conn: sqlite3.Connection) -> Tuple[bool, List[str]]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    spec_key = planet.get("specialization_key")
    if not spec_key:
        return False, ["no_specialization"]

    tier = int(planet.get("specialization_tier") or 0)
    if tier >= MAX_SPECIALIZATION_TIER:
        return False, ["max_tier"]

    next_tier = tier + 1
    need_level = TIER_LEVEL_REQUIREMENTS.get(next_tier)
    if need_level is None:
        return False, ["invalid_tier"]

    level = int(planet.get("planet_level") or 1)
    if level < need_level:
        return False, [f"planet_level>={need_level}"]

    return True, []
