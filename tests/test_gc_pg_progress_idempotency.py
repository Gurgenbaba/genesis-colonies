"""PostgreSQL regression: duplicate progress events must stay transaction-safe."""

from __future__ import annotations

from collections.abc import Mapping

from tests.pg_fixtures import close_pg_pool, postgres_test_url, requires_postgres


def _assert_transaction_healthy(conn) -> None:
    row = conn.execute("SELECT 1 AS ok;").fetchone()
    assert row is not None
    value = row["ok"] if isinstance(row, Mapping) else row[0]
    assert int(value) == 1


@requires_postgres
def test_duplicate_progress_writes_do_not_abort_postgres(monkeypatch):
    url = postgres_test_url()
    assert url
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    close_pg_pool()

    from game.db import db, rollback
    import game.directives.progress as directive_progress
    from game.initiation.progress import _record_progress_delta as initiation_record
    from game.story.progress import _record_progress_delta as story_record

    # TEMP tables intentionally do not live in public schema. Force the Directives
    # helper past its production schema probe so this test exercises the actual
    # duplicate INSERT path rather than the "schema absent" compatibility branch.
    monkeypatch.setattr(directive_progress, "progress_schema_ready", lambda _conn: True)
    directive_record = directive_progress._record_progress_delta

    conn = db()
    try:
        conn.execute(
            """
            CREATE TEMP TABLE player_initiation_progress (
                id BIGSERIAL PRIMARY KEY,
                player_id BIGINT NOT NULL,
                source_event_id TEXT NOT NULL,
                delta BIGINT NOT NULL,
                created_at BIGINT NOT NULL,
                UNIQUE(player_id, source_event_id)
            ) ON COMMIT PRESERVE ROWS;
            """
        )
        conn.execute(
            """
            CREATE TEMP TABLE player_story_progress (
                id BIGSERIAL PRIMARY KEY,
                player_arc_id BIGINT NOT NULL,
                source_event_id TEXT NOT NULL,
                delta BIGINT NOT NULL,
                created_at BIGINT NOT NULL,
                UNIQUE(player_arc_id, source_event_id)
            ) ON COMMIT PRESERVE ROWS;
            """
        )
        conn.execute(
            """
            CREATE TEMP TABLE directive_progress (
                id BIGSERIAL PRIMARY KEY,
                player_directive_id BIGINT NOT NULL,
                source_event_id TEXT NOT NULL,
                delta BIGINT NOT NULL,
                created_at BIGINT NOT NULL,
                UNIQUE(player_directive_id, source_event_id)
            ) ON COMMIT PRESERVE ROWS;
            """
        )
        conn.commit()

        assert initiation_record(90001, source_event_id="dup:initiation", delta=1, conn=conn, now=1)
        assert not initiation_record(90001, source_event_id="dup:initiation", delta=1, conn=conn, now=2)
        _assert_transaction_healthy(conn)

        assert story_record(90002, source_event_id="dup:story", delta=1, conn=conn, now=1)
        assert not story_record(90002, source_event_id="dup:story", delta=1, conn=conn, now=2)
        _assert_transaction_healthy(conn)

        assert directive_record(90003, source_event_id="dup:directive", delta=1, conn=conn, now=1)
        assert not directive_record(90003, source_event_id="dup:directive", delta=1, conn=conn, now=2)
        _assert_transaction_healthy(conn)
    finally:
        try:
            rollback(conn)
        except Exception:
            pass
        conn.close()
        close_pg_pool()
