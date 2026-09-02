from pathlib import Path

# 1) Make pooled PgConnection.close() idempotent. A second close must never
# close a raw connection that has already been returned to the pool.
p = Path("game/db_pg.py")
text = p.read_text(encoding="utf-8")
old = '''    # Return to pool on close\n    original_close = wrapped.close\n\n    def _close_and_return() -> None:\n        try:\n            if wrapped.in_transaction:\n                wrapped.rollback()\n        except Exception:\n            pass\n        try:\n            pool.putconn(raw)\n        except Exception:\n            try:\n                raw.close()\n            except Exception:\n                pass\n        # avoid double-return\n        wrapped.close = original_close  # type: ignore[method-assign]\n\n    wrapped.close = _close_and_return  # type: ignore[method-assign]\n    return wrapped\n'''
new = '''    # Return to pool on close. This must be idempotent: request teardown may\n    # defensively close a wrapper that a domain helper already closed.\n    returned = False\n    return_lock = threading.Lock()\n\n    def _close_and_return() -> None:\n        nonlocal returned\n        with return_lock:\n            if returned:\n                return\n            returned = True\n        try:\n            if wrapped.in_transaction:\n                wrapped.rollback()\n        except Exception:\n            pass\n        try:\n            pool.putconn(raw)\n        except Exception:\n            try:\n                raw.close()\n            except Exception:\n                pass\n\n    wrapped.close = _close_and_return  # type: ignore[method-assign]\n    return wrapped\n'''
if old not in text:
    raise SystemExit("db_pg connect_postgres close marker not found")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

# 2) Track every Postgres checkout created during a Flask request. Helpers are
# still expected to close explicitly; teardown is the last-resort leak guard.
p = Path("game/db.py")
text = p.read_text(encoding="utf-8")
marker = '''def db() -> DbConn:\n    \"\"\"Open a DB connection for the configured backend.\"\"\"\n'''
helper = '''def _track_request_postgres_connection(conn: DbConn) -> None:\n    \"\"\"Register a pooled PG checkout for defensive Flask request teardown.\n\n    Normal domain code still owns explicit close(). The tracker only guarantees\n    that a forgotten close cannot accumulate until GC_PG_POOL_MAX is exhausted.\n    PgConnection.close() is idempotent, so already-returned connections are safe.\n    \"\"\"\n    try:\n        from flask import g, has_request_context\n\n        if not has_request_context():\n            return\n        tracked = getattr(g, \"gc_pg_request_connections\", None)\n        if tracked is None:\n            tracked = []\n            g.gc_pg_request_connections = tracked\n        tracked.append(conn)\n    except Exception:\n        pass\n\n\ndef close_request_postgres_connections() -> int:\n    \"\"\"Return any PG checkouts still associated with the current request.\"\"\"\n    if get_db_backend() != \"postgres\":\n        return 0\n    try:\n        from flask import g, has_request_context\n\n        if not has_request_context():\n            return 0\n        tracked = list(getattr(g, \"gc_pg_request_connections\", ()) or ())\n        g.gc_pg_request_connections = []\n    except Exception:\n        return 0\n    closed = 0\n    for conn in reversed(tracked):\n        try:\n            conn.close()\n            closed += 1\n        except Exception:\n            pass\n    return closed\n\n\n'''
if marker not in text:
    raise SystemExit("db() marker not found")
text = text.replace(marker, helper + marker, 1)
old = '''            conn = connect_postgres()\n        except NotImplementedError:\n'''
new = '''            conn = connect_postgres()\n            _track_request_postgres_connection(conn)\n        except NotImplementedError:\n'''
if old not in text:
    raise SystemExit("postgres connect marker not found")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

# 3) Install teardown safety in Flask. Runs after every request, including 5xx.
p = Path("app.py")
text = p.read_text(encoding="utf-8")
marker = '''@app.errorhandler(DbPoolTimeout)\ndef handle_db_pool_timeout(exc):\n'''
teardown = '''@app.teardown_request\ndef _return_request_postgres_connections(_exc):\n    \"\"\"Last-resort PG pool leak guard for every HTTP request.\"\"\"\n    try:\n        from game.db import close_request_postgres_connections\n\n        close_request_postgres_connections()\n    except Exception:\n        pass\n\n\n'''
if marker not in text:
    raise SystemExit("app DbPoolTimeout marker not found")
text = text.replace(marker, teardown + marker, 1)
p.write_text(text, encoding="utf-8")

# 4) Regression tests: idempotent return + request teardown contract.
t = Path("tests/test_gc_pg_request_pool_guard.py")
t.write_text('''from __future__ import annotations\n\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parent.parent\n\n\ndef test_pg_pool_return_is_idempotent():\n    src = (ROOT / "game/db_pg.py").read_text(encoding="utf-8")\n    section = src.split("def connect_postgres()", 1)[1].split("def close_pool()", 1)[0]\n    assert "returned = False" in section\n    assert "if returned:" in section\n    assert "pool.putconn(raw)" in section\n    assert "wrapped.close = original_close" not in section\n\n\ndef test_request_pg_connections_are_tracked_and_drained():\n    db_src = (ROOT / "game/db.py").read_text(encoding="utf-8")\n    assert "def _track_request_postgres_connection" in db_src\n    assert "gc_pg_request_connections" in db_src\n    assert "_track_request_postgres_connection(conn)" in db_src\n    assert "def close_request_postgres_connections" in db_src\n\n    app_src = (ROOT / "app.py").read_text(encoding="utf-8")\n    assert "@app.teardown_request" in app_src\n    assert "close_request_postgres_connections()" in app_src\n''', encoding="utf-8")
