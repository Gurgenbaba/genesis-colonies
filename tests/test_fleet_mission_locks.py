"""Fleet mission lockdown — live-ops gates for preview/send paths."""

from __future__ import annotations

import time
import uuid

import pytest

from game.db import db
from game.fleet import build_fleet_send_preview, get_planet_ships, send_fleet
from game.fleet_mission_locks import (
    VALID_FLEET_MISSIONS,
    apply_reset_attack_protection,
    get_fleet_mission_locks,
    is_fleet_mission_locked,
    set_fleet_mission_lock,
)
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db


@pytest.fixture
def fleet_lock_db(tmp_path, monkeypatch):
    db_path = tmp_path / "fleet_lock_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


@pytest.fixture()
def admin_env(tmp_path, monkeypatch):
    db_file = tmp_path / "fleet_lock_admin.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    return db_file


@pytest.fixture()
def app_client(admin_env, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import migrate

    migrate.main()

    import importlib
    import app as app_module

    importlib.reload(app_module)

    from game.models import create_user, ensure_player_and_homeworld

    ok_a, _, admin_info = create_user("admin_cc", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("normal_cc", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def _login(client, username, password):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)


def _as_admin(client, admin_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(admin_id)
        sess["is_admin"] = 1


def _as_user(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["is_admin"] = 0


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"lock_user_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Admiral", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _foreign_coords():
    ok, err, user = create_user(f"foreign_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    from game.db import begin_write_transaction, commit

    begin_write_transaction(conn)
    ensure_player_and_homeworld(uid, player_name="Foreign", conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (pid,))
    row = cur.fetchone()
    coords = (int(row["galaxy"]), int(row["system"]), int(row["position"]))
    commit(conn)
    conn.close()
    return coords


def _seed_attack_fleet(conn, uid: int):
    from game.fleet import add_planet_ships

    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE id = ?;",
        (pid,),
    )
    add_planet_ships(pid, uid, {"falcon_interceptor": 10}, conn=conn)
    cur.execute("SELECT * FROM planets WHERE id = ?;", (pid,))
    origin = dict(cur.fetchone())
    conn.commit()
    return pid, origin


def test_all_mission_keys_validate():
    assert VALID_FLEET_MISSIONS == {
        "transport",
        "collect",
        "deploy",
        "spy",
        "attack",
        "hold",
        "expedition",
        "colonize",
        "recycle",
    }


def test_attack_locked_blocks_preview(fleet_lock_db):
    g, s, p = _foreign_coords()
    conn = db()
    uid = _player(conn=conn)
    pid, origin = _seed_attack_fleet(conn, uid)
    set_fleet_mission_lock(
        "attack",
        True,
        locked_until=int(time.time()) + 3600,
        reason="maintenance",
        conn=conn,
    )

    preview = build_fleet_send_preview(
        player_id=uid,
        origin_planet=origin,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"falcon_interceptor": 5},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert preview["can_send"] is False
    assert preview["block_reason"] == "mission_locked"
    assert preview.get("mission_lock", {}).get("locked") is True
    conn.close()


def test_attack_locked_blocks_send_without_mutation(fleet_lock_db):
    g, s, p = _foreign_coords()
    conn = db()
    uid = _player(conn=conn)
    pid, origin = _seed_attack_fleet(conn, uid)
    set_fleet_mission_lock("attack", True, reason="maintenance", conn=conn)

    before_ships = dict(get_planet_ships(pid, conn=conn))
    cur = conn.cursor()
    cur.execute("SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;", (pid,))
    before_res = dict(cur.fetchone())

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"falcon_interceptor": 5},
        conn=conn,
    )
    assert not ok
    assert reason == "mission_locked"
    assert result is None

    after_ships = dict(get_planet_ships(pid, conn=conn))
    cur.execute("SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;", (pid,))
    after_res = dict(cur.fetchone())
    assert after_ships == before_ships
    assert after_res == before_res

    cur.execute("SELECT COUNT(*) AS cnt FROM fleet_movements WHERE player_id = ?;", (uid,))
    assert int(cur.fetchone()["cnt"]) == 0
    conn.close()


def test_expired_lock_no_longer_blocks(fleet_lock_db):
    g, s, p = _foreign_coords()
    conn = db()
    uid = _player(conn=conn)
    pid, origin = _seed_attack_fleet(conn, uid)
    set_fleet_mission_lock(
        "attack",
        True,
        locked_until=int(time.time()) - 60,
        reason="maintenance",
        conn=conn,
    )

    locked, _ = is_fleet_mission_locked("attack", conn=conn)
    assert locked is False

    preview = build_fleet_send_preview(
        player_id=uid,
        origin_planet=origin,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"falcon_interceptor": 5},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert preview["block_reason"] != "mission_locked"
    conn.close()


def test_spy_allowed_while_attack_locked(fleet_lock_db):
    g, s, p = _foreign_coords()
    conn = db()
    uid = _player(conn=conn)
    pid, origin = _seed_attack_fleet(conn, uid)
    from game.fleet import add_planet_ships

    add_planet_ships(pid, uid, {"veil_probe": 5}, conn=conn)
    conn.commit()
    set_fleet_mission_lock("attack", True, reason="maintenance", conn=conn)

    preview = build_fleet_send_preview(
        player_id=uid,
        origin_planet=origin,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="spy",
        ships={"veil_probe": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert preview.get("block_reason") != "mission_locked"
    conn.close()


def test_apply_reset_attack_protection_sets_72h(fleet_lock_db):
    conn = db()
    result = apply_reset_attack_protection(duration_seconds=72 * 3600, conn=conn)
    assert result["locked"] is True
    assert result["reason"] == "reset_protection"
    until = int(result["locked_until"])
    assert until > int(time.time()) + (71 * 3600)
    locked, info = is_fleet_mission_locked("attack", conn=conn)
    assert locked is True
    assert info["reason"] == "reset_protection"
    conn.close()


def test_get_fleet_mission_locks_returns_all_missions(fleet_lock_db):
    locks = get_fleet_mission_locks()
    assert set(locks.keys()) == set(VALID_FLEET_MISSIONS)


def test_fleet_page_context_includes_active_locks(fleet_lock_db):
    from game.fleet import build_fleet_page_context

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("SELECT * FROM planets WHERE id = ?;", (pid,))
    planet = dict(cur.fetchone())
    until = int(time.time()) + 3600
    set_fleet_mission_lock("attack", True, locked_until=until, reason="maintenance", conn=conn)
    ctx = build_fleet_page_context(player_id=uid, planet_id=pid, planet=planet, conn=conn)
    assert ctx.get("ready") is True
    locks = ctx.get("mission_locks") or {}
    assert "attack" in locks
    assert locks["attack"]["locked"] is True
    assert int(locks["attack"]["locked_until"]) == until
    assert "spy" not in locks
    conn.close()


def test_fleet_live_state_includes_mission_locks(fleet_lock_db):
    from game.fleet import get_fleet_live_state

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    set_fleet_mission_lock("transport", True, reason="maintenance", conn=conn)
    state = get_fleet_live_state(player_id=uid, planet_id=pid, conn=conn)
    assert state.get("ready") is True
    locks = state.get("mission_locks") or {}
    assert locks.get("transport", {}).get("locked") is True
    conn.close()


def test_admin_set_lock_writes_audit(app_client):
    client, admin_id, _user_id = app_client
    _as_admin(client, admin_id)

    r = client.post(
        "/api/admin/fleet-mission-locks",
        json={"mission": "attack", "locked": True, "reason": "maintenance"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("ok") is True
    assert data.get("lock", {}).get("locked") is True

    audit = client.get("/api/admin/audit-log?action=fleet_mission_lock_set")
    assert audit.status_code == 200
    entries = audit.get_json().get("entries") or []
    assert any(e.get("action") == "fleet_mission_lock_set" for e in entries)


def test_admin_fleet_locks_forbidden_for_user(app_client):
    client, _admin_id, user_id = app_client
    _as_user(client, user_id)
    r = client.get("/api/admin/fleet-mission-locks")
    assert r.status_code == 403


def test_admin_reset_attack_protection_endpoint(app_client):
    client, admin_id, _user_id = app_client
    _as_admin(client, admin_id)
    r = client.post(
        "/api/admin/fleet-mission-locks/reset-attack-protection",
        json={"duration_hours": 72},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("ok") is True
    assert data.get("attack_protection", {}).get("locked") is True

    audit = client.get("/api/admin/audit-log?action=fleet_attack_protection_set")
    assert audit.status_code == 200
    entries = audit.get_json().get("entries") or []
    assert any(e.get("action") == "fleet_attack_protection_set" for e in entries)
