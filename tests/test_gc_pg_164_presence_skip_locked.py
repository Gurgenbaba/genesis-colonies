from game.presence_store import sync_legacy_last_seen


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        if sql.startswith("SELECT id FROM players"):
            return _Result(self.row)
        return _Result(None)


def test_legacy_presence_mirror_skips_busy_player_without_update():
    conn = _Conn(None)
    assert sync_legacy_last_seen(conn, 7, now=1000) is False
    assert len(conn.calls) == 1
    assert "FOR UPDATE SKIP LOCKED" in conn.calls[0][0]
    assert not any("UPDATE players SET last_seen" in sql for sql, _ in conn.calls)


def test_legacy_presence_mirror_updates_only_after_nonblocking_row_claim():
    conn = _Conn({"id": 7})
    assert sync_legacy_last_seen(conn, 7, now=1000) is True
    assert "FOR UPDATE SKIP LOCKED" in conn.calls[0][0]
    assert any("UPDATE players SET last_seen" in sql for sql, _ in conn.calls[1:])
