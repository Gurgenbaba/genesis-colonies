"""GC-580A/580B — Sector grid renderer and viewport loading tests."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.sector_grid import (
    SECTOR_SIZE,
    SECTOR_VIEWPORT_PAD,
    SectorBoundsTooLargeError,
    build_sector_chunks_for_request,
    build_sector_chunks_for_world,
    dedupe_chunks_by_id,
    expand_world_bounds,
    normalize_world_bounds,
    sector_coords,
    sector_type,
    sector_types_in_range,
    visible_world_bounds_from_viewport,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def sector_grid_db(tmp_path, monkeypatch):
    db_file = tmp_path / "sector_grid.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def _create_player() -> int:
    uname = f"sector_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def test_sector_coords_maps_world_to_grid():
    assert sector_coords(0, 0) == (0, 0)
    assert sector_coords(1999.9, 3999.9) == (0, 1)
    assert sector_coords(2000, 2000) == (1, 1)
    assert sector_coords(-1, -1) == (-1, -1)


def test_sector_type_is_deterministic():
    assert sector_type(2, -3, seed=1) == sector_type(2, -3, seed=1)
    assert sector_type(2, -3, seed=1) != sector_type(2, -3, seed=2)
    assert sector_type(0, 0, seed=1) in {
        "genesis_core",
        "outer_rim",
        "ancient_sector",
        "dark_expanse",
        "nebula",
        "void",
        "crystal_belt",
        "dead_zone",
    }


def test_sector_types_vary_in_five_by_five_grid():
    types = sector_types_in_range(-2, -2, 2, 2, seed=1)
    assert len(types) >= 3


def test_build_sector_chunks_for_world_bounds():
    chunks = build_sector_chunks_for_world(1500, 1500, 2500, 2500, seed=1)
    assert chunks
    first = chunks[0]
    assert first["id"].startswith("sector_")
    assert first["sector_x"] == 0
    assert first["sector_y"] == 0
    assert first["type"]
    assert first["label_key"]
    assert first["tone"]
    assert first["width"] == SECTOR_SIZE
    assert first["height"] == SECTOR_SIZE
    assert first["path"].startswith("M ")
    assert first["path"].endswith("Z")


def test_normalize_world_bounds_swaps_inverted_edges():
    assert normalize_world_bounds(10, 20, 0, 5) == (0.0, 5.0, 10.0, 20.0)


def test_expand_world_bounds_adds_viewport_pad():
    lo_x, lo_y, hi_x, hi_y = expand_world_bounds(0, 0, 100, 100, pad=SECTOR_VIEWPORT_PAD)
    assert lo_x == -SECTOR_VIEWPORT_PAD
    assert lo_y == -SECTOR_VIEWPORT_PAD
    assert hi_x == 100 + SECTOR_VIEWPORT_PAD
    assert hi_y == 100 + SECTOR_VIEWPORT_PAD


def test_visible_world_bounds_from_viewport_matches_pan_zoom():
    min_wx, min_wy, max_wx, max_wy = visible_world_bounds_from_viewport(
        pan_x=-400.0,
        pan_y=-200.0,
        zoom=0.5,
        viewport_w=800.0,
        viewport_h=600.0,
        pad=0.0,
    )
    assert min_wx == pytest.approx(800.0)
    assert min_wy == pytest.approx(400.0)
    assert max_wx == pytest.approx(2400.0)
    assert max_wy == pytest.approx(1600.0)


def test_dedupe_chunks_by_id_keeps_last_row():
    rows = [
        {"id": "sector_0_0", "type": "void"},
        {"id": "sector_0_0", "type": "nebula"},
        {"id": "sector_1_0", "type": "rim"},
    ]
    deduped = dedupe_chunks_by_id(rows)
    assert len(deduped) == 2
    by_id = {row["id"]: row for row in deduped}
    assert by_id["sector_0_0"]["type"] == "nebula"
    assert by_id["sector_1_0"]["type"] == "rim"


def test_build_sector_chunks_for_request_is_deterministic_for_same_bounds():
    bounds = (5000, 5000, 9000, 9000)
    first = build_sector_chunks_for_request(*bounds, seed=1)
    second = build_sector_chunks_for_request(*bounds, seed=1)
    assert first == second
    assert len({row["id"] for row in first}) == len(first)


def test_build_sector_chunks_for_request_rejects_oversized_bounds():
    with pytest.raises(SectorBoundsTooLargeError):
        build_sector_chunks_for_request(-50000, -50000, 50000, 50000, seed=1)


def test_build_sector_chunks_for_request_loads_far_from_origin():
    chunks = build_sector_chunks_for_request(12000, 12000, 14000, 14000, seed=1)
    assert chunks
    assert all(row["sector_x"] >= 6 for row in chunks)
    assert all(row["sector_y"] >= 6 for row in chunks)


def test_command_map_payload_includes_sector_grid_meta(sector_grid_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    grid = payload.get("sector_grid") or {}
    assert grid.get("seed") == 1
    assert grid.get("sector_size") == SECTOR_SIZE
    assert grid.get("viewport_pad") == SECTOR_VIEWPORT_PAD
    assert "sector_chunks" not in payload


def test_galaxy_template_renders_sector_layer_shell(sector_grid_db, monkeypatch):
    dbmod.DB_PATH = sector_grid_db
    models.DB_PATH = sector_grid_db
    import app as app_module

    importlib.reload(app_module)

    player_id = _create_player()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    resp = client.get("/galaxy?view=command_map&dev=1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "galaxy-command-map-sector-layer" in body
    assert "data-command-map-sector-root" in body
    assert "data-sector-seed" in body
    assert "galaxy-command-map-nebulas" not in body


def test_api_command_map_sectors_returns_chunks(sector_grid_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    dbmod.DB_PATH = sector_grid_db
    models.DB_PATH = sector_grid_db
    import app as app_module

    importlib.reload(app_module)

    player_id = _create_player()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    resp = client.get(
        "/api/command-map/sectors"
        "?min_wx=1500&min_wy=1500&max_wx=2500&max_wy=2500&seed=1"
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    chunks = payload.get("sector_chunks") or []
    assert chunks
    assert len({row["id"] for row in chunks}) == len(chunks)
    assert payload["bounds"]["min_wx"] == pytest.approx(1500.0)
    assert all("path" in row and "type" in row for row in chunks)


def test_api_command_map_sectors_requires_bounds(sector_grid_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    dbmod.DB_PATH = sector_grid_db
    models.DB_PATH = sector_grid_db
    import app as app_module

    importlib.reload(app_module)

    player_id = _create_player()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    resp = client.get("/api/command-map/sectors?min_wx=0&min_wy=0")
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
