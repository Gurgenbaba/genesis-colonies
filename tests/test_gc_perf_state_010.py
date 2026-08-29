import sqlite3

from game import auction_house


def _conn(*, with_visits=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE lootbox_inventory (id INTEGER PRIMARY KEY);")
    conn.execute(
        "CREATE TABLE auction_house_listings ("
        "id INTEGER PRIMARY KEY, status TEXT, ends_at INTEGER, "
        "current_bidder_id INTEGER, created_at INTEGER"
        ");"
    )
    conn.execute(
        "CREATE TABLE auction_house_bids ("
        "id INTEGER PRIMARY KEY, listing_id INTEGER, player_id INTEGER"
        ");"
    )
    if with_visits:
        conn.execute(
            "CREATE TABLE auction_house_player_visits ("
            "player_id INTEGER PRIMARY KEY, last_visited_at INTEGER"
            ");"
        )
    conn.commit()
    return conn


def _selects(trace):
    return [sql for sql in trace if sql.lstrip().upper().startswith(("SELECT", "WITH"))]


def _seed_listing(conn, listing_id, *, status="active", ends_at=2000, bidder=None, created_at=500):
    conn.execute(
        "INSERT INTO auction_house_listings "
        "(id, status, ends_at, current_bidder_id, created_at) VALUES (?, ?, ?, ?, ?);",
        (listing_id, status, ends_at, bidder, created_at),
    )


def _seed_bid(conn, listing_id, player_id):
    conn.execute(
        "INSERT INTO auction_house_bids (listing_id, player_id) VALUES (?, ?);",
        (listing_id, player_id),
    )


def test_auction_attention_visited_player_preserves_semantics_and_uses_three_selects(monkeypatch):
    monkeypatch.setattr(auction_house.time, "time", lambda: 1000)
    conn = _conn(with_visits=True)
    try:
        conn.execute(
            "INSERT INTO auction_house_player_visits (player_id, last_visited_at) VALUES (7, 700);"
        )
        _seed_listing(conn, 1, bidder=9, created_at=800)
        _seed_bid(conn, 1, 7)  # outbid + new
        _seed_listing(conn, 2, bidder=9, created_at=600)
        _seed_bid(conn, 2, 7)  # outbid, but not new
        _seed_listing(conn, 3, bidder=7, created_at=900)  # new, still leading
        _seed_bid(conn, 3, 7)
        _seed_listing(conn, 4, bidder=9, created_at=900, ends_at=900)  # ended
        _seed_bid(conn, 4, 7)
        _seed_listing(conn, 5, status="completed", bidder=9, created_at=900)
        _seed_bid(conn, 5, 7)
        conn.commit()

        trace = []
        conn.set_trace_callback(trace.append)
        assert auction_house.count_auction_nav_attention(7, conn=conn) == 4
        selects = _selects(trace)
        assert len(selects) == 3
        assert sum("sqlite_master" in sql.lower() for sql in selects) == 2
        data_sql = selects[-1].lower()
        assert data_sql.lstrip().startswith("with visit as")
        assert " join " not in f" {data_sql} "
        assert "count(*)" in data_sql
        assert not conn.in_transaction
    finally:
        conn.close()


def test_auction_attention_never_visited_counts_all_active(monkeypatch):
    monkeypatch.setattr(auction_house.time, "time", lambda: 1000)
    conn = _conn(with_visits=True)
    try:
        _seed_listing(conn, 1, bidder=9, created_at=100)
        _seed_bid(conn, 1, 8)  # outbid + active listing
        _seed_listing(conn, 2, bidder=None, created_at=200)
        conn.commit()
        assert auction_house.count_auction_nav_attention(8, conn=conn) == 3
    finally:
        conn.close()


def test_auction_attention_missing_optional_visits_table_is_supported(monkeypatch):
    monkeypatch.setattr(auction_house.time, "time", lambda: 1000)
    conn = _conn(with_visits=False)
    try:
        _seed_listing(conn, 1, bidder=9, created_at=100)
        _seed_bid(conn, 1, 11)
        _seed_listing(conn, 2, bidder=None, created_at=200)
        conn.commit()

        trace = []
        conn.set_trace_callback(trace.append)
        assert auction_house.count_auction_nav_attention(11, conn=conn) == 3
        selects = _selects(trace)
        assert len(selects) == 3
        assert sum("sqlite_master" in sql.lower() for sql in selects) == 2
        data_sql = selects[-1].lower()
        assert "auction_house_player_visits" not in data_sql
        assert " join " not in f" {data_sql} "
        assert not conn.in_transaction
    finally:
        conn.close()
