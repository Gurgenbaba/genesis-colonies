"""
Ranking worker tests — batch score refresh, interval guard, CLI fail-fast.
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
from game.db import db, get_connection, resolve_db_path
from game.models import add_build_job, create_user, get_homeworld, get_planet_buildings, init_db
from game.queue_engine import finish_due_work
from game.ranking import get_player_score_row, upsert_player_scores
from game.ranking_worker import (
    RANKING_WORKER_INTERVAL_SEC,
    RANKING_WORKER_KEY,
    _cli_main,
    run_ranking_worker,
    seconds_until_ranking_worker_allowed,
    worker_exit_code,
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


def test_finish_due_work_updates_scores_by_default(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("worker_live")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 20, now - 1, conn=conn)
    conn.commit()
    conn.close()

    result = finish_due_work(player_id=pid, planet_id=planet_id, source="test")
    _close_db()
    assert result["finished"]["buildings"] >= 1
    assert result["score_updates"] >= 1

    row = get_player_score_row(pid)
    assert row is not None
    assert int(row.get("score_buildings") or 0) > 0


def test_apply_score_updates_throttles_rank_recalc(temp_db):
    from game.score_events import apply_score_updates_for_players

    _run_migrate(temp_db)
    init_db()
    _close_db()

    p1 = _create_player("throttle_a")
    p2 = _create_player("throttle_b")
    conn = db()

    with patch("game.score_events.recalculate_ranks") as mock_ranks:
        apply_score_updates_for_players([p1], conn=conn, reason="test_a")
        apply_score_updates_for_players([p2], conn=conn, reason="test_b")
        assert mock_ranks.call_count == 1

        apply_score_updates_for_players(
            [p2],
            conn=conn,
            reason="test_force",
            force_rank_recalc=True,
        )
        assert mock_ranks.call_count == 2

    conn.close()
    _close_db()


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
    assert finish_result["score_updates"] >= 1

    buildings = get_planet_buildings(planet_id)
    assert int(buildings.get("metal_mine") or 0) >= 1

    row_before_worker = get_player_score_row(pid)
    assert row_before_worker is not None
    assert int(row_before_worker["score_buildings"]) > 0

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


def test_ranking_worker_skip_does_not_persist_interval_marker(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("skip_marker")
    _close_db()

    recent_at = int(time.time())
    set_runtime_value(
        RANKING_WORKER_KEY,
        json.dumps(
            {
                "at": recent_at,
                "source": "test",
                "ok": True,
                "players_updated": 1,
                "ranks_assigned": 1,
                "duration_ms": 5,
                "errors": [],
            }
        ),
    )
    _close_db()

    with patch("game.ranking_worker.recalculate_all_rankings") as mock_full:
        skipped = run_ranking_worker(source="test", force=False, persist=True)
        _close_db()
        mock_full.assert_not_called()
        assert skipped.get("skipped_interval") is True

    from game.runtime_state import get_runtime_value

    stored = json.loads(get_runtime_value(RANKING_WORKER_KEY) or "{}")
    assert int(stored.get("at") or 0) == recent_at


def _clear_universe_data() -> None:
    conn = db()
    for table in (
        "player_scores",
        "planet_buildings",
        "planets",
        "players",
        "users",
    ):
        try:
            conn.execute(f"DELETE FROM {table};")
        except Exception:
            pass
    conn.commit()
    conn.close()


def test_ranking_worker_empty_db_exits_without_allow_empty(temp_db):
    _run_migrate(temp_db)
    _clear_universe_data()
    _close_db()

    result = run_ranking_worker(source="test", force=True, persist=False, allow_empty=False)
    _close_db()
    assert result["ok"] is False
    assert worker_exit_code(result, allow_empty=False) == 1
    assert "empty database" in (result.get("errors") or [""])[0]


def test_ranking_worker_empty_db_allowed_with_flag(temp_db):
    _run_migrate(temp_db)
    _clear_universe_data()
    _close_db()

    with patch(
        "game.ranking_worker.recalculate_all_rankings",
        return_value={
            "ok": True,
            "players_updated": 0,
            "ranks_assigned": 0,
            "duration_ms": 1,
            "errors": [],
        },
    ):
        result = run_ranking_worker(source="test", force=True, persist=False, allow_empty=True)
    _close_db()
    assert result["ok"] is True


def test_ranking_worker_commits_score_changes(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("worker_commit")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 20, now - 1, conn=conn)
    conn.commit()
    conn.close()

    finish_due_work(player_id=pid, planet_id=planet_id, source="test")
    _close_db()

    result = run_ranking_worker(source="test", force=True, persist=False)
    _close_db()
    assert result["ok"] is True
    assert int(result.get("scores_updated") or 0) >= 1

    conn2 = db()
    row = conn2.execute(
        "SELECT score_buildings FROM player_scores WHERE player_id = ?",
        (pid,),
    ).fetchone()
    conn2.close()
    assert row is not None
    assert int(row["score_buildings"]) > 0


def test_ranking_worker_uses_canonical_db_helper(temp_db, monkeypatch):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("worker_db")
    upsert_player_scores(pid, {"total_score": 5, "building_score": 5, "research_score": 0})
    _close_db()

    seen_paths: list[str] = []

    original_db = dbmod.db

    def tracking_db():
        conn = original_db()
        seen_paths.append(str(resolve_db_path()))
        return conn

    monkeypatch.setattr(dbmod, "db", tracking_db)
    monkeypatch.setattr("game.ranking_worker.db", tracking_db)

    run_ranking_worker(source="test", force=True, persist=False)
    _close_db()
    assert seen_paths
    assert str(temp_db) in seen_paths[0]


def test_get_connection_alias_matches_db(temp_db, monkeypatch):
    monkeypatch.setenv("GC_DB_PATH", str(temp_db))
    _run_migrate(temp_db)
    init_db()
    _close_db()
    conn = get_connection()
    try:
        conn.execute("SELECT 1;")
    finally:
        conn.close()


def test_cli_main_empty_db_exits_one(temp_db, monkeypatch):
    _run_migrate(temp_db)
    _clear_universe_data()
    _close_db()

    monkeypatch.setattr("game.bootstrap.bootstrap_application", lambda **_: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ranking_worker", "--source", "test", "--force"],
    )

    assert _cli_main() == 1


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


def test_ranking_worker_failed_run_does_not_block_guard(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("worker_fail_guard")
    upsert_player_scores(pid, {"total_score": 10, "building_score": 10, "research_score": 0})
    _close_db()

    failed = {
        "at": int(time.time()),
        "source": "test",
        "ok": False,
        "players_updated": 0,
        "ranks_assigned": 0,
        "duration_ms": 5,
        "errors": ["boom"],
    }
    set_runtime_value(RANKING_WORKER_KEY, json.dumps(failed))
    _close_db()

    wait = seconds_until_ranking_worker_allowed()
    assert wait == 0.0

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
        result = run_ranking_worker(source="test", force=False, persist=False)
        _close_db()
        mock_full.assert_called_once()
        assert result.get("skipped_interval") is not True


def test_ranking_worker_failed_run_not_persisted_as_guard_marker(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("worker_fail_persist")
    upsert_player_scores(pid, {"total_score": 10, "building_score": 10, "research_score": 0})
    _close_db()

    with patch(
        "game.ranking_worker.recalculate_all_rankings",
        return_value={
            "ok": False,
            "players_updated": 0,
            "ranks_assigned": 0,
            "duration_ms": 1,
            "errors": ["partial failure"],
        },
    ):
        result = run_ranking_worker(source="test", force=True, persist=True)
    _close_db()
    assert result.get("ok") is False

    from game.runtime_state import get_runtime_value

    assert get_runtime_value(RANKING_WORKER_KEY) is None
