"""GC-562 — Evolution unlock gates (expansion sites on Command Map + dashboard teaser)."""

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
from game.planet_evolution.dashboard import build_dashboard_extras
from game.planet_evolution.expansion_gates import (
    build_expansion_unlock_block,
    get_homeworld_level,
    get_next_expansion_unlock,
    list_expansion_sites_for_player,
)
from game.planet_evolution.bootstrap import ensure_planet_evolution
from game.planet_evolution.repository import get_planet_culture, get_planet_dna, get_planet_row
from game.planet_evolution.mechanics import compile_planet_mechanics
from game.planet_evolution.planet_research import get_planet_research_status

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def expansion_gates_db(tmp_path, monkeypatch):
    db_file = tmp_path / "expansion_gates.db"
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
    uname = f"expgate_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def _set_homeworld_level(player_id: int, level: int) -> int:
    from game.db import db

    conn = db()
    try:
        hw = get_homeworld(player_id=player_id, conn=conn)
        assert hw
        hw_id = int(hw["id"])
        conn.execute(
            "UPDATE planets SET planet_level = ? WHERE id = ?;",
            (int(level), hw_id),
        )
        conn.commit()
        return hw_id
    finally:
        conn.close()


def test_homeworld_level_is_gate_source_not_context_planet(expansion_gates_db):
    player_id = _create_player()
    hw_id = _set_homeworld_level(player_id, 4)

    from game.planet_evolution.service import colonize_planet
    from game.db import db

    ok, reason, colony = colonize_planet(player_id, name="High Level Colony", galaxy=1, system=2, position=3)
    assert ok, reason
    colony_id = int(colony["planet_id"])

    conn = db()
    try:
        conn.execute("UPDATE planets SET planet_level = ? WHERE id = ?;", (10, colony_id))
        conn.commit()
        assert get_homeworld_level(player_id, conn=conn) == 4
        sites = list_expansion_sites_for_player(player_id, conn=conn)
    finally:
        conn.close()

    frontier = next(s for s in sites if s["site_key"] == "frontier_ix")
    assert frontier["is_locked"] is True
    assert frontier["required_homeworld_level"] == 5
    assert hw_id != colony_id


def test_level_4_shows_locked_frontier_ix_on_command_map(expansion_gates_db):
    player_id = _create_player()
    _set_homeworld_level(player_id, 4)

    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    expansion_nodes = [n for n in payload["nodes"] if n.get("node_kind") == "expansion_site"]
    assert len(expansion_nodes) == 5
    frontier = next(n for n in expansion_nodes if n["site_key"] == "frontier_ix")
    assert frontier["is_locked"] is True
    assert frontier["region_key"] == "outer_rim"
    assert frontier["empire_role_icon"] == "🔒"

    locked_edges = [e for e in payload["edges"] if e["edge_type"] == "expansion_locked"]
    assert len(locked_edges) == 5
    assert payload["expansion"]["homeworld_level"] == 4
    assert payload["expansion"]["next_unlock"]["site_key"] == "frontier_ix"


def test_level_5_unlocks_frontier_ix_on_command_map(expansion_gates_db):
    player_id = _create_player()
    _set_homeworld_level(player_id, 5)

    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    frontier = next(n for n in payload["nodes"] if n.get("site_key") == "frontier_ix")
    assert frontier["is_unlocked"] is True
    assert frontier["is_locked"] is False
    assert frontier["is_newly_discovered"] is True
    assert frontier["empire_role_icon"] == "🌌"

    unlocked_edges = [e for e in payload["edges"] if e["edge_type"] == "expansion_unlocked"]
    assert len(unlocked_edges) == 1
    assert payload["expansion"]["next_unlock"]["site_key"] == "ancient_relay"
    outer = next(r for r in payload["regions"] if r["region_key"] == "outer_rim")
    assert outer["is_dimmed"] is False


def test_newly_discovered_only_at_exact_unlock_level(expansion_gates_db):
    player_id = _create_player()
    _set_homeworld_level(player_id, 6)

    from game.db import db

    conn = db()
    try:
        sites = list_expansion_sites_for_player(player_id, conn=conn)
    finally:
        conn.close()

    frontier = next(s for s in sites if s["site_key"] == "frontier_ix")
    assert frontier["is_unlocked"] is True
    assert frontier["is_newly_discovered"] is False


def test_command_map_expansion_nodes_have_no_planet_id(expansion_gates_db):
    player_id = _create_player()
    _set_homeworld_level(player_id, 4)

    from game.planet_evolution.service import colonize_planet
    from game.db import db

    ok, reason, _ = colonize_planet(player_id, name="Spoke", galaxy=1, system=2, position=3)
    assert ok, reason

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    colonies = [n for n in payload["nodes"] if n.get("node_kind", "colony") == "colony"]
    expansion = [n for n in payload["nodes"] if n.get("node_kind") == "expansion_site"]
    assert colonies
    assert expansion
    assert all("planet_id" in n for n in colonies)
    assert all("planet_id" not in n for n in expansion)

    by_id = {int(n["planet_id"]): n for n in colonies}
    assert len(by_id) == len(colonies)


def test_dashboard_shows_next_unlock_on_homeworld(expansion_gates_db):
    player_id = _create_player()
    hw_id = _set_homeworld_level(player_id, 4)

    from game.db import db

    conn = db()
    try:
        ensure_planet_evolution(hw_id, conn)
        conn.commit()
        planet = get_planet_row(hw_id, conn=conn)
        dash = build_dashboard_extras(
            hw_id,
            planet=planet,
            dna=get_planet_dna(hw_id, conn=conn),
            culture=get_planet_culture(hw_id, conn=conn),
            mechanics=compile_planet_mechanics(hw_id, conn=conn),
            research=get_planet_research_status(hw_id, conn=conn),
            active_event=None,
            conn=conn,
        )
        block = build_expansion_unlock_block(player_id, conn=conn)
    finally:
        conn.close()

    assert dash["expansion_unlock"]["visible"] is True
    assert dash["expansion_unlock"]["next_unlock"]["site_key"] == "frontier_ix"
    assert block["next_unlock"]["required_homeworld_level"] == 5
    assert get_next_expansion_unlock(4)["levels_remaining"] == 1


def test_dashboard_colony_shows_genesis_ark_hint(expansion_gates_db):
    player_id = _create_player()
    _set_homeworld_level(player_id, 4)

    from game.planet_evolution.service import colonize_planet
    from game.db import db

    ok, reason, colony = colonize_planet(player_id, name="Outpost", galaxy=1, system=3, position=4)
    assert ok, reason
    colony_id = int(colony["planet_id"])

    conn = db()
    try:
        ensure_planet_evolution(colony_id, conn)
        conn.commit()
        planet = get_planet_row(colony_id, conn=conn)
        dash = build_dashboard_extras(
            colony_id,
            planet=planet,
            dna=get_planet_dna(colony_id, conn=conn),
            culture=get_planet_culture(colony_id, conn=conn),
            mechanics=compile_planet_mechanics(colony_id, conn=conn),
            research=get_planet_research_status(colony_id, conn=conn),
            active_event=None,
            conn=conn,
        )
    finally:
        conn.close()

    exp = dash["expansion_unlock"]
    assert exp["visible"] is True
    assert exp["show_genesis_ark_hint"] is True
    assert exp["on_homeworld"] is False
    assert exp["next_unlock"]["site_key"] == "frontier_ix"


def test_galaxy_command_map_renders_locked_expansion_node(expansion_gates_db, monkeypatch):
    import importlib

    dbmod.DB_PATH = expansion_gates_db
    models.DB_PATH = expansion_gates_db
    import app as app_module

    importlib.reload(app_module)

    uname = f"expgate_ui_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    player_id = int(user["id"])
    _set_homeworld_level(player_id, 4)

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/galaxy?view=command_map").get_data(as_text=True)

    assert "galaxy-command-map-node--locked" in body
    assert "galaxy-command-map-edge--expansion_locked" in body
    assert "Frontier IX" in body or "expansion_site_frontier_ix" in body


def test_galaxy_command_map_renders_newly_discovered_badge(expansion_gates_db, monkeypatch):
    import importlib

    dbmod.DB_PATH = expansion_gates_db
    models.DB_PATH = expansion_gates_db
    import app as app_module

    importlib.reload(app_module)

    uname = f"expgate_new_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    player_id = int(user["id"])
    _set_homeworld_level(player_id, 5)

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/galaxy?view=command_map").get_data(as_text=True)

    assert "galaxy-command-map-node--new" in body
    assert "galaxy-command-map-node-badge--new" in body
