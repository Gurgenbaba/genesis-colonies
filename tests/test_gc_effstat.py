"""GC-EFFSTAT — effective stat display payloads (server authority)."""

from __future__ import annotations

import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import (
    create_user,
    ensure_player_and_homeworld,
    get_homeworld,
    get_planet_buildings,
    get_research_levels,
    init_db,
)
from game.ship_detail import build_ship_detail_card
from game.technical_data import (
    apply_combat_stats_to_catalog_entry,
    build_effective_stat,
    build_mobility_effective_stats,
    build_unit_technical_block,
    resolve_unit_effect_context,
)


@pytest.fixture
def effstat_db(tmp_path, monkeypatch):
    db_file = tmp_path / "effstat.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    import migrate

    migrate.main()
    uname = f"eff_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return uid


def test_build_effective_stat_multiplier_net_pct():
    stat = build_effective_stat("speed", 10000, multiplier=1.18)
    assert stat["base"] == 10000
    assert stat["effective"] == 11800
    assert stat["bonus_pct"] == 18
    assert stat["bonus_display"] == "+18 %"


def test_build_effective_stat_additive_combat():
    stat = build_effective_stat("attack", 100, additive_frac=0.15)
    assert stat["effective"] == 115
    assert stat["bonus_pct"] == 15


def test_build_effective_stat_zero_bonus_omits_nonzero_display_shape():
    stat = build_effective_stat("cargo", 5000, multiplier=1.0)
    assert stat["effective"] == 5000
    assert stat["bonus_pct"] == 0


def test_build_effective_stat_fuel_reduction():
    stat = build_effective_stat("fuel", 100, multiplier=0.91)
    assert stat["effective"] == 91
    assert stat["bonus_pct"] == -9
    assert stat["bonus_display"] == "-9 %"


def test_unit_technical_block_includes_combat_stat_payloads():
    technical = build_unit_technical_block(
        base_attack=100,
        base_shield=50,
        base_hull=200,
        base_build_seconds=60,
        production={"cycle_seconds": 54, "yard_batch_capacity": 9},
        buildings={"orbital_shipyard": 2},
        research_levels={"weapon_tech": 4, "shield_tech": 2, "armor_tech": 3},
        next_yard_unit_seconds=48,
        base_speed=10000,
        base_cargo=5000,
        base_fuel=100,
    )
    assert technical["combat"]["attack_stat"]["effective"] == technical["combat"]["attack"]
    assert technical["combat"]["attack_stat"]["bonus_pct"] > 0
    assert technical["mobility"]["speed"]["base"] == 10000
    assert technical["mobility"]["cargo"]["effective"] >= 5000
    assert technical["active_bonuses"]


def test_ship_detail_applies_mobility_and_combat(effstat_db):
    uid = effstat_db
    planet = get_homeworld(player_id=uid)
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, 'weapon_tech', 4);",
            (uid,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, 'engine_tech', 5);",
            (uid,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, 'navigation_tech', 3);",
            (uid,),
        )
        conn.commit()
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        research = get_research_levels(user_id=uid, conn=conn)
        card, err = build_ship_detail_card(
            "falcon_interceptor",
            buildings=buildings,
            research=research,
            player_id=uid,
            conn=conn,
            planet=planet,
        )
    finally:
        conn.close()

    assert err is None
    assert card is not None
    assert card["speed_stat"]["effective"] == card["speed"]
    assert card["speed_stat"]["bonus_pct"] > 0
    assert card["technical"]["combat"]["attack_stat"]["base"] > 0
    assert card["technical"]["combat"]["attack_stat"]["bonus_pct"] > 0
    assert card["technical"]["combat"]["attack_stat"]["effective"] == card["technical"]["combat"]["attack"]


def test_catalog_entry_gets_effective_combat(effstat_db):
    uid = effstat_db
    planet = get_homeworld(player_id=uid)
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, 'weapon_tech', 2);",
            (uid,),
        )
        conn.commit()
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        research = get_research_levels(user_id=uid, conn=conn)
        ctx = resolve_unit_effect_context(
            buildings=buildings,
            research_levels=research,
            player_id=uid,
            conn=conn,
            planet=planet,
        )
        entry = {"attack": 100, "shield": 40, "hull": 80}
        apply_combat_stats_to_catalog_entry(entry, effect_ctx=ctx)
    finally:
        conn.close()

    assert entry["attack"] > 100
    assert entry["attack_stat"]["bonus_pct"] == 10
    assert entry["attack_stat"]["effective"] == entry["attack"]


def test_mobility_helpers_match_multipliers():
    ctx = {
        "fleet_speed_multiplier": 1.1,
        "cargo_multiplier": 1.2,
        "fuel_efficiency_factor": 0.9,
        "resolver": None,
    }
    mob = build_mobility_effective_stats(
        base_speed=1000,
        base_cargo=2000,
        base_fuel=50,
        effect_ctx=ctx,
    )
    assert mob["speed"]["effective"] == 1100
    assert mob["cargo"]["effective"] == 2400
    assert mob["fuel"]["effective"] == 45
    assert mob["fuel"]["bonus_pct"] == -10


def test_templates_include_effective_stat_macro():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    macro = (root / "templates" / "partials" / "effective_stat.html").read_text(encoding="utf-8")
    shipyard = (root / "templates" / "shipyard.html").read_text(encoding="utf-8")
    fleet = (root / "templates" / "fleet.html").read_text(encoding="utf-8")
    assert "render_effective_stat_value" in macro
    assert "attack_stat" in shipyard
    assert "data-ship-tooltip-speed-bonus" in fleet
    assert "data-preview-cargo-bonus" in fleet
