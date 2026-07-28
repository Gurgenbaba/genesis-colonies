"""EPIC-26 / GC-2600–2601: auto_empire + inactive autoplay."""

from __future__ import annotations

import json
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


def test_autoplay_chain_applies_levels_and_scores(autoplay_db):
    """GC-2605: force-complete chain finishes in-tick → buildings + player_scores."""
    from game.auto_empire import plan_passive_planet_tick
    from game.models import get_planet_buildings

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        player = _seed_dormant(conn, uid, days_inactive=0.1)
        # Start from empty mines so first upgrades clearly raise score.
        conn.execute(
            """
            UPDATE planet_buildings
            SET metal_mine = 0, crystal_mine = 0, solar_plant = 0
            WHERE planet_id = ?;
            """,
            (int(player["planet_id"]),),
        )
        before_b = get_planet_buildings(int(player["planet_id"]), conn=conn)
        before_score = conn.execute(
            "SELECT COALESCE(score_total, 0) AS s FROM player_scores WHERE player_id = ?;",
            (uid,),
        ).fetchone()
        score_before = int((before_score or {"s": 0})["s"] or 0)

        out = plan_passive_planet_tick(
            conn,
            player_id=uid,
            planet=player["planet"],
            now=time.time(),
            is_home=True,
            allow_ships=False,
            allow_defense=False,
            build_duration_cap=90,
            research_duration_cap=120,
            chain_limit=3,
            source="test",
            update_scores=True,
        )
        assert out.get("builds") or out.get("build") or out.get("finished")
        after_b = get_planet_buildings(int(player["planet_id"]), conn=conn)
        mine_before = (
            int(before_b.get("metal_mine") or 0)
            + int(before_b.get("crystal_mine") or 0)
            + int(before_b.get("solar_plant") or 0)
        )
        mine_after = (
            int(after_b.get("metal_mine") or 0)
            + int(after_b.get("crystal_mine") or 0)
            + int(after_b.get("solar_plant") or 0)
        )
        assert mine_after > mine_before
        # Due jobs should be cleared after final finish.
        queued = int(
            (
                conn.execute(
                    "SELECT COUNT(*) AS c FROM build_queue WHERE planet_id = ?;",
                    (int(player["planet_id"]),),
                ).fetchone()
                or {"c": 0}
            )["c"]
            or 0
        )
        assert queued == 0
        after_score = conn.execute(
            "SELECT COALESCE(score_total, 0) AS s FROM player_scores WHERE player_id = ?;",
            (uid,),
        ).fetchone()
        score_after = int((after_score or {"s": 0})["s"] or 0)
        assert score_after > score_before
        commit(conn)
    finally:
        conn.close()


def test_inactive_resource_floor_raises_empty_stockpile(autoplay_db):
    """GC-2607: empty dormant home gets soft floor so enqueue can proceed."""
    from game.inactive_autoplay import (
        INACTIVE_RESOURCE_FLOOR,
        _ensure_resource_floor,
        run_inactive_autoplay_tick,
        set_inactive_autoplay_enabled,
    )

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        player = _seed_dormant(conn, uid, days_inactive=5.0)
        conn.execute(
            "UPDATE planets SET metal = 0, crystal = 0, fuel_cells = 0 WHERE id = ?;",
            (int(player["planet_id"]),),
        )
        floor = _ensure_resource_floor(conn, int(player["planet_id"]))
        assert floor.get("raised") == 1
        row = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
            (int(player["planet_id"]),),
        ).fetchone()
        assert float(row["metal"]) >= INACTIVE_RESOURCE_FLOOR["metal"]
        assert float(row["crystal"]) >= INACTIVE_RESOURCE_FLOOR["crystal"]
        assert float(row["fuel_cells"]) >= INACTIVE_RESOURCE_FLOOR["fuel_cells"]

        result = run_inactive_autoplay_tick(
            conn, now=time.time(), force=True, source="test"
        )
        assert result.get("ok")
        assert int(result.get("woke_count") or 0) >= 1
        commit(conn)
    finally:
        conn.close()


def test_inactive_autoplay_roster_lru_rotation_covers_whole_pool(autoplay_db, monkeypatch):
    """GC-2609: full roster evicts oldest-ticked members instead of freezing forever."""
    from game.inactive_autoplay import (
        max_concurrent_sessions,
        run_inactive_autoplay_tick,
        set_inactive_autoplay_enabled,
    )

    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_MAX_SESSIONS", "4")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_BATCH", "2")

    uids = [_register_user() for _ in range(10)]
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        for uid in uids:
            _seed_dormant(conn, uid, days_inactive=10.0)
        commit(conn)
    finally:
        conn.close()

    assert max_concurrent_sessions() == 4

    distinct_woken: set = set()
    now0 = time.time()
    for cycle in range(3):
        conn = db()
        try:
            begin_write_transaction(conn)
            result = run_inactive_autoplay_tick(
                conn,
                now=now0 + cycle * 2 * 24 * 3600,
                force=True,
                source="test",
            )
            assert result.get("ok") is True
            assert int(result.get("roster_size") or 0) <= 4
            for w in result.get("woke") or []:
                distinct_woken.add(int(w["player_id"]))
            commit(conn)
        finally:
            conn.close()

    assert len(distinct_woken) > max_concurrent_sessions()


def test_admin_inactive_autoplay_roster_shows_username_and_last_seen(autoplay_db):
    """GC-2614: players.username doesn't exist (it's users.username / players.name);
    the admin payload must JOIN users so Name/Zuletzt gesehen actually render
    instead of silently swallowing the bad query and showing "-" for everyone.
    """
    from game.inactive_autoplay import run_inactive_autoplay_tick, set_inactive_autoplay_enabled
    from game.inactive_autoplay_admin import build_admin_inactive_autoplay_payload

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        _seed_dormant(conn, uid, days_inactive=5.0)
        result = run_inactive_autoplay_tick(conn, now=time.time(), force=True, source="test")
        assert int(result.get("woke_count") or 0) >= 1

        payload = build_admin_inactive_autoplay_payload(conn)
        assert payload["ok"] is True
        rows = {int(r["player_id"]): r for r in payload["roster"]}
        assert uid in rows
        row = rows[uid]
        assert row["username"], "username must be resolved via JOIN users, not left None"
        assert row["last_seen"] is not None
        commit(conn)
    finally:
        conn.close()


def test_inactive_autoplay_bulk_presence_keeps_whole_roster_online(autoplay_db, monkeypatch):
    """GC-2614 -> superseded by GC-2617: unconditionally touching the *entire*
    sticky roster every tick let the visible "online" count grow with the
    roster cap (up to 60+) regardless of the real player base — exactly the
    "40 accounts online at once looks fake" problem flagged after Phase 3
    shipped. GC-2617 bounds simultaneous presence to a small, independently
    rotating subset (`online_visible_cap`, percent of real registered
    players), with one deliberate exception: freshly-woken accounts are
    always touched immediately, so a just-woken account instantly clears the
    multi-day ranking-inactive flag instead of waiting for its rotation turn.
    This test still proves that exact requirement: in one wake wave (batch ==
    roster cap here, so "all woken" happens to mean "the whole roster"),
    every newly woken account reads as online right away — not just whoever
    got a full economy round-robin tick.
    """
    from game.inactive_autoplay import (
        run_inactive_autoplay_tick,
        set_inactive_autoplay_enabled,
        tick_per_cron,
    )
    from game.models import ONLINE_WINDOW_SEC

    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_MAX_SESSIONS", "6")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_BATCH", "6")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_TICK_PER_CRON", "1")

    uids = [_register_user() for _ in range(6)]
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        # Other pre-seeded players default last_seen=0 (never touched) — mark
        # them "seen just now" so only our 6 freshly seeded dormant accounts
        # are eligible wake candidates (mirrors the admin force-tick test).
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id NOT IN (%s);"
            % ",".join("?" * len(uids)),
            (time.time(), *uids),
        )
        for uid in uids:
            _seed_dormant(conn, uid, days_inactive=5.0)
        now = time.time()
        result = run_inactive_autoplay_tick(conn, now=now, force=True, source="test")
        assert int(result.get("woke_count") or 0) == 6
        assert tick_per_cron() == 1

        # Only 1 of 6 gets a full economy round-robin tick, but *all six* must
        # still read as online (bulk presence touch), not just that one.
        placeholders = ",".join("?" for _ in uids)
        rows = conn.execute(
            f"SELECT id, last_seen FROM players WHERE id IN ({placeholders});",
            tuple(uids),
        ).fetchall()
        assert len(rows) == 6
        for row in rows:
            assert float(row["last_seen"] or 0) >= now - ONLINE_WINDOW_SEC
        commit(conn)
    finally:
        conn.close()


def test_inactive_autoplay_eviction_sends_activity_report(autoplay_db, monkeypatch):
    """GC-2615: when the LRU evicts a roster member, they get exactly one inbox
    message summarizing what autoplay actually built/researched/defended while
    they were away — visible activity instead of a silent tick.
    """
    from game.inactive_autoplay import run_inactive_autoplay_tick, set_inactive_autoplay_enabled

    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_MAX_SESSIONS", "4")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_BATCH", "4")

    uids = [_register_user() for _ in range(8)]
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        # Other pre-seeded players default last_seen=0 (never touched) — mark
        # them "seen just now" so only our 8 freshly seeded dormant accounts
        # are eligible wake candidates (mirrors the admin force-tick test).
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id NOT IN (%s);"
            % ",".join("?" * len(uids)),
            (time.time(), *uids),
        )
        for uid in uids:
            _seed_dormant(conn, uid, days_inactive=10.0)
        now0 = time.time()
        first = run_inactive_autoplay_tick(conn, now=now0, force=True, source="test")
        assert int(first.get("woke_count") or 0) == 4
        first_ids = {int(w["player_id"]) for w in first["woke"]}
        assert first_ids.issubset(set(uids))
        commit(conn)
    finally:
        conn.close()

    # Second wake cycle: roster is full, so the first batch gets evicted.
    conn = db()
    try:
        begin_write_transaction(conn)
        second = run_inactive_autoplay_tick(
            conn, now=now0 + 24 * 3600, force=True, source="test"
        )
        assert int(second.get("evicted_count") or 0) == 4
        evicted_ids = set(first_ids)  # oldest-ticked == the ones woken first

        placeholders = ",".join("?" for _ in evicted_ids)
        msgs = conn.execute(
            f"""
            SELECT recipient_player_id, subject, body
            FROM player_messages
            WHERE recipient_player_id IN ({placeholders})
              AND category = 'system';
            """,
            tuple(evicted_ids),
        ).fetchall()
        # Every evicted account did at least one real build/research this session,
        # so each must have received exactly one report.
        recipients = [int(m["recipient_player_id"]) for m in msgs]
        assert set(recipients) == evicted_ids
        assert len(recipients) == len(set(recipients)), "must be exactly one report per session"
        for m in msgs:
            assert m["subject"]
            assert m["body"]
        commit(conn)
    finally:
        conn.close()


def test_online_visible_cap_scales_with_real_player_count(autoplay_db, monkeypatch):
    """GC-2617: the simultaneous-"online" cap must scale with the *real*
    registered player base, not be a static number lifted from the roster
    cap — otherwise a small server with a big roster cap (default 60) shows
    an implausible wall of logins ("40 Leute auf einmal online")."""
    from game.inactive_autoplay import (
        MAX_ONLINE_VISIBLE,
        MIN_ONLINE_VISIBLE,
        online_visible_cap,
    )

    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_ONLINE_PERCENT", "50")

    # `_register_user` opens its own connection/transaction — must run before
    # this test's own `begin_write_transaction`, else SQLite deadlocks. Each
    # checkpoint is its own committed phase so `more_uids` are only created
    # (and only count towards `get_registered_player_count`) *after* the
    # small-base cap has actually been measured.
    small_uids = [_register_user() for _ in range(3)]
    conn = db()
    try:
        begin_write_transaction(conn)
        for uid in small_uids:
            ensure_player_and_homeworld(uid, player_name=f"Real{uid}", conn=conn)
        cap_small_base = online_visible_cap(conn=conn)
        assert MIN_ONLINE_VISIBLE <= cap_small_base <= MAX_ONLINE_VISIBLE
        commit(conn)
    finally:
        conn.close()

    # Growing the real player base must raise the cap proportionally — proves
    # it is percent-based, not a fixed constant.
    more_uids = [_register_user() for _ in range(17)]
    conn = db()
    try:
        begin_write_transaction(conn)
        for uid in more_uids:
            ensure_player_and_homeworld(uid, player_name=f"Real{uid}", conn=conn)
        cap_big_base = online_visible_cap(conn=conn)
        assert cap_big_base > cap_small_base
        assert cap_big_base <= MAX_ONLINE_VISIBLE
        commit(conn)
    finally:
        conn.close()


def test_inactive_autoplay_presence_rotation_bounds_online_count(autoplay_db, monkeypatch):
    """GC-2617: presence visibility is decoupled from roster size — a full
    roster of standing (already-woken, not freshly-woken this tick) accounts
    must NOT all look "online" simultaneously; only a small, dynamically
    capped rotating subset does, while the rest keep building silently.

    The roster + `worker_last` are seeded directly (not via a wake tick) so
    `seconds_until_wake_allowed` is still positive and the wake/evict block
    is skipped entirely (`force=False`) — isolating exactly the presence
    rotation behavior under test, independent of wake/evict mechanics.
    """
    from game.inactive_autoplay import (
        ROSTER_KEY,
        WORKER_LAST_KEY,
        online_visible_cap,
        run_inactive_autoplay_tick,
        set_inactive_autoplay_enabled,
    )
    from game.models import ONLINE_WINDOW_SEC
    from game.runtime_state import set_runtime_value

    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_ONLINE_PERCENT", "1")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_TICK_PER_CRON", "1")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_INTERVAL_SEC", "600")

    uids = [_register_user() for _ in range(10)]
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        for uid in uids:
            _seed_dormant(conn, uid, days_inactive=5.0)

        now = time.time()
        roster = [
            {
                "player_id": uid,
                "joined_at": now - 3600,
                "last_ticked_at": now - 3600,
                "last_action": None,
                "builds_done": 0,
                "research_done": 0,
                "defense_done": 0,
            }
            for uid in uids
        ]
        set_runtime_value(ROSTER_KEY, json.dumps(roster), conn=conn)
        set_runtime_value(
            WORKER_LAST_KEY,
            json.dumps({"ok": True, "at": now, "source": "test", "woke": 0, "evicted": 0}),
            conn=conn,
        )

        cap = online_visible_cap(conn=conn)
        assert cap < len(uids), "test setup needs a cap smaller than the roster to be meaningful"

        tick_now = now + 1
        result = run_inactive_autoplay_tick(conn, now=tick_now, force=False, source="test")
        assert result.get("ok")
        assert int(result.get("woke_count") or 0) == 0, "wake/evict block must have been skipped"

        placeholders = ",".join("?" for _ in uids)
        rows = conn.execute(
            f"SELECT id, last_seen FROM players WHERE id IN ({placeholders});",
            tuple(uids),
        ).fetchall()
        online_now = sum(
            1 for r in rows if float(r["last_seen"] or 0) >= tick_now - ONLINE_WINDOW_SEC
        )
        assert online_now <= cap
        assert online_now < len(uids), "a big roster must not make everyone look online at once"
        commit(conn)
    finally:
        conn.close()


def test_auto_empire_defense_boost_uses_real_timekeeper(autoplay_db):
    """GC-2616: defense queue (not covered by duration_cap+chain_limit) gets
    auto-boosted through the *real* Timekeeper ledger — auto-credit when empty,
    then auto-apply — instead of a parallel speed mechanic.
    """
    from game import timekeeper
    from game.auto_empire import plan_passive_planet_tick

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        player = _seed_dormant(conn, uid, days_inactive=0.1)
        # Defense build requires an already-built Defense Factory (GC-039); a
        # fresh homeworld starts at level 0, so raise it as if this account had
        # played before going inactive.
        conn.execute(
            "UPDATE planet_buildings SET defense_factory = 5 WHERE planet_id = ?;",
            (int(player["planet_id"]),),
        )
        assert timekeeper.get_balance(uid, conn=conn) == 0

        out = plan_passive_planet_tick(
            conn,
            player_id=uid,
            planet=player["planet"],
            now=time.time(),
            is_home=True,
            allow_buildings=False,
            allow_research=False,
            allow_ships=False,
            allow_defense=True,
            source="test",
        )
        assert out.get("defense"), "defense job must have been enqueued"

        # Balance was auto-refilled to 10h and then partially spent applying the boost.
        balance_after = timekeeper.get_balance(uid, conn=conn)
        assert 0 <= balance_after < 36_000

        tx = conn.execute(
            """
            SELECT source FROM timekeeper_transactions
            WHERE player_id = ? ORDER BY id ASC;
            """,
            (uid,),
        ).fetchall()
        sources = [str(r["source"]) for r in tx]
        assert "autoplay_replenish" in sources
        assert any(s.startswith("apply:defense") for s in sources)

        # The auto-apply should have finished the boosted defense job in-tick.
        planet_id = int(player["planet_id"])
        built = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS n FROM planet_defense WHERE planet_id = ?;",
            (planet_id,),
        ).fetchone()
        assert int(built["n"] or 0) > 0
        commit(conn)
    finally:
        conn.close()


def test_admin_inactive_autoplay_panel_contract():
    """GC-2608: admin panel mirrors the pirates admin tab pattern exactly."""
    html = (ROOT / "templates/admin_panel.html").read_text(encoding="utf-8")
    assert 'data-admin-tab="inactive_autoplay"' in html
    assert 'data-admin-panel="inactive_autoplay"' in html
    assert 'data-admin-action="inactive-autoplay-refresh"' in html
    assert 'data-admin-action="inactive-autoplay-on"' in html
    assert 'data-admin-action="inactive-autoplay-off"' in html
    assert 'data-admin-action="inactive-autoplay-force-tick"' in html
    js = (ROOT / "static/admin.js").read_text(encoding="utf-8")
    assert "loadInactiveAutoplayAdmin" in js
    assert "/api/admin/inactive-autoplay" in js
    assert "setInactiveAutoplayAdmin" in js
    assert "/api/admin/inactive-autoplay/toggle" in js
    assert "forceTickInactiveAutoplayAdmin" in js
    assert "/api/admin/inactive-autoplay/force-tick" in js
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        assert "admin_inactive_autoplay_title" in data
        assert "admin_inactive_autoplay_toggle_on" in data
        assert "admin_inactive_autoplay_kpi_roster" in data
        assert "admin_inactive_autoplay_roster" in data
        assert "admin_inactive_autoplay_force_tick" in data
        assert "admin_inactive_autoplay_force_tick_done" in data


@pytest.fixture()
def autoplay_admin_client(autoplay_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)

    import importlib

    import app as app_module

    importlib.reload(app_module)

    ok_a, _, admin_info = create_user("autoplay_admin", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("autoplay_user", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def test_admin_inactive_autoplay_api_and_toggle(autoplay_admin_client):
    """GC-2608: admin GET/toggle mirror the pirates auth + kill-switch contract."""
    client, admin_id, user_id = autoplay_admin_client

    r = client.get("/api/admin/inactive-autoplay")
    assert r.status_code == 401

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    r = client.get("/api/admin/inactive-autoplay")
    assert r.status_code == 403

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
    r = client.get("/api/admin/inactive-autoplay")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["enabled"] is True
    assert "roster" in data
    assert "kpis" in data
    assert "config" in data

    off = client.post("/api/admin/inactive-autoplay/toggle", json={"enabled": False})
    assert off.status_code == 200
    off_data = off.get_json()
    assert off_data["ok"] is True
    assert off_data["enabled"] is False

    r2 = client.get("/api/admin/inactive-autoplay")
    assert r2.get_json()["enabled"] is False

    on = client.post("/api/admin/inactive-autoplay/toggle", json={"enabled": True})
    assert on.status_code == 200
    assert on.get_json()["enabled"] is True

    missing = client.post("/api/admin/inactive-autoplay/toggle", json={})
    assert missing.status_code == 400
    assert missing.get_json()["error"] == "enabled_required"


def test_admin_inactive_autoplay_force_tick_wakes_players_now(autoplay_admin_client):
    """GC-2613: LiveOps must be able to wake 2-3 dormant accounts immediately —
    without waiting for embedded cron (off by default outside production, see
    game.config.is_embedded_cron_enabled) or the wake-interval guard.
    """
    client, admin_id, user_id = autoplay_admin_client

    dormant_ids = [_register_user() for _ in range(3)]
    conn = db()
    try:
        begin_write_transaction(conn)
        # The fixture's own admin/user players default last_seen=0 (never touched
        # by a real request) — mark them "seen just now" so only our freshly
        # seeded dormant_ids are eligible wake candidates for this assertion.
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id NOT IN (%s);"
            % ",".join("?" * len(dormant_ids)),
            (time.time(), *dormant_ids),
        )
        for uid in dormant_ids:
            _seed_dormant(conn, uid, days_inactive=5.0)
        commit(conn)
    finally:
        conn.close()

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id

    # Sanity: nothing woke yet — mirrors a fresh local dev boot with no cron running.
    pre = client.get("/api/admin/inactive-autoplay").get_json()
    assert pre["kpis"]["roster_size"] == 0

    res = client.post("/api/admin/inactive-autoplay/force-tick", json={})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["woke_count"] > 0
    assert data["roster_size"] >= data["woke_count"]
    woken_ids = {int(w["player_id"]) for w in data["woke"]}
    assert woken_ids.issubset(set(dormant_ids))

    post = client.get("/api/admin/inactive-autoplay").get_json()
    assert post["kpis"]["roster_size"] == data["roster_size"]
    assert post["kpis"]["woke_last_cycle"] == data["woke_count"]

    off = client.post("/api/admin/inactive-autoplay/toggle", json={"enabled": False})
    assert off.status_code == 200
    tick_off = client.post("/api/admin/inactive-autoplay/force-tick", json={})
    assert tick_off.status_code == 400
    assert tick_off.get_json()["error"] == "disabled"
