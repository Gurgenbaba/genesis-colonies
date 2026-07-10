"""
GC-SCORE-E — planet evolution wealth score from invested resources.

Run: python -m pytest tests/test_gc_score_e_planet_evolution.py -v
"""

from __future__ import annotations

import pytest

from game.models import db, ensure_player_and_homeworld, create_user
from game.planet_evolution.ascension import ascension_cost_resources, ascension_invested_resource_totals
from game.planet_evolution.planet_research import (
    compute_planet_research_cost,
    cumulative_planet_research_resource_totals,
)
from game.planet_evolution.scoring import compute_player_evolution_score, compute_single_planet_score
from game.resource_score import add_score_from_cost_dicts, score_from_cost_dict


@pytest.fixture
def evo_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pe_score_e.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    from game import db as gdb

    gdb._DB_PATH = None
    from game.models import init_db

    init_db()
    import migrate

    migrate.main()
    conn = db()
    from game.planet_evolution.bootstrap import backfill_all_planets_evolution
    from game.planet_evolution.definitions import reload_definitions

    reload_definitions(conn)
    backfill_all_planets_evolution(conn)
    conn.commit()
    conn.close()
    yield
    gdb._DB_PATH = None


def test_cumulative_planet_research_totals_match_level_costs():
    metal = crystal = 0
    for level in range(1, 3):
        m, c = compute_planet_research_cost("industry_t1_automation", level)
        metal += m
        crystal += c
    assert metal == 800 + 1200
    assert crystal == 400 + 600


def test_planet_score_ignores_level_tier_without_resource_investment(evo_db):
    conn = db()
    ok, _, user = create_user("pe_score_zero", "test-pass-123")
    assert ok
    ensure_player_and_homeworld(int(user["id"]), player_name="Zero", conn=conn)
    planet = conn.execute(
        "SELECT id, planet_level, specialization_tier, ascension_rank FROM planets LIMIT 1;"
    ).fetchone()
    conn.execute(
        """
        UPDATE planets
        SET planet_level = 30, specialization_tier = 3, ascension_rank = 1
        WHERE id = ?;
        """,
        (int(planet["id"]),),
    )
    conn.commit()
    assert compute_single_planet_score(int(planet["id"]), conn) == 0
    conn.close()


def test_planet_score_from_planet_research_levels(evo_db):
    conn = db()
    ok, _, user = create_user("pe_score_research", "test-pass-123")
    assert ok
    ensure_player_and_homeworld(int(user["id"]), player_name="Researcher", conn=conn)
    planet = conn.execute("SELECT id FROM planets LIMIT 1;").fetchone()
    planet_id = int(planet["id"])
    conn.execute(
        """
        INSERT INTO planet_research_levels (planet_id, tech_key, level)
        VALUES (?, 'industry_t1_automation', 2)
        ON CONFLICT(planet_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (planet_id,),
    )
    conn.commit()

    totals = cumulative_planet_research_resource_totals(planet_id, conn=conn)
    expected_score = score_from_cost_dict(totals)
    assert expected_score == 2
    assert compute_single_planet_score(planet_id, conn) == expected_score
    conn.close()


def test_ascension_cost_resources_machine_ascension():
    cost = ascension_cost_resources("machine_ascension")
    assert cost == {"metal": 5_000_000, "crystal": 3_000_000, "fuel_cells": 0}
    assert score_from_cost_dict(cost) == 3333 + 3000


def test_planet_score_includes_completed_ascension(evo_db):
    conn = db()
    ok, _, user = create_user("pe_score_asc", "test-pass-123")
    assert ok
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Ascended", conn=conn)
    planet = conn.execute("SELECT id FROM planets WHERE player_id = ? LIMIT 1;", (uid,)).fetchone()
    planet_id = int(planet["id"])
    conn.execute(
        """
        UPDATE planets
        SET ascension_key = 'machine_ascension', ascension_rank = 1
        WHERE id = ?;
        """,
        (planet_id,),
    )
    conn.commit()

    ascension = ascension_invested_resource_totals(planet_id, conn)
    assert score_from_cost_dict(ascension) == 6333
    assert compute_single_planet_score(planet_id, conn) == 6333
    assert compute_player_evolution_score(uid, conn) == 6333
    conn.close()


def test_planet_score_sums_research_and_ascension(evo_db):
    conn = db()
    ok, _, user = create_user("pe_score_combo", "test-pass-123")
    assert ok
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Combo", conn=conn)
    planet = conn.execute("SELECT id FROM planets WHERE player_id = ? LIMIT 1;", (uid,)).fetchone()
    planet_id = int(planet["id"])
    conn.execute(
        """
        INSERT INTO planet_research_levels (planet_id, tech_key, level)
        VALUES (?, 'industry_t1_automation', 2)
        ON CONFLICT(planet_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (planet_id,),
    )
    conn.execute(
        """
        UPDATE planets
        SET ascension_key = 'machine_ascension', ascension_rank = 1
        WHERE id = ?;
        """,
        (planet_id,),
    )
    conn.commit()

    research = cumulative_planet_research_resource_totals(planet_id, conn=conn)
    ascension = ascension_invested_resource_totals(planet_id, conn)
    assert compute_single_planet_score(planet_id, conn) == add_score_from_cost_dicts(
        research, ascension
    )
    conn.close()
