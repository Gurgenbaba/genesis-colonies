"""EPIC-26 / GC-2600–2601: auto_empire + inactive autoplay."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.ranking import RANKING_INACTIVE_AFTER_SEC, is_player_id_inactive, ranking_inactive_from_last_seen


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def autoplay_db(tmp_path, monkeypatch):
    db_path = tmp_path / "inactive_autoplay_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _register_user() -> int:
    ok, err, user = create_user(f"dorm_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    return int(user["id"])


def _seed_dormant(conn, uid: int, *, days_inactive: float = 5.0) -> dict:
    ensure_player_and_homeworld(uid, player_name=f"Dorm{uid}", conn=conn)
    home = get_planets_by_player(uid, conn=conn)[0]
    stale = time.time() - (days_inactive * 24 * 3600)
    conn.execute(
        "UPDATE players SET last_seen = ? WHERE id = ?;",
        (stale, uid),
    )
    conn.execute(
        """
        UPDATE planets
        SET metal = max(COALESCE(metal, 0), 500000),
            crystal = max(COALESCE(crystal, 0), 500000),
            fuel_cells = max(COALESCE(fuel_cells, 0), 100000)
        WHERE id = ?;
        """,
        (int(home["id"]),),
    )
    return {"player_id": uid, "planet_id": int(home["id"]), "planet": dict(home)}


def test_auto_empire_passive_tick_enqueues_building(autoplay_db):
    from game.auto_empire import plan_passive_planet_tick

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        player = _seed_dormant(conn, uid, days_inactive=0.1)
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id = ?;",
            (time.time(), int(player["player_id"])),
        )
        out = plan_passive_planet_tick(
            conn,
            player_id=int(player["player_id"]),
            planet=player["planet"],
            now=time.time(),
            is_home=True,
            allow_ships=False,
            allow_defense=True,
            source="test",
        )
        assert out.get("build") or out.get("research") or out.get("defense")
        assert out.get("ships") is None
        commit(conn)
    finally:
        conn.close()


def test_inactive_autoplay_wake_touches_presence_and_enqueues(autoplay_db):
    from game.inactive_autoplay import (
        run_inactive_autoplay_tick,
        set_inactive_autoplay_enabled,
        wake_batch_size,
    )

    uids = [_register_user() for _ in range(3)]
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        players = [_seed_dormant(conn, uid, days_inactive=5.0) for uid in uids]
        for p in players:
            assert is_player_id_inactive(int(p["player_id"]), conn=conn)

        now = time.time()
        result = run_inactive_autoplay_tick(
            conn, now=now, force=True, source="test"
        )
        assert result.get("ok")
        assert 1 <= int(result.get("woke_count") or 0) <= wake_batch_size()

        woke_ids = {int(w["player_id"]) for w in (result.get("woke") or [])}
        assert woke_ids
        for pid in woke_ids:
            assert not is_player_id_inactive(pid, conn=conn, now=int(now))
            row = conn.execute(
                "SELECT last_seen FROM players WHERE id = ?;", (pid,)
            ).fetchone()
            assert not ranking_inactive_from_last_seen(
                int(row["last_seen"] or 0), now=int(now)
            )

        placeholders = ",".join("?" for _ in woke_ids)
        fleet_n = int(
            (
                conn.execute(
                    f"SELECT COUNT(*) AS c FROM fleet_movements WHERE player_id IN ({placeholders});",
                    tuple(woke_ids),
                ).fetchone()
                or {"c": 0}
            )["c"]
            or 0
        )
        assert fleet_n == 0
        assert RANKING_INACTIVE_AFTER_SEC > 0
        commit(conn)
    finally:
        conn.close()


def test_inactive_autoplay_sticky_roster_keeps_building(autoplay_db, monkeypatch):
    """Once woken, a second tick still enqueues without needing another wake."""
    from game.inactive_autoplay import (
        run_inactive_autoplay_tick,
        set_inactive_autoplay_enabled,
    )

    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_BATCH", "1")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_INTERVAL_SEC", "3600")
    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        _seed_dormant(conn, uid, days_inactive=5.0)
        t0 = time.time()
        first = run_inactive_autoplay_tick(conn, now=t0, force=True, source="test")
        assert int(first.get("woke_count") or 0) == 1
        assert int(first.get("roster_size") or 0) >= 1
        pid = int(first["woke"][0]["player_id"])

        # Second tick within wake interval: no new wake, but sticky roster still builds.
        second = run_inactive_autoplay_tick(
            conn, now=t0 + 30, force=False, source="test"
        )
        assert second.get("ok")
        assert int(second.get("woke_count") or 0) == 0
        assert int(second.get("roster_size") or 0) >= 1
        assert int(second.get("session_ticks") or 0) >= 1
        # Presence stays fresh.
        assert not is_player_id_inactive(pid, conn=conn, now=int(t0 + 30))
        commit(conn)
    finally:
        conn.close()


def test_inactive_autoplay_never_mass_wakes(autoplay_db, monkeypatch):
    from game.inactive_autoplay import (
        run_inactive_autoplay_tick,
        set_inactive_autoplay_enabled,
        wake_batch_size,
    )

    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_BATCH", "2")
    uids = [_register_user() for _ in range(10)]
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        for uid in uids:
            _seed_dormant(conn, uid, days_inactive=6.0)
        assert wake_batch_size() == 2
        result = run_inactive_autoplay_tick(
            conn, now=time.time(), force=True, source="test"
        )
        assert int(result.get("woke_count") or 0) <= 2
        commit(conn)
    finally:
        conn.close()


def test_inactive_autoplay_disabled_skips(autoplay_db):
    from game.inactive_autoplay import (
        run_inactive_autoplay_tick,
        set_inactive_autoplay_enabled,
    )

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(False, conn=conn)
        _seed_dormant(conn, uid)
        result = run_inactive_autoplay_tick(
            conn, now=time.time(), force=True, source="test"
        )
        assert result.get("ok") is False
        assert result.get("error") == "disabled"
        commit(conn)
    finally:
        conn.close()
