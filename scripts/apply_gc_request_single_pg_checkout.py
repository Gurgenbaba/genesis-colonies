from pathlib import Path

p = Path('game/db.py')
s = p.read_text(encoding='utf-8')

old = '''def _track_request_postgres_connection(conn: DbConn) -> None:
    """Register a pooled PG checkout for defensive Flask request teardown.

    Normal domain code still owns explicit close(). The tracker only guarantees
    that a forgotten close cannot accumulate until GC_PG_POOL_MAX is exhausted.
    PgConnection.close() is idempotent, so already-returned connections are safe.
    """
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return
        tracked = getattr(g, "gc_pg_request_connections", None)
        if tracked is None:
            tracked = []
            g.gc_pg_request_connections = tracked
        tracked.append(conn)
    except Exception:
        pass


def close_request_postgres_connections() -> int:
    """Return any PG checkouts still associated with the current request."""
    if get_db_backend() != "postgres":
        return 0
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return 0
        tracked = list(getattr(g, "gc_pg_request_connections", ()) or ())
        g.gc_pg_request_connections = []
    except Exception:
        return 0
    closed = 0
    for conn in reversed(tracked):
        try:
            conn.close()
            closed += 1
        except Exception:
            pass
    return closed
'''

new = '''def _request_postgres_connection() -> DbConn | None:
    """Return the PG checkout already pinned to this Flask request, if any."""
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return None
        return getattr(g, "gc_pg_request_connection", None)
    except Exception:
        return None


def _pin_request_postgres_connection(conn: DbConn) -> bool:
    """Pin one pooled PG checkout to the current Flask request.

    Deep helpers historically call ``db()`` independently and often close their
    local handle. On Postgres that can make one request hold several pool slots
    at once before teardown runs. Pinning collapses all nested ``db()`` calls in
    a request onto one checkout. Helper ``close()`` becomes a transaction-cleanup
    boundary; the actual pool return happens exactly once in teardown_request.
    """
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return False
        real_close = conn.close

        def _request_local_close() -> None:
            try:
                if in_transaction(conn):
                    rollback(conn)
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass

        conn.close = _request_local_close  # type: ignore[method-assign]
        g.gc_pg_request_connection = conn
        g.gc_pg_request_connection_real_close = real_close
        # Legacy marker retained for the original request-pool guard contract.
        g.gc_pg_request_connections = [conn]
        return True
    except Exception:
        return False


def _track_request_postgres_connection(conn: DbConn) -> None:
    """Compatibility entrypoint: request tracking now pins a single checkout."""
    _pin_request_postgres_connection(conn)


def close_request_postgres_connections() -> int:
    """Return the request-pinned PG checkout to the pool exactly once."""
    if get_db_backend() != "postgres":
        return 0
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return 0
        conn = getattr(g, "gc_pg_request_connection", None)
        real_close = getattr(g, "gc_pg_request_connection_real_close", None)
        g.gc_pg_request_connection = None
        g.gc_pg_request_connection_real_close = None
        g.gc_pg_request_connections = []
    except Exception:
        return 0
    if conn is None:
        return 0
    try:
        if in_transaction(conn):
            rollback(conn)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    try:
        if callable(real_close):
            real_close()
        else:
            conn.close()
        return 1
    except Exception:
        return 0
'''

if old not in s:
    raise SystemExit('request tracking block not found')
s = s.replace(old, new, 1)

old_db = '''    if backend == "postgres":
        conn_t0 = time.perf_counter()
        try:
            from game.db_pg import connect_postgres

            conn = connect_postgres()
            _track_request_postgres_connection(conn)
'''
new_db = '''    if backend == "postgres":
        existing = _request_postgres_connection()
        if existing is not None:
            return existing
        conn_t0 = time.perf_counter()
        try:
            from game.db_pg import connect_postgres

            conn = connect_postgres()
            _track_request_postgres_connection(conn)
'''
if old_db not in s:
    raise SystemExit('db postgres checkout block not found')
s = s.replace(old_db, new_db, 1)
p.write_text(s, encoding='utf-8')

Path('tests/test_gc_request_single_pg_checkout.py').write_text('''from flask import Flask\n\nimport game.db as gcdb\nimport game.db_pg as dbpg\n\n\nclass FakeConn:\n    def __init__(self):\n        self.in_transaction = False\n        self.real_close_calls = 0\n        self.rollback_calls = 0\n\n    def close(self):\n        self.real_close_calls += 1\n\n    def rollback(self):\n        self.rollback_calls += 1\n        self.in_transaction = False\n\n\ndef test_one_postgres_checkout_per_flask_request(monkeypatch):\n    monkeypatch.setenv("GC_DB_BACKEND", "postgres")\n    calls = []\n\n    def fake_connect():\n        conn = FakeConn()\n        calls.append(conn)\n        return conn\n\n    monkeypatch.setattr(dbpg, "connect_postgres", fake_connect)\n    app = Flask(__name__)\n    with app.test_request_context("/"):\n        a = gcdb.db()\n        b = gcdb.db()\n        assert a is b\n        assert len(calls) == 1\n        a.close()\n        assert a.real_close_calls == 0\n        assert gcdb.db() is a\n        assert gcdb.close_request_postgres_connections() == 1\n        assert a.real_close_calls == 1\n\n\ndef test_request_local_close_rolls_back_before_reuse(monkeypatch):\n    monkeypatch.setenv("GC_DB_BACKEND", "postgres")\n    conn = FakeConn()\n    monkeypatch.setattr(dbpg, "connect_postgres", lambda: conn)\n    app = Flask(__name__)\n    with app.test_request_context("/"):\n        got = gcdb.db()\n        got.in_transaction = True\n        got.close()\n        assert got.rollback_calls == 1\n        assert got.real_close_calls == 0\n        assert gcdb.db() is got\n        gcdb.close_request_postgres_connections()\n        assert got.real_close_calls == 1\n\n\ndef test_outside_request_keeps_normal_pool_checkout_semantics(monkeypatch):\n    monkeypatch.setenv("GC_DB_BACKEND", "postgres")\n    made = []\n\n    def fake_connect():\n        conn = FakeConn()\n        made.append(conn)\n        return conn\n\n    monkeypatch.setattr(dbpg, "connect_postgres", fake_connect)\n    a = gcdb.db()\n    b = gcdb.db()\n    assert a is not b\n    assert len(made) == 2\n''', encoding='utf-8')
