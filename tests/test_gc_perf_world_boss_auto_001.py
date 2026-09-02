"""GC-PERF-WB-AUTO-001 — keep enabled World Boss auto-attacks on a tiny PG partial index."""

from __future__ import annotations

from game.pg_hotpath_indexes import HOTPATH_INDEXES


def test_postgres_world_boss_auto_attack_index_is_concurrent_and_partial():
    matches = [
        (table, name, sql)
        for table, name, sql in HOTPATH_INDEXES
        if name == "idx_world_boss_contrib_auto_enabled_player_event"
    ]
    assert len(matches) == 1
    table, _, sql = matches[0]
    normalized = " ".join(str(sql).split()).upper()

    assert table == "world_boss_contributions"
    assert (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "IDX_WORLD_BOSS_CONTRIB_AUTO_ENABLED_PLAYER_EVENT"
    ) in normalized
    assert "ON WORLD_BOSS_CONTRIBUTIONS(PLAYER_ID, EVENT_ID)" in normalized
    assert "WHERE AUTO_ATTACK_ENABLED = 1" in normalized


def test_world_boss_auto_attack_index_stays_postgres_hotpath_only():
    """Never add request-time DDL or a numbered production CREATE INDEX migration."""
    _, _, sql = next(
        entry
        for entry in HOTPATH_INDEXES
        if entry[1] == "idx_world_boss_contrib_auto_enabled_player_event"
    )
    normalized = " ".join(str(sql).split()).upper()
    assert "CONCURRENTLY" in normalized
    assert normalized.endswith("WHERE AUTO_ATTACK_ENABLED = 1;")
