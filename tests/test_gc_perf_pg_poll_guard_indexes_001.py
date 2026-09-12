from __future__ import annotations

from game import pg_hotpath_indexes as hot


def _index_sql(name: str) -> str:
    for _table, index_name, sql in hot.HOTPATH_INDEXES:
        if index_name == name:
            return sql
    raise AssertionError(f"missing hotpath index: {name}")


def test_poll_guard_queue_indexes_match_runtime_predicates():
    defense = _index_sql("idx_defense_queue_planet_due_queued")
    assert "ON defense_queue(planet_id, finish_at)" in defense
    assert "WHERE status = 'queued'" in defense

    troops = _index_sql("idx_troop_queue_player_due_queued")
    assert "ON troop_queue(player_id, finish_at, planet_id)" in troops
    assert "WHERE status = 'queued'" in troops


def test_poll_guard_unread_partial_index_matches_exact_visibility_predicate():
    unread = _index_sql("idx_player_messages_unread_active_recipient")
    assert "ON player_messages(recipient_player_id)" in unread
    assert "COALESCE(is_archived, 0) = 0" in unread
    assert "COALESCE(is_read, 0) = 0" in unread
    assert "deleted_at IS NULL OR deleted_at = 0" in unread


def test_new_hotpath_indexes_remain_live_safe():
    for name in (
        "idx_defense_queue_planet_due_queued",
        "idx_troop_queue_player_due_queued",
        "idx_player_messages_unread_active_recipient",
    ):
        sql = _index_sql(name).upper()
        assert sql.startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS")
        assert "DROP " not in sql
        assert "ALTER " not in sql
