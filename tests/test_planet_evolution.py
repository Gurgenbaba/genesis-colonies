"""Tests for Planet Evolution System."""

from __future__ import annotations

import pytest

from game.models import db, create_user, ensure_player_and_homeworld, get_planets_by_player
from game.planet_evolution.bootstrap import backfill_all_planets_evolution, ensure_planet_evolution
from game.planet_evolution.dna import MAX_SQLITE_SIGNED_INT, generate_planet_dna, _stable_seed
from game.planet_evolution.definitions import reload_definitions
from game.planet_evolution.repository import evolution_schema_ready, get_planet_dna, get_locked_choices
from game.planet_evolution.planet_research import queue_planet_research, finish_planet_research_jobs
from game.planet_evolution.service import make_locked_choice, colonize_planet, pick_specialization, upgrade_specialization_tier
from game.planet_evolution.specialization import eligible_specialization_keys, list_specialization_options
from game.planet_evolution.mechanics import compile_planet_mechanics
from game.planet_evolution.repository import save_planet_dna


@pytest.fixture
def evo_db(tmp_path, monkeypatch):
    db_path = tmp_path / "evo_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
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


def _ensure_test_player(player_id: int, *, name: str = "Tester", conn=None) -> int:
    uname = f"pe_user_{player_id}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
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
    a = generate_planet_dna(galaxy=1, system=5, position=3, planet_class="terrestrial")
    b = generate_planet_dna(galaxy=1, system=5, position=3, planet_class="terrestrial")
    assert a["dna_seed"] == b["dna_seed"]
    assert a["geology_traits"] == b["geology_traits"]


def test_planet_class_varies_by_coordinates(evo_db):
    from game.planet_evolution.dna import effective_planet_class, planet_class_for_coordinates

    reload_definitions()
    classes = {
        planet_class_for_coordinates(galaxy=1, system=1, position=pos)
        for pos in range(1, 16)
    }
    assert len(classes) > 1

    stale_row = {
        "galaxy": 1,
        "system": 302,
        "position": 7,
        "planet_class": "terrestrial",
        "dna_seed": 0,
        "is_homeworld": 0,
    }
    assert effective_planet_class(stale_row) == planet_class_for_coordinates(
        galaxy=1, system=302, position=7
    )


def test_dna_seed_fits_sqlite_signed_integer(evo_db):
    reload_definitions()
    salts = ("genesis_colonies_v1", "alt_salt_probe", "")
    for salt in salts:
        for galaxy in range(1, 12):
            for system in range(0, 600, 37):
                for position in range(1, 10):
                    seed = _stable_seed(galaxy, system, position, server_salt=salt)
                    assert 0 <= seed <= MAX_SQLITE_SIGNED_INT
                    dna = generate_planet_dna(
                        galaxy=galaxy,
                        system=system,
                        position=position,
                        server_salt=salt or None,
                    )
                    assert 0 <= int(dna["dna_seed"]) <= MAX_SQLITE_SIGNED_INT


def test_colonize_planet_never_overflows_dna_seed(evo_db):
    uid = _ensure_test_player(901, name="Colonist")
    for attempt in range(8):
        ok, reason, extra = colonize_planet(
            uid,
            name=f"Outpost_{attempt}",
            galaxy=1,
            system=100 + attempt,
            position=1 + (attempt % 8),
        )
        assert ok is True, reason
        conn = db()
        row = conn.execute(
            "SELECT dna_seed FROM planets WHERE id = ?;",
            (int(extra["planet_id"]),),
        ).fetchone()
        conn.close()
        assert 0 <= int(row["dna_seed"]) <= MAX_SQLITE_SIGNED_INT


def test_homeworld_has_dna(evo_db):
    conn = db()
    uid = _ensure_test_player(42, conn=conn)
    planets = get_planets_by_player(uid, conn=conn)
    assert planets
    pid = int(planets[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.commit()
    dna = get_planet_dna(pid, conn=conn)
    assert dna is not None
    assert dna.get("rarity_tier") in ("common", "uncommon", "rare", "epic", "legendary")
    conn.close()


def test_ensure_planet_evolution_skips_writes_when_bootstrapped(evo_db):
    import re

    from game.planet_evolution.bootstrap import planet_evolution_needs_bootstrap

    conn = db()
    uid = _ensure_test_player(43, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.commit()
    assert planet_evolution_needs_bootstrap(pid, conn) is False

    root_write = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)
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

    assert result.get("ready") is True
    assert result.get("dna_created") is False
    assert writes == [], f"unexpected writes on bootstrapped planet: {writes}"


def test_locked_choice_exclusive(evo_db):
    conn = db()
    uid = _ensure_test_player(7, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.commit()

    ok, reason = make_locked_choice(pid, "mining_path", "deep_core", uid, conn=conn)
    assert ok is True
    choices = get_locked_choices(pid, conn=conn)
    assert choices.get("mining_path") == "deep_core"

    ok2, _reason2 = make_locked_choice(pid, "mining_path", "orbital_mining", uid, conn=conn)
    assert ok2 is False
    conn.close()


def test_planet_research_queue(evo_db):
    conn = db()
    uid = _ensure_test_player(9, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;", (pid,))
    cur.execute("UPDATE planet_buildings SET research_lab = 5 WHERE planet_id = ?;", (pid,))
    conn.commit()

    ok, reason, extra = queue_planet_research(
        pid,
        "industry_t1_automation",
        player_id=uid,
        conn=conn,
    )
    assert ok is True, reason
    assert extra and extra.get("job_id")

    import time

    n = finish_planet_research_jobs(conn, pid, time.time() + 99999)
    assert n >= 1
    conn.close()


def test_colonize_second_planet(evo_db):
    uid = _ensure_test_player(11, name="Colonizer")
    ok, reason, extra = colonize_planet(uid, name="Outpost Beta", galaxy=1, system=200, position=4)
    assert ok is True, reason
    conn = db()
    planets = get_planets_by_player(uid, conn=conn)
    conn.close()
    assert len(planets) >= 1


def _forge_world_dna():
    return {
        "rarity_tier": "uncommon",
        "geology_traits": ["ferronit_rich_crust", "deep_core_pressure"],
        "atmosphere_traits": [],
        "environment_traits": ["unstable_mantle"],
        "anomaly_traits": [],
        "hidden_traits": [],
        "affinity_scores": {"industry": 70, "science": 10, "trade": 10},
        "risk_profile": {},
        "resource_potential": {},
    }


def test_api_spec_pick_route(evo_db):
    """Regression: API route must unpack 3-tuple from pick_specialization."""
    conn = db()
    uid = _ensure_test_player(31, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    cur = conn.cursor()
    cur.execute("UPDATE planets SET planet_level = 8, dna_reveal_tier = 2 WHERE id = ?;", (pid,))
    save_planet_dna(pid, _forge_world_dna(), conn)
    conn.commit()
    conn.close()

    from app import app

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = uid
        r = client.post(f"/api/planets/{pid}/specialization/pick", json={"spec_key": "forge_world"})
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data.get("ok") is True, data.get("reason")


def test_policy_activate_route(evo_db):
    conn = db()
    uid = _ensure_test_player(33, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    cur = conn.cursor()
    cur.execute("UPDATE planets SET planet_level = 8 WHERE id = ?;", (pid,))
    cur.execute(
        """
        UPDATE planet_culture SET archetype_key = 'scientific_collective'
        WHERE planet_id = ?;
        """,
        (pid,),
    )
    conn.commit()
    conn.close()

    from app import app

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = uid
        r = client.post(
            f"/api/planets/{pid}/policies/activate",
            json={"slot": 1, "policy_key": "research_mandate"},
        )
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data.get("ok") is True, data.get("reason")


def test_specialization_pick_and_tier_upgrade(evo_db):
    conn = db()
    uid = _ensure_test_player(21, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    cur = conn.cursor()
    cur.execute("UPDATE planets SET planet_level = 8, dna_reveal_tier = 2 WHERE id = ?;", (pid,))
    save_planet_dna(pid, _forge_world_dna(), conn)
    conn.commit()

    eligible = eligible_specialization_keys(pid, conn)
    assert "forge_world" in eligible

    options = list_specialization_options(pid, conn)
    forge = next(o for o in options if o["spec_key"] == "forge_world")
    assert forge["eligible"] is True
    assert forge["synergy_score"] >= 10

    ok, reason, extra = pick_specialization(pid, "forge_world", uid, conn=conn)
    assert ok is True, reason
    assert extra and extra.get("tier") == 1

    mech = compile_planet_mechanics(pid, conn)
    assert "refined_ferronit" in mech.get("export_slots", [])
    assert "mantle_alloy" not in [u.split(":")[-1] for u in mech.get("unlocks", []) if u.startswith("chain:")]

    cur.execute("UPDATE planets SET planet_level = 14 WHERE id = ?;", (pid,))
    conn.commit()
    ok2, reason2, extra2 = upgrade_specialization_tier(pid, uid, conn=conn)
    assert ok2 is True, reason2
    assert extra2 and extra2.get("tier") == 2

    mech2 = compile_planet_mechanics(pid, conn)
    chain_unlocks = [u for u in mech2.get("unlocks", []) if "mantle_alloy" in u]
    assert chain_unlocks
    conn.close()
