from pathlib import Path

p = Path('game/db.py')
s = p.read_text(encoding='utf-8')
old = '''        def _request_local_close() -> None:\n            try:\n                if in_transaction(conn):\n                    rollback(conn)\n            except Exception:\n                try:\n                    conn.rollback()\n                except Exception:\n                    pass\n'''
new = '''        def _request_local_close() -> None:\n            # One pooled checkout is shared by the entire Flask request. A nested\n            # helper calling close() must not roll back that shared transaction:\n            # doing so destroys outer queue-engine SAVEPOINTs. The real rollback\n            # and pool-return boundary is teardown_request.\n            return None\n'''
if old not in s:
    raise SystemExit('request-local close block not found')
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')

Path('tests/test_gc_request_pinned_pg_close_semantics.py').write_text('''from flask import Flask\n\nimport game.db as gcdb\nimport game.db_pg as dbpg\n\n\nclass FakeConn:\n    def __init__(self):\n        self.in_transaction = False\n        self.real_close_calls = 0\n        self.rollback_calls = 0\n\n    def close(self):\n        self.real_close_calls += 1\n\n    def rollback(self):\n        self.rollback_calls += 1\n        self.in_transaction = False\n\n\ndef test_nested_close_does_not_destroy_request_transaction(monkeypatch):\n    monkeypatch.setenv("GC_DB_BACKEND", "postgres")\n    conn = FakeConn()\n    monkeypatch.setattr(dbpg, "connect_postgres", lambda: conn)\n    app = Flask(__name__)\n    with app.test_request_context("/"):\n        got = gcdb.db()\n        got.in_transaction = True\n        got.close()\n        assert got.rollback_calls == 0\n        assert got.in_transaction is True\n        assert got.real_close_calls == 0\n        assert gcdb.db() is got\n        assert gcdb.close_request_postgres_connections() == 1\n        assert got.rollback_calls == 1\n        assert got.real_close_calls == 1\n''', encoding='utf-8')
