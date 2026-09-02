from flask import Flask

import game.db as gcdb
import game.db_pg as dbpg


class FakeConn:
    def __init__(self):
        self.in_transaction = False
        self.real_close_calls = 0
        self.rollback_calls = 0

    def close(self):
        self.real_close_calls += 1

    def rollback(self):
        self.rollback_calls += 1
        self.in_transaction = False


def test_nested_close_does_not_destroy_request_transaction(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    conn = FakeConn()
    monkeypatch.setattr(dbpg, "connect_postgres", lambda: conn)
    app = Flask(__name__)

    with app.test_request_context("/"):
        got = gcdb.db()
        got.in_transaction = True
        got.close()

        # A helper that thinks it owns its db() handle must not roll back the
        # request-shared connection: doing so destroys outer SAVEPOINTs.
        assert got.rollback_calls == 0
        assert got.in_transaction is True
        assert got.real_close_calls == 0
        assert gcdb.db() is got

        assert gcdb.close_request_postgres_connections() == 1
        assert got.rollback_calls == 1
        assert got.real_close_calls == 1
