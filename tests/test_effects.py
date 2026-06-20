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
import math
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
        assert snap["modifiers"]["weapon_bonus"] == pytest.approx(0.10)
        from game.effects.effect_resolver import COMBAT_MODIFIER_KEYS

        assert "weapon_bonus" in COMBAT_MODIFIER_KEYS
        assert snap["modifiers_prepared"].get("weapon_bonus") is None


class TestBuildingEffects:
    def test_nanofactory_reduces_build_time(self):
        pid = _create_player("nano")
        _set_buildings(pid, {"metal_mine": 1})
        t0 = get_build_time("metal_mine", 4, user_id=pid)
        _set_buildings(pid, {"metal_mine": 1, "nanofactory": 1})
        clear_effect_resolver_cache(pid)
        t1 = get_build_time("metal_mine", 4, user_id=pid)
        assert t1 < t0
        assert t1 <= int(t0 * 0.71)

    def test_command_center_reduces_nanofactory_build_time_only(self):
        pid = _create_player("cmd")
        _set_buildings(pid, {"metal_mine": 1})
        clear_effect_resolver_cache(pid)
        mine_base = get_build_time("metal_mine", 4, user_id=pid)
        _set_buildings(pid, {"metal_mine": 1, "command_center": 3})
        clear_effect_resolver_cache(pid)
        mine_with_cc = get_build_time("metal_mine", 4, user_id=pid)
        assert mine_with_cc == mine_base

        _set_buildings(pid, {"command_center": 2})
        clear_effect_resolver_cache(pid)
        nano_cc2 = get_build_time("nanofactory", 1, user_id=pid)
        _set_buildings(pid, {"command_center": 4})
        clear_effect_resolver_cache(pid)
        nano_cc4 = get_build_time("nanofactory", 1, user_id=pid)
        assert nano_cc4 < nano_cc2
        assert abs(nano_cc4 - int(nano_cc2 * (0.75 ** 2))) <= 1

    def test_nanofactory_speed_bonus_matches_get_build_time_seconds(self):
        pid = _create_player("nano_pct")
        b = _set_buildings(pid, {"metal_mine": 1, "nanofactory": 2})
        r = EffectResolver(b, {}, player_id=pid)
        pct = r.get_build_time_speed_bonus_pct("metal_mine")
        t_mod = get_build_time("metal_mine", 4, user_id=pid)
        _set_buildings(pid, {"metal_mine": 1})
        t_base = get_build_time("metal_mine", 4, user_id=pid)
        expected_pct = int(round((t_base / max(t_mod, 1) - 1.0) * 100))
        assert abs(pct - expected_pct) <= 2

    def test_command_center_speed_bonus_matches_nanofactory_build_time(self):
        pid = _create_player("cc_pct")
        b = _set_buildings(pid, {"command_center": 4})
        r = EffectResolver(b, {}, player_id=pid)
        pct = r.get_build_time_speed_bonus_pct("nanofactory")
        t_mod = get_build_time("nanofactory", 1, user_id=pid)
        _set_buildings(pid, {})
        t_base = get_build_time("nanofactory", 1, user_id=pid)
        expected_pct = int(round((t_base / max(t_mod, 1) - 1.0) * 100))
        assert abs(pct - expected_pct) <= 2

    def test_nanofactory_stacked_speed_bonus_not_additive(self):
        pid = _create_player("stack")
        b = _set_buildings(pid, {"metal_mine": 1, "nanofactory": 2})
        _set_research(pid, {"buildtime_tech": 5})
        r = EffectResolver(b, get_research_levels(pid), player_id=pid)
        pct = r.get_build_time_speed_bonus_pct("metal_mine")
        t_mod = get_build_time("metal_mine", 4, user_id=pid)
        _set_buildings(pid, {"metal_mine": 1})
        _set_research(pid, {})
        t_base = get_build_time("metal_mine", 4, user_id=pid)
        expected_pct = int(round((t_base / max(t_mod, 1) - 1.0) * 100))
        assert abs(pct - expected_pct) <= 2
        from game.effects.effect_resolver import BUILDTIME_TECH_DURATION, NANOFACTORY_DURATION_PER_LEVEL

        expected_speed = (1.0 / (BUILDTIME_TECH_DURATION ** 5)) / (NANOFACTORY_DURATION_PER_LEVEL ** 2)
        assert r.get_build_time_player_speed("metal_mine") == pytest.approx(expected_speed, rel=1e-4)
        wrong_linear_bonus = EffectResolver.buildtime_speed_bonus_pct(5) + 60
        assert pct != wrong_linear_bonus

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

    def test_energy_tech_scales_without_hard_stop(self):
        b = {"metal_mine": 10, "crystal_mine": 10, "solar_plant": 5}
        for level in (12, 20, 50):
            r = {f"energy_tech": level}
            mods = EffectResolver(b, r).get_modifiers()
            expected = max(0.0, 1.0 - 0.05 * level)
            assert mods["mine_energy_factor"] == pytest.approx(expected)
            assert EffectResolver.mine_energy_reduction_pct(level) == int(round(0.05 * level * 100))

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


class TestResearchEffectRealityAudit:
    """GC-622 — technical display, EffectResolver, and gameplay must agree."""

    def test_buildtime_tech_matches_effect_resolver(self):
        level = 24
        b = {}
        r = {"buildtime_tech": level}
        er = EffectResolver(b, r)
        mods = er.get_modifiers()

        duration_factor = float(0.97 ** level)
        assert EffectResolver.buildtime_duration_factor_for_level(level) == pytest.approx(duration_factor)
        assert EffectResolver.buildtime_speed_bonus_pct(level) == int(
            round((1.0 / duration_factor - 1.0) * 100)
        )
        assert mods["build_time_multiplier"] == pytest.approx(duration_factor)
        assert mods["build_time_speed"] == pytest.approx(1 / duration_factor)

        base_seconds = 600
        actual = er.get_build_time_seconds("planet_core_nexus", 1)
        expected = int(base_seconds * mods["build_time_multiplier"] / er.build_speed_setting())
        assert actual == expected

    def test_energy_efficiency_matches_display(self):
        level = 35
        b = {"metal_mine": 8, "crystal_mine": 4}
        r = {"energy_tech": level}
        er = EffectResolver(b, r)

        # linear display: 0.05 * 35 * 100 = 175%; gameplay factor clamps at 0
        assert EffectResolver.mine_energy_reduction_pct(level) == 175
        assert er.get_modifiers()["mine_energy_factor"] == pytest.approx(0.0)

        preview = __import__("game.research", fromlist=["get_research_effect_preview"]).get_research_effect_preview(
            "energy_tech", level, level + 1
        )
        assert preview["effect_current"] == 175

        _, used = er.compute_energy()
        assert used > 0
        raw_metal = int(10 * (8 ** 1.25))
        raw_crystal = int(6 * (4 ** 1.25))
        assert used == EffectResolver.apply_mine_energy_draw(raw_metal, 0.0) + EffectResolver.apply_mine_energy_draw(
            raw_crystal, 0.0
        )

    def test_fuel_efficiency_matches_display(self):
        level = 17
        factor = EffectResolver.fuel_efficiency_factor_for_level(level)
        mods = EffectResolver({}, {"fuel_efficiency": level}).get_modifiers()

        # factor = max(SAFETY_MIN_FACTOR, 1 - 0.03 * level)
        # => level 17: 1 - 0.03*17 = 0.49 => reduction = 51%
        assert factor == pytest.approx(0.49)
        assert mods["fuel_efficiency_factor"] == pytest.approx(0.49)
        assert EffectResolver.fuel_efficiency_reduction_pct(level) == 51

        from game.fleet_calc import calculate_fuel_cost, fuel_efficiency_factor

        assert fuel_efficiency_factor(level) == pytest.approx(factor)
        base = calculate_fuel_cost({"mule_courier": 10}, 5000, 100, fuel_efficiency_level=0)
        reduced = calculate_fuel_cost({"mule_courier": 10}, 5000, 100, fuel_efficiency_level=level)
        assert reduced == int(math.ceil(base * factor))

    def test_research_modal_output_matches_effect(self):
        from game.research import RESEARCH_TECHS, get_research_effect_preview

        cases = {
            "energy_tech": (35, EffectResolver.mine_energy_reduction_pct),
            "buildtime_tech": (24, EffectResolver.buildtime_speed_bonus_pct),
            "fuel_efficiency": (17, EffectResolver.fuel_efficiency_reduction_pct),
            "mining_tech": (6, EffectResolver.metal_prod_bonus_pct),
            "storage_tech": (4, EffectResolver.storage_bonus_pct),
            "weapon_tech": (8, EffectResolver.combat_bonus_pct),
        }
        for tech_key, (level, fn) in cases.items():
            assert tech_key in RESEARCH_TECHS
            preview = get_research_effect_preview(tech_key, level, level + 1)
            assert preview["effect_current"] == fn(level)

    def test_buildtime_tech_l24_ten_minute_base_becomes_four_minutes(self):
        """Browser repro sanity: Bauoptimierung L24 matches EffectResolver math."""
        pid = _create_player("gc622_buildtime")
        _set_buildings(pid, {})
        _set_research(pid, {"buildtime_tech": 24})
        clear_effect_resolver_cache(pid)

        t = get_build_time("planet_core_nexus", 1, user_id=pid)
        er = EffectResolver({}, {"buildtime_tech": 24})
        mods = er.get_modifiers()
        base = EffectResolver({}, {}).get_build_time_seconds("planet_core_nexus", 1)
        assert t == int(base * mods["build_time_multiplier"])

        preview = __import__("game.research", fromlist=["get_research_effect_preview"]).get_research_effect_preview(
            "buildtime_tech", 24, 25
        )
        assert preview["effect_current"] == EffectResolver.buildtime_speed_bonus_pct(24)
        assert preview["effect_kind"] == "bonus_percent"

    def test_research_effects_scale_without_hard_stop(self):
        """GC-622C — infinite scaling display; gameplay clamps at 0 draw / 1s time."""
        from game.research import get_research_effect_preview, RESEARCH_TECHS
        from game.fleet_calc import calculate_fuel_cost

        levels = (50, 100, 250)

        for lvl in levels:
            assert "energy_tech" in RESEARCH_TECHS
            factor = max(0.0, 1.0 - 0.05 * lvl)
            expected_reduction = int(round(0.05 * lvl * 100))

            er = EffectResolver({}, {"energy_tech": lvl}, settings={"build_speed": 1.0})
            mods = er.get_modifiers()
            assert mods["mine_energy_factor"] == pytest.approx(factor)

            preview = get_research_effect_preview("energy_tech", lvl, lvl + 1)
            assert preview["effect_current"] == expected_reduction

            b = {"metal_mine": 5, "crystal_mine": 5}
            _, used = EffectResolver(b, {"energy_tech": lvl}).compute_energy()
            assert used >= 2

        base = 600  # BUILD_TIME_BASE["planet_core_nexus"]
        for lvl in levels:
            assert "buildtime_tech" in RESEARCH_TECHS
            duration_factor = float(0.97 ** lvl)
            expected_bonus = EffectResolver.buildtime_speed_bonus_pct(lvl)

            er = EffectResolver({}, {"buildtime_tech": lvl}, settings={"build_speed": 1.0})
            mods = er.get_modifiers()
            assert mods["build_time_multiplier"] == pytest.approx(duration_factor)
            assert er.get_build_time_seconds("planet_core_nexus", 1) >= 1
            expected_seconds = max(1, int(base * duration_factor))
            assert er.get_build_time_seconds("planet_core_nexus", 1) == expected_seconds

            preview = get_research_effect_preview("buildtime_tech", lvl, lvl + 1)
            assert preview["effect_current"] == expected_bonus
            assert preview["effect_kind"] == "bonus_percent"

        for lvl in levels:
            assert "fuel_efficiency" in RESEARCH_TECHS
            factor = max(0.0, 1.0 - 0.03 * lvl)
            expected_reduction = int(round(0.03 * lvl * 100))

            er = EffectResolver({}, {"fuel_efficiency": lvl})
            mods = er.get_modifiers()
            assert mods["fuel_efficiency_factor"] == pytest.approx(factor)

            preview = get_research_effect_preview("fuel_efficiency", lvl, lvl + 1)
            assert preview["effect_current"] == expected_reduction

            base_cost = calculate_fuel_cost({"mule_courier": 10}, 5000, 100, fuel_efficiency_level=0)
            reduced_cost = calculate_fuel_cost({"mule_courier": 10}, 5000, 100, fuel_efficiency_level=lvl)
            assert reduced_cost == int(math.ceil(base_cost * factor))
            assert reduced_cost >= 0

    def test_crystal_production_buffed_vs_metal_at_equal_mine_level(self):
        lvl = 10
        b = {"metal_mine": lvl, "crystal_mine": lvl}
        metal, crystal = EffectResolver(b, {}).production_rates_per_sec()
        assert crystal > 0.03 * (lvl ** 1.35)
        assert crystal / metal > 0.72

    def test_fuel_cell_plant_production_nerfed(self):
        b = {"fuel_cell_plant": 5}
        er = EffectResolver(b, {}, settings={"fuel_production_per_hour": 2.0})
        per_hour = er.fuel_cells_production_per_hour()
        old_formula = 4 * 5 * (1.35 ** 4)
        assert per_hour < old_formula
        assert per_hour == pytest.approx(2.0 * 5 * (1.255 ** 4))

    def test_gc622d_economy_ratio_targets(self):
        """High-level mines: Crytite ~65% of Ferronit, Brennzellen ~35–40% of Ferronit."""
        ps = 400.0
        ratio = 1.0
        er = EffectResolver(
            {"metal_mine": 29, "crystal_mine": 27, "fuel_cell_plant": 27},
            {"mining_tech": 15, "drone_tech": 10},
            settings={"production_speed": ps, "fuel_production_per_hour": 2.0},
        )
        prod = er.get_building_production_per_hour(ratio)
        metal_ph = float(prod["metal_mine"])
        crystal_ph = float(prod["crystal_mine"])
        fuel_ph = float(prod["fuel_cell_plant"])

        assert metal_ph > crystal_ph > fuel_ph
        assert 0.60 <= crystal_ph / metal_ph <= 0.68
        assert 0.34 <= fuel_ph / metal_ph <= 0.42
        assert 0.52 <= fuel_ph / crystal_ph <= 0.68


class TestGalacticDirectiveEffectResolver:
    def _set_galaxy_directive(
        self,
        galaxy: int,
        primary: str,
        secondary: str | None = None,
    ) -> None:
        conn = db()
        try:
            conn.execute(
                """
                INSERT INTO gd_galaxy_state (
                    galaxy, primary_directive, secondary_directive,
                    consecutive_primary_wins, updated_at
                ) VALUES (?, ?, ?, 0, 0)
                ON CONFLICT(galaxy) DO UPDATE SET
                    primary_directive = excluded.primary_directive,
                    secondary_directive = excluded.secondary_directive,
                    updated_at = excluded.updated_at;
                """,
                (int(galaxy), str(primary), secondary),
            )
            conn.commit()
        finally:
            conn.close()

    def test_industrial_boosts_resource_production(self):
        pid = _create_player("gd_industrial")
        self._set_galaxy_directive(1, "industrial")
        b = _set_buildings(pid, {"metal_mine": 10, "crystal_mine": 10, "fuel_cell_plant": 5})
        er = EffectResolver.for_player(pid)
        mods = er.get_modifiers()
        assert mods["metal_prod_factor"] == pytest.approx(1.20)
        assert mods["crystal_prod_factor"] == pytest.approx(1.15)
        assert mods["fuel_prod_factor"] == pytest.approx(1.25)

        boosted_metal, _ = er.production_rates_per_sec()
        baseline = EffectResolver(b, {}, galaxy_id=None).production_rates_per_sec()[0]
        assert boosted_metal == pytest.approx(baseline * 1.20)

        fuel_ph = er.fuel_cells_production_per_hour()
        fuel_base = EffectResolver(
            b, {}, settings={"fuel_production_per_hour": 2.0}, galaxy_id=None
        ).fuel_cells_production_per_hour()
        assert fuel_ph == pytest.approx(fuel_base * 1.25)

    def test_scientific_affects_research_and_build_speed(self):
        pid = _create_player("gd_scientific")
        self._set_galaxy_directive(1, "scientific")
        _set_buildings(pid, {"research_lab": 1})
        er = EffectResolver.for_player(pid)
        mods = er.get_modifiers()
        assert mods["research_time_speed"] == pytest.approx(1.25)
        assert mods["build_time_speed"] == pytest.approx(1.0)
        assert mods.get("weapon_bonus", 0.0) == pytest.approx(-0.15)

        sci_time = er.get_research_time_seconds("energy_tech", 2)
        self._set_galaxy_directive(1, "defensive")
        clear_effect_resolver_cache(pid)
        def_time = EffectResolver.for_player(pid).get_research_time_seconds("energy_tech", 2)
        assert sci_time < def_time

    def test_missing_state_falls_back_to_defensive(self):
        pid = _create_player("gd_fallback")
        er = EffectResolver.for_player(pid)
        mods = er.get_modifiers()
        assert mods["metal_prod_factor"] == pytest.approx(1.0)
        assert mods["research_time_speed"] == pytest.approx(1.0)

    def test_invalid_directive_keys_do_not_crash(self):
        pid = _create_player("gd_invalid")
        self._set_galaxy_directive(1, "not_a_real_directive")
        er = EffectResolver.for_player(pid)
        mods = er.get_modifiers()
        assert mods["metal_prod_factor"] == pytest.approx(1.0)

    def test_logistics_fleet_modifiers_applied(self):
        pid = _create_player("gd_logistics")
        self._set_galaxy_directive(1, "logistics")
        _set_buildings(pid, {"metal_mine": 5})
        mods = EffectResolver.for_player(pid).get_modifiers()
        assert mods["fleet_speed_multiplier"] == pytest.approx(1.20)
        assert mods["cargo_multiplier"] == pytest.approx(1.50)
        assert mods["fuel_efficiency_factor"] == pytest.approx(0.75)
        assert mods["solar_output_factor"] == pytest.approx(0.95)

    def test_military_combat_and_shipyard_modifiers(self):
        pid = _create_player("gd_military")
        self._set_galaxy_directive(1, "military")
        mods = EffectResolver.for_player(pid).get_modifiers()
        assert mods["weapon_bonus"] == pytest.approx(0.20)
        assert mods["shield_bonus"] == pytest.approx(0.15)
        assert mods["armor_bonus"] == pytest.approx(0.10)
        assert mods["shipyard_time_speed"] == pytest.approx(1.25)
        assert mods["research_time_speed"] == pytest.approx(0.80)


class TestGalacticDiplomacyEffectResolver:
    def _set_galaxy_directive(
        self,
        galaxy: int,
        primary: str,
        secondary: str | None = None,
    ) -> None:
        conn = db()
        try:
            conn.execute(
                """
                INSERT INTO gd_galaxy_state (
                    galaxy, primary_directive, secondary_directive,
                    consecutive_primary_wins, updated_at
                ) VALUES (?, ?, ?, 0, 0)
                ON CONFLICT(galaxy) DO UPDATE SET
                    primary_directive = excluded.primary_directive,
                    secondary_directive = excluded.secondary_directive,
                    updated_at = excluded.updated_at;
                """,
                (int(galaxy), str(primary), secondary),
            )
            conn.commit()
        finally:
            conn.close()

    def test_personality_boosts_research_speed(self):
        from game.galactic_diplomacy import set_galaxy_personality

        pid = _create_player("gdp_academia")
        conn = db()
        try:
            set_galaxy_personality(1, "academia_prime", conn=conn)
        finally:
            conn.close()
        clear_effect_resolver_cache(pid)
        mods = EffectResolver.for_player(pid).get_modifiers()
        assert mods["research_time_speed"] == pytest.approx(1.10)

    def test_directive_and_diplomacy_stack_multiplicatively(self):
        from game.galactic_diplomacy import set_galaxy_personality

        pid = _create_player("gdp_stack")
        conn = db()
        try:
            self._set_galaxy_directive(1, "scientific")
            set_galaxy_personality(1, "academia_prime", conn=conn)
        finally:
            conn.close()
        clear_effect_resolver_cache(pid)
        mods = EffectResolver.for_player(pid).get_modifiers()
        assert mods["research_time_speed"] == pytest.approx(1.25 * 1.10)

    def test_emergency_combat_modifiers_applied(self):
        from game.galactic_diplomacy import set_active_emergency

        pid = _create_player("gdp_emergency")
        conn = db()
        try:
            self._set_galaxy_directive(1, "logistics")
            set_active_emergency(1, "alien_invasion", conn=conn)
        finally:
            conn.close()
        clear_effect_resolver_cache(pid)
        mods = EffectResolver.for_player(pid).get_modifiers()
        assert mods["weapon_bonus"] == pytest.approx(0.25)
        assert mods["shield_bonus"] == pytest.approx(0.20)
        assert mods["defense_time_speed"] == pytest.approx(1.15)

    def test_resolution_and_directive_both_apply(self):
        from game.galactic_diplomacy import set_active_resolution

        pid = _create_player("gdp_resolution")
        conn = db()
        try:
            self._set_galaxy_directive(1, "defensive")
            set_active_resolution(1, "gate_control", conn=conn)
        finally:
            conn.close()
        clear_effect_resolver_cache(pid)
        mods = EffectResolver.for_player(pid).get_modifiers()
        assert mods["research_time_speed"] == pytest.approx(1.05)
        assert mods["metal_prod_factor"] == pytest.approx(1.0)

    def test_missing_diplomacy_state_does_not_crash(self):
        pid = _create_player("gdp_missing")
        mods = EffectResolver.for_player(pid).get_modifiers()
        assert mods["research_time_speed"] == pytest.approx(1.0)
        assert mods["weapon_bonus"] == pytest.approx(0.0)

    def test_directives_remain_active_with_diplomacy(self):
        from game.galactic_diplomacy import set_galaxy_personality

        pid = _create_player("gdp_directive_active")
        conn = db()
        try:
            self._set_galaxy_directive(1, "industrial")
            set_galaxy_personality(1, "forge_of_war", conn=conn)
        finally:
            conn.close()
        clear_effect_resolver_cache(pid)
        mods = EffectResolver.for_player(pid).get_modifiers()
        assert mods["metal_prod_factor"] == pytest.approx(1.20)
        assert mods["weapon_bonus"] == pytest.approx(0.05)
        assert mods["shipyard_time_speed"] == pytest.approx(1.05)
