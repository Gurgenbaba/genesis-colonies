"""GC-SCORE-PERF-001 — deferred dirty scores (Phase 2–3)."""

from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest

from game import db as gdb
from game.db import db
from game.models import (
    add_build_job,
    create_user,
    ensure_player_and_homeworld,
    get_homeworld,
    get_planet_buildings,
    init_db,
)
from game.queue_engine import finish_due_work
from game.ranking import get_player_score_row
from game.ranking_worker import (
    FULL_RECONCILE_KEY,
    process_dirty_score_batch,
    run_ranking_worker,
)
from game.runtime_state import set_runtime_value
from game.score_events import (
    apply_score_updates_for_players,
    clear_player_score_dirty_if_version,
    get_player_score_dirty,
    mark_player_score_dirty,
)


@pytest.fixture()
def score_audit_db(tmp_path, monkeypatch):
    db_path = tmp_path / "score_perf_audit.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    # Ordinary worker runs should stay dirty-only in these tests.
    set_runtime_value(FULL_RECONCILE_KEY, str(time.time()))
    yield
    gdb._DB_PATH = None


def _player() -> int:
    ok, err, user = create_user(f"sc_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name=f"Sc{uid}")
    return uid


def test_building_finish_marks_dirty_without_recompute(score_audit_db):
    pid = _player()
    planet_id = int(get_homeworld(pid)["id"])
    now = time.time()
    conn = db()
    try:
        add_build_job(planet_id, "metal_mine", now - 10, now - 1, conn=conn)
        conn.commit()
    finally:
        conn.close()

    with patch("game.ranking.refresh_player_score") as mock_refresh:
        with patch("game.ranking.compute_player_scores") as mock_compute:
            with patch("game.ranking.recompute_and_upsert_score") as mock_recompute:
                result = finish_due_work(
                    player_id=pid,
                    planet_id=planet_id,
                    source="score_audit",
                    update_scores=True,
                    recalc_ranks=True,
                )

    assert int(result["finished"]["buildings"]) >= 1
    assert int(result.get("score_updates") or 0) == 1
    assert result.get("rank_recalculated") is False
    assert mock_refresh.call_count == 0
    assert mock_compute.call_count == 0
    assert mock_recompute.call_count == 0
    assert get_player_score_dirty(pid) is not None
    assert int(get_planet_buildings(planet_id).get("metal_mine") or 0) >= 1


def test_duplicate_invalidations_collapse_to_one_dirty_row(score_audit_db):
    pid = _player()
    mark_player_score_dirty(pid, reason="a")
    first = get_player_score_dirty(pid)
    assert first is not None
    mark_player_score_dirty(pid, reason="b")
    mark_player_score_dirty(pid, reason="c")
    second = get_player_score_dirty(pid)
    assert second is not None
    assert int(second["dirty_version"]) == int(first["dirty_version"]) + 2
    assert float(second["dirty_since"]) == float(first["dirty_since"])


def test_auto_empire_finish_defaults_update_scores_true_but_no_sync_formula():
    import inspect

    from game import auto_empire

    sig = inspect.signature(auto_empire.plan_passive_planet_tick)
    assert sig.parameters["update_scores"].default is True
    src = inspect.getsource(auto_empire._finish_due)
    assert "update_scores=bool(update_scores)" in src


def test_ranking_payload_refresh_false_does_not_recompute(score_audit_db):
    from game.ranking import build_ranking_api_payload

    pid = _player()
    with patch("game.ranking.recompute_and_upsert_score") as mock_recompute:
        with patch("game.ranking.refresh_player_score") as mock_refresh:
            with patch("game.ranking.recalculate_all_rankings") as mock_all:
                with patch("game.score_events.apply_score_updates_for_players") as mock_apply:
                    payload = build_ranking_api_payload(pid, limit=50, refresh=False)

    assert payload is not None
    assert mock_recompute.call_count == 0
    assert mock_refresh.call_count == 0
    assert mock_all.call_count == 0
    assert mock_apply.call_count == 0


def test_worker_refreshes_only_dirty_players(score_audit_db):
    dirty = _player()
    clean = _player()
    mark_player_score_dirty(dirty, reason="test")

    conn = db()
    try:
        result = process_dirty_score_batch(conn=conn, limit=50)
        conn.commit()
    finally:
        conn.close()

    assert int(result["players_updated"]) == 1
    assert int(result["dirty_cleared"]) == 1
    assert int(result["rank_rewrites"]) == 1
    assert get_player_score_dirty(dirty) is None
    assert get_player_score_dirty(clean) is None
    row = get_player_score_row(dirty)
    assert row is not None


def test_failed_refresh_preserves_dirty(score_audit_db):
    pid = _player()
    mark_player_score_dirty(pid, reason="fail")
    version = int(get_player_score_dirty(pid)["dirty_version"])

    conn = db()
    try:
        with patch(
            "game.ranking_worker.refresh_player_score",
            side_effect=RuntimeError("boom"),
        ):
            result = process_dirty_score_batch(conn=conn, limit=10)
        conn.commit()
    finally:
        conn.close()

    assert result["ok"] is False
    dirty = get_player_score_dirty(pid)
    assert dirty is not None
    assert int(dirty["dirty_version"]) == version


def test_concurrent_mutation_does_not_clear_newer_dirty(score_audit_db):
    pid = _player()
    mark_player_score_dirty(pid, reason="v1")
    v1 = int(get_player_score_dirty(pid)["dirty_version"])

    # Simulate worker holding v1 while a mutation bumps to v2.
    mark_player_score_dirty(pid, reason="v2")
    v2 = int(get_player_score_dirty(pid)["dirty_version"])
    assert v2 == v1 + 1

    conn = db()
    try:
        cleared = clear_player_score_dirty_if_version(pid, v1, conn=conn)
        conn.commit()
    finally:
        conn.close()

    assert cleared is False
    remaining = get_player_score_dirty(pid)
    assert remaining is not None
    assert int(remaining["dirty_version"]) == v2


def test_ranking_worker_full_mode_updates_clean_universe(score_audit_db):
    _player()
    result = run_ranking_worker(source="test", force=True, persist=False)
    assert result.get("ok") is True
    assert result.get("mode") == "full"
    assert int(result.get("players_updated") or 0) >= 1
    assert int(result.get("ranks_assigned") or 0) >= 1


def test_finish_then_worker_updates_snapshot(score_audit_db):
    pid = _player()
    planet_id = int(get_homeworld(pid)["id"])
    now = time.time()
    conn = db()
    try:
        add_build_job(planet_id, "metal_mine", now - 10, now - 1, conn=conn)
        conn.commit()
    finally:
        conn.close()

    finish = finish_due_work(
        player_id=pid,
        planet_id=planet_id,
        source="score_audit_e2e",
        update_scores=True,
        recalc_ranks=False,
    )
    assert int(finish["finished"]["buildings"]) >= 1
    assert get_player_score_dirty(pid) is not None

    result = run_ranking_worker(source="test", force=True, persist=False)
    assert result.get("ok") is True
    assert int(result.get("players_updated") or 0) >= 1
    assert get_player_score_dirty(pid) is None
    row = get_player_score_row(pid)
    assert row is not None
    assert int(row.get("score_buildings") or 0) > 0


def test_admin_source_runs_full_reconcile(score_audit_db):
    pid = _player()
    mark_player_score_dirty(pid, reason="before_admin")
    result = run_ranking_worker(source="admin", force=True, persist=False)
    assert result.get("ok") is True
    assert result.get("mode") == "full"
    assert get_player_score_dirty(pid) is None


def test_ordinary_tick_uses_dirty_batch_not_full_reconcile(score_audit_db):
    """GC-SCORE-PERF-001: the regular unforced 10-min cron must stay dirty-batch only."""
    import json

    from game.ranking_worker import RANKING_WORKER_INTERVAL_SEC, RANKING_WORKER_KEY

    dirty = _player()
    clean = _player()
    mark_player_score_dirty(dirty, reason="ordinary_tick")

    # Interval already elapsed -> the 10-min guard allows this run to proceed.
    stale_at = time.time() - RANKING_WORKER_INTERVAL_SEC - 5
    set_runtime_value(
        RANKING_WORKER_KEY,
        json.dumps({"at": stale_at, "ok": True}),
    )
    # score_audit_db fixture already marks FULL_RECONCILE_KEY as "just now",
    # so the daily safety net is not due either.

    result = run_ranking_worker(source="cron", force=False, persist=False)
    assert result.get("ok") is True
    assert result.get("skipped_interval") is False
    assert result.get("mode") == "dirty"
    assert get_player_score_dirty(dirty) is None
    assert get_player_score_dirty(clean) is None
    row = get_player_score_row(dirty)
    assert row is not None


def test_apply_score_updates_never_calls_ranks(score_audit_db):
    pid = _player()
    with patch("game.ranking.recalculate_ranks") as mock_ranks:
        with patch("game.ranking.recompute_and_upsert_score") as mock_recompute:
            n = apply_score_updates_for_players(
                [pid],
                recalc_ranks=True,
                force_rank_recalc=True,
                reason="compat",
            )
    assert n == 1
    assert mock_ranks.call_count == 0
    assert mock_recompute.call_count == 0
    assert get_player_score_dirty(pid) is not None


def test_ranking_worker_interval_is_ten_minutes():
    from game.ranking_worker import RANKING_WORKER_INTERVAL_SEC

    assert int(RANKING_WORKER_INTERVAL_SEC) == 600
