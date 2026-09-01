#!/usr/bin/env python3
"""Remove mutation ownership from the two production World Boss GET callers."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app.py"


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    old_view = '''    from game.db import begin_write_transaction, commit, rollback
    from game.world_boss import build_world_boss_payload

    player_id = _current_player_id()
    conn = db()
    wb_payload = None
    try:
        begin_write_transaction(conn)
        try:
            wb_payload = build_world_boss_payload(player_id, conn=conn, flush_auto=True)
            commit(conn)
        except Exception:
            rollback(conn)
            raise
    finally:
        conn.close()
'''
    new_view = '''    from game.world_boss import build_world_boss_payload

    player_id = _current_player_id()
    conn = db()
    wb_payload = None
    try:
        # PostgreSQL GET hotpath: payload composition is read-only. Auto attacks
        # are server-owned by the fleet worker / explicit POST mutations.
        wb_payload = build_world_boss_payload(player_id, conn=conn)
    finally:
        conn.close()
'''
    src = replace_once(src, old_view, new_view)

    old_api = '''        from game.db import begin_write_transaction, commit, rollback
        from game.world_boss import build_world_boss_payload

        event_id = request.args.get("event_id", type=int)
        conn = db()
        try:
            begin_write_transaction(conn)
            try:
                payload = build_world_boss_payload(
                    player_id, conn=conn, event_id=event_id, flush_auto=True
                )
                commit(conn)
            except Exception:
                rollback(conn)
                raise
        finally:
            conn.close()
'''
    new_api = '''        from game.world_boss import build_world_boss_payload

        event_id = request.args.get("event_id", type=int)
        conn = db()
        try:
            # GET must never become an attack transaction merely by polling.
            payload = build_world_boss_payload(player_id, conn=conn, event_id=event_id)
        finally:
            conn.close()
'''
    src = replace_once(src, old_api, new_api)
    TARGET.write_text(src, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
