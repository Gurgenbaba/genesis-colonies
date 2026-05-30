"""Galaxy coordinate system — foundation tests."""

from __future__ import annotations

import importlib
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.galaxy import (
    assign_free_coordinates,
    format_coordinates,
    get_planet_coordinates,
    list_system,
    repair_missing_coordinates,
)
from game.models import create_user, db, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.overview_page import build_planet_meta


@pytest.fixture()
def galaxy_db(tmp_path, monkeypatch):
    db_path = tmp_path / "galaxy_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)
    import migrate

    migrate.ensure_db_exists()
    migrate.main()
    yield
    dbmod._DB_PATH = None


def _create_player() -> int:
    uname = f"gal_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    return int(user["id"])


def test_new_player_gets_coordinates(galaxy_db):
    uid = _create_player()
    planets = get_planets_by_player(uid)
    assert len(planets) >= 1
    hw = next(p for p in planets if int(p.get("is_homeworld") or 0) == 1)
    coords = get_planet_coordinates(hw)
    assert coords["galaxy"] == 1
    assert 1 <= coords["system"] <= 499
    assert 1 <= coords["position"] <= 15


def test_coordinates_are_unique(galaxy_db):
    ids = [_create_player() for _ in range(5)]
    seen = set()
    for uid in ids:
        for p in get_planets_by_player(uid):
            c = get_planet_coordinates(p)
            key = (c["galaxy"], c["system"], c["position"])
            assert key not in seen, key
            seen.add(key)


def test_repair_assigns_missing_coordinates(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    pid = int(planet["id"])

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE planets SET system = NULL, position = NULL WHERE id = ?;", (pid,))
    conn.commit()
    conn.close()

    repaired = repair_missing_coordinates()
    assert repaired >= 1

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (pid,))
    row = dict(cur.fetchone())
    conn.close()
    coords = get_planet_coordinates(row)
    assert coords["formatted"] == format_coordinates(
        coords["galaxy"], coords["system"], coords["position"]
    )


def test_format_coordinates():
    assert format_coordinates(1, 42, 8) == "[1:42:8]"


def test_get_planet_coordinates(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    assert coords["formatted"] == format_coordinates(
        coords["galaxy"], coords["system"], coords["position"]
    )


def test_list_system_returns_15_slots(galaxy_db):
    data = list_system(1, 1)
    assert data["galaxy"] == 1
    assert data["system"] == 1
    assert len(data["slots"]) == 15
    positions = [s["position"] for s in data["slots"]]
    assert positions == list(range(1, 16))


def test_occupied_slots_have_data(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    data = list_system(coords["galaxy"], coords["system"])
    slot = next(s for s in data["slots"] if s["occupied"] and s["planet_id"] == int(planet["id"]))
    assert slot["planet_name"]
    assert slot["commander_name"]
    assert slot["player_id"] == uid
    assert slot["coordinates_formatted"] == coords["formatted"]


def test_empty_slots_are_marked_empty(galaxy_db):
    data = list_system(1, 499)
    empty = [s for s in data["slots"] if not s["occupied"]]
    assert len(empty) == 15
    for slot in empty:
        assert slot["planet_id"] is None
        assert slot["player_id"] is None
        assert slot["coordinates_formatted"] == format_coordinates(1, 499, slot["position"])


def test_overview_uses_real_coordinates(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    meta = build_planet_meta(planet)
    assert meta["coordinates"]["display"] == format_coordinates(
        meta["coordinates"]["galaxy"],
        meta["coordinates"]["system"],
        meta["coordinates"]["position"],
    )
    assert "?" not in meta["coordinates"]["display"]
    assert "Sektor" not in meta["coordinates"]["display"]


def test_galaxy_page_loads(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    uname = f"page_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    client = app_module.app.test_client()
    login = client.post("/login", data={"username": uname, "password": "test-pass-123"})
    assert login.status_code in (200, 302)
    resp = client.get("/galaxy")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "galaxy-slot-row" in body
    assert "galaxy-hero" in body


def test_api_galaxy_system(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    uname = f"api_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    resp = client.get("/api/galaxy/system?galaxy=1&system=1")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert len(payload["data"]["slots"]) == 15


def test_assign_free_coordinates_never_duplicates(galaxy_db):
    uid = _create_player()
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        a = assign_free_coordinates(conn)
        conn.execute(
            """
            INSERT INTO planets (
                player_id, name, is_homeworld, metal, crystal, last_update,
                galaxy, system, position
            ) VALUES (?, 'Probe', 0, 0, 0, 0, ?, ?, ?);
            """,
            (uid, *a),
        )
        b = assign_free_coordinates(conn)
        assert a != b
        conn.rollback()
    finally:
        conn.close()
