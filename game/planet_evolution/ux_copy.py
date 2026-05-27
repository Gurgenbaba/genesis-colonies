"""Human-readable requirement and status copy for Planet Evolution UI."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .definitions import get_research_def, get_trait

_REQ_PLANET_LEVEL = re.compile(r"planet_level>=(\d+)")
_REQ_SPEC_TIER = re.compile(r"specialization_tier>=(\d+)")
_REQ_SPEC = re.compile(r"specialization=(\w+)")
_REQ_BUILDING = re.compile(r"building:(\w+)>=(\d+)")
_REQ_PLANET_RESEARCH = re.compile(r"planet_research:(\w+)>=(\d+)")
_REQ_IMPERIAL = re.compile(r"imperial_research:(\w+)>=(\d+)")
_REQ_TRAITS_ANY = re.compile(r"traits_any:(.+)")
_REQ_TRAITS_NONE = re.compile(r"traits_none:(\w+)")
_REQ_LOCKED = re.compile(r"locked_choice:(\w+)=(\w+)")

_CATEGORY_KEYS = {
    "geology": "pe_cat_geology",
    "atmosphere": "pe_cat_atmosphere",
    "anomaly": "pe_cat_anomaly",
    "culture": "pe_cat_culture",
    "biology": "pe_cat_biology",
}

_POLARITY_KEYS = {
    "positive": "pe_trait_badge_positive",
    "negative": "pe_trait_badge_negative",
    "rare": "pe_trait_badge_rare",
    "neutral": "pe_trait_badge_neutral",
}

_PLANET_CLASS_KEYS = {
    "terrestrial": "pe_class_terrestrial",
    "volcanic": "pe_class_volcanic",
    "ice": "pe_class_ice",
    "barren": "pe_class_barren",
    "oceanic": "pe_class_oceanic",
    "ruin": "pe_class_ruin",
    "gas_giant_moon": "pe_class_gas_moon",
}

_LEVEL_UNLOCK_LABELS = {
    ("dna_reveal", 1): "pe_unlock_dna_1",
    ("policy_slot", 1): "pe_unlock_policy_1",
    ("specialization",): "pe_unlock_specialization",
    ("export_slot", 2): "pe_unlock_export_2",
    ("dna_reveal", 2): "pe_unlock_dna_2",
    ("policy_slot", 2): "pe_unlock_policy_2",
    ("experimental_gate",): "pe_unlock_experimental",
    ("ascension",): "pe_unlock_ascension",
    ("policy_slot", 3): "pe_unlock_policy_3",
}

_EVENT_STATE_KEYS = {
    "pending": "pe_event_state_pending",
    "active": "pe_event_state_active",
    "resolved": "pe_event_state_resolved",
    "expired": "pe_event_state_expired",
}


def category_label_key(category: str) -> str:
    return _CATEGORY_KEYS.get(str(category or ""), "pe_cat_other")


def polarity_label_key(polarity: str) -> str:
    return _POLARITY_KEYS.get(str(polarity or ""), "pe_trait_badge_neutral")


def planet_class_label_key(planet_class: str) -> str:
    return _PLANET_CLASS_KEYS.get(str(planet_class or ""), "pe_class_terrestrial")


def humanize_requirement(raw: str, *, planet_level: int = 1) -> Dict[str, Any]:
    """Return structured copy for templates: label_key + format kwargs."""
    s = str(raw or "").strip()
    m = _REQ_PLANET_LEVEL.match(s)
    if m:
        need = int(m.group(1))
        return {
            "label_key": "pe_req_planet_level",
            "need": need,
            "current": planet_level,
            "fallback": f"Planet muss Stufe {need} erreichen (aktuell: Stufe {planet_level})",
        }
    m = _REQ_SPEC_TIER.match(s)
    if m:
        need = int(m.group(1))
        return {
            "label_key": "pe_req_spec_tier",
            "need": need,
            "fallback": f"Spezialisierung Stufe {need} erforderlich",
        }
    m = _REQ_SPEC.match(s)
    if m:
        spec = m.group(1)
        return {
            "label_key": "pe_req_spec",
            "spec_key": spec,
            "fallback": f"Benötigt Spezialisierung: {spec}",
        }
    m = _REQ_BUILDING.match(s)
    if m:
        bkey, need = m.group(1), int(m.group(2))
        return {
            "label_key": "pe_req_building",
            "building": bkey,
            "need": need,
            "fallback": f"Benötigt Gebäude: {bkey} (Stufe {need})",
        }
    m = _REQ_PLANET_RESEARCH.match(s)
    if m:
        tech, need = m.group(1), int(m.group(2))
        rdef = get_research_def(tech) or {}
        tech_name = rdef.get("label_key") or tech
        return {
            "label_key": "pe_req_planet_research",
            "tech_key": tech,
            "tech_label_key": tech_name,
            "need": need,
            "fallback": f"Benötigt: {tech_name} (Stufe {need})",
        }
    m = _REQ_IMPERIAL.match(s)
    if m:
        tech, need = m.group(1), int(m.group(2))
        return {
            "label_key": "pe_req_imperial_research",
            "tech_key": tech,
            "need": need,
            "fallback": f"Benötigt Imperiums-Forschung: {tech} (Stufe {need})",
        }
    m = _REQ_TRAITS_ANY.match(s)
    if m:
        return {
            "label_key": "pe_req_traits_any",
            "fallback": "Benötigt passende Planet-Eigenschaft",
        }
    m = _REQ_TRAITS_NONE.match(s)
    if m:
        trait = m.group(1)
        tdef = get_trait(trait) or {}
        return {
            "label_key": "pe_req_trait_none",
            "trait_key": trait,
            "trait_label_key": tdef.get("lore_key") or f"trait_{trait}",
            "fallback": f"Darf nicht haben: {trait}",
        }
    m = _REQ_LOCKED.match(s)
    if m:
        return {
            "label_key": "pe_req_locked_choice",
            "fallback": "Benötigt vorherige permanente Entscheidung",
        }
    return {"label_key": "pe_req_unknown", "raw": s, "fallback": s.replace("_", " ")}


def humanize_requirements(missing: List[str], *, planet_level: int = 1) -> List[Dict[str, Any]]:
    return [humanize_requirement(m, planet_level=planet_level) for m in (missing or [])]


def level_unlock_label_key(level: int, unlock: Tuple[Any, ...]) -> str:
    return _LEVEL_UNLOCK_LABELS.get(tuple(unlock), "pe_unlock_generic")


def event_state_label_key(state: str) -> str:
    return _EVENT_STATE_KEYS.get(str(state or ""), "pe_event_state_unknown")
