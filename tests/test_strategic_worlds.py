"""GC-581 — Strategic world metadata and Command Map presentation."""

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
from game.planet_evolution.strategic_worlds import (
    STRATEGIC_WORLD_TYPES,
    STRATEGIC_WORLD_TYPE_DEFS,
    build_strategic_world_field,
    list_strategic_world_type_defs,
    strategic_world_name_key,
    strategic_world_type_for_coords,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"

REQUIRED_FIELD_KEYS = (
    "name_key",
    "world_type",
    "world_key",
    "is_colonizable",
    "is_expedition",
    "is_expedition_prepared",
    "is_salvage",
    "expedition_count",
    "familiarity_status",
    "familiarity_label_key",
    "next_milestone",
    "type_key",
    "role_icon",
    "risk_level",
    "risk_key",
    "promise_key",
    "reward_hint_key",
    "future_action_key",
    "owner_key",
)


@pytest.fixture()
def strategic_worlds_db(tmp_path, monkeypatch):
    db_file = tmp_path / "strategic_worlds.db"
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
    uname = f"sw_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def test_all_strategic_world_types_define_metadata():
    assert len(STRATEGIC_WORLD_TYPES) == 8
    defs = list_strategic_world_type_defs()
    assert len(defs) == 8
    for row in defs:
        world_type = row["world_type"]
        assert world_type in STRATEGIC_WORLD_TYPE_DEFS
        meta = STRATEGIC_WORLD_TYPE_DEFS[world_type]
        for key in ("type_key", "role_icon", "risk_level", "risk_key", "promise_key", "reward_hint_key", "future_action_key"):
            assert meta.get(key), f"{world_type} missing {key}"
        assert meta["promise_key"].startswith("strategic_world_promise_")
        assert meta["reward_hint_key"].startswith("strategic_world_reward_")
        assert meta["future_action_key"].startswith("strategic_world_future_")


def test_build_strategic_world_field_is_deterministic():
    first = build_strategic_world_field(1820.5, 2140.0)
    second = build_strategic_world_field(1820.5, 2140.0)
    assert first == second
    progress_keys = {
        "expedition_count",
        "familiarity_status",
        "familiarity_label_key",
        "next_milestone",
    }
    for key in REQUIRED_FIELD_KEYS:
        if key in progress_keys and not first.get("is_expedition"):
            continue
        assert key in first, f"missing {key}"
    assert str(first["world_key"]).startswith("field:")


def test_strategic_world_type_and_name_vary_by_coords():
    types = {strategic_world_type_for_coords(x * 113.0, x * 97.0) for x in range(24)}
    names = {strategic_world_name_key(x * 113.0, x * 97.0) for x in range(24)}
    assert len(types) >= 3
    assert len(names) >= 3
    assert all(t in STRATEGIC_WORLD_TYPE_DEFS for t in types)


def test_command_map_payload_world_fields_are_strategic(strategic_worlds_db):
    player_id = _create_player()
    from game.db import db

    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()

    fields = [n for n in payload["nodes"] if n.get("node_kind") == "world_field"]
    assert fields
    progress_keys = {
        "expedition_count",
        "familiarity_status",
        "familiarity_label_key",
        "next_milestone",
    }
    for sample in fields:
        for key in REQUIRED_FIELD_KEYS:
            if key in progress_keys and not sample.get("is_expedition"):
                continue
            assert key in sample, f"world_field missing {key}"
    assert fields[0]["owner_key"] == "strategic_world_owner_unclaimed"


def test_galaxy_template_renders_strategic_world_inspector(strategic_worlds_db, monkeypatch):
    dbmod.DB_PATH = strategic_worlds_db
    models.DB_PATH = strategic_worlds_db
    import app as app_module

    importlib.reload(app_module)

    player_id = _create_player()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    body = client.get("/galaxy?view=command_map").get_data(as_text=True)
    assert "gc-world-inspector-modal" in body
    assert "data-world-field-inspect" in body
    assert "data-strategic-name" in body
    assert "data-strategic-world-key" in body
    assert "data-strategic-colonizable" in body
    assert "data-strategic-promise" in body
    assert "data-strategic-risk" in body
    assert "strategic_world_name_helios_prime" in body or "Helios Prime" in body
