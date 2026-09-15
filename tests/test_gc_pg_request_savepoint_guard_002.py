from __future__ import annotations

from flask import Flask

from game import db as dbmod


class _FakePgConn:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.in_transaction = True

    def execute(self, sql, params=None):  # noqa: ANN001
        self.executed.append(str(sql))
        return self

    def commit(self) -> None:
        self.commit_count += 1
        self.in_transaction = False

    def rollback(self) -> None:
        self.rollback_count += 1
        self.in_transaction = False

    def close(self) -> None:
        self.close_count += 1


def test_request_pinned_pg_commit_cannot_destroy_outer_savepoint(monkeypatch):
    monkeypatch.setattr(dbmod, "get_db_backend", lambda: "postgres")
    app = Flask(__name__)
    conn = _FakePgConn()

    with app.test_request_context("/"):
        assert dbmod._pin_request_postgres_connection(conn) is True

        conn.execute("SAVEPOINT gc_fleet_arrival_48612")
        conn.commit()

        assert conn.commit_count == 0
        assert conn.in_transaction is True

        conn.execute("RELEASE SAVEPOINT gc_fleet_arrival_48612")
        conn.commit()

        assert conn.commit_count == 1
        assert conn.in_transaction is False


def test_request_pinned_pg_rollback_rewinds_but_keeps_owner_savepoint(monkeypatch):
    monkeypatch.setattr(dbmod, "get_db_backend", lambda: "postgres")
    app = Flask(__name__)
    conn = _FakePgConn()

    with app.test_request_context("/"):
        assert dbmod._pin_request_postgres_connection(conn) is True

        conn.execute("SAVEPOINT qe_2741")
        conn.rollback()

        assert conn.rollback_count == 0
        assert "ROLLBACK TO SAVEPOINT qe_2741" in conn.executed
        assert conn.in_transaction is True

        # The SAVEPOINT owner must still be able to release it afterwards.
        conn.execute("RELEASE SAVEPOINT qe_2741")
        assert getattr(conn, "_gc_request_savepoints") == []


def test_request_teardown_uses_real_full_rollback_even_with_savepoint(monkeypatch):
    monkeypatch.setattr(dbmod, "get_db_backend", lambda: "postgres")
    app = Flask(__name__)
    conn = _FakePgConn()

    with app.test_request_context("/"):
        assert dbmod._pin_request_postgres_connection(conn) is True
        conn.execute("SAVEPOINT qe_99")

        closed = dbmod.close_request_postgres_connections()

        assert closed == 1
        assert conn.rollback_count == 1
        assert conn.close_count == 1
        assert conn.in_transaction is False


def test_nested_savepoint_stack_tracks_rollback_and_release(monkeypatch):
    monkeypatch.setattr(dbmod, "get_db_backend", lambda: "postgres")
    app = Flask(__name__)
    conn = _FakePgConn()

    with app.test_request_context("/"):
        assert dbmod._pin_request_postgres_connection(conn) is True

        conn.execute("SAVEPOINT qe_outer")
        conn.execute("SAVEPOINT gc_fleet_arrival_48614")
        assert getattr(conn, "_gc_request_savepoints") == [
            "qe_outer",
            "gc_fleet_arrival_48614",
        ]

        conn.execute("ROLLBACK TO SAVEPOINT qe_outer")
        assert getattr(conn, "_gc_request_savepoints") == ["qe_outer"]

        conn.execute("RELEASE SAVEPOINT qe_outer")
        assert getattr(conn, "_gc_request_savepoints") == []
