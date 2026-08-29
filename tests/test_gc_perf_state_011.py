import sqlite3

from game import vote_rewards


def _conn(*, optional_columns=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE vote_providers ("
        "provider_key TEXT PRIMARY KEY, enabled INTEGER NOT NULL, "
        "cooldown_sec INTEGER, sort_order INTEGER"
        ");"
    )
    optional = (
        ", provider_next_vote_at INTEGER, vote_channel TEXT"
        if optional_columns
        else ""
    )
    conn.execute(
        "CREATE TABLE vote_rewards ("
        "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, provider TEXT NOT NULL, "
        "voted_at INTEGER NOT NULL, status TEXT NOT NULL"
        f"{optional}"
        ");"
    )
    conn.commit()
    return conn


def _provider(conn, key, cooldown, *, enabled=1, sort_order=10):
    conn.execute(
        "INSERT INTO vote_providers (provider_key, enabled, cooldown_sec, sort_order) "
        "VALUES (?, ?, ?, ?);",
        (key, enabled, cooldown, sort_order),
    )


def _reward(
    conn,
    uid,
    provider,
    voted_at,
    *,
    status="claimed",
    next_at=None,
    channel="player",
    optional_columns=True,
):
    if optional_columns:
        conn.execute(
            "INSERT INTO vote_rewards "
            "(user_id, provider, voted_at, status, provider_next_vote_at, vote_channel) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            (uid, provider, voted_at, status, next_at, channel),
        )
    else:
        conn.execute(
            "INSERT INTO vote_rewards (user_id, provider, voted_at, status) "
            "VALUES (?, ?, ?, ?);",
            (uid, provider, voted_at, status),
        )


def _read_statements(trace):
    prefixes = ("SELECT", "WITH", "PRAGMA")
    return [sql for sql in trace if sql.lstrip().upper().startswith(prefixes)]


def test_vote_nav_bulk_read_preserves_canonical_cooldown_and_three_read_shape(monkeypatch):
    conn = _conn(optional_columns=True)
    try:
        # Stale DB cooldown for topg must not override the canonical 6h value.
        _provider(conn, "topg", 1, sort_order=1)
        _provider(conn, "custom", 50, sort_order=2)
        _reward(conn, 7, "topg", 900)
        _reward(conn, 7, "custom", 900)
        # Pending rewards count regardless of provider enablement.
        _reward(conn, 7, "disabled", 995, status="pending")
        conn.commit()

        monkeypatch.setattr(
            vote_rewards,
            "list_enabled_providers",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("N+1 provider loop used")),
        )
        monkeypatch.setattr(
            vote_rewards,
            "get_provider_cooldown_status",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("per-provider cooldown used")),
        )

        trace = []
        conn.set_trace_callback(trace.append)
        # custom is voteable (900 + 50 <= 1000), topg is not (canonical 6h), +1 pending.
        assert vote_rewards.count_vote_center_attention(7, conn=conn, now=1000) == 2
        reads = _read_statements(trace)
        assert len(reads) == 3
        assert reads[0].lstrip().upper().startswith("SELECT")
        assert "sqlite_master" in reads[0].lower()
        assert reads[1].lstrip().upper().startswith("PRAGMA TABLE_INFO")
        assert reads[2].lstrip().upper().startswith("WITH LATEST_RANKED")
        assert not conn.in_transaction
    finally:
        conn.close()


def test_vote_nav_provider_next_at_override_and_reengagement_filter():
    conn = _conn(optional_columns=True)
    try:
        _provider(conn, "topg", 1)
        # Real player vote is old enough, while a newer synthetic historical row
        # would block the vote if the player-channel filter regressed.
        _reward(conn, 8, "topg", 100, next_at=500, channel="player")
        _reward(conn, 8, "topg", 990, next_at=99999, channel="reengagement")
        conn.commit()
        assert vote_rewards.count_vote_center_attention(8, conn=conn, now=1000) == 1

        # Positive provider_next_vote_at remains authoritative over derived cooldown.
        conn.execute("DELETE FROM vote_rewards;")
        _reward(conn, 8, "topg", 100, next_at=1200, channel="player")
        conn.commit()
        assert vote_rewards.count_vote_center_attention(8, conn=conn, now=1000) == 0
    finally:
        conn.close()


def test_vote_nav_legacy_optional_columns_missing_is_supported():
    conn = _conn(optional_columns=False)
    try:
        _provider(conn, "custom", 50)
        _reward(conn, 9, "custom", 900, optional_columns=False)
        conn.commit()
        assert vote_rewards.count_vote_center_attention(9, conn=conn, now=1000) == 1
    finally:
        conn.close()


def test_vote_nav_pending_rewards_survive_zero_enabled_providers():
    conn = _conn(optional_columns=True)
    try:
        _provider(conn, "topg", 1, enabled=0)
        _reward(conn, 10, "topg", 995, status="pending")
        _reward(conn, 10, "topg", 996, status="pending")
        conn.commit()
        assert vote_rewards.count_vote_center_attention(10, conn=conn, now=1000) == 2
    finally:
        conn.close()
