from pathlib import Path

p = Path('game/db.py')
s = p.read_text(encoding='utf-8')
old = '''        def _request_local_close() -> None:\n            try:\n                if in_transaction(conn):\n                    rollback(conn)\n            except Exception:\n                try:\n                    conn.rollback()\n                except Exception:\n                    pass\n'''
new = '''        def _request_local_close() -> None:\n            # The checkout is shared by the entire Flask request. Nested helpers\n            # that call close() must not roll back the shared transaction: an\n            # outer queue-engine SAVEPOINT may still be active. The real cleanup\n            # and rollback boundary is teardown_request.\n            return None\n'''
if old not in s:
    raise SystemExit('request-local close block not found')
p.write_text(s.replace(old, new, 1), encoding='utf-8')
