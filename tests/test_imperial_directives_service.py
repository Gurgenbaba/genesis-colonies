"""GC-911B — Imperial Directives service layer tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.directives.service import (
    get_imperial_directives_state,
    get_imperial_directives_summary,
    serialize_directive_row,
)
from game.models import create_user

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def id_db(tmp_path, monkeypatch):
    db_file = tmp_path / "imperial_directives_service.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
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
    yield db_file


def _create_player() -> int:
    import uuid

    ok, _reason, user = create_user(f"id_svc_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    return int(user["id"])


def test_get_imperial_directives_state_shape(id_db):
    conn = db()
    try:
        player_id = _create_player()
        conn.commit()

        state = get_imperial_directives_state(
            player_id,
            conn=conn,
            now=1_718_800_000.0,
        )
        assert state["ready"] is True
        assert len(state["directives"]) == 4
        assert state["daily_reset_at"] > 1_718_800_000
        assert state["weekly_reset_at"] > 1_718_800_000

        first = state["directives"][0]
        assert first["id"] > 0
        assert first["title_key"].startswith("id_def_")
        assert first["target"] >= 1
        assert first["progress"] == 0
        assert first["status"] == "active"
        assert isinstance(first["rewards_preview"], list)
        assert first["rewards_preview"]
    finally:
        conn.close()


def test_get_imperial_directives_summary_shape(id_db):
    conn = db()
    try:
        player_id = _create_player()
        conn.commit()

        summary = get_imperial_directives_summary(
            player_id,
            conn=conn,
            now=1_718_800_000.0,
        )
        assert summary["ready"] is True
        assert summary["daily_total"] == 3
        assert summary["weekly_total"] == 1
        assert summary["claimable_count"] == 0
        assert "directives" not in summary
        assert summary["daily_reset_at"] > 1_718_800_000
    finally:
        conn.close()


def test_serialize_directive_row_claimable(id_db):
    row = {
        "id": 7,
        "definition_key": "upgrade_buildings",
        "cadence": "daily",
        "rarity": "common",
        "target_value": 3,
        "progress_value": 3,
        "status": "completed",
        "reward_json": json.dumps(
            {
                "container_key": "container_basic",
                "container_amount": 1,
                "boosters": [{"item_key": "booster_build_5m", "amount": 1}],
                "rarity": "common",
            }
        ),
        "expires_at": 1_719_000_000,
        "completed_at": 1_718_900_000,
        "claimed_at": None,
    }
    defn = {
        "category": "economy",
        "title_key": "id_def_upgrade_buildings_title",
        "description_key": "id_def_upgrade_buildings_desc",
        "objective_kind": "count",
    }
    payload = serialize_directive_row(row, defn)
    assert payload["claimable"] is True
    assert payload["category"] == "economy"
    assert len(payload["rewards_preview"]) == 2
