"""Tests for Planet Evolution System."""
from __future__ import annotations
import pytest
from game.models import db, create_user, ensure_player_and_homeworld, get_planets_by_player
from game.planet_evolution.bootstrap import backfill_all_planets_evolution, ensure_planet_evolution
from game.planet_evolution.dna import MAX_SQLITE_SIGNED_INT, generate_planet_dna, _stable_seed
from game.planet_evolution.definitions import reload_definitions
from game.planet_evolution.repository import (
    evolution_schema_ready,
    get_planet_dna,
    get_locked_choices,
    get_planet_mechanics,
    save_planet_mechanics,
    save_planet_dna,
)
from game.planet_evolution.economy import ensure_special_resource_row, tick_special_resources
from game.planet_evolution.mechanics import compile_planet_mechanics, get_flag
from game.planet_evolution.requirements import check_requirements
from game.planet_evolution.planet_research import (
    compute_planet_research_reward_xp,
    compute_planet_research_time,
    queue_planet_research,
    finish_planet_research_jobs,
    get_planet_research_status,
)
from game.planet_evolution.service import (
    activate_policy,
    colonize_planet,
    make_locked_choice,
    pick_specialization,
    upgrade_specialization_tier,
)
from game.planet_evolution.specialization import eligible_specialization_keys, list_specialization_options
from game.planet_evolution.dashboard import _policy_ux
from game.planet_evolution.policies import policies_requiring_explicit_unlock
from game.planet_evolution.repository import get_planet_culture, get_planet_row

@pytest.fixture
def evo_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'evo_test.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_path))
    from game import db as gdb
    gdb._DB_PATH = None
    from game.models import init_db
    init_db()
    import migrate
    migrate.main()
    conn = db()
    reload_definitions(conn)
    backfill_all_planets_evolution(conn)
    conn.commit()
    conn.close()
    yield
    gdb._DB_PATH = None

def _ensure_test_player(player_id: int, *, name: str='Tester', conn=None) -> int:
    uname = f'pe_user_{player_id}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok, err
    uid = int(user['id'])
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return uid

def test_evolution_schema_ready(evo_db):
    conn = db()
    assert evolution_schema_ready(conn) is True
    conn.close()

def test_dna_deterministic(evo_db):
    reload_definitions()
    a = generate_planet_dna(galaxy=1, system=5, position=3, planet_class='terrestrial')
    b = generate_planet_dna(galaxy=1, system=5, position=3, planet_class='terrestrial')
    assert a['dna_seed'] == b['dna_seed']
    assert a['geology_traits'] == b['geology_traits']

def test_planet_class_varies_by_coordinates(evo_db):
    from game.planet_evolution.dna import effective_planet_class, planet_class_for_coordinates
    reload_definitions()
    classes = {planet_class_for_coordinates(galaxy=1, system=1, position=pos) for pos in range(1, 16)}
    assert len(classes) > 1
    stale_row = {'galaxy': 1, 'system': 302, 'position': 7, 'planet_class': 'terrestrial', 'dna_seed': 0, 'is_homeworld': 0}
    assert effective_planet_class(stale_row) == planet_class_for_coordinates(galaxy=1, system=302, position=7)

def test_dna_seed_fits_sqlite_signed_integer(evo_db):
    reload_definitions()
    salts = ('genesis_colonies_v1', 'alt_salt_probe', '')
    for salt in salts:
        for galaxy in range(1, 12):
            for system in range(0, 600, 37):
                for position in range(1, 10):
                    seed = _stable_seed(galaxy, system, position, server_salt=salt)
                    assert 0 <= seed <= MAX_SQLITE_SIGNED_INT
                    dna = generate_planet_dna(galaxy=galaxy, system=system, position=position, server_salt=salt or None)
                    assert 0 <= int(dna['dna_seed']) <= MAX_SQLITE_SIGNED_INT

def test_colonize_planet_never_overflows_dna_seed(evo_db):
    uid = _ensure_test_player(901, name='Colonist')
    for attempt in range(8):
        ok, reason, extra = colonize_planet(uid, name=f'Outpost_{attempt}', galaxy=1, system=100 + attempt, position=1 + attempt % 8, allow_legacy_coordinates=True, source='test')
        assert ok is True, reason
        conn = db()
        row = conn.execute('SELECT dna_seed FROM planets WHERE id = ?;', (int(extra['planet_id']),)).fetchone()
        conn.close()
        assert 0 <= int(row['dna_seed']) <= MAX_SQLITE_SIGNED_INT

def test_homeworld_has_dna(evo_db):
    conn = db()
    uid = _ensure_test_player(42, conn=conn)
    planets = get_planets_by_player(uid, conn=conn)
    assert planets
    pid = int(planets[0]['id'])
    ensure_planet_evolution(pid, conn)
    conn.commit()
    dna = get_planet_dna(pid, conn=conn)
    assert dna is not None
    assert dna.get('rarity_tier') in ('common', 'uncommon', 'rare', 'epic', 'legendary')
    conn.close()

def test_ensure_planet_evolution_skips_writes_when_bootstrapped(evo_db):
    import re
    from game.planet_evolution.bootstrap import planet_evolution_needs_bootstrap
    conn = db()
    uid = _ensure_test_player(43, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    conn.commit()
    assert planet_evolution_needs_bootstrap(pid, conn) is False
    root_write = re.compile('^\\s*(INSERT|UPDATE|DELETE|REPLACE)\\b', re.IGNORECASE)
    writes: list[str] = []

    def trace(stmt: str) -> None:
        if root_write.match(stmt):
            writes.append(stmt.strip().split()[0].upper())
    conn.set_trace_callback(trace)
    try:
        result = ensure_planet_evolution(pid, conn)
    finally:
        conn.set_trace_callback(None)
        conn.close()
    assert result.get('ready') is True
    assert result.get('dna_created') is False
    assert writes == [], f'unexpected writes on bootstrapped planet: {writes}'

def _set_planet_research_level(conn, planet_id: int, tech_key: str, level: int = 1) -> None:
    conn.execute(
        """
        INSERT INTO planet_research_levels (planet_id, tech_key, level, unlocked_at)
        VALUES (?, ?, ?, strftime('%s','now'))
        ON CONFLICT(planet_id, tech_key) DO UPDATE SET
            level = excluded.level,
            unlocked_at = COALESCE(planet_research_levels.unlocked_at, excluded.unlocked_at);
        """,
        (int(planet_id), str(tech_key), int(level)),
    )


def _activate_production_chain(conn, planet_id: int, chain_key: str) -> None:
    conn.execute(
        """
        INSERT INTO planet_production_chains (planet_id, chain_key, building_key, is_active, efficiency, last_tick_at)
        VALUES (?, ?, 'virtual', 1, 1.0, strftime('%s','now'))
        ON CONFLICT(planet_id, chain_key) DO UPDATE SET is_active = 1, efficiency = 1.0;
        """,
        (int(planet_id), str(chain_key)),
    )


def _merge_planet_mechanic_flags(conn, planet_id: int, flags: dict) -> None:
    mech = get_planet_mechanics(planet_id, conn=conn)
    merged = dict(mech.get("flags") or {})
    merged.update(flags)
    mech["flags"] = merged
    save_planet_mechanics(planet_id, mech, conn)


def _tick_chain_output(conn, planet_id: int) -> dict:
    result = tick_special_resources(planet_id, 1.0, conn)
    return dict(result.get("produced") or {})


def test_planet_research_any_requirement_or_logic(evo_db):
    conn = db()
    uid = _ensure_test_player(9721, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.commit()

    req = {"planet_research_any": ["industry_t3_orbital_refinery", "industry_t3_mantle_tap"]}
    ok, missing = check_requirements(pid, req, conn)
    assert ok is False
    assert any("planet_research_any" in m for m in missing)

    _set_planet_research_level(conn, pid, "industry_t3_orbital_refinery")
    conn.commit()
    ok, missing = check_requirements(pid, req, conn)
    assert ok is True
    assert missing == []

    conn.execute("DELETE FROM planet_research_levels WHERE planet_id = ?;", (pid,))
    _set_planet_research_level(conn, pid, "industry_t3_mantle_tap")
    conn.commit()
    ok, missing = check_requirements(pid, req, conn)
    assert ok is True
    assert missing == []

    ok_both, missing_both = check_requirements(
        pid,
        {
            "planet_research": {"industry_t3_orbital_refinery": 1, "industry_t3_mantle_tap": 1},
        },
        conn,
    )
    assert ok_both is False
    assert missing_both
    conn.close()


@pytest.mark.parametrize(
    "t3_tech",
    ["industry_t3_orbital_refinery", "industry_t3_mantle_tap"],
)
def test_industry_t4_queueable_with_single_industry_t3(evo_db, t3_tech):
    conn = db()
    uid = _ensure_test_player(9722 if t3_tech.endswith("orbital") else 9723, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;", (pid,))
    _set_planet_research_level(conn, pid, t3_tech)
    conn.commit()

    ok, reason, extra = queue_planet_research(pid, "industry_t4_mass_foundry", player_id=uid, conn=conn)
    assert ok is True, reason
    assert extra and extra.get("job_id")

    status = get_planet_research_status(pid, conn=conn)
    t4 = next(t for t in status["techs"] if t["tech_key"] == "industry_t4_mass_foundry")
    assert t4["requirements_met"] is True
    conn.close()


def test_industry_t4_blocked_without_industry_t3(evo_db):
    conn = db()
    uid = _ensure_test_player(9724, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;", (pid,))
    conn.commit()

    ok, reason, extra = queue_planet_research(pid, "industry_t4_mass_foundry", player_id=uid, conn=conn)
    assert ok is False
    assert reason == "requirements"
    assert extra and any("planet_research_any" in m for m in extra.get("missing", []))
    conn.close()


def test_chain_output_bonus_absent_unchanged(evo_db):
    conn = db()
    uid = _ensure_test_player(9725, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;", (pid,))
    _activate_production_chain(conn, pid, "refined_ferronit")
    ensure_special_resource_row(pid, "refined_ferronit", conn)
    conn.commit()

    produced = _tick_chain_output(conn, pid)
    assert produced.get("refined_ferronit") == pytest.approx(120.0)
    conn.close()


def test_chain_output_bonus_per_chain_from_compiled_mechanics(evo_db):
    conn = db()
    uid = _ensure_test_player(9726, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;", (pid,))
    _activate_production_chain(conn, pid, "refined_ferronit")
    _activate_production_chain(conn, pid, "mantle_alloy")
    ensure_special_resource_row(pid, "refined_ferronit", conn)
    ensure_special_resource_row(pid, "mantle_alloy", conn)
    _merge_planet_mechanic_flags(
        conn,
        pid,
        {"chain_output_bonus": {"refined_ferronit": 0.20}},
    )
    conn.commit()

    produced = _tick_chain_output(conn, pid)
    assert produced.get("refined_ferronit") == pytest.approx(144.0)
    assert produced.get("mantle_alloy") == pytest.approx(60.0)
    conn.close()


def test_chain_output_bonus_scalar_applies_to_all_chains(evo_db):
    conn = db()
    uid = _ensure_test_player(9727, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;", (pid,))
    _activate_production_chain(conn, pid, "refined_ferronit")
    ensure_special_resource_row(pid, "refined_ferronit", conn)
    _merge_planet_mechanic_flags(conn, pid, {"chain_output_bonus": 0.20})
    conn.commit()

    produced = _tick_chain_output(conn, pid)
    assert produced.get("refined_ferronit") == pytest.approx(144.0)
    conn.close()


def test_orbital_t2_compile_chain_output_bonus(evo_db):
    conn = db()
    uid = _ensure_test_player(9728, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    _set_planet_research_level(conn, pid, "orbital_t2_zero_g_foundry")
    compile_planet_mechanics(pid, conn)
    assert get_flag(pid, "chain_output_bonus", conn=conn) == {"refined_ferronit": 0.15}

    conn.execute("UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;", (pid,))
    _activate_production_chain(conn, pid, "refined_ferronit")
    ensure_special_resource_row(pid, "refined_ferronit", conn)
    conn.commit()

    produced = _tick_chain_output(conn, pid)
    assert produced.get("refined_ferronit") == pytest.approx(138.0)
    conn.close()


def _policy_option(policy_ux: dict, slot: int, policy_key: str) -> dict | None:
    for slot_row in policy_ux.get("slots") or []:
        if int(slot_row["slot"]) == int(slot):
            for opt in slot_row.get("options") or []:
                if opt["policy_key"] == policy_key:
                    return opt
    return None


def _prep_policy_planet(
    conn,
    uid: int,
    *,
    level: int = 10,
    archetype: str = "industrial_union_state",
) -> int:
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET planet_level = ? WHERE id = ?;", (int(level), pid))
    conn.execute(
        "UPDATE planet_culture SET archetype_key = ? WHERE planet_id = ?;",
        (str(archetype), pid),
    )
    return pid


def test_policies_requiring_explicit_unlock_includes_mandatory_overtime(evo_db):
    assert "mandatory_overtime" in policies_requiring_explicit_unlock()


def test_mandatory_overtime_blocked_without_policy_unlock(evo_db):
    conn = db()
    uid = _ensure_test_player(9730, conn=conn)
    pid = _prep_policy_planet(conn, uid, level=10, archetype="industrial_union_state")
    conn.commit()

    ok, reason = activate_policy(pid, 2, "mandatory_overtime", uid, conn=conn)
    assert ok is False
    assert reason == "policy_locked"

    culture = get_planet_culture(pid, conn=conn)
    planet = get_planet_row(pid, conn=conn) or {}
    policy_ux = _policy_ux(pid, planet=planet, culture=culture, conn=conn)
    opt = _policy_option(policy_ux, 2, "mandatory_overtime")
    assert opt is not None
    assert opt["eligible"] is False
    assert opt["locked_reason_key"] == "pe_policy_locked_by_research"

    conn.execute(
        "UPDATE planet_culture SET archetype_key = 'scientific_collective' WHERE planet_id = ?;",
        (pid,),
    )
    conn.commit()
    ok_open, reason_open = activate_policy(pid, 1, "research_mandate", uid, conn=conn)
    assert ok_open is True, reason_open
    conn.close()


def test_mandatory_overtime_allowed_with_policy_unlock_flag(evo_db):
    conn = db()
    uid = _ensure_test_player(9731, conn=conn)
    pid = _prep_policy_planet(conn, uid, level=10, archetype="industrial_union_state")
    _merge_planet_mechanic_flags(conn, pid, {"policy_unlock:mandatory_overtime": True})
    conn.commit()

    culture = get_planet_culture(pid, conn=conn)
    planet = get_planet_row(pid, conn=conn) or {}
    policy_ux = _policy_ux(pid, planet=planet, culture=culture, conn=conn)
    opt = _policy_option(policy_ux, 2, "mandatory_overtime")
    assert opt is not None
    assert opt["eligible"] is True
    assert opt["locked_reason_key"] is None

    ok, reason = activate_policy(pid, 2, "mandatory_overtime", uid, conn=conn)
    assert ok is True, reason
    conn.close()


def test_mandatory_overtime_allowed_after_industry_t5_compile(evo_db):
    conn = db()
    uid = _ensure_test_player(9732, conn=conn)
    pid = _prep_policy_planet(conn, uid, level=18, archetype="industrial_union_state")
    _set_planet_research_level(conn, pid, "industry_t5_overdrive")
    compile_planet_mechanics(pid, conn)
    assert get_flag(pid, "policy_unlock:mandatory_overtime", conn=conn) is True
    conn.commit()

    ok, reason = activate_policy(pid, 2, "mandatory_overtime", uid, conn=conn)
    assert ok is True, reason
    conn.close()


def test_policy_tier_blocks_high_tier_policies_after_governance_t1(evo_db):
    conn = db()
    uid = _ensure_test_player(9733, conn=conn)
    pid = _prep_policy_planet(conn, uid, level=10, archetype="militarized_society")
    _set_planet_research_level(conn, pid, "governance_t1_civil_admin")
    compile_planet_mechanics(pid, conn)
    assert get_flag(pid, "policy_tier", conn=conn) == 1
    conn.commit()

    culture = get_planet_culture(pid, conn=conn)
    planet = get_planet_row(pid, conn=conn) or {}
    policy_ux = _policy_ux(pid, planet=planet, culture=culture, conn=conn)
    martial = _policy_option(policy_ux, 2, "martial_law")
    assert martial is not None
    assert martial["eligible"] is False
    assert martial["locked_reason_key"] == "pe_policy_tier_locked"

    ok, reason = activate_policy(pid, 2, "martial_law", uid, conn=conn)
    assert ok is False
    assert reason == "policy_tier_locked"

    conn.execute(
        "UPDATE planet_culture SET archetype_key = 'scientific_collective' WHERE planet_id = ?;",
        (pid,),
    )
    conn.commit()
    culture = get_planet_culture(pid, conn=conn)
    policy_ux = _policy_ux(pid, planet=planet, culture=culture, conn=conn)
    research = _policy_option(policy_ux, 1, "research_mandate")
    assert research is not None
    assert research["eligible"] is True
    conn.close()


def test_policy_tier_absent_keeps_tier2_policies_available(evo_db):
    conn = db()
    uid = _ensure_test_player(9734, conn=conn)
    pid = _prep_policy_planet(conn, uid, level=10, archetype="militarized_society")
    conn.commit()

    culture = get_planet_culture(pid, conn=conn)
    planet = get_planet_row(pid, conn=conn) or {}
    policy_ux = _policy_ux(pid, planet=planet, culture=culture, conn=conn)
    martial = _policy_option(policy_ux, 2, "martial_law")
    assert martial is not None
    assert martial["eligible"] is True
    assert martial["locked_reason_key"] is None

    ok, reason = activate_policy(pid, 2, "martial_law", uid, conn=conn)
    assert ok is True, reason
    conn.close()


def test_locked_choice_exclusive(evo_db):
    conn = db()
    uid = _ensure_test_player(7, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    conn.commit()
    ok, reason = make_locked_choice(pid, 'mining_path', 'deep_core', uid, conn=conn)
    assert ok is True
    choices = get_locked_choices(pid, conn=conn)
    assert choices.get('mining_path') == 'deep_core'
    ok2, _reason2 = make_locked_choice(pid, 'mining_path', 'orbital_mining', uid, conn=conn)
    assert ok2 is False
    conn.close()

def test_planet_research_queue(evo_db):
    conn = db()
    uid = _ensure_test_player(9, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planet_buildings SET research_lab = 5 WHERE planet_id = ?;', (pid,))
    conn.commit()
    ok, reason, extra = queue_planet_research(pid, 'industry_t1_automation', player_id=uid, conn=conn)
    assert ok is True, reason
    assert extra and extra.get('job_id')
    import time
    n = finish_planet_research_jobs(conn, pid, time.time() + 99999)
    assert n >= 1
    conn.close()

def test_compute_planet_research_reward_xp_uses_canonical_formula():
    t1 = compute_planet_research_reward_xp("industry_t1_automation")
    assert t1["reward_xp"] == 40
    assert t1["reward_xp_base"] == 25
    assert t1["reward_xp_tier_bonus"] == 15
    assert t1["reward_tier"] == 1

    t3 = compute_planet_research_reward_xp("industry_t3_orbital_refinery")
    assert t3["reward_xp"] == 70
    assert t3["reward_xp_tier_bonus"] == 45
    assert t3["reward_tier"] == 3

def test_planet_research_time_has_only_small_safety_floor(evo_db):
    """
    GC-622B / Zusatz: No 30s balancing floor.
    Even at extreme planet_research_speed, duration must not clamp to 30s.
    """
    conn = db()
    uid = _ensure_test_player(99, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    conn.execute("INSERT INTO game_settings (key, value) VALUES ('planet_research_speed', '10000') ON CONFLICT(key) DO UPDATE SET value = excluded.value;")
    conn.commit()
    duration = float(compute_planet_research_time(pid, 'industry_t1_automation', 3, conn=conn))
    assert duration >= 1.0
    assert duration < 30.0
    conn.close()

def test_colonize_second_planet(evo_db):
    uid = _ensure_test_player(11, name='Colonizer')
    ok, reason, extra = colonize_planet(uid, name='Outpost Beta', galaxy=1, system=200, position=4, allow_legacy_coordinates=True, source='test')
    assert ok is True, reason
    conn = db()
    planets = get_planets_by_player(uid, conn=conn)
    conn.close()
    assert len(planets) >= 1

def _forge_world_dna():
    return {'rarity_tier': 'uncommon', 'geology_traits': ['ferronit_rich_crust', 'deep_core_pressure'], 'atmosphere_traits': [], 'environment_traits': ['unstable_mantle'], 'anomaly_traits': [], 'hidden_traits': [], 'affinity_scores': {'industry': 70, 'science': 10, 'trade': 10}, 'risk_profile': {}, 'resource_potential': {}}

def test_api_spec_pick_route(evo_db):
    """Regression: API route must unpack 3-tuple from pick_specialization."""
    conn = db()
    uid = _ensure_test_player(31, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET planet_level = 8, dna_reveal_tier = 2 WHERE id = ?;', (pid,))
    save_planet_dna(pid, _forge_world_dna(), conn)
    conn.commit()
    conn.close()
    from app import app
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
        r = client.post(f'/api/planets/{pid}/specialization/pick', json={'spec_key': 'forge_world'})
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data.get('ok') is True, data.get('reason')

def test_policy_activate_route(evo_db):
    conn = db()
    uid = _ensure_test_player(33, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET planet_level = 8 WHERE id = ?;', (pid,))
    cur.execute("\n        UPDATE planet_culture SET archetype_key = 'scientific_collective'\n        WHERE planet_id = ?;\n        ", (pid,))
    conn.commit()
    conn.close()
    from app import app
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
        r = client.post(f'/api/planets/{pid}/policies/activate', json={'slot': 1, 'policy_key': 'research_mandate'})
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data.get('ok') is True, data.get('reason')

def test_specialization_pick_and_tier_upgrade(evo_db):
    conn = db()
    uid = _ensure_test_player(21, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET planet_level = 8, dna_reveal_tier = 2 WHERE id = ?;', (pid,))
    save_planet_dna(pid, _forge_world_dna(), conn)
    conn.commit()
    eligible = eligible_specialization_keys(pid, conn)
    assert 'forge_world' in eligible
    options = list_specialization_options(pid, conn)
    forge = next((o for o in options if o['spec_key'] == 'forge_world'))
    assert forge['eligible'] is True
    assert forge['synergy_score'] >= 10
    ok, reason, extra = pick_specialization(pid, 'forge_world', uid, conn=conn)
    assert ok is True, reason
    assert extra and extra.get('tier') == 1
    mech = compile_planet_mechanics(pid, conn)
    assert 'refined_ferronit' in mech.get('export_slots', [])
    assert 'mantle_alloy' not in [u.split(':')[-1] for u in mech.get('unlocks', []) if u.startswith('chain:')]
    cur.execute('UPDATE planets SET planet_level = 14 WHERE id = ?;', (pid,))
    conn.commit()
    ok2, reason2, extra2 = upgrade_specialization_tier(pid, uid, conn=conn)
    assert ok2 is True, reason2
    assert extra2 and extra2.get('tier') == 2
    mech2 = compile_planet_mechanics(pid, conn)
    chain_unlocks = [u for u in mech2.get('unlocks', []) if 'mantle_alloy' in u]
    assert chain_unlocks
    conn.close()


def test_enable_event_pool_compiled_from_research_mechanics(evo_db):
    conn = db()
    uid = _ensure_test_player(972, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    conn.execute(
        """
        INSERT INTO planet_research_levels (planet_id, tech_key, level)
        VALUES (?, 'science_t3_breakthrough_lab', 1)
        ON CONFLICT(planet_id, tech_key) DO UPDATE SET level = 1;
        """,
        (pid,),
    )
    conn.commit()
    compile_planet_mechanics(pid, conn)
    assert get_flag(pid, 'event_pool:science_breakthrough', conn=conn) is True
    conn.close()


def test_event_pool_helpers_gate_by_unlocked_pool():
    from game.planet_evolution.events import (
        event_allowed_by_pool_tags,
        event_belongs_to_pool,
        unlocked_event_pool_names,
    )

    flags = {'event_pool:science_breakthrough': True, 'trait_keys': []}
    assert unlocked_event_pool_names(flags) == {'science_breakthrough'}
    assert event_belongs_to_pool('science_breakthrough', 'science_breakthrough', ['spec:science_nexus'])
    assert event_belongs_to_pool('smuggler_authority_raid', 'smuggler', ['spec:smuggler_colony'])

    assert event_allowed_by_pool_tags(
        'science_breakthrough',
        ['spec:science_nexus'],
        specialization_key='forge_world',
        unlocked_pools={'science_breakthrough'},
    )
    assert not event_allowed_by_pool_tags(
        'science_breakthrough',
        ['spec:science_nexus'],
        specialization_key='forge_world',
        unlocked_pools=set(),
    )
    assert event_allowed_by_pool_tags(
        'smuggler_black_market_boom',
        ['spec:smuggler_colony'],
        specialization_key='forge_world',
        unlocked_pools={'smuggler'},
    )
    assert not event_allowed_by_pool_tags(
        'smuggler_black_market_boom',
        ['spec:smuggler_colony'],
        specialization_key='forge_world',
        unlocked_pools=set(),
    )
    assert event_allowed_by_pool_tags(
        'trade_route_disruption',
        [],
        specialization_key='forge_world',
        unlocked_pools=set(),
    )


def test_pick_event_key_respects_event_pool_flag(evo_db):
    from game.planet_evolution.events import PlanetEventEngine, _stable_roll

    conn = db()
    uid = _ensure_test_player(973, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ensure_planet_evolution(pid, conn)
    conn.execute(
        "UPDATE planets SET specialization_key = 'forge_world' WHERE id = ?;",
        (pid,),
    )
    conn.execute(
        """
        INSERT INTO planet_research_levels (planet_id, tech_key, level)
        VALUES (?, 'science_t3_breakthrough_lab', 1)
        ON CONFLICT(planet_id, tech_key) DO UPDATE SET level = 1;
        """,
        (pid,),
    )
    conn.commit()
    compile_planet_mechanics(pid, conn)
    planet = get_planet_row(pid, conn=conn) or {}

    roll_day = next(
        (day for day in range(4000) if _stable_roll(pid, 'science_breakthrough', day) < 0.03),
        None,
    )
    assert roll_day is not None
    key = PlanetEventEngine._pick_event_key(pid, planet, conn, float(roll_day * 86400))
    assert key == 'science_breakthrough'

    conn.execute(
        "DELETE FROM planet_research_levels WHERE planet_id = ? AND tech_key = 'science_t3_breakthrough_lab';",
        (pid,),
    )
    conn.commit()
    compile_planet_mechanics(pid, conn)
    assert get_flag(pid, 'event_pool:science_breakthrough', conn=conn) in (None, False)

    key_without_pool = PlanetEventEngine._pick_event_key(pid, planet, conn, float(roll_day * 86400))
    assert key_without_pool != 'science_breakthrough'
    conn.close()
