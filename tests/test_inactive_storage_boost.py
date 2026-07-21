"""Inactive storage boost (admin / CLI owner)."""

from __future__ import annotations

import time
import uuid

import pytest

from game import db as gdb
from game.admin_api import apply_inactive_storage_boost, boost_inactive_storage
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_planet_buildings, init_db
from game.ranking import RANKING_INACTIVE_AFTER_SEC


@pytest.fixture
def storage_boost_db(tmp_path, monkeypatch):
    db_path = tmp_path / "inactive_storage_boost.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _make_player(*, last_seen: int, storage: dict | None = None):
    ok, err, user = create_user(f"st_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Storage")
    conn = db()
    conn.execute("UPDATE players SET last_seen = ? WHERE id = ?;", (int(last_seen), uid))
    planet = conn.execute(
        "SELECT id FROM planets WHERE player_id = ? ORDER BY id ASC LIMIT 1;",
        (uid,),
    ).fetchone()
    assert planet is not None
    planet_id = int(planet["id"])
    if storage:
        for key, level in storage.items():
            conn.execute(
                f"UPDATE planet_buildings SET {key} = ? WHERE planet_id = ?;",
                (int(level), planet_id),
            )
    conn.commit()
    conn.close()
    return uid, planet_id


def test_apply_inactive_storage_boost_raises_only_inactive(storage_boost_db):
    now = int(time.time())
    inactive_seen = now - int(RANKING_INACTIVE_AFTER_SEC) - 3600
    _, p_low = _make_player(last_seen=inactive_seen, storage={"metal_storage": 3, "crystal_storage": 0})
    _, p_high = _make_player(
        last_seen=inactive_seen,
        storage={"metal_storage": 20, "crystal_storage": 18, "fuel_storage": 16},
    )
    _, p_active = _make_player(last_seen=now - 60, storage={"metal_storage": 1})

    result = apply_inactive_storage_boost(target_level=15, now=now)
    assert result["ok"] is True
    assert result["inactive_players"] == 2
    assert result["planets_updated"] >= 1
    assert result["players_rescored"] >= 1

    low = get_planet_buildings(p_low)
    assert low["metal_storage"] == 15
    assert low["crystal_storage"] == 15
    assert low["fuel_storage"] == 15

    high = get_planet_buildings(p_high)
    assert high["metal_storage"] == 20
    assert high["crystal_storage"] == 18
    assert high["fuel_storage"] == 16

    active = get_planet_buildings(p_active)
    assert active["metal_storage"] == 1


def test_boost_inactive_storage_requires_confirm(storage_boost_db):
    denied = boost_inactive_storage(1, {})
    assert denied["ok"] is False
    assert denied["error"] == "confirm_required"
