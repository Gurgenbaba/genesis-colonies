"""
GC-PERF-PG-MIGRATE-001 — SQLite→Postgres importer contracts.

Default (no Postgres): module load, table order, dry-run helpers.
Optional live import: set GC_TEST_POSTGRES_URL (+ GC_DB_BACKEND=postgres).

Run:
  python -m pytest tests/test_gc_perf_pg_migrate_001.py -v
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pg_import_sqlite.py"


def _load_importer():
    spec = importlib.util.spec_from_file_location("pg_import_sqlite", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pg_import_sqlite"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def importer():
    return _load_importer()


def test_ticket_doc_and_core_status(importer):
    doc = ROOT / "docs" / "GC_PERF_PG_MIGRATE_001.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "GC-PERF-PG-MIGRATE-001" in text
    assert "Dry-run" in text or "dry-run" in text
    assert "out-of-scope" in text.lower() or "Out-of-scope" in text or "out of scope" in text.lower()
    assert "Railway" in text or "STAGING" in text
    assert "Blind" in text or "blind" in text

    import re

    core = (ROOT / "docs" / "GC_PERF_CORE.md").read_text(encoding="utf-8")
    assert "GC-PERF-PG-MIGRATE-001" in core
    assert "GC_PERF_PG_MIGRATE_001.md" in core
    # Script+doc deliverable marked in progress or done (not cutover).
    assert re.search(
        r"GC_PERF_PG_MIGRATE_001\.md.*\|.*\|.*(🔄|✅)",
        core,
    ), "MIGRATE-001 status in GC_PERF_CORE should be 🔄 or ✅"


def test_importer_module_loads(importer):
    assert SCRIPT.is_file()
    assert hasattr(importer, "compute_import_table_order")
    assert hasattr(importer, "ROOT_PRIORITY")
    assert hasattr(importer, "SKIP_TABLES")
    assert "migration_history" in importer.SKIP_TABLES
    assert importer.ROOT_PRIORITY[0] == "users"


def test_table_order_parents_before_children(importer):
    tables = ["users", "players", "planets", "planet_buildings", "build_queue"]
    edges = [
        ("players", "users"),
        ("planets", "players"),
        ("planet_buildings", "planets"),
        ("build_queue", "planets"),
    ]
    order = importer.compute_import_table_order(tables, edges)
    assert order.index("users") < order.index("players")
    assert order.index("players") < order.index("planets")
    assert order.index("planets") < order.index("planet_buildings")
    assert order.index("planets") < order.index("build_queue")
    assert set(order) == set(tables)


def test_table_order_detects_cycle(importer):
    with pytest.raises(ValueError, match="cycle|unresolved"):
        importer.compute_import_table_order(
            ["a", "b"],
            [("a", "b"), ("b", "a")],
        )


def test_dry_run_on_fixture_sqlite(importer, tmp_path):
    db_path = tmp_path / "migrate_src.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL
            );
            CREATE TABLE players (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                FOREIGN KEY (id) REFERENCES users(id)
            );
            CREATE TABLE planets (
                id INTEGER PRIMARY KEY,
                player_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                FOREIGN KEY (player_id) REFERENCES players(id)
            );
            CREATE TABLE migration_history (
                id INTEGER PRIMARY KEY,
                name TEXT
            );
            INSERT INTO users (id, username) VALUES (1, 'admin');
            INSERT INTO players (id, name) VALUES (1, 'admin');
            INSERT INTO planets (id, player_id, name) VALUES (10, 1, 'Home');
            INSERT INTO migration_history (id, name) VALUES (1, '001_init.sql');
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = importer.build_dry_run_report(db_path)
    assert report.ok
    assert report.dry_run is True
    assert "migration_history" not in report.table_order
    assert report.table_order.index("users") < report.table_order.index("players")
    assert report.table_order.index("players") < report.table_order.index("planets")
    by_name = {s.table: s for s in report.stats}
    assert by_name["users"].sqlite_rows == 1
    assert by_name["planets"].sqlite_rows == 1


def test_dry_run_cli_exits_zero(importer, tmp_path):
    db_path = tmp_path / "cli.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE game_settings (key TEXT PRIMARY KEY, value TEXT);")
        conn.execute(
            "INSERT INTO game_settings (key, value) VALUES ('universe_speed', '1');"
        )
        conn.commit()
    finally:
        conn.close()
    rc = importer.main(["--dry-run", "--sqlite", str(db_path)])
    assert rc == 0


def test_require_postgres_config_fails_clearly(importer, monkeypatch):
    monkeypatch.delenv("GC_DB_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GC_TEST_POSTGRES_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        importer.require_postgres_config()
    msg = str(exc.value)
    assert "GC_DB_BACKEND" in msg

    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    with pytest.raises(SystemExit) as exc2:
        importer.require_postgres_config()
    assert "DATABASE_URL" in str(exc2.value) or "GC_TEST_POSTGRES_URL" in str(exc2.value)


def test_fk_edges_from_sqlite(importer, tmp_path):
    db_path = tmp_path / "fk.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE players (
                id INTEGER PRIMARY KEY,
                FOREIGN KEY (id) REFERENCES users(id)
            );
            """
        )
        conn.commit()
        tables = importer.list_sqlite_tables(conn)
        edges = importer.sqlite_fk_edges(conn, tables)
    finally:
        conn.close()
    assert ("players", "users") in edges


@pytest.mark.skipif(
    not (
        __import__("os").environ.get("GC_TEST_POSTGRES_URL", "").strip().lower().startswith(
            "postgres"
        )
    ),
    reason="Set GC_TEST_POSTGRES_URL for live Postgres import smoke",
)
def test_live_import_optional(importer, tmp_path, monkeypatch):
    """Opt-in: tiny fixture → wipe+import against staging PG."""
    from tests.pg_fixtures import close_pg_pool, postgres_test_url

    url = postgres_test_url()
    assert url
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("GC_TEST_POSTGRES_URL", url)

    db_path = tmp_path / "live_src.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL DEFAULT 0
            );
            INSERT INTO users (id, username, password_hash, created_at)
            VALUES (900001, 'migrate_probe_user', 'x', 1);
            """
        )
        conn.commit()
    finally:
        conn.close()

    close_pg_pool()
    report = importer.run_import(sqlite_path=db_path, wipe=False, dry_run=False)
    # Without wipe, staging likely has rows → expect clear nonempty error OR success
    # if users empty. Either way importer must not crash opaquely.
    assert isinstance(report.stats, list) or report.errors
    if report.errors:
        assert any("wipe" in e.lower() or "rows" in e.lower() for e in report.errors)
