"""GC-550 — Lootbox auction house tests."""

from __future__ import annotations

import importlib
import os
import time
import uuid

import pytest

from game import db as gdb
from game.auction_house import (
    ACTIVE_AUCTION_TARGET,
    ROTATION_INTERVAL_SECONDS,
    UPCOMING_AUCTION_TARGET,
    auction_schema_ready,
    build_auction_house_state,
    finish_due_auctions,
    generate_auction_rotation,
    get_active_auctions,
    get_rotation_meta,
    get_upcoming_auctions,
    is_auction_allowed_box,
    is_event_box,
    place_bid,
)
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db


@pytest.fixture
def auction_db(tmp_path, monkeypatch):
    db_path = tmp_path / "auction_house_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"ah_user_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Bidder", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _second_player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"ah_user2_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Rival", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _insert_listing(
    conn,
    *,
    box_key: str = "generic_supply_container",
    currency: str = "metal",
    start_price: int = 10_000,
    ends_at: int | None = None,
) -> int:
    now = int(time.time())
    end = ends_at if ends_at is not None else now + 3600
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO auction_house_listings (
            box_key, currency, start_price, current_bid, starts_at, ends_at, status, created_at
        ) VALUES (?, ?, ?, 0, ?, ?, 'active', ?);
        """,
        (box_key, currency, start_price, now, end, now),
    )
    return int(cur.lastrowid)


def test_auction_schema_ready(auction_db):
    conn = db()
    assert auction_schema_ready(conn) is True
    conn.close()


def test_event_box_never_allowed_in_rotation(auction_db):
    assert is_event_box("event_container") is True
    assert is_event_box("container_event_special") is True
    assert is_event_box("event_summer_box") is True
    assert is_auction_allowed_box("event_container") is False
    assert is_auction_allowed_box("container_event_special") is False
    assert is_auction_allowed_box("generic_supply_container") is True

    conn = db()
    for _ in range(40):
        generate_auction_rotation(conn=conn, seed=1000 + _)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT box_key FROM auction_house_listings;")
    keys = {str(r["box_key"]) for r in cur.fetchall()}
    assert "event_container" not in keys
    assert "container_event_special" not in keys
    assert all(not is_event_box(k) for k in keys)
    conn.close()


def test_get_active_auctions_seeds_rotation(auction_db):
    conn = db()
    uid = _player(conn=conn)
    auctions = get_active_auctions(uid, conn=conn)
    assert len(auctions) == ACTIVE_AUCTION_TARGET
    assert all(a["seconds_remaining"] > 0 for a in auctions)
    conn.close()


def test_upcoming_auctions_seeded(auction_db):
    conn = db()
    uid = _player(conn=conn)
    get_active_auctions(uid, conn=conn)
    upcoming = get_upcoming_auctions(conn=conn)
    assert len(upcoming) == UPCOMING_AUCTION_TARGET
    assert all(u["seconds_until_available"] >= 0 for u in upcoming)
    assert all(not is_event_box(u["box_key"]) for u in upcoming)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    state = build_auction_house_state(uid, pid, conn=conn)
    assert len(state["upcoming"]) == UPCOMING_AUCTION_TARGET
    assert state["next_rotation_at"] > 0
    assert state["rotation_interval_seconds"] == ROTATION_INTERVAL_SECONDS
    conn.close()


def test_upcoming_times_tied_to_rotation_anchor(auction_db):
    conn = db()
    uid = _player(conn=conn)
    get_active_auctions(uid, conn=conn)
    meta = get_rotation_meta(conn)
    upcoming = get_upcoming_auctions(conn=conn)
    anchor = int(meta["next_rotation_at"])
    interval = int(meta["rotation_interval_seconds"])
    assert upcoming[0]["available_at"] == anchor
    assert upcoming[1]["available_at"] == anchor + interval
    assert upcoming[2]["available_at"] == anchor + interval * 2
    assert all(not is_event_box(u["box_key"]) for u in upcoming)
    conn.close()


def test_next_rotation_at_stable_within_same_window(auction_db):
    conn = db()
    uid = _player(conn=conn)
    get_active_auctions(uid, conn=conn)
    meta1 = get_rotation_meta(conn)
    upcoming1 = get_upcoming_auctions(conn=conn)
    meta2 = get_rotation_meta(conn)
    upcoming2 = get_upcoming_auctions(conn=conn)
    assert meta1["next_rotation_at"] == meta2["next_rotation_at"]
    assert [u["box_key"] for u in upcoming1] == [u["box_key"] for u in upcoming2]
    conn.close()


def test_active_auctions_exclude_event_boxes(auction_db):
    conn = db()
    uid = _player(conn=conn)
    auctions = get_active_auctions(uid, conn=conn)
    assert all(not is_event_box(a["box_key"]) for a in auctions)
    conn.close()


def test_place_valid_bid_deducts_resources(auction_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 200000 WHERE id = ?;", (pid,))
    listing_id = _insert_listing(conn, currency="metal", start_price=50_000)
    conn.commit()

    ok, reason, _ = place_bid(
        player_id=uid,
        planet_id=pid,
        listing_id=listing_id,
        amount=50_000,
        currency="metal",
        conn=conn,
    )
    assert ok, reason
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,))
    assert int(cur.fetchone()["metal"]) == 150_000
    cur.execute("SELECT current_bid, current_bidder_id FROM auction_house_listings WHERE id = ?;", (listing_id,))
    row = cur.fetchone()
    assert int(row["current_bid"]) == 50_000
    assert int(row["current_bidder_id"]) == uid
    conn.close()


def test_bid_too_low_rejected(auction_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 200000 WHERE id = ?;", (pid,))
    listing_id = _insert_listing(conn, currency="metal", start_price=50_000)
    conn.commit()

    ok, reason, extra = place_bid(
        player_id=uid,
        planet_id=pid,
        listing_id=listing_id,
        amount=10_000,
        currency="metal",
        conn=conn,
    )
    assert not ok
    assert reason == "bid_too_low"
    assert extra and extra.get("min_bid") == 50_000
    conn.close()


def test_outbid_player_gets_refund(auction_db):
    uid1 = _player()
    uid2 = _second_player()
    conn = db()
    pid1 = int(get_planets_by_player(uid1, conn=conn)[0]["id"])
    pid2 = int(get_planets_by_player(uid2, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 500000 WHERE id IN (?, ?);", (pid1, pid2))
    listing_id = _insert_listing(conn, currency="metal", start_price=50_000)
    conn.commit()

    ok1, _, _ = place_bid(
        player_id=uid1, planet_id=pid1, listing_id=listing_id, amount=50_000, currency="metal", conn=conn
    )
    assert ok1
    ok2, _, _ = place_bid(
        player_id=uid2, planet_id=pid2, listing_id=listing_id, amount=52_500, currency="metal", conn=conn
    )
    assert ok2

    cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid1,))
    assert int(cur.fetchone()["metal"]) == 500_000
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid2,))
    assert int(cur.fetchone()["metal"]) == 447_500
    cur.execute(
        "SELECT refunded FROM auction_house_bids WHERE listing_id = ? AND player_id = ? ORDER BY id DESC LIMIT 1;",
        (listing_id, uid1),
    )
    assert int(cur.fetchone()["refunded"]) == 1
    conn.close()


def test_auction_finish_grants_lootbox(auction_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    now = int(time.time())
    listing_id = _insert_listing(
        conn,
        box_key="resource_cache",
        currency="metal",
        start_price=50_000,
        ends_at=now - 10,
    )
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE auction_house_listings
        SET current_bid = 120000, current_bidder_id = ?, current_bid_planet_id = ?
        WHERE id = ?;
        """,
        (uid, pid, listing_id),
    )
    conn.commit()

    finished = finish_due_auctions(conn=conn, now=now)
    assert finished == 1
    cur.execute("SELECT status FROM auction_house_listings WHERE id = ?;", (listing_id,))
    assert str(cur.fetchone()["status"]) == "completed"
    cur.execute("SELECT COUNT(*) AS c FROM lootbox_inventory WHERE player_id = ? AND box_key = ?;", (uid, "resource_cache"))
    assert int(cur.fetchone()["c"]) == 1
    cur.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "container_rare"),
    )
    row = cur.fetchone()
    assert row and int(row["amount"]) >= 1
    conn.close()


def test_idempotent_bid_api(auction_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    conn.execute("UPDATE planets SET metal = 300000 WHERE id = ?;", (pid,))
    listing_id = _insert_listing(conn, currency="metal", start_price=50_000)
    conn.commit()
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    rid = str(uuid.uuid4())
    body = {"listing_id": listing_id, "amount": 50_000, "currency": "metal", "request_id": rid}

    r1 = client.post("/api/auction-house/bid", json=body)
    r2 = client.post("/api/auction-house/bid", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.get_json() == r2.get_json()

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM auction_house_bids WHERE listing_id = ?;", (listing_id,))
    assert int(cur.fetchone()["c"]) == 1
    conn.close()


def test_auction_house_page_reachable(auction_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    res = client.get("/auction-house")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "auction-house-page" in body
    assert "auction-house-card" in body or "auction-house-table" in body or "auction-house-empty" in body
    assert "auction-upcoming-panel" in body or "auction-house-upcoming" in body or "auction-house-empty" in body
    assert "auction-stats-bar" in body or "auction-house-empty" in body


def test_context_planet_resources_used_for_bid(auction_db):
    conn = db()
    uid = _player(conn=conn)
    planets = get_planets_by_player(uid, conn=conn)
    pid = int(planets[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 0 WHERE player_id = ?;", (uid,))
    cur.execute("UPDATE planets SET metal = 250000 WHERE id = ?;", (pid,))
    listing_id = _insert_listing(conn, currency="metal", start_price=50_000)
    conn.commit()

    ok, reason, _ = place_bid(
        player_id=uid,
        planet_id=pid,
        listing_id=listing_id,
        amount=50_000,
        currency="metal",
        conn=conn,
    )
    assert ok, reason
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,))
    assert int(cur.fetchone()["metal"]) == 200_000
    conn.close()
