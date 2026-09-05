"""P1 PostgreSQL schema-final numeric hardening contract."""

from __future__ import annotations

from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]


def test_migration_runner_has_post_numbered_postgres_finalizer():
    source = (ROOT / "migrate.py").read_text(encoding="utf-8")

    assert "def finalize_postgres_schema(" in source
    assert "finalize_postgres_schema(conn)" in source

    loop_pos = source.index("for path in new_migrations:")
    final_pos = source.index("finalize_postgres_schema(conn)", loop_pos)
    assert final_pos > loop_pos

    # The pass must live outside the new_migrations branch so an already
    # migrated schema can be repaired by a plain second migrate.py run.
    no_new_pos = source.index('if not new_migrations:')
    assert final_pos > no_new_pos


def test_schema_finalizer_is_noop_for_sqlite(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")

    from migrate import finalize_postgres_schema

    class BombConnection:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("SQLite finalizer must not touch the DB")

    assert finalize_postgres_schema(BombConnection()) == []


@requires_postgres
def test_migrate_rerun_repairs_late_migration_int4_column(pg_parity_db):
    """A late table must be hardened even when no numbered migration is pending."""
    from migrate import main as migrate_main
    from game.db import db

    migrate_main()

    conn = db()
    try:
        before = conn.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'expedition_daily_value'
              AND column_name = 'expo_value_total';
            """
        ).fetchone()
        assert before is not None
        assert str(before["data_type"]).lower() in {"bigint", "numeric"}

        # Simulate the historical fresh-bootstrap ordering bug: a table created
        # by a numbered migration exists as ordinary PG INTEGER after the
        # pre-migration hardening pass.
        conn.execute(
            """
            ALTER TABLE expedition_daily_value
            ALTER COLUMN expo_value_total TYPE INTEGER
            USING expo_value_total::integer;
            """
        )
        conn.commit()
    finally:
        conn.close()

    # No migration is pending here. The schema-final pass itself must repair it.
    migrate_main()

    conn = db()
    try:
        after = conn.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'expedition_daily_value'
              AND column_name = 'expo_value_total';
            """
        ).fetchone()
        assert after is not None
        assert str(after["data_type"]).lower() == "bigint"
    finally:
        conn.close()
        close_pg_pool()
