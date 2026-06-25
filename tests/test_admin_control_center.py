"""
Admin Control Center API tests.

Run: python -m pytest tests/test_admin_control_center.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def admin_env(tmp_path, monkeypatch):
    db_file = tmp_path / "admin_test.db"
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

    from game.models import create_user, db, ensure_player_and_homeworld

    ok_a, _, admin_info = create_user("admin_cc", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("normal_cc", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def _login(client, username, password):
    from game.models import db, verify_user

    user = verify_user(str(username), str(password))
    if user:
        with client.session_transaction() as sess:
            sess["user_id"] = int(user["id"])
        return user

    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def _as_user(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)


def _as_admin(client, admin_id: int) -> None:
    _as_user(client, admin_id)


def test_api_admin_requires_login(app_client):
    client, _, _ = app_client
    r = client.get("/api/admin/health")
    assert r.status_code == 401
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "not_logged_in"


def test_api_admin_forbidden_for_normal_user(app_client):
    client, _, _ = app_client
    _login(client, "normal_cc", "userpass123")
    r = client.get("/api/admin/health")
    assert r.status_code == 403
    assert r.get_json()["error"] == "forbidden"


def test_api_admin_health_ok_for_admin(app_client):
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.get("/api/admin/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "health" in data
    assert "checks" in data["health"]


def test_player_search_works(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.get(f"/api/admin/players?q={user_id}")
    assert r.status_code == 200
    players = r.get_json()["players"]
    assert any(int(p["id"]) == user_id for p in players)


def test_resources_set_clamps_negative(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.post(
        f"/api/admin/player/{user_id}/resources",
        json={"mode": "set", "metal": -5000, "crystal": -100},
    )
    assert r.status_code == 200
    hw = r.get_json()["homeworld"]
    assert float(hw["metal"]) >= 0
    assert float(hw["crystal"]) >= 0


def test_queue_cancel_writes_audit_log(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")

    from game.models import db, get_homeworld
    import time

    hw = get_homeworld(user_id)
    planet_id = int(hw["id"])
    conn = db()
    conn.execute(
        "INSERT INTO build_queue (planet_id, building_type, start_time, finish_time) VALUES (?, ?, ?, ?);",
        (planet_id, "metal_mine", time.time(), time.time() + 3600),
    )
    conn.commit()
    job_id = conn.execute("SELECT id FROM build_queue ORDER BY id DESC LIMIT 1;").fetchone()["id"]
    conn.close()

    r = client.post(f"/api/admin/queue/build/{job_id}/cancel", json={})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    audit = client.get("/api/admin/audit-log?action=queue_cancel")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(e["action"] == "queue_cancel" for e in entries)


def test_destructive_action_without_confirm_rejected(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.post(
        f"/api/admin/player/{user_id}/ban",
        json={"reason": "test", "hours": 1},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "confirm_required"


def test_audit_log_admin_only(app_client):
    client, _, _ = app_client
    _login(client, "normal_cc", "userpass123")
    r = client.get("/api/admin/audit-log")
    assert r.status_code == 403


def test_search_no_sql_injection(app_client):
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")
    payload = "' OR 1=1; DROP TABLE users; --"
    r = client.get(f"/api/admin/players?q={payload}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert isinstance(data["players"], list)

    conn_ok = True
    try:
        from game.models import db

        conn = db()
        conn.execute("SELECT 1 FROM users LIMIT 1;")
        conn.close()
    except Exception:
        conn_ok = False
    assert conn_ok is True


def test_migrations_endpoint(app_client):
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.get("/api/admin/migrations")
    assert r.status_code == 200
    m = r.get_json()["migrations"]
    assert "applied" in m
    assert "pending" in m


def test_finish_due_queues_returns_200(app_client):
    """Admin finish-due must not reference planets.planet_id (uses planets.id)."""
    client, _, user_id = app_client
    _login(client, "admin_cc", "adminpass123")

    from game.models import db, get_homeworld
    import time

    hw = get_homeworld(user_id)
    planet_id = int(hw["id"])
    conn = db()
    conn.execute(
        "INSERT INTO build_queue (planet_id, building_type, start_time, finish_time) "
        "VALUES (?, ?, ?, ?);",
        (planet_id, "metal_mine", time.time() - 60, time.time() - 1),
    )
    conn.commit()
    conn.close()

    r = client.post("/api/admin/queues/finish-due", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "finished" in data
    assert "affected_players" in data
    assert "duration_ms" in data
    assert data["source"] == "admin"


def test_schema_validation_passes_after_bootstrap(admin_env, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application
    from game.schema_validation import validate_core_schema

    bootstrap_application(skip_migration_check=True)
    issues = validate_core_schema(strict=True)
    assert issues == []


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


def test_migration_015_runtime_state_idempotent(admin_env):
    _run_migrate(admin_env)
    _run_migrate(admin_env)

    from game.bootstrap import bootstrap_application
    from game.db import table_exists
    from game.models import db

    bootstrap_application(skip_migration_check=True)
    conn = db()
    try:
        assert table_exists(conn, "runtime_state")
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runtime_state';"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_api_admin_queue_tick_admin_ok(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")

    from game.models import db, get_homeworld

    hw = get_homeworld(user_id)
    planet_id = int(hw["id"])
    conn = db()
    conn.execute(
        "INSERT INTO build_queue (planet_id, building_type, start_time, finish_time) "
        "VALUES (?, ?, ?, ?);",
        (planet_id, "metal_mine", time.time() - 60, time.time() - 1),
    )
    conn.commit()
    conn.close()

    r = client.post("/api/admin/queue-tick", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "finished" in data
    assert "affected_players" in data
    assert "batches" in data
    assert "tick_elapsed_ms" in data
    assert "errors" in data
    assert data["finished"]["buildings"] >= 1

    from game.runtime_state import get_queue_tick_status

    status = get_queue_tick_status()
    assert status["last_tick_at"] is not None
    assert status["last_tick_source"] == "admin_manual"
    assert status["last_tick_duration_ms"] is not None
    assert status["finished"].get("buildings", 0) >= 1
    assert status["affected_players_count"] >= 1

    audit = client.get("/api/admin/audit-log?action=queue_tick")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(e["action"] == "queue_tick" for e in entries)
    tick_entry = next(e for e in entries if e["action"] == "queue_tick")
    assert tick_entry["payload"]["source"] == "admin_manual"
    assert tick_entry["payload"]["finished"]["buildings"] >= 1


def test_api_admin_queue_tick_forbidden_for_user(app_client):
    client, _, _ = app_client
    _login(client, "normal_cc", "userpass123")
    r = client.post("/api/admin/queue-tick", json={})
    assert r.status_code == 403
    assert r.get_json()["error"] == "forbidden"


def test_admin_grant_inventory_all_players(app_client):
    client, _, user_id = app_client
    _login(client, "admin_cc", "adminpass123")

    from game.db import db
    from game.inventory import build_inventory_state

    r = client.post(
        "/api/admin/inventory/grant-all",
        json={"item_key": "container_basic", "amount": 3},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["granted"]["item_key"] == "container_basic"
    assert data["granted"]["amount"] == 3
    assert data["granted_count"] >= 1
    assert data["player_count"] == data["granted_count"]

    conn = db()
    try:
        state = build_inventory_state(user_id, conn=conn)
        basic = next(c for c in state["containers"] if c["item_key"] == "container_basic")
        assert basic["amount"] == 3
    finally:
        conn.close()

    audit = client.get("/api/admin/audit-log?action=grant_inventory_all")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(e["action"] == "grant_inventory_all" for e in entries)


def test_admin_grant_inventory_container(app_client):
    client, _, user_id = app_client
    _login(client, "admin_cc", "adminpass123")

    cat = client.get("/api/admin/inventory/catalog")
    assert cat.status_code == 200
    assert cat.get_json()["ok"] is True
    assert len(cat.get_json()["containers"]) >= 8

    r = client.post(
        f"/api/admin/player/{user_id}/inventory-grant",
        json={"item_key": "container_epic", "amount": 2},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["granted"]["item_key"] == "container_epic"
    assert data["granted"]["amount"] == 2

    from game.db import db
    from game.inventory import build_inventory_state

    conn = db()
    try:
        state = build_inventory_state(user_id, conn=conn)
        epic = next(c for c in state["containers"] if c["item_key"] == "container_epic")
        assert epic["amount"] == 2
    finally:
        conn.close()


def test_admin_lootboxes_state(app_client):
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.get("/api/admin/lootboxes/state")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert len(data["containers"]) >= 8
    assert "container_basic" in data["pools"]
    assert data["pools"]["container_basic"]["entries"]
    assert "reward_keys_by_type" in data
    assert "booster" in data["reward_keys_by_type"]
    assert "item" in data["reward_keys_by_type"]
    assert "resource" not in data["reward_keys_by_type"]


def test_admin_lootbox_pool_save_rejects_economy_rewards(app_client):
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")

    save = client.post(
        "/api/admin/lootboxes/pools/save",
        json={
            "container_key": "container_rare",
            "entries": [
                {
                    "weight": 100,
                    "reward_type": "resource",
                    "reward_key": "metal",
                    "min_amount": 42,
                    "max_amount": 42,
                }
            ],
        },
    )
    assert save.status_code == 400
    data = save.get_json()
    assert data["ok"] is False


def test_admin_lootbox_pool_save_and_open(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")

    custom_pool = [
        {
            "weight": 100,
            "reward_type": "booster",
            "reward_key": "booster_build_15m",
            "min_amount": 2,
            "max_amount": 2,
        }
    ]
    save = client.post(
        "/api/admin/lootboxes/pools/save",
        json={"container_key": "container_rare", "entries": custom_pool},
    )
    assert save.status_code == 200
    save_data = save.get_json()
    assert save_data["ok"] is True
    assert save_data["pool"]["is_custom"] is True

    from game import inventory_loot

    effective = inventory_loot.get_loot_pools()
    assert effective["container_rare"][0]["reward_key"] == "booster_build_15m"

    from game.db import db, begin_write_transaction, commit
    from game.inventory import grant_inventory_item, open_containers
    from game.planet_evolution.repository import get_context_planet
    import random

    conn = db()
    try:
        planet = get_context_planet(user_id, conn=conn)
        pid = int(planet["id"])
        metal_before = float(planet["metal"])
        grant_inventory_item(user_id, "container_rare", 1, conn=conn)
        begin_write_transaction(conn)
        ok, reason, result = open_containers(
            user_id, pid, "container_rare", 1, conn=conn, rng=random.Random(99)
        )
        assert ok, reason
        commit(conn)
        cur = conn.cursor()
        cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,))
        row = cur.fetchone()
        assert float(row["metal"]) == metal_before
        inv = cur.execute(
            "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
            (user_id, "booster_build_15m"),
        ).fetchone()
        assert inv and int(inv["amount"]) >= 2
    finally:
        conn.close()

    reset = client.post(
        "/api/admin/lootboxes/pools/reset",
        json={"container_key": "container_rare"},
    )
    assert reset.status_code == 200
    assert reset.get_json()["pool"]["is_custom"] is False

    audit = client.get("/api/admin/audit-log?action=loot_pool_save")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(e["action"] == "loot_pool_save" for e in entries)


def test_api_admin_queue_tick_error_response_shape(app_client):
    """Admin JS must receive structured JSON even when tick fails."""
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")

    with patch("game.tick_runner.run_tick") as mock_tick:
        mock_tick.return_value = {
            "ok": False,
            "source": "admin_manual",
            "scope": "due",
            "finished": {"buildings": 0, "research": 0, "shipyard": 0, "defense": 0},
            "affected_players": [],
            "errors": ["simulated failure"],
            "batches": 0,
            "tick_elapsed_ms": 1,
            "duration_ms": 1,
        }
        r = client.post("/api/admin/queue-tick", json={})

    assert r.status_code == 400
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "tick_failed"
    assert data["errors"] == ["simulated failure"]
    assert "finished" in data
    assert "message" in data


def test_admin_page_smoke_html(app_client):
    """Smoke: /admin shell markup for JS/CSS bindings."""
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.get("/admin")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="admin-control-center"' in html
    assert 'data-page="admin"' in html
    assert 'class="admin-tab-btn' in html
    assert 'data-admin-tab="health"' in html
    assert 'data-admin-panel="health"' in html
    assert 'data-admin-tab="lootboxes"' in html
    assert 'data-admin-panel="lootboxes"' in html
    assert "admin.js" in html
    assert "admin.css" in html
    assert 'data-admin-action="run-queue-tick"' in html
    assert "admin-btn-queue-tick" in html
    assert "GC_ASSET_VERSION" not in html
    assert "?v=" in html
    assert "admin-messages-broadcast" in html
    assert 'data-admin-action="messages-broadcast"' in html
    assert 'id="admin-messages-broadcast-confirm"' in html
    assert "admin-checkbox-row" in html


def test_admin_messages_broadcast_requires_confirm(app_client):
    client, admin_id, user_id = app_client
    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
    r = client.post(
        "/api/admin/messages/broadcast",
        json={"subject": "Test", "body": "Body text", "confirm": "WRONG"},
    )
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    assert r.get_json()["error"] == "confirm_required"

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    inbox = client.get("/api/messages?category=system").get_json()
    assert inbox["ok"]
    assert not any(m.get("subject") == "Test" for m in inbox["data"]["messages"])


def test_admin_messages_broadcast_audit(app_client):
    client, admin_id, user_id = app_client
    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
    r = client.post(
        "/api/admin/messages/broadcast",
        json={
            "subject": "Audit ping",
            "body": "Broadcast audit trail",
            "confirm": "SEND SYSTEM BROADCAST",
        },
    )
    assert r.status_code == 200
    assert r.get_json()["ok"]
    assert r.get_json()["delivered_count"] >= 2

    audit = client.get("/api/admin/audit-log?action=messages_broadcast")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(row.get("action") == "messages_broadcast" for row in entries)


def test_admin_galactic_diplomacy_forbidden_for_normal_user(app_client):
    client, admin_id, user_id = app_client
    _as_user(client, user_id)
    r = client.get("/api/admin/galactic-diplomacy/1")
    assert r.status_code == 403
    assert r.get_json()["error"] == "forbidden"


def test_admin_galactic_diplomacy_get_and_set_layers(app_client):
    client, admin_id, user_id = app_client
    _as_admin(client, admin_id)

    empty = client.get("/api/admin/galactic-diplomacy/1").get_json()
    assert empty["ok"] is True
    assert empty["galaxy"] == 1
    assert empty["personality"] is None
    assert empty["resolution"] is None
    assert empty["emergency"] is None
    assert len(empty["options"]["personalities"]) >= 5
    assert len(empty["options"]["emergencies"]) >= 5

    r = client.post(
        "/api/admin/galactic-diplomacy/1/personality",
        json={"personality_key": "academia_prime"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["personality"]["key"] == "academia_prime"

    r = client.post(
        "/api/admin/galactic-diplomacy/1/resolution",
        json={"resolution_key": "gate_control"},
    )
    assert r.status_code == 200
    assert r.get_json()["resolution"]["key"] == "gate_control"

    r = client.post(
        "/api/admin/galactic-diplomacy/1/emergency",
        json={"emergency_key": "hyperstorm"},
    )
    assert r.status_code == 200
    assert r.get_json()["emergency"]["key"] == "hyperstorm"

    state = client.get("/api/admin/galactic-diplomacy/1").get_json()
    assert state["personality"]["key"] == "academia_prime"
    assert state["resolution"]["key"] == "gate_control"
    assert state["emergency"]["key"] == "hyperstorm"


def test_admin_galactic_diplomacy_clear_layers(app_client):
    client, admin_id, user_id = app_client
    _as_admin(client, admin_id)

    client.post(
        "/api/admin/galactic-diplomacy/1/emergency",
        json={"emergency_key": "galaxy_war"},
    )
    r = client.post(
        "/api/admin/galactic-diplomacy/1/emergency",
        json={"clear": True},
    )
    assert r.status_code == 200
    assert r.get_json()["emergency"] is None

    client.post(
        "/api/admin/galactic-diplomacy/1/personality",
        json={"clear": True},
    )
    state = client.get("/api/admin/galactic-diplomacy/1").get_json()
    assert state["personality"] is None


def test_admin_galactic_diplomacy_invalid_inputs(app_client):
    client, admin_id, user_id = app_client
    _as_admin(client, admin_id)

    r = client.get("/api/admin/galactic-diplomacy/99")
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_galaxy"

    r = client.post(
        "/api/admin/galactic-diplomacy/1/emergency",
        json={"emergency_key": "not_real"},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_emergency_key"


def test_admin_galactic_diplomacy_writes_audit(app_client):
    client, admin_id, user_id = app_client
    _as_admin(client, admin_id)

    client.post(
        "/api/admin/galactic-diplomacy/1/personality",
        json={"personality_key": "forge_of_war"},
    )
    audit = client.get("/api/admin/audit-log?action=galactic_diplomacy_set_personality")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(row.get("action") == "galactic_diplomacy_set_personality" for row in entries)


def test_admin_panel_includes_diplomacy_tab(app_client):
    client, admin_id, user_id = app_client
    _as_admin(client, admin_id)
    r = client.get("/admin")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'data-admin-tab="diplomacy"' in html
    assert 'data-admin-action="diplomacy-load"' in html
    assert "admin-diplomacy-output" in html


def test_delete_player_requires_confirm(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.post(f"/api/admin/player/{user_id}/delete", json={})
    assert r.status_code == 400
    assert r.get_json()["error"] == "confirm_required"


def test_delete_player_requires_username_match(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.post(
        f"/api/admin/player/{user_id}/delete",
        json={"confirm": True, "expected_username": "wrong_name"},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "username_mismatch"


def test_delete_player_cannot_delete_self(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.post(
        f"/api/admin/player/{admin_id}/delete",
        json={"confirm": True, "expected_username": "admin_cc"},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "cannot_delete_self"


def test_delete_player_removes_user_and_planets(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")

    from game.models import db, get_planets_by_player

    conn = db()
    try:
        username = conn.execute(
            "SELECT username FROM users WHERE id = ?;", (user_id,)
        ).fetchone()["username"]
        planet_count = len(get_planets_by_player(user_id, conn=conn))
        assert planet_count >= 1
    finally:
        conn.close()

    r = client.post(
        f"/api/admin/player/{user_id}/delete",
        json={"confirm": True, "expected_username": username},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["deleted"]["player_id"] == user_id
    assert data["deleted"]["username"] == username
    assert data["deleted"]["planet_count"] >= 1

    conn = db()
    try:
        assert conn.execute("SELECT 1 FROM users WHERE id = ?;", (user_id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM players WHERE id = ?;", (user_id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM planets WHERE player_id = ?;", (user_id,)).fetchone() is None
    finally:
        conn.close()

    audit = client.get("/api/admin/audit-log?action=delete_player")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(int(e.get("target_id") or 0) == user_id for e in entries)
