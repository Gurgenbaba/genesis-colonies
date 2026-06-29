"""
GC-GALAXY-LAST-VIEW — View tab prefs + active-planet galaxy coords.

Run: python -m pytest tests/test_gc_galaxy_last_view.py -v
"""

from __future__ import annotations

import importlib
import re
import uuid
from pathlib import Path

import game.db as dbmod
import game.models as models
import migrate
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def galaxy_db(tmp_path, monkeypatch):
    db_path = tmp_path / "galaxy_last_view.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)
    migrate.ensure_db_exists()
    migrate.main()
    yield
    dbmod._DB_PATH = None


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _galaxy_client(monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    uname = f"galview_{uuid.uuid4().hex[:8]}"
    from game.models import create_user

    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])
    return client


def _page_coords(body: str) -> tuple[int | None, int | None]:
    root = re.search(
        r'id="galaxy-page-root"[^>]*data-galaxy="(\d+)"[^>]*data-system="(\d+)"',
        body,
    )
    if root:
        return int(root.group(1)), int(root.group(2))
    root = re.search(
        r'id="galaxy-page-root"[^>]*data-system="(\d+)"[^>]*data-galaxy="(\d+)"',
        body,
    )
    if root:
        return int(root.group(2)), int(root.group(1))
    return None, None


def test_galaxy_without_url_coords_uses_active_planet_not_session(galaxy_db, monkeypatch):
    client = _galaxy_client(monkeypatch)
    with client.session_transaction() as sess:
        uid = int(sess["user_id"])
    from game.galaxy import get_planet_coordinates
    from game.models import get_homeworld

    active = get_planet_coordinates(get_homeworld(player_id=uid))

    client.get("/galaxy?view=system&galaxy=3&system=42")
    resp = client.get("/galaxy?view=system")
    assert resp.status_code == 200
    galaxy, system = _page_coords(resp.get_data(as_text=True))
    assert galaxy == int(active["galaxy"])
    assert system == int(active["system"])
    assert system != 42


def test_galaxy_first_visit_falls_back_to_active_planet(galaxy_db, monkeypatch):
    from game.models import get_homeworld

    client = _galaxy_client(monkeypatch)
    with client.session_transaction() as sess:
        uid = int(sess["user_id"])
    hw = get_homeworld(player_id=uid)
    from game.galaxy import get_planet_coordinates

    coords = get_planet_coordinates(hw)

    resp = client.get("/galaxy?view=system")
    assert resp.status_code == 200
    galaxy, system = _page_coords(resp.get_data(as_text=True))
    assert galaxy == int(coords["galaxy"])
    assert system == int(coords["system"])


def test_galaxy_url_coords_override_active_planet(galaxy_db, monkeypatch):
    client = _galaxy_client(monkeypatch)
    client.get("/galaxy?view=system&galaxy=3&system=42")
    resp = client.get("/galaxy?view=system&galaxy=1&system=77")
    assert resp.status_code == 200
    galaxy, system = _page_coords(resp.get_data(as_text=True))
    assert galaxy == 1
    assert system == 77


def test_galaxy_planet_switch_resets_session_coords(galaxy_db, monkeypatch):
    client = _galaxy_client(monkeypatch)
    with client.session_transaction() as sess:
        uid = int(sess["user_id"])

    from game.db import commit, db
    from game.galaxy import get_planet_coordinates
    from game.models import get_homeworld
    from game.planet_evolution.service import set_active_planet

    hw = get_homeworld(player_id=uid)
    hw_coords = get_planet_coordinates(hw)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO planets (
            player_id, name, is_homeworld, metal, crystal, last_update,
            galaxy, system, position
        ) VALUES (?, 'Colony Beta', 0, 1000, 1000, 0, ?, ?, ?);
        """,
        (uid, int(hw_coords["galaxy"]), 250, 10),
    )
    colony_id = int(cur.lastrowid)
    commit(conn)
    conn.close()

    client.get("/galaxy?view=system&galaxy=3&system=42")
    ok, reason = set_active_planet(uid, colony_id)
    assert ok, reason

    resp = client.get("/galaxy?view=system")
    assert resp.status_code == 200
    galaxy, system = _page_coords(resp.get_data(as_text=True))
    assert galaxy == int(hw_coords["galaxy"])
    assert system == 250


def test_gc_galaxy_last_view_main_js_contract():
    src = _read("static/main.js")
    assert "gc_galaxy_prefs_v2" in src
    assert "persistGalaxyViewFromPage" in src
    assert "resolveGalaxyNavHref" in src
    assert 'writeGalaxyPrefs({ view: "system" })' in src
    assert 'link.dataset.navModule === "galaxy"' in src
    resolve_block = src.split("resolveGalaxyNavHref")[1].split("function initGalaxyDebrisUx", 1)[0]
    assert "prefs.galaxy" not in resolve_block
    assert 'url.searchParams.set("view", "system")' in resolve_block
    assert "command_map" not in resolve_block
