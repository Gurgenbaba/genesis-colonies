"""
EPIC-27 — Commander class / skill catalog (code-first).

Owner: game/commander_class_catalog.py · Docs: docs/COMMANDER_CLASSES.md
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

CLASS_KEYS: Tuple[str, ...] = (
    "vanguard",
    "forge_lord",
    "archivist",
    "void_admiral",
    "envoy",
)

CLASSES: Dict[str, Dict[str, Any]] = {
    "vanguard": {
        "key": "vanguard",
        "name_key": "commander_class_vanguard",
        "desc_key": "commander_class_vanguard_desc",
        "tagline_key": "commander_class_vanguard_tag",
        "officer_key": "commander_officer_vanguard",
        "title_key": "commander_title_vanguard",
        "epithet_key": "commander_epithet_vanguard",
        "portrait": "img/classes/Vanguard.webp",
        "theme": "vanguard",
        "playstyle": "combat",
        "icons": ("weapon", "armor", "shield", "raid"),
    },
    "forge_lord": {
        "key": "forge_lord",
        "name_key": "commander_class_forge_lord",
        "desc_key": "commander_class_forge_lord_desc",
        "tagline_key": "commander_class_forge_lord_tag",
        "officer_key": "commander_officer_forge_lord",
        "title_key": "commander_title_forge_lord",
        "epithet_key": "commander_epithet_forge_lord",
        "portrait": "img/classes/Forge_Lord.webp",
        "theme": "forge",
        "playstyle": "economy",
        "icons": ("production", "build", "storage", "industry"),
    },
    "archivist": {
        "key": "archivist",
        "name_key": "commander_class_archivist",
        "desc_key": "commander_class_archivist_desc",
        "tagline_key": "commander_class_archivist_tag",
        "officer_key": "commander_officer_archivist",
        "title_key": "commander_title_archivist",
        "epithet_key": "commander_epithet_archivist",
        "portrait": "img/classes/Archivist.webp",
        "theme": "archivist",
        "playstyle": "research",
        "icons": ("research", "codex", "data", "lab"),
    },
    "void_admiral": {
        "key": "void_admiral",
        "name_key": "commander_class_void_admiral",
        "desc_key": "commander_class_void_admiral_desc",
        "tagline_key": "commander_class_void_admiral_tag",
        "officer_key": "commander_officer_void_admiral",
        "title_key": "commander_title_void_admiral",
        "epithet_key": "commander_epithet_void_admiral",
        "portrait": "img/classes/Void_Admiral.webp",
        "theme": "admiral",
        "playstyle": "fleet",
        "icons": ("fleet", "cargo", "fuel", "shipyard"),
    },
    "envoy": {
        "key": "envoy",
        "name_key": "commander_class_envoy",
        "desc_key": "commander_class_envoy_desc",
        "tagline_key": "commander_class_envoy_tag",
        "officer_key": "commander_officer_envoy",
        "title_key": "commander_title_envoy",
        "epithet_key": "commander_epithet_envoy",
        "portrait": "img/classes/Envoy.webp",
        "theme": "envoy",
        "playstyle": "support",
        "icons": ("scan", "support", "shield", "signal"),
    },
}

# Score milestones → skill points (idempotent claims).
SP_MILESTONES: Tuple[Dict[str, Any], ...] = (
    {"key": "score_1k", "min_score": 1_000, "points": 1},
    {"key": "score_5k", "min_score": 5_000, "points": 1},
    {"key": "score_10k", "min_score": 10_000, "points": 1},
    {"key": "score_25k", "min_score": 25_000, "points": 2},
    {"key": "score_50k", "min_score": 50_000, "points": 2},
    {"key": "score_100k", "min_score": 100_000, "points": 3},
    {"key": "score_250k", "min_score": 250_000, "points": 3},
    {"key": "score_500k", "min_score": 500_000, "points": 4},
    {"key": "score_1m", "min_score": 1_000_000, "points": 5},
)

# Timekeeper swap cost by swap_count index (seconds). Beyond last → last value.
CLASS_SWAP_COST_SEC: Tuple[int, ...] = (
    24 * 3600,   # first swap: 24h
    72 * 3600,   # 72h
    168 * 3600,  # 7d
    336 * 3600,  # 14d
    720 * 3600,  # 30d
)

# Capstone costs — intentionally ruinous (late-empire scale).
_CAPSTONE_A = {"metal": 25_000_000, "crystal": 12_500_000, "fuel_cells": 5_000_000}
_CAPSTONE_B = {"metal": 120_000_000, "crystal": 60_000_000, "fuel_cells": 25_000_000}


def _skill(
    key: str,
    class_key: str,
    order: int,
    *,
    name_key: str,
    desc_key: str,
    icon_key: str,
    max_rank: int = 1,
    sp_cost: int = 1,
    prereq: Optional[str] = None,
    mods_per_rank: Optional[Dict[str, float]] = None,
    resource_cost: Optional[Dict[str, int]] = None,
    is_capstone: bool = False,
) -> Dict[str, Any]:
    return {
        "key": key,
        "class_key": class_key,
        "order": int(order),
        "name_key": name_key,
        "desc_key": desc_key,
        "icon_key": str(icon_key),
        "max_rank": int(max_rank),
        "sp_cost": int(sp_cost),
        "prereq_skill": prereq,
        "effect_mods_per_rank": dict(mods_per_rank or {}),
        "resource_cost": dict(resource_cost) if resource_cost else None,
        "is_capstone": bool(is_capstone),
    }


SKILLS: Dict[str, Dict[str, Any]] = {}


def _register(*skills: Dict[str, Any]) -> None:
    for s in skills:
        SKILLS[str(s["key"])] = s


# --- Vanguard (combat) ---
_register(
    _skill(
        "vanguard_strike_doctrine",
        "vanguard",
        1,
        name_key="commander_skill_vanguard_strike",
        desc_key="commander_skill_vanguard_strike_desc",
        icon_key="weapon",
        max_rank=3,
        mods_per_rank={"weapon_bonus": 0.02},
    ),
    _skill(
        "vanguard_hull_focus",
        "vanguard",
        2,
        name_key="commander_skill_vanguard_hull",
        desc_key="commander_skill_vanguard_hull_desc",
        icon_key="armor",
        max_rank=3,
        prereq="vanguard_strike_doctrine",
        mods_per_rank={"armor_bonus": 0.02},
    ),
    _skill(
        "vanguard_barrier",
        "vanguard",
        3,
        name_key="commander_skill_vanguard_barrier",
        desc_key="commander_skill_vanguard_barrier_desc",
        icon_key="shield",
        max_rank=3,
        prereq="vanguard_hull_focus",
        mods_per_rank={"shield_bonus": 0.02},
    ),
    _skill(
        "vanguard_assault_protocol",
        "vanguard",
        4,
        name_key="commander_skill_vanguard_assault",
        desc_key="commander_skill_vanguard_assault_desc",
        icon_key="raid",
        max_rank=2,
        sp_cost=2,
        prereq="vanguard_barrier",
        mods_per_rank={"weapon_bonus": 0.03, "armor_bonus": 0.01},
    ),
    _skill(
        "vanguard_apex_raider",
        "vanguard",
        5,
        name_key="commander_skill_vanguard_apex",
        desc_key="commander_skill_vanguard_apex_desc",
        icon_key="raid",
        max_rank=1,
        sp_cost=0,
        prereq="vanguard_assault_protocol",
        mods_per_rank={"weapon_bonus": 0.05, "armor_bonus": 0.05, "shield_bonus": 0.05},
        resource_cost=_CAPSTONE_A,
        is_capstone=True,
    ),
    _skill(
        "vanguard_war_sovereign",
        "vanguard",
        6,
        name_key="commander_skill_vanguard_sovereign",
        desc_key="commander_skill_vanguard_sovereign_desc",
        icon_key="weapon",
        max_rank=1,
        sp_cost=0,
        prereq="vanguard_apex_raider",
        mods_per_rank={"weapon_bonus": 0.04, "armor_bonus": 0.04, "shield_bonus": 0.04},
        resource_cost=_CAPSTONE_B,
        is_capstone=True,
    ),
)

# --- Forge Lord (economy) ---
_register(
    _skill(
        "forge_extraction",
        "forge_lord",
        1,
        name_key="commander_skill_forge_extraction",
        desc_key="commander_skill_forge_extraction_desc",
        icon_key="production",
        max_rank=3,
        mods_per_rank={
            "metal_prod_factor": 1.02,
            "crystal_prod_factor": 1.02,
            "fuel_prod_factor": 1.02,
        },
    ),
    _skill(
        "forge_nanoforge",
        "forge_lord",
        2,
        name_key="commander_skill_forge_nanoforge",
        desc_key="commander_skill_forge_nanoforge_desc",
        icon_key="build",
        max_rank=3,
        prereq="forge_extraction",
        mods_per_rank={"build_time_speed": 1.03},
    ),
    _skill(
        "forge_vaults",
        "forge_lord",
        3,
        name_key="commander_skill_forge_vaults",
        desc_key="commander_skill_forge_vaults_desc",
        icon_key="storage",
        max_rank=3,
        prereq="forge_nanoforge",
        mods_per_rank={"storage_factor": 1.03},
    ),
    _skill(
        "forge_industrial_surge",
        "forge_lord",
        4,
        name_key="commander_skill_forge_surge",
        desc_key="commander_skill_forge_surge_desc",
        icon_key="industry",
        max_rank=2,
        sp_cost=2,
        prereq="forge_vaults",
        mods_per_rank={
            "metal_prod_factor": 1.03,
            "crystal_prod_factor": 1.03,
            "fuel_prod_factor": 1.03,
            "build_time_speed": 1.02,
        },
    ),
    _skill(
        "forge_planetforge",
        "forge_lord",
        5,
        name_key="commander_skill_forge_planetforge",
        desc_key="commander_skill_forge_planetforge_desc",
        icon_key="industry",
        max_rank=1,
        sp_cost=0,
        prereq="forge_industrial_surge",
        mods_per_rank={
            "metal_prod_factor": 1.05,
            "crystal_prod_factor": 1.05,
            "fuel_prod_factor": 1.05,
            "storage_factor": 1.05,
        },
        resource_cost=_CAPSTONE_A,
        is_capstone=True,
    ),
    _skill(
        "forge_omniforge",
        "forge_lord",
        6,
        name_key="commander_skill_forge_omniforge",
        desc_key="commander_skill_forge_omniforge_desc",
        icon_key="production",
        max_rank=1,
        sp_cost=0,
        prereq="forge_planetforge",
        mods_per_rank={
            "metal_prod_factor": 1.04,
            "crystal_prod_factor": 1.04,
            "fuel_prod_factor": 1.04,
            "build_time_speed": 1.05,
        },
        resource_cost=_CAPSTONE_B,
        is_capstone=True,
    ),
)

# --- Archivist (research) ---
_register(
    _skill(
        "archivist_codex",
        "archivist",
        1,
        name_key="commander_skill_archivist_codex",
        desc_key="commander_skill_archivist_codex_desc",
        icon_key="codex",
        max_rank=3,
        mods_per_rank={"research_time_speed": 1.03},
    ),
    _skill(
        "archivist_lab_network",
        "archivist",
        2,
        name_key="commander_skill_archivist_lab",
        desc_key="commander_skill_archivist_lab_desc",
        icon_key="lab",
        max_rank=3,
        prereq="archivist_codex",
        mods_per_rank={"research_time_speed": 1.03},
    ),
    _skill(
        "archivist_deep_archive",
        "archivist",
        3,
        name_key="commander_skill_archivist_archive",
        desc_key="commander_skill_archivist_archive_desc",
        icon_key="data",
        max_rank=3,
        prereq="archivist_lab_network",
        mods_per_rank={"research_time_speed": 1.02, "crystal_prod_factor": 1.01},
    ),
    _skill(
        "archivist_synthesis",
        "archivist",
        4,
        name_key="commander_skill_archivist_synthesis",
        desc_key="commander_skill_archivist_synthesis_desc",
        icon_key="research",
        max_rank=2,
        sp_cost=2,
        prereq="archivist_deep_archive",
        mods_per_rank={"research_time_speed": 1.04},
    ),
    _skill(
        "archivist_omniscience",
        "archivist",
        5,
        name_key="commander_skill_archivist_omniscience",
        desc_key="commander_skill_archivist_omniscience_desc",
        icon_key="research",
        max_rank=1,
        sp_cost=0,
        prereq="archivist_synthesis",
        mods_per_rank={"research_time_speed": 1.06},
        resource_cost=_CAPSTONE_A,
        is_capstone=True,
    ),
    _skill(
        "archivist_prime_axiom",
        "archivist",
        6,
        name_key="commander_skill_archivist_axiom",
        desc_key="commander_skill_archivist_axiom_desc",
        icon_key="codex",
        max_rank=1,
        sp_cost=0,
        prereq="archivist_omniscience",
        mods_per_rank={"research_time_speed": 1.05, "build_time_speed": 1.02},
        resource_cost=_CAPSTONE_B,
        is_capstone=True,
    ),
)

# --- Void Admiral (fleet) ---
_register(
    _skill(
        "admiral_warp_lanes",
        "void_admiral",
        1,
        name_key="commander_skill_admiral_warp",
        desc_key="commander_skill_admiral_warp_desc",
        icon_key="fleet",
        max_rank=3,
        mods_per_rank={"fleet_speed_multiplier": 1.03},
    ),
    _skill(
        "admiral_hold_capacity",
        "void_admiral",
        2,
        name_key="commander_skill_admiral_hold",
        desc_key="commander_skill_admiral_hold_desc",
        icon_key="cargo",
        max_rank=3,
        prereq="admiral_warp_lanes",
        mods_per_rank={"cargo_multiplier": 1.03},
    ),
    _skill(
        "admiral_fuel_thrift",
        "void_admiral",
        3,
        name_key="commander_skill_admiral_fuel",
        desc_key="commander_skill_admiral_fuel_desc",
        icon_key="fuel",
        max_rank=3,
        prereq="admiral_hold_capacity",
        mods_per_rank={"fuel_efficiency_factor": 1.03},
    ),
    _skill(
        "admiral_dockyard",
        "void_admiral",
        4,
        name_key="commander_skill_admiral_dockyard",
        desc_key="commander_skill_admiral_dockyard_desc",
        icon_key="shipyard",
        max_rank=2,
        sp_cost=2,
        prereq="admiral_fuel_thrift",
        mods_per_rank={"shipyard_time_speed": 1.04},
    ),
    _skill(
        "admiral_armada",
        "void_admiral",
        5,
        name_key="commander_skill_admiral_armada",
        desc_key="commander_skill_admiral_armada_desc",
        icon_key="fleet",
        max_rank=1,
        sp_cost=0,
        prereq="admiral_dockyard",
        mods_per_rank={
            "fleet_speed_multiplier": 1.05,
            "cargo_multiplier": 1.05,
            "shipyard_time_speed": 1.05,
        },
        resource_cost=_CAPSTONE_A,
        is_capstone=True,
    ),
    _skill(
        "admiral_void_crown",
        "void_admiral",
        6,
        name_key="commander_skill_admiral_crown",
        desc_key="commander_skill_admiral_crown_desc",
        icon_key="shipyard",
        max_rank=1,
        sp_cost=0,
        prereq="admiral_armada",
        mods_per_rank={
            "fleet_speed_multiplier": 1.04,
            "fuel_efficiency_factor": 1.05,
            "shipyard_time_speed": 1.05,
        },
        resource_cost=_CAPSTONE_B,
        is_capstone=True,
    ),
)

# --- Envoy (support / intel) ---
_register(
    _skill(
        "envoy_signal_net",
        "envoy",
        1,
        name_key="commander_skill_envoy_signal",
        desc_key="commander_skill_envoy_signal_desc",
        icon_key="signal",
        max_rank=3,
        mods_per_rank={"scan_range": 1.0},
    ),
    _skill(
        "envoy_logistics_aid",
        "envoy",
        2,
        name_key="commander_skill_envoy_logistics",
        desc_key="commander_skill_envoy_logistics_desc",
        icon_key="support",
        max_rank=3,
        prereq="envoy_signal_net",
        mods_per_rank={"cargo_multiplier": 1.02, "fuel_efficiency_factor": 1.02},
    ),
    _skill(
        "envoy_shield_doctrine",
        "envoy",
        3,
        name_key="commander_skill_envoy_shield",
        desc_key="commander_skill_envoy_shield_desc",
        icon_key="shield",
        max_rank=3,
        prereq="envoy_logistics_aid",
        mods_per_rank={"shield_bonus": 0.02, "armor_bonus": 0.01},
    ),
    _skill(
        "envoy_rapid_response",
        "envoy",
        4,
        name_key="commander_skill_envoy_response",
        desc_key="commander_skill_envoy_response_desc",
        icon_key="support",
        max_rank=2,
        sp_cost=2,
        prereq="envoy_shield_doctrine",
        mods_per_rank={"build_time_speed": 1.02, "defense_time_speed": 1.03},
    ),
    _skill(
        "envoy_grand_mandate",
        "envoy",
        5,
        name_key="commander_skill_envoy_mandate",
        desc_key="commander_skill_envoy_mandate_desc",
        icon_key="scan",
        max_rank=1,
        sp_cost=0,
        prereq="envoy_rapid_response",
        mods_per_rank={
            "scan_range": 2.0,
            "shield_bonus": 0.03,
            "cargo_multiplier": 1.03,
        },
        resource_cost=_CAPSTONE_A,
        is_capstone=True,
    ),
    _skill(
        "envoy_galactic_voice",
        "envoy",
        6,
        name_key="commander_skill_envoy_voice",
        desc_key="commander_skill_envoy_voice_desc",
        icon_key="signal",
        max_rank=1,
        sp_cost=0,
        prereq="envoy_grand_mandate",
        mods_per_rank={
            "scan_range": 2.0,
            "research_time_speed": 1.02,
            "defense_time_speed": 1.05,
            "armor_bonus": 0.03,
        },
        resource_cost=_CAPSTONE_B,
        is_capstone=True,
    ),
)

# Additive combat / scan keys vs multiplicative factor keys
ADDITIVE_MOD_KEYS = frozenset(
    {"weapon_bonus", "armor_bonus", "shield_bonus", "scan_range"}
)

# Role icons — assets: static/img/classes/icons/{key}.webp (RGBA; JPG/GIF via process script)
ROLE_ICON_KEYS: Tuple[str, ...] = (
    "weapon",
    "armor",
    "shield",
    "raid",
    "production",
    "build",
    "storage",
    "industry",
    "research",
    "codex",
    "data",
    "lab",
    "fleet",
    "cargo",
    "fuel",
    "shipyard",
    "scan",
    "support",
    "signal",
)

# preview_mods key → chip label i18n (display only; values from class_preview_mods)
PREVIEW_CHIP_META: Dict[str, Dict[str, str]] = {
    "weapon_bonus": {"label_key": "commander_chip_weapon", "kind": "additive"},
    "armor_bonus": {"label_key": "commander_chip_armor", "kind": "additive"},
    "shield_bonus": {"label_key": "commander_chip_shield", "kind": "additive"},
    "metal_prod_factor": {"label_key": "commander_chip_metal", "kind": "mult"},
    "crystal_prod_factor": {"label_key": "commander_chip_crystal", "kind": "mult"},
    "fuel_prod_factor": {"label_key": "commander_chip_fuel_prod", "kind": "mult"},
    "build_time_speed": {"label_key": "commander_chip_build", "kind": "mult"},
    "research_time_speed": {"label_key": "commander_chip_research", "kind": "mult"},
    "storage_factor": {"label_key": "commander_chip_storage", "kind": "mult"},
    "fleet_speed_multiplier": {"label_key": "commander_chip_fleet", "kind": "mult"},
    "cargo_multiplier": {"label_key": "commander_chip_cargo", "kind": "mult"},
    "fuel_efficiency_factor": {"label_key": "commander_chip_fuel_eff", "kind": "mult"},
    "shipyard_time_speed": {"label_key": "commander_chip_shipyard", "kind": "mult"},
    "defense_time_speed": {"label_key": "commander_chip_defense", "kind": "mult"},
    "scan_range": {"label_key": "commander_chip_scan", "kind": "additive"},
}


def preview_chips_for_class(class_key: str, *, limit: int = 3) -> List[Dict[str, Any]]:
    """Top preview chips for UI (server-authored labels + display strings)."""
    mods = class_preview_mods(class_key)
    chips: List[Dict[str, Any]] = []
    for key, meta in PREVIEW_CHIP_META.items():
        if key not in mods:
            continue
        raw = float(mods[key])
        kind = meta["kind"]
        if kind == "additive":
            if abs(raw) < 0.001:
                continue
            pct = int(round(raw * 100))
            display = f"+{pct}%" if pct >= 0 else f"{pct}%"
            if key == "scan_range":
                display = f"+{int(round(raw))}"
        else:
            if abs(raw - 1.0) < 0.001:
                continue
            pct = int(round((raw - 1.0) * 100))
            display = f"+{pct}%" if pct >= 0 else f"{pct}%"
        chips.append(
            {
                "key": key,
                "label_key": meta["label_key"],
                "display": display,
            }
        )
        if len(chips) >= int(limit):
            break
    return chips


def role_icon_path(icon_key: str) -> str:
    return f"img/classes/icons/{icon_key}.webp"


def skill_image_path(skill_key: str) -> str:
    """Trunk node art — unique per skill (not role icons)."""
    return f"img/classes/skills/{skill_key}.webp"


def is_valid_class(class_key: str) -> bool:
    return str(class_key or "") in CLASSES


def get_class(class_key: str) -> Optional[Dict[str, Any]]:
    return CLASSES.get(str(class_key or ""))


def get_skill(skill_key: str) -> Optional[Dict[str, Any]]:
    return SKILLS.get(str(skill_key or ""))


def skills_for_class(class_key: str) -> List[Dict[str, Any]]:
    ck = str(class_key or "")
    rows = [s for s in SKILLS.values() if s["class_key"] == ck]
    rows.sort(key=lambda s: int(s["order"]))
    return rows


def trunk_skill_keys(class_key: str) -> List[str]:
    return [str(s["key"]) for s in skills_for_class(class_key)]


def swap_cost_sec(swap_count: int) -> int:
    idx = max(0, int(swap_count or 0))
    if idx >= len(CLASS_SWAP_COST_SEC):
        return int(CLASS_SWAP_COST_SEC[-1])
    return int(CLASS_SWAP_COST_SEC[idx])


def class_preview_mods(class_key: str) -> Dict[str, float]:
    """Maxed trunk preview for UI (server-authoritative display only)."""
    out: Dict[str, float] = {}
    for skill in skills_for_class(class_key):
        per = skill.get("effect_mods_per_rank") or {}
        ranks = int(skill.get("max_rank") or 1)
        for k, raw in per.items():
            key = str(k)
            val = float(raw)
            if key in ADDITIVE_MOD_KEYS:
                out[key] = float(out.get(key, 0.0)) + val * ranks
            else:
                base = float(out.get(key, 1.0))
                out[key] = base * (val ** ranks)
    return out
