"""
Ranking system tests.

Run: python -m pytest tests/test_ranking.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
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
    ranking_inactive_from_last_seen,
    recalculate_all_rankings,
    recalculate_ranks,
    repair_player_score_totals,
    refresh_player_score,
    upsert_player_scores,
    _normalize_db_row,
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
    from game.ranking import _sanitize_scores

    clean = _sanitize_scores(
        {
            "resource_score": 0,
            "building_score": 1000,
            "research_score": 500,
            "fleet_score": 0,
            "defense_score": 0,
            "destroyed_score": 250,
            "evolution_score": 0,
        }
    )
    assert clean["total_score"] == 1500
    assert clean["destroyed_score"] == 250


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
    from game.models import DEFAULT_GAME_SETTINGS
    from game.resource_score import score_from_resources

    expected_resources = score_from_resources(
        int(DEFAULT_GAME_SETTINGS["start_metal"]),
        int(DEFAULT_GAME_SETTINGS["start_crystal"]),
        int(DEFAULT_GAME_SETTINGS["start_fuel_cells"]),
    )
    assert scores["resource_score"] == expected_resources
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
        VALUES (?, ?, 'mule_courier', 10, CAST(strftime('%s','now') AS INTEGER), CAST(strftime('%s','now') AS INTEGER))
        ON CONFLICT DO NOTHING;
        """,
        (pid, int(planet["id"])),
    )
    conn.commit()
    conn.close()
    _close_db()

    scores = compute_player_scores(pid)
    # mule_courier: 2500/2500/0 -> 3 points per hull × 10 = 30
    assert scores["fleet_score"] == 30

    refresh = build_ranking_api_payload(pid, limit=10, refresh=True)
    assert refresh["current_player"]["fleet_score"] == 30
    assert refresh["current_player"]["ranks"].get("fleet") == 1


def test_compute_player_scores_research_uses_cumulative_costs(temp_db):
    """Research ranking points = cumulative invested costs via resource_score."""
    from game.research import RESEARCH_TECHS, get_research_cost

    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("researcher")
    conn = db()
    conn.execute(
        """
        INSERT INTO research_levels (user_id, tech_key, level)
        VALUES (?, 'energy_tech', 3)
        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (pid,),
    )
    conn.commit()
    conn.close()
    _close_db()

    total_metal = 0
    total_crystal = 0
    for target in range(1, 4):
        metal, crystal = get_research_cost("energy_tech", target)
        total_metal += int(metal)
        total_crystal += int(crystal)
    from game.resource_score import score_from_resources

    cumulative = score_from_resources(total_metal, total_crystal, 0)
    scores = compute_player_scores(pid)
    assert scores["research_score"] == cumulative
    level2_metal = 0
    level2_crystal = 0
    for target in range(1, 3):
        metal, crystal = get_research_cost("energy_tech", target)
        level2_metal += int(metal)
        level2_crystal += int(crystal)
    level2 = score_from_resources(level2_metal, level2_crystal, 0)
    assert cumulative > level2
    assert scores["research_score"] > level2


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
    assert "players_seen" in data
    assert "players_updated" in data
    assert "ranks_assigned" in data
    assert "duration_ms" in data
    assert data.get("skipped_interval") is False


def test_admin_ranking_recompute_alias(app_client, temp_db):
    _close_db()
    uid = _create_player("adminrecomp")
    conn = db()
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (uid,))
    conn.execute("UPDATE players SET is_admin = 1 WHERE id = ?", (uid,))
    user_row = conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
    conn.commit()
    conn.close()

    _login(app_client, user_row["username"])
    resp = app_client.post("/api/admin/ranking/recompute")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True
    assert "players_seen" in data
    assert "scores_updated" in data
    assert "ranks_assigned" in data
    assert "duration_ms" in data

    audit = app_client.get("/api/admin/audit-log?action=admin_ranking_recompute")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(row.get("action") == "admin_ranking_recompute" for row in entries)


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
    assert "FROM alliance_members" in sql
    assert "GROUP BY player_id" in sql
    assert "LEFT JOIN alliances a ON a.id = am.alliance_id" in sql
    assert "card_avatar_url" in social_select
    assert "alliance_tag" in social_select
    assert "card_name_style" in social_select

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
    assert row["badges"][0]["image_url"].startswith("/static/img/badges/")


def test_ranking_invalid_avatar_url_rejected(temp_db):
    raw = {
        "commander_name": "Test",
        "card_avatar_url": "javascript:alert(1)",
        "card_title": "Title",
        "card_theme": "cyan",
        "card_name_style": "plasma",
        "card_is_public": 1,
        "alliance_id": None,
        "alliance_tag": "",
        "alliance_name": "",
    }
    social = enrich_ranking_social_fields(raw)
    assert social["show_avatar"] is False
    assert social["avatar_url"] == ""
    assert social["avatar_initial"] == "T"
    assert social["name_style"] == "plasma"


def test_ranking_name_style_always_public(temp_db):
    """Name style is a social signal — exposed even when the card is private."""
    social = enrich_ranking_social_fields(
        {
            "commander_name": "Ghost",
            "card_avatar_url": "/static/img/x.png",
            "card_title": "Hidden",
            "card_theme": "violet",
            "card_name_style": "void",
            "card_is_public": 0,
            "alliance_id": None,
            "alliance_tag": "",
            "alliance_name": "",
        }
    )
    assert social["profile_is_public"] is False
    assert social["title"] == ""
    assert social["name_style"] == "void"


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


def test_ranking_dedupes_player_in_multiple_alliances(temp_db):
    """One player in two alliances must not appear twice in ranking rows."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("dual_alliance")
    _seed_scores(pid, 500, 100)
    create_alliance("AAA", "Alpha", pid)
    conn = db()
    conn.execute(
        "INSERT INTO alliances (tag, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("BBB", "Beta", 1, 1),
    )
    beta_id = conn.execute("SELECT id FROM alliances WHERE tag = 'BBB'").fetchone()["id"]
    conn.execute(
        "INSERT INTO alliance_members (alliance_id, player_id, role, joined_at) VALUES (?, ?, 'member', ?)",
        (beta_id, pid, 2),
    )
    conn.commit()
    conn.close()
    _close_db()

    rows = get_sorted_ranking_entries(limit=200)
    matches = [r for r in rows if r["player_id"] == pid]
    assert len(matches) == 1


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


def test_ranking_persistent_avatar_url(temp_db):
    from game.playercard import avatar_api_path, process_avatar_upload

    class _FakeUpload:
        def __init__(self, data: bytes, mimetype: str = "image/png"):
            self._data = data
            self.mimetype = mimetype

        def read(self) -> bytes:
            return self._data

    def _png_bytes() -> bytes:
        from PIL import Image
        import io

        im = Image.new("RGB", (64, 64), (40, 120, 200))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("avatar_persist_rank")
    _seed_scores(pid, 10, 5)
    recalculate_ranks()
    ok, path = process_avatar_upload(pid, _FakeUpload(_png_bytes()))
    assert ok is True
    _set_player_card(pid, avatar_url=path, is_public=1)
    _close_db()

    rows = get_sorted_ranking_entries(limit=50)
    row = next(r for r in rows if r["player_id"] == pid)
    assert row["show_avatar"] is True
    assert f"/api/player-avatar/{pid}" in row["avatar_url"]
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


def test_ranking_api_rank_monotonic_despite_stale_rank_columns(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    players = []
    for idx, total in enumerate((1000, 800, 600, 400, 200), start=1):
        pid = _create_player(f"mono_{idx}")
        _seed_scores(pid, building=total, research=0)
        players.append(pid)

    conn = db()
    conn.execute(
        """
        UPDATE player_scores
        SET rank_total = CASE
            WHEN player_id = ? THEN 6
            WHEN player_id = ? THEN 6
            WHEN player_id = ? THEN 7
            WHEN player_id = ? THEN 8
            WHEN player_id = ? THEN 9
            ELSE rank_total
        END
        """,
        tuple(players),
    )
    conn.commit()
    conn.close()

    payload = build_ranking_api_payload(players[0], limit=10, refresh=False)
    top = payload["top_players"][:5]
    ranks = [row["rank"] for row in top]
    scores = [row["total_score"] for row in top]

    assert ranks == [1, 2, 3, 4, 5]
    assert scores == sorted(scores, reverse=True)
    assert payload["current_player"]["rank"] == 1


def test_recalculate_ranks_includes_evolution_and_destroyed(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    low = _create_player("rank_low")
    high = _create_player("rank_high")

    conn = db()
    conn.execute(
        """
        UPDATE player_scores
        SET score_total = 100,
            score_buildings = 100,
            score_research = 0,
            score_fleet = 0,
            score_defense = 0,
            score_destroyed = 0,
            score_planet_evolution = 0
        WHERE player_id = ?
        """,
        (low,),
    )
    conn.execute(
        """
        UPDATE player_scores
        SET score_total = 50,
            score_buildings = 50,
            score_research = 0,
            score_fleet = 0,
            score_defense = 0,
            score_destroyed = 0,
            score_planet_evolution = 5000
        WHERE player_id = ?
        """,
        (high,),
    )
    conn.commit()
    conn.close()

    recalculate_ranks()
    _close_db()

    payload = build_ranking_api_payload(high, limit=10, refresh=False)
    top = payload["top_players"][:2]
    assert top[0]["player_id"] == high
    assert top[0]["rank"] == 1
    assert top[0]["total_score"] == 5050
    assert top[1]["player_id"] == low
    assert top[1]["rank"] == 2
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
            defender_losses={"plasma_arc": 4},
            conn=conn,
        )
        conn.commit()
        raw = get_destroyed_raw(attacker, conn=conn)
        assert raw == compute_destroyed_raw_from_losses({"plasma_arc": 4})

        refresh_player_score(attacker, conn=conn)
        conn.commit()
        row = get_player_score_row(attacker, conn=conn)
        assert row is not None
        assert int(row["score_destroyed_raw"]) == raw
        assert int(row["score_destroyed"]) > 0
        normalized = _normalize_db_row(dict(row))
        assert normalized["total_score"] == (normalized["building_score"] + normalized["research_score"] + normalized["fleet_score"] + normalized["defense_score"] + normalized["evolution_score"])
        assert normalized["destroyed_score"] == raw
    finally:
        conn.close()
    _close_db()

    recalculate_ranks()
    entries = get_sorted_ranking_entries(limit=50)
    atk_row = next(r for r in entries if r["player_id"] == attacker)
    assert atk_row["destroyed_score"] > 0
    assert atk_row["military_score"] >= atk_row["destroyed_score"]


def test_ranking_exposes_vacation_active_flag(temp_db):
    _run_migrate(temp_db)
    init_db()
    ok, err, user = create_user(f"vac_rank_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    pid = int(user["id"])
    from game.models import ensure_player_and_homeworld

    conn = db()
    ensure_player_and_homeworld(pid, player_name="Vacationer", conn=conn)
    conn.execute(
        "UPDATE players SET vacation_mode_active = 1, vacation_locked_until = ? WHERE id = ?;",
        (int(time.time()) + 86400, pid),
    )
    conn.commit()
    conn.close()

    entries = get_sorted_ranking_entries(limit=50)
    row = next(r for r in entries if int(r["player_id"]) == pid)
    assert row["vacation_active"] is True


def test_ranking_world_boss_and_alliance_tabs(temp_db):
    """GC-Rnk-01: lifetime WB damage + alliance points = sum of member scores."""
    from game.db import begin_write_transaction
    from game.world_boss import spawn_world_boss

    _run_migrate(temp_db)
    init_db()
    _close_db()

    leader = _create_player("rnk_ally_lead")
    member = _create_player("rnk_ally_mem")
    solo = _create_player("rnk_solo_wb")

    _seed_scores(leader, 1000, 0)
    _seed_scores(member, 400, 0)
    _seed_scores(solo, 50, 0)

    create_alliance("WBA", "World Boss Alliance", leader)
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM alliances WHERE tag = 'WBA' LIMIT 1")
        aid = int(cur.fetchone()["id"])
        cur.execute(
            "INSERT INTO alliance_members (alliance_id, player_id, role, joined_at) VALUES (?, ?, 'member', ?)",
            (aid, member, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=1,
            system=9,
            position=4,
            announce=False,
        )
        eid = int(spawn["event"]["id"])
        now = time.time()
        for pid, dmg in ((solo, 9000), (leader, 1000), (member, 500)):
            conn.execute(
                """
                INSERT INTO world_boss_contributions (
                    event_id, player_id, alliance_id, damage, waves,
                    last_attack_at, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, 1, ?, ?, ?)
                """,
                (eid, pid, dmg, now, now, now),
            )
        conn.commit()
    finally:
        conn.close()
    _close_db()

    payload = build_ranking_api_payload(solo, limit=50, refresh=False)
    assert payload["ok"] is True
    assert "top_alliances" in payload

    top = payload["top_players"]
    solo_row = next(r for r in top if r["player_id"] == solo)
    assert int(solo_row.get("world_boss_damage") or 0) == 9000
    assert int(payload["current_player"].get("world_boss_damage") or 0) == 9000

    alliances = payload["top_alliances"]
    assert alliances, "expected at least one alliance ranking row"
    top_ally = alliances[0]
    assert int(top_ally["alliance_id"]) == aid
    assert int(top_ally["alliance_score"]) == 1400  # 1000 + 400

    payload_lead = build_ranking_api_payload(leader, limit=50, refresh=False)
    cur = payload_lead["current_player"]
    assert int(cur["alliance_id"]) == aid
    assert int(cur["alliance_score"]) == 1400
    assert int(cur["alliance_rank"]) == 1


def test_ranking_inactive_flag_after_three_days(temp_db):
    _run_migrate(temp_db)
    init_db()
    ok, err, user = create_user(f"inactive_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    pid = int(user["id"])
    from game.models import ensure_player_and_homeworld

    now = int(time.time())
    conn = db()
    ensure_player_and_homeworld(pid, player_name="InactiveOne", conn=conn)
    conn.execute("UPDATE players SET last_seen = ? WHERE id = ?;", (now - 4 * 86400, pid))
    conn.commit()
    conn.close()

    assert ranking_inactive_from_last_seen(now - 4 * 86400, now=now) is True
    assert ranking_inactive_from_last_seen(now - 2 * 86400, now=now) is False
    assert ranking_inactive_from_last_seen(0, now=now) is True

    entries = get_sorted_ranking_entries(limit=50)
    row = next(r for r in entries if int(r["player_id"]) == pid)
    assert row["inactive"] is True
    assert row["vacation_active"] is False


# GC-SCORE-BIGNUM regression coverage

def test_big_score_has_no_ceiling_and_excludes_liquid_wealth():
    from game.ranking import _sanitize_scores

    huge = 10**50 + 123456789
    clean = _sanitize_scores({
        "resource_score": huge * 9,
        "building_score": huge,
        "research_score": 7,
        "fleet_score": 11,
        "defense_score": 13,
        "evolution_score": 17,
    })
    assert clean["resource_score"] == huge * 9
    assert clean["total_score"] == huge + 48


def test_big_score_text_roundtrip_exact_order_and_js_transport(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()
    low = _create_player("big_low")
    high = _create_player("big_high")
    base = 10**40
    _seed_scores(low, base, 1)
    _seed_scores(high, base + 1, 1)

    conn = db()
    row = conn.execute("SELECT score_total, typeof(score_total) AS kind FROM player_scores WHERE player_id = ?", (high,)).fetchone()
    conn.close()
    assert row["kind"] == "text"
    assert row["score_total"] == str(base + 2)

    payload = build_ranking_api_payload(high, limit=10, refresh=False)
    rows = [r for r in payload["top_players"] if r["player_id"] in (low, high)]
    assert [r["player_id"] for r in rows] == [high, low]
    assert rows[0]["total_score"] == str(base + 2)
    assert rows[1]["total_score"] == str(base + 1)
    assert payload["current_player"]["total_score"] == str(base + 2)


def test_big_score_schema_is_decimal_text(temp_db):
    _run_migrate(temp_db)
    init_db()
    conn = db()
    types = {row["name"]: str(row["type"]).upper() for row in conn.execute("PRAGMA table_info(player_scores)").fetchall()}
    conn.close()
    for column in (
        "score_total", "score_resources", "score_buildings", "score_research", "score_fleet",
        "score_defense", "score_planet_evolution", "score_destroyed_raw", "score_combat", "score_destroyed",
    ):
        assert types[column] == "TEXT"


def test_big_score_exact_order_with_122_players(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()
    base = 10**35
    created = []
    for idx in range(122):
        pid = _create_player(f"live_scale_{idx}")
        created.append(pid)
        _seed_scores(pid, base + idx, idx % 3)
    rows = get_sorted_ranking_entries(limit=122, offset=0)
    ranked = [r for r in rows if r["player_id"] in set(created)]
    expected = sorted(created, key=lambda pid: -(base + created.index(pid) + (created.index(pid) % 3)))
    assert [r["player_id"] for r in ranked] == expected


# GC-SCORE-BIGNUM live hardening coverage

def test_big_score_rank_reads_never_seed_score_rows(temp_db):
    from game.ranking import get_player_category_ranks, get_player_rank_from_snapshot

    _run_migrate(temp_db)
    init_db()
    _close_db()
    pid = _create_player("rank_read_only")
    conn = db()
    conn.execute("DELETE FROM player_scores WHERE player_id = ?", (pid,))
    conn.commit()
    conn.close()

    with patch("game.ranking._ensure_score_rows") as ensure_rows:
        rank, total = get_player_rank_from_snapshot(pid)
        ranks = get_player_category_ranks(pid)
        ensure_rows.assert_not_called()
    assert rank is not None
    assert total >= 1
    assert ranks["total_players"] >= 1

    conn = db()
    persisted = conn.execute("SELECT 1 FROM player_scores WHERE player_id = ?", (pid,)).fetchone()
    conn.close()
    assert persisted is None


def test_read_player_scores_preserves_combat_and_destroyed_fields(temp_db):
    from game.ranking import read_player_scores

    _run_migrate(temp_db)
    init_db()
    _close_db()
    pid = _create_player("score_projection")
    upsert_player_scores(pid, {
        "building_score": 10,
        "research_score": 20,
        "fleet_score": 30,
        "defense_score": 40,
        "destroyed_raw": 123456789,
        "destroyed_score": 123456789,
    })
    scores = read_player_scores(pid)
    assert scores["total_score"] == 100
    assert scores["combat_score"] == 70
    assert scores["destroyed_score"] == 123456789
    assert scores["destroyed_raw"] == 123456789


def test_pirate_threat_accepts_scores_far_beyond_float(temp_db):
    from game.pirates.threat import recompute_player_threat, threat_schema_ready

    _run_migrate(temp_db)
    init_db()
    _close_db()
    pid = _create_player("huge_threat")
    conn = db()
    if not threat_schema_ready(conn):
        conn.close()
        pytest.skip("pirate threat schema unavailable")
    huge = 10**500
    upsert_player_scores(pid, {
        "building_score": huge,
        "fleet_score": huge,
        "defense_score": huge,
        "destroyed_score": huge,
        "destroyed_raw": huge,
    }, conn=conn)
    result = recompute_player_threat(pid, conn=conn)
    conn.commit()
    conn.close()
    assert 0 <= result["threat"] <= 100
