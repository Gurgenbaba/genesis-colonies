"""
GC-RESET-SMOKE — Universe reset end-to-end via /api/admin/universe-reset (no browser).

Run: python -m pytest tests/test_gc_reset_smoke.py -v
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def smoke_env(tmp_path, monkeypatch):
    db_file = tmp_path / "gc_reset_smoke.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    return db_file


@pytest.fixture()
def smoke_client(smoke_env, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import migrate

    migrate.main()

    import importlib
    import app as app_module

    importlib.reload(app_module)
    return app_module.app.test_client()


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)


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


def _seed_players_and_game_world() -> tuple[int, int]:
    """Create admin + player, inventory, queues, research, message, fleet, extra colony."""
    from game.db import table_exists
    from game.fleet import EXPEDITION_POSITION, add_planet_ships, send_fleet
    from game.inventory import grant_inventory_item, inventory_schema_ready
    from game.models import create_user, db, ensure_player_and_homeworld, get_homeworld

    ok_a, _, admin_info = create_user("smoke_admin", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("smoke_player", "userpass123", is_admin=0)
    assert ok_u
    admin_id = int(admin_info["id"])
    user_id = int(user_info["id"])
    ensure_player_and_homeworld(admin_id)
    ensure_player_and_homeworld(user_id)

    conn = db()
    try:
        assert inventory_schema_ready(conn)
        grant_inventory_item(user_id, "container_basic", 3, conn=conn)
        grant_inventory_item(user_id, "fragment_dna_common", 12, conn=conn)

        hw = get_homeworld(user_id, conn=conn)
        planet_id = int(hw["id"])
        now = time.time()

        conn.execute(
            "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 500000 WHERE id = ?;",
            (planet_id,),
        )

        # Extra colony — must be gone after reset (only homeworld remains).
        conn.execute(
            """
            INSERT INTO planets (
                player_id, name, is_homeworld, metal, crystal, fuel_cells, last_update,
                galaxy, system, position
            ) VALUES (?, ?, 0, 1000, 1000, 100, ?, 1, 2, 3);
            """,
            (user_id, "Outpost Alpha", now),
        )
        conn.execute("INSERT INTO planet_buildings (planet_id) VALUES (last_insert_rowid());")

        conn.execute(
            """
            INSERT INTO build_queue (planet_id, building_type, start_time, finish_time)
            VALUES (?, ?, ?, ?);
            """,
            (planet_id, "metal_mine", now, now + 3600),
        )
        conn.execute(
            "INSERT INTO research_levels (user_id, tech_key, level) VALUES (?, ?, ?);",
            (user_id, "weapons", 5),
        )
        if table_exists(conn, "research_queue"):
            conn.execute(
                """
                INSERT INTO research_queue (user_id, tech_key, start_at, finish_at)
                VALUES (?, ?, ?, ?);
                """,
                (user_id, "armor", now, now + 7200),
            )

        conn.execute(
            """
            INSERT INTO player_messages (
                recipient_player_id, sender_player_id, subject, body, created_at, is_read
            ) VALUES (?, ?, ?, ?, ?, 0);
            """,
            (user_id, admin_id, "smoke", "pre-reset message", int(now)),
        )

        add_planet_ships(planet_id, user_id, {"solar_skiff": 2}, conn=conn)
        g = int(hw.get("galaxy") or 1)
        s = int(hw.get("system") or 1)
        ok, err, fleet_result = send_fleet(
            player_id=user_id,
            origin_planet_id=planet_id,
            target_galaxy=g,
            target_system=s,
            target_position=EXPEDITION_POSITION,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            conn=conn,
        )
        assert ok, err
        assert fleet_result and fleet_result.get("fleet")

        conn.commit()
    finally:
        conn.close()

    return admin_id, user_id


@patch("game.admin_universe_reset.create_pre_reset_backup")
def test_gc_reset_smoke_universe_reset_end_to_end(mock_backup, smoke_client, tmp_path):
    """Full live-ops path: seed progress → POST /api/admin/universe-reset → verify season state."""
    mock_backup.return_value = tmp_path / "pre_universe_reset_smoke.db"

    admin_id, user_id = _seed_players_and_game_world()
    client = smoke_client
    _login(client, admin_id)

    before_inv = _inventory_snapshot(user_id)
    assert before_inv == [
        ("container_basic", 3),
        ("fragment_dna_common", 12),
    ]
    assert _count_table("build_queue") > 0
    assert _count_table("research_levels") > 0
    assert _count_table("research_queue") > 0
    assert _count_table("player_messages") > 0
    assert _count_table("fleet_movements") > 0
    assert _count_table("planets") >= 3  # admin hw + player hw + outpost

    r = client.post(
        "/api/admin/universe-reset",
        json={"confirm_text": "RESET UNIVERSE KEEP INVENTORY"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["players_reinitialized"] >= 2
    assert body["backup_path"]
    assert mock_backup.called

    assert _inventory_snapshot(user_id) == before_inv
    assert _count_table("build_queue") == 0
    assert _count_table("research_levels") == 0
    assert _count_table("research_queue") == 0
    assert _count_table("player_messages") == 0
    assert _count_table("fleet_movements") == 0

    from game.models import db, get_homeworld

    conn = db()
    try:
        for pid in (admin_id, user_id):
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM planets WHERE player_id = ?;",
                (int(pid),),
            ).fetchone()["c"]
            homeworlds = conn.execute(
                "SELECT COUNT(*) AS c FROM planets WHERE player_id = ? AND is_homeworld = 1;",
                (int(pid),),
            ).fetchone()["c"]
            assert int(total) == 1
            assert int(homeworlds) == 1

            hw = get_homeworld(int(pid), conn=conn)
            active = conn.execute(
                "SELECT active_planet_id FROM players WHERE id = ? LIMIT 1;",
                (int(pid),),
            ).fetchone()["active_planet_id"]
            assert int(active) == int(hw["id"])
            assert str(hw.get("name") or "") == "Genesis Ark"
    finally:
        conn.close()

    audit = client.get("/api/admin/audit-log?action=universe_reset_keep_inventory")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(e["action"] == "universe_reset_keep_inventory" for e in entries)
    hit = next(e for e in entries if e["action"] == "universe_reset_keep_inventory")
    payload = hit.get("payload") or {}
    assert payload.get("action") == "universe_reset_keep_inventory"
    assert payload.get("backup_path")
    assert "deleted_tables" in payload
    assert int(payload.get("players_reinitialized") or 0) >= 2
