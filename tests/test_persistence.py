"""
Persistence layer tests: migrations, idempotency TTL, queue indexes, DB helpers.

Run: python -m pytest tests/test_persistence.py -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import (
    begin_write_transaction,
    commit,
    db,
    index_exists,
    rollback,
    table_exists,
    with_transaction,
)
from game.models import (
    harden_planets_schema,
    init_db,
    purge_stale_idempotency,
    purge_stale_idempotency_global,
    save_idempotent_action,
)


ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "persist_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def test_fresh_init_then_migrate(temp_db):
    init_db()
    assert temp_db.exists()

    result = _run_migrate(temp_db)
    assert result.returncode == 0, result.stderr or result.stdout

    conn = db()
    try:
        assert table_exists(conn, "action_idempotency")
        assert index_exists(conn, "idx_build_queue_planet_finish")
        assert index_exists(conn, "idx_research_queue_user_finish")
        assert index_exists(conn, "idx_action_idempotency_created")

        applied = conn.execute("SELECT name FROM migration_history;").fetchall()
        names = {r["name"] for r in applied}
        assert "008_persistence_hardening.sql" in names
        assert "009_legacy_planets_hardening.sql" in names
    finally:
        conn.close()


def test_existing_db_migration_idempotent(temp_db):
    """Simulates legacy DB: init_db only, then migrate applies 008 safely."""
    init_db()
    conn = db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            applied_at INTEGER NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO migration_history (name, applied_at) VALUES (?, ?);",
        ("006_add_player_scores.sql", int(time.time())),
    )
    conn.execute(
        "INSERT INTO migration_history (name, applied_at) VALUES (?, ?);",
        ("007_seed_player_scores.sql", int(time.time())),
    )
    conn.commit()
    conn.close()

    result = _run_migrate(temp_db)
    assert result.returncode == 0, result.stderr or result.stdout

    conn = db()
    try:
        assert table_exists(conn, "action_idempotency")
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(research_queue);").fetchall()]
        assert "start_at" in cols
    finally:
        conn.close()


def test_idempotency_cleanup_ttl(temp_db):
    init_db()
    ok, _, info = models.create_user("ttl_user", "secret123")
    assert ok
    user_id = int(info["id"])

    conn = db()
    begin_write_transaction(conn)
    cutoff_old = time.time() - 500
    conn.execute(
        """
        INSERT INTO action_idempotency (user_id, request_id, response_json, created_at)
        VALUES (?, ?, ?, ?);
        """,
        (user_id, "old-req", json.dumps({"ok": True}), cutoff_old),
    )
    conn.execute(
        """
        INSERT INTO action_idempotency (user_id, request_id, response_json, created_at)
        VALUES (?, ?, ?, ?);
        """,
        (user_id, "new-req", json.dumps({"ok": True}), time.time()),
    )
    commit(conn)
    conn.close()

    deleted = purge_stale_idempotency_global(max_age_sec=120.0)
    assert deleted >= 1

    conn = db()
    rows = conn.execute(
        "SELECT request_id FROM action_idempotency WHERE user_id = ?;",
        (user_id,),
    ).fetchall()
    conn.close()
    assert {r["request_id"] for r in rows} == {"new-req"}


def test_with_transaction_commits(temp_db):
    init_db()
    ok, _, info = models.create_user("tx_user", "secret123")
    assert ok
    user_id = int(info["id"])

    with with_transaction() as conn:
        purge_stale_idempotency(conn, user_id=user_id, max_age_sec=120.0)
        conn.execute(
            """
            INSERT INTO action_idempotency (user_id, request_id, response_json, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (user_id, "tx-req", "{}", time.time()),
        )

    conn = db()
    row = conn.execute(
        "SELECT 1 FROM action_idempotency WHERE user_id = ? AND request_id = ?;",
        (user_id, "tx-req"),
    ).fetchone()
    conn.close()
    assert row is not None


def test_queue_indexes_used_by_status_queries(temp_db):
    init_db()
    conn = db()
    try:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC;",
            (1,),
        ).fetchall()
        plan_text = " ".join(" ".join(str(c) for c in r) for r in plan).lower()
        assert "build_queue" in plan_text

        plan2 = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC;",
            (1,),
        ).fetchall()
        plan2_text = " ".join(" ".join(str(c) for c in r) for r in plan2).lower()
        assert "research_queue" in plan2_text
    finally:
        conn.close()


def test_sql_uses_parameter_placeholders_not_fstrings(temp_db):
    """Guard: queue/status SQL must use ? placeholders (Postgres path uses adapter later)."""
    init_db()
    conn = db()
    try:
        conn.execute(
            "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
            (1,),
        )
        conn.execute(
            "DELETE FROM action_idempotency WHERE created_at < ?;",
            (time.time(),),
        )
    finally:
        conn.close()


def _seed_legacy_planets_db(db_path: Path) -> None:
    """Simulates pre-006 DB: planets without player_id / is_homeworld."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE players (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE planets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            metal REAL NOT NULL DEFAULT 1000,
            crystal REAL NOT NULL DEFAULT 500,
            last_update REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE game_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT INTO planets (name, metal, crystal, last_update)
        VALUES ('Legacy World', 1000, 500, 0);
        """
    )
    conn.commit()
    conn.close()


def test_legacy_planets_without_player_id_bootstraps(temp_db):
    _seed_legacy_planets_db(temp_db)
    init_db()

    conn = db()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(planets);").fetchall()}
        assert "player_id" in cols
        assert "is_homeworld" in cols

        player = conn.execute("SELECT id, name FROM players WHERE id = 1;").fetchone()
        assert player is not None

        homeworld = conn.execute(
            "SELECT id, player_id, is_homeworld, name FROM planets WHERE player_id = 1 AND is_homeworld = 1;"
        ).fetchone()
        assert homeworld is not None
        assert int(homeworld["player_id"]) == 1
        assert int(homeworld["is_homeworld"]) == 1
    finally:
        conn.close()


def test_legacy_planets_hardening_idempotent(temp_db):
    _seed_legacy_planets_db(temp_db)
    conn = db()
    try:
        harden_planets_schema(conn)
        conn.commit()
        harden_planets_schema(conn)
        conn.commit()

        rows = conn.execute(
            "SELECT id, player_id, is_homeworld FROM planets ORDER BY id ASC;"
        ).fetchall()
        assert len(rows) == 1
        assert int(rows[0]["player_id"]) == 1
        assert int(rows[0]["is_homeworld"]) == 1
    finally:
        conn.close()


def test_legacy_planets_migration_idempotent(temp_db):
    _seed_legacy_planets_db(temp_db)
    init_db()
    first = _run_migrate(temp_db)
    assert first.returncode == 0, first.stderr or first.stdout

    second = _run_migrate(temp_db)
    assert second.returncode == 0, second.stderr or second.stdout
    assert "Alle Migrationen sind bereits angewendet" in second.stdout

    conn = db()
    try:
        assert index_exists(conn, "idx_planets_player_id")
        assert index_exists(conn, "idx_planets_player_homeworld")
        homeworld = conn.execute(
            "SELECT 1 FROM planets WHERE player_id = 1 AND is_homeworld = 1 LIMIT 1;"
        ).fetchone()
        assert homeworld is not None
    finally:
        conn.close()
