"""
Central queue engine tests.

Run: python -m pytest tests/test_queue_engine.py -v
"""

from __future__ import annotations

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
from game.models import (
    add_build_job,
    create_user,
    get_homeworld,
    get_planet_buildings,
    get_research_levels,
    init_db,
)
from game.queue_engine import (
    clear_request_finish_dedup,
    finish_due_work,
    finish_due_work_once,
)
from flask import Flask

from game.runtime_state import get_queue_tick_status, record_queue_tick_result
from game.tick_runner import run_global_queue_tick, run_queue_tick, run_tick

_flask_app = Flask("queue_engine_test")
from game.ranking import get_player_score_row

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "queue_engine_test.db"
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
        env=env,
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


def test_finish_building_job_once_idempotent(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("build_once")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 100, now - 1, conn=conn)
    conn.commit()
    conn.close()

    before = get_planet_buildings(planet_id)
    lvl_before = int(before.get("metal_mine", 0))

    r1 = finish_due_work(player_id=pid, planet_id=planet_id, source="test")
    _close_db()
    assert r1["finished"]["buildings"] == 1
    assert pid in r1["affected_players"]

    after = get_planet_buildings(planet_id)
    assert int(after.get("metal_mine", 0)) == lvl_before + 1

    r2 = finish_due_work(player_id=pid, planet_id=planet_id, source="test")
    _close_db()
    assert r2["finished"]["buildings"] == 0
    assert int(get_planet_buildings(planet_id).get("metal_mine", 0)) == lvl_before + 1


def test_finish_research_job_once(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("res_once")
    now = time.time()

    conn = db()
    conn.execute(
        """
        INSERT INTO research_queue (user_id, tech_key, start_at, finish_at)
        VALUES (?, ?, ?, ?);
        """,
        (pid, "mining_tech", now - 50, now - 1),
    )
    conn.commit()
    conn.close()

    levels_before = get_research_levels(pid)
    lvl_before = int(levels_before.get("mining_tech", 0))

    result = finish_due_work(player_id=pid, source="test")
    _close_db()
    assert result["finished"]["research"] == 1
    assert pid in result["affected_players"]

    levels_after = get_research_levels(pid)
    assert int(levels_after.get("mining_tech", 0)) == lvl_before + 1


def test_rank_recalculated_once_per_engine_run(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("rank_once")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 10, now - 1, conn=conn)
    conn.commit()
    conn.close()

    with patch("game.score_events.recalculate_ranks") as mock_ranks:
        finish_due_work(player_id=pid, planet_id=planet_id, source="test")
        _close_db()
        assert mock_ranks.call_count == 1


def test_score_updated_after_finish(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("score_upd")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    for _ in range(3):
        add_build_job(planet_id, "metal_mine", now - 20, now - 1, conn=conn)
    conn.commit()
    conn.close()

    result = finish_due_work(player_id=pid, planet_id=planet_id, source="test")
    _close_db()
    assert result["score_updates"] >= 1

    row = get_player_score_row(pid)
    assert row is not None
    assert int(row["score_buildings"]) > 0


def test_finish_due_work_once_dedup_same_scope_flask_g(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("dedup")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 5, now - 1, conn=conn)
    conn.commit()
    conn.close()

    with _flask_app.test_request_context():
        clear_request_finish_dedup()
        with patch("game.queue_engine.finish_due_work") as mock_finish:
            mock_finish.return_value = {
                "ok": True,
                "source": "resources",
                "finished": {"buildings": 1, "research": 0, "shipyard": 0, "defense": 0},
                "affected_players": [pid],
                "affected_planets": [planet_id],
                "score_updates": 1,
                "rank_recalculated": True,
                "duration_ms": 5,
                "errors": [],
            }
            r1 = finish_due_work_once(player_id=pid, source="resources")
            r2 = finish_due_work_once(player_id=pid, source="game_state")
        assert mock_finish.call_count == 1

    assert r1["finished"]["buildings"] == 1
    assert r2["skipped_due_to_dedup"] is True
    assert r2["finished"]["buildings"] == 1
    assert r2["duration_ms"] == 0


def test_finish_due_work_once_dedup_same_scope_integration(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("dedup_int")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 5, now - 1, conn=conn)
    conn.commit()
    conn.close()

    with _flask_app.test_request_context():
        clear_request_finish_dedup()
        r1 = finish_due_work_once(player_id=pid, source="resources")
        r2 = finish_due_work_once(player_id=pid, source="game_state")
    _close_db()

    assert r1["finished"]["buildings"] == 1
    assert r2["skipped_due_to_dedup"] is True
    assert int(get_planet_buildings(planet_id).get("metal_mine", 0)) == 1


def test_planet_scope_covered_by_player_scope_dedup(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("dedup_sub")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 5, now - 1, conn=conn)
    conn.commit()
    conn.close()

    with _flask_app.test_request_context():
        clear_request_finish_dedup()
        finish_due_work_once(player_id=pid, source="player")
        r_planet = finish_due_work_once(player_id=pid, planet_id=planet_id, source="planet")
    _close_db()

    assert r_planet["skipped_due_to_dedup"] is True


def test_different_scopes_run_separately_in_flask(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    p1 = _create_player("dedup_a")
    p2 = _create_player("dedup_b")
    now = time.time()

    conn = db()
    add_build_job(int(get_homeworld(p1)["id"]), "metal_mine", now - 5, now - 1, conn=conn)
    add_build_job(int(get_homeworld(p2)["id"]), "metal_mine", now - 5, now - 1, conn=conn)
    conn.commit()
    conn.close()

    with _flask_app.test_request_context():
        clear_request_finish_dedup()
        with patch("game.queue_engine.finish_due_work") as mock_finish:
            mock_finish.side_effect = lambda **kw: {
                "ok": True,
                "source": kw.get("source"),
                "finished": {"buildings": 1, "research": 0, "shipyard": 0, "defense": 0},
                "affected_players": [kw["player_id"]],
                "affected_planets": [],
                "score_updates": 1,
                "rank_recalculated": True,
                "duration_ms": 1,
                "errors": [],
            }
            finish_due_work_once(player_id=p1, source="a")
            finish_due_work_once(player_id=p2, source="b")
        assert mock_finish.call_count == 2


def test_no_flask_context_no_crash(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("no_flask")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 5, now - 1, conn=conn)
    conn.commit()
    conn.close()

    clear_request_finish_dedup()
    r1 = finish_due_work_once(player_id=pid, source="cli")
    r2 = finish_due_work_once(player_id=pid, source="cli")
    _close_db()

    assert r1["skipped_due_to_dedup"] is False
    assert r2["skipped_due_to_dedup"] is False
    assert r1["finished"]["buildings"] == 1
    assert r2["finished"]["buildings"] == 0


def test_dedup_false_always_runs(temp_db):
    with _flask_app.test_request_context():
        clear_request_finish_dedup()
        with patch("game.queue_engine.finish_due_work") as mock_finish:
            mock_finish.return_value = {
                "ok": True,
                "finished": {"buildings": 0, "research": 0, "shipyard": 0, "defense": 0},
                "affected_players": [],
                "affected_planets": [],
                "score_updates": 0,
                "rank_recalculated": False,
                "duration_ms": 0,
                "errors": [],
            }
            finish_due_work_once(player_id=1, dedup=False)
            finish_due_work_once(player_id=1, dedup=False)
        assert mock_finish.call_count == 2


def test_tick_runner_run_tick(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("cron_batch")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 5, now - 1, conn=conn)
    conn.commit()
    conn.close()

    result = run_tick(scope="due", batch_size=100, source="cron_test", persist=True)
    _close_db()
    assert result["ok"] is True
    assert result["finished"]["buildings"] >= 1
    assert result.get("skipped_due_to_dedup") is False
    assert result["batches"] >= 1

    status = get_queue_tick_status()
    assert status["last_at"] is not None
    assert status["source"] == "cron_test"


def test_tick_runner_global(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("cron")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()

    conn = db()
    add_build_job(planet_id, "metal_mine", now - 5, now - 1, conn=conn)
    conn.commit()
    conn.close()

    result = run_global_queue_tick(source="cron_legacy", persist=False)
    _close_db()
    assert result["ok"] is True
    assert result["finished"]["buildings"] >= 1
    assert result.get("skipped_due_to_dedup") is False


def test_admin_finish_uses_unduped_engine():
    with _flask_app.test_request_context():
        clear_request_finish_dedup()
        with patch("game.admin_api.audit"):
            with patch("game.queue_engine.finish_due_work") as mock_direct:
                with patch("game.queue_engine.finish_due_work_once") as mock_once:
                    mock_direct.return_value = {
                        "ok": True,
                        "source": "admin",
                        "finished": {"buildings": 0, "research": 0, "shipyard": 0, "defense": 0},
                        "affected_players": [],
                        "affected_planets": [],
                        "score_updates": 0,
                        "rank_recalculated": False,
                        "duration_ms": 0,
                        "errors": [],
                    }
                    from game.admin_api import finish_due_queues

                    finish_due_queues(admin_id=1)
        mock_direct.assert_called_once()
        mock_once.assert_not_called()


def test_scoped_finish_not_global(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    p1 = _create_player("scope_a")
    p2 = _create_player("scope_b")
    hw1 = get_homeworld(p1)
    hw2 = get_homeworld(p2)
    now = time.time()

    conn = db()
    add_build_job(int(hw1["id"]), "metal_mine", now - 5, now - 1, conn=conn)
    add_build_job(int(hw2["id"]), "metal_mine", now - 5, now - 1, conn=conn)
    conn.commit()
    conn.close()

    result = finish_due_work(player_id=p1, source="poll")
    _close_db()
    assert p1 in result["affected_players"]
    assert p2 not in result["affected_players"]
    assert result["finished"]["buildings"] == 1

    b2 = int(get_planet_buildings(int(hw2["id"])).get("metal_mine", 0))
    assert b2 == 0


def test_finish_active_planet_due_work_retries_after_dedup(temp_db):
    """Short build times: second pass must finish even if dedup skipped the first noop."""
    from game.queue_engine import finish_active_planet_due_work

    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("short_build")
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    conn = db()
    finish_at = time.time() + 2.0
    add_build_job(planet_id, "metal_mine", finish_at - 1, finish_at, conn=conn)
    conn.commit()
    conn.close()

    with _flask_app.test_request_context():
        clear_request_finish_dedup()
        finish_due_work_once(
            player_id=pid,
            planet_id=planet_id,
            source="noop_probe",
        )
        assert int(get_planet_buildings(planet_id).get("metal_mine", 0)) == 0

        conn = db()
        conn.execute(
            "UPDATE build_queue SET finish_time = ? WHERE planet_id = ?;",
            (time.time() - 0.1, planet_id),
        )
        conn.commit()

        result = finish_active_planet_due_work(
            pid,
            planet_id,
            conn,
            source="short_build_test",
        )
        conn.commit()
        conn.close()

    assert int(result["finished"]["buildings"]) >= 1
    assert int(get_planet_buildings(planet_id).get("metal_mine", 0)) >= 1
