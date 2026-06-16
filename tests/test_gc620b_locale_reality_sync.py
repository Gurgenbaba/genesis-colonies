"""GC-620B — Locale Reality Sync (no stale player-facing lies)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

GC620B_SYNCED_KEYS = (
    "fleet_mission_hint_attack",
    "logistics_tab_distribute_soon",
    "logistics_coming_soon",
    "defense_placeholder_note",
    "fleet_logistics_not_implemented",
    "fleet_error_logistics_not_implemented",
    "galaxy_colony_target_hint",
    "galaxy_colonize_soon_hint",
    "galaxy_legend_colonizable",
    "strategic_world_inspector_hint",
    "strategic_world_inspector_status_prepared",
    "strategic_world_inspector_wreckage_hint",
    "world_map_inspector_foreign_hint",
    "world_field_inspector_hint",
    "fleet_ship_harvest_reclaimer_desc",
    "fleet_ship_seed_ark_desc",
    "fleet_ship_eclipse_runner_desc",
)

STALE_PHRASES = (
    "not active yet",
    "nicht aktiv",
    "kampfsimulation noch nicht",
    "placeholder report",
    "platzhalterbericht",
    "coming in a later update",
    "folgt in einem späteren update",
    "colonization is not available yet",
    "noch nicht freigeschaltet",
    "not playable yet",
    "noch nicht spielbar",
    "coming soon",
    "combat simulation is not",
)


@pytest.fixture(params=("locales/de.json", "locales/en.json"))
def locale_data(request):
    path = ROOT / request.param
    return request.param, json.loads(path.read_text(encoding="utf-8"))


def test_gc620b_synced_keys_present(locale_data):
    rel_path, data = locale_data
    for key in GC620B_SYNCED_KEYS:
        assert key in data, f"missing {key} in {rel_path}"


def test_gc620b_no_stale_phrases_in_synced_keys(locale_data):
    rel_path, data = locale_data
    for key in GC620B_SYNCED_KEYS:
        value = str(data.get(key, "")).lower()
        for phrase in STALE_PHRASES:
            assert phrase not in value, f"{rel_path} {key} still contains stale phrase {phrase!r}: {data[key]!r}"


def test_gc620b_attack_hint_describes_combat(locale_data):
    _, data = locale_data
    text = data["fleet_mission_hint_attack"].lower()
    assert "kampf" in text or "combat" in text


def test_gc620b_foreign_hint_marks_dev_preview(locale_data):
    _, data = locale_data
    text = data["world_map_inspector_foreign_hint"].lower()
    assert "dev" in text
