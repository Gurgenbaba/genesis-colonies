"""GC-WB-TAME — World Boss catch + companion missions."""

from __future__ import annotations

import random
import time
import uuid

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.story.free_shop import ARK_TOKEN_KEY
from game.timekeeper import credit, get_balance
from game.world_boss import spawn_world_boss
from game.world_boss_companions import (
    CATCH_COST_SEC,
    CATCH_COOLDOWN_SEC,
    MISSION_DURATION_SEC,
    MISSION_VARIANTS,
    BASE_COMPANION_CAPACITY,
    MAX_COMPANION_CAPACITY,
    attempt_tame,
    build_catch_info_for_event,
    build_overview_companions,
    claim_mission_reward,
    companions_schema_ready,
    get_companion_capacity,
    get_bonus_slots,
    grant_companion_slot,
    has_companion,
    list_mission_offers,
    mission_reward_tokens,
    refresh_mission_status,
    start_companion_mission,
)


@pytest.fixture
def wb_db(tmp_path, monkeypatch):
    db_path = tmp_path / "world_boss_tame_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(name="Tamer"):
    ok, err, user = create_user(f"tame_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        commit(conn)
    finally:
        conn.close()
    return uid


def _spawn_phase3(conn, boss_key="void_titan", *, position: int = 9, system: int = 2):
    result = spawn_world_boss(
        boss_key,
        conn=conn,
        galaxy=1,
        system=int(system),
        position=int(position),
        announce=False,
        force=True,
    )
    assert result["ok"], result
    event = result["event"]
    eid = int(event["id"])
    max_hp = int(event["max_hp"])
    # Phase 3: ≤25% HP remaining
    target_hp = max(1, int(max_hp * 0.20))
    conn.execute(
        "UPDATE world_boss_events SET current_hp = ?, updated_at = ? WHERE id = ?;",
        (target_hp, time.time(), eid),
    )
    from game.world_boss import get_event_by_id

    return get_event_by_id(eid, conn=conn)


def test_companions_schema(wb_db):
    conn = db()
    try:
        assert companions_schema_ready(conn)
    finally:
        conn.close()


def test_catch_success_and_once(wb_db):
    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        event = _spawn_phase3(conn)
        credit(uid, CATCH_COST_SEC * 3, "test", conn=conn)
        info = build_catch_info_for_event(uid, event, conn=conn)
        assert info["can_attempt"] is True
        assert info["phase_ok"] is True

        ok = attempt_tame(
            uid,
            int(event["id"]),
            conn=conn,
            rng=random.Random(0),  # deterministic; may fail or succeed
        )
        # Force success path with fixed rng that returns < 0.10
        # Re-credit and clear CD for a guaranteed success roll.
        conn.execute(
            "UPDATE player_boss_catch_state SET cooldown_until = 0 WHERE player_id = ?;",
            (uid,),
        )
        credit(uid, CATCH_COST_SEC, "test2", conn=conn)
        # If first roll already tamed, skip; else force success.
        if not has_companion(uid, "void_titan", conn=conn):
            class _R:
                def random(self):
                    return 0.01

            ok = attempt_tame(uid, int(event["id"]), conn=conn, rng=_R())
            assert ok["ok"] and ok["success"]
        assert has_companion(uid, "void_titan", conn=conn)

        conn.execute(
            "UPDATE player_boss_catch_state SET cooldown_until = 0 WHERE player_id = ?;",
            (uid,),
        )
        credit(uid, CATCH_COST_SEC, "test3", conn=conn)
        again = attempt_tame(
            uid,
            int(event["id"]),
            conn=conn,
            rng=random.Random(1),
        )
        assert again["ok"] is False
        assert again["error"] == "already_tamed"
        commit(conn)
    finally:
        conn.close()


def test_tame_removes_boss_and_auto_pays_participants(wb_db):
    """Successful catch ends the live event and auto-claims contrib rewards."""
    from game.inventory import inventory_amount
    from game.world_boss import (
        STATUS_TAMED,
        _player_claim_row,
        claim_world_boss_rewards,
        get_event_by_id,
        list_active_events,
    )

    uid_a = _player("wb_tame_a")
    uid_b = _player("wb_tame_b")
    conn = db()
    try:
        begin_write_transaction(conn)
        event = _spawn_phase3(conn, "void_titan")
        eid = int(event["id"])
        now = time.time()
        for uid, dmg in ((uid_a, 5000), (uid_b, 1500)):
            conn.execute(
                """
                INSERT INTO world_boss_contributions (
                    event_id, player_id, alliance_id, damage, waves,
                    last_attack_at, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, 1, ?, ?, ?);
                """,
                (eid, uid, dmg, now, now, now),
            )
        credit(uid_a, CATCH_COST_SEC, "tame_pay", conn=conn)

        class _Ok:
            def random(self):
                return 0.0

        result = attempt_tame(uid_a, eid, conn=conn, rng=_Ok())
        assert result["ok"] and result["success"]
        assert result.get("event_status") == STATUS_TAMED
        assert int((result.get("reward_distribution") or {}).get("claimed_count") or 0) == 2

        closed = get_event_by_id(eid, conn=conn)
        assert closed is not None
        assert closed["status"] == STATUS_TAMED
        assert int(closed["current_hp"]) == 0
        active_ids = {int(e["id"]) for e in list_active_events(conn=conn)}
        assert eid not in active_ids

        claim_a = _player_claim_row(eid, uid_a, conn=conn)
        claim_b = _player_claim_row(eid, uid_b, conn=conn)
        assert claim_a and claim_a["rewards"]
        assert claim_b and claim_b["rewards"]
        assert inventory_amount(uid_a, "container_void_artifact", conn=conn) > 0
        assert inventory_amount(uid_b, "container_void_artifact", conn=conn) > 0

        again = claim_world_boss_rewards(uid_a, eid, conn=conn, now=now)
        assert again["ok"] is False
        assert again["error"] == "already_claimed"
        commit(conn)
    finally:
        conn.close()


def test_catch_phase_and_cooldown(wb_db):
    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        result = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=1,
            system=3,
            position=7,
            announce=False,
        )
        assert result["ok"]
        event = result["event"]
        credit(uid, CATCH_COST_SEC * 2, "test", conn=conn)
        blocked = attempt_tame(uid, int(event["id"]), conn=conn, rng=random.Random(0))
        assert blocked["ok"] is False
        assert blocked["error"] == "phase_locked"

        # Force phase 3
        max_hp = int(event["max_hp"])
        conn.execute(
            "UPDATE world_boss_events SET current_hp = ? WHERE id = ?;",
            (int(max_hp * 0.2), int(event["id"])),
        )
        from game.world_boss import get_event_by_id

        event = get_event_by_id(int(event["id"]), conn=conn)

        class _Fail:
            def random(self):
                return 0.99

        fail = attempt_tame(uid, int(event["id"]), conn=conn, rng=_Fail())
        assert fail["ok"] and fail["success"] is False
        assert float(fail["cooldown_until"]) > time.time()
        bal_after = get_balance(uid, conn=conn)
        assert bal_after == CATCH_COST_SEC  # one attempt spent

        blocked_cd = attempt_tame(uid, int(event["id"]), conn=conn, rng=_Fail())
        assert blocked_cd["ok"] is False
        assert blocked_cd["error"] == "catch_cooldown"
        assert CATCH_COOLDOWN_SEC == 3600
        commit(conn)
    finally:
        conn.close()


def test_companion_mission_ark_tokens(wb_db):
    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        event = _spawn_phase3(conn, "planet_eater")
        credit(uid, CATCH_COST_SEC, "test", conn=conn)

        class _Ok:
            def random(self):
                return 0.0

        tame = attempt_tame(uid, int(event["id"]), conn=conn, rng=_Ok())
        assert tame["ok"] and tame["success"]

        overview = build_overview_companions(uid, conn=conn)
        assert overview["ready"]
        assert overview["owned_count"] >= 1
        slot = next(s for s in overview["slots"] if s["boss_key"] == "planet_eater")
        assert slot["owned"] and slot["mission"]["can_start"]
        offers = slot.get("mission_offers") or []
        assert len(offers) == 3
        assert {o["variant_key"] for o in offers} == {"patrol", "strike", "void_run"}
        assert offers[0]["duration_sec"] == MISSION_VARIANTS["patrol"]["duration_sec"]
        assert offers[1]["duration_sec"] == MISSION_DURATION_SEC
        assert offers[2]["fail_chance"] == MISSION_VARIANTS["void_run"]["fail_chance"]

        started = start_companion_mission(
            uid, "planet_eater", conn=conn, variant_key="strike"
        )
        assert started["ok"]
        assert started["variant_key"] == "strike"
        assert started["mission"]["status"] == "away"
        assert started["fail_chance"] == 0.25
        assert started["reward_tokens"] == mission_reward_tokens(
            "planet_eater", 1, variant_key="strike"
        )

        bad = start_companion_mission(
            uid, "planet_eater", conn=conn, variant_key="nope"
        )
        assert bad["ok"] is False
        assert bad["error"] == "invalid_variant"

        # Fast-forward mission end — force success roll
        conn.execute(
            "UPDATE player_boss_missions SET ends_at = ? WHERE player_id = ? AND boss_key = ?;",
            (time.time() - 1, uid, "planet_eater"),
        )

        class _Success:
            def random(self):
                return 0.99

        ready = refresh_mission_status(
            uid, "planet_eater", conn=conn, now=time.time(), rng=_Success()
        )
        assert ready["status"] == "ready"
        assert ready["outcome"] == "success"

        from game.inventory import inventory_amount

        before = int(inventory_amount(uid, ARK_TOKEN_KEY, conn=conn) or 0)
        claimed = claim_mission_reward(uid, "planet_eater", conn=conn)
        assert claimed["ok"]
        assert claimed["success"] is True
        after = int(inventory_amount(uid, ARK_TOKEN_KEY, conn=conn) or 0)
        assert after == before + int(claimed["tokens_granted"])
        assert claimed["tokens_granted"] > 0
        commit(conn)
    finally:
        conn.close()


def test_mission_sync_marks_ready_immediately(wb_db):
    """Countdown end must flip away→ready without waiting for fleet_worker."""
    from game.world_boss_companions import sync_companion_mission

    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        event = _spawn_phase3(conn, "ancient_leviathan")
        credit(uid, CATCH_COST_SEC, "test", conn=conn)

        class _Ok:
            def random(self):
                return 0.0

        tame = attempt_tame(uid, int(event["id"]), conn=conn, rng=_Ok())
        assert tame["ok"] and tame["success"]
        started = start_companion_mission(
            uid, "ancient_leviathan", conn=conn, variant_key="patrol"
        )
        assert started["ok"]
        conn.execute(
            "UPDATE player_boss_missions SET ends_at = ? WHERE player_id = ? AND boss_key = ?;",
            (time.time() - 1, uid, "ancient_leviathan"),
        )
        synced = sync_companion_mission(uid, "ancient_leviathan", conn=conn)
        assert synced["ok"]
        assert synced["status"] == "ready"
        commit(conn)
    finally:
        conn.close()


def test_companion_mission_can_fail(wb_db):
    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        event = _spawn_phase3(conn, "void_titan")
        credit(uid, CATCH_COST_SEC, "test", conn=conn)

        class _Ok:
            def random(self):
                return 0.0

        tame = attempt_tame(uid, int(event["id"]), conn=conn, rng=_Ok())
        assert tame["ok"] and tame["success"]

        started = start_companion_mission(
            uid, "void_titan", conn=conn, variant_key="void_run"
        )
        assert started["ok"]
        assert started["duration_sec"] == 8 * 3600
        assert started["fail_chance"] == 0.40

        conn.execute(
            "UPDATE player_boss_missions SET ends_at = ? WHERE player_id = ? AND boss_key = ?;",
            (time.time() - 1, uid, "void_titan"),
        )

        class _Fail:
            def random(self):
                return 0.0  # 0.0 < 0.40 → fail

        ready = refresh_mission_status(
            uid, "void_titan", conn=conn, now=time.time(), rng=_Fail()
        )
        assert ready["status"] == "ready"
        assert ready["outcome"] == "fail"
        assert int(ready["reward_tokens"] or 0) == 0

        from game.inventory import inventory_amount

        before = int(inventory_amount(uid, ARK_TOKEN_KEY, conn=conn) or 0)
        claimed = claim_mission_reward(uid, "void_titan", conn=conn)
        assert claimed["ok"]
        assert claimed["success"] is False
        assert claimed["tokens_granted"] == 0
        after = int(inventory_amount(uid, ARK_TOKEN_KEY, conn=conn) or 0)
        assert after == before
        commit(conn)
    finally:
        conn.close()


def test_capacity_blocks_second_tame_and_shop_slot(wb_db):
    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        assert get_companion_capacity(uid, conn=conn) == BASE_COMPANION_CAPACITY

        e1 = _spawn_phase3(conn, "void_titan")
        credit(uid, CATCH_COST_SEC * 4, "test", conn=conn)

        class _Ok:
            def random(self):
                return 0.0

        first = attempt_tame(uid, int(e1["id"]), conn=conn, rng=_Ok())
        assert first["ok"] and first["success"]

        e2 = _spawn_phase3(conn, "ancient_leviathan", position=8, system=3)
        # force phase 3 already done in helper; clear catch CD for second boss
        conn.execute(
            "UPDATE player_boss_catch_state SET cooldown_until = 0 WHERE player_id = ?;",
            (uid,),
        )
        blocked = attempt_tame(uid, int(e2["id"]), conn=conn, rng=_Ok())
        assert blocked["ok"] is False
        assert blocked["error"] == "capacity_full"

        grant = grant_companion_slot(uid, conn=conn, source="test")
        assert grant["ok"]
        assert get_companion_capacity(uid, conn=conn) == 2

        second = attempt_tame(uid, int(e2["id"]), conn=conn, rng=_Ok())
        assert second["ok"] and second["success"]
        assert has_companion(uid, "ancient_leviathan", conn=conn)

        # Reward = base + capacity bonus + variant bonus (strike default +2)
        assert mission_reward_tokens("void_titan", 1, variant_key="patrol") == 4
        assert mission_reward_tokens("void_titan", 1, variant_key="strike") == 6
        assert mission_reward_tokens("void_titan", 4, variant_key="strike") == 9
        assert mission_reward_tokens("void_titan", 1, variant_key="void_run") == 9
        offers = list_mission_offers("void_titan", 1)
        assert [o["reward_tokens"] for o in offers] == [4, 6, 9]

        # Cap max
        while get_companion_capacity(uid, conn=conn) < MAX_COMPANION_CAPACITY:
            ok = grant_companion_slot(uid, conn=conn, source="test")
            assert ok["ok"]
        full = grant_companion_slot(uid, conn=conn, source="test")
        assert full["ok"] is False
        assert full["error"] == "already_owned"
        commit(conn)
    finally:
        conn.close()
def test_admin_gets_max_titan_slots_without_purchase(wb_db):
    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        assert get_companion_capacity(uid, conn=conn) == BASE_COMPANION_CAPACITY
        conn.execute('UPDATE users SET is_admin = 1 WHERE id = ?;', (uid,))
        conn.execute('UPDATE players SET is_admin = 1 WHERE id = ?;', (uid,))
        assert get_companion_capacity(uid, conn=conn) == MAX_COMPANION_CAPACITY
        assert get_bonus_slots(uid, conn=conn) == 0
        commit(conn)
    finally:
        conn.close()
