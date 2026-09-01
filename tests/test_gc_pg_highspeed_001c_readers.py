"""GC-PG-HIGHSPEED-001C reader-cutover regression gates."""

from __future__ import annotations

from types import SimpleNamespace

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


def test_pg_effective_single_reader_prefers_presence_with_legacy_fallback_sql():
    conn = _Conn([_Rows(one={"last_seen": 777})])

    seen = presence_store.get_effective_last_seen(conn, 7, backend="postgres")

    assert seen == 777
    sql = conn.sql[0]
    assert "LEFT JOIN player_presence pp ON pp.player_id = p.id" in sql
    assert "COALESCE(pp.last_seen, p.last_seen, 0) AS last_seen" in sql
    assert "WHERE p.id = ?" in sql
    assert conn.params == [(7,)]


def test_pg_effective_bulk_reader_returns_presence_and_legacy_values():
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
    sql = conn.sql[0]
    assert "LEFT JOIN player_presence pp ON pp.player_id = p.id" in sql
    assert "COALESCE(pp.last_seen, p.last_seen, 0) AS last_seen" in sql
    assert conn.params == [(2, 4, 9)]


def test_pg_hot_presence_reader_remains_players_row_free():
    conn = _Conn([_Rows(one={"last_seen": 123})])

    seen = presence_store.get_presence_last_seen(conn, 5, backend="postgres")

    assert seen == 123
    sql = conn.sql[0]
    assert "player_presence" in sql
    assert " players " not in f" {sql.lower()} "
    assert "from players" not in sql.lower()
    assert "join players" not in sql.lower()


def test_sqlite_effective_reader_keeps_legacy_players_path():
    conn = _Conn([_Rows(one={"last_seen": 456})])

    seen = presence_store.get_effective_last_seen(conn, 3, backend="sqlite")

    assert seen == 456
    assert "FROM players WHERE id = ?" in conn.sql[0]
    assert "player_presence" not in conn.sql[0]


def test_presence_sql_fragments_are_backend_aware():
    assert presence_store.last_seen_join_sql(backend="sqlite") == ""
    assert presence_store.effective_last_seen_sql(backend="sqlite") == "COALESCE(p.last_seen, 0)"

    join = presence_store.last_seen_join_sql(backend="postgres")
    expr = presence_store.effective_last_seen_sql(backend="postgres")
    assert join == "LEFT JOIN player_presence pp ON pp.player_id = p.id"
    assert expr == "COALESCE(pp.last_seen, p.last_seen, 0)"
