"""Combat balance bot system — live fleet attacks for balance auditing."""

from __future__ import annotations

import time

import pytest

from game import db as gdb
from game.combat_balance_bots import (
    BOT_ALPHA_USERNAME,
    BOT_BETA_USERNAME,
    COMBAT_BALANCE_SCENARIOS,
    SCENARIO_KEYS,
    advance_scenario_index,
    count_for_budget,
    ensure_combat_balance_bots,
    is_combat_balance_bot_player,
    is_combat_balance_bots_enabled,
    list_combat_balance_results,
    mixed_defense_for_budget,
    resolve_next_scenario_key,
    run_combat_balance_scenario,
    set_combat_balance_bots_enabled,
    ships_for_budget,
    unit_score_cost,
)
from game.db import begin_write_transaction, commit, db
from game.fleet import process_fleet_tick, send_fleet, validate_fleet_send
from game.fleet_defs import ship_score_value
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.ranking import get_sorted_ranking_entries


@pytest.fixture
def bot_db(tmp_path, monkeypatch):
    db_path = tmp_path / "combat_bots.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _admin_client(bot_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import importlib

    import app as app_module

    importlib.reload(app_module)
    ok, _, admin = create_user("cbb_admin", "adminpass123", is_admin=1)
    assert ok
    ok2, _, user = create_user("cbb_normal", "userpass123", is_admin=0)
    assert ok2
    ensure_player_and_homeworld(int(user["id"]))
    client = app_module.app.test_client()
    return client, int(admin["id"]), int(user["id"])


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)


def test_ensure_creates_exactly_two_bots(bot_db):
    conn = db()
    begin_write_transaction(conn)
    payload = ensure_combat_balance_bots(conn=conn)
    commit(conn)
    assert payload["ok"] is True
    alpha_id = int(payload["alpha"]["player_id"])
    beta_id = int(payload["beta"]["player_id"])
    assert alpha_id != beta_id
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM users WHERE username IN (?, ?);",
        (BOT_ALPHA_USERNAME, BOT_BETA_USERNAME),
    )
    assert int(cur.fetchone()["c"]) == 2
    conn.close()


def test_equal_cost_uses_fleet_defs_score(bot_db):
    budget = 220_000
    raptor_cost = unit_score_cost("falcon_interceptor")
    aegis_cost = unit_score_cost("ironclad_frigate")
    assert raptor_cost == ship_score_value("falcon_interceptor")
    assert aegis_cost == ship_score_value("ironclad_frigate")
    raptors = ships_for_budget("falcon_interceptor", budget)["falcon_interceptor"]
    aegis = ships_for_budget("ironclad_frigate", budget)["ironclad_frigate"]
    assert raptors * raptor_cost <= budget
    assert aegis * aegis_cost <= budget
    assert abs(raptors * raptor_cost - aegis * aegis_cost) < max(raptor_cost, aegis_cost)


def test_scenario_creates_real_fleet_movement_with_flight_time(bot_db):
    conn = db()
    begin_write_transaction(conn)
    set_combat_balance_bots_enabled(True, conn=conn)
    ensure_combat_balance_bots(conn=conn)
    result = run_combat_balance_scenario(
        "raptor_vs_aegis_equal_cost",
        conn=conn,
        force=True,
        skip_cooldown=True,
    )
    commit(conn)
    assert result["ok"] is True
    movement_id = int(result["fleet_movement_id"])
    assert movement_id > 0
    assert int(result["flight_seconds"]) > 0
    row = conn.execute(
        "SELECT status, mission_type, flight_seconds, arrival_at, departure_at FROM fleet_movements WHERE id = ?;",
        (movement_id,),
    ).fetchone()
    assert row is not None
    assert row["mission_type"] == "attack"
    assert row["status"] == "outbound"
    assert int(row["flight_seconds"]) > 0
    assert float(row["arrival_at"]) > float(row["departure_at"])
    conn.close()


def test_combat_result_logged_after_arrival(bot_db):
    conn = db()
    begin_write_transaction(conn)
    set_combat_balance_bots_enabled(True, conn=conn)
    ensure_combat_balance_bots(conn=conn)
    result = run_combat_balance_scenario(
        "raptor_vs_aegis_equal_cost",
        conn=conn,
        force=True,
        skip_cooldown=True,
    )
    assert result["ok"] is True
    movement_id = int(result["fleet_movement_id"])
    conn.execute(
        "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
        (time.time() - 1, movement_id),
    )
    commit(conn)
    attacker_id = int(result["attacker_bot_id"])
    process_fleet_tick(player_id=attacker_id, conn=conn)
    commit(conn)
    audit = conn.execute(
        "SELECT resolved_at, winner, rounds FROM combat_balance_runs WHERE fleet_movement_id = ?;",
        (movement_id,),
    ).fetchone()
    assert audit is not None
    assert audit["resolved_at"] is not None
    assert audit["winner"] in ("attacker", "defender", "draw")
    assert int(audit["rounds"] or 0) >= 0
    conn.close()


def _policy_safe_username(prefix: str = "cbb") -> str:
    from game.name_policy import validate_player_name

    for seq in range(1, 1000):
        candidate = f"{prefix}{seq:04d}"
        ok, _ = validate_player_name(candidate)
        if ok:
            return candidate
    raise AssertionError("could not allocate policy-safe username")


def test_bots_only_target_each_other(bot_db):
    conn = db()
    begin_write_transaction(conn)
    bots = ensure_combat_balance_bots(conn=conn)
    commit(conn)
    conn.close()

    ok_u, err, user = create_user(_policy_safe_username("cbbv"), "pass123456", is_admin=0)
    assert ok_u, err
    victim_id = int(user["id"])
    conn = db()
    begin_write_transaction(conn)
    ensure_player_and_homeworld(victim_id, conn=conn)
    alpha_id = int(bots["alpha"]["player_id"])
    beta_coords = bots["beta"]["coords"]
    victim_planets = conn.execute(
        "SELECT id, galaxy, system, position FROM planets WHERE player_id = ? LIMIT 1;",
        (victim_id,),
    ).fetchone()
    from game.fleet import set_planet_ships

    set_planet_ships(
        int(bots["alpha"]["planet_id"]),
        alpha_id,
        {"falcon_interceptor": 5},
        conn=conn,
    )
    ok_bot, reason_bot, _ = validate_fleet_send(
        player_id=alpha_id,
        origin_planet_id=int(bots["alpha"]["planet_id"]),
        target_galaxy=int(beta_coords["galaxy"]),
        target_system=int(beta_coords["system"]),
        target_position=int(beta_coords["position"]),
        mission_type="attack",
        ships={"falcon_interceptor": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    ok_real, reason_real, _ = validate_fleet_send(
        player_id=alpha_id,
        origin_planet_id=int(bots["alpha"]["planet_id"]),
        target_galaxy=int(victim_planets["galaxy"]),
        target_system=int(victim_planets["system"]),
        target_position=int(victim_planets["position"]),
        mission_type="attack",
        ships={"falcon_interceptor": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    commit(conn)
    assert ok_bot is True
    assert ok_real is False
    assert reason_real == "combat_bot_target_forbidden"
    conn.close()


def test_cannot_run_scenario_against_real_player_via_api(bot_db, monkeypatch):
    client, admin_id, user_id = _admin_client(bot_db, monkeypatch)
    _login(client, admin_id)
    conn = db()
    begin_write_transaction(conn)
    ensure_combat_balance_bots(conn=conn)
    commit(conn)
    conn.close()
    _login(client, user_id)
    resp = client.post(
        "/api/admin/combat-bots/run-scenario",
        json={"scenario_key": "raptor_vs_aegis_equal_cost", "force": True},
    )
    assert resp.status_code in (401, 403)


def test_admin_only_api_guard(bot_db, monkeypatch):
    client, admin_id, user_id = _admin_client(bot_db, monkeypatch)
    _login(client, user_id)
    for path, method in (
        ("/api/admin/combat-bots/ensure", "post"),
        ("/api/admin/combat-bots/toggle", "post"),
        ("/api/admin/combat-bots/results", "get"),
    ):
        if method == "post":
            resp = client.post(path, json={})
        else:
            resp = client.get(path)
        assert resp.status_code in (401, 403), path


def test_toggle_works(bot_db, monkeypatch):
    client, admin_id, _user_id = _admin_client(bot_db, monkeypatch)
    _login(client, admin_id)
    conn = db()
    assert is_combat_balance_bots_enabled(conn=conn) is False
    conn.close()
    on = client.post("/api/admin/combat-bots/toggle", json={"enabled": True})
    assert on.status_code == 200
    assert on.get_json().get("enabled") is True
    off = client.post("/api/admin/combat-bots/toggle", json={"enabled": False})
    assert off.status_code == 200
    assert off.get_json().get("enabled") is False


def test_ranking_excludes_combat_bots(bot_db):
    conn = db()
    begin_write_transaction(conn)
    bots = ensure_combat_balance_bots(conn=conn)
    alpha_id = int(bots["alpha"]["player_id"])
    beta_id = int(bots["beta"]["player_id"])
    commit(conn)
    entries = get_sorted_ranking_entries(limit=500, conn=conn)
    ranked_ids = {int(e["player_id"]) for e in entries}
    assert alpha_id not in ranked_ids
    assert beta_id not in ranked_ids
    assert is_combat_balance_bot_player(alpha_id, conn=conn)
    conn.close()


def test_all_scenario_keys_registered(bot_db):
    assert "raptor_vs_aegis_equal_cost" in COMBAT_BALANCE_SCENARIOS
    assert len(COMBAT_BALANCE_SCENARIOS) >= 200
    with_defense = sum(
        1 for sc in COMBAT_BALANCE_SCENARIOS.values() if sc.defender_defense(220_000)
    )
    assert with_defense >= 150
    for key, sc in COMBAT_BALANCE_SCENARIOS.items():
        assert sc.key == key
        preview = sc.attacker_ships(sc.cost_budget)
        assert isinstance(preview, dict)
        def_preview = sc.defender_defense(sc.cost_budget)
        assert isinstance(def_preview, dict)


def test_mixed_defense_for_budget_uses_defense_score(bot_db):
    from game.defense_defs import defense_score_value

    budget = 50_000
    out = mixed_defense_for_budget({"sentinel_turret": 0.5, "plasma_arc": 0.5}, budget)
    assert out.get("sentinel_turret", 0) > 0
    assert out.get("plasma_arc", 0) > 0
    total = sum(
        int(qty) * defense_score_value(str(k))
        for k, qty in out.items()
    )
    assert total <= budget + defense_score_value("plasma_arc")


def test_resolve_next_scenario_key_rotates(bot_db):
    conn = db()
    begin_write_transaction(conn)
    first = resolve_next_scenario_key(conn=conn)
    assert first in SCENARIO_KEYS
    nxt = advance_scenario_index(conn=conn)
    second = resolve_next_scenario_key(conn=conn)
    assert second == SCENARIO_KEYS[(SCENARIO_KEYS.index(first) + 1) % len(SCENARIO_KEYS)]
    conn.rollback()
    conn.close()


def test_run_scenario_disabled_by_default(bot_db):
    conn = db()
    begin_write_transaction(conn)
    ensure_combat_balance_bots(conn=conn)
    result = run_combat_balance_scenario("raptor_vs_aegis_equal_cost", conn=conn)
    commit(conn)
    assert result["ok"] is False
    assert result["error"] == "combat_bots_disabled"
    conn.close()


def test_list_results_after_run(bot_db):
    conn = db()
    begin_write_transaction(conn)
    set_combat_balance_bots_enabled(True, conn=conn)
    ensure_combat_balance_bots(conn=conn)
    run_combat_balance_scenario(
        "raptor_vs_aegis_equal_cost",
        conn=conn,
        force=True,
        skip_cooldown=True,
    )
    commit(conn)
    rows = list_combat_balance_results(conn=conn, limit=5)
    assert len(rows) >= 1
    assert rows[0]["scenario_key"] == "raptor_vs_aegis_equal_cost"
    conn.close()
