"""
GC-DB-POSTGRES-003-P1 — maintenance-bag PostgreSQL blockers.

Covers:
- gather_score_stats NUMERIC casts + numeric MAX for TEXT big-scores
- World Boss defeated_at CASE WHEN ? = 1
- migration_history survival across importer --wipe
- maintenance bag ok=true on disposable Postgres

Live PG: set GC_TEST_POSTGRES_URL (or DATABASE_URL=postgresql://…).
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.pg_fixtures import close_pg_pool, postgres_test_url, requires_postgres

HUGE = "999999999999999999999999"
LEX_TRAP = "9"
MID = "100"


def _load_importer():
    script = ROOT / "scripts" / "pg_import_sqlite.py"
    spec = importlib.util.spec_from_file_location("pg_import_sqlite_p1", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pg_import_sqlite_p1"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_score_rows(conn=None) -> None:
    """Insert TEXT score_total rows that trap lexicographic MAX.

    Opens its own connection when ``conn`` is None (preferred for SQLite —
    ``create_user`` also opens a write connection).
    """
    from game.db import db
    from game.models import create_user

    owns = conn is None
    if owns:
        conn = db()
    try:
        for i, score in enumerate((LEX_TRAP, MID, HUGE), start=1):
            uname = f"P1sc{i}{int(time.time() * 1000) % 100000}{i}"
            ok, reason, user = create_user(uname, f"Pass!{i}xx99Ab")
            assert ok and user, f"create_user failed: {reason}"
            pid = int(user["id"])
            conn.execute(
                """
                INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
                VALUES (?, ?, '0', '0', ?)
                ON CONFLICT(player_id) DO UPDATE SET
                    score_total = excluded.score_total,
                    updated_at = excluded.updated_at;
                """,
                (pid, score, time.time()),
            )
        conn.commit()
    finally:
        if owns:
            conn.close()


def test_gather_score_stats_numeric_max_sqlite(tmp_path, monkeypatch):
    db_file = tmp_path / "score_stats.db"
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SECRET_KEY", "p1-test-secret-key-xxxxxxxxxxxxxxxx")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")

    from game.config import init_config
    from game.db import db, gather_score_stats

    init_config()
    conn = db()
    try:
        conn.execute(
            """
            CREATE TABLE player_scores (
                player_id INTEGER PRIMARY KEY,
                score_total TEXT NOT NULL DEFAULT '0',
                score_buildings TEXT NOT NULL DEFAULT '0',
                score_research TEXT NOT NULL DEFAULT '0',
                updated_at REAL
            );
            """
        )
        for i, score in enumerate((LEX_TRAP, MID, HUGE), start=1):
            conn.execute(
                "INSERT INTO player_scores (player_id, score_total, updated_at) VALUES (?, ?, ?);",
                (i, score, time.time()),
            )
        conn.commit()
        stats = gather_score_stats(conn)
    finally:
        conn.close()

    assert stats["scores_rows"] == 3
    assert stats["scores_positive"] == 3
    assert stats["top_score"] == int(HUGE)
    assert isinstance(stats["top_score"], int)


@requires_postgres
def test_gather_score_stats_numeric_max_postgres(pg_parity_db):
    from game.db import db, gather_score_stats

    _seed_score_rows()
    conn = db()
    try:
        stats = gather_score_stats(conn)
    finally:
        conn.close()
        close_pg_pool()

    assert stats["scores_positive"] >= 3
    assert stats["top_score"] == int(HUGE)
    assert isinstance(stats["top_score"], int)


@requires_postgres
def test_world_boss_defeated_at_case_when_equals_one_postgres(pg_parity_db):
    """Execute the CASE WHEN ? = 1 pattern against live Postgres."""
    from game.db import db

    conn = db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gc_p1_wb_case_probe (
                id BIGSERIAL PRIMARY KEY,
                defeated_at DOUBLE PRECISION,
                updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
            );
            """
        )
        conn.execute("DELETE FROM gc_p1_wb_case_probe;")
        conn.execute(
            "INSERT INTO gc_p1_wb_case_probe (defeated_at, updated_at) VALUES (NULL, 1.0);"
        )
        conn.commit()
        row = conn.execute("SELECT id FROM gc_p1_wb_case_probe LIMIT 1;").fetchone()
        eid = int(row["id"] if isinstance(row, dict) else row[0])

        # defeated=False → preserve NULL
        ts_keep = 111.0
        conn.execute(
            """
            UPDATE gc_p1_wb_case_probe
            SET defeated_at = CASE WHEN ? = 1 THEN ? ELSE defeated_at END,
                updated_at = ?
            WHERE id = ?;
            """,
            (0, ts_keep, ts_keep, eid),
        )
        conn.commit()
        after_false = conn.execute(
            "SELECT defeated_at FROM gc_p1_wb_case_probe WHERE id = ?;",
            (eid,),
        ).fetchone()
        val_false = after_false["defeated_at"] if isinstance(after_false, dict) else after_false[0]
        assert val_false is None

        # defeated=True → set timestamp
        ts_set = 222.0
        conn.execute(
            """
            UPDATE gc_p1_wb_case_probe
            SET defeated_at = CASE WHEN ? = 1 THEN ? ELSE defeated_at END,
                updated_at = ?
            WHERE id = ?;
            """,
            (1, ts_set, ts_set, eid),
        )
        conn.commit()
        after_true = conn.execute(
            "SELECT defeated_at FROM gc_p1_wb_case_probe WHERE id = ?;",
            (eid,),
        ).fetchone()
        val_true = after_true["defeated_at"] if isinstance(after_true, dict) else after_true[0]
        assert float(val_true) == ts_set
    finally:
        try:
            conn.execute("DROP TABLE IF EXISTS gc_p1_wb_case_probe;")
            conn.commit()
        except Exception:
            pass
        conn.close()
        close_pg_pool()


def test_world_boss_source_uses_equals_one_predicate():
    source = (ROOT / "game" / "world_boss.py").read_text(encoding="utf-8")
    assert "CASE WHEN ? = 1 THEN ? ELSE defeated_at END" in source
    assert source.count("CASE WHEN ? THEN ? ELSE defeated_at END") == 0
    assert "WHEN ? = 1 THEN ? ELSE resonance_initiator_player_id END" in source
    assert "WHEN ? = 1 THEN ? ELSE finisher_player_id END" in source
    assert "COALESCE(excluded.alliance_id, alliance_id)" not in source
    assert "COALESCE(excluded.alliance_id, world_boss_contributions.alliance_id)" in source or (
        "world_boss_contributions.alliance_id" in source
        and "excluded.alliance_id" in source
    )


@requires_postgres
def test_migration_history_survives_importer_wipe(tmp_path, monkeypatch, pg_parity_database_url):
    """Importer SKIP_TABLES + wipe order must leave migration_history intact."""
    importer = _load_importer()
    assert "migration_history" in importer.SKIP_TABLES

    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", pg_parity_database_url)
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "p1-test-secret-key-xxxxxxxxxxxxxxxx")
    monkeypatch.setenv("APP_ENV", "development")

    from game.db_pg import connect_postgres_migration

    close_pg_pool()
    pg = connect_postgres_migration()
    try:
        before_rows = [
            (str(r["name"]), int(r["applied_at"]))
            for r in pg.execute(
                "SELECT name, applied_at FROM migration_history ORDER BY name;"
            ).fetchall()
        ]
        assert before_rows, "target must already be migrated"

        # Same wipe surface the importer uses: application tables only (no history).
        wipe_order = [
            "users",
            "players",
            "planets",
            "player_scores",
            "build_queue",
            "research_queue",
            "fleet_movements",
        ]
        wipe_order = [t for t in wipe_order if t not in importer.SKIP_TABLES]
        assert "migration_history" not in wipe_order
        importer.wipe_postgres_tables(pg, wipe_order)

        after_rows = [
            (str(r["name"]), int(r["applied_at"]))
            for r in pg.execute(
                "SELECT name, applied_at FROM migration_history ORDER BY name;"
            ).fetchall()
        ]
    finally:
        pg.close()
        close_pg_pool()

    assert before_rows == after_rows

    # Confirm importer table discovery never schedules migration_history.
    sqlite_path = tmp_path / "wipe_src.db"
    sconn = sqlite3.connect(str(sqlite_path))
    sconn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE migration_history (id INTEGER PRIMARY KEY, name TEXT, applied_at INTEGER);
        INSERT INTO users (id, username) VALUES (1, 'a');
        INSERT INTO migration_history (id, name, applied_at) VALUES (1, '006_x.sql', 1);
        """
    )
    sconn.commit()
    tables = importer.list_sqlite_tables(sconn)
    sconn.close()
    assert "users" in tables
    assert "migration_history" not in tables



@requires_postgres
def test_maintenance_bag_ok_on_postgres(pg_parity_db):
    """Ranking/world-boss bag path must not raise PG datatype mismatches."""
    from game.db import db, gather_score_stats
    from game.internal_cron import run_maintenance_bag
    from game.models import create_user

    conn = db()
    try:
        ok, _, user = create_user(f"bag_p1_{int(time.time())}", "BagPass!xx")
        assert ok and user
        pid = int(user["id"])
        conn.execute(
            """
            INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
            VALUES (?, ?, '0', '0', ?)
            ON CONFLICT(player_id) DO UPDATE SET
                score_total = excluded.score_total,
                updated_at = excluded.updated_at;
            """,
            (pid, HUGE, time.time()),
        )
        conn.commit()
        # Prove gather_score_stats itself is healthy before bag.
        stats = gather_score_stats(conn)
        assert stats["top_score"] >= int(HUGE) or stats["scores_positive"] >= 1
    finally:
        conn.close()

    payload = run_maintenance_bag(force=True, source="maintenance_worker")
    assert payload.get("ok") is True, payload
    assert "DatatypeMismatch" not in str(payload)
    assert "CASE/WHEN" not in str(payload).upper()
    close_pg_pool()


def test_gather_score_stats_sql_uses_numeric_cast():
    source = (ROOT / "game" / "db.py").read_text(encoding="utf-8")
    assert "CAST(score_total AS NUMERIC)" in source
    assert "COALESCE(score_total, 0) > 0" not in source
    # top_score must not use SQL MAX on TEXT (lexicographic / float loss).
    assert "MAX(score_total)" not in source
    assert "int(str(raw)" in source or 'int(str(raw)' in source
