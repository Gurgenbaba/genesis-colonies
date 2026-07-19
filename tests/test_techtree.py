"""
Tech-Tree page context tests (GC-555).

Run: python -m pytest tests/test_techtree.py -v
"""

from __future__ import annotations

import uuid

import pytest

from game.buildings import BUILDING_ORDER
from game.defense_defs import DEFENSE_ORDER
from game.fleet_defs import ACTIVE_SHIP_KEYS, SHIPS
from game.models import create_user, init_db
from game.research import RESEARCH_TECHS
from game.techtree import (
    RESEARCH_PREPARED_EFFECT_KEYS,
    get_techtree_data,
    get_techtree_page_context,
)


@pytest.fixture()
def techtree_db(tmp_path, monkeypatch):
    db_path = tmp_path / "techtree_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")

    from game import db as gdb

    gdb._DB_PATH = None
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_path


def _create_player() -> int:
    uname = f"tt_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def test_page_context_contains_all_sections(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    section_keys = [s["key"] for s in ctx["sections"]]
    assert section_keys == [
        "research",
        "ships",
        "buildings",
        "defense",
        "planet_evolution",
    ]


def test_building_and_research_counts(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    by_key = {s["key"]: s for s in ctx["sections"]}

    assert len(by_key["buildings"]["nodes"]) == len(BUILDING_ORDER)
    assert len(by_key["research"]["nodes"]) == len(RESEARCH_TECHS)
    assert len(by_key["ships"]["nodes"]) >= len(ACTIVE_SHIP_KEYS)


def test_active_ships_present(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    ship_section = next(s for s in ctx["sections"] if s["key"] == "ships")
    ship_keys = {item["key"] for item in ship_section["nodes"]}
    for key in ACTIVE_SHIP_KEYS:
        assert key in ship_keys


def test_eclipse_runner_active_hybrid(techtree_db):
    """GC-SHIP-1: Voidrunner is now an active expedition+combat hybrid, no longer phase2-only."""
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    ship_section = next(s for s in ctx["sections"] if s["key"] == "ships")
    eclipse = next((i for i in ship_section["nodes"] if i["key"] == "eclipse_runner"), None)
    assert eclipse is not None
    assert SHIPS["eclipse_runner"].get("phase2_only") is None
    assert eclipse["key"] in ACTIVE_SHIP_KEYS
    assert eclipse["role_label_key"] == "techtree_role_expedition_combat"


def test_defense_units_listed(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    defense_section = next(s for s in ctx["sections"] if s["key"] == "defense")
    assert len(defense_section["nodes"]) == len(DEFENSE_ORDER)


def test_requirements_have_label_keys_not_raw_only(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    research_section = next(s for s in ctx["sections"] if s["key"] == "research")
    engine = next(i for i in research_section["nodes"] if i["key"] == "engine_tech")
    assert engine["requirements"]
    for req in engine["requirements"]:
        assert req.get("label_key")
        assert req.get("kind") in ("building", "research", "planet_level")


def test_prepared_research_flagged(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    research_section = next(s for s in ctx["sections"] if s["key"] == "research")
    by_key = {i["key"]: i for i in research_section["nodes"]}
    for key in RESEARCH_PREPARED_EFFECT_KEYS:
        assert by_key[key]["effect_status"] == "prepared"
    assert by_key["energy_tech"]["effect_status"] == "active"


def test_legacy_get_techtree_data_tuple(techtree_db):
    player_id = _create_player()
    building_nodes, research_nodes = get_techtree_data(user_id=player_id)
    assert len(building_nodes) == len(BUILDING_ORDER)
    assert len(research_nodes) == len(RESEARCH_TECHS)


def test_planet_evolution_tracks(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    pe_section = next(s for s in ctx["sections"] if s["key"] == "planet_evolution")
    track_keys = {item["key"] for item in pe_section["nodes"]}
    assert "planet_dna" in track_keys
    assert "ascension" in track_keys
    assert "specialization" in track_keys


def test_planet_evolution_tracks_use_evo_png_icons(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    pe_section = next(s for s in ctx["sections"] if s["key"] == "planet_evolution")
    by_key = {item["key"]: item for item in pe_section["nodes"]}
    assert by_key["planet_dna"]["icon"] == "img/evo/dna.png"
    assert by_key["planet_level"]["icon"] == "img/evo/planetary.png"
    assert by_key["traits"]["icon"] == "img/evo/trait.png"
    assert by_key["specialization"]["icon"] == "img/evo/specialization.png"
    assert by_key["policies"]["icon"] == "img/evo/policy.png"
    assert by_key["planet_research"]["icon"] == "img/evo/planet_research_institute.png"
    assert by_key["ascension"]["icon"] == "img/evo/ascension_monument.png"


def test_section_progress_fields(techtree_db):
    player_id = _create_player()
    ctx = get_techtree_page_context(user_id=player_id)
    for section in ctx["sections"]:
        assert "progress_unlocked" in section
        assert "progress_total" in section
        assert section["progress_total"] == len(section["nodes"])


def test_build_time_nodes_have_description_and_effect_preview(techtree_db):
    from game.effects import EffectResolver
    from game.models import save_planet_buildings, get_homeworld

    player_id = _create_player()
    planet_id = int(get_homeworld(player_id=player_id)["id"])
    save_planet_buildings(
        planet_id,
        {
            "command_center": 2,
            "nanofactory": 3,
            "research_lab": 5,
            "solar_plant": 1,
        },
    )

    ctx = get_techtree_page_context(user_id=player_id)
    buildings_section = next(s for s in ctx["sections"] if s["key"] == "buildings")
    research_section = next(s for s in ctx["sections"] if s["key"] == "research")
    by_building = {item["key"]: item for item in buildings_section["nodes"]}
    by_research = {item["key"]: item for item in research_section["nodes"]}

    for key in ("command_center", "nanofactory"):
        item = by_building[key]
        assert item.get("description_key") == f"desc_{key}"
        preview = item.get("effect_preview") or {}
        assert preview.get("effect_kind") == "bonus_percent"
        assert int(preview.get("effect_value") or 0) >= 0

    from game.buildings import command_center_nanofactory_build_bonus_pct

    cc = by_building["command_center"]
    # GC-863 UI: flat ×15 % per CC level (runtime for nano upgrades remains 0.75^cc).
    assert cc["effect_preview"]["effect_value"] == command_center_nanofactory_build_bonus_pct(2)

    nano = by_building["nanofactory"]
    # GC-NANO-001: speed bonus % from 1 + 0.55 × level^0.8 (not flat ×30).
    assert nano["effect_preview"]["effect_value"] == EffectResolver.nanofactory_build_speed_bonus_pct(3)

    buildtime = by_research["buildtime_tech"]
    assert buildtime.get("description_key") == "desc_buildtime_tech"
    bt_preview = buildtime.get("effect_preview") or {}
    assert bt_preview.get("effect_value") == EffectResolver.buildtime_speed_bonus_pct(1)

    ctx_leveled = get_techtree_page_context(user_id=player_id)
    from game.models import save_research_level

    save_research_level("buildtime_tech", 5, player_id)
    ctx_leveled = get_techtree_page_context(user_id=player_id)
    research_nodes = next(s for s in ctx_leveled["sections"] if s["key"] == "research")["nodes"]
    bt5 = next(i for i in research_nodes if i["key"] == "buildtime_tech")
    assert (bt5.get("effect_preview") or {}).get("effect_value") == EffectResolver.buildtime_speed_bonus_pct(5)
