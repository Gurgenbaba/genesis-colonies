from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "159_debris_expiry_index.sql"


def test_debris_expiry_index_matches_worker_delete_predicate() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    combat = (ROOT / "game" / "combat.py").read_text(encoding="utf-8")

    assert "CREATE INDEX IF NOT EXISTS idx_debris_fields_updated_at" in migration
    assert "ON debris_fields(updated_at)" in migration

    start = combat.index("def expire_due_debris_fields(")
    block = combat[start : start + 1800]
    assert "DELETE FROM debris_fields" in block
    assert "WHERE updated_at <= ?" in block


def test_debris_expiry_index_migration_is_idempotent() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE debris_fields (
                id INTEGER PRIMARY KEY,
                galaxy INTEGER NOT NULL,
                system INTEGER NOT NULL,
                position INTEGER NOT NULL,
                metal REAL NOT NULL DEFAULT 0,
                crystal REAL NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(galaxy, system, position)
            )
            """
        )
        conn.executescript(migration)
        conn.executescript(migration)

        index_names = {row[1] for row in conn.execute("PRAGMA index_list('debris_fields')")}
        assert "idx_debris_fields_updated_at" in index_names

        columns = [row[2] for row in conn.execute("PRAGMA index_info('idx_debris_fields_updated_at')")]
        assert columns == ["updated_at"]
    finally:
        conn.close()
