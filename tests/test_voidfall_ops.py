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
    assert html.count('data-voidfall-form') >= 7
    assert 'id="voidfall-community-title"' in html
    assert "gc-voidfall__discovery" in html

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

# GC-VOIDFALL-003 — community scoreboard, milestone claims and rare drops.

def test_community_signals_only_count_verified_daily_claim_receipts(voidfall_db, monkeypatch):
    import game.voidfall_community as community

    monkeypatch.setattr(community.secrets, "randbelow", lambda n: n - 1)
    user_id = _player()
    other = _player()
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    ok, _, _ = claim(user_id, "welcome", conn=conn, now=ts)
    assert ok
    state = get_state(user_id, conn=conn, now=ts)
    assert state["community"]["signals"] == 0  # welcome is not a contribution
    assert state["community"]["my_signals"] == 0
    assert all(not m["claimable"] for m in state["community"]["milestones"])

    # 2 expeditions and 1 building yield 3 daily claims; single planet.
    for d in range(7):
        day_ts = ts + d * 86400
        _activity(conn, user_id, "expedition", ts=day_ts, n=2)
        _activity(conn, user_id, "building_finish", ts=day_ts)
        for key in ("expeditions", "construction", "operations"):
            ok, reason, _ = claim(user_id, key, conn=conn, now=day_ts)
            assert ok, (d, key, reason)

    state = get_state(user_id, conn=conn, now=ts + 6 * 86400)
    assert state["community"]["signals"] == 21
    assert state["community"]["my_signals"] == 21
    assert state["community"]["milestones"][0]["claimable"]
    assert not state["community"]["milestones"][1]["unlocked"]
    assert not get_state(other, conn=conn, now=ts)["community"]["milestones"][0]["claimable"]

    ok, reason, _ = claim(other, "community_breach", conn=conn, now=ts)
    assert not ok and reason == "objective_incomplete"
    _activity(conn, other, "building_finish", ts=ts)
    assert claim(other, "construction", conn=conn, now=ts)[0]
    ok, reason, payload = claim(other, "community_breach", conn=conn, now=ts)
    assert ok, reason
    assert payload["claim_key"] == "voidfall2026:community:community_breach"
    assert inventory_amount(other, "container_rare", conn=conn) == 1
    ok, reason, _ = claim(other, "community_breach", conn=conn, now=ts)
    assert not ok and reason == "already_claimed"
    # Community reward receipt itself must NOT increase shared signals.
    assert get_state(other, conn=conn, now=ts)["community"]["signals"] == 22
    assert not claim(other, "community_free_mythic", conn=conn, now=ts)[0]
    conn.commit()
    conn.close()


def test_community_higher_tiers_unlock_without_counting_community_claims(voidfall_db, monkeypatch):
    import game.voidfall_community as community

    monkeypatch.setattr(community.secrets, "randbelow", lambda n: n - 1)
    user_id = _player()
    other_ids = [_player() for _ in range(7)]
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    _activity(conn, user_id, "building_finish", ts=ts)
    assert claim(user_id, "construction", conn=conn, now=ts)[0]

    # Model legacy Release-2 mission receipts. They have the same canonical
    # schema and unique key that production recorded before Release 3 shipped.
    # The player needs their own actual daily claim to receive any milestone.
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 10, 31, tzinfo=timezone.utc)
    n = 0
    for pid in other_ids:
        for day in range(8):
            label = (base + timedelta(days=day)).strftime("%Y-%m-%d")
            for mission_key in ("expeditions", "construction", "operations"):
                conn.execute(
                    "INSERT INTO voidfall_reward_claims (user_id, claim_key, reward_json, claimed_at)"
                    " VALUES (?, ?, ?, ?);",
                    (pid, f"voidfall2026:{label}:{mission_key}", "[]", ts),
                )
                n += 1

    state = get_state(user_id, conn=conn, now=ts)
    assert state["community"]["signals"] == n + 1
    assert n + 1 >= 150
    assert all(m["claimable"] for m in state["community"]["milestones"])
    for key, reward in (
        ("community_breach", "container_rare"),
        ("community_stabilize", "container_event_special"),
        ("community_contain", "container_relic"),
    ):
        ok, reason, _ = claim(user_id, key, conn=conn, now=ts)
        assert ok, (key, reason)
        assert inventory_amount(user_id, reward, conn=conn) == 1
        assert claim(user_id, key, conn=conn, now=ts)[:2] == (False, "already_claimed")
    assert get_state(user_id, conn=conn, now=ts)["community"]["signals"] == n + 1
    conn.commit()
    conn.close()


def test_rare_discoveries_have_two_per_account_limit_and_limited_tier(voidfall_db, monkeypatch):
    import game.voidfall_community as community

    def forced_artifact_roll(n):
        return 99 if n == 100 else 0

    monkeypatch.setattr(community.secrets, "randbelow", forced_artifact_roll)
    user_id = _player()
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    _activity(conn, user_id, "expedition", ts=ts, n=2)
    _activity(conn, user_id, "building_finish", ts=ts)
    drops = []
    for key in ("expeditions", "construction", "operations"):
        ok, reason, result = claim(user_id, key, conn=conn, now=ts)
        assert ok, reason
        drops.append(result.get("discovery"))
    assert [drop["kind"] if drop else None for drop in drops] == ["artifact", "artifact", None]
    state = get_state(user_id, conn=conn, now=ts)
    assert state["community"]["discovery_count"] == 2
    assert state["community"]["discovery_max"] == 2
    assert inventory_amount(user_id, "container_void_artifact", conn=conn) == 2
    assert not claim(user_id, "expeditions", conn=conn, now=ts)[0]
    assert inventory_amount(user_id, "container_void_artifact", conn=conn) == 2

    day_2 = ts + 86400
    _activity(conn, user_id, "expedition", ts=day_2, n=2)
    assert claim(user_id, "expeditions", conn=conn, now=day_2)[0]
    assert inventory_amount(user_id, "container_void_artifact", conn=conn) == 2
    conn.commit()
    conn.close()


def test_rare_discovery_failure_rolls_back_daily_reward(voidfall_db, monkeypatch):
    import game.voidfall_community as community
    from game.db import begin_write_transaction, rollback

    monkeypatch.setattr(community.secrets, "randbelow", lambda n: 0)
    monkeypatch.setattr(community, "grant_inventory_item", lambda *args, **kwargs: False)
    user_id = _player()
    conn = db()
    _enable_event(conn)
    conn.commit()
    ts = float(START_AT + 3600)
    _activity(conn, user_id, "expedition", ts=ts, n=2)
    conn.commit()
    begin_write_transaction(conn)
    with pytest.raises(RuntimeError, match="voidfall_discovery_grant_failed"):
        claim(user_id, "expeditions", conn=conn, now=ts)
    rollback(conn)
    assert inventory_amount(user_id, "booster_expedition_loot_25_24h", conn=conn) == 0
    assert get_state(user_id, conn=conn, now=ts)["community"]["signals"] == 0
    assert get_state(user_id, conn=conn, now=ts)["community"]["discovery_count"] == 0
    conn.close()


def test_release3_page_renders_and_expired_milestones_lock(voidfall_db):
    from game.voidfall_community import COMMUNITY_MILESTONES
    assert [threshold for _key, threshold, _rewards in COMMUNITY_MILESTONES] == [20, 40, 70]
    assert len(set(key for key, _, _ in COMMUNITY_MILESTONES)) == 3
    user_id = _player()
    conn = db()
    _enable_event(conn)
    state = get_state(user_id, conn=conn, now=END_AT + 1)
    assert not state["active"]
    assert all(not m["claimable"] for m in state["community"]["milestones"])
    assert claim(user_id, "community_breach", conn=conn, now=END_AT + 1)[:2] == (
        False, "event_ended",
    )
    conn.close()
    template = (ROOT / "templates/partials/voidfall_community.html").read_text(encoding="utf-8")
    assert 'id="voidfall-community-title"' in template
    assert "voidfall_discovery" in template and "csrf_input()" in template
    assert "milestone.progress" in template


# GC-VOIDFALL-004: account-scoped, irreversible Rift alignment.

def test_alignment_requires_40_global_and_3_personal_signals(voidfall_db, monkeypatch):
    import game.voidfall_community as community

    calls = {"rolls": 0}

    def no_discovery(n):
        calls["rolls"] += 1
        return n - 1

    monkeypatch.setattr(community.secrets, "randbelow", no_discovery)
    user_id = _player()
    outsiders = [_player() for _ in range(3)]
    newcomer = _player()
    low_user = _player()
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    _activity(conn, user_id, "expedition", ts=ts, n=2)
    _activity(conn, user_id, "building_finish", ts=ts)
    for key in ("expeditions", "construction", "operations"):
        assert claim(user_id, key, conn=conn, now=ts)[0]
    assert get_state(user_id, conn=conn, now=ts)["community"]["my_signals"] == 3
    assert claim(user_id, "alignment_science", conn=conn, now=ts)[:2] == (
        False, "objective_incomplete"
    )

    # Release-2-style historical receipts: three daily claims/account/day.
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 10, 31, tzinfo=timezone.utc)
    for other in outsiders:
        for day in range(8):
            label = (base + timedelta(days=day)).strftime("%Y-%m-%d")
            for mission in ("expeditions", "construction", "operations"):
                conn.execute(
                    "INSERT INTO voidfall_reward_claims (user_id, claim_key, reward_json, claimed_at)"
                    " VALUES (?, ?, ?, ?)",
                    (other, f"voidfall2026:{label}:{mission}", "[]", ts),
                )

    state = get_state(user_id, conn=conn, now=ts)
    assert state["community"]["signals"] == 75
    assert state["community"]["alignment"]["available"] is True
    assert len(state["community"]["alignment"]["options"]) == 3
    assert claim(newcomer, "alignment_industry", conn=conn, now=ts)[:2] == (
        False, "objective_incomplete"
    )
    _activity(conn, low_user, "building_finish", ts=ts)
    assert claim(low_user, "construction", conn=conn, now=ts)[0]
    assert claim(low_user, "alignment_industry", conn=conn, now=ts)[:2] == (
        False, "objective_incomplete"
    )
    count_before = calls["rolls"]
    ok, reason, result = claim(user_id, "alignment_science", conn=conn, now=ts)
    assert ok, reason
    assert calls["rolls"] == count_before  # no rarity reroll on alignment
    assert result["claim_key"] == community.ALIGNMENT_CLAIM_KEY
    assert inventory_amount(user_id, "booster_research_15m", conn=conn) == 2
    for other_key in ("alignment_industry", "alignment_science", "alignment_exploration"):
        assert claim(user_id, other_key, conn=conn, now=ts)[:2] == (
            False, "already_claimed"
        )
    chosen = get_state(user_id, conn=conn, now=ts)["community"]["alignment"]
    assert chosen["chosen"] is True and chosen["selected_path"] == "alignment_science"
    assert all(not option["claimable"] for option in chosen["options"])
    assert sum(option["selected"] for option in chosen["options"]) == 1
    # One more verified daily mission adds one signal; the choice itself adds none.
    assert get_state(user_id, conn=conn, now=ts)["community"]["signals"] == 76
    conn.commit()
    conn.close()


def test_alignment_failed_grant_writes_no_receipt(voidfall_db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from game.voidfall_community import ALIGNMENT_CLAIM_KEY
    import game.voidfall as vf

    user_id = _player()
    others = [_player() for _ in range(3)]
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    for pid in [user_id] + others:
        for d in range(8):
            label = (datetime(2026, 10, 31, tzinfo=timezone.utc)
                     + timedelta(days=d)).strftime("%Y-%m-%d")
            for key in ("expeditions", "construction", "operations"):
                conn.execute(
                    "INSERT INTO voidfall_reward_claims (user_id, claim_key, reward_json, claimed_at)"
                    " VALUES (?, ?, ?, ?)",
                    (pid, f"voidfall2026:{label}:{key}", "[]", ts),
                )
    monkeypatch.setattr(vf, "grant_inventory_item", lambda *args, **kwargs: False)
    assert claim(user_id, "alignment_industry", conn=conn, now=ts)[:2] == (
        False, "grant_failed"
    )
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM voidfall_reward_claims "
        "WHERE user_id = ? AND claim_key = ?", (user_id, ALIGNMENT_CLAIM_KEY)
    ).fetchone()["n"]
    assert int(count) == 0
    assert inventory_amount(user_id, "booster_build_15m", conn=conn) == 0
    conn.close()


def test_alignment_ui_and_pjax_contract():
    template = (ROOT / "templates/partials/voidfall_community.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/voidfall_claim.js").read_text(encoding="utf-8")
    assert "data-voidfall-alignment" in template
    assert "vf.community.alignment.options" in template
    assert "csrf_input()" in template
    assert "GC.navigateTo" in js
    assert "force: true" in js


# GC-VOIDFALL-005: PostgreSQL psycopg rejects unescaped '%' in SQL literals.

def test_voidfall_all_claim_pattern_reads_bind_like_wildcards(voidfall_db, monkeypatch):
    """Exercise both real SQLite read paths and reject PostgreSQL-unsafe literal LIKE patterns."""
    import re
    import game.voidfall_community as community

    user_id = _player()
    connection = db()
    _enable_event(connection)

    class PgSafeSqlGuard:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.seen_like = []

        def execute(self, sql, params=()):
            if "voidfall_reward_claims" in sql and "LIKE" in sql:
                # psycopg's percent placeholder parser sees literal '%' as a malformed
                # placeholder even within quoted SQL string literals.
                assert not re.search(r"\bLIKE\s*'[^']*%[^']*'", sql, flags=re.I)
                assert "LIKE ?" in sql
                self.seen_like.append((sql, tuple(params)))
            return self.wrapped.execute(sql, params)

    guarded = PgSafeSqlGuard(connection)
    state = community.get_community_state(user_id, conn=guarded, active=True)
    assert state["signals"] == 0
    # Avoid inventory mutations: this exercises discovery's SQL read path.
    monkeypatch.setattr(community.secrets, "randbelow", lambda n: n - 1)
    assert community.maybe_award_discovery(user_id, conn=guarded, now=START_AT + 3600) is None
    assert len(guarded.seen_like) == 2
    assert all(all("%" in str(p) for p in params[1:-1])
               for sql, params in guarded.seen_like[:1])
    assert guarded.seen_like[1][1][-1] == f"{community.DISCOVERY_PREFIX}%"
    connection.close()


# GC-VOIDFALL-006 — small-community threshold boundaries on the canonical ledger.

def test_small_community_thresholds_and_alignment_exact_boundaries(voidfall_db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import game.voidfall_community as community

    # No unrelated discovery reward obscures the result.
    monkeypatch.setattr(community.secrets, "randbelow", lambda n: n - 1)
    user = _player()
    contributors = [_player() for _ in range(3)]
    conn = db()
    _enable_event(conn)
    ts = float(START_AT + 3600)
    _activity(conn, user, "expedition", ts=ts, n=2)
    _activity(conn, user, "building_finish", ts=ts)
    for key in ("expeditions", "construction", "operations"):
        assert claim(user, key, conn=conn, now=ts)[0]
    assert get_state(user, conn=conn, now=ts)["community"]["my_signals"] == 3

    receipts = []
    base = datetime(2026, 10, 31, tzinfo=timezone.utc)
    for other in contributors:
        for d in range(8):
            label = (base + timedelta(days=d)).strftime("%Y-%m-%d")
            for key in ("expeditions", "construction", "operations"):
                receipts.append((other, f"voidfall2026:{label}:{key}"))
    assert len(receipts) >= 67

    def add_until(total):
        while get_state(user, conn=conn, now=ts)["community"]["signals"] < total:
            other, receipt_key = receipts.pop(0)
            conn.execute(
                "INSERT INTO voidfall_reward_claims (user_id, claim_key, reward_json, claimed_at)"
                " VALUES (?, ?, ?, ?)",
                (other, receipt_key, "[]", ts),
            )

    add_until(39)
    state = get_state(user, conn=conn, now=ts)["community"]
    assert state["signals"] == 39
    assert state["milestones"][0]["claimable"]
    assert not state["milestones"][1]["unlocked"]
    assert not state["alignment"]["available"]
    assert claim(user, "community_stabilize", conn=conn, now=ts)[:2] == (
        False, "objective_incomplete"
    )
    assert claim(user, "alignment_industry", conn=conn, now=ts)[:2] == (
        False, "objective_incomplete"
    )

    add_until(40)
    state = get_state(user, conn=conn, now=ts)["community"]
    assert state["milestones"][1]["threshold"] == 40
    assert state["milestones"][1]["claimable"]
    assert state["alignment"]["required_global"] == 40
    assert state["alignment"]["available"]
    assert claim(user, "community_stabilize", conn=conn, now=ts)[0]
    assert claim(user, "alignment_industry", conn=conn, now=ts)[0]
    assert not claim(user, "alignment_science", conn=conn, now=ts)[0]
    assert get_state(user, conn=conn, now=ts)["community"]["signals"] == 40

    add_until(69)
    state = get_state(user, conn=conn, now=ts)["community"]
    assert state["signals"] == 69
    assert state["milestones"][2]["threshold"] == 70
    assert not state["milestones"][2]["unlocked"]
    assert claim(user, "community_contain", conn=conn, now=ts)[:2] == (
        False, "objective_incomplete"
    )

    add_until(70)
    state = get_state(user, conn=conn, now=ts)["community"]
    assert state["milestones"][2]["claimable"]
    assert claim(user, "community_contain", conn=conn, now=ts)[0]
    assert claim(user, "community_contain", conn=conn, now=ts)[:2] == (
        False, "already_claimed"
    )
    assert get_state(user, conn=conn, now=ts)["community"]["signals"] == 70
    conn.commit()
    conn.close()
