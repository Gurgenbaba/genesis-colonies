"""GC-565 — Chokepoint gate nodes on Command Map."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db
from game.planet_evolution.chokepoints import (
    CHOKEPOINTS,
    CHOKEPOINT_CHAIN,
    gate_chain_for_region,
    list_chokepoints_for_map,
)
from game.planet_evolution.command_map import build_command_map_payload

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def chokepoints_db(tmp_path, monkeypatch):
    db_file = tmp_path / "chokepoints.db"
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
    uname = f"gate_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def test_static_chokepoint_definitions():
    assert len(CHOKEPOINTS) == 3
    assert CHOKEPOINT_CHAIN == ["helios_corridor", "ancient_threshold", "void_rift"]
    helios = CHOKEPOINTS["helios_corridor"]
    assert helios["connects_regions"] == ["genesis_core", "outer_rim"]
    assert helios["layout_radius_world"] == 480.0


def test_gate_chain_for_region():
    assert gate_chain_for_region("outer_rim") == ["helios_corridor"]
    assert gate_chain_for_region("ancient_sector") == ["helios_corridor", "ancient_threshold"]
    assert gate_chain_for_region("dark_expanse") == [
        "helios_corridor",
        "ancient_threshold",
        "void_rift",
    ]
    assert gate_chain_for_region("genesis_core") == []


def test_list_chokepoints_for_map_layout():
    rows = list_chokepoints_for_map()
    assert len(rows) == 3
    assert rows[0]["chokepoint_key"] == "helios_corridor"
    assert rows[0]["node_kind"] == "chokepoint"
    assert rows[-1]["chokepoint_key"] == "void_rift"


def test_command_map_includes_chokepoint_nodes(chokepoints_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    chokepoints = [n for n in payload["nodes"] if n.get("node_kind") == "chokepoint"]
    assert len(chokepoints) == 3
    keys = {n["chokepoint_key"] for n in chokepoints}
    assert keys == {"helios_corridor", "ancient_threshold", "void_rift"}
    assert payload["chokepoints"]
    helios = next(n for n in chokepoints if n["chokepoint_key"] == "helios_corridor")
    assert helios["layout_y_pct"] < 52.0


def test_frontier_ix_routes_through_helios_not_direct_hub(chokepoints_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    hub = next(
        n for n in payload["nodes"]
        if n.get("empire_role_key") == "homeworld"
    )
    frontier = next(
        n for n in payload["nodes"]
        if n.get("site_key") == "frontier_ix"
    )
    helios = next(
        n for n in payload["nodes"]
        if n.get("chokepoint_key") == "helios_corridor"
    )

    hub_key = f"planet:{hub['planet_id']}"
    frontier_key = "site:frontier_ix"
    helios_key = "chokepoint:helios_corridor"

    edge_pairs = {
        (e["source_key"], e["target_key"])
        for e in payload["edges"]
    }
    assert (hub_key, helios_key) in edge_pairs
    assert (helios_key, frontier_key) in edge_pairs
    assert (hub_key, frontier_key) not in edge_pairs

    choke_links = [e for e in payload["edges"] if e["edge_type"] == "chokepoint_link"]
    assert len(choke_links) >= 2
    expansion_tail = [
        e for e in payload["edges"]
        if e["edge_type"] in ("expansion_locked", "expansion_unlocked")
    ]
    assert any(
        e["source_key"] == helios_key and e["target_key"] == frontier_key
        for e in expansion_tail
    )


def test_dark_expanse_sites_route_through_full_gate_chain(chokepoints_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    void_site = next(n for n in payload["nodes"] if n.get("site_key") == "void_frontier")
    edge_pairs = {(e["source_key"], e["target_key"]) for e in payload["edges"]}

    assert ("chokepoint:helios_corridor", "chokepoint:ancient_threshold") in edge_pairs
    assert ("chokepoint:ancient_threshold", "chokepoint:void_rift") in edge_pairs
    assert ("chokepoint:void_rift", "site:void_frontier") in edge_pairs
    assert void_site["region_key"] == "dark_expanse"


def test_galaxy_command_map_renders_chokepoint_nodes(chokepoints_db, monkeypatch):
    import importlib

    dbmod.DB_PATH = chokepoints_db
    models.DB_PATH = chokepoints_db
    import app as app_module

    importlib.reload(app_module)

    uname = f"gate_ui_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    player_id = int(user["id"])

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/galaxy?view=command_map&dev=1").get_data(as_text=True)

    assert "galaxy-command-map-node--chokepoint" in body
    assert "data-chokepoint-key=\"helios_corridor\"" in body
    assert "galaxy-command-map-edge--chokepoint_link" in body
