"""GC-CB — Case Battles / Relikt-Arena."""

from __future__ import annotations

import importlib
import os
import time
import uuid
from collections import Counter

import pytest

from game import db as gdb
from game.case_battles import (
    AUTO_SETTLE_AFTER_SEC,
    CONTAINER_BATTLE_VALUE,
    battle_value_for_container,
    build_case_battles_state,
    cancel_battle,
    case_battles_schema_ready,
    create_battle,
    get_battle_payload,
    join_battle,
    maybe_auto_settle,
    reward_value_for_item,
    settle_battle,
    total_battle_value,
    verify_battle_roll,
)
from game.db import begin_write_transaction, commit, db, rollback
from game.inventory import grant_inventory_item, inventory_amount, open_containers, run_inventory_mutation
from game.models import create_user, ensure_player_and_homeworld, init_db


@pytest.fixture
def cb_db(tmp_path, monkeypatch):
    db_path = tmp_path / "case_battles.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(name: str = "CBTester") -> int:
    ok, err, user = create_user(f"cb_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return uid


def _grant_cases(user_id: int, cases) -> None:
    def _mut(conn):
        for key, n in Counter(cases).items():
            assert grant_inventory_item(user_id, key, int(n), conn=conn)
        return True, "ok", None

    ok, reason, _ = run_inventory_mutation(_mut)
    assert ok, reason


def test_schema_and_battle_values(cb_db):
    conn = db()
    try:
        assert case_battles_schema_ready(conn)
        assert battle_value_for_container("container_basic") == 100
        assert battle_value_for_container("container_void_artifact") == 8000
        assert (
            total_battle_value(
                ["container_basic", "container_basic", "container_military_cache", "container_relic"]
            )
            == 2700
        )
        assert reward_value_for_item("fragment_dna_common", 2) == reward_value_for_item(
            "fragment_dna_common", 1
        ) * 2
        assert CONTAINER_BATTLE_VALUE
    finally:
        conn.close()


def test_create_escrows_containers(cb_db):
    uid = _player("Creator")
    cases = ["container_basic", "container_rare"]
    _grant_cases(uid, cases + ["container_basic"])

    ok, reason, battle = run_inventory_mutation(
        lambda c: create_battle(uid, cases=cases, mode="standard", visibility="public", conn=c)
    )
    assert ok, reason
    assert battle["status"] == "open"
    assert battle["total_battle_value"] == 350

    conn = db()
    try:
        assert inventory_amount(uid, "container_basic", conn=conn) == 1
        assert inventory_amount(uid, "container_rare", conn=conn) == 0
    finally:
        conn.close()


def test_cancel_refunds_escrow(cb_db):
    uid = _player()
    cases = ["container_basic", "container_basic"]
    _grant_cases(uid, cases)
    ok, reason, battle = run_inventory_mutation(
        lambda c: create_battle(uid, cases=cases, mode="crazy", visibility="public", conn=c)
    )
    assert ok, reason
    bid = int(battle["id"])
    ok, reason, battle = run_inventory_mutation(lambda c: cancel_battle(uid, bid, conn=c))
    assert ok, reason
    assert battle["status"] == "cancelled"
    conn = db()
    try:
        assert inventory_amount(uid, "container_basic", conn=conn) == 2
    finally:
        conn.close()


def test_join_starts_and_settle_standard(cb_db):
    a = _player("Alpha")
    b = _player("Bravo")
    cases = ["container_basic"]
    _grant_cases(a, cases)
    _grant_cases(b, cases)

    ok, reason, battle = run_inventory_mutation(
        lambda c: create_battle(a, cases=cases, mode="standard", visibility="public", conn=c)
    )
    assert ok, reason
    bid = int(battle["id"])

    ok, reason, battle = run_inventory_mutation(lambda c: join_battle(b, bid, conn=c))
    assert ok, reason
    assert battle["status"] == "running"
    assert battle["server_seed"] is None
    assert battle["server_seed_hash"]
    assert len(battle["rolls"]) == 2

    conn = db()
    try:
        assert inventory_amount(a, "container_basic", conn=conn) == 0
        assert inventory_amount(b, "container_basic", conn=conn) == 0
    finally:
        conn.close()

    ok, reason, finished = run_inventory_mutation(lambda c: settle_battle(bid, conn=c))
    assert ok, reason
    assert finished["status"] == "finished"
    assert finished["server_seed"]
    assert finished["winner_id"] in (a, b)

    winner = int(finished["winner_id"])
    granted = finished.get("granted") or []
    assert granted
    winner_grants = [g for g in granted if int(g.get("user_id") or winner) == winner]
    assert winner_grants
    conn = db()
    try:
        for g in winner_grants:
            assert inventory_amount(winner, g["reward_key"], conn=conn) >= int(g["amount"])
    finally:
        conn.close()

    ok2, reason2, again = run_inventory_mutation(lambda c: settle_battle(bid, conn=c))
    assert ok2 and reason2 == "case_battle_already_settled"
    assert again["winner_id"] == winner


def test_crazy_mode_lowest_wins(cb_db):
    a = _player("High")
    b = _player("Low")
    cases = ["container_basic", "container_rare"]
    _grant_cases(a, cases)
    _grant_cases(b, cases)
    ok, _, battle = run_inventory_mutation(
        lambda c: create_battle(a, cases=cases, mode="crazy", visibility="public", conn=c)
    )
    assert ok
    bid = int(battle["id"])
    ok, _, battle = run_inventory_mutation(lambda c: join_battle(b, bid, conn=c))
    assert ok and battle["status"] == "running"
    ok, _, finished = run_inventory_mutation(lambda c: settle_battle(bid, conn=c))
    assert ok
    totals = {int(p["user_id"]): int(p["total_reward_value"]) for p in finished["players"]}
    winner = int(finished["winner_id"])
    loser = a if winner == b else b
    assert totals[winner] <= totals[loser]


def test_private_join_code(cb_db):
    a = _player("Host")
    b = _player("Guest")
    cases = ["container_basic"]
    _grant_cases(a, cases)
    _grant_cases(b, cases)
    ok, _, battle = run_inventory_mutation(
        lambda c: create_battle(a, cases=cases, mode="standard", visibility="private", conn=c)
    )
    assert ok
    assert battle.get("join_code")
    bid = int(battle["id"])
    code = battle["join_code"]
    ok, reason, _ = run_inventory_mutation(
        lambda c: join_battle(b, bid, join_code="WRONG1", conn=c)
    )
    assert not ok and reason == "invalid_join_code"
    ok, reason, battle = run_inventory_mutation(
        lambda c: join_battle(b, bid, join_code=code, conn=c)
    )
    assert ok, reason
    assert battle["status"] == "running"


def test_insufficient_containers_rejected(cb_db):
    uid = _player()
    ok, reason, _ = run_inventory_mutation(
        lambda c: create_battle(uid, cases=["container_epic"], mode="standard", visibility="public", conn=c)
    )
    assert not ok and reason == "insufficient_containers"


def test_escrow_blocks_normal_open(cb_db):
    uid = _player()
    cases = ["container_rare"]
    _grant_cases(uid, cases)
    ok, _, battle = run_inventory_mutation(
        lambda c: create_battle(uid, cases=cases, mode="standard", visibility="public", conn=c)
    )
    assert ok

    conn = db()
    try:
        assert inventory_amount(uid, "container_rare", conn=conn) == 0
        from game.planet_evolution.repository import get_context_planet

        planet = get_context_planet(uid, conn=conn)
        ok2, reason2, _ = open_containers(uid, int(planet["id"]), "container_rare", 1, conn=conn)
        assert not ok2
        assert reason2
    finally:
        conn.close()

    run_inventory_mutation(lambda c: cancel_battle(uid, int(battle["id"]), conn=c))


def test_verify_roll_after_finish(cb_db):
    a = _player("V1")
    b = _player("V2")
    cases = ["container_basic"]
    _grant_cases(a, cases)
    _grant_cases(b, cases)
    ok, _, battle = run_inventory_mutation(
        lambda c: create_battle(a, cases=cases, mode="standard", visibility="public", conn=c)
    )
    bid = int(battle["id"])
    run_inventory_mutation(lambda c: join_battle(b, bid, conn=c))
    run_inventory_mutation(lambda c: settle_battle(bid, conn=c))
    conn = db()
    try:
        ok, reason, result = verify_battle_roll(bid, round_index=0, user_id=a, conn=conn)
        assert ok, reason
        assert result["matches"] is True
    finally:
        conn.close()


def test_auto_settle_after_grace(cb_db):
    a = _player("A1")
    b = _player("A2")
    cases = ["container_basic"]
    _grant_cases(a, cases)
    _grant_cases(b, cases)
    ok, _, battle = run_inventory_mutation(
        lambda c: create_battle(a, cases=cases, mode="standard", visibility="public", conn=c)
    )
    bid = int(battle["id"])
    run_inventory_mutation(lambda c: join_battle(b, bid, conn=c))

    def _backdate_and_settle(conn):
        conn.execute(
            "UPDATE case_battles SET started_at = ? WHERE id = ?;",
            (time.time() - AUTO_SETTLE_AFTER_SEC - 5, bid),
        )
        maybe_auto_settle(bid, conn=conn)
        return True, "ok", get_battle_payload(bid, conn=conn)

    ok, _, finished = run_inventory_mutation(_backdate_and_settle)
    assert ok
    assert finished["status"] == "finished"
    assert finished["winner_id"]


def test_api_create_join_settle(cb_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    a = _player("ApiA")
    b = _player("ApiB")
    _grant_cases(a, ["container_basic"])
    _grant_cases(b, ["container_basic"])

    client_a = app_module.app.test_client()
    client_b = app_module.app.test_client()
    with client_a.session_transaction() as sess:
        sess["user_id"] = a
    with client_b.session_transaction() as sess:
        sess["user_id"] = b

    r = client_a.post(
        "/api/case-battles/create",
        json={"cases": ["container_basic"], "mode": "standard", "visibility": "public"},
    )
    data = r.get_json()
    assert data["ok"] is True, data
    bid = int(data["battle"]["id"])

    r = client_b.post("/api/case-battles/join", json={"battle_id": bid})
    data = r.get_json()
    assert data["ok"] is True, data
    assert data["battle"]["status"] == "running"

    r = client_a.post("/api/case-battles/settle", json={"battle_id": bid})
    data = r.get_json()
    assert data["ok"] is True, data
    assert data["battle"]["status"] == "finished"
    assert data["battle"]["server_seed"]

    r = client_a.get("/inventory")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "inventory-tab-case-battles" in html
    assert "case-battles-page-state" in html


def test_create_with_player_limit_3(cb_db):
    a = _player("Host3")
    cases = ["container_basic"]
    _grant_cases(a, cases)
    ok, reason, battle = run_inventory_mutation(
        lambda c: create_battle(
            a, cases=cases, mode="crazy", visibility="public", player_limit=3, conn=c
        )
    )
    assert ok, reason
    assert battle["player_limit"] == 3
    assert battle["status"] == "open"


def test_team_requires_four(cb_db):
    a = _player("TeamHost")
    cases = ["container_basic"]
    _grant_cases(a, cases)
    ok, reason, battle = run_inventory_mutation(
        lambda c: create_battle(
            a, cases=cases, mode="team", visibility="public", player_limit=2, conn=c
        )
    )
    assert ok, reason
    assert battle["player_limit"] == 4


def test_terminal_settlement_grants_per_round(cb_db):
    a = _player("T1")
    b = _player("T2")
    cases = ["container_basic", "container_rare"]
    _grant_cases(a, cases)
    _grant_cases(b, cases)
    ok, _, battle = run_inventory_mutation(
        lambda c: create_battle(a, cases=cases, mode="terminal", visibility="public", player_limit=2, conn=c)
    )
    assert ok
    bid = int(battle["id"])
    run_inventory_mutation(lambda c: join_battle(b, bid, conn=c))
    ok, reason, finished = run_inventory_mutation(lambda c: settle_battle(bid, conn=c))
    assert ok, reason
    assert finished["status"] == "finished"
    assert finished.get("settlement_kind") == "terminal"
    granted = finished.get("granted") or []
    assert granted
    assert all("user_id" in g for g in granted)


def test_inventory_badge_active_for_open_case_battle(cb_db):
    from game.live_state import nav_badges_for_game_state

    a = _player("BadgeHost")
    cases = ["container_basic"]
    _grant_cases(a, cases)
    ok, reason, _ = run_inventory_mutation(
        lambda c: create_battle(a, cases=cases, mode="standard", visibility="public", conn=c)
    )
    assert ok, reason
    conn = db()
    try:
        badges = nav_badges_for_game_state(a, conn=conn)
        assert badges["inventory"]["active"] is True
        assert int(badges["inventory"]["count"]) >= 1
    finally:
        conn.close()


def test_inventory_badge_clears_after_cancel(cb_db):
    from game.live_state import nav_badges_for_game_state

    a = _player("BadgeCancel")
    cases = ["container_basic"]
    _grant_cases(a, cases)
    ok, _, battle = run_inventory_mutation(
        lambda c: create_battle(a, cases=cases, mode="standard", visibility="public", conn=c)
    )
    assert ok
    bid = int(battle["id"])
    run_inventory_mutation(lambda c: cancel_battle(a, bid, conn=c))
    conn = db()
    try:
        badges = nav_badges_for_game_state(a, conn=conn)
        assert badges["inventory"]["active"] is False
        assert int(badges["inventory"]["count"]) == 0
    finally:
        conn.close()


def test_state_endpoint(cb_db, monkeypatch):
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
    r = client.get("/api/case-battles/state")
    data = r.get_json()
    assert data["ok"] is True
    assert data["case_battles"]["ready"] is True
    assert "container_battle_values" in data["case_battles"]
    assert "terminal" in data["case_battles"]["modes"]
