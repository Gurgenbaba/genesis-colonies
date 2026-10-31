"""VOIDFALL Release 1 — production-only and side-effect-safe activation."""

from datetime import datetime, timezone

import game.config as config
import game.db as db_module
import game.server_events as events
from scripts.seed_voidfall_release1 import (
    EFFECTS,
    END_AT,
    SLUG,
    START_AT,
    activate,
    runtime_allowed,
)


def test_voidfall_time_window_and_gameplay_only_effects():
    assert SLUG == "voidfall-rift-opening-2026"
    assert datetime.fromtimestamp(START_AT, tz=timezone.utc).isoformat() == "2026-10-31T00:00:00+00:00"
    assert datetime.fromtimestamp(END_AT, tz=timezone.utc).isoformat() == "2026-11-07T23:59:59+00:00"
    cleaned, error = events.validate_effects(EFFECTS)
    assert error is None
    assert cleaned == [
        {"kind": "expedition_hold_mult", "mult": 0.85},
        {"kind": "research_time_speed", "mult": 1.10},
    ]


def test_voidfall_not_seeded_in_ci_or_sqlite():
    for env, backend in (
        ("test", "postgres"),
        ("development", "postgres"),
        ("production", "sqlite"),
        ("", "postgres"),
    ):
        assert runtime_allowed(env, backend) is False
    assert runtime_allowed("production", "postgres") is True


def test_voidfall_skips_before_touching_ci_database(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setattr(config, "init_config", lambda: None)
    monkeypatch.setattr(db_module, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(db_module, "db", lambda: (_ for _ in ()).throw(AssertionError("must not connect")))
    assert activate(now=START_AT + 100) == "skipped: not PostgreSQL production"


def test_voidfall_preserves_existing_operator_pause(monkeypatch):
    class FakeConn:
        closed = False

        def execute(self, sql, params):
            assert params == (SLUG,)
            return self

        def fetchone(self):
            return {"id": 99, "enabled": 0}

        def close(self):
            self.closed = True

    conn = FakeConn()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(config, "init_config", lambda: None)
    monkeypatch.setattr(db_module, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(db_module, "db", lambda: conn)
    monkeypatch.setattr(events, "schema_ready", lambda _conn: True)
    monkeypatch.setattr(events, "create_event", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not overwrite")))
    assert activate(now=START_AT + 100) == "existing: operator state preserved"
    assert conn.closed is True
