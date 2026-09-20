from __future__ import annotations

from game.pirates import play_loop as pl


class _Conn:
    def __init__(self, in_tx: bool = False):
        self.in_tx = bool(in_tx)


def _patch_lightweight_loop(monkeypatch, events):
    import game.pirates.brain as brain

    monkeypatch.setattr(pl, "_try_acquire_play_loop_busy", lambda *, conn, now: events.append("acquire") or True)
    monkeypatch.setattr(pl, "_release_play_loop_busy", lambda *, conn: events.append("release"))
    monkeypatch.setattr(brain, "run_raid_brain_tick", lambda conn, now, skip_home_raids: {"raids": []})
    monkeypatch.setattr(brain, "run_recycle_brain_tick", lambda conn, now: {"recycles": []})


def test_pg_implicit_read_transaction_does_not_disable_short_tx(monkeypatch):
    events = []
    conn = _Conn(False)
    _patch_lightweight_loop(monkeypatch, events)

    monkeypatch.setattr(pl, "in_transaction", lambda c: bool(c.in_tx))

    def ai_enabled(*, conn):
        # Psycopg semantics: even a SELECT opens INTRANS when autocommit is off.
        events.append("ai-read")
        conn.in_tx = True
        return True

    def begin(conn, **kwargs):
        assert conn.in_tx is False, "implicit read TX must be closed before short write"
        events.append("begin")
        conn.in_tx = True

    def commit(conn):
        events.append("commit")
        conn.in_tx = False

    def rollback(conn):
        events.append("rollback-read")
        conn.in_tx = False

    monkeypatch.setattr(pl, "is_pirates_ai_enabled", ai_enabled)
    monkeypatch.setattr(pl, "begin_write_transaction", begin)
    monkeypatch.setattr(pl, "commit", commit)
    monkeypatch.setattr(pl, "rollback", rollback)

    out = pl.run_play_loop_tick(conn, now=123.0, bots=[])

    assert out["ok"] is True
    assert out["short_tx"] is True
    assert out["write_commits"] == 3  # acquire + active-pick + brains; release is finally
    assert events[:2] == ["ai-read", "rollback-read"]
    assert events.count("begin") == 4  # includes busy-release finally
    assert events.count("commit") == 4
    assert conn.in_tx is False


def test_real_outer_transaction_stays_caller_owned(monkeypatch):
    events = []
    conn = _Conn(True)
    _patch_lightweight_loop(monkeypatch, events)

    monkeypatch.setattr(pl, "in_transaction", lambda c: bool(c.in_tx))
    monkeypatch.setattr(
        pl,
        "is_pirates_ai_enabled",
        lambda *, conn: events.append("ai-read") or True,
    )
    monkeypatch.setattr(
        pl,
        "begin_write_transaction",
        lambda conn, **kwargs: (_ for _ in ()).throw(AssertionError("must not begin nested owner TX")),
    )
    monkeypatch.setattr(
        pl,
        "commit",
        lambda conn: (_ for _ in ()).throw(AssertionError("must not commit caller TX")),
    )
    monkeypatch.setattr(
        pl,
        "rollback",
        lambda conn: (_ for _ in ()).throw(AssertionError("must not rollback caller TX")),
    )

    out = pl.run_play_loop_tick(conn, now=123.0, bots=[])

    assert out["ok"] is True
    assert out["short_tx"] is False
    assert out["write_commits"] == 0
    assert conn.in_tx is True
