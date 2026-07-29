"""GC-567 — Expansion site metadata and Command Map presentation."""

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
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.expansion_gates import EXPANSION_SITES, list_expansion_sites_for_player

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"

REQUIRED_STATIC_KEYS = (
    "site_type",
    "type_key",
    "promise_key",
    "risk_level",
    "risk_key",
    "reward_hint_key",
    "future_role_key",
)

REQUIRED_OUTPUT_KEYS = REQUIRED_STATIC_KEYS + ("region_label_key",)


@pytest.fixture()
def expansion_sites_v2_db(tmp_path, monkeypatch):
    db_file = tmp_path / "expansion_sites_v2.db"
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
    uname = f"expsite_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def test_all_expansion_sites_define_v2_metadata():
    assert len(EXPANSION_SITES) == 5
    for site_key, site in EXPANSION_SITES.items():
        for key in REQUIRED_STATIC_KEYS:
            assert key in site, f"{site_key} missing {key}"
        assert site["promise_key"].startswith("expansion_site_promise_")
        assert site["reward_hint_key"].startswith("expansion_site_reward_")
        assert site["future_role_key"].startswith("expansion_site_future_role_")


def test_list_expansion_sites_includes_metadata(expansion_sites_v2_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        sites = list_expansion_sites_for_player(player_id, conn=conn)
    finally:
        conn.close()

    frontier = next(s for s in sites if s["site_key"] == "frontier_ix")
    for key in REQUIRED_OUTPUT_KEYS:
        assert key in frontier
    assert frontier["site_type"] == "outpost"
    assert frontier["risk_level"] == "low"
    assert frontier["empire_subtitle_key"] == "expansion_site_promise_frontier_ix"


def test_command_map_nodes_carry_site_metadata(expansion_sites_v2_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    expansion_nodes = [n for n in payload["nodes"] if n.get("node_kind") == "expansion_site"]
    assert len(expansion_nodes) == 5
    void_frontier = next(n for n in expansion_nodes if n["site_key"] == "void_frontier")
    assert void_frontier["site_type"] == "frontier"
    assert void_frontier["risk_level"] == "extreme"
    assert void_frontier["promise_key"] == "expansion_site_promise_void_frontier"


def test_locked_site_shows_promise_not_generic_locked_label(expansion_sites_v2_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        conn.execute("UPDATE planets SET planet_level = 4 WHERE player_id = ? AND is_homeworld = 1;", (player_id,))
        conn.commit()
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    ancient = next(n for n in payload["nodes"] if n.get("site_key") == "ancient_relay")
    assert ancient["is_locked"] is True
    assert ancient["empire_subtitle_key"] == "expansion_site_promise_ancient_relay"
    assert ancient["empire_subtitle_key"] != "expansion_site_locked"


def test_galaxy_command_map_renders_site_inspector(expansion_sites_v2_db, monkeypatch):
    import importlib

    dbmod.DB_PATH = expansion_sites_v2_db
    models.DB_PATH = expansion_sites_v2_db
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True

    uname = f"expsite_ui_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/galaxy?view=command_map&dev=1").get_data(as_text=True)

    assert "data-command-map-site-inspector" in body
    assert "data-expansion-site-inspect" in body
    assert "data-site-promise=" in body
    assert "data-site-reward=" in body
    assert "galaxy-command-map-node-type" in body
    assert "expansion_site_promise_frontier_ix" in body or "First outpost beyond" in body or "Erster Außenposten" in body
