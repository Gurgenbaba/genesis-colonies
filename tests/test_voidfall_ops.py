"""VOIDFALL 2026 Ops — real ledger, UTC windows, missions, grant idempotency."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from game.db import db
from game.inventory import inventory_amount
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.server_events import create_event
from game.voidfall import END_AT, MISSION_CATALOG, SLUG, START_AT, claim, get_state, schema_ready

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def voidfall_db(tmp_path, monkeypatch):
    monkeypatch.setenv("GC_DB_PATH", str(tmp_path / "voidfall.db"))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "voidfall-test-secret-key-at-least-32bytes")
    import game.db as gdb
    gdb._DB_PATH = None
    init_db()
    import migrate
    migrate.main()
    yield
    gdb._DB_PATH = None


def _player():
    ok, error, row = create_user(f"vf_{uuid.uuid4().hex[:10]}", "pass-voidfall-123")
    assert ok, error
    user_id = int(row["id"])
    ensure_player_and_homeworld(user_id, player_name="RiftTester")
    return user_id


def _enable_event(conn):
    event, reason = create_event(
        slug=SLUG, title="VOIDFALL: Rift Opening",
        starts_at=START_AT, ends_at=END_AT,
        effects=[{"kind": "expedition_hold_mult", "mult": 0.85},
                 {"kind": "research_time_speed", "mult": 1.10}],
        conn=conn,
    )
    assert event is not None, reason


def _activity(conn, user_id, source, *, ts, n=1):
    world = conn.execute("SELECT id FROM planets WHERE player_id = ? LIMIT 1;", (user_id,)).fetchone()
    assert world is not None
    for _ in range(n):
        idem = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO activity_xp_log
                (player_id, planet_id, source_key, amount, metadata_json,
                 idempotency_key, day_bucket, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (user_id, int(world["id"]), source, 3, "{}", idem, int(ts // 86400), ts),
        )


def test_event_requires_existing_server_event_and_schema(voidfall_db):
    user_id = _player()
    conn = db()
    assert schema_ready(conn)
    state = get_state(user_id, conn=conn, now=START_AT + 100)
    assert state["visible"] is False
    ok, reason, _ = claim(user_id, "welcome", conn=conn, now=START_AT + 100)
    assert not ok and reason == "event_inactive"
    conn.close()


def test_all_daily_missions_finish_with_one_planet(voidfall_db):
    user_id = _player()
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    _activity(conn, user_id, "expedition", ts=ts, n=2)
    _activity(conn, user_id, "building_finish", ts=ts)
    state = get_state(user_id, conn=conn, now=ts, locale="de")
    assert state["active"] is True
    assert {m["key"]: (m["progress"], m["target"]) for m in state["missions"]} == {
        "expeditions": (2, 2), "construction": (1, 1), "operations": (3, 3)
    }
    assert all(m["claimable"] for m in state["missions"])
    assert state["welcome"]["claimable"]
    assert len(MISSION_CATALOG) == 3
    for m in state["missions"]:
        ok, reason, payload = claim(user_id, m["key"], conn=conn, now=ts)
        assert ok, reason
        assert payload["claim_key"].startswith("voidfall2026:2026-10-31:")
    conn.commit()
    assert inventory_amount(user_id, "container_event_special", conn=conn) == 1
    assert inventory_amount(user_id, "booster_build_15m", conn=conn) == 1
    assert inventory_amount(user_id, "booster_expedition_loot_25_24h", conn=conn) == 1
    assert all(m["claimed"] for m in get_state(user_id, conn=conn, now=ts)["missions"])
    conn.close()


def test_welcome_once_per_player_and_daily_claim_resets_at_utc_midnight(voidfall_db):
    first, second = _player(), _player()
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    for user_id in (first, second):
        ok, reason, _ = claim(user_id, "welcome", conn=conn, now=ts)
        assert ok, reason
        assert inventory_amount(user_id, "container_rare", conn=conn) == 1
    ok, reason, _ = claim(first, "welcome", conn=conn, now=ts + 86400)
    assert not ok and reason == "already_claimed"
    assert inventory_amount(first, "container_rare", conn=conn) == 1

    _activity(conn, first, "expedition", ts=ts, n=2)
    assert claim(first, "expeditions", conn=conn, now=ts)[0]
    ok, reason, _ = claim(first, "expeditions", conn=conn, now=ts)
    assert not ok and reason == "already_claimed"
    next_day = get_state(first, conn=conn, now=ts + 86400)
    assert next_day["welcome"]["claimed"]
    assert next_day["missions"][0]["progress"] == 0
    assert next_day["missions"][0]["claimed"] is False
    _activity(conn, first, "expedition", ts=ts + 86400, n=2)
    assert claim(first, "expeditions", conn=conn, now=ts + 86400)[0]
    assert inventory_amount(first, "booster_expedition_loot_25_24h", conn=conn) == 2
    assert inventory_amount(second, "booster_expedition_loot_25_24h", conn=conn) == 0
    conn.commit()
    conn.close()


def test_paused_event_and_expiry_block_rewards(voidfall_db):
    user_id = _player()
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    conn.execute("UPDATE server_events SET enabled = 0 WHERE slug = ?;", (SLUG,))
    assert claim(user_id, "welcome", conn=conn, now=ts)[:2] == (False, "event_inactive")
    conn.execute("UPDATE server_events SET enabled = 1 WHERE slug = ?;", (SLUG,))
    assert claim(user_id, "welcome", conn=conn, now=END_AT + 1)[:2] == (False, "event_ended")
    assert claim(user_id, "admin_free_mythic", conn=conn, now=ts)[:2] == (False, "unknown_claim")
    assert inventory_amount(user_id, "container_rare", conn=conn) == 0
    conn.close()


def test_rollback_prevents_partial_grants(voidfall_db, monkeypatch):
    user_id = _player()
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    import game.voidfall as vf

    monkeypatch.setattr(vf, "grant_inventory_item", lambda *args, **kwargs: False)
    ok, reason, _ = claim(user_id, "welcome", conn=conn, now=ts)
    assert not ok and reason == "grant_failed"
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM voidfall_reward_claims WHERE user_id = ?;",
        (user_id,),
    ).fetchone()
    assert int(row["n"]) == 0
    conn.close()


def test_voidfall_ui_and_security_contract():
    template = (ROOT / "templates/partials/voidfall_daily_ops.html").read_text(encoding="utf-8")
    page = (ROOT / "templates/login_rewards.html").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    script = (ROOT / "static/js/voidfall_claim.js").read_text(encoding="utf-8")
    assert 'csrf_input()' in template
    assert 'data-voidfall-form' in template and 'mission.progress' in template
    assert 'partials/voidfall_daily_ops.html' in page
    assert 'validate_csrf_request' in app and 'lock_player_for_update(conn, user_id)' in app
    assert 'X-CSRF-Token' in script and 'credentials: "same-origin"' in script


def test_voidfall_http_page_and_csrf_claim(voidfall_db, monkeypatch):
    """Actual Flask/Jinja render, CSRF rejection and exactly-once API grant."""
    import importlib
    import game.voidfall as vf
    import app as app_mod

    importlib.reload(app_mod)
    monkeypatch.setattr(app_mod.app, "testing", False)
    uid = _player()
    conn = db()
    _enable_event(conn)
    conn.commit()
    conn.close()
    fixed = float(START_AT + 3600)
    real_state = vf.get_state
    real_claim = vf.claim
    monkeypatch.setattr(
        vf, "get_state",
        lambda player_id, *, conn, now=None, locale=None:
            real_state(player_id, conn=conn, now=fixed, locale=locale),
    )
    monkeypatch.setattr(
        vf, "claim",
        lambda player_id, key, *, conn, now=None:
            real_claim(player_id, key, conn=conn, now=fixed),
    )
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_csrf_token"] = "voidfall-test-csrf-token"

    page = client.get("/login-rewards")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="voidfall-ops"' in html
    assert html.count('data-voidfall-form') >= 4

    bad = client.post("/voidfall/claim", json={"claim_key": "welcome"})
    assert bad.status_code == 403
    assert bad.get_json()["reason"] == "invalid_csrf"

    headers = {"X-CSRF-Token": "voidfall-test-csrf-token"}
    good = client.post("/voidfall/claim", json={"claim_key": "welcome"}, headers=headers)
    assert good.status_code == 200
    assert good.get_json()["ok"] is True

    duplicate = client.post("/voidfall/claim", json={"claim_key": "welcome"}, headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.get_json()["reason"] == "already_claimed"

    conn = db()
    assert inventory_amount(uid, "container_rare", conn=conn) == 1
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM voidfall_reward_claims WHERE user_id = ?;", (uid,),
    ).fetchone()
    assert int(row["n"]) == 1
    conn.close()
