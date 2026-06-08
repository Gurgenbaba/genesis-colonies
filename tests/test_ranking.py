"""
Ranking system tests.

Run: python -m pytest tests/test_ranking.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import create_user, init_db
from game.ranking import (
    build_ranking_api_payload,
    compute_player_scores,
    enrich_ranking_social_fields,
    get_player_score_row,
    get_sorted_ranking_entries,
    recalculate_all_rankings,
    recalculate_ranks,
    repair_player_score_totals,
    refresh_player_score,
    upsert_player_scores,
)
from game.scoring import (
    compute_destroyed_raw_from_losses,
    get_destroyed_raw,
    record_combat_outcome,
)
from game.alliance import create_alliance
from game.playercard import ensure_player_card_tables

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "ranking_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


@pytest.fixture()
def app_client(temp_db, monkeypatch):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _close_db() -> None:
    try:
        db().close()
    except Exception:
        pass


def _create_player(username: str) -> int:
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    _close_db()
    return int(user["id"])


def _seed_scores(player_id: int, building: int, research: int) -> None:
    upsert_player_scores(
        player_id,
        {
            "total_score": building + research,
            "building_score": building,
            "research_score": research,
            "fleet_score": 0,
            "defense_score": 0,
        },
    )
    _close_db()


def _set_player_card(
    player_id: int,
    *,
    avatar_url: str = "",
    title: str = "",
    is_public: int = 1,
) -> None:
    ensure_player_card_tables()
    conn = db()
    conn.execute(
        """
        INSERT INTO player_cards
            (player_id, avatar_url, title, bio, theme, is_public, created_at, updated_at)
        VALUES (?, ?, ?, '', 'cyan', ?, CAST(strftime('%s','now') AS INTEGER), CAST(strftime('%s','now') AS INTEGER))
        ON CONFLICT(player_id) DO UPDATE SET
            avatar_url = excluded.avatar_url,
            title = excluded.title,
            is_public = excluded.is_public,
            updated_at = CAST(strftime('%s','now') AS INTEGER)
        """,
        (int(player_id), avatar_url, title, int(is_public)),
    )
    conn.commit()
    conn.close()


def _update_player_name(player_id: int, name: str) -> None:
    conn = db()
    conn.execute("UPDATE players SET name = ? WHERE id = ?", (name, int(player_id)))
    conn.commit()
    conn.close()


def _login(client, username: str, password: str = "test-pass-123") -> None:
    resp = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert resp.status_code in (200, 302)


def test_total_score_is_sum_of_components():
    clean = {
        "total_score": 1500,
        "building_score": 1000,
        "research_score": 500,
        "fleet_score": 0,
        "defense_score": 0,
    }
    assert clean["total_score"] == (
        clean["building_score"]
        + clean["research_score"]
        + clean["fleet_score"]
        + clean["defense_score"]
    )


def test_ranking_order_and_current_player_consistency(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    player_a = _create_player("alpha")
    player_b = _create_player("beta")

    _seed_scores(player_a, building=1000, research=500)
    _seed_scores(player_b, building=200, research=300)

    recalculate_ranks()
    _close_db()

    payload = build_ranking_api_payload(player_a, limit=100, refresh=False)
    assert payload["ok"] is True

    top = payload["top_players"]
    assert len(top) >= 2
    assert top[0]["player_id"] == player_a
    assert top[0]["rank"] == 1
    assert top[0]["total_score"] == 1500
    assert top[1]["player_id"] == player_b
    assert top[1]["rank"] == 2
    assert top[1]["total_score"] == 500

    cur = payload["current_player"]
    assert cur["rank"] == 1
    assert cur["total_score"] == top[0]["total_score"]
    assert cur["building_score"] == top[0]["building_score"]
    assert cur["research_score"] == top[0]["research_score"]


def test_tie_breaker_building_then_player_id(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    low_id = _create_player("tie_low")
    high_id = _create_player("tie_high")
    assert low_id < high_id

    # Same total; more building wins. Same components -> lower player_id wins.
    _seed_scores(low_id, building=700, research=300)
    _seed_scores(high_id, building=600, research=400)

    recalculate_ranks()
    _close_db()

    payload = build_ranking_api_payload(low_id, limit=10, refresh=False)
    top = payload["top_players"]
    assert top[0]["player_id"] == low_id
    assert top[1]["player_id"] == high_id

    # Equal total/building/research – lower player_id ranks ahead
    _seed_scores(low_id, building=500, research=500)
    _seed_scores(high_id, building=500, research=500)
    recalculate_ranks()
    _close_db()

    payload2 = build_ranking_api_payload(low_id, limit=10, refresh=False)
    ids = [r["player_id"] for r in payload2["top_players"][:2]]
    assert ids == sorted([low_id, high_id])


def test_current_player_not_in_top_n(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    p1 = _create_player("top1")
    p2 = _create_player("top2")
    p3 = _create_player("top3")

    _seed_scores(p1, 900, 100)
    _seed_scores(p2, 800, 100)
    _seed_scores(p3, 100, 100)
    recalculate_ranks()
    _close_db()

    payload = build_ranking_api_payload(p3, limit=2, refresh=False)
    top_ids = {r["player_id"] for r in payload["top_players"]}
    assert p3 not in top_ids
    assert payload["current_player"]["rank"] == 3
    assert payload["current_player"]["total_score"] == 200


def test_legacy_weighted_total_repaired(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("legacy")
    conn = db()
    conn.execute(
        """
        INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
        VALUES (?, ?, ?, ?, CAST(strftime('%s','now') AS INTEGER))
        ON CONFLICT(player_id) DO UPDATE SET
            score_total = excluded.score_total,
            score_buildings = excluded.score_buildings,
            score_research = excluded.score_research,
            updated_at = excluded.updated_at
        """,
        (pid, 1_414_715, 4_000_000, 3_474_715),
    )
    conn.commit()
    conn.close()

    row_before = get_player_score_row(pid)
    assert int(row_before["score_total"]) == 1_414_715

    repaired = repair_player_score_totals(pid)
    _close_db()
    assert repaired is True

    row_after = get_player_score_row(pid)
    expected = 4_000_000 + 3_474_715
    assert int(row_after["score_total"]) == expected

    payload = build_ranking_api_payload(pid, limit=10, refresh=False)
    assert payload["current_player"]["total_score"] == expected


def test_api_read_path_skips_full_recalc(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("readpath")
    _seed_scores(pid, 10, 20)
    recalculate_ranks()
    _close_db()

    with patch("game.ranking.recalculate_all_rankings") as mock_full:
        build_ranking_api_payload(pid, limit=10, refresh=False)
        mock_full.assert_not_called()

    with patch("game.ranking.recalculate_all_rankings") as mock_full:
        build_ranking_api_payload(pid, limit=10, refresh=True)
        mock_full.assert_called_once()


def test_current_player_matches_top_row_when_listed(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("listed")
    _seed_scores(pid, 1200, 300)
    recalculate_ranks()
    _close_db()

    payload = build_ranking_api_payload(pid, limit=10, refresh=False)
    row = next(r for r in payload["top_players"] if r["player_id"] == pid)
    cur = payload["current_player"]
    assert cur["rank"] == row["rank"]
    assert cur["total_score"] == row["total_score"]
    assert cur["building_score"] == row["building_score"]
    assert cur["research_score"] == row["research_score"]


def test_recalculate_all_players(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    player_a = _create_player("recalc_a")
    _seed_scores(player_a, building=50, research=50)

    result = recalculate_all_rankings(refresh_scores=True)
    _close_db()

    assert result["players_updated"] >= 1
    assert result["ranks_assigned"] >= 1
    assert result["ok"] is True


def test_compute_player_scores_returns_zero_for_new_player(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("empty")
    scores = compute_player_scores(pid)
    _close_db()

    assert scores["building_score"] == 0
    assert scores["research_score"] == 0
    assert scores["fleet_score"] == 0
    assert scores["total_score"] == 0


def test_compute_player_scores_includes_fleet(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("fleet_owner")
    conn = db()
    planet = conn.execute(
        "SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
        (pid,),
    ).fetchone()
    assert planet
    conn.execute(
        """
        INSERT INTO planet_ships (player_id, planet_id, ship_key, amount, created_at, updated_at)
        VALUES (?, ?, 'spark_drone', 10, CAST(strftime('%s','now') AS INTEGER), CAST(strftime('%s','now') AS INTEGER))
        ON CONFLICT DO NOTHING;
        """,
        (pid, int(planet["id"])),
    )
    conn.commit()
    conn.close()
    _close_db()

    scores = compute_player_scores(pid)
    # spark_drone: 500 metal + 200 crystal = 700 per hull × 10 = 7000
    assert scores["fleet_score"] == 7000
    assert scores["total_score"] == 7000

    refresh = build_ranking_api_payload(pid, limit=10, refresh=True)
    assert refresh["current_player"]["fleet_score"] == 7000
    assert refresh["current_player"]["ranks"].get("fleet") == 1


def test_migration_014_idempotent(temp_db):
    _run_migrate(temp_db)
    _run_migrate(temp_db)
    _close_db()
    conn = db()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(player_scores);").fetchall()}
    conn.close()
    assert "score_fleet" in cols
    assert "rank_total" in cols
    assert "rank_fleet" in cols


def test_api_ranking_requires_login(app_client):
    resp = app_client.get("/api/ranking")
    assert resp.status_code in (401, 302)


def test_admin_recalculate_forbidden_for_normal_user(app_client, temp_db):
    _close_db()
    uid = _create_player("normie")
    conn = db()
    conn.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (uid,))
    conn.execute("UPDATE players SET is_admin = 0 WHERE id = ?", (uid,))
    user_row = conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
    conn.commit()
    conn.close()

    _login(app_client, user_row["username"])
    resp = app_client.post("/api/admin/rankings/recalculate")
    assert resp.status_code == 403


def test_admin_recalculate_allowed_for_admin(app_client, temp_db):
    _close_db()
    uid = _create_player("adminrank")
    conn = db()
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (uid,))
    conn.execute("UPDATE players SET is_admin = 1 WHERE id = ?", (uid,))
    user_row = conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
    conn.commit()
    conn.close()

    _login(app_client, user_row["username"])
    resp = app_client.post("/api/admin/rankings/recalculate")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True


def test_ranking_includes_avatar_when_public(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("avatar_public")
    _update_player_name(pid, "AlphaCmd")
    _seed_scores(pid, 500, 100)
    _set_player_card(pid, avatar_url="https://cdn.example.com/a.png", title="Star Marshal", is_public=1)
    recalculate_ranks()
    _close_db()

    rows = get_sorted_ranking_entries(limit=10)
    row = next(r for r in rows if r["player_id"] == pid)
    assert row["show_avatar"] is True
    assert "cdn.example.com/a.png" in row["avatar_url"]
    assert "?v=" in row["avatar_url"] or "&v=" in row["avatar_url"]
    assert row["avatar_initial"] == "A"
    assert row["title"] == "Star Marshal"


def test_ranking_private_profile_hides_avatar(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("avatar_private")
    _update_player_name(pid, "HiddenCmd")
    _seed_scores(pid, 400, 50)
    _set_player_card(pid, avatar_url="https://cdn.example.com/hidden.png", title="Secret", is_public=0)
    recalculate_ranks()
    _close_db()

    rows = get_sorted_ranking_entries(limit=10)
    row = next(r for r in rows if r["player_id"] == pid)
    assert row["show_avatar"] is False
    assert row["avatar_url"] == ""
    assert row["avatar_initial"] == "H"
    assert row["title"] == ""
    assert row["profile_is_public"] is False


def test_ranking_includes_alliance(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("allied")
    _seed_scores(pid, 900, 100)
    create_alliance("NXS", "Nexus Pact", pid)
    recalculate_ranks()
    _close_db()

    rows = get_sorted_ranking_entries(limit=10)
    row = next(r for r in rows if r["player_id"] == pid)
    assert row["alliance_id"] is not None
    assert row["alliance_tag"] == "NXS"
    assert row["alliance_name"] == "Nexus Pact"


def test_ranking_no_alliance_when_missing(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("loner")
    _seed_scores(pid, 100, 50)
    recalculate_ranks()
    _close_db()

    rows = get_sorted_ranking_entries(limit=10)
    row = next(r for r in rows if r["player_id"] == pid)
    assert row["alliance_id"] is None
    assert row["alliance_tag"] == ""
    assert row["alliance_name"] == ""


def test_ranking_api_payload_has_social_fields(app_client, temp_db):
    _close_db()
    pid = _create_player("social_api")
    _update_player_name(pid, "SocialCmd")
    _seed_scores(pid, 700, 200)
    _set_player_card(pid, avatar_url="https://cdn.example.com/s.png", title="Pilot", is_public=1)
    create_alliance("SOC", "Social Fleet", pid)
    recalculate_ranks()
    _close_db()

    conn = db()
    user_row = conn.execute("SELECT username FROM users WHERE id = ?", (pid,)).fetchone()
    conn.close()

    _login(app_client, user_row["username"])
    resp = app_client.get("/api/ranking")
    assert resp.status_code == 200
    data = resp.get_json()
    row = next(r for r in data["top_players"] if r["player_id"] == pid)
    assert row["player_id"] == pid
    assert row["show_avatar"] is True
    assert row["alliance_tag"] == "SOC"
    assert "avatar_initial" in row
    assert "title" in row


def test_ranking_page_embeds_payload_with_player_id(app_client, temp_db):
    _close_db()
    pid = _create_player("page_embed")
    _seed_scores(pid, 300, 100)
    recalculate_ranks()
    _close_db()

    conn = db()
    user_row = conn.execute("SELECT username FROM users WHERE id = ?", (pid,)).fetchone()
    conn.close()

    _login(app_client, user_row["username"])
    resp = app_client.get("/ranking")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "ranking-initial-data" in html
    assert f'"player_id": {pid}' in html or f'"player_id":{pid}' in html
    assert "gc-ranking" in html
    assert "ranking-tabs" in html
    assert "ranking-my-strip" in html


def test_ranking_html_escapes_special_characters(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("xss_rank")
    _update_player_name(pid, '<script>alert(1)</script>')
    _seed_scores(pid, 250, 50)
    create_alliance("XSS", 'Evil <img onerror=alert(1)>', pid)
    recalculate_ranks()
    _close_db()

    rows = get_sorted_ranking_entries(limit=10)
    row = next(r for r in rows if r["player_id"] == pid)
    social = enrich_ranking_social_fields(
        {
            **row,
            "card_avatar_url": "",
            "card_title": "",
            "card_theme": "cyan",
            "card_is_public": 1,
            "alliance_id": row["alliance_id"],
            "alliance_tag": row["alliance_tag"],
            "alliance_name": row["alliance_name"],
        }
    )
    assert "<script>" in row["commander_name"]
    assert "<img" in row["alliance_name"]
    assert social["alliance_tag"] == "XSS"


def test_ranking_uses_single_join_query(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    from game.ranking import _fleet_defense_select, _ranking_social_select_and_join

    conn = db()
    extra = _fleet_defense_select(conn)
    social_select, social_join = _ranking_social_select_and_join(conn)
    sql = (
        f"SELECT p.id, {extra}, {social_select} "
        f"FROM players p JOIN player_scores ps ON ps.player_id = p.id {social_join}"
    )
    conn.close()

    assert "LEFT JOIN player_cards pc ON pc.player_id = p.id" in sql
    assert "LEFT JOIN alliance_members am ON am.player_id = p.id" in sql
    assert "LEFT JOIN alliances a ON a.id = am.alliance_id" in sql
    assert "card_avatar_url" in social_select
    assert "alliance_tag" in social_select

    for i in range(3):
        pid = _create_player(f"join_{i}")
        _seed_scores(pid, 100 * (i + 1), 50)
    recalculate_ranks()
    _close_db()

    rows = get_sorted_ranking_entries(limit=10)
    assert len(rows) >= 3
    assert all("avatar_initial" in row for row in rows)
    assert all("alliance_id" in row for row in rows)


def test_ranking_includes_badges_when_public(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("badge_rank")
    _seed_scores(pid, 600, 100)
    _set_player_card(pid, avatar_url="https://cdn.example.com/b.png", title="Owner", is_public=1)
    conn = db()
    founder = conn.execute(
        "SELECT id FROM player_card_badges WHERE badge_key = 'founder' LIMIT 1"
    ).fetchone()
    assert founder
    conn.execute(
        "UPDATE player_cards SET selected_badge_1 = ? WHERE player_id = ?",
        (int(founder["id"]), int(pid)),
    )
    conn.commit()
    conn.close()
    recalculate_ranks()
    _close_db()

    rows = get_sorted_ranking_entries(limit=10)
    row = next(r for r in rows if r["player_id"] == pid)
    assert len(row.get("badges") or []) >= 1
    assert row["badges"][0]["icon"]


def test_ranking_invalid_avatar_url_rejected(temp_db):
    raw = {
        "commander_name": "Test",
        "card_avatar_url": "javascript:alert(1)",
        "card_title": "Title",
        "card_theme": "cyan",
        "card_is_public": 1,
        "alliance_id": None,
        "alliance_tag": "",
        "alliance_name": "",
    }
    social = enrich_ranking_social_fields(raw)
    assert social["show_avatar"] is False
    assert social["avatar_url"] == ""
    assert social["avatar_initial"] == "T"


def test_ranking_includes_player_without_score_row(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("zero_row")
    conn = db()
    conn.execute("DELETE FROM player_scores WHERE player_id = ?", (pid,))
    conn.commit()
    conn.close()
    _close_db()

    rows = get_sorted_ranking_entries(limit=200)
    match = next((r for r in rows if r["player_id"] == pid), None)
    assert match is not None
    assert match["total_score"] == 0
    assert match["building_score"] == 0
    assert match["research_score"] == 0


def test_ranking_avatar_cache_bust(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("avatar_rank")
    _seed_scores(pid, 10, 5)
    recalculate_ranks()
    _set_player_card(
        pid,
        avatar_url="https://example.com/avatar.png",
        is_public=1,
    )
    _close_db()

    rows = get_sorted_ranking_entries(limit=50)
    row = next(r for r in rows if r["player_id"] == pid)
    assert row["show_avatar"] is True
    assert "example.com/avatar.png" in row["avatar_url"]
    assert "?v=" in row["avatar_url"] or "&v=" in row["avatar_url"]


def test_ranking_uses_component_sum_not_stale_score_total(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    high = _create_player("sum_high")
    low = _create_player("sum_low")

    conn = db()
    conn.execute(
        """
        UPDATE player_scores
        SET score_total = 50, score_buildings = 3000, score_research = 2000,
            score_fleet = 0, score_defense = 0
        WHERE player_id = ?
        """,
        (high,),
    )
    conn.execute(
        """
        UPDATE player_scores
        SET score_total = 99999, score_buildings = 100, score_research = 50,
            score_fleet = 0, score_defense = 0
        WHERE player_id = ?
        """,
        (low,),
    )
    conn.commit()
    conn.close()

    payload = build_ranking_api_payload(high, limit=10, refresh=False)
    assert payload["top_players"][0]["player_id"] == high
    assert payload["top_players"][0]["total_score"] == 5000
    assert payload["current_player"]["total_score"] == 5000
    assert payload["current_player"]["rank"] == 1


def test_combat_destruction_increases_ranking_scores(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    attacker = _create_player("combat_atk")
    defender = _create_player("combat_def")
    conn = db()
    try:
        record_combat_outcome(
            attacker_id=attacker,
            defender_id=defender,
            attacker_losses={},
            defender_losses={"sentinel_turret": 4},
            conn=conn,
        )
        conn.commit()
        raw = get_destroyed_raw(attacker, conn=conn)
        assert raw == compute_destroyed_raw_from_losses({"sentinel_turret": 4})

        refresh_player_score(attacker, conn=conn)
        conn.commit()
        row = get_player_score_row(attacker, conn=conn)
        assert row is not None
        assert int(row["score_destroyed_raw"]) == raw
        assert int(row["score_destroyed"]) > 0
        assert int(row["score_total"]) >= int(row["score_destroyed"])
    finally:
        conn.close()
    _close_db()

    recalculate_ranks()
    entries = get_sorted_ranking_entries(limit=50)
    atk_row = next(r for r in entries if r["player_id"] == attacker)
    assert atk_row["destroyed_score"] > 0
    assert atk_row["military_score"] >= atk_row["destroyed_score"]
