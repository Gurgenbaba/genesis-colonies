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
