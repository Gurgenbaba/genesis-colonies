"""
Effect resolver tests – authoritative building + research bonuses.

Run: python -m pytest tests/test_effects.py tests/test_game_state_live.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import get_build_time, get_max_level_for_building
from game.db import db
from game.effects import (
    PREPARED_MODIFIER_KEYS,
    EffectResolver,
    clear_effect_resolver_cache,
)
from game.models import (
    add_build_job,
    create_user,
    get_homeworld,
    get_planet_buildings,
    get_research_levels,
    init_db,
    save_planet_buildings,
    save_research_level,
)
from game.queue_engine import finish_due_work, finish_due_work_once
from game.tick_runner import run_queue_tick
from game.research import RESEARCH_TECHS, get_research_modifiers, get_research_time
from game.logic import get_building_production_per_hour, get_research_status, refresh_player_live_state
from game.resources import (
    compute_energy,
    get_storage_capacity,
    production_rates_per_sec,
    sync_derived_state_after_queue_finish,
    update_planet_resources,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "effects_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _close_db() -> None:
    try:
        db().close()
    except Exception:
        pass


def _create_player(username: str) -> int:
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    _close_db()
    return int(user["id"])


def _set_buildings(player_id: int, levels: dict) -> dict:
    planet = get_homeworld(player_id=player_id)
    save_planet_buildings(int(planet["id"]), levels)
    clear_effect_resolver_cache(player_id)
    return get_planet_buildings(int(planet["id"]))


def _set_research(player_id: int, levels: dict) -> dict:
    for key in RESEARCH_TECHS:
        save_research_level(key, int(levels.get(key, 0) or 0), player_id)
    clear_effect_resolver_cache(player_id)
    return get_research_levels(player_id)


@pytest.fixture(autouse=True)
def _db_setup(temp_db):
    _close_db()
    init_db()
    _close_db()
    _run_migrate(temp_db)
    init_db()
    yield
    _close_db()


class TestResearchModifiers:
    def test_energy_tech_reduces_mine_consumption(self):
        pid = _create_player("energy")
        b = _set_buildings(pid, {"metal_mine": 5, "crystal_mine": 3, "solar_plant": 2})
        r0 = _set_research(pid, {})
        _, used0 = compute_energy(b, r0, mods=get_research_modifiers(pid))

        r1 = _set_research(pid, {"energy_tech": 2})
        mods = get_research_modifiers(pid)
        _, used1 = compute_energy(b, r1, mods=mods)

        assert mods["mine_energy_factor"] == pytest.approx(0.9)
        assert used1 < used0

    def test_mining_tech_boosts_metal_more_than_crystal(self):
        pid = _create_player("mining")
        b = _set_buildings(pid, {"metal_mine": 4, "crystal_mine": 4})
        base_m, base_c = production_rates_per_sec(b, {}, mods={"metal_prod_factor": 1.0, "crystal_prod_factor": 1.0})

        r = _set_research(pid, {"mining_tech": 3})
        mods = get_research_modifiers(pid)
        m, c = production_rates_per_sec(b, r, mods=mods)

        assert m > base_m * 1.29
        assert c > base_c * 1.11
        assert (m / base_m) > (c / base_c)

    def test_drone_tech_boosts_both_resources(self):
        pid = _create_player("drone")
        b = _set_buildings(pid, {"metal_mine": 3, "crystal_mine": 3})
        base_m, base_c = production_rates_per_sec(b, {}, mods={"metal_prod_factor": 1.0, "crystal_prod_factor": 1.0})

        mods = get_research_modifiers(pid)
        _set_research(pid, {"drone_tech": 4})
        mods = get_research_modifiers(pid)
        m, c = production_rates_per_sec(b, _set_research(pid, {"drone_tech": 4}), mods=mods)

        assert m == pytest.approx(base_m * 1.12, rel=0.01)
        assert c == pytest.approx(base_c * 1.12, rel=0.01)

    def test_storage_tech_increases_capacity(self):
        pid = _create_player("storage")
        b = _set_buildings(pid, {"metal_storage": 2, "crystal_storage": 2})
        cap0 = get_storage_capacity(b, {}, mods={"storage_factor": 1.0})

        r = _set_research(pid, {"storage_tech": 2})
        cap1 = get_storage_capacity(b, r, mods=get_research_modifiers(pid))

        assert cap1["metal"] > cap0["metal"]
        assert cap1["metal"] == pytest.approx(int(cap0["metal"] * 1.5))

    def test_buildtime_tech_speeds_build_and_research(self):
        pid = _create_player("buildtime")
        _set_buildings(pid, {"research_lab": 3})
        _set_research(pid, {})

        t_base = get_build_time("metal_mine", 5, user_id=None)
        t_fast = get_build_time("metal_mine", 5, user_id=pid)

        _set_research(pid, {"buildtime_tech": 5})
        clear_effect_resolver_cache(pid)
        t_boosted = get_build_time("metal_mine", 5, user_id=pid)

        assert t_boosted < t_fast
        assert t_fast <= t_base

        _set_research(pid, {})
        clear_effect_resolver_cache(pid)
        r_no_boost = get_research_time("energy_tech", 3, pid)
        _set_research(pid, {"buildtime_tech": 5})
        clear_effect_resolver_cache(pid)
        r_with_boost = get_research_time("energy_tech", 3, pid)
        assert r_with_boost < r_no_boost

    def test_combat_modifiers_prepared_not_applied_to_production(self):
        pid = _create_player("combat")
        b = _set_buildings(pid, {"metal_mine": 4, "crystal_mine": 2})
        _set_research(pid, {"weapon_tech": 2, "armor_tech": 1, "shield_tech": 3})
        mods = get_research_modifiers(pid)
        assert mods["weapon_bonus"] == pytest.approx(0.10)
        base_m, _ = production_rates_per_sec(b, {}, mods={"metal_prod_factor": 1.0, "crystal_prod_factor": 1.0})
        boosted_m, _ = production_rates_per_sec(b, {}, mods=mods)
        assert boosted_m == pytest.approx(base_m)
        snap = EffectResolver(b, get_research_levels(pid), player_id=pid).debug_snapshot()
        assert snap["modifiers_prepared"]["weapon_bonus"] == pytest.approx(0.10)
        assert "weapon_bonus" in PREPARED_MODIFIER_KEYS


class TestBuildingEffects:
    def test_nanofactory_reduces_build_time(self):
        pid = _create_player("nano")
        _set_buildings(pid, {"metal_mine": 1})
        t0 = get_build_time("metal_mine", 4, user_id=pid)
        _set_buildings(pid, {"metal_mine": 1, "nanofactory": 1})
        clear_effect_resolver_cache(pid)
        t1 = get_build_time("metal_mine", 4, user_id=pid)
        assert t1 < t0
        assert t1 <= int(t0 / 1.29)

    def test_academy_speeds_research(self):
        pid = _create_player("academy")
        _set_buildings(pid, {"research_lab": 4})
        t0 = get_research_time("mining_tech", 2, pid)
        _set_buildings(pid, {"research_lab": 4, "academy": 2})
        clear_effect_resolver_cache(pid)
        t1 = get_research_time("mining_tech", 2, pid)
        assert t1 < t0

    def test_geothermal_boosts_solar_and_max_levels(self):
        pid = _create_player("geo")
        b = _set_buildings(pid, {"solar_plant": 5, "metal_mine": 1})
        e0, _ = compute_energy(b, {}, mods={"solar_output_factor": 1.0, "mine_energy_factor": 1.0})

        b2 = _set_buildings(pid, {"solar_plant": 5, "metal_mine": 1, "geothermal_nexus": 2})
        mods = get_research_modifiers(pid)
        e1, _ = compute_energy(b2, {}, mods=mods)

        assert e1 > e0
        assert get_max_level_for_building("metal_mine", b2) == 50 + 4
        assert get_max_level_for_building("metal_storage", b2) == 54

    def test_geothermal_and_core_stack_max_levels(self):
        b = {
            "planet_core_nexus": 3,
            "geothermal_nexus": 2,
        }
        assert EffectResolver(b, {}).get_max_building_level("solar_plant") == 57

    def test_radar_scan_range_prepared_only(self):
        pid = _create_player("radar")
        b = _set_buildings(pid, {"radar_array": 3, "metal_mine": 2})
        mods = get_research_modifiers(pid)
        assert mods["scan_range"] == 6
        snap = EffectResolver(b, get_research_levels(pid), player_id=pid).debug_snapshot()
        assert any(s["key"] == "scan_range" and s["status"] == "prepared" for s in snap["sources_prepared"])


class TestRecursionSafeSync:
    def test_sync_calls_update_with_skip_queue_finish_only(self):
        pid = _create_player("sync_skip")
        planet = get_homeworld(player_id=pid)
        planet_id = int(planet["id"])

        with patch("game.resources.finish_due_work_once") as mock_finish_once:
            with patch(
                "game.resources.update_planet_resources",
                wraps=update_planet_resources,
            ) as mock_update:
                sync_derived_state_after_queue_finish(
                    planet_ids=[planet_id],
                    player_ids=[pid],
                )

            mock_finish_once.assert_not_called()
            assert mock_update.call_count >= 1
            for call in mock_update.call_args_list:
                assert call.kwargs.get("skip_queue_finish") is True

    def test_finish_due_work_then_sync_no_extra_finish_once(self):
        pid = _create_player("no_double_finish")
        planet = get_homeworld(player_id=pid)
        planet_id = int(planet["id"])
        _set_buildings(pid, {"metal_mine": 1, "solar_plant": 1})

        conn = db()
        now = time.time()
        add_build_job(planet_id, "metal_mine", now - 30, now - 1, conn=conn)
        conn.commit()

        finish_once_calls: list[str] = []

        def _track_finish(*_a, **_k):
            finish_once_calls.append("called")
            from game.queue_engine import finish_due_work_once as real

            return real(*_a, **_k)

        with patch("game.resources.finish_due_work_once", side_effect=_track_finish):
            result = finish_due_work(player_id=pid, conn=conn, source="recursion_test")
            conn.commit()

        conn.close()
        _close_db()

        # finish_due_work does not call finish_due_work_once; sync must not add calls
        assert finish_once_calls == []
        assert result.get("derived_sync_count", 0) >= 1


class TestOfflineTickDerivedState:
    def _planet_energy(self, planet_id: int, conn) -> tuple[int, int]:
        cur = conn.cursor()
        cur.execute(
            "SELECT energy_total, energy_used FROM planets WHERE id = ?;",
            (int(planet_id),),
        )
        row = cur.fetchone()
        return int(row["energy_total"] or 0), int(row["energy_used"] or 0)

    def test_finish_due_work_persists_energy_without_http(self):
        pid = _create_player("offline_energy")
        planet = get_homeworld(player_id=pid)
        planet_id = int(planet["id"])
        _set_buildings(pid, {"solar_plant": 2, "metal_mine": 3})

        conn = db()
        try:
            et_before, eu_before = self._planet_energy(planet_id, conn)
            now = time.time()
            add_build_job(planet_id, "solar_plant", now - 50, now - 1, conn=conn)
            conn.commit()

            result = finish_due_work(player_id=pid, conn=conn, source="cron_test")
            conn.commit()
            assert result["derived_sync_count"] >= 1

            et_after, eu_after = self._planet_energy(planet_id, conn)
            assert int(get_planet_buildings(planet_id, conn=conn).get("solar_plant", 0)) == 3
            assert et_after > et_before or eu_after != eu_before
        finally:
            conn.close()

    def test_research_finish_syncs_and_speeds_build_time(self):
        pid = _create_player("offline_research")
        _set_buildings(pid, {"research_lab": 2, "metal_mine": 1})
        _set_research(pid, {})

        t_before = get_build_time("metal_mine", 4, user_id=pid)

        conn = db()
        now = time.time()
        conn.execute(
            "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
            (pid, "buildtime_tech", now - 50, now - 1),
        )
        conn.commit()
        conn.close()

        result = finish_due_work(player_id=pid, source="worker_test")
        _close_db()
        assert result["finished"]["research"] == 1
        assert result["derived_sync_count"] >= 1

        t_after = get_build_time("metal_mine", 4, user_id=pid)
        assert t_after < t_before

    def test_run_queue_tick_syncs_due_player(self):
        pid = _create_player("queue_tick")
        planet = get_homeworld(player_id=pid)
        planet_id = int(planet["id"])
        _set_buildings(pid, {"metal_mine": 2, "solar_plant": 1})

        conn = db()
        now = time.time()
        add_build_job(planet_id, "metal_mine", now - 40, now - 1, conn=conn)
        conn.commit()
        conn.close()

        result = run_queue_tick(player_id=pid, source="test_tick", persist=False)
        _close_db()
        assert result["finished"]["buildings"] >= 1
        assert int(get_planet_buildings(planet_id).get("metal_mine", 0)) == 3


class TestQueueFinishLiveEffects:
    def test_build_finish_applies_production_immediately(self):
        pid = _create_player("queue_prod")
        planet = get_homeworld(player_id=pid)
        planet_id = int(planet["id"])

        _set_buildings(pid, {"metal_mine": 1, "solar_plant": 2})
        now = time.time()
        add_build_job(planet_id, "metal_mine", now - 100, now - 1)

        conn = db()
        try:
            finish_due_work_once(player_id=pid, conn=conn, source="test")
            conn.commit()
            planet2, _, _, _, _ = update_planet_resources(dict(planet), conn=conn)
            conn.commit()
        finally:
            conn.close()

        buildings = get_planet_buildings(planet_id)
        assert int(buildings.get("metal_mine", 0)) == 2

        r = EffectResolver(buildings, get_research_levels(pid))
        m_rate, _ = r.production_rates_per_sec()
        assert m_rate > 0.04 * (1 ** 1.4)


class TestLiveRefreshGuards:
    def test_coerce_skip_finish_after_refresh(self):
        pid = _create_player("coerce")
        _set_buildings(pid, {"metal_mine": 1})

        from flask import Flask

        app = Flask("guard_test")
        with app.test_request_context("/"):
            from game.live_state import mark_request_live_refreshed
            from game.logic import get_build_queue_status, get_research_status

            mark_request_live_refreshed()
            with patch("game.queue_engine.finish_due_work_once") as mock_finish:
                get_build_queue_status(pid, skip_finish=False)
                get_research_status(pid, skip_finish=False)
                mock_finish.assert_not_called()

    def test_skip_finish_research_does_not_finish(self):
        pid = _create_player("skip_res")
        _set_buildings(pid, {"research_lab": 1})

        with patch("game.queue_engine.finish_due_work_once") as mock_finish:
            with patch("game.research.complete_finished_research") as mock_complete:
                get_research_status(pid, skip_finish=True)
                mock_finish.assert_not_called()
                mock_complete.assert_not_called()

    def test_energy_tech_mine_factor_caps_at_0_4(self):
        b = {"metal_mine": 10, "crystal_mine": 10, "solar_plant": 5}
        for level in (12, 20):
            r = {f"energy_tech": level}
            mods = EffectResolver(b, r).get_modifiers()
            assert mods["mine_energy_factor"] == pytest.approx(0.4)

    def test_overview_rows_production_after_mining_tech(self):
        pid = _create_player("overview_rows")
        b = _set_buildings(pid, {"metal_mine": 5, "crystal_mine": 3, "solar_plant": 2})
        _set_research(pid, {})

        m_before, _ = production_rates_per_sec(b, {}, mods={"metal_prod_factor": 1.0, "crystal_prod_factor": 1.0})
        _set_research(pid, {"mining_tech": 2})
        _, buildings, ratio, _, _, _ = refresh_player_live_state(pid, finish_source="test_overview")
        prod_after = get_building_production_per_hour(buildings, ratio, user_id=pid)["metal_mine"]
        m_after, _ = production_rates_per_sec(buildings, get_research_levels(pid), mods=get_research_modifiers(pid))

        assert m_after > m_before
        assert prod_after > 0


class TestLiveRefreshPipeline:
    def test_refresh_player_live_state_applies_energy_tech(self):
        pid = _create_player("live_energy")
        _set_buildings(pid, {"metal_mine": 6, "crystal_mine": 4, "solar_plant": 3})
        _set_research(pid, {})

        b = get_planet_buildings(int(get_homeworld(player_id=pid)["id"]))
        r = get_research_levels(pid)
        used_before = EffectResolver(b, r, player_id=pid).compute_energy()[1]

        _set_research(pid, {"energy_tech": 2})
        _close_db()

        _, buildings, _, _, energy_used, _ = refresh_player_live_state(pid, finish_source="test_live")
        mods = get_research_modifiers(pid)
        assert mods["mine_energy_factor"] == pytest.approx(0.9)
        assert energy_used < used_before

    def test_game_state_path_single_finish_pass(self):
        pid = _create_player("single_finish")
        _set_buildings(pid, {"metal_mine": 2, "solar_plant": 1})

        with patch("game.queue_engine.finish_due_work_once") as mock_finish:
            refresh_player_live_state(pid, finish_source="game_state")
            get_research_status(pid, skip_finish=True)
            assert mock_finish.call_count == 1

    def test_update_resources_then_status_no_second_finish(self):
        pid = _create_player("order_guard")
        planet = get_homeworld(player_id=pid)
        _set_buildings(pid, {"metal_mine": 2, "solar_plant": 1})

        from flask import Flask

        app = Flask("order_guard")
        conn = db()
        try:
            with app.test_request_context("/"):
                with patch("game.resources.finish_due_work_once") as mock_finish:
                    update_planet_resources(dict(planet), conn=conn)
                    get_research_status(pid, skip_finish=False, conn=conn)
                    assert mock_finish.call_count == 1
            conn.commit()
        finally:
            conn.close()


class TestServerAuthoritativeDisplay:
    def test_energy_ratio_authoritative_from_resolver(self):
        pid = _create_player("ratio")
        b = _set_buildings(pid, {"metal_mine": 8, "crystal_mine": 4, "solar_plant": 2})
        r = _set_research(pid, {"energy_tech": 1})
        resolver = EffectResolver(b, r, player_id=pid)
        et, eu = resolver.compute_energy()
        ratio = EffectResolver.energy_ratio(et, eu)
        assert et < eu
        assert ratio == pytest.approx(et / max(1, eu))
        assert int(round(ratio * 100)) < 100


class TestMultiPlayerIsolation:
    def test_players_do_not_share_modifiers(self):
        p1 = _create_player("iso1")
        p2 = _create_player("iso2")
        _set_research(p1, {"mining_tech": 6})
        _set_research(p2, {})

        m1 = get_research_modifiers(p1)["metal_prod_factor"]
        m2 = get_research_modifiers(p2)["metal_prod_factor"]
        assert m1 == pytest.approx(1.6)
        assert m2 == pytest.approx(1.0)
