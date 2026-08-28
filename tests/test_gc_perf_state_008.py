from __future__ import annotations

import sqlite3

from game import db as db_module


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _schema_queries(statements: list[str]) -> list[str]:
    return [sql for sql in statements if "sqlite_master" in sql.lower()]


def test_tables_exist_checks_many_sqlite_tables_with_one_query() -> None:
    conn = _memory_conn()
    try:
        conn.execute("CREATE TABLE alpha (id INTEGER);")
        conn.execute("CREATE TABLE beta (id INTEGER);")
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        assert db_module.tables_exist(conn, ("alpha", "beta")) is True
        assert len(_schema_queries(statements)) == 1
    finally:
        conn.close()


def test_tables_exist_returns_false_when_one_table_is_missing() -> None:
    conn = _memory_conn()
    try:
        conn.execute("CREATE TABLE alpha (id INTEGER);")
        assert db_module.tables_exist(conn, ("alpha", "missing")) is False
    finally:
        conn.close()


def test_bulk_schema_helper_uses_information_schema_on_postgres(monkeypatch) -> None:
    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return list(self._rows)

    class FakeConn:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, sql, params):
            self.calls.append((str(sql), tuple(params)))
            return FakeCursor([{"name": "alpha"}, {"name": "beta"}])

    conn = FakeConn()
    monkeypatch.setattr(db_module, "get_db_backend", lambda: "postgres")

    assert db_module.tables_exist(conn, ("alpha", "beta")) is True
    assert len(conn.calls) == 1
    assert "information_schema.tables" in conn.calls[0][0]
    assert conn.calls[0][1] == ("alpha", "beta")


def test_hot_nav_domain_schema_guards_are_one_query_each() -> None:
    from game.alliance import alliance_hub_schema_ready
    from game.auction_house import auction_schema_ready
    from game.case_battles import case_battles_schema_ready

    conn = _memory_conn()
    try:
        tables = (
            # Alliance core
            "alliances",
            "alliance_members",
            "alliance_donations",
            "alliance_buildings",
            "alliance_technologies",
            "alliance_projects",
            "alliance_applications",
            "alliance_diplomacy",
            "alliance_diplomacy_requests",
            # Auction core
            "lootbox_inventory",
            "auction_house_listings",
            "auction_house_bids",
            # Case Battles core
            "case_battles",
            "case_battle_players",
            "case_battle_rolls",
            "case_battle_settlements",
        )
        for table in tables:
            conn.execute(f"CREATE TABLE {table} (id INTEGER);")

        for guard in (
            alliance_hub_schema_ready,
            auction_schema_ready,
            case_battles_schema_ready,
        ):
            statements: list[str] = []
            conn.set_trace_callback(statements.append)
            assert guard(conn) is True
            conn.set_trace_callback(None)
            assert len(_schema_queries(statements)) == 1, guard.__name__
    finally:
        conn.close()
