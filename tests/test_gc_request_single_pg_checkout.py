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


def test_one_postgres_checkout_per_flask_request(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    calls = []

    def fake_connect():
        conn = FakeConn()
        calls.append(conn)
        return conn

    monkeypatch.setattr(dbpg, "connect_postgres", fake_connect)
    app = Flask(__name__)
    with app.test_request_context("/"):
        a = gcdb.db()
        b = gcdb.db()
        assert a is b
        assert len(calls) == 1
        a.close()
        assert a.real_close_calls == 0
        assert gcdb.db() is a
        assert gcdb.close_request_postgres_connections() == 1
        assert a.real_close_calls == 1


def test_request_local_close_rolls_back_before_reuse(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    conn = FakeConn()
    monkeypatch.setattr(dbpg, "connect_postgres", lambda: conn)
    app = Flask(__name__)
    with app.test_request_context("/"):
        got = gcdb.db()
        got.in_transaction = True
        got.close()
        assert got.rollback_calls == 1
        assert got.real_close_calls == 0
        assert gcdb.db() is got
        gcdb.close_request_postgres_connections()
        assert got.real_close_calls == 1


def test_outside_request_keeps_normal_pool_checkout_semantics(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    made = []

    def fake_connect():
        conn = FakeConn()
        made.append(conn)
        return conn

    monkeypatch.setattr(dbpg, "connect_postgres", fake_connect)
    a = gcdb.db()
    b = gcdb.db()
    assert a is not b
    assert len(made) == 2
