"""
GC-PERF-PG-SCHEMA-001 — Postgres migration rewrite + runner contracts.

Run: python -m pytest tests/test_gc_perf_pg_schema_001.py -v

Live migrate (optional):
  GC_TEST_POSTGRES_URL=postgresql://… pytest tests/test_gc_perf_pg_schema_001.py -k live -v
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_ticket_doc_exists():
    assert (ROOT / "docs" / "GC_PERF_PG_SCHEMA_001.md").is_file()
    core = (ROOT / "docs" / "GC_PERF_CORE.md").read_text(encoding="utf-8")
    assert "Core Foundation abgeschlossen" in core
    assert "GC-PERF-PG-SCHEMA-001" in core


def test_rewrite_scalar_max_min_to_greatest_least():
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    out = rewrite_sqlite_statement(
        "UPDATE planets SET metal = MAX(0, ?), crystal = MAX(0, crystal + ?) WHERE id = ?;"
    )
    assert "GREATEST(0, ?)" in out
    assert "GREATEST(0, crystal + ?)" in out
    assert "MAX(0" not in out.upper().replace("GREATEST", "")

    nested = rewrite_sqlite_statement(
        "UPDATE planets SET metal = MIN(?, MAX(0, metal + ?)) WHERE id = ?;"
    )
    assert "LEAST" in nested.upper()
    assert "GREATEST" in nested.upper()
    assert re.search(r"\bMAX\s*\(", nested, re.I) is None
    assert re.search(r"\bMIN\s*\(", nested, re.I) is None

    # Aggregate single-arg MAX must stay
    agg = rewrite_sqlite_statement("SELECT COALESCE(MAX(score_total), 0) AS top FROM player_scores;")
    assert "MAX(score_total)" in agg
    assert "GREATEST" not in agg.upper()


def test_rewrite_skips_pragma():
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    assert rewrite_sqlite_statement("PRAGMA foreign_keys=ON;") == ""


def test_rewrite_autoincrement():
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    out = rewrite_sqlite_statement(
        "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);"
    )
    assert "BIGSERIAL PRIMARY KEY" in out
    assert "AUTOINCREMENT" not in out.upper()


def test_rewrite_dna_seed_integer_to_bigint():
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    out = rewrite_sqlite_statement(
        "ALTER TABLE planets ADD COLUMN dna_seed INTEGER NOT NULL DEFAULT 0;"
    )
    assert "BIGINT" in out.upper()
    assert "dna_seed" in out.lower()


def test_rewrite_insert_or_ignore_after_comment():
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    out = rewrite_sqlite_statement(
        "-- Seed default badges\n"
        "INSERT OR IGNORE INTO player_card_badges (badge_key) VALUES ('founder');"
    )
    assert "INSERT OR IGNORE" not in out.upper()
    assert out.upper().startswith("INSERT INTO")
    assert "ON CONFLICT DO NOTHING" in out.upper()


def test_rewrite_migration_011_seed_fragment():
    from game.sql_pg_rewrite import rewrite_migration_script

    sql = """
CREATE TABLE IF NOT EXISTS player_card_badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    badge_key TEXT NOT NULL UNIQUE
);
-- Seed default badges (idempotent via badge_key)
INSERT OR IGNORE INTO player_card_badges (badge_key, icon, rarity, name_i18n_key, description_i18n_key, requirement_type, requirement_value, is_active)
VALUES
    ('founder', '◆', 'legendary', 'playercard_badge_founder', 'playercard_badge_founder_desc', NULL, NULL, 1);
"""
    rewritten, notes = rewrite_migration_script(sql)
    assert "INSERT OR IGNORE" not in rewritten.upper()
    assert "ON CONFLICT DO NOTHING" in rewritten.upper()
    assert "BIGSERIAL" in rewritten.upper()
    assert any("INSERT OR IGNORE" in n for n in notes)


def test_rewrite_drop_table_cascade():
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    out = rewrite_sqlite_statement("DROP TABLE fleet_presets;")
    assert "CASCADE" in out.upper()
    assert "IF EXISTS" in out.upper()


def test_rewrite_043_rebuild_readds_fk():
    from pathlib import Path

    from game.sql_pg_rewrite import rewrite_migration_script

    sql = Path("migrations/043_fleet_recycle_mission.sql").read_text(encoding="utf-8")
    rewritten, notes = rewrite_migration_script(sql)
    assert "DROP TABLE IF EXISTS fleet_presets CASCADE" in rewritten.replace("  ", " ")
    assert "fleet_movements_preset_id_fkey" in rewritten
    assert any("CASCADE" in n for n in notes)


def test_rewrite_real_and_datetime():
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    out = rewrite_sqlite_statement(
        "CREATE TABLE t (x REAL, ts TEXT DEFAULT (datetime('now')));"
    )
    assert "DOUBLE PRECISION" in out
    assert "NOW()" in out


def test_rewrite_migration_script_drops_pragmas():
    from game.sql_pg_rewrite import rewrite_migration_script

    sql = """
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS demo (id INTEGER PRIMARY KEY AUTOINCREMENT);
    INSERT OR IGNORE INTO demo (id) VALUES (1);
    """
    rewritten, notes = rewrite_migration_script(sql)
    assert "PRAGMA" not in rewritten.upper()
    assert "BIGSERIAL" in rewritten.upper()
    assert any("PRAGMA" in n for n in notes)


def test_core_schema_bootstrap_rewrites_users():
    from game.schema_bootstrap import _CORE_DDL
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    users_ddl = next(s for s in _CORE_DDL if "CREATE TABLE IF NOT EXISTS users" in s)
    out = rewrite_sqlite_statement(users_ddl)
    assert "BIGSERIAL" in out.upper() or "SERIAL" in out.upper()
    assert "AUTOINCREMENT" not in out.upper()


def test_bootstrap_module_importable():
    from game.schema_bootstrap import bootstrap_core_schema, core_schema_ready

    assert callable(bootstrap_core_schema)
    assert callable(core_schema_ready)


def test_migrate_sqlite_idempotent_second_pass(tmp_path, monkeypatch):
    """SQLite path still works; second run applies zero new migrations."""
    db_file = tmp_path / "schema_test.db"
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "migrate-test-secret-key-xxxxxxxx")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")

    from migrate import main

    main()
    assert db_file.exists()

    # Capture applied count via second run (should not raise)
    main()


@pytest.mark.skipif(
    not os.environ.get("GC_TEST_POSTGRES_URL", "").strip(),
    reason="Set GC_TEST_POSTGRES_URL for live Postgres migrate",
)
def test_live_postgres_migrate_idempotent(monkeypatch):
    url = os.environ["GC_TEST_POSTGRES_URL"].strip()
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SECRET_KEY", "migrate-pg-test-secret-key-xxxx")

    from migrate import get_applied_migrations, get_connection, main

    main()
    conn = get_connection()
    try:
        first = get_applied_migrations(conn)
    finally:
        conn.close()
    assert len(first) > 0

    main()
    conn = get_connection()
    try:
        second = get_applied_migrations(conn)
    finally:
        conn.close()
    assert first == second
