"""Initiation / BiS locale coverage — no raw keys in any language pack."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
LANGS = ("de", "en", "es", "fr", "pl", "pt", "ru", "tr")

REQUIRED_KEYS = (
    "initiation_tabs_label",
    "initiation_tab_doctrine",
    "initiation_tab_build_order",
    "initiation_bo_title",
    "initiation_bo_hint",
    "initiation_bo_complete",
    "initiation_bo_truncated",
    "initiation_bo_empty",
    "initiation_bo_unavailable",
    "ini_bo_reason_energy",
    "ini_bo_reason_speed",
    "ini_bo_reason_cap",
    "ini_bo_reason_mine",
    "initiation_go_btn",
    "building_metal_mine",
    "building_crystal_mine",
    "building_solar_plant",
    "building_fuel_cell_plant",
    "building_research_lab",
    "building_command_center",
    "building_nanofactory",
    "building_geothermal_nexus",
    "building_planet_core_nexus",
    "building_metal_storage",
    "building_crystal_storage",
    "buildtime_tech",
    "energy_tech",
    "mining_tech",
    "storage_tech",
    "research_drones_tech",
    "research_engine_tech",
)


def _load(lang: str) -> dict:
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def test_initiation_bis_keys_present_in_all_locales():
    packs = {lang: _load(lang) for lang in LANGS}
    missing = []
    raw = []
    for key in REQUIRED_KEYS:
        for lang, data in packs.items():
            val = data.get(key)
            if val is None or not str(val).strip():
                missing.append(f"{lang}:{key}")
            elif str(val).strip() == key:
                raw.append(f"{lang}:{key}")
    assert not missing, f"Missing locale keys: {missing}"
    assert not raw, f"Raw locale keys (value==key): {raw}"
