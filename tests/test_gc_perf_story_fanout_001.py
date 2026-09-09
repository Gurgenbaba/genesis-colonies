"""GC-PERF-STORY-FANOUT-001 — Story ensure dedup for PostgreSQL event fan-out."""

from __future__ import annotations

from unittest.mock import patch

from game.story.flags import set_flag
from game.story.progress import apply_gameplay_events


def _fake_pg_connection():
    PgConnection = type("PgConnection", (), {})
    PgConnection.__module__ = "game.db_pg"
    conn = PgConnection()
    conn.statements = []

    def execute(sql, params=None):
        conn.statements.append((sql, params))
        return object()

    conn.execute = execute
    return conn


def _event(source: str = "test:1"):
    return {
        "kind": "build_complete",
        "building_type": "metal_mine",
        "amount": 1,
        "source_event_id": source,
    }


def test_postgres_story_progress_ensures_once_per_flag_generation():
    conn = _fake_pg_connection()

    with (
        patch("game.story.progress.story_schema_ready", return_value=True),
        patch("game.story.progress._load_active_arcs", return_value=[]),
        patch("game.story.engine.ensure_player_story") as ensure_story,
    ):
        apply_gameplay_events(7, [_event("test:1")], conn=conn, now=100)
        apply_gameplay_events(7, [_event("test:2")], conn=conn, now=101)

    assert ensure_story.call_count == 1


def test_postgres_story_flag_write_invalidates_progress_ensure_memo():
    conn = _fake_pg_connection()

    with (
        patch("game.story.progress.story_schema_ready", return_value=True),
        patch("game.story.progress._load_active_arcs", return_value=[]),
        patch("game.story.engine.ensure_player_story") as ensure_story,
        patch("game.story.flags.flags_schema_ready", return_value=True),
    ):
        apply_gameplay_events(7, [_event("test:1")], conn=conn, now=100)
        assert ensure_story.call_count == 1

        assert set_flag(7, "story_test_unlock", conn=conn, now=100)

        apply_gameplay_events(7, [_event("test:2")], conn=conn, now=101)

    assert ensure_story.call_count == 2
    assert getattr(conn, "_gc_story_flag_versions")[7] == 1


def test_sqlite_story_progress_keeps_existing_ensure_behavior():
    class SQLiteLike:
        pass

    conn = SQLiteLike()

    with (
        patch("game.story.progress.story_schema_ready", return_value=True),
        patch("game.story.progress._load_active_arcs", return_value=[]),
        patch("game.story.engine.ensure_player_story") as ensure_story,
    ):
        apply_gameplay_events(7, [_event("test:1")], conn=conn, now=100)
        apply_gameplay_events(7, [_event("test:2")], conn=conn, now=101)

    assert ensure_story.call_count == 2
