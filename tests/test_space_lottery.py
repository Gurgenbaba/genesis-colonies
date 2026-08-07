"""EPIC-28 Space Lottery — Tombola, Mines, Crash."""

from __future__ import annotations

import uuid

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.provably_fair import hash_seed
from game.space_lottery import (
    MIN_BET_SEC,
    TICKET_PRICE_SEC,
    buy_tombola_tickets,
    cashout_crash,
    cashout_mines,
    crash_point_from_seed,
    current_week_id,
    draw_week,
    mines_multiplier,
    reveal_mines_cell,
    schema_ready,
    serialize_state,
    start_crash,
    start_mines,
    verify_round,
    week_draw_at,
)
from game.timekeeper import credit, get_balance


@pytest.fixture
def lottery_db(tmp_path, monkeypatch):
    db_path = tmp_path / "space_lottery.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    # Unlock Mines/Crash in tests — live product gate is tombola-only.
    monkeypatch.setattr(
        "game.space_lottery.LIVE_MODES",
        frozenset({"tombola", "mines", "crash"}),
    )
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def test_live_modes_tombola_only_by_default():
    from game import space_lottery as sl

    assert "tombola" in sl.LIVE_MODES
    assert "mines" not in sl.LIVE_MODES
    assert "crash" not in sl.LIVE_MODES
    assert sl.mode_enabled("tombola") is True
    assert sl.mode_enabled("mines") is False
    assert sl.mode_enabled("crash") is False


def test_mines_and_crash_blocked_when_live_gate_on(lottery_db, monkeypatch):
    monkeypatch.setattr("game.space_lottery.LIVE_MODES", frozenset({"tombola"}))
    uid = _player()
    _fund(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, _ = start_mines(uid, MIN_BET_SEC, mine_count=3, conn=conn)
        assert not ok and reason == "mode_disabled"
        ok2, reason2, _ = start_crash(uid, MIN_BET_SEC, conn=conn)
        assert not ok2 and reason2 == "mode_disabled"
        st = serialize_state(uid, conn=conn)
        assert st["modes"]["tombola"] is True
        assert st["modes"]["mines"] is False
        assert st["modes"]["crash"] is False
        commit(conn)
    finally:
        conn.close()


def _player(name: str = "LotteryTester") -> int:
    ok, err, user = create_user(f"sl_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return uid


def _fund(uid: int, sec: int = 50_000) -> None:
    conn = db()
    try:
        begin_write_transaction(conn)
        credit(uid, sec, "test:fund", conn=conn)
        commit(conn)
    finally:
        conn.close()


def test_schema_ready(lottery_db):
    conn = db()
    try:
        assert schema_ready(conn)
    finally:
        conn.close()


def test_mines_multiplier_increases():
    m0 = mines_multiplier(0, 3)
    m1 = mines_multiplier(1, 3)
    m3 = mines_multiplier(3, 3)
    assert m0 == 1.0
    assert m1 > m0
    assert m3 > m1


def test_tombola_buy_and_pool(lottery_db):
    uid = _player()
    _fund(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        before = get_balance(uid, conn=conn)
        ok, reason, state = buy_tombola_tickets(uid, 2, conn=conn)
        assert ok, reason
        assert state["tombola"]["my_tickets"] == 2
        assert state["tombola"]["pool_sec"] == 2 * TICKET_PRICE_SEC
        assert get_balance(uid, conn=conn) == before - 2 * TICKET_PRICE_SEC
        commit(conn)
    finally:
        conn.close()


def test_tombola_draw_pays_winner(lottery_db, monkeypatch):
    a = _player("A")
    b = _player("B")
    _fund(a)
    _fund(b)
    monkeypatch.setattr("game.space_lottery.current_week_id", lambda now=None: "2099-W01")
    conn = db()
    try:
        begin_write_transaction(conn)
        assert buy_tombola_tickets(a, 1, conn=conn)[0]
        assert buy_tombola_tickets(b, 3, conn=conn)[0]
        monkeypatch.setattr("game.space_lottery.current_week_id", lambda now=None: "2099-W02")
        ok, reason, week_row = draw_week("2099-W01", conn=conn)
        assert ok, reason
        assert week_row["status"] == "paid"
        assert week_row["winner_player_id"] in (a, b)
        assert int(week_row["pool_sec"]) == 4 * TICKET_PRICE_SEC
        ok2, reason2, _ = draw_week("2099-W01", conn=conn)
        assert ok2 and reason2 == "already_paid"
        commit(conn)
    finally:
        conn.close()


def test_mines_bust_and_cashout(lottery_db):
    uid = _player()
    _fund(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        before = get_balance(uid, conn=conn)
        ok, reason, state = start_mines(uid, MIN_BET_SEC, mine_count=3, conn=conn)
        assert ok, reason
        assert state["active_round"]["game"] == "mines"
        rid = int(state["active_round"]["id"])
        # Peek mines from DB
        row = conn.execute(
            "SELECT payload_json, seed FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        import json

        payload = json.loads(row["payload_json"])
        mines = set(payload["mine_positions"])
        safe = [i for i in range(25) if i not in mines][0]
        ok, reason, state = reveal_mines_cell(uid, safe, conn=conn)
        assert ok, reason
        assert state["active_round"]["status"] == "active"
        ok, reason, state = cashout_mines(uid, conn=conn)
        assert ok, reason
        assert state["active_round"] is None
        assert get_balance(uid, conn=conn) > before - MIN_BET_SEC
        # Verify last round
        last = conn.execute(
            "SELECT id FROM space_lottery_rounds WHERE player_id = ? ORDER BY id DESC LIMIT 1;",
            (uid,),
        ).fetchone()
        vok, vreason, vres = verify_round(int(last["id"]), conn=conn)
        assert vok, vreason
        assert vres["matches"] is True

        # Bust path
        ok, reason, state = start_mines(uid, MIN_BET_SEC, mine_count=5, conn=conn)
        assert ok, reason
        rid = int(state["active_round"]["id"])
        row = conn.execute(
            "SELECT payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        payload = json.loads(row["payload_json"])
        hit = int(payload["mine_positions"][0])
        mid = get_balance(uid, conn=conn)
        ok, reason, state = reveal_mines_cell(uid, hit, conn=conn)
        assert ok and reason == "bust"
        assert get_balance(uid, conn=conn) == mid
        commit(conn)
    finally:
        conn.close()


def test_crash_cashout_and_bust(lottery_db):
    """Cashout is time-progress SoT (not raw client mult); bust after runway elapses."""
    from game.space_lottery import crash_bust_after_ms, crash_mult_at_progress

    uid = _player()
    _fund(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, state = start_crash(uid, MIN_BET_SEC, conn=conn)
        assert ok, reason
        rid = int(state["active_round"]["id"])
        row = conn.execute(
            "SELECT seed, created_at, payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        import json

        payload = json.loads(row["payload_json"])
        point = float(payload["crash_point"])
        assert abs(point - crash_point_from_seed(row["seed"], rid)) < 1e-9
        assert hash_seed(row["seed"]) == state["active_round"]["seed_hash"]
        bust_ms = crash_bust_after_ms(point)
        created = float(row["created_at"])

        if point <= 1.01:
            # Instant crash point — age past runway → bust
            conn.execute(
                "UPDATE space_lottery_rounds SET created_at = ? WHERE id = ?;",
                (created - (bust_ms + 600) / 1000.0, rid),
            )
            ok, reason, state = cashout_crash(uid, 2.0, conn=conn)
            assert reason == "bust"
        else:
            # Mid-climb cashout at fair progress (~50%)
            conn.execute(
                "UPDATE space_lottery_rounds SET created_at = ? WHERE id = ?;",
                (created - (bust_ms * 0.5) / 1000.0, rid),
            )
            fair = crash_mult_at_progress(point, 0.5)
            before = get_balance(uid, conn=conn)
            ok, reason, state = cashout_crash(uid, fair, conn=conn)
            assert ok and reason == "ok", (ok, reason)
            assert get_balance(uid, conn=conn) >= before

        ok, reason, state = start_crash(uid, MIN_BET_SEC, conn=conn)
        assert ok, reason
        rid = int(state["active_round"]["id"])
        row = conn.execute(
            "SELECT created_at, payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        point = float(json.loads(row["payload_json"])["crash_point"])
        bust_ms = crash_bust_after_ms(point)
        created = float(row["created_at"])
        # Past runway (incl. start-lag grace) → bust regardless of client mult
        conn.execute(
            "UPDATE space_lottery_rounds SET created_at = ? WHERE id = ?;",
            (created - (bust_ms + 600) / 1000.0, rid),
        )
        ok, reason, state = cashout_crash(uid, 1.5, conn=conn)
        assert reason == "bust"
        vok, _, vres = verify_round(rid, conn=conn)
        assert vok and vres["matches"]
        commit(conn)
    finally:
        conn.close()


def test_serialize_state(lottery_db):
    uid = _player()
    _fund(uid, 1000)
    conn = db()
    try:
        begin_write_transaction(conn)
        st = serialize_state(uid, conn=conn)
        assert st["ready"] is True
        assert st["tombola"]["week_id"]
        assert st["tombola"]["ends_in_sec"] > 0
        assert st["tombola"]["ends_at"] == week_draw_at(st["tombola"]["week_id"])
        assert isinstance(st["tombola"]["recent_winners"], list)
        assert "mines_history" in st and isinstance(st["mines_history"], list)
        assert "mines_today" in st
        assert st["mines_today"]["won_sec"] == 0
        assert "potential_by_mines" in st["mines_defaults"]
        assert st["mines_defaults"]["potential_by_mines"]["3"] == round(
            mines_multiplier(22, 3), 4
        )
        commit(conn)
    finally:
        conn.close()


def test_mines_history_and_today(lottery_db):
    uid = _player()
    _fund(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        import json

        ok, reason, state = start_mines(uid, MIN_BET_SEC, mine_count=3, conn=conn)
        assert ok, reason
        ar = state["active_round"]
        assert ar["mines"]["hits"] == 0
        assert ar["mines"]["max_safe"] == 22
        assert ar["mines"]["potential_multiplier"] == round(mines_multiplier(22, 3), 4)

        rid = int(ar["id"])
        row = conn.execute(
            "SELECT payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        payload = json.loads(row["payload_json"])
        mines = set(payload["mine_positions"])
        safe = [i for i in range(25) if i not in mines][:2]
        for cell in safe:
            ok, reason, state = reveal_mines_cell(uid, cell, conn=conn)
            assert ok, reason
        assert state["active_round"]["mines"]["hits"] == 2
        ok, reason, state = cashout_mines(uid, conn=conn)
        assert ok, reason
        assert state["mines_today"]["won_sec"] > 0
        assert state["mines_today"]["best_mult"] > 1.0
        assert state["mines_history"]
        assert state["mines_history"][0]["status"] == "cashed"
        assert state["mines_history"][0]["multiplier"] > 1.0

        # Bust path lands in history
        ok, reason, state = start_mines(uid, MIN_BET_SEC, mine_count=5, conn=conn)
        assert ok, reason
        rid = int(state["active_round"]["id"])
        row = conn.execute(
            "SELECT payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        payload = json.loads(row["payload_json"])
        hit = int(payload["mine_positions"][0])
        ok, reason, state = reveal_mines_cell(uid, hit, conn=conn)
        assert ok and reason == "bust"
        assert any(h["status"] == "bust" for h in state["mines_history"])
        commit(conn)
    finally:
        conn.close()


def test_recent_winners_after_draw(lottery_db, monkeypatch):
    a = _player("WinnerA")
    _fund(a)
    monkeypatch.setattr("game.space_lottery.current_week_id", lambda now=None: "2099-W01")
    conn = db()
    try:
        begin_write_transaction(conn)
        assert buy_tombola_tickets(a, 2, conn=conn)[0]
        monkeypatch.setattr("game.space_lottery.current_week_id", lambda now=None: "2099-W02")
        ok, reason, week_row = draw_week("2099-W01", conn=conn)
        assert ok, reason
        st = serialize_state(a, conn=conn)
        winners = st["tombola"]["recent_winners"]
        assert winners
        assert winners[0]["winner_player_id"] == a
        assert winners[0]["pool_sec"] == 2 * TICKET_PRICE_SEC
        assert winners[0]["winner_name"]
        commit(conn)
    finally:
        conn.close()


def test_week_draw_at_sunday_20_utc():
    # 2026-W23 Monday is 2026-06-01 → Sunday 2026-06-07 20:00 UTC
    ts = week_draw_at("2026-W23")
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    assert dt.weekday() == 6
    assert dt.hour == 20
    assert dt.minute == 0


def test_crash_history_and_today(lottery_db):
    from game.space_lottery import CRASH_MAX_MULT, crash_bust_after_ms, crash_mult_at_progress

    uid = _player()
    _fund(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        assert CRASH_MAX_MULT >= 1000.0
        st = serialize_state(uid, conn=conn)
        assert "crash_history" in st
        assert "crash_today" in st
        assert st["crash_defaults"]["max_mult"] == CRASH_MAX_MULT

        ok, reason, state = start_crash(uid, MIN_BET_SEC, conn=conn)
        assert ok, reason
        rid = int(state["active_round"]["id"])
        import json

        row = conn.execute(
            "SELECT created_at, payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        point = float(json.loads(row["payload_json"])["crash_point"])
        bust_ms = crash_bust_after_ms(point)
        created = float(row["created_at"])

        if point <= 1.01:
            conn.execute(
                "UPDATE space_lottery_rounds SET created_at = ? WHERE id = ?;",
                (created - (bust_ms + 600) / 1000.0, rid),
            )
            ok, reason, state = cashout_crash(uid, 2.0, conn=conn)
            assert reason == "bust"
            ok, reason, state = start_crash(uid, MIN_BET_SEC, conn=conn)
            assert ok, reason
            rid = int(state["active_round"]["id"])
            row = conn.execute(
                "SELECT created_at, payload_json FROM space_lottery_rounds WHERE id = ?;",
                (rid,),
            ).fetchone()
            point = float(json.loads(row["payload_json"])["crash_point"])
            bust_ms = crash_bust_after_ms(point)
            created = float(row["created_at"])
            if point <= 1.01:
                commit(conn)
                return

        conn.execute(
            "UPDATE space_lottery_rounds SET created_at = ? WHERE id = ?;",
            (created - (bust_ms * 0.5) / 1000.0, rid),
        )
        target = crash_mult_at_progress(point, 0.5)
        ok, reason, state = cashout_crash(uid, target, conn=conn)
        assert ok and reason == "ok", (ok, reason)
        assert state["crash_today"]["won_sec"] > 0
        assert state["crash_history"]
        assert state["crash_history"][0]["status"] == "cashed"
        assert state["crash_history"][0]["multiplier"] > 1.0

        # Double cashout rejected
        ok2, reason2, _ = cashout_crash(uid, target, conn=conn)
        assert not ok2 and reason2 == "no_active_round"
        commit(conn)
    finally:
        conn.close()


def test_crash_cashout_uses_elapsed_not_inflated_client_mult(lottery_db):
    """GC-2810 fix: client display overshoot must not force bust if still before crash time."""
    from game.space_lottery import crash_bust_after_ms, crash_mult_at_progress

    uid = _player()
    _fund(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, state = start_crash(uid, MIN_BET_SEC, conn=conn)
        assert ok, reason
        rid = int(state["active_round"]["id"])
        import json
        from game.space_lottery import CRASH_START_LAG_MS

        row = conn.execute(
            "SELECT created_at, payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        point = float(json.loads(row["payload_json"])["crash_point"])
        if point <= 1.01:
            commit(conn)
            return
        bust_ms = crash_bust_after_ms(point)
        # Wall elapsed = lag + 40% runway → effective progress 0.4 after lag subtract
        created = float(row["created_at"])
        wall_ms = float(CRASH_START_LAG_MS) + bust_ms * 0.4
        conn.execute(
            "UPDATE space_lottery_rounds SET created_at = ? WHERE id = ?;",
            (created - wall_ms / 1000.0, rid),
        )
        fair = crash_mult_at_progress(point, 0.4)
        # Client wrongly sends 31× — server must still cash out at fair progress.
        ok, reason, state = cashout_crash(uid, 31.42, conn=conn)
        assert ok and reason == "ok", (ok, reason)
        assert state["crash_history"][0]["status"] == "cashed"
        assert state["crash_history"][0]["multiplier"] <= point
        assert abs(state["crash_history"][0]["multiplier"] - fair) < 0.05 or state["crash_history"][0]["multiplier"] <= fair
        commit(conn)
    finally:
        conn.close()


def test_crash_history_exposes_crash_point_after_cashout(lottery_db):
    """After early cashout, history must reveal how high the round would have flown."""
    from game.space_lottery import crash_bust_after_ms, crash_mult_at_progress, CRASH_START_LAG_MS

    uid = _player()
    _fund(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, state = start_crash(uid, MIN_BET_SEC, conn=conn)
        assert ok, reason
        rid = int(state["active_round"]["id"])
        import json

        row = conn.execute(
            "SELECT created_at, payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        point = float(json.loads(row["payload_json"])["crash_point"])
        if point <= 1.5:
            commit(conn)
            return
        bust_ms = crash_bust_after_ms(point)
        created = float(row["created_at"])
        wall_ms = float(CRASH_START_LAG_MS) + bust_ms * 0.35
        conn.execute(
            "UPDATE space_lottery_rounds SET created_at = ? WHERE id = ?;",
            (created - wall_ms / 1000.0, rid),
        )
        fair = crash_mult_at_progress(point, 0.35)
        ok, reason, state = cashout_crash(uid, fair, conn=conn)
        assert ok and reason == "ok", (ok, reason)
        h = state["crash_history"][0]
        assert h["status"] == "cashed"
        assert h["crash_point"] == point or abs(float(h["crash_point"]) - point) < 1e-9
        assert float(h["cashout_mult"] or h["multiplier"]) < float(h["crash_point"])
        commit(conn)
    finally:
        conn.close()


def test_crash_point_respects_max_cap():
    from game.space_lottery import CRASH_MAX_MULT, crash_point_from_seed

    # Deterministic: any seed result must be within [1, max]
    for i in range(20):
        p = crash_point_from_seed(f"seed-{i}", i + 1)
        assert 1.0 <= p <= CRASH_MAX_MULT


def test_daily_wager_caps_per_game(lottery_db):
    """GC-2809: tombola / mines / crash each have independent daily volume."""
    from game.space_lottery import DAILY_WAGER_CAPS_SEC

    uid = _player()
    _fund(uid, 200_000)
    conn = db()
    try:
        begin_write_transaction(conn)
        st = serialize_state(uid, conn=conn)
        by_game = st["caps"]["by_game"]
        assert by_game["tombola"]["cap_sec"] == DAILY_WAGER_CAPS_SEC["tombola"]
        assert by_game["mines"]["cap_sec"] == DAILY_WAGER_CAPS_SEC["mines"]
        assert by_game["crash"]["cap_sec"] == DAILY_WAGER_CAPS_SEC["crash"]
        assert by_game["mines"]["cap_sec"] > by_game["tombola"]["cap_sec"]

        # Fill tombola to cap via tickets (max 50 per buy) — must not block mines.
        tombola_cap = DAILY_WAGER_CAPS_SEC["tombola"]
        n = tombola_cap // TICKET_PRICE_SEC
        bought = 0
        while bought < n:
            chunk = min(50, n - bought)
            ok, reason, st = buy_tombola_tickets(uid, chunk, conn=conn)
            assert ok, reason
            bought += chunk
        assert st["caps"]["by_game"]["tombola"]["wagered_sec"] == n * TICKET_PRICE_SEC
        assert st["caps"]["by_game"]["mines"]["wagered_sec"] == 0
        ok, reason, _ = buy_tombola_tickets(uid, 1, conn=conn)
        assert not ok and reason == "daily_wager_cap"

        ok, reason, st = start_mines(uid, MIN_BET_SEC, mine_count=3, conn=conn)
        assert ok, reason
        assert st["caps"]["by_game"]["mines"]["wagered_sec"] == MIN_BET_SEC
        import json

        rid = int(st["active_round"]["id"])
        row = conn.execute(
            "SELECT payload_json FROM space_lottery_rounds WHERE id = ?;",
            (rid,),
        ).fetchone()
        hit = int(json.loads(row["payload_json"])["mine_positions"][0])
        reveal_mines_cell(uid, hit, conn=conn)

        ok, reason, st = start_crash(uid, MIN_BET_SEC, conn=conn)
        assert ok, reason
        assert st["caps"]["by_game"]["crash"]["wagered_sec"] == MIN_BET_SEC
        assert st["caps"]["by_game"]["tombola"]["wagered_sec"] == n * TICKET_PRICE_SEC
        commit(conn)
    finally:
        conn.close()
