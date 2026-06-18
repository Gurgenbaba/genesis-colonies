"""GC-703 — Referral system tests."""

from __future__ import annotations

import importlib
import os
import time
import uuid

import pytest

from game.db import db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.referrals import (
    REFERRAL_MIN_ACCOUNT_AGE_SEC,
    apply_referral_code,
    claim_referral_reward,
    count_claimable_referral_rewards,
    count_successful_referrals,
    ensure_referral_code,
    get_referral_state,
    referrals_schema_ready,
    refresh_referral_qualifications,
    set_user_registration_meta,
)


@pytest.fixture
def referrals_db(tmp_path, monkeypatch):
    db_path = tmp_path / "referrals_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")

    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None, *, ip: str = "10.0.0.1"):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"ref_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Referrer", conn=conn)
    set_user_registration_meta(uid, registration_ip=ip, conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _set_homeworld_level(uid: int, level: int, conn) -> None:
    conn.execute(
        "UPDATE planets SET planet_level = ? WHERE player_id = ? AND is_homeworld = 1;",
        (int(level), int(uid)),
    )


def _backdate_registration(uid: int, conn, *, hours: int = 25) -> None:
    ts = int(time.time()) - int(hours) * 3600
    conn.execute("UPDATE users SET registered_at = ? WHERE id = ?;", (ts, int(uid)))


def test_schema_ready(referrals_db):
    conn = db()
    try:
        assert referrals_schema_ready(conn)
    finally:
        conn.close()


def test_unique_referral_code_per_player(referrals_db):
    uid = _player()
    conn = db()
    try:
        code_a = ensure_referral_code(uid, conn=conn)
        code_b = ensure_referral_code(uid, conn=conn)
        assert code_a == code_b
        assert len(code_a) == 8
        conn.commit()
    finally:
        conn.close()


def test_apply_rejects_self_referral(referrals_db):
    referrer = _player(ip="10.0.0.10")
    conn = db()
    try:
        code = ensure_referral_code(referrer, conn=conn)
        ok, reason = apply_referral_code(referrer, code, "10.0.0.20", conn=conn)
        assert not ok
        assert reason == "referral_self_not_allowed"
    finally:
        conn.close()


def test_apply_and_referred_starter_claim(referrals_db):
    referrer = _player(ip="10.0.0.10")
    referred = _player(ip="10.0.0.20")
    conn = db()
    try:
        code = ensure_referral_code(referrer, conn=conn)
        ok, reason = apply_referral_code(referred, code, "10.0.0.20", conn=conn)
        assert ok, reason
        conn.commit()
    finally:
        conn.close()

    conn = db()
    try:
        state = get_referral_state(referred, conn=conn)
        assert state["has_referrer"] is True
        assert state["referred_reward"]["claimable"] is True
        ok, reason, result = claim_referral_reward(
            referred, "referred", "referred_starter", conn=conn
        )
        assert ok, reason
        assert result and result["box_key"] == "generic_supply_container"
        conn.commit()
        state2 = get_referral_state(referred, conn=conn)
        assert state2["referred_reward"]["claimed"] is True
    finally:
        conn.close()


def test_same_ip_does_not_count_for_referrer_tier(referrals_db):
    referrer = _player(ip="10.0.0.99")
    referred = _player(ip="10.0.0.99")
    conn = db()
    try:
        code = ensure_referral_code(referrer, conn=conn)
        apply_referral_code(referred, code, "10.0.0.99", conn=conn)
        _backdate_registration(referred, conn, hours=30)
        _set_homeworld_level(referred, 3, conn)
        refresh_referral_qualifications(conn=conn)
        row = conn.execute(
            "SELECT status, same_ip_flag FROM player_referrals WHERE referred_player_id = ?;",
            (referred,),
        ).fetchone()
        assert int(row["same_ip_flag"]) == 1
        assert str(row["status"]) == "qualified"
        assert count_successful_referrals(referrer, conn=conn) == 0
        conn.commit()
    finally:
        conn.close()


def test_qualified_referral_unlocks_referrer_tier(referrals_db):
    referrer = _player(ip="10.0.1.1")
    referred = _player(ip="10.0.1.2")
    conn = db()
    try:
        code = ensure_referral_code(referrer, conn=conn)
        apply_referral_code(referred, code, "10.0.1.2", conn=conn)
        _backdate_registration(referred, conn, hours=30)
        _set_homeworld_level(referred, 3, conn)
        refresh_referral_qualifications(conn=conn)
        assert count_successful_referrals(referrer, conn=conn) == 1
        state = get_referral_state(referrer, conn=conn)
        tier1 = next(t for t in state["referrer_tiers"] if t["reward_key"] == "tier_1")
        assert tier1["claimable"] is True
        ok, reason, _ = claim_referral_reward(referrer, "referrer", "tier_1", conn=conn)
        assert ok, reason
        conn.commit()
    finally:
        conn.close()


def test_pending_referral_not_counted_before_milestones(referrals_db):
    referrer = _player(ip="10.0.2.1")
    referred = _player(ip="10.0.2.2")
    conn = db()
    try:
        code = ensure_referral_code(referrer, conn=conn)
        apply_referral_code(referred, code, "10.0.2.2", conn=conn)
        refresh_referral_qualifications(conn=conn)
        assert count_successful_referrals(referrer, conn=conn) == 0
        state = get_referral_state(referrer, conn=conn)
        tier1 = next(t for t in state["referrer_tiers"] if t["reward_key"] == "tier_1")
        assert tier1["claimable"] is False
        conn.commit()
    finally:
        conn.close()


def test_nav_badge_claimable_count(referrals_db):
    referrer = _player(ip="10.0.3.1")
    referred = _player(ip="10.0.3.2")
    conn = db()
    try:
        code = ensure_referral_code(referrer, conn=conn)
        apply_referral_code(referred, code, "10.0.3.2", conn=conn)
        _backdate_registration(referred, conn, hours=30)
        _set_homeworld_level(referred, 3, conn)
        refresh_referral_qualifications(conn=conn)
        assert count_claimable_referral_rewards(referrer, conn=conn) >= 1
        conn.commit()
    finally:
        conn.close()


def test_api_referrals_state(referrals_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    uid = _player()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get("/api/referrals/state")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["referrals"]["ready"] is True
    assert data["referrals"]["code"]


def test_api_game_state_includes_referrals_nav_badge(referrals_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    uid = _player()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get("/api/game-state")
    assert r.status_code == 200
    state = r.get_json()
    assert "referrals" in state["nav_badges"]
    assert isinstance(state["nav_badges"]["referrals"]["active"], bool)
