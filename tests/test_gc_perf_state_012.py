import sqlite3

from game.directives import service


def _conn(*, include_player_directives=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE directive_definitions (key TEXT PRIMARY KEY);")
    if include_player_directives:
        conn.execute(
            "CREATE TABLE player_directives ("
            "id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL, "
            "cadence TEXT NOT NULL, period_key TEXT NOT NULL, status TEXT NOT NULL"
            ");"
        )
    conn.commit()
    return conn


def _directive(conn, player_id, cadence, period_key, status):
    conn.execute(
        "INSERT INTO player_directives (player_id, cadence, period_key, status) "
        "VALUES (?, ?, ?, ?);",
        (player_id, cadence, period_key, status),
    )


def _read_statements(trace):
    prefixes = ("SELECT", "WITH", "PRAGMA")
    return [sql for sql in trace if sql.lstrip().upper().startswith(prefixes)]


def _write_or_tx_statements(trace):
    prefixes = (
        "INSERT",
        "UPDATE",
        "DELETE",
        "REPLACE",
        "CREATE",
        "DROP",
        "ALTER",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
    )
    return [sql for sql in trace if sql.lstrip().upper().startswith(prefixes)]


def test_directives_nav_attention_is_current_period_read_only_two_read_shape(monkeypatch):
    conn = _conn()
    try:
        current_daily = "daily:2026-08-29"
        current_weekly = "weekly:2026-W35"
        previous_daily = "daily:2026-08-28"
        previous_weekly = "weekly:2026-W34"

        _directive(conn, 7, "daily", current_daily, "completed")
        _directive(conn, 7, "daily", current_daily, "completed")
        _directive(conn, 7, "weekly", current_weekly, "completed")
        _directive(conn, 7, "daily", current_daily, "active")
        _directive(conn, 7, "weekly", current_weekly, "claimed")
        _directive(conn, 7, "daily", previous_daily, "completed")
        _directive(conn, 7, "weekly", previous_weekly, "completed")
        _directive(conn, 8, "daily", current_daily, "completed")
        conn.commit()

        monkeypatch.setattr(service, "daily_period_key", lambda: current_daily)
        monkeypatch.setattr(service, "weekly_period_key", lambda: current_weekly)
        monkeypatch.setattr(
            service,
            "ensure_player_directives",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("nav attention must not generate directives")
            ),
        )
        monkeypatch.setattr(
            service,
            "commit",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("nav attention must not commit")
            ),
        )

        trace = []
        conn.set_trace_callback(trace.append)
        assert service.count_claimable_directives(7, conn=conn) == 3

        reads = _read_statements(trace)
        assert len(reads) == 2
        assert "sqlite_master" in reads[0].lower()
        assert "directive_definitions" in reads[0]
        assert "player_directives" in reads[0]
        assert reads[1].lstrip().upper().startswith("SELECT COUNT(*)")
        assert "status = 'completed'" in reads[1].lower()
        assert not _write_or_tx_statements(trace)
        assert not conn.in_transaction
    finally:
        conn.close()


def test_directives_nav_attention_missing_schema_returns_zero_without_write():
    conn = _conn(include_player_directives=False)
    try:
        trace = []
        conn.set_trace_callback(trace.append)
        assert service.count_claimable_directives(7, conn=conn) == 0

        reads = _read_statements(trace)
        assert len(reads) == 1
        assert "sqlite_master" in reads[0].lower()
        assert not _write_or_tx_statements(trace)
        assert not conn.in_transaction
    finally:
        conn.close()


def test_directives_full_summary_keeps_lazy_ensure_and_commit(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    calls = {"ensure": 0, "commit": 0}

    def _ensure(player_id, *, conn, now):
        calls["ensure"] += 1
        assert player_id == 9
        assert now == 1234.0
        return {
            "daily": [{"status": "completed"}, {"status": "active"}],
            "weekly": [{"status": "completed"}],
            "daily_reset_at": 2000,
            "weekly_reset_at": 3000,
        }

    def _commit(conn):
        calls["commit"] += 1

    monkeypatch.setattr(service, "directives_schema_ready", lambda conn: True)
    monkeypatch.setattr(service, "ensure_player_directives", _ensure)
    monkeypatch.setattr(service, "commit", _commit)

    try:
        summary = service.get_imperial_directives_summary(9, conn=conn, now=1234.0)
        assert summary["ready"] is True
        assert summary["daily_completed"] == 1
        assert summary["daily_total"] == 2
        assert summary["weekly_completed"] == 1
        assert summary["weekly_total"] == 1
        assert summary["claimable_count"] == 2
        assert calls == {"ensure": 1, "commit": 1}
    finally:
        conn.close()
