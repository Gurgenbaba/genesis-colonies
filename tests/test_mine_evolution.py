"""
EPIC-29 / GC-2905 — Mine Ascension (no reset, Tribute@milestone).

Run: python -m pytest tests/test_mine_evolution.py -q
"""

from __future__ import annotations

import uuid

import pytest

from game.buildings import get_upgrade_cost
from game.mine_evolution import (
    TRIBUTE_LOOKBACK_LEVELS,
    UNCAPPED_BUILDING_LEVEL,
    building_modifier_from_rank,
    cumulative_production_bonus,
    evolve_mine,
    get_evolution_rank,
    required_level_for_evolution,
    roman_numeral,
    tribute_cost_for_next_rank,
)


def _fund_planet(planet_id: int, metal: int = 10**18, crystal: int = 10**18) -> None:
    from game.db import db

    conn = db()
    try:
        conn.execute(
            "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
            (int(metal), int(crystal), int(planet_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _expected_tribute(building_type: str, next_rank: int) -> tuple[int, int]:
    m_level = required_level_for_evolution(next_rank)
    metal_sum = crystal_sum = 0
    for target in range(m_level - TRIBUTE_LOOKBACK_LEVELS + 1, m_level + 1):
        m, c = get_upgrade_cost(building_type, target - 1)
        metal_sum += int(m)
        crystal_sum += int(c)
    return metal_sum // 4, crystal_sum // 4


@pytest.fixture
def mevo_db(tmp_path, monkeypatch):
    import game.db as dbmod
    import game.models as models
    from game.models import create_user, ensure_player_and_homeworld, init_db

    db_file = tmp_path / "mine_evo.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    import migrate

    migrate.main()
    uname = f"mevo_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


class TestMineEvolutionFormulas:
    def test_required_level_linear(self):
        assert required_level_for_evolution(1) == 200
        assert required_level_for_evolution(2) == 225
        assert required_level_for_evolution(3) == 250
        assert required_level_for_evolution(4) == 275
        assert required_level_for_evolution(5) == 300

    def test_required_level_keeps_rising(self):
        prev = required_level_for_evolution(5)
        for n in range(6, 20):
            cur = required_level_for_evolution(n)
            assert cur == prev + 25
            prev = cur

    def test_bonus_anchors(self):
        assert cumulative_production_bonus(0) == 0.0
        assert cumulative_production_bonus(1) == pytest.approx(0.1199, abs=0.0005)
        assert cumulative_production_bonus(2) == pytest.approx(0.1802, abs=0.0005)
        assert cumulative_production_bonus(3) == pytest.approx(0.2246, abs=0.0005)
        assert cumulative_production_bonus(5) == pytest.approx(0.2894, abs=0.0005)
        assert cumulative_production_bonus(10) == pytest.approx(0.3851, abs=0.0005)
        assert cumulative_production_bonus(20) == pytest.approx(0.4713, abs=0.0005)
        assert cumulative_production_bonus(1000) == pytest.approx(0.55, abs=0.01)
        d1 = cumulative_production_bonus(2) - cumulative_production_bonus(1)
        d10 = cumulative_production_bonus(11) - cumulative_production_bonus(10)
        assert d10 < d1

    def test_tribute_milestone_windows(self):
        t1 = tribute_cost_for_next_rank("metal_mine", 1)
        assert t1 == _expected_tribute("metal_mine", 1)
        assert t1[0] > 0 and t1[1] > 0
        t2 = tribute_cost_for_next_rank("metal_mine", 2)
        assert t2 == _expected_tribute("metal_mine", 2)
        assert t2[0] > t1[0]

    def test_building_modifier_and_roman(self):
        assert building_modifier_from_rank(0) == 1.0
        assert building_modifier_from_rank(1) == pytest.approx(1.0 + cumulative_production_bonus(1))
        assert roman_numeral(7) == "VII"
        assert roman_numeral(0) == ""


class TestMineEvolutionCaps:
    def test_mines_and_solar_share_nexus_cap_before_ascension(self):
        from game.effects.effect_resolver import EffectResolver

        buildings = {
            "metal_mine": 10,
            "crystal_mine": 10,
            "fuel_cell_plant": 10,
            "solar_plant": 10,
            "planet_core_nexus": 5,
            "geothermal_nexus": 3,
        }
        er = EffectResolver(buildings, {})
        producer_cap = 50 + 5 + 2 * 3
        assert er.get_max_building_level("metal_mine") == producer_cap
        assert er.get_max_building_level("crystal_mine") == producer_cap
        assert er.get_max_building_level("fuel_cell_plant") == producer_cap
        assert er.get_max_building_level("solar_plant") == producer_cap
        assert er.get_max_building_level("metal_storage") == 50 + 2 * 3
        assert er.get_max_building_level("research_lab") == 50

    def test_max_nexuses_unlock_level_200_before_rank_one(self):
        from game.effects.effect_resolver import EffectResolver

        buildings = {"planet_core_nexus": 50, "geothermal_nexus": 50}
        er = EffectResolver(buildings, {})
        for key in ("metal_mine", "crystal_mine", "fuel_cell_plant", "solar_plant"):
            assert er.get_max_building_level(key) == 200


class TestMineEvolutionAction:
    def test_ascend_keeps_level_and_spends_tribute(self, mevo_db):
        from game.db import db
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 200
        save_planet_buildings(pid, buildings)
        tribute_m, tribute_c = tribute_cost_for_next_rank("metal_mine", 1)
        _fund_planet(pid, metal=tribute_m + 1000, crystal=tribute_c + 1000)

        ok, reason, payload = evolve_mine(uid, dict(planet), "metal_mine")
        assert ok, reason
        assert payload["evolution_rank"] == 1
        assert payload["level"] == 200
        assert payload["tribute_metal"] == tribute_m
        assert payload["tribute_crystal"] == tribute_c
        assert get_evolution_rank(pid, "metal_mine") == 1
        assert int(get_planet_buildings(pid)["metal_mine"]) == 200

        conn = db()
        try:
            row = conn.execute(
                "SELECT metal, crystal FROM planets WHERE id = ?;", (pid,)
            ).fetchone()
            assert int(row["metal"]) == 1000
            assert int(row["crystal"]) == 1000
        finally:
            conn.close()

    def test_catchup_same_tribute_as_milestone(self, mevo_db):
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        tribute_m, tribute_c = tribute_cost_for_next_rank("metal_mine", 1)
        assert tribute_cost_for_next_rank("metal_mine", 1) == _expected_tribute("metal_mine", 1)

        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 285
        save_planet_buildings(pid, buildings)
        _fund_planet(pid)

        ok, reason, payload = evolve_mine(uid, dict(planet), "metal_mine")
        assert ok, reason
        assert payload["evolution_rank"] == 1
        assert payload["level"] == 285
        assert payload["tribute_metal"] == tribute_m
        assert payload["tribute_crystal"] == tribute_c

        # Sequential catch-up through IV; V blocked at L285.
        for expected_rank in (2, 3, 4):
            ok, reason, payload = evolve_mine(uid, dict(planet), "metal_mine")
            assert ok, reason
            assert payload["evolution_rank"] == expected_rank
            assert payload["level"] == 285

        ok, reason, payload = evolve_mine(uid, dict(planet), "metal_mine")
        assert not ok
        assert reason == "level_too_low"
        assert payload["required"] == 300
        assert get_evolution_rank(pid, "metal_mine") == 4
        assert int(get_planet_buildings(pid)["metal_mine"]) == 285

    def test_cannot_skip_ranks(self, mevo_db):
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 300
        save_planet_buildings(pid, buildings)
        _fund_planet(pid)

        ok, reason, payload = evolve_mine(uid, dict(planet), "metal_mine")
        assert ok, reason
        assert payload["evolution_rank"] == 1
        # Next request must still be II (cannot jump to V).
        ok, reason, payload = evolve_mine(uid, dict(planet), "metal_mine")
        assert ok, reason
        assert payload["evolution_rank"] == 2

    def test_insufficient_resources_atomic(self, mevo_db):
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 200
        save_planet_buildings(pid, buildings)
        _fund_planet(pid, metal=1, crystal=1)

        ok, reason, payload = evolve_mine(uid, dict(planet), "metal_mine")
        assert not ok
        assert reason == "insufficient_resources"
        assert get_evolution_rank(pid, "metal_mine") == 0
        assert int(get_planet_buildings(pid)["metal_mine"]) == 200
        assert payload["cost_metal"] == tribute_cost_for_next_rank("metal_mine", 1)[0]

    def test_evolve_rejects_below_threshold(self, mevo_db):
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 199
        save_planet_buildings(pid, buildings)
        _fund_planet(pid)

        ok, reason, payload = evolve_mine(uid, dict(planet), "metal_mine")
        assert not ok
        assert reason == "level_too_low"
        assert payload["required"] == 200

    def test_evolve_rejects_queue_pending(self, mevo_db):
        import time

        from game.models import (
            add_build_job,
            get_homeworld,
            get_planet_buildings,
            save_planet_buildings,
        )

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 200
        save_planet_buildings(pid, buildings)
        _fund_planet(pid)
        now = time.time()
        add_build_job(pid, "metal_mine", now, now + 3600)

        ok, reason, _ = evolve_mine(uid, dict(planet), "metal_mine")
        assert not ok
        assert reason == "queue_pending"

    def test_evolve_rejects_non_mine(self, mevo_db):
        from game.models import get_homeworld

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        ok, reason, _ = evolve_mine(uid, dict(planet), "solar_plant")
        assert not ok
        assert reason == "invalid_building"

    def test_second_evolution_needs_higher_level(self, mevo_db):
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["crystal_mine"] = 200
        save_planet_buildings(pid, buildings)
        _fund_planet(pid)
        ok, reason, _ = evolve_mine(uid, dict(planet), "crystal_mine")
        assert ok, reason
        assert int(get_planet_buildings(pid)["crystal_mine"]) == 200

        buildings = get_planet_buildings(pid)
        buildings["crystal_mine"] = 224
        save_planet_buildings(pid, buildings)
        ok, reason, payload = evolve_mine(uid, dict(planet), "crystal_mine")
        assert not ok
        assert reason == "level_too_low"
        assert payload["required"] == 225

        buildings["crystal_mine"] = 225
        save_planet_buildings(pid, buildings)
        ok, reason, payload = evolve_mine(uid, dict(planet), "crystal_mine")
        assert ok, reason
        assert payload["evolution_rank"] == 2
        assert payload["level"] == 225


    def test_build_queue_max_stops_at_next_ascension_gate(self, mevo_db, monkeypatch):
        import game.buildings as bmod
        from game.db import db
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 245
        save_planet_buildings(pid, buildings)

        conn = db()
        try:
            conn.execute(
                """
                INSERT INTO planet_mine_evolution (planet_id, building_type, evolution_rank, updated_at)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(planet_id, building_type) DO UPDATE SET evolution_rank = excluded.evolution_rank;
                """,
                (pid, "metal_mine", 2),
            )
            conn.commit()
        finally:
            conn.close()

        _fund_planet(pid, metal=1000, crystal=1000)
        monkeypatch.setattr(
            bmod, "_resolve_build_queue_limit", lambda settings=None, *, conn=None: 10
        )
        monkeypatch.setattr(bmod, "get_upgrade_cost", lambda *_args, **_kwargs: (1, 1))
        monkeypatch.setattr(
            bmod.BuildingsPanelContext,
            "build_time_seconds",
            lambda self, building_type, target_level: 3600,
        )

        buildings = get_planet_buildings(pid)
        ok, reason, payload = bmod.queue_build_for_planet(
            dict(planet), buildings, "metal_mine", user_id=uid, queue_mode="max"
        )
        assert ok and reason == "ok"
        assert int(payload["jobs_queued"]) == 5
        mine_rows = [
            r for r in bmod.get_build_queue_rows(pid) if str(r["building_type"]) == "metal_mine"
        ]
        assert len(mine_rows) == 5

        ok, reason, blocked = bmod.queue_build_for_planet(
            dict(planet), buildings, "metal_mine", user_id=uid, queue_mode="max"
        )
        assert not ok
        assert reason == "ascension_required"
        assert int(blocked["max_level"]) == 250
        assert int(blocked["evolution_rank"]) == 2
        assert int(blocked["next_evolution_rank"]) == 3

    def test_build_queue_max_uses_smaller_of_free_slots_and_ascension_headroom(self, mevo_db, monkeypatch):
        import time
        import game.buildings as bmod
        from game.db import db
        from game.models import add_build_job, get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 245
        save_planet_buildings(pid, buildings)

        conn = db()
        try:
            conn.execute(
                """
                INSERT INTO planet_mine_evolution (planet_id, building_type, evolution_rank, updated_at)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(planet_id, building_type) DO UPDATE SET evolution_rank = excluded.evolution_rank;
                """,
                (pid, "metal_mine", 2),
            )
            now = time.time()
            add_build_job(pid, "solar_plant", now + 10, now + 3610, conn=conn)
            add_build_job(pid, "crystal_storage", now + 3620, now + 7220, conn=conn)
            add_build_job(pid, "metal_storage", now + 7230, now + 10830, conn=conn)
            add_build_job(pid, "fuel_storage", now + 10840, now + 14440, conn=conn)
            add_build_job(pid, "research_lab", now + 14450, now + 18050, conn=conn)
            add_build_job(pid, "academy", now + 18060, now + 21660, conn=conn)
            conn.commit()
        finally:
            conn.close()

        _fund_planet(pid, metal=1000, crystal=1000)
        monkeypatch.setattr(
            bmod, "_resolve_build_queue_limit", lambda settings=None, *, conn=None: 10
        )
        monkeypatch.setattr(bmod, "get_upgrade_cost", lambda *_args, **_kwargs: (1, 1))
        monkeypatch.setattr(
            bmod.BuildingsPanelContext,
            "build_time_seconds",
            lambda self, building_type, target_level: 3600,
        )

        buildings = get_planet_buildings(pid)
        ok, reason, payload = bmod.queue_build_for_planet(
            dict(planet), buildings, "metal_mine", user_id=uid, queue_mode="max"
        )
        assert ok and reason == "ok"
        assert int(payload["jobs_queued"]) == 4
        assert len(bmod.get_build_queue_rows(pid)) == 10

    def test_queue_cap_helper_combines_nexus_phase_and_per_mine_rank(self):
        import game.buildings as bmod

        # Rank 0 follows the actual Nexus cap until the L200 Ascension gate.
        assert bmod._effective_building_queue_cap(
            "metal_mine", 137, planet_id=1, evolution_rank=0
        ) == 137
        assert bmod._effective_building_queue_cap(
            "metal_mine", 200, planet_id=1, evolution_rank=0
        ) == 200
        # Completed ranks extend this mine beyond the Nexus ceiling.
        assert bmod._effective_building_queue_cap(
            "metal_mine", 200, planet_id=1, evolution_rank=1
        ) == 225
        assert bmod._effective_building_queue_cap(
            "metal_mine", 200, planet_id=1, evolution_rank=2
        ) == 250
        assert bmod._effective_building_queue_cap(
            "metal_mine", 200, planet_id=1, evolution_rank=4
        ) == 300


class TestMineEvolutionProduction:
    def test_building_modifier_wired_and_isolated(self, mevo_db):
        from game.effects.effect_resolver import EffectResolver
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings
        from game.production_formula import (
            calculate_resource_output,
            production_context_from_resolver,
        )

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 200
        buildings["crystal_mine"] = 200
        save_planet_buildings(pid, buildings)
        _fund_planet(pid)
        ok, reason, _ = evolve_mine(uid, dict(planet), "metal_mine")
        assert ok, reason

        buildings = get_planet_buildings(pid)
        er = EffectResolver(
            buildings,
            {},
            player_id=uid,
            planet_id=pid,
            planet_position=int(planet.get("position") or 9),
        )
        ctx_metal = production_context_from_resolver(er, "metal", energy_ratio=1.0)
        ctx_crystal = production_context_from_resolver(er, "crystal", energy_ratio=1.0)
        ctx_fuel = production_context_from_resolver(er, "fuel_cells", energy_ratio=1.0)
        assert ctx_metal.building_modifier == pytest.approx(building_modifier_from_rank(1))
        assert ctx_crystal.building_modifier == pytest.approx(1.0)
        assert ctx_fuel.building_modifier == pytest.approx(1.0)

        out = calculate_resource_output("metal", ctx_metal)
        ctx0 = production_context_from_resolver(
            EffectResolver(
                buildings,
                {},
                player_id=uid,
                planet_id=None,
                planet_position=int(planet.get("position") or 9),
            ),
            "metal",
            energy_ratio=1.0,
        )
        out0 = calculate_resource_output("metal", ctx0)
        assert out > out0
        assert out / out0 == pytest.approx(ctx_metal.building_modifier, rel=1e-6)

    def test_planet_isolation(self, mevo_db):
        import time

        from game.db import db
        from game.effects.effect_resolver import EffectResolver
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings
        from game.production_formula import production_context_from_resolver
        from tests.conftest import unlock_colony_slots

        uid = mevo_db
        home = get_homeworld(player_id=uid)
        home_id = int(home["id"])

        conn = db()
        unlock_colony_slots(conn, home_id, slots=1)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planets (
                player_id, name, galaxy, system, position, is_homeworld, last_update
            )
            VALUES (?, 'Colony B', 1, 2, 5, 0, ?);
            """,
            (uid, float(time.time())),
        )
        colony_id = int(cur.lastrowid)
        conn.commit()
        conn.close()

        from game.models import get_planet_buildings as gpb

        gpb(home_id)
        gpb(colony_id)

        hb = get_planet_buildings(home_id)
        hb["metal_mine"] = 200
        save_planet_buildings(home_id, hb)
        _fund_planet(home_id)
        ok, reason, _ = evolve_mine(uid, dict(home), "metal_mine")
        assert ok, reason

        cb = get_planet_buildings(colony_id)
        cb["metal_mine"] = 50
        save_planet_buildings(colony_id, cb)

        assert get_evolution_rank(home_id, "metal_mine") == 1
        assert get_evolution_rank(colony_id, "metal_mine") == 0

        hb = get_planet_buildings(home_id)
        er_home = EffectResolver(hb, {}, planet_id=home_id, planet_position=9)
        er_col = EffectResolver(cb, {}, planet_id=colony_id, planet_position=5)
        mod_home = production_context_from_resolver(er_home, "metal").building_modifier
        mod_col = production_context_from_resolver(er_col, "metal").building_modifier
        assert mod_home == pytest.approx(building_modifier_from_rank(1))
        assert mod_col == pytest.approx(1.0)


class TestMineEvolutionPanel:
    def test_panel_row_has_evolution_fields(self, mevo_db):
        from game.buildings import get_buildings_panel_rows
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 180
        save_planet_buildings(pid, buildings)
        planet = dict(planet)
        planet["metal"] = 1e12
        planet["crystal"] = 1e12
        rows = get_buildings_panel_rows(planet, buildings, active_tab="resources")
        metal = next(r for r in rows["resources"] if r["key"] == "metal_mine")
        assert metal["mine_evolution"] is True
        assert metal["uncapped"] is True
        assert metal["evolution_required_level"] == 200
        assert metal["evolution_next_roman"] == "I"
        assert metal["evolution_can_evolve"] is False
        assert metal["evolution_tribute_metal"] == tribute_cost_for_next_rank("metal_mine", 1)[0]
        assert metal["evolution_tribute_crystal"] == tribute_cost_for_next_rank("metal_mine", 1)[1]
        assert "evolution_reset_level" not in metal
        assert metal["at_queue_max"] is False

        solar = next(r for r in rows["resources"] if r["key"] == "solar_plant")
        assert solar.get("mine_evolution") is False
        assert solar.get("uncapped") is False


class TestMineEvolutionApiIdempotent:
    def test_request_id_idempotent(self, mevo_db, monkeypatch):
        from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

        uid = mevo_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        buildings = get_planet_buildings(pid)
        buildings["metal_mine"] = 200
        save_planet_buildings(pid, buildings)
        tribute_m, tribute_c = tribute_cost_for_next_rank("metal_mine", 1)
        _fund_planet(pid, metal=tribute_m + 5000, crystal=tribute_c + 5000)

        import app as app_module

        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = uid

        request_id = f"mevo-{uuid.uuid4().hex}"
        body = {"building_type": "metal_mine", "request_id": request_id}
        r1 = client.post("/api/buildings/mine-evolve", json=body)
        assert r1.status_code == 200
        j1 = r1.get_json()
        assert j1["ok"] is True
        assert get_evolution_rank(pid, "metal_mine") == 1

        from game.db import db

        conn = db()
        try:
            row = conn.execute(
                "SELECT metal, crystal FROM planets WHERE id = ?;", (pid,)
            ).fetchone()
            metal_after = int(row["metal"])
            crystal_after = int(row["crystal"])
        finally:
            conn.close()

        r2 = client.post("/api/buildings/mine-evolve", json=body)
        assert r2.status_code == 200
        j2 = r2.get_json()
        assert j2["ok"] is True
        assert get_evolution_rank(pid, "metal_mine") == 1
        assert int(get_planet_buildings(pid)["metal_mine"]) == 200

        conn = db()
        try:
            row = conn.execute(
                "SELECT metal, crystal FROM planets WHERE id = ?;", (pid,)
            ).fetchone()
            assert int(row["metal"]) == metal_after
            assert int(row["crystal"]) == crystal_after
        finally:
            conn.close()


class TestMineEvolutionDocs:
    def test_master_doc_and_owner_listed(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        doc = (root / "docs" / "MINE_EVOLUTION.md").read_text(encoding="utf-8")
        assert "Tribute" in doc
        assert "required_level(n)" in doc or "required_level" in doc
        assert "kein Level-Reset" in doc.lower() or "no level reset" in doc.lower() or "Level remains" in doc or "level is kept" in doc.lower() or "Level bleibt" in doc or "level unchanged" in doc.lower()
        assert "GC-2905" in doc
        core = (root / "docs" / "CORE_ARCHITECTURE.md").read_text(encoding="utf-8")
        assert "mine_evolution" in core
        assert "MINE_EVOLUTION.md" in core
        epics = (root / "docs" / "EPICS.md").read_text(encoding="utf-8")
        assert "EPIC-29" in epics
        assert "GC-2905" in epics
