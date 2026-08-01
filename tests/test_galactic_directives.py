"""GC-720B/C — Galactic directive definitions and active state resolver."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.galactic_directives import (
    FALLBACK_PRIMARY,
    SECONDARY_SCALE,
    build_galactic_directive_banner,
    ensure_galaxy_state,
    get_active_directives_for_galaxy,
    get_galaxy_directive_mechanics,
    list_active_directives_for_galaxies,
    merge_mechanics,
    normalize_galaxy,
    scale_numeric_mechanics,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gd_db(tmp_path, monkeypatch):
    db_file = tmp_path / "galactic_directives.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    yield db_file


def test_normalize_galaxy_rejects_invalid(gd_db):
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('galaxy_count', '3');"
        )
        conn.commit()

        assert normalize_galaxy(1, conn=conn) == 1
        assert normalize_galaxy(3, conn=conn) == 3
        assert normalize_galaxy(0, conn=conn) is None
        assert normalize_galaxy(4, conn=conn) is None
        assert normalize_galaxy("2", conn=conn) == 2
        assert normalize_galaxy("nope", conn=conn) is None
    finally:
        conn.close()


def test_ensure_galaxy_state_bootstraps_defensive(gd_db):
    conn = db()
    try:
        state = ensure_galaxy_state(1, conn=conn)
        assert state["galaxy"] == 1
        assert state["primary_directive"] == FALLBACK_PRIMARY
        assert state["secondary_directive"] is None
        assert int(state["consecutive_primary_wins"] or 0) == 0

        row = conn.execute(
            "SELECT primary_directive FROM gd_galaxy_state WHERE galaxy = 1;"
        ).fetchone()
        assert row is not None
        assert row["primary_directive"] == FALLBACK_PRIMARY
    finally:
        conn.close()


def test_ensure_galaxy_state_idempotent(gd_db):
    conn = db()
    try:
        first = ensure_galaxy_state(2, conn=conn)
        second = ensure_galaxy_state(2, conn=conn)
        assert first["galaxy"] == second["galaxy"] == 2
        assert first["primary_directive"] == second["primary_directive"]

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM gd_galaxy_state WHERE galaxy = 2;"
        ).fetchone()["c"]
        assert int(count) == 1
    finally:
        conn.close()


def test_get_active_directives_fallback_on_missing_state(gd_db):
    conn = db()
    try:
        before = conn.execute("SELECT COUNT(*) AS c FROM gd_galaxy_state;").fetchone()["c"]
    finally:
        conn.close()
    payload = get_active_directives_for_galaxy(1)
    assert payload is not None
    assert payload["galaxy"] == 1
    assert payload["primary"] == FALLBACK_PRIMARY
    assert payload["secondary"] is None
    assert payload["source"] == "fallback"
    assert payload["primary_definition"] is not None
    assert payload["primary_definition"]["directive_key"] == FALLBACK_PRIMARY
    assert payload["secondary_definition"] is None
    conn = db()
    try:
        after = conn.execute("SELECT COUNT(*) AS c FROM gd_galaxy_state;").fetchone()["c"]
        assert int(after) == int(before)
    finally:
        conn.close()


def test_get_active_directives_reads_persisted_state(gd_db):
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO gd_galaxy_state (
                galaxy, primary_directive, secondary_directive, consecutive_primary_wins, updated_at
            ) VALUES (1, 'scientific', 'logistics', 0, 0);
            """
        )
        conn.commit()

        payload = get_active_directives_for_galaxy(1, conn=conn)
        assert payload is not None
        assert payload["primary"] == "scientific"
        assert payload["secondary"] == "logistics"
        assert payload["source"] == "state"
        assert payload["primary_definition"]["directive_key"] == "scientific"
        assert payload["secondary_definition"]["directive_key"] == "logistics"
    finally:
        conn.close()


def test_get_active_directives_invalid_stored_keys_fallback(gd_db):
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO gd_galaxy_state (
                galaxy, primary_directive, secondary_directive, consecutive_primary_wins, updated_at
            ) VALUES (1, 'not_a_real_directive', 'also_bogus', 0, 0);
            """
        )
        conn.commit()

        payload = get_active_directives_for_galaxy(1, conn=conn)
        assert payload is not None
        assert payload["primary"] == FALLBACK_PRIMARY
        assert payload["secondary"] is None
        assert payload["source"] == "fallback"
    finally:
        conn.close()


def test_get_active_directives_invalid_galaxy_returns_none(gd_db):
    assert get_active_directives_for_galaxy(0) is None
    assert get_active_directives_for_galaxy(99) is None


def test_list_active_directives_for_galaxies(gd_db):
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('galaxy_count', '5');"
        )
        conn.execute(
            """
            INSERT INTO gd_galaxy_state (
                galaxy, primary_directive, secondary_directive, consecutive_primary_wins, updated_at
            ) VALUES (2, 'military', NULL, 0, 0);
            """
        )
        conn.commit()

        result = list_active_directives_for_galaxies([1, 2, 0, 99], conn=conn)
        assert set(result.keys()) == {1, 2}
        assert result[1]["primary"] == FALLBACK_PRIMARY
        assert result[1]["source"] == "fallback"
        assert result[2]["primary"] == "military"
        assert result[2]["secondary"] is None
        assert result[2]["source"] == "state"
    finally:
        conn.close()


def test_scale_numeric_mechanics_multiplicative_and_additive(gd_db):
    mechanics = {
        "effect_resolver": {
            "metal_prod_factor": 1.20,
            "weapon_bonus": 0.20,
        },
        "queue_limits": {"research": 1},
        "unlocks": ["unlock:world:test"],
        "flags": {"expedition_loot_mult": 2.0},
    }
    scaled = scale_numeric_mechanics(mechanics, SECONDARY_SCALE)
    assert scaled["effect_resolver"]["metal_prod_factor"] == pytest.approx(1.08)
    assert scaled["effect_resolver"]["weapon_bonus"] == pytest.approx(0.08)
    assert scaled["queue_limits"]["research"] == 1
    assert scaled["unlocks"] == ["unlock:world:test"]
    assert scaled["flags"]["expedition_loot_mult"] == pytest.approx(1.4)


def test_merge_mechanics_numeric_rules(gd_db):
    primary = {"effect_resolver": {"metal_prod_factor": 1.20, "weapon_bonus": 0.20}}
    secondary = {"effect_resolver": {"metal_prod_factor": 1.08, "weapon_bonus": 0.08}}
    merged = merge_mechanics(primary, secondary)
    assert merged["effect_resolver"]["metal_prod_factor"] == pytest.approx(1.28)
    assert merged["effect_resolver"]["weapon_bonus"] == pytest.approx(0.28)


def test_merge_mechanics_primary_wins_non_numeric(gd_db):
    primary = {"unlocks": ["unlock:primary"]}
    secondary = {"unlocks": ["unlock:secondary"]}
    merged = merge_mechanics(primary, secondary)
    assert merged["unlocks"] == ["unlock:primary"]


def test_get_galaxy_directive_mechanics_primary_only(gd_db):
    payload = get_galaxy_directive_mechanics(1)
    assert payload is not None
    assert payload["galaxy"] == 1
    assert payload["primary"] == FALLBACK_PRIMARY
    assert payload["secondary"] is None
    assert payload["sources"] == [f"primary:{FALLBACK_PRIMARY}"]
    assert "effect_resolver" in payload["mechanics"]


def test_get_galaxy_directive_mechanics_primary_secondary_custom(gd_db):
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO gd_galaxy_state (
                galaxy, primary_directive, secondary_directive, consecutive_primary_wins, updated_at
            ) VALUES (1, 'scientific', 'logistics', 0, 0);
            """
        )
        conn.commit()

        payload = get_galaxy_directive_mechanics(1, conn=conn)
        assert payload is not None
        assert payload["primary"] == "scientific"
        assert payload["secondary"] == "logistics"
        assert payload["sources"] == ["primary:scientific", "secondary:logistics:custom"]
        er = payload["mechanics"]["effect_resolver"]
        assert er["research_time_speed"] == pytest.approx(1.25)
        assert er["cargo_multiplier"] == pytest.approx(1.20)
    finally:
        conn.close()


def test_get_galaxy_directive_mechanics_secondary_scaled_fallback(gd_db):
    conn = db()
    try:
        conn.execute(
            """
            UPDATE gd_directive_definitions
            SET secondary_mechanics_json = '{}'
            WHERE directive_key = 'logistics';
            """
        )
        conn.execute(
            """
            INSERT INTO gd_galaxy_state (
                galaxy, primary_directive, secondary_directive, consecutive_primary_wins, updated_at
            ) VALUES (1, 'defensive', 'logistics', 0, 0);
            """
        )
        conn.commit()

        from game.galactic_directives.definitions import reload_definitions

        reload_definitions(conn=conn)

        payload = get_galaxy_directive_mechanics(1, conn=conn)
        assert payload is not None
        assert payload["secondary"] == "logistics"
        assert payload["sources"] == ["primary:defensive", "secondary:logistics:scaled"]
        assert payload["mechanics"]["effect_resolver"]["cargo_multiplier"] == pytest.approx(1.20)
    finally:
        conn.close()


def test_get_galaxy_directive_mechanics_invalid_galaxy(gd_db):
    assert get_galaxy_directive_mechanics(0) is None
    assert get_galaxy_directive_mechanics(99) is None


def test_build_galactic_directive_banner_bootstraps_defensive(gd_db):
    conn = db()
    try:
        banner = build_galactic_directive_banner(1, conn=conn)
        assert banner["visible"] is True
        assert banner["galaxy"] == 1
        assert banner["primary"]["key"] == FALLBACK_PRIMARY
        assert banner["primary"]["label_key"] == "gd_dir_defensive_title"
        assert banner["secondary"] is None
        assert banner["source"] == "fallback"
    finally:
        conn.close()


def test_build_galactic_directive_banner_with_secondary(gd_db):
    conn = db()
    try:
        ensure_galaxy_state(1, conn=conn)
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'industrial', secondary_directive = 'scientific'
            WHERE galaxy = 1;
            """
        )
        conn.commit()

        banner = build_galactic_directive_banner(1, conn=conn)
        assert banner["visible"] is True
        assert banner["primary"]["key"] == "industrial"
        assert banner["secondary"]["key"] == "scientific"
        assert banner["source"] == "state"
    finally:
        conn.close()


def test_get_directive_flags_for_galaxy_exploration(gd_db):
    conn = db()
    try:
        ensure_galaxy_state(1, conn=conn)
        conn.execute(
            "UPDATE gd_galaxy_state SET primary_directive = 'exploration' WHERE galaxy = 1;"
        )
        conn.commit()
        from game.galactic_directives.mechanics import get_directive_flags_for_galaxy

        flags = get_directive_flags_for_galaxy(1, conn=conn)
        assert flags["expedition_loot_mult"] == pytest.approx(2.0)
        assert flags["expedition_event_bonus"] == pytest.approx(0.30)
    finally:
        conn.close()


def test_resolve_expedition_outcome_applies_loot_mult(gd_db):
    from game.expedition_events import resolve_expedition_outcome

    base = resolve_expedition_outcome(
        1,
        cargo_total=500_000,
        expedition_ship_count=3,
        flight_seconds=120,
        directive_flags={"expedition_loot_mult": 1.0},
    )
    boosted = resolve_expedition_outcome(
        1,
        cargo_total=500_000,
        expedition_ship_count=3,
        flight_seconds=120,
        directive_flags={"expedition_loot_mult": 2.0},
    )
    if int(base.get("reward_total") or 0) > 0:
        assert int(boosted.get("reward_total") or 0) == int(base["reward_total"]) * 2


def test_build_galactic_directive_banner_invalid_galaxy(gd_db):
    assert build_galactic_directive_banner(0)["visible"] is False
    assert build_galactic_directive_banner(99)["visible"] is False


# --- GC-720G voting cycle ---

import uuid

from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
from game.galactic_directives.voting import (
    PHASE_ACTIVE,
    PHASE_RESOLVED,
    PHASE_VOTE_OPEN,
    _cycle_timestamps,
    get_or_create_current_cycle,
    get_vote_phase,
    resolve_directive_cycle,
    submit_directive_vote,
)


def _gd_player(conn):
    ok, err, user = create_user(f"gd_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Voter", conn=conn)
    conn.commit()
    return uid


def _gd_player_galaxy(uid: int, conn) -> int:
    planets = get_planets_by_player(uid, conn=conn)
    assert planets
    return int(planets[0]["galaxy"])


def _gd_place_in_galaxy(uid: int, galaxy: int, conn) -> None:
    """Ensure the player's colonies count for votes in ``galaxy`` (test fixture)."""
    conn.execute(
        "UPDATE planets SET galaxy = ? WHERE player_id = ?;",
        (int(galaxy), int(uid)),
    )
    conn.commit()


def _gd_vote_open_now(year: int = 2026, month: int = 6) -> int:
    stamps = _cycle_timestamps(year, month)
    return int(stamps["vote_start_at"]) + 3600


def test_galactic_politics_js_formats_galaxy_title():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert 'tf("gd_politics_galaxy_title"' in src or "tf('gd_politics_galaxy_title'" in src
    assert 't("gd_politics_galaxy_title", "Galaxie %(galaxy)s", { galaxy })' not in src

    stamps = _cycle_timestamps(2026, 6)
    cycle = {"vote_end_at": stamps["vote_end_at"], "effect_end_at": stamps["effect_end_at"]}
    assert get_vote_phase(cycle, stamps["vote_start_at"]) == PHASE_VOTE_OPEN
    assert get_vote_phase(cycle, stamps["vote_end_at"]) == PHASE_VOTE_OPEN
    assert get_vote_phase(cycle, stamps["effect_start_at"]) == PHASE_ACTIVE
    assert get_vote_phase(cycle, stamps["effect_end_at"]) == PHASE_ACTIVE
    assert get_vote_phase(cycle, stamps["effect_end_at"] + 1) == PHASE_RESOLVED
    # Mid-month (e.g. launch day) must still be vote_open under full-month schedule.
    mid = stamps["vote_start_at"] + 20 * 86400
    assert mid < stamps["vote_end_at"]
    assert get_vote_phase(cycle, mid) == PHASE_VOTE_OPEN


def test_galactic_politics_clarity_guide_and_human_bloc_labels():
    """UI must teach the 3 layers via tabs and never fall back to raw *_bloc keys."""
    import json

    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "_gdGuideStripHtml" in src
    assert "data-gd-tab" in src
    assert "data-gd-tab-panel" in src
    assert "_gdStatusStripHtml" in src
    assert "_gdSetGalaxyTab" in src
    assert "_gdPoliticsImgTag" in src
    assert "gp-option-banner" in src
    assert "gp-bloc-btn-grid" in src
    assert "_gdVoteCountLabel" in src
    assert "gd_politics_mandate_votes_one" in src
    assert "_gdBlocFallbackName" in src
    assert "/_bloc$/i.test(translated)" in src
    assert "gp-live-effects" in src
    assert "gd_politics_stance_help" in src
    assert "gp-stance" in src
    assert "_gdEffectChipsHtml" in src
    assert "gd_politics_resolution_option_days" in src
    assert "Abstimmung starten" in src
    assert "gp-chamber" in src
    assert "gp-faction-tile" in src
    assert "gp-badge-stance" in src
    # Propose dropdown: title + duration only — no effect chips baked into <option>.
    assert ".slice(0, 2)" not in src.split("data-gd-resolution-propose")[1][:800]

    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "minmax(220px, 1fr)" in css
    assert "text-overflow: ellipsis" in css
    assert "gp-bloc-btn-grid" in css
    assert "gp-option-banner" in css
    assert "chamber_backdrop.webp" in css
    assert css.count("chamber_backdrop") == 1
    assert "gp-live-effects" in css
    assert "gp-chamber" in css
    assert "gp-faction-tile" in css

    required = [
        "gd_politics_hint",
        "gd_politics_guide_now",
        "gd_politics_guide_politics",
        "gd_politics_guide_vote",
        "gd_politics_badge_not_voted",
        "gd_politics_badge_resolution",
        "gd_politics_badge_emergency",
        "gd_politics_mandate_votes_one",
        "gd_politics_mandate_votes",
        "gd_politics_live_kicker",
        "gd_politics_stance_help",
        "gd_politics_stance_military",
        "gd_politics_badge_stance",
        "gd_politics_live_mandate_only",
        "gd_fx_gate_control_active",
        "gd_fx_ban_directive_cycles",
        "gd_fx_directive_boost_mult",
        "gd_fx_trigger_emergency_session",
        "gd_fx_bloc_vote_weight_mult",
        "gd_fx_trader_daily_limit_mult",
        "gd_politics_resolution_propose_btn",
        "gd_politics_resolution_option_days",
        "gdp_bloc_military_title",
        "gdp_bloc_scientific_title",
        "gdp_bloc_industrial_title",
        "gdp_bloc_frontier_title",
        "gdp_bloc_neutral_title",
    ]
    for locale in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        for key in required:
            assert key in data, f"missing {key} in {locale}.json"
            assert not str(data[key]).endswith("_bloc"), f"raw bloc key in {locale}:{key}"
        assert len(data["gd_politics_stance_help"]) > 20


def test_galactic_politics_sigil_art_pack_exists():
    """Senate immersion: optimized PNG + WebP siblings; SVG remains fallback."""
    base = ROOT / "static" / "img" / "politics"
    required = [
        ("chamber/chamber_backdrop", 200_000, 100_000),
        ("chamber/senate_hero", 150_000, 60_000),
        ("chamber/tab_now", 40_000, 16_000),
        ("chamber/tab_politics", 40_000, 16_000),
        ("chamber/tab_vote", 40_000, 16_000),
        ("chamber/mandate_ring", 40_000, 16_000),
        ("chamber/resolution_mark", 40_000, 16_000),
        ("directives/industrial", 160_000, 80_000),
        ("directives/scientific", 160_000, 80_000),
        ("directives/military", 160_000, 80_000),
        ("directives/logistics", 160_000, 80_000),
        ("directives/defensive", 160_000, 80_000),
        ("directives/expansion", 160_000, 80_000),
        ("directives/exploration", 160_000, 80_000),
        ("blocs/military_bloc", 40_000, 16_000),
        ("blocs/scientific_bloc", 40_000, 16_000),
        ("blocs/industrial_bloc", 40_000, 16_000),
        ("blocs/frontier_bloc", 40_000, 16_000),
        ("blocs/neutral_bloc", 40_000, 16_000),
    ]
    for stem, png_budget, webp_budget in required:
        png = base / f"{stem}.png"
        webp = base / f"{stem}.webp"
        assert png.is_file(), f"missing art {stem}.png"
        assert webp.is_file(), f"missing art {stem}.webp"
        assert 1000 < png.stat().st_size <= png_budget, f"png budget {stem}: {png.stat().st_size}"
        assert 500 < webp.stat().st_size <= webp_budget, f"webp budget {stem}: {webp.stat().st_size}"

    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "preferWebpStaticUrl" in src.split("function _gdPoliticsImgTag")[1].split("function _gdSealHtml")[0]
    assert 'kind === "personalities"' in src.split("function _gdPoliticsImg(")[1].split("function _gdPoliticsImgTag")[0]


def test_get_or_create_reopens_empty_mid_month_cycle(gd_db):
    conn = db()
    try:
        stamps = _cycle_timestamps(2026, 7)
        mid = stamps["vote_start_at"] + 25 * 86400
        # Legacy day-5 schedule already auto-resolved with zero votes.
        conn.execute(
            """
            INSERT INTO gd_cycles (
                galaxy, year, month,
                vote_start_at, vote_end_at, effect_start_at, effect_end_at,
                status, winning_primary, total_votes, total_voters,
                created_at, updated_at
            ) VALUES (1, 2026, 7, ?, ?, ?, ?, 'active', 'defensive', 0, 0, ?, ?);
            """,
            (
                stamps["vote_start_at"],
                stamps["vote_start_at"] + 4 * 86400,
                stamps["vote_start_at"] + 5 * 86400,
                stamps["vote_end_at"],
                mid,
                mid,
            ),
        )
        conn.commit()
        cycle = get_or_create_current_cycle(1, now=mid, conn=conn)
        assert cycle is not None
        assert cycle.get("winning_primary") in (None, "")
        assert get_vote_phase(cycle, mid) == PHASE_VOTE_OPEN
        assert int(cycle["vote_end_at"]) == int(stamps["vote_end_at"])
    finally:
        conn.close()


def test_get_or_create_current_cycle_inserts_row(gd_db):
    conn = db()
    try:
        now = _gd_vote_open_now()
        cycle = get_or_create_current_cycle(1, now=now, conn=conn)
        assert cycle is not None
        assert int(cycle["galaxy"]) == 1
        assert int(cycle["year"]) == 2026
        assert int(cycle["month"]) == 6
        assert cycle["status"] == PHASE_VOTE_OPEN
        again = get_or_create_current_cycle(1, now=now, conn=conn)
        assert int(again["id"]) == int(cycle["id"])
    finally:
        conn.close()


def test_submit_directive_vote_requires_colony(gd_db):
    conn = db()
    try:
        ok, err, user = create_user(f"gd_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok, err
        uid = int(user["id"])
        conn.execute("DELETE FROM planets WHERE player_id = ?;", (uid,))
        conn.commit()
        now = _gd_vote_open_now()
        get_or_create_current_cycle(1, now=now, conn=conn)
        result = submit_directive_vote(uid, 1, "industrial", conn=conn, now=now)
        assert result["ok"] is False
        assert result["reason"] == "no_colony"
    finally:
        conn.close()


def test_submit_directive_vote_and_change(gd_db):
    conn = db()
    try:
        uid = _gd_player(conn)
        galaxy = _gd_player_galaxy(uid, conn)
        now = _gd_vote_open_now()
        get_or_create_current_cycle(galaxy, now=now, conn=conn)

        first = submit_directive_vote(uid, galaxy, "industrial", conn=conn, now=now)
        assert first["ok"] is True
        assert first["directive"] == "industrial"

        second = submit_directive_vote(uid, galaxy, "scientific", conn=conn, now=now)
        assert second["ok"] is True
        assert second["directive"] == "scientific"

        row = conn.execute(
            """
            SELECT directive_key FROM gd_votes v
            JOIN gd_cycles c ON c.id = v.cycle_id
            WHERE v.player_id = ? AND c.galaxy = ? AND c.year = 2026 AND c.month = 6;
            """,
            (uid, galaxy),
        ).fetchone()
        assert row["directive_key"] == "scientific"
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM gd_votes WHERE player_id = ?;",
            (uid,),
        ).fetchone()["c"]
        assert int(count) == 1
    finally:
        conn.close()


def test_resolve_directive_cycle_writes_winners(gd_db):
    conn = db()
    try:
        uid_a = _gd_player(conn)
        uid_b = _gd_player(conn)
        uid_c = _gd_player(conn)
        galaxy = _gd_player_galaxy(uid_a, conn)
        _gd_place_in_galaxy(uid_b, galaxy, conn)
        _gd_place_in_galaxy(uid_c, galaxy, conn)
        now = _gd_vote_open_now()
        cycle = get_or_create_current_cycle(galaxy, now=now, conn=conn)
        assert submit_directive_vote(uid_a, galaxy, "industrial", conn=conn, now=now)["ok"]
        assert submit_directive_vote(uid_b, galaxy, "industrial", conn=conn, now=now)["ok"]
        assert submit_directive_vote(uid_c, galaxy, "scientific", conn=conn, now=now)["ok"]

        after_vote = int(cycle["vote_end_at"]) + 1
        resolved = resolve_directive_cycle(galaxy, 2026, 6, conn=conn, now=after_vote)
        assert resolved is not None
        assert resolved["winning_primary"] == "industrial"
        assert resolved["winning_secondary"] == "scientific"
        assert int(resolved["winning_primary_votes"]) == 2

        state = conn.execute(
            "SELECT primary_directive, secondary_directive FROM gd_galaxy_state WHERE galaxy = ?;",
            (galaxy,),
        ).fetchone()
        assert state["primary_directive"] == "industrial"
        assert state["secondary_directive"] == "scientific"
    finally:
        conn.close()


def test_resolve_directive_cycle_no_votes_keeps_primary(gd_db):
    conn = db()
    try:
        ensure_galaxy_state(1, conn=conn)
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'logistics', secondary_directive = 'defensive'
            WHERE galaxy = 1;
            """
        )
        conn.commit()
        now = _gd_vote_open_now()
        get_or_create_current_cycle(1, now=now, conn=conn)
        after_vote = int(_cycle_timestamps(2026, 6)["vote_end_at"]) + 1
        resolve_directive_cycle(1, 2026, 6, conn=conn, now=after_vote)
        state = conn.execute(
            "SELECT primary_directive, secondary_directive FROM gd_galaxy_state WHERE galaxy = 1;"
        ).fetchone()
        assert state["primary_directive"] == "logistics"
        assert state["secondary_directive"] == "defensive"
    finally:
        conn.close()


def test_resolve_directive_cycle_no_votes_no_state_uses_defensive(gd_db):
    conn = db()
    try:
        now = _gd_vote_open_now()
        get_or_create_current_cycle(2, now=now, conn=conn)
        after_vote = int(_cycle_timestamps(2026, 6)["vote_end_at"]) + 1
        resolve_directive_cycle(2, 2026, 6, conn=conn, now=after_vote)
        state = conn.execute(
            "SELECT primary_directive, secondary_directive FROM gd_galaxy_state WHERE galaxy = 2;"
        ).fetchone()
        assert state is not None
        assert state["primary_directive"] == FALLBACK_PRIMARY
        assert state["secondary_directive"] is None
    finally:
        conn.close()


def test_submit_directive_vote_rejects_cooldown(gd_db):
    conn = db()
    try:
        uid = _gd_player(conn)
        galaxy = _gd_player_galaxy(uid, conn)
        now = _gd_vote_open_now()
        ensure_galaxy_state(galaxy, conn=conn)
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET cooldown_directive = 'military', cooldown_until_ym = '202606'
            WHERE galaxy = ?;
            """,
            (galaxy,),
        )
        conn.commit()
        get_or_create_current_cycle(galaxy, now=now, conn=conn)
        result = submit_directive_vote(uid, galaxy, "military", conn=conn, now=now)
        assert result["ok"] is False
        assert result["reason"] == "cooldown"
    finally:
        conn.close()


def test_resolve_directive_cycle_tie_breaks_primary(gd_db, monkeypatch):
    conn = db()
    try:
        uid_a = _gd_player(conn)
        uid_b = _gd_player(conn)
        galaxy = _gd_player_galaxy(uid_a, conn)
        _gd_place_in_galaxy(uid_b, galaxy, conn)
        now = _gd_vote_open_now()
        get_or_create_current_cycle(galaxy, now=now, conn=conn)
        assert submit_directive_vote(uid_a, galaxy, "industrial", conn=conn, now=now)["ok"]
        assert submit_directive_vote(uid_b, galaxy, "scientific", conn=conn, now=now)["ok"]
        monkeypatch.setattr("game.galactic_directives.voting.random.choice", lambda xs: xs[0])
        after_vote = int(_cycle_timestamps(2026, 6)["vote_end_at"]) + 1
        resolved = resolve_directive_cycle(galaxy, 2026, 6, conn=conn, now=after_vote)
        assert resolved["winning_primary"] in ("industrial", "scientific")
        assert int(resolved["is_tie_primary"]) == 1
    finally:
        conn.close()


def test_get_galaxy_directive_mechanics_after_resolution(gd_db):
    conn = db()
    try:
        uid = _gd_player(conn)
        galaxy = _gd_player_galaxy(uid, conn)
        now = _gd_vote_open_now()
        get_or_create_current_cycle(galaxy, now=now, conn=conn)
        submit_directive_vote(uid, galaxy, "scientific", conn=conn, now=now)
        after_vote = int(_cycle_timestamps(2026, 6)["vote_end_at"]) + 1
        resolve_directive_cycle(galaxy, 2026, 6, conn=conn, now=after_vote)
        payload = get_galaxy_directive_mechanics(galaxy, conn=conn)
        assert payload is not None
        assert payload["primary"] == "scientific"
    finally:
        conn.close()


# --- GC-720I cron resolve + admin force ---

from game.galactic_directives.voting import (
    admin_force_directive,
    admin_unforce_directive,
    resolve_due_cycles,
)


def test_resolve_due_cycles_resolves_overdue_without_votes(gd_db):
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('galaxy_count', '1');"
        )
        conn.commit()
        now = _gd_vote_open_now()
        cycle = get_or_create_current_cycle(1, now=now, conn=conn)
        after_vote = int(cycle["vote_end_at"]) + 1
        result = resolve_due_cycles(conn=conn, now=after_vote)
        assert result["ok"] is True
        assert result["galaxies"] == 1
        state = conn.execute(
            "SELECT primary_directive FROM gd_galaxy_state WHERE galaxy = 1;"
        ).fetchone()
        assert state is not None
        assert state["primary_directive"] == FALLBACK_PRIMARY
        refreshed = conn.execute(
            "SELECT winning_primary FROM gd_cycles WHERE id = ?;",
            (int(cycle["id"]),),
        ).fetchone()
        assert refreshed["winning_primary"] == FALLBACK_PRIMARY
    finally:
        conn.close()


def test_admin_force_and_unforce_directive(gd_db):
    conn = db()
    try:
        now = _gd_vote_open_now()
        get_or_create_current_cycle(1, now=now, conn=conn)

        forced = admin_force_directive(
            1, "military", "logistics", conn=conn, now=now
        )
        assert forced["ok"] is True
        assert forced["primary"] == "military"
        assert forced["secondary"] == "logistics"
        state = conn.execute(
            "SELECT primary_directive, secondary_directive FROM gd_galaxy_state WHERE galaxy = 1;"
        ).fetchone()
        assert state["primary_directive"] == "military"
        assert state["secondary_directive"] == "logistics"
        cycle = conn.execute(
            "SELECT winning_primary, status, vote_end_at FROM gd_cycles WHERE galaxy = 1 AND year = 2026 AND month = 6;"
        ).fetchone()
        assert cycle["winning_primary"] == "military"
        assert int(cycle["vote_end_at"]) <= now

        opened = admin_unforce_directive(1, reset_state=True, conn=conn, now=now)
        assert opened["ok"] is True
        cycle2 = conn.execute(
            "SELECT winning_primary, status FROM gd_cycles WHERE galaxy = 1 AND year = 2026 AND month = 6;"
        ).fetchone()
        assert cycle2["winning_primary"] is None
        assert cycle2["status"] == PHASE_VOTE_OPEN
        state2 = conn.execute(
            "SELECT primary_directive, secondary_directive FROM gd_galaxy_state WHERE galaxy = 1;"
        ).fetchone()
        assert state2["primary_directive"] == FALLBACK_PRIMARY
        assert state2["secondary_directive"] is None
    finally:
        conn.close()


# --- GC-720G results messages ---

from game.galactic_directives.results import maybe_broadcast_cycle_results


def test_maybe_broadcast_cycle_results_idempotent(gd_db):
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('galaxy_count', '1');"
        )
        conn.commit()
        uid = _gd_player(conn)
        now = _gd_vote_open_now()
        get_or_create_current_cycle(1, now=now, conn=conn)
        submit_directive_vote(uid, 1, "industrial", conn=conn, now=now)
        after_vote = int(_cycle_timestamps(2026, 6)["vote_end_at"]) + 1
        resolve_directive_cycle(1, 2026, 6, conn=conn, now=after_vote)

        first = maybe_broadcast_cycle_results(2026, 6, conn=conn, now=after_vote)
        # resolve_directive_cycle may already have sent; accept either first send or already_sent
        assert first["ok"] is True
        if first.get("sent"):
            assert int(first.get("delivered") or 0) >= 1
        else:
            assert first.get("reason") == "already_sent"

        second = maybe_broadcast_cycle_results(2026, 6, conn=conn, now=after_vote)
        assert second["ok"] is True
        assert second.get("sent") is False
        assert second.get("reason") == "already_sent"

        sent_flag = conn.execute(
            "SELECT results_sent FROM gd_cycles WHERE galaxy = 1 AND year = 2026 AND month = 6;"
        ).fetchone()["results_sent"]
        assert int(sent_flag) == 1

        msgs = conn.execute(
            """
            SELECT subject, metadata_json FROM player_messages
            WHERE recipient_player_id = ? AND metadata_json LIKE '%gd_results%';
            """,
            (uid,),
        ).fetchall()
        assert len(msgs) == 1
        assert "2026" in msgs[0]["subject"]
    finally:
        conn.close()


# --- GC-720J domain flags ---

from game.galactic_directives.mechanics import get_directive_queue_limit_bonus
from game.research import _resolve_research_queue_limit
from game.scrapyard import scrap_value_for_ship


def test_directive_queue_limit_and_flags_wired(gd_db):
    conn = db()
    try:
        ensure_galaxy_state(1, conn=conn)
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'scientific', secondary_directive = NULL
            WHERE galaxy = 1;
            """
        )
        conn.commit()
        assert get_directive_queue_limit_bonus(1, "research", conn=conn) == 1

        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'expansion', secondary_directive = NULL
            WHERE galaxy = 1;
            """
        )
        conn.commit()
        from game.galactic_directives.mechanics import get_directive_flags_for_galaxy

        flags = get_directive_flags_for_galaxy(1, conn=conn)
        assert int(flags.get("max_colonies_bonus") or 0) == 1
        assert float(flags.get("colonize_cost_mult") or 1.0) == 0.70

        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'logistics', secondary_directive = NULL
            WHERE galaxy = 1;
            """
        )
        conn.commit()
        flags = get_directive_flags_for_galaxy(1, conn=conn)
        assert float(flags.get("trader_daily_limit_mult") or 1.0) == 1.50
        assert float(flags.get("scrapyard_yield_mult") or 1.0) == 1.20
        base = scrap_value_for_ship("light_fighter", 10, ratio=0.5, yield_mult=1.0)
        boosted = scrap_value_for_ship("light_fighter", 10, ratio=0.5, yield_mult=1.20)
        assert boosted["metal"] >= base["metal"]

        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'defensive', secondary_directive = NULL
            WHERE galaxy = 1;
            """
        )
        conn.commit()
        flags = get_directive_flags_for_galaxy(1, conn=conn)
        assert float(flags.get("defense_combat_mult") or 0.0) == 0.10
    finally:
        conn.close()


def test_research_queue_limit_includes_directive_bonus(gd_db):
    conn = db()
    try:
        uid = _gd_player(conn)
        galaxy = _gd_player_galaxy(uid, conn)
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'scientific', secondary_directive = NULL
            WHERE galaxy = ?;
            """,
            (galaxy,),
        )
        conn.commit()
        ensure_galaxy_state(galaxy, conn=conn)
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'scientific', secondary_directive = NULL
            WHERE galaxy = ?;
            """,
            (galaxy,),
        )
        conn.commit()
        base = _resolve_research_queue_limit(player_id=None, conn=conn)
        with_bonus = _resolve_research_queue_limit(player_id=uid, conn=conn)
        assert with_bonus >= base + 1
    finally:
        conn.close()


def test_politics_state_exposes_mandate_and_chronicle(gd_db):
    """GC-POL-00: during a new vote, players see the prior election mandate + chronicle."""
    from game.galactic_directives.voting import (
        build_galaxy_politics_entry,
        get_galactic_politics_state,
    )

    conn = db()
    try:
        uid = _gd_player(conn)
        galaxy = _gd_player_galaxy(uid, conn)
        _gd_place_in_galaxy(uid, galaxy, conn)

        july = _cycle_timestamps(2026, 7)
        august = _cycle_timestamps(2026, 8)
        # Prior election (July vote → August mandate window)
        conn.execute(
            """
            INSERT INTO gd_cycles (
                galaxy, year, month,
                vote_start_at, vote_end_at, effect_start_at, effect_end_at,
                status, winning_primary, winning_secondary,
                winning_primary_votes, winning_secondary_votes,
                total_votes, total_voters, is_tie_primary, is_tie_secondary,
                results_sent, created_at, updated_at
            ) VALUES (
                ?, 2026, 7, ?, ?, ?, ?, 'active',
                'military', 'logistics', 12, 7, 19, 15, 0, 0, 1, ?, ?
            );
            """,
            (
                galaxy,
                july["vote_start_at"],
                july["vote_end_at"],
                july["effect_start_at"],
                july["effect_end_at"],
                july["effect_start_at"],
                july["effect_start_at"],
            ),
        )
        conn.execute(
            """
            INSERT INTO gd_cycles (
                galaxy, year, month,
                vote_start_at, vote_end_at, effect_start_at, effect_end_at,
                status, winning_primary, winning_secondary,
                winning_primary_votes, winning_secondary_votes,
                total_votes, total_voters, created_at, updated_at
            ) VALUES (
                ?, 2026, 6, ?, ?, ?, ?, 'resolved',
                'scientific', 'defensive', 9, 4, 13, 11, ?, ?
            );
            """,
            (
                galaxy,
                _cycle_timestamps(2026, 6)["vote_start_at"],
                _cycle_timestamps(2026, 6)["vote_end_at"],
                _cycle_timestamps(2026, 6)["effect_start_at"],
                _cycle_timestamps(2026, 6)["effect_end_at"],
                _cycle_timestamps(2026, 6)["effect_start_at"],
                _cycle_timestamps(2026, 6)["effect_start_at"],
            ),
        )
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = 'military',
                secondary_directive = 'logistics',
                last_cycle_id = (
                    SELECT id FROM gd_cycles WHERE galaxy = ? AND year = 2026 AND month = 7
                )
            WHERE galaxy = ?;
            """,
            (galaxy, galaxy),
        )
        conn.commit()

        # Mid-August: new vote open, July mandate still in force
        now = august["vote_start_at"] + 3 * 86400
        entry = build_galaxy_politics_entry(uid, galaxy, conn=conn, now=now)

        assert entry["cycle"]["phase"] == PHASE_VOTE_OPEN
        assert entry["cycle"]["month"] == 8
        mandate = entry["mandate"]
        assert mandate["in_force"] is True
        assert mandate["primary"] == "military"
        assert mandate["secondary"] == "logistics"
        assert mandate["election_year"] == 2026
        assert mandate["election_month"] == 7
        assert mandate["effect_year"] == 2026
        assert mandate["effect_month"] == 8
        assert mandate["primary_votes"] == 12
        assert mandate["total_voters"] == 15
        assert mandate["primary_monogram"] == "MIL"
        assert mandate["countdown_seconds"] > 0

        chronicle = entry["chronicle"]
        assert len(chronicle) >= 2
        assert chronicle[0]["primary"] == "military"
        assert chronicle[0]["in_force"] is True
        assert chronicle[1]["primary"] == "scientific"
        assert chronicle[1]["election_month"] == 6

        state = get_galactic_politics_state(uid, conn=conn, now=now)
        assert state["ready"] is True
        assert state["galaxies"][0]["mandate"]["primary"] == "military"
        assert len(state["galaxies"][0]["chronicle"]) >= 2
    finally:
        conn.close()


def test_politics_state_includes_diplomacy_and_vote_share(gd_db):
    from game.galactic_directives.voting import build_galaxy_politics_entry

    conn = db()
    try:
        uid = _gd_player(conn)
        galaxy = _gd_player_galaxy(uid, conn)
        now = _gd_vote_open_now(2026, 8)
        entry = build_galaxy_politics_entry(uid, galaxy, conn=conn, now=now)
        assert "diplomacy" in entry
        assert "mandate" in entry
        assert "chronicle" in entry
        assert isinstance(entry["options"], list)
        for opt in entry["options"]:
            assert "vote_share" in opt
            assert "monogram" in opt
            assert "tradeoffs" in opt
            for chip in opt["tradeoffs"]:
                assert "label_key" in chip
                assert "display" in chip
                assert "mine_energy_factor" not in str(chip.get("display"))
        assert entry["cycle"].get("effect_year") is not None
        assert entry["cycle"].get("effect_month") is not None
        # Vote month August → effect September
        assert int(entry["cycle"]["month"]) == 8
        assert int(entry["cycle"]["effect_month"]) == 9
    finally:
        conn.close()


def test_politics_js_renders_mandate_rail_and_chronicle():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "_gdMandateRailHtml" in src
    assert "_gdChronicleHtml" in src
    assert "_gdDiplomacyRailHtml" in src
    assert "gd_politics_mandate_kicker" in src
    assert "data-gd-mandate-rail" in src
    assert "data-gd-chronicle" in src
    assert "data-gd-bloc-btn" in src
    assert "/api/galactic-politics/resolution/vote" in src
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert ".gp-mandate-rail" in css
    assert ".gp-chronicle-list" in css
    assert ".gp-emergency-theater" in css

