"""GC-PG-HIGHSPEED-001C effective presence reader regression gates."""

from __future__ import annotations

from game import presence_store


class _Rows:
    def __init__(self, *, one=None, many=None):
        self._one = one
        self._many = list(many or [])

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._many)


class _Conn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sql: list[str] = []
        self.params: list[object] = []

    def execute(self, sql, params=None):  # noqa: ANN001
        self.sql.append(str(sql))
        self.params.append(params)
        if not self.responses:
            raise AssertionError(f"unexpected SQL: {sql}")
        return self.responses.pop(0)


def test_pg_effective_expression_uses_newest_timestamp():
    expr = presence_store.effective_last_seen_sql(backend="postgres")
    assert expr == "GREATEST(COALESCE(pp.last_seen, 0), COALESCE(p.last_seen, 0))"
    assert presence_store.last_seen_join_sql(backend="postgres") == (
        "LEFT JOIN player_presence pp ON pp.player_id = p.id"
    )


def test_pg_effective_single_reader_uses_newest_wins_query():
    conn = _Conn([_Rows(one={"last_seen": 999})])
    seen = presence_store.get_effective_last_seen(conn, 7, backend="postgres")
    assert seen == 999
    sql = conn.sql[0]
    assert "GREATEST(COALESCE(pp.last_seen, 0), COALESCE(p.last_seen, 0))" in sql
    assert "LEFT JOIN player_presence pp ON pp.player_id = p.id" in sql
    assert conn.params == [(7,)]


def test_pg_effective_bulk_reader_uses_one_query_and_fills_missing_ids():
    conn = _Conn(
        [
            _Rows(
                many=[
                    {"player_id": 2, "last_seen": 222},
                    {"player_id": 9, "last_seen": 999},
                ]
            )
        ]
    )
    seen = presence_store.get_effective_last_seen_by_ids(
        conn, [9, 2, 9, 4], backend="postgres"
    )
    assert seen == {2: 222, 4: 0, 9: 999}
    assert len(conn.sql) == 1
    assert "GREATEST(COALESCE(pp.last_seen, 0), COALESCE(p.last_seen, 0))" in conn.sql[0]
    assert conn.params == [(2, 4, 9)]


def test_sqlite_effective_readers_keep_players_only_path():
    single = _Conn([_Rows(one={"last_seen": 456})])
    assert presence_store.get_effective_last_seen(single, 3, backend="sqlite") == 456
    assert "FROM players WHERE id = ?" in single.sql[0]
    assert "player_presence" not in single.sql[0]

    bulk = _Conn([_Rows(many=[{"player_id": 3, "last_seen": 456}])])
    assert presence_store.get_effective_last_seen_by_ids(
        bulk, [3], backend="sqlite"
    ) == {3: 456}
    assert "FROM players" in bulk.sql[0]
    assert "player_presence" not in bulk.sql[0]


def test_authenticated_pg_hot_reader_remains_players_row_free():
    conn = _Conn([_Rows(one={"last_seen": 123})])
    assert presence_store.get_presence_last_seen(conn, 5, backend="postgres") == 123
    sql = conn.sql[0].lower()
    assert "player_presence" in sql
    assert "from players" not in sql
    assert "join players" not in sql
