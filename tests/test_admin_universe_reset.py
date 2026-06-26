"""
GC-RESET — Admin universe reset with inventory preserve.

Run: python -m pytest tests/test_admin_universe_reset.py -v
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def admin_env(tmp_path, monkeypatch):
    db_file = tmp_path / "admin_reset.db"
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

    from game.inventory import grant_inventory_item, inventory_schema_ready
    from game.models import create_user, db, ensure_player_and_homeworld, get_homeworld

    ok_a, _, admin_info = create_user("admin_reset", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("player_reset", "userpass123", is_admin=0)
    assert ok_u
    admin_id = int(admin_info["id"])
    user_id = int(user_info["id"])
    ensure_player_and_homeworld(user_id)

    conn = db()
    try:
        if inventory_schema_ready(conn):
            grant_inventory_item(user_id, "container_basic", 3, conn=conn)
            grant_inventory_item(user_id, "fragment_dna_common", 12, conn=conn)

        hw = get_homeworld(user_id, conn=conn)
        planet_id = int(hw["id"])
        conn.execute(
            "INSERT INTO build_queue (planet_id, building_type, start_time, finish_time) VALUES (?, ?, ?, ?);",
            (planet_id, "metal_mine", time.time(), time.time() + 3600),
        )
        conn.execute(
            "INSERT INTO research_levels (user_id, tech_key, level) VALUES (?, ?, ?);",
            (user_id, "weapons", 5),
        )
        if conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_messages';"
        ).fetchone():
            conn.execute(
                """
                INSERT INTO player_messages (
                    recipient_player_id, sender_player_id, subject, body, created_at, is_read
                ) VALUES (?, ?, ?, ?, ?, 0);
                """,
                (user_id, admin_id, "test", "hello", int(time.time())),
            )
        conn.commit()
    finally:
        conn.close()

    client = app_module.app.test_client()
    return client, admin_id, user_id


def _login(client, username, password):
    from game.models import verify_user

    user = verify_user(str(username), str(password))
    if user:
        with client.session_transaction() as sess:
            sess["user_id"] = int(user["id"])
        return user
    return None


def _inventory_snapshot(user_id: int) -> list[tuple[str, int]]:
    from game.models import db

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT item_key, amount FROM player_inventory_items
            WHERE user_id = ? ORDER BY item_key ASC;
            """,
            (int(user_id),),
        ).fetchall()
        return [(str(r["item_key"]), int(r["amount"])) for r in rows]
    finally:
        conn.close()


def _count_table(table: str) -> int:
    from game.db import table_exists
    from game.models import db

    conn = db()
    try:
        if not table_exists(conn, table):
            return 0
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table};").fetchone()
        return int(row["c"] or 0)
    finally:
        conn.close()


def test_universe_reset_wrong_confirm_no_db_change(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_reset", "adminpass123")

    before_inv = _inventory_snapshot(user_id)
    before_planets = _count_table("planets")
    before_messages = _count_table("player_messages")

    r = client.post("/api/admin/universe-reset", json={})
    assert r.status_code == 400
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "confirm_required"

    assert _inventory_snapshot(user_id) == before_inv
    assert _count_table("planets") == before_planets
    assert _count_table("player_messages") == before_messages


def test_universe_reset_forbidden_for_normal_user(app_client):
    client, _, _ = app_client
    _login(client, "player_reset", "userpass123")
    r = client.post(
        "/api/admin/universe-reset",
        json={"confirm_text": "RESET UNIVERSE KEEP INVENTORY"},
    )
    assert r.status_code == 403
    assert r.get_json()["error"] == "forbidden"


@patch("game.admin_universe_reset.create_pre_reset_backup")
def test_universe_reset_clears_game_state_preserves_inventory(mock_backup, app_client, tmp_path):
    mock_backup.return_value = tmp_path / "pre_universe_reset_test.db"

    client, admin_id, user_id = app_client
    _login(client, "admin_reset", "adminpass123")

    before_inv = _inventory_snapshot(user_id)
    assert before_inv
    assert _count_table("build_queue") > 0
    assert _count_table("research_levels") > 0
    assert _count_table("player_messages") > 0

    r = client.post(
        "/api/admin/universe-reset",
        json={"confirm_text": "RESET UNIVERSE KEEP INVENTORY"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["players_reinitialized"] >= 2
    assert data["backup_path"]
    assert mock_backup.called

    assert _inventory_snapshot(user_id) == before_inv
    assert _count_table("build_queue") == 0
    assert _count_table("research_levels") == 0
    assert _count_table("player_messages") == 0
    assert _count_table("fleet_movements") == 0


@patch("game.admin_universe_reset.create_pre_reset_backup")
def test_universe_reset_homeworld_and_active_planet(mock_backup, app_client, tmp_path):
    mock_backup.return_value = tmp_path / "pre_universe_reset_test.db"

    client, admin_id, user_id = app_client
    _login(client, "admin_reset", "adminpass123")

    r = client.post(
        "/api/admin/universe-reset",
        json={"confirm_text": "RESET UNIVERSE KEEP INVENTORY"},
    )
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    from game.models import db, get_homeworld

    conn = db()
    try:
        for pid in (admin_id, user_id):
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM planets WHERE player_id = ? AND is_homeworld = 1;",
                (int(pid),),
            )
            assert int(cur.fetchone()["c"]) == 1
            hw = get_homeworld(int(pid), conn=conn)
            row = conn.execute(
                "SELECT active_planet_id FROM players WHERE id = ? LIMIT 1;",
                (int(pid),),
            ).fetchone()
            assert int(row["active_planet_id"]) == int(hw["id"])
    finally:
        conn.close()


@patch("game.admin_universe_reset.create_pre_reset_backup")
def test_universe_reset_preserves_users_and_admin(mock_backup, app_client, tmp_path):
    mock_backup.return_value = tmp_path / "pre_universe_reset_test.db"

    client, admin_id, user_id = app_client
    _login(client, "admin_reset", "adminpass123")

    r = client.post(
        "/api/admin/universe-reset",
        json={"confirm_text": "RESET UNIVERSE KEEP INVENTORY"},
    )
    assert r.get_json()["ok"] is True

    from game.models import db

    conn = db()
    try:
        admin_row = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE id = ?;",
            (admin_id,),
        ).fetchone()
        user_row = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE id = ?;",
            (user_id,),
        ).fetchone()
        assert int(admin_row["is_admin"]) == 1
        assert int(user_row["is_admin"]) == 0
        assert str(admin_row["username"]) == "admin_reset"
        assert str(user_row["username"]) == "player_reset"
    finally:
        conn.close()


@patch("game.admin_universe_reset.create_pre_reset_backup")
def test_universe_reset_writes_audit_log(mock_backup, app_client, tmp_path):
    mock_backup.return_value = tmp_path / "pre_universe_reset_test.db"

    client, admin_id, _ = app_client
    _login(client, "admin_reset", "adminpass123")

    client.post(
        "/api/admin/universe-reset",
        json={"confirm_text": "RESET UNIVERSE KEEP INVENTORY"},
    )

    r = client.get("/api/admin/audit-log?action=universe_reset_keep_inventory")
    assert r.status_code == 200
    entries = r.get_json()["entries"]
    assert any(e["action"] == "universe_reset_keep_inventory" for e in entries)
    hit = next(e for e in entries if e["action"] == "universe_reset_keep_inventory")
    payload = hit.get("payload") or {}
    assert payload.get("action") == "universe_reset_keep_inventory"
    assert payload.get("backup_path")
    assert "deleted_tables" in payload


def test_reset_domain_coverage_complete():
    from game.admin_universe_reset import CLEAR_TABLES_ORDER, RESET_DOMAINS

    mapped = set()
    for tables in RESET_DOMAINS.values():
        mapped.update(tables)
    assert mapped == set(CLEAR_TABLES_ORDER)


def _only_messages_reset_options() -> dict:
    from game.admin_universe_reset import RESET_DOMAIN_ORDER, default_reset_options

    opts = default_reset_options()
    for key in RESET_DOMAIN_ORDER:
        opts[key] = key == "messages"
    return opts


def test_universe_reset_empty_domains_rejected(app_client):
    client, _, _ = app_client
    _login(client, "admin_reset", "adminpass123")
    opts = _only_messages_reset_options()
    for key in opts:
        opts[key] = False
    r = client.post(
        "/api/admin/universe-reset",
        json={"confirm_text": "RESET UNIVERSE KEEP INVENTORY", "reset_options": opts},
    )
    assert r.status_code == 400
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "reset_options_empty"


@patch("game.admin_universe_reset.create_pre_reset_backup")
def test_universe_reset_selective_messages_only(mock_backup, app_client, tmp_path):
    mock_backup.return_value = tmp_path / "pre_universe_reset_test.db"

    client, _, user_id = app_client
    _login(client, "admin_reset", "adminpass123")

    before_planets = _count_table("planets")
    before_research = _count_table("research_levels")
    assert before_planets > 0
    assert before_research > 0
    assert _count_table("player_messages") > 0

    r = client.post(
        "/api/admin/universe-reset",
        json={
            "confirm_text": "RESET UNIVERSE KEEP INVENTORY",
            "reset_options": _only_messages_reset_options(),
        },
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["players_reinitialized"] == 0
    assert data["reset_domains_applied"] == ["messages"]

    assert _count_table("planets") == before_planets
    assert _count_table("research_levels") == before_research
    assert _count_table("player_messages") == 0
    assert _count_table("build_queue") > 0


@patch("game.admin_universe_reset.create_pre_reset_backup")
def test_universe_reset_recalculates_rankings(mock_backup, app_client, tmp_path):
    """After season reset, scores must be recomputed from live state — not stale ranks."""
    mock_backup.return_value = tmp_path / "pre_universe_reset_test.db"

    client, admin_id, user_id = app_client
    _login(client, "admin_reset", "adminpass123")

    from game.models import db

    conn = db()
    try:
        conn.execute(
            """
            UPDATE player_scores
            SET score_research = 50000, score_total = 50000, rank_total = 1
            WHERE player_id = ?;
            """,
            (user_id,),
        )
        conn.commit()
        before = conn.execute(
            """
            SELECT score_total, score_research, rank_total
            FROM player_scores WHERE player_id = ?;
            """,
            (user_id,),
        ).fetchone()
        assert before is not None
        assert int(before["score_research"] or 0) == 50000
    finally:
        conn.close()

    r = client.post(
        "/api/admin/universe-reset",
        json={"confirm": True},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    ranking = data.get("ranking_refresh") or {}
    assert ranking.get("ok") is True
    assert ranking.get("players_updated", 0) >= 2
    assert ranking.get("ranks_assigned", 0) >= 2

    attack_protection = data.get("attack_protection") or {}
    assert attack_protection.get("locked") is True
    assert attack_protection.get("reason") == "reset_protection"
    assert int(attack_protection.get("locked_until") or 0) > int(time.time())

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT player_id, score_total, score_research, rank_total
            FROM player_scores
            ORDER BY player_id ASC;
            """
        ).fetchall()
        assert len(rows) >= 2
        for row in rows:
            assert int(row["score_research"] or 0) == 0
            assert int(row["rank_total"] or 0) >= 1
        rank_totals = sorted(int(r["rank_total"]) for r in rows)
        assert rank_totals == list(range(1, len(rows) + 1))
    finally:
        conn.close()
