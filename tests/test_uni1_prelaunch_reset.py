"""UNI1 final closed-universe prelaunch normalization regression."""

from __future__ import annotations

import time
import uuid

import pytest


@pytest.fixture()
def uni1_prelaunch_db(tmp_path, monkeypatch):
    db_path = tmp_path / "uni1_prelaunch.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "uni1-prelaunch-test-secret-key-32chars")
    monkeypatch.setenv("GC_UNIVERSE_KEY", "uni1")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_KEY", "dev")
    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", "0")
    monkeypatch.setenv("GC_PIRATE_AI_ENABLED", "0")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_ENABLED", "0")
    monkeypatch.setenv("GC_UNIVERSE_SPEED_PROFILE", "x1")
    monkeypatch.setenv("GC_ENDGAME_ECONOMY_MODE", "active")
    monkeypatch.setenv("GC_ENDGAME_PRODUCTION_PIVOT", "120")
    monkeypatch.setenv("GC_ENDGAME_PRODUCTION_TAIL_POWER", "4")
    monkeypatch.setenv("GC_NETWORK_START_RESOURCE_MULTIPLIER", "10")
    monkeypatch.setenv("GC_NETWORK_START_TIMEKEEPER_SECONDS", str(72 * 3600))

    import game.db as dbmod
    import game.models as models

    dbmod._DB_PATH = None
    if hasattr(dbmod, "DB_PATH"):
        monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    if hasattr(models, "DB_PATH"):
        monkeypatch.setattr(models, "DB_PATH", db_path)

    from game.models import init_db

    init_db()
    import migrate

    migrate.main()

    monkeypatch.setattr("game.mine_evolution.ruleset.ASCENSION_RULESET", "nodebuster-v1")
    yield db_path
    dbmod._DB_PATH = None


def _human(conn, username: str, display: str) -> int:
    from game.models import create_user, ensure_player_and_homeworld

    ok, err, user = create_user(username, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name=display, conn=conn)
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO network_account_links
            (local_user_id, network_account_id, authority_key, created_at, last_login_at)
        VALUES (?, ?, 'dev', ?, ?);
        """,
        (uid, f"acct_{uuid.uuid4().hex}", now - 86400, now - 3600),
    )
    return uid


def test_prelaunch_reset_preserves_humans_removes_ai_and_normalizes_starters(
    uni1_prelaunch_db,
):
    from game.db import db
    from game.models import get_homeworld, get_planet_buildings, save_planet_buildings
    from game.pirates.accounts import PIRATE_BOT_USERNAMES, bootstrap_faction_bots
    from game.timekeeper import credit, get_balance
    from game.uni1_prelaunch import run_uni1_prelaunch_reset_once

    conn = db()
    try:
        human_a = _human(conn, "mando_probe", "Mando Probe")
        human_b = _human(conn, "gurken_probe", "Gurken Probe")

        home_a = get_homeworld(human_a, conn=conn)
        levels = get_planet_buildings(int(home_a["id"]), conn=conn)
        levels["metal_mine"] = 42
        levels["research_lab"] = 7
        save_planet_buildings(int(home_a["id"]), levels, conn=conn)
        conn.execute(
            "UPDATE planets SET metal = 999999999, crystal = 888888888, fuel_cells = 777777777 "
            "WHERE id = ?;",
            (int(home_a["id"]),),
        )

        credit(human_a, 3600, "prelaunch-test", conn=conn)
        credit(human_b, 100 * 3600, "prelaunch-test", conn=conn)

        bots = bootstrap_faction_bots(conn=conn)
        assert len(bots) == 6
        conn.execute(
            """
            INSERT INTO galaxy_heat
                (galaxy_id, heat, combat_events, expo_events, asteroid_events,
                 boss_events, colonize_events, updated_at)
            VALUES (1, 700, 1, 1, 1, 1, 1, ?)
            ON CONFLICT(galaxy_id) DO UPDATE SET heat = 700, updated_at = excluded.updated_at;
            """,
            (time.time(),),
        )
        conn.commit()
    finally:
        conn.close()

    token = "uni1-launch-test-v1"
    result = run_uni1_prelaunch_reset_once(token)
    assert result["ok"] is True
    assert result["skipped"] is False
    assert result["pirate_cleanup"]["accounts"]["deleted"] == 6

    conn = db()
    try:
        # Human account and cross-universe identity links survive.
        for uid in (human_a, human_b):
            assert conn.execute("SELECT 1 FROM users WHERE id = ?;", (uid,)).fetchone()
            assert conn.execute(
                "SELECT 1 FROM network_account_links WHERE local_user_id = ?;",
                (uid,),
            ).fetchone()

        placeholders = ",".join("?" for _ in PIRATE_BOT_USERNAMES)
        pirate_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM users WHERE username IN ({placeholders});",
            tuple(sorted(PIRATE_BOT_USERNAMES)),
        ).fetchone()
        assert int(pirate_count["c"]) == 0

        # Dynamic synthetic Pirate world state is minute-zero clean.
        for table in (
            "galaxy_heat",
            "pirate_bases",
            "pirate_bot_state",
            "pirate_intel",
            "pirate_action_log",
            "pirate_infiltrations",
            "smuggler_contacts",
        ):
            row = conn.execute(f"SELECT COUNT(*) AS c FROM {table};").fetchone()
            assert int(row["c"]) == 0

        # Existing humans receive exactly the same resource baseline future
        # first-entry players receive: 150k/100k/25k x10.
        for uid in (human_a, human_b):
            home = get_homeworld(uid, conn=conn)
            assert int(home["metal"]) == 1_500_000
            assert int(home["crystal"]) == 1_000_000
            assert int(home["fuel_cells"]) == 250_000
            b = get_planet_buildings(int(home["id"]), conn=conn)
            assert int(b.get("metal_mine", 0) or 0) == 0
            assert int(b.get("research_lab", 0) or 0) == 0

        # Top-up, never destructive overwrite: early tester gets 72h, a
        # hypothetical legitimate 100h balance remains 100h.
        assert get_balance(human_a, conn=conn) == 72 * 3600
        assert get_balance(human_b, conn=conn) == 100 * 3600

        # Existing early testers are not launch-day "inactive" because they
        # entered the universe before the public opening.
        now = int(time.time())
        for uid in (human_a, human_b):
            row = conn.execute(
                "SELECT last_seen FROM player_presence WHERE player_id = ?;",
                (uid,),
            ).fetchone()
            assert row is not None
            assert abs(int(row["last_seen"]) - now) <= 10

        # Same token is strictly one-shot. Mutate a value and prove a restart
        # cannot silently wipe the universe again.
        home_a = get_homeworld(human_a, conn=conn)
        conn.execute("UPDATE planets SET metal = 42 WHERE id = ?;", (int(home_a["id"]),))
        conn.commit()
    finally:
        conn.close()

    second = run_uni1_prelaunch_reset_once(token)
    assert second["ok"] is True
    assert second["skipped"] is True
    assert second["reason"] == "token_already_applied"

    conn = db()
    try:
        home_a = get_homeworld(human_a, conn=conn)
        assert int(home_a["metal"]) == 42
    finally:
        conn.close()


def test_prelaunch_reset_refuses_unsafe_environment(uni1_prelaunch_db, monkeypatch):
    from game.uni1_prelaunch import run_uni1_prelaunch_reset_once

    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", "1")
    with pytest.raises(RuntimeError, match="requires_closed_universe"):
        run_uni1_prelaunch_reset_once("uni1-unsafe-open")

    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", "0")
    monkeypatch.setenv("GC_PIRATE_AI_ENABLED", "1")
    with pytest.raises(RuntimeError, match="requires_pirate_ai_hard_off"):
        run_uni1_prelaunch_reset_once("uni1-unsafe-ai")



def test_hard_off_ranking_is_human_only_even_before_purge(uni1_prelaunch_db):
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld
    from game.pirates.accounts import bootstrap_faction_bots
    from game.ranking import (
        get_player_rank_from_snapshot,
        get_sorted_ranking_entries,
        recalculate_all_rankings,
    )

    conn = db()
    try:
        ok, err, user = create_user("ranking_human", "test-pass-123")
        assert ok, err
        human_id = int(user["id"])
        ensure_player_and_homeworld(human_id, player_name="Ranking Human", conn=conn)
        bots = bootstrap_faction_bots(conn=conn)
        conn.commit()

        recalculate_all_rankings(refresh_scores=True, conn=conn)
        rows = get_sorted_ranking_entries(limit=100, conn=conn)
        bot_ids = {int(bot["player_id"]) for bot in bots}
        visible_ids = {int(row["player_id"]) for row in rows}
        assert human_id in visible_ids
        assert not (bot_ids & visible_ids)

        rank, total = get_player_rank_from_snapshot(human_id, conn=conn)
        assert rank == 1
        assert total == 1
    finally:
        conn.close()
