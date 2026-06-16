"""GC-567B — Region landmarks on Command Map."""

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
from game.planet_evolution.influence_layer import select_influence_nodes
from game.planet_evolution.region_landmarks import REGION_LANDMARKS, list_landmarks_for_map

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def landmarks_db(tmp_path, monkeypatch):
    db_file = tmp_path / "landmarks.db"
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
    uname = f"lm_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def test_region_landmarks_static_definitions():
    assert len(REGION_LANDMARKS) == 9
    rows = list_landmarks_for_map()
    assert len(rows) == 9
    by_region: dict[str, list[str]] = {}
    for row in rows:
        by_region.setdefault(row["region_key"], []).append(row["landmark_key"])
    assert len(by_region["outer_rim"]) == 3
    assert len(by_region["ancient_sector"]) == 3
    assert len(by_region["dark_expanse"]) == 3
    assert "broken_relay" in by_region["outer_rim"]
    assert "void_signal" in by_region["dark_expanse"]


def test_command_map_includes_landmark_nodes(landmarks_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    landmarks = [n for n in payload["nodes"] if n.get("node_kind") == "landmark"]
    assert len(landmarks) == 9
    assert len(payload["landmarks"]) == 9
    broken = next(n for n in landmarks if n["landmark_key"] == "broken_relay")
    assert broken["flavor_key"] == "landmark_broken_relay_flavor"
    assert broken["is_unlockable"] is False
    assert broken["layout_x_pct"] > 0


def test_landmarks_excluded_from_influence_and_edges(landmarks_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    influence_keys = set(payload["influence"].get("node_keys") or [])
    landmark_keys = {n["node_key"] for n in payload["nodes"] if n.get("node_kind") == "landmark"}
    assert landmark_keys
    assert not influence_keys & landmark_keys

    influence_nodes = select_influence_nodes(payload["nodes"])
    assert all(n.get("node_kind", "colony") == "colony" for n in payload["nodes"] if n["node_key"] in influence_keys)

    for edge in payload["edges"]:
        assert edge["source_key"] not in landmark_keys
        assert edge["target_key"] not in landmark_keys


def test_no_landmarks_in_genesis_core(landmarks_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    landmarks = [n for n in payload["nodes"] if n.get("node_kind") == "landmark"]
    assert all(n["region_key"] != "genesis_core" for n in landmarks)


def test_galaxy_command_map_renders_landmarks(landmarks_db, monkeypatch):
    import importlib

    dbmod.DB_PATH = landmarks_db
    models.DB_PATH = landmarks_db
    import app as app_module

    importlib.reload(app_module)

    uname = f"lm_ui_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/galaxy?view=command_map").get_data(as_text=True)

    assert "galaxy-command-map-node--landmark" in body
    assert "gc-world-inspector-modal" in body
    assert "data-landmark-inspect" in body
    assert "data-landmark-key=\"broken_relay\"" in body
    assert "landmark_broken_relay_flavor" in body or "187 years ago" in body or "187 Jahren" in body
