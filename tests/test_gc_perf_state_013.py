import sqlite3

from game.galactic_directives import state


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE gd_directive_definitions (directive_key TEXT PRIMARY KEY);"
    )
    conn.execute(
        "CREATE TABLE planets ("
        "id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL, galaxy INTEGER"
        ");"
    )
    conn.execute(
        "CREATE TABLE gd_cycles ("
        "id INTEGER PRIMARY KEY, galaxy INTEGER NOT NULL, status TEXT NOT NULL, "
        "vote_start_at INTEGER NOT NULL, vote_end_at INTEGER NOT NULL"
        ");"
    )
    conn.execute(
        "CREATE TABLE gd_votes (cycle_id INTEGER NOT NULL, player_id INTEGER NOT NULL);"
    )
    conn.commit()
    return conn


def _cycle(conn, cycle_id, galaxy, start_at, end_at, *, status="vote_open"):
    conn.execute(
        "INSERT INTO gd_cycles "
        "(id, galaxy, status, vote_start_at, vote_end_at) VALUES (?, ?, ?, ?, ?);",
        (cycle_id, galaxy, status, start_at, end_at),
    )


def _read_statements(trace):
    prefixes = ("SELECT", "WITH", "PRAGMA")
    return [sql for sql in trace if sql.lstrip().upper().startswith(prefixes)]


def test_government_nav_count_is_two_reads_and_preserves_vote_semantics(monkeypatch):
    conn = _conn()
    try:
        # Two colonies in the same galaxy must not double-count the cycle.
        conn.execute("INSERT INTO planets (id, player_id, galaxy) VALUES (1, 7, 1);")
        conn.execute("INSERT INTO planets (id, player_id, galaxy) VALUES (2, 7, 1);")
        conn.execute("INSERT INTO planets (id, player_id, galaxy) VALUES (3, 8, 2);")

        # Count: current open cycle in an owned galaxy.
        _cycle(conn, 1, 1, 900, 1100)
        # Excluded: player has already voted.
        _cycle(conn, 2, 1, 900, 1100)
        conn.execute("INSERT INTO gd_votes (cycle_id, player_id) VALUES (2, 7);")
        # Excluded: unowned galaxy.
        _cycle(conn, 3, 2, 900, 1100)
        # Excluded: future, expired, and closed cycles.
        _cycle(conn, 4, 1, 1001, 1200)
        _cycle(conn, 5, 1, 800, 999)
        _cycle(conn, 6, 1, 900, 1100, status="closed")
        conn.commit()

        monkeypatch.setattr(
            state,
            "get_player_vote_galaxies",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("nav count materialized player galaxy list")
            ),
        )

        trace = []
        conn.set_trace_callback(trace.append)
        assert state.count_pending_government_votes(7, conn=conn, now=1000) == 1

        reads = _read_statements(trace)
        assert len(reads) == 2
        assert "sqlite_master" in reads[0].lower()
        assert reads[1].lstrip().upper().startswith("SELECT COUNT(*)")
        assert "from planets" in reads[1].lower()
        assert "from gd_votes" in reads[1].lower()

        upper = [sql.lstrip().upper() for sql in trace]
        assert not any(
            sql.startswith(("BEGIN", "COMMIT", "INSERT", "UPDATE", "DELETE"))
            for sql in upper
        )
        assert not conn.in_transaction
    finally:
        conn.close()


def test_government_nav_missing_schema_returns_zero_without_transaction():
    conn = _conn()
    try:
        conn.execute("DROP TABLE gd_votes;")
        conn.commit()

        trace = []
        conn.set_trace_callback(trace.append)
        assert state.count_pending_government_votes(7, conn=conn, now=1000) == 0

        reads = _read_statements(trace)
        assert len(reads) == 1
        assert "sqlite_master" in reads[0].lower()
        assert not conn.in_transaction
    finally:
        conn.close()


def test_get_player_vote_galaxies_keeps_distinct_sorted_behavior():
    conn = _conn()
    try:
        conn.execute("INSERT INTO planets (id, player_id, galaxy) VALUES (1, 7, 3);")
        conn.execute("INSERT INTO planets (id, player_id, galaxy) VALUES (2, 7, 1);")
        conn.execute("INSERT INTO planets (id, player_id, galaxy) VALUES (3, 7, 3);")
        conn.execute("INSERT INTO planets (id, player_id, galaxy) VALUES (4, 8, 2);")
        conn.commit()

        assert state.get_player_vote_galaxies(7, conn=conn) == [1, 3]
    finally:
        conn.close()
