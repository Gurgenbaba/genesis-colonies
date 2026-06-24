"""
Ranking worker tests — batch score refresh, interval guard.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import add_build_job, create_user, get_homeworld, get_planet_buildings, init_db
from game.queue_engine import finish_due_work
from game.ranking import get_player_score_row, upsert_player_scores
from game.ranking_worker import (
    RANKING_WORKER_INTERVAL_SEC,
    RANKING_WORKER_KEY,
    run_ranking_worker,
    seconds_until_ranking_worker_allowed,
)
from game.runtime_state import set_runtime_value

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "ranking_worker_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _close_db() -> None:
    try:
        db().close()
    except Exception:
        pass


def _create_player(username: str) -> int:
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    _close_db()
    return int(user["id"])


def test_finish_due_work_skips_live_score_by_default(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("worker_skip")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 20, now - 1, conn=conn)
    conn.commit()
    conn.close()

    with patch("game.score_events.apply_score_updates_for_players") as mock_scores:
        result = finish_due_work(player_id=pid, planet_id=planet_id, source="test")
        _close_db()
        assert result["finished"]["buildings"] >= 1
        mock_scores.assert_not_called()
        assert result["score_updates"] == 0

    row = get_player_score_row(pid)
    assert row is None or int(row.get("score_buildings") or 0) == 0


def test_ranking_worker_recomputes_after_queue_finish(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("worker_run")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 20, now - 1, conn=conn)
    conn.commit()
    conn.close()

    finish_result = finish_due_work(player_id=pid, planet_id=planet_id, source="test")
    _close_db()
    assert finish_result["finished"]["buildings"] >= 1

    buildings = get_planet_buildings(planet_id)
    assert int(buildings.get("metal_mine") or 0) >= 1

    result = run_ranking_worker(source="test", force=True, persist=False)
    _close_db()
    assert result["ok"] is True
    assert int(result.get("players_updated") or 0) >= 1

    row = get_player_score_row(pid)
    assert row is not None
    assert int(row["score_buildings"]) > 0


def test_ranking_worker_interval_guard(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    recent = {
        "at": int(time.time()),
        "source": "test",
        "ok": True,
        "players_updated": 1,
        "ranks_assigned": 1,
        "duration_ms": 5,
        "errors": [],
    }
    set_runtime_value(RANKING_WORKER_KEY, json.dumps(recent))
    _close_db()

    wait = seconds_until_ranking_worker_allowed()
    assert wait > 0
    assert wait <= RANKING_WORKER_INTERVAL_SEC

    with patch("game.ranking_worker.recalculate_all_rankings") as mock_full:
        skipped = run_ranking_worker(source="test", force=False, persist=False)
        _close_db()
        mock_full.assert_not_called()
        assert skipped.get("skipped_interval") is True


def test_ranking_worker_force_bypasses_interval(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("worker_force")
    upsert_player_scores(pid, {"total_score": 10, "building_score": 10, "research_score": 0})
    _close_db()

    recent = {
        "at": int(time.time()),
        "source": "test",
        "ok": True,
        "players_updated": 1,
        "ranks_assigned": 1,
        "duration_ms": 5,
        "errors": [],
    }
    set_runtime_value(RANKING_WORKER_KEY, json.dumps(recent))
    _close_db()

    with patch(
        "game.ranking_worker.recalculate_all_rankings",
        return_value={
            "ok": True,
            "players_updated": 1,
            "ranks_assigned": 1,
            "duration_ms": 1,
            "errors": [],
        },
    ) as mock_full:
        run_ranking_worker(source="test", force=True, persist=False)
        _close_db()
        mock_full.assert_called_once()
