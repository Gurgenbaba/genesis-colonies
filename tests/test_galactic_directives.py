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


def test_build_galactic_directive_banner_invalid_galaxy(gd_db):
    assert build_galactic_directive_banner(0)["visible"] is False
    assert build_galactic_directive_banner(99)["visible"] is False
