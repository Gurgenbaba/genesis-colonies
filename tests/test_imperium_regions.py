"""GC-564 — Imperium region layer tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, get_homeworld, init_db
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.expansion_gates import EXPANSION_SITES
from game.planet_evolution.imperium_regions import (
    IMPERIUM_REGIONS,
    build_regions_payload,
    region_is_dimmed,
    region_for_colony,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def regions_db(tmp_path, monkeypatch):
    db_file = tmp_path / "imperium_regions.db"
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
    uname = f"regions_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def _set_homeworld_level(player_id: int, level: int) -> None:
    from game.db import db

    conn = db()
    try:
        hw = get_homeworld(player_id=player_id, conn=conn)
        assert hw
        conn.execute("UPDATE planets SET planet_level = ? WHERE id = ?;", (int(level), int(hw["id"])))
        conn.commit()
    finally:
        conn.close()


def test_all_expansion_sites_have_region_key():
    assert len(EXPANSION_SITES) == 5
    regions_used = {site["region_key"] for site in EXPANSION_SITES.values()}
    assert regions_used == {"outer_rim", "ancient_sector", "dark_expanse"}


def test_no_region_is_empty_in_definitions():
    sites_by_region: dict[str, list[str]] = {}
    for key, site in EXPANSION_SITES.items():
        rk = site["region_key"]
        sites_by_region.setdefault(rk, []).append(key)
    assert "frontier_ix" in sites_by_region["outer_rim"]
    assert set(sites_by_region["ancient_sector"]) == {"ancient_relay", "archive_nexus"}
    assert set(sites_by_region["dark_expanse"]) == {"abyss_gate", "void_frontier"}


def test_region_is_dimmed_when_all_sites_locked():
    sites = [
        {"site_key": "frontier_ix", "is_locked": True},
    ]
    assert region_is_dimmed("outer_rim", sites) is True
    assert region_is_dimmed("genesis_core", sites) is False
    assert region_is_dimmed("outer_rim", [{"is_locked": False}]) is False


def test_colony_region_is_genesis_core():
    assert region_for_colony({}) == "genesis_core"


def test_build_regions_payload_four_zones():
    sites = [
        {"region_key": "outer_rim", "is_locked": True},
        {"region_key": "ancient_sector", "is_locked": True},
        {"region_key": "ancient_sector", "is_locked": True},
        {"region_key": "dark_expanse", "is_locked": True},
        {"region_key": "dark_expanse", "is_locked": True},
    ]
    regions = build_regions_payload(expansion_sites=sites, colony_count=1)
    assert len(regions) == len(IMPERIUM_REGIONS)
    assert regions[0]["region_key"] == "genesis_core"
    assert "layout_zone" in regions[0]
    assert "layout_band" not in regions[0]
    assert regions[0]["layout_zone"]["kind"] == "ellipse"
    assert regions[0]["is_dimmed"] is False
    assert regions[1]["region_key"] == "outer_rim"
    assert regions[1]["is_dimmed"] is True
    ancient = next(r for r in regions if r["region_key"] == "ancient_sector")
    assert ancient["teaser_count"] == 2
    dark = next(r for r in regions if r["region_key"] == "dark_expanse")
    assert dark["teaser_count"] == 2


def test_command_map_payload_includes_regions_and_site_regions(regions_db):
    player_id = _create_player()
    _set_homeworld_level(player_id, 4)

    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    assert len(payload["regions"]) == 4
    expansion_nodes = [n for n in payload["nodes"] if n.get("node_kind") == "expansion_site"]
    assert len(expansion_nodes) == 5
    by_region: dict[str, list[str]] = {}
    for node in expansion_nodes:
        by_region.setdefault(node["region_key"], []).append(node["site_key"])
    assert by_region["outer_rim"] == ["frontier_ix"]
    assert set(by_region["ancient_sector"]) == {"ancient_relay", "archive_nexus"}
    assert set(by_region["dark_expanse"]) == {"abyss_gate", "void_frontier"}

    hub = next(n for n in payload["nodes"] if n.get("empire_role_key") == "homeworld")
    assert hub["region_key"] == "genesis_core"
    assert hub["world_x"] == pytest.approx(2000.0)
    assert hub["world_y"] == pytest.approx(2000.0)

    frontier = next(n for n in expansion_nodes if n["site_key"] == "frontier_ix")
    assert frontier["layout_y_pct"] < hub["layout_y_pct"]

    ancient = next(n for n in expansion_nodes if n["site_key"] == "ancient_relay")
    assert ancient["layout_x_pct"] > hub["layout_x_pct"]


def test_outer_rim_not_dimmed_after_frontier_unlock(regions_db):
    player_id = _create_player()
    _set_homeworld_level(player_id, 5)

    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    outer = next(r for r in payload["regions"] if r["region_key"] == "outer_rim")
    assert outer["is_dimmed"] is False


def test_galaxy_command_map_renders_nebula_layer(regions_db, monkeypatch):
    import importlib

    dbmod.DB_PATH = regions_db
    models.DB_PATH = regions_db
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True

    uname = f"regions_ui_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/galaxy?view=command_map&dev=1").get_data(as_text=True)

    assert "galaxy-command-map-sector-layer" in body
    assert "data-command-map-sector-layer" in body
    assert "data-command-map-sector-root" in body
    assert "galaxy-command-map-nebulas" not in body
    assert "galaxy-command-map-region-panel" not in body
    assert "imperium_region_genesis_core" in body or "Genesis Core" in body
    assert "Ancient Relay" in body or "expansion_site_ancient_relay" in body
    assert "Abyss Gate" in body or "expansion_site_abyss_gate" in body
