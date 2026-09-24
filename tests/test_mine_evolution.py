"""Nodebuster Mine Ascension V1 regression contract."""

from __future__ import annotations

import uuid

import pytest

from game.mine_evolution import evolve_mine, get_evolution_rank
from game.mine_evolution.nodebuster import (
    ASCENSION_MIN_LEVEL,
    SKILL_CATALOG,
    ascension_points_for_depth,
    get_state,
    production_multiplier,
    purchase_skill,
    reset_start_level,
    skill_point_cost,
)
from game.models import get_homeworld, get_planet_buildings, save_planet_buildings


@pytest.fixture
def mevo_db(tmp_path, monkeypatch):
    import game.db as dbmod
    import game.models as models
    from game.models import create_user, ensure_player_and_homeworld, init_db

    db_file = tmp_path / "nodebuster_mine.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()

    import migrate

    migrate.main()

    uname = f"nodebuster_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


def _set_level(uid: int, building: str, level: int) -> dict:
    planet = dict(get_homeworld(player_id=uid))
    levels = get_planet_buildings(int(planet["id"]))
    levels[building] = int(level)
    save_planet_buildings(int(planet["id"]), levels)
    return planet


def test_nodebuster_depth_points_are_unbounded_and_depth_sensitive():
    assert ASCENSION_MIN_LEVEL == 200
    assert ascension_points_for_depth(199) == 0
    assert ascension_points_for_depth(200) == 1
    assert ascension_points_for_depth(225) == 2
    assert ascension_points_for_depth(250) == 3
    assert ascension_points_for_depth(300) == 6
    assert ascension_points_for_depth(400) == 11
    assert ascension_points_for_depth(1000) > ascension_points_for_depth(500)


def test_skill_costs_rise_and_capstone_has_prerequisites():
    assert skill_point_cost("reconstruction", 0) == 1
    assert skill_point_cost("reconstruction", 1) == 1
    assert skill_point_cost("reconstruction", 2) == 2
    assert skill_point_cost("deep_yield", 0) == 2
    assert skill_point_cost("overdrive", 0) == 5
    assert SKILL_CATALOG["overdrive"]["requires"]["deep_yield"] == 5
    assert SKILL_CATALOG["overdrive"]["requires"]["deep_storage"] == 5


def test_ascension_resets_only_selected_mine_and_grants_points(mevo_db):
    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 250)
    levels = get_planet_buildings(int(planet["id"]))
    levels["crystal_mine"] = 77
    save_planet_buildings(int(planet["id"]), levels)

    ok, reason, payload = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason
    assert payload["ascended_from_level"] == 250
    assert payload["level"] == 0
    assert payload["points_gain"] == 3
    assert payload["best_depth"] == 250

    after = get_planet_buildings(int(planet["id"]))
    assert int(after["metal_mine"]) == 0
    assert int(after["crystal_mine"]) == 77
    assert get_evolution_rank(int(planet["id"]), "metal_mine") == 1
    assert get_evolution_rank(int(planet["id"]), "crystal_mine") == 0

    state = get_state(int(planet["id"]), "metal_mine")
    assert state["ascension_count"] == 1
    assert state["points_earned"] == 3
    assert state["points_unspent"] == 3
    assert state["best_depth"] == 250
    assert state["last_depth"] == 250


def test_ascension_settles_resources_before_reset(mevo_db, monkeypatch):
    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 250)
    pid = int(planet["id"])
    seen_levels = []

    def _settle(snapshot, *, conn, skip_queue_finish, persist):
        seen_levels.append(int(get_planet_buildings(pid, conn=conn)["metal_mine"]))
        assert skip_queue_finish is True
        assert persist is True
        return snapshot, get_planet_buildings(pid, conn=conn), 1.0, 0, 0

    monkeypatch.setattr("game.resources.update_planet_resources", _settle)

    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason
    assert seen_levels == [250]
    assert int(get_planet_buildings(pid)["metal_mine"]) == 0


def test_reconstruction_changes_next_reset_baseline(mevo_db):
    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 300)
    ok, reason, first = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason
    assert first["points_gain"] == 6

    ok, reason, skill = purchase_skill(uid, planet, "metal_mine", "reconstruction")
    assert ok, reason
    assert skill["skill_rank"] == 1
    assert skill["reset_level"] == 12

    _set_level(uid, "metal_mine", 200)
    ok, reason, second = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason
    assert second["reset_level"] == 12
    assert int(get_planet_buildings(int(planet["id"]))["metal_mine"]) == 12


def test_output_skill_is_per_mine_and_per_planet(mevo_db):
    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 300)
    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason

    ok, reason, skill = purchase_skill(uid, planet, "metal_mine", "deep_yield")
    assert ok, reason
    assert skill["production_bonus_pct"] == pytest.approx(2.5)

    from game.mine_evolution.service import building_modifier_for

    pid = int(planet["id"])
    assert building_modifier_for(pid, "metal_mine") == pytest.approx(1.025)
    assert building_modifier_for(pid, "crystal_mine") == pytest.approx(1.0)


def test_deep_storage_is_per_mine_resource_and_planet(mevo_db):
    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 300)
    pid = int(planet["id"])

    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason

    from game.db import db
    from game.effects import get_effect_resolver
    from game.models import get_research_levels

    conn = db()
    try:
        buildings = get_planet_buildings(pid, conn=conn)
        research = get_research_levels(uid, conn=conn)
        resolver = get_effect_resolver(
            uid,
            buildings=buildings,
            research=research,
            conn=conn,
            planet=dict(get_homeworld(player_id=uid, conn=conn)),
            force_refresh=True,
        )
        before = resolver.get_storage_capacity()
    finally:
        conn.close()

    ok, reason, skill = purchase_skill(uid, planet, "metal_mine", "deep_storage")
    assert ok, reason
    assert skill["storage_bonus_pct"] == pytest.approx(5.0)

    conn = db()
    try:
        buildings = get_planet_buildings(pid, conn=conn)
        research = get_research_levels(uid, conn=conn)
        resolver = get_effect_resolver(
            uid,
            buildings=buildings,
            research=research,
            conn=conn,
            planet=dict(get_homeworld(player_id=uid, conn=conn)),
            force_refresh=True,
        )
        after = resolver.get_storage_capacity()
    finally:
        conn.close()

    assert after["metal"] == (before["metal"] * 10500) // 10000
    assert after["crystal"] == before["crystal"]
    assert after["fuel_cells"] == before["fuel_cells"]


def test_panel_exposes_nodebuster_server_truth(mevo_db):
    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 225)

    from game.mine_evolution import panel_evolution_fields

    fields = panel_evolution_fields(
        int(planet["id"]),
        "metal_mine",
        225,
    )
    assert fields["nodebuster"] is True
    assert fields["evolution_can_evolve"] is True
    assert fields["nodebuster_points_gain"] == 2
    assert fields["nodebuster_reset_level"] == 0
    assert len(fields["nodebuster_skills"]) == 12
    assert any(row["key"] == "deep_storage" for row in fields["nodebuster_skills"])
    assert any(row["key"] == "overdrive" for row in fields["nodebuster_skills"])


def test_request_id_keeps_ascension_exactly_once(mevo_db):
    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 225)

    import app as app_module

    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    request_id = f"nodebuster-{uuid.uuid4().hex}"
    body = {"building_type": "metal_mine", "request_id": request_id}

    r1 = client.post("/api/buildings/mine-evolve", json=body)
    assert r1.status_code == 200
    assert r1.get_json()["ok"] is True

    r2 = client.post("/api/buildings/mine-evolve", json=body)
    assert r2.status_code == 200
    assert r2.get_json()["ok"] is True

    state = get_state(int(planet["id"]), "metal_mine")
    assert state["ascension_count"] == 1
    assert state["points_earned"] == 2
    assert int(get_planet_buildings(int(planet["id"]))["metal_mine"]) == 0


def test_ruleset_is_nodebuster_v1():
    from game.mine_evolution.ruleset import ASCENSION_RULESET

    assert ASCENSION_RULESET == "nodebuster-v1"


def test_breakthrough_window_reaches_buildings_cost_and_time_consumer(mevo_db):
    import time

    from game.buildings import _nodebuster_rebuild_bps
    from game.db import commit, db
    from game.mine_evolution.nodebuster import rebuild_bps_for_target

    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 500)
    pid = int(planet["id"])
    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason

    conn = db()
    try:
        now = time.time()
        for key, rank in (
            ("frugal_rebuild", 8),
            ("rapid_rebuild", 8),
            ("breakthrough_window", 1),
        ):
            conn.execute(
                """
                INSERT INTO planet_mine_ascension_skills (
                    planet_id, building_type, skill_key, skill_rank, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(planet_id, building_type, skill_key) DO UPDATE SET
                    skill_rank = excluded.skill_rank,
                    updated_at = excluded.updated_at;
                """,
                (pid, "metal_mine", key, rank, now),
            )
        commit(conn)

        assert rebuild_bps_for_target(pid, "metal_mine", 550, conn=conn) == (5600, 4800)
        assert rebuild_bps_for_target(pid, "metal_mine", 551, conn=conn) == (10000, 10000)
        assert _nodebuster_rebuild_bps(pid, "metal_mine", 550, conn=conn) == (5600, 4800)
        assert _nodebuster_rebuild_bps(pid, "metal_mine", 551, conn=conn) == (10000, 10000)
    finally:
        conn.close()


def test_breakthrough_tail_flows_from_db_into_production_context(mevo_db):
    import time

    from game.db import commit, db
    from game.effects import get_effect_resolver
    from game.mine_evolution.service import tail_power_bonus_hundredths_for
    from game.models import get_research_levels
    from game.production_formula import production_context_from_resolver

    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 500)
    pid = int(planet["id"])
    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason
    _set_level(uid, "metal_mine", 500)

    conn = db()
    try:
        now = time.time()
        for key in ("core_resonance", "singularity_excavation"):
            conn.execute(
                """
                INSERT INTO planet_mine_ascension_skills (
                    planet_id, building_type, skill_key, skill_rank, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(planet_id, building_type, skill_key) DO UPDATE SET
                    skill_rank = excluded.skill_rank,
                    updated_at = excluded.updated_at;
                """,
                (pid, "metal_mine", key, 1, now),
            )
        commit(conn)

        assert tail_power_bonus_hundredths_for(pid, "metal_mine", conn=conn) == 30

        buildings = get_planet_buildings(pid, conn=conn)
        research = get_research_levels(uid, conn=conn)
        resolver = get_effect_resolver(
            uid,
            buildings=buildings,
            research=research,
            conn=conn,
            planet=dict(get_homeworld(player_id=uid, conn=conn)),
            force_refresh=True,
        )
        context = production_context_from_resolver(resolver, "metal")
        assert context.mine_tail_power_bonus_hundredths == 30
    finally:
        conn.close()


def test_ascension_energy_skills_reach_live_energy_and_production_context(mevo_db):
    import time

    from game.db import commit, db
    from game.effects import EffectResolver, get_effect_resolver
    from game.models import get_research_levels
    from game.production_formula import production_context_from_resolver

    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 300)
    pid = int(planet["id"])
    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason

    levels = get_planet_buildings(pid)
    levels["metal_mine"] = 100
    levels["crystal_mine"] = 100
    levels["solar_plant"] = 100
    save_planet_buildings(pid, levels)

    conn = db()
    try:
        now = time.time()
        for key, rank in (
            ("optimized_energy", 10),
            ("load_balancing", 10),
        ):
            conn.execute(
                """
                INSERT INTO planet_mine_ascension_skills (
                    planet_id, building_type, skill_key, skill_rank, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(planet_id, building_type, skill_key) DO UPDATE SET
                    skill_rank = excluded.skill_rank,
                    updated_at = excluded.updated_at;
                """,
                (pid, "metal_mine", key, rank, now),
            )
        commit(conn)

        buildings = get_planet_buildings(pid, conn=conn)
        research = get_research_levels(uid, conn=conn)
        resolver = get_effect_resolver(
            uid,
            buildings=buildings,
            research=research,
            conn=conn,
            planet=dict(get_homeworld(player_id=uid, conn=conn)),
            force_refresh=True,
        )

        raw_metal = int(10 * (100 ** 1.25))
        assert resolver.building_energy_draw("metal_mine") == EffectResolver.apply_mine_energy_draw(
            raw_metal, 0.8
        )

        metal_ctx = production_context_from_resolver(
            resolver,
            "metal",
            energy_ratio=0.60,
        )
        crystal_ctx = production_context_from_resolver(
            resolver,
            "crystal",
            energy_ratio=0.60,
        )
        assert metal_ctx.energy_ratio == pytest.approx(0.70)
        assert crystal_ctx.energy_ratio == pytest.approx(0.60)
    finally:
        conn.close()



def test_rebuild_surge_flows_from_db_into_canonical_production_context(mevo_db):
    import time

    from game.db import commit, db
    from game.effects import get_effect_resolver
    from game.models import get_research_levels
    from game.production_formula import production_context_from_resolver

    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 500)
    pid = int(planet["id"])
    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason

    conn = db()
    try:
        now = time.time()
        conn.execute(
            """
            INSERT INTO planet_mine_ascension_skills (
                planet_id, building_type, skill_key, skill_rank, updated_at
            ) VALUES (?, ?, 'legacy_reconstruction', 1, ?)
            ON CONFLICT(planet_id, building_type, skill_key) DO UPDATE SET
                skill_rank = excluded.skill_rank,
                updated_at = excluded.updated_at;
            """,
            (pid, "metal_mine", now),
        )
        commit(conn)

        def _context_at(level: int):
            levels = get_planet_buildings(pid, conn=conn)
            levels["metal_mine"] = int(level)
            save_planet_buildings(pid, levels, conn=conn)
            research = get_research_levels(uid, conn=conn)
            resolver = get_effect_resolver(
                uid,
                buildings=get_planet_buildings(pid, conn=conn),
                research=research,
                conn=conn,
                planet=dict(get_homeworld(player_id=uid, conn=conn)),
                force_refresh=True,
            )
            return production_context_from_resolver(resolver, "metal")

        assert _context_at(500).mine_rebuild_modifier == pytest.approx(2.00)
        assert _context_at(501).mine_rebuild_modifier == pytest.approx(1.0)

        conn.execute(
            """
            INSERT INTO planet_mine_ascension_skills (
                planet_id, building_type, skill_key, skill_rank, updated_at
            ) VALUES (?, ?, 'breakthrough_window', 1, ?)
            ON CONFLICT(planet_id, building_type, skill_key) DO UPDATE SET
                skill_rank = excluded.skill_rank,
                updated_at = excluded.updated_at;
            """,
            (pid, "metal_mine", now),
        )
        commit(conn)

        assert _context_at(550).mine_rebuild_modifier == pytest.approx(2.00)
        assert _context_at(551).mine_rebuild_modifier == pytest.approx(1.0)
    finally:
        conn.close()


def test_queue_finish_settles_rebuild_surge_before_crossing_record_boundary(
    mevo_db, monkeypatch
):
    import time

    from game.db import commit, db
    from game.models import add_build_job
    from game.queue_engine import finish_planet_build_jobs

    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 500)
    pid = int(planet["id"])
    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason
    _set_level(uid, "metal_mine", 500)

    conn = db()
    try:
        now = time.time()
        conn.execute(
            """
            INSERT INTO planet_mine_ascension_skills (
                planet_id, building_type, skill_key, skill_rank, updated_at
            ) VALUES (?, ?, 'legacy_reconstruction', 1, ?)
            ON CONFLICT(planet_id, building_type, skill_key) DO UPDATE SET
                skill_rank = excluded.skill_rank,
                updated_at = excluded.updated_at;
            """,
            (pid, "metal_mine", now),
        )
        # Start one level below the record and finish two overdue jobs. Both
        # completion boundaries are still inside the purchased surge window.
        levels = get_planet_buildings(pid, conn=conn)
        levels["metal_mine"] = 499
        save_planet_buildings(pid, levels, conn=conn)
        first_finish = now - 8.0
        second_finish = now - 5.0
        add_build_job(
            pid,
            "metal_mine",
            now - 10.0,
            first_finish,
            conn=conn,
        )
        add_build_job(
            pid,
            "metal_mine",
            first_finish,
            second_finish,
            conn=conn,
        )
        commit(conn)

        seen = []
        profile_snapshots = []
        from game.mine_evolution import service as mine_evolution_service

        real_rebuild_multiplier = mine_evolution_service.rebuild_production_multiplier_for

        def _rebuild_multiplier(*args, profiles=None, **kwargs):
            current_level = int(args[2]) if len(args) >= 3 else int(kwargs["current_level"])
            if current_level in (499, 500):
                profile_snapshots.append(profiles)
            return real_rebuild_multiplier(*args, profiles=profiles, **kwargs)

        def _settle(snapshot, *, conn, skip_queue_finish, persist, as_of=None):
            seen.append(
                {
                    "level": int(get_planet_buildings(pid, conn=conn)["metal_mine"]),
                    "as_of": float(as_of),
                    "skip_queue_finish": bool(skip_queue_finish),
                    "persist": bool(persist),
                }
            )
            return snapshot

        monkeypatch.setattr(
            mine_evolution_service,
            "rebuild_production_multiplier_for",
            _rebuild_multiplier,
        )
        monkeypatch.setattr("game.resources.update_planet_resources", _settle)

        completed = finish_planet_build_jobs(conn, pid, uid, now)
        assert completed == 2
        assert len(profile_snapshots) == 2
        assert profile_snapshots[0] is not None
        assert profile_snapshots[0] is profile_snapshots[1]
        assert [row["level"] for row in seen] == [499, 500]
        assert [row["as_of"] for row in seen] == pytest.approx(
            [first_finish, second_finish]
        )
        assert all(row["skip_queue_finish"] is True for row in seen)
        assert all(row["persist"] is True for row in seen)
        assert int(get_planet_buildings(pid, conn=conn)["metal_mine"]) == 501
    finally:
        conn.close()



def test_skill_purchase_settles_old_rank_before_energy_mutation(mevo_db, monkeypatch):
    from game.mine_evolution.nodebuster import get_skills

    uid = mevo_db
    planet = _set_level(uid, "metal_mine", 300)
    pid = int(planet["id"])

    ok, reason, _ = evolve_mine(uid, planet, "metal_mine")
    assert ok, reason

    seen_ranks = []

    def _settle(snapshot, *, conn, skip_queue_finish, persist):
        seen_ranks.append(
            int(get_skills(pid, "metal_mine", conn=conn).get("optimized_energy", 0))
        )
        assert skip_queue_finish is True
        assert persist is True
        return snapshot

    monkeypatch.setattr("game.resources.update_planet_resources", _settle)

    ok, reason, payload = purchase_skill(
        uid,
        planet,
        "metal_mine",
        "optimized_energy",
    )
    assert ok, reason
    assert seen_ranks == [0]
    assert payload["skill_rank"] == 1
    assert get_skills(pid, "metal_mine")["optimized_energy"] == 1
