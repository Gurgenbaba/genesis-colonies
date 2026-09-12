from __future__ import annotations

from game import pg_hotpath_indexes as hot


def _index_sql(name: str) -> str:
    for _table, index_name, sql in hot.HOTPATH_INDEXES:
        if index_name == name:
            return sql
    raise AssertionError(f"missing hotpath index: {name}")


def test_auction_bid_hot_index_matches_bid_limit_and_refund_reads():
    sql = _index_sql("idx_auction_bids_listing_player_created")
    assert "ON auction_house_bids(listing_id, player_id, created_at DESC)" in sql
    assert "INCLUDE (refunded, id)" in sql


def test_news_published_hot_index_matches_visible_timeline_order():
    sql = _index_sql("idx_universe_news_published_visible")
    assert "ON universe_news(published_at DESC, id DESC)" in sql
    assert "WHERE is_draft = 0" in sql


def test_action_read_hot_indexes_are_concurrent_and_fail_open_compatible():
    for name in (
        "idx_auction_bids_listing_player_created",
        "idx_universe_news_published_visible",
    ):
        sql = _index_sql(name).upper()
        assert sql.startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS")
        assert "DROP " not in sql
        assert "ALTER " not in sql
