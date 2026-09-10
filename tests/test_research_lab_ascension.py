"""GC-RESEARCH-NET-ASC-001 — Research Network Ascension contract."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from game.research_lab_ascension import (
    MAX_ASCENSION_RANK,
    base_slots_for_lab_level,
    max_lab_level_for_rank,
    required_level_for_rank,
    research_queue_capacity,
    tribute_cost_for_rank,
)


def test_base_slot_boundaries():
    expected = {
        0: 2,
        29: 2,
        30: 3,
        39: 3,
        40: 4,
        49: 4,
        50: 5,
        100: 5,
        999: 5,
    }
    for level, slots in expected.items():
        assert base_slots_for_lab_level(level) == slots


def test_ascension_gates_and_caps():
    assert MAX_ASCENSION_RANK == 5
    assert [required_level_for_rank(r) for r in range(1, 6)] == [50, 60, 70, 80, 90]
    assert [max_lab_level_for_rank(r) for r in range(0, 6)] == [50, 60, 70, 80, 90, 100]


def test_tribute_uses_requested_crytite_heavy_weights():
    expected_metal_pct = {1: 40, 2: 35, 3: 30, 4: 25, 5: 20}
    for rank, metal_pct in expected_metal_pct.items():
        metal, crystal = tribute_cost_for_rank(rank)
        total = metal + crystal
        assert total > 0
        # Integer rounding may differ by at most one resource unit.
        assert abs(metal * 100 - total * metal_pct) <= 100
        assert crystal == total - metal


def _capacity_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE planets (
            id INTEGER PRIMARY KEY,
            player_id INTEGER NOT NULL,
            galaxy INTEGER DEFAULT 1
        );
        CREATE TABLE planet_buildings (
            planet_id INTEGER PRIMARY KEY,
            research_lab INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE research_lab_ascension (
            planet_id INTEGER PRIMARY KEY,
            rank INTEGER NOT NULL DEFAULT 0,
            ascended_at INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    return conn


def test_strongest_single_lab_wins_and_ranks_do_not_sum():
    conn = _capacity_conn()
    try:
        conn.executemany(
            "INSERT INTO planets(id, player_id, galaxy) VALUES (?, 7, 1)",
            [(1,), (2,), (3,)],
        )
        conn.executemany(
            "INSERT INTO planet_buildings(planet_id, research_lab) VALUES (?, ?)",
            [(1, 70), (2, 60), (3, 50)],
        )
        conn.executemany(
            "INSERT INTO research_lab_ascension(planet_id, rank) VALUES (?, ?)",
            [(1, 3), (2, 2), (3, 1)],
        )
        cap = research_queue_capacity(
            7,
            conn=conn,
            settings={"research_queue_limit": 2},
            include_external_bonus=False,
        )
        assert cap["best_planet_id"] == 1
        assert cap["lab_level"] == 70
        assert cap["ascension_rank"] == 3
        assert cap["base"] == 5
        assert cap["prestige_limit"] == 8
        assert cap["limit"] == 8
        assert cap["research_speed_bonus_pct"] == 6
    finally:
        conn.close()


def test_configured_limit_remains_compatibility_floor():
    conn = _capacity_conn()
    try:
        conn.execute("INSERT INTO planets(id, player_id, galaxy) VALUES (1, 8, 1)")
        conn.execute("INSERT INTO planet_buildings(planet_id, research_lab) VALUES (1, 30)")
        cap = research_queue_capacity(
            8,
            conn=conn,
            settings={"research_queue_limit": 6},
            include_external_bonus=False,
        )
        assert cap["prestige_limit"] == 3
        assert cap["configured_limit"] == 6
        assert cap["limit"] == 6
    finally:
        conn.close()


def test_static_integration_contracts_are_present():
    root = Path(__file__).resolve().parents[1]
    research = (root / "game/research.py").read_text(encoding="utf-8")
    buildings = (root / "game/buildings.py").read_text(encoding="utf-8")
    effects = (root / "game/effects/effect_resolver.py").read_text(encoding="utf-8")
    app = (root / "app.py").read_text(encoding="utf-8")
    research_template = (root / "templates/research.html").read_text(encoding="utf-8")
    buildings_template = (root / "templates/buildings.html").read_text(encoding="utf-8")
    building_script = (root / "static/js/pages/research_lab_ascension.js").read_text(encoding="utf-8")

    assert "research_queue_capacity" in research
    assert 'building_type == "research_lab"' in buildings
    assert "max_lab_level_for_rank" in buildings
    assert "_research_lab_ascension_rank_cache" in effects
    assert '/api/research/ascend-lab' in app
    assert "data-research-network-ascend" not in research_template
    assert "js/pages/research_network.js" not in research_template
    assert "data-research-lab-ascend" in buildings_template
    assert "gc-research-lab-ascension-confirm-modal" in buildings_template
    assert "js/pages/research_lab_ascension.js" in buildings_template
    assert '/api/research/ascend-lab' in building_script
