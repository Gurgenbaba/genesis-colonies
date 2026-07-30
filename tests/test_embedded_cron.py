"""
Embedded in-process maintenance cron (Railway SQLite — no external scheduler).

Run: python -m pytest tests/test_embedded_cron.py -q
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture()
def embedded_env(tmp_path, monkeypatch):
    db_file = tmp_path / "game.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    monkeypatch.setenv("GC_EMBEDDED_BACKUP", "1")
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)

    from game.bootstrap import bootstrap_application
    from game.config import init_config
    from game.db import ensure_db_parent_dir
    from game.models import init_db

    init_config()
    ensure_db_parent_dir()
    bootstrap_application(skip_migration_check=True)
    init_db()
    yield db_file

    from game.internal_cron import stop_embedded_cron_for_tests

    stop_embedded_cron_for_tests()


def test_run_maintenance_bag_includes_backup_and_fleet(embedded_env, monkeypatch):
    from game.internal_cron import run_maintenance_bag

    with (
        patch("game.internal_cron.execute_ranking_recompute", return_value={"ok": True, "players_updated": 0}),
        patch("game.internal_cron._maybe_run_fleet_tick", return_value={"ok": True, "skipped_interval": True}),
        patch("game.internal_cron._maybe_run_vote_reengagement", return_value={"ok": True, "skipped_interval": True}),
        patch("game.options.maybe_run_due_account_deletions", return_value={"ok": True, "deleted": 0}),
    ):
        payload = run_maintenance_bag(force=True, source="test")

    assert payload["ok"] is True
    assert "fleet_tick" in payload
    assert "vote_reengagement" in payload
    assert payload["sqlite_backup"]["ok"] is True
    backup_path = Path(payload["sqlite_backup"]["path"])
    assert backup_path.is_file()
    assert backup_path.parent.name == "backups"


def test_sqlite_backup_skips_second_run_same_day(embedded_env):
    from game.internal_cron import maybe_sqlite_volume_backup

    first = maybe_sqlite_volume_backup(force=False)
    assert first["ok"] is True
    second = maybe_sqlite_volume_backup(force=False)
    assert second["ok"] is True
    assert second.get("skipped") == "already_today"


def test_embedded_cron_starts_when_enabled(embedded_env, monkeypatch):
    monkeypatch.setenv("GC_EMBEDDED_CRON", "1")
    monkeypatch.setenv("GC_EMBEDDED_CRON_SEC", "60")

    from game.config import init_config
    from game import internal_cron
    from game.internal_cron import start_embedded_cron_if_enabled, stop_embedded_cron_for_tests

    init_config()
    stop_embedded_cron_for_tests()

    assert start_embedded_cron_if_enabled() is True
    assert internal_cron._EMBEDDED_THREAD is not None
    assert internal_cron._EMBEDDED_THREAD.is_alive()
    # Second start in same process is a no-op
    assert start_embedded_cron_if_enabled() is False
    stop_embedded_cron_for_tests()


def test_embedded_cron_disabled_by_default_outside_production(embedded_env, monkeypatch):
    monkeypatch.delenv("GC_EMBEDDED_CRON", raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    from game.config import init_config, is_embedded_cron_enabled
    from game.internal_cron import start_embedded_cron_if_enabled, stop_embedded_cron_for_tests

    init_config()
    stop_embedded_cron_for_tests()
    assert is_embedded_cron_enabled() is False
    assert start_embedded_cron_if_enabled() is False


def test_maintenance_sidecar_disables_in_process_embedded_cron(embedded_env, monkeypatch):
    """GC-PERF-PROD-002: sidecar owns the bag; gunicorn must not start the thread."""
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "1")  # would enable thread if sidecar ignored

    from game.config import (
        init_config,
        is_embedded_backup_enabled,
        is_embedded_cron_enabled,
        is_maintenance_worker_sidecar_enabled,
    )
    from game.internal_cron import start_embedded_cron_if_enabled, stop_embedded_cron_for_tests

    init_config()
    stop_embedded_cron_for_tests()
    assert is_maintenance_worker_sidecar_enabled() is True
    assert is_embedded_cron_enabled() is False
    assert is_embedded_backup_enabled() is True  # backup still on with sidecar
    assert start_embedded_cron_if_enabled() is False


def test_docker_entrypoint_starts_maintenance_sidecar():
    text = Path(__file__).resolve().parents[1].joinpath("scripts/docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert "run_maintenance_worker.py" in text
    assert "GC_MAINTENANCE_WORKER" in text
    assert "GC_EMBEDDED_CRON=0" in text
    # GC-RANK-CRON-001: dead sidecar must not leave ranking without an owner.
    assert "restarting in 5s" in text
    assert "while true" in text


def test_maintenance_worker_retries_leader_lock(embedded_env, monkeypatch):
    """Deploy volume handoff: first lock miss must not exit permanently."""
    from game import internal_cron

    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    calls = {"lock": 0, "bag": 0, "sleep": []}

    def fake_lock():
        calls["lock"] += 1
        return calls["lock"] >= 2

    def fake_bag(**_kwargs):
        calls["bag"] += 1

    def fake_sleep(sec):
        calls["sleep"].append(float(sec))
        if calls["bag"] >= 1:
            raise StopIteration("done")

    with (
        patch.object(internal_cron, "_acquire_embedded_leader_lock", side_effect=fake_lock),
        patch.object(internal_cron, "run_maintenance_bag", side_effect=fake_bag),
        patch.object(internal_cron.time, "sleep", side_effect=fake_sleep),
    ):
        with pytest.raises(StopIteration):
            internal_cron.run_maintenance_worker_loop(once=False, lock_retry_sec=1.0)

    assert calls["lock"] >= 2
    assert calls["bag"] == 1
    assert any(s == 1.0 for s in calls["sleep"])


def test_maintenance_worker_once_still_exits_without_lock(embedded_env, monkeypatch):
    from game import internal_cron

    with (
        patch.object(internal_cron, "_acquire_embedded_leader_lock", return_value=False),
        patch.object(internal_cron, "run_maintenance_bag") as mock_bag,
    ):
        internal_cron.run_maintenance_worker_loop(once=True, lock_retry_sec=1.0)
    mock_bag.assert_not_called()


def test_backup_file_is_valid_sqlite(embedded_env):
    from game.internal_cron import maybe_sqlite_volume_backup

    result = maybe_sqlite_volume_backup(force=True)
    assert result["ok"] is True
    conn = sqlite3.connect(result["path"])
    try:
        row = conn.execute("SELECT 1").fetchone()
        assert row == (1,)
    finally:
        conn.close()
