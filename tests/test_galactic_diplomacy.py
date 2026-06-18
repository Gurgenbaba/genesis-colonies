"""GC-721B — Galactic diplomacy definitions and schema."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db, table_exists
from game.galactic_diplomacy import (
    BLOC_KEYS,
    EMERGENCY_KEYS,
    PERSONALITY_KEYS,
    RESOLUTION_KEYS,
    clear_active_emergency,
    clear_active_resolution,
    clear_alliance_bloc,
    ensure_galaxy_personality_state,
    get_active_emergency,
    get_active_resolution,
    get_alliance_bloc,
    get_bloc_definition,
    get_emergency_definition,
    get_galaxy_diplomacy_mechanics,
    get_galaxy_personality,
    get_personality_definition,
    get_resolution_definition,
    infer_personality_key,
    list_active_emergencies,
    list_active_resolutions,
    list_alliance_blocs_for_galaxy,
    list_bloc_definitions,
    list_emergency_definitions,
    list_personality_definitions,
    list_resolution_definitions,
    merge_diplomacy_mechanics,
    normalize_bloc_key,
    normalize_emergency_key,
    normalize_galaxy,
    normalize_personality_key,
    normalize_resolution_key,
    reload_definitions,
    reload_emergency_definitions,
    reload_resolution_definitions,
    schema_ready,
    score_directive_history,
    set_active_emergency,
    set_active_resolution,
    set_alliance_bloc,
    set_galaxy_personality,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gdp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "galactic_diplomacy.db"
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
    reload_definitions()
    reload_resolution_definitions()
    reload_emergency_definitions()
    yield db_file


def test_migration_creates_tables(gdp_db):
    conn = db()
    try:
        assert table_exists(conn, "gd_bloc_definitions")
        assert table_exists(conn, "gd_alliance_blocs")
        assert table_exists(conn, "gd_resolution_definitions")
        assert table_exists(conn, "gd_emergency_definitions")
        assert table_exists(conn, "gd_galaxy_personality_definitions")
        assert table_exists(conn, "gd_galaxy_personality_state")
        assert table_exists(conn, "gd_resolution_state")
        assert table_exists(conn, "gd_emergency_state")
        assert schema_ready(conn=conn)
    finally:
        conn.close()


def test_migration_idempotent(gdp_db):
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(gdp_db)
    second = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert second.returncode == 0, second.stderr or second.stdout
    assert "Alle Migrationen sind bereits angewendet" in second.stdout


def test_bloc_definition_seeds(gdp_db):
    blocs = list_bloc_definitions()
    assert len(blocs) == len(BLOC_KEYS)
    keys = {b["bloc_key"] for b in blocs}
    assert keys == set(BLOC_KEYS)

    scientific = get_bloc_definition("scientific_bloc")
    assert scientific is not None
    assert scientific["label_key"] == "gdp_bloc_scientific_title"
    assert "scientific" in scientific.get("affinity_directives", [])


def test_personality_definition_seeds(gdp_db):
    traits = list_personality_definitions()
    assert len(traits) == len(PERSONALITY_KEYS)
    keys = {t["personality_key"] for t in traits}
    assert keys == set(PERSONALITY_KEYS)

    academia = get_personality_definition("academia_prime")
    assert academia is not None
    assert academia["mechanics"]["effect_resolver"]["research_time_speed"] == pytest.approx(1.10)
    assert academia["unlock_rules"]["min_wins"] == 4


def test_normalize_keys_reject_invalid(gdp_db):
    assert normalize_bloc_key("scientific_bloc") == "scientific_bloc"
    assert normalize_bloc_key("SCIENTIFIC_BLOC") == "scientific_bloc"
    assert normalize_bloc_key("not_a_bloc") == ""
    assert normalize_bloc_key("") == ""

    assert normalize_personality_key("academia_prime") == "academia_prime"
    assert normalize_personality_key("unknown_trait") == ""
    assert normalize_personality_key(None) == ""


def test_get_definition_returns_none_for_invalid(gdp_db):
    assert get_bloc_definition("military") is None
    assert get_personality_definition("scientific_bloc") is None


def test_normalize_galaxy_rejects_invalid(gdp_db):
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
    finally:
        conn.close()


def test_set_get_list_clear_alliance_bloc(gdp_db):
    conn = db()
    try:
        payload = set_alliance_bloc(10, 1, "scientific_bloc", conn=conn)
        assert payload["alliance_id"] == 10
        assert payload["galaxy"] == 1
        assert payload["bloc_key"] == "scientific_bloc"
        assert payload["definition"]["bloc_key"] == "scientific_bloc"
        assert payload["updated_at"] > 0

        got = get_alliance_bloc(10, 1, conn=conn)
        assert got is not None
        assert got["bloc_key"] == "scientific_bloc"

        set_alliance_bloc(20, 1, "military_bloc", conn=conn)
        listed = list_alliance_blocs_for_galaxy(1, conn=conn)
        assert len(listed) == 2
        assert {row["alliance_id"] for row in listed} == {10, 20}

        assert clear_alliance_bloc(10, 1, conn=conn) is True
        assert get_alliance_bloc(10, 1, conn=conn) is None
        assert clear_alliance_bloc(10, 1, conn=conn) is False
        assert len(list_alliance_blocs_for_galaxy(1, conn=conn)) == 1
    finally:
        conn.close()


def test_set_alliance_bloc_upsert_no_duplicate(gdp_db):
    conn = db()
    try:
        set_alliance_bloc(5, 2, "frontier_bloc", conn=conn)
        first_since = get_alliance_bloc(5, 2, conn=conn)["since_at"]
        set_alliance_bloc(5, 2, "industrial_bloc", conn=conn)
        updated = get_alliance_bloc(5, 2, conn=conn)
        assert updated["bloc_key"] == "industrial_bloc"
        assert updated["since_at"] == first_since

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM gd_alliance_blocs WHERE alliance_id = 5 AND galaxy = 2;"
        ).fetchone()
        assert int(count["c"]) == 1
    finally:
        conn.close()


def test_set_alliance_bloc_rejects_invalid(gdp_db):
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('galaxy_count', '2');"
        )
        conn.commit()

        with pytest.raises(ValueError, match="invalid_alliance_id"):
            set_alliance_bloc(0, 1, "neutral_bloc", conn=conn)

        with pytest.raises(ValueError, match="invalid_galaxy"):
            set_alliance_bloc(1, 99, "neutral_bloc", conn=conn)

        with pytest.raises(ValueError, match="invalid_bloc_key"):
            set_alliance_bloc(1, 1, "not_a_bloc", conn=conn)
    finally:
        conn.close()


def test_score_directive_history_maps_directives_to_traits():
    scores = score_directive_history(
        [
            "scientific",
            "scientific",
            "logistics",
            "scientific",
            "military",
            "industrial",
        ]
    )
    assert scores["academia_prime"] == 3
    assert scores["trade_nexus"] == 1
    assert scores["forge_of_war"] == 2
    assert scores["frontier_space"] == 0


def test_infer_personality_key_clear_winner_and_tie():
    assert infer_personality_key({"academia_prime": 4, "forge_of_war": 2}) == "academia_prime"
    assert infer_personality_key({"academia_prime": 3, "forge_of_war": 3}) == ""
    assert infer_personality_key({}) == ""
    assert infer_personality_key({"academia_prime": 0}) == ""


def test_ensure_get_set_galaxy_personality(gdp_db):
    conn = db()
    try:
        state = ensure_galaxy_personality_state(1, conn=conn)
        assert state["galaxy"] == 1
        assert state["personality_key"] == ""
        assert state["source"] in ("default", "state")

        row = conn.execute(
            "SELECT 1 FROM gd_galaxy_personality_state WHERE galaxy = 1;"
        ).fetchone()
        assert row is not None

        saved = set_galaxy_personality(1, "academia_prime", score=4, conn=conn)
        assert saved["personality_key"] == "academia_prime"
        assert saved["dominance_score"] == 4
        assert saved["definition"]["personality_key"] == "academia_prime"
        assert saved["active_since"] is not None

        loaded = get_galaxy_personality(1, conn=conn)
        assert loaded["personality_key"] == "academia_prime"
        assert loaded["dominance_score"] == 4

        cleared = set_galaxy_personality(1, "", conn=conn)
        assert cleared["personality_key"] == ""
        assert cleared["active_since"] is None
    finally:
        conn.close()


def test_set_galaxy_personality_rejects_invalid(gdp_db):
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('galaxy_count', '2');"
        )
        conn.commit()

        with pytest.raises(ValueError, match="invalid_galaxy"):
            set_galaxy_personality(99, "academia_prime", conn=conn)

        with pytest.raises(ValueError, match="invalid_personality_key"):
            set_galaxy_personality(1, "not_a_trait", conn=conn)
    finally:
        conn.close()


def test_scoring_infers_academia_from_scientific_history():
    history = ["scientific"] * 4 + ["logistics", "scientific"]
    scores = score_directive_history(history)
    assert infer_personality_key(scores) == "academia_prime"


def test_resolution_definition_seeds(gdp_db):
    resolutions = list_resolution_definitions()
    assert len(resolutions) == len(RESOLUTION_KEYS)
    keys = {r["resolution_key"] for r in resolutions}
    assert keys == set(RESOLUTION_KEYS)

    ban = get_resolution_definition("ban_directive")
    assert ban is not None
    assert ban["category"] == "directive_control"
    assert ban["duration_days"] == 30
    assert ban["mechanics"]["flags"]["ban_directive_cycles"] == 1


def test_normalize_resolution_key_rejects_invalid(gdp_db):
    assert normalize_resolution_key("boost_directive") == "boost_directive"
    assert normalize_resolution_key("unknown") == ""


def test_set_get_clear_active_resolution(gdp_db):
    conn = db()
    try:
        active = set_active_resolution(
            1,
            "gate_control",
            {"alliance_tag": "CTX", "world_key": "helios_gate"},
            conn=conn,
        )
        assert active["galaxy"] == 1
        assert active["resolution_key"] == "gate_control"
        assert active["definition"]["resolution_key"] == "gate_control"
        assert active["payload"]["alliance_tag"] == "CTX"
        assert active["ends_at"] is not None

        loaded = get_active_resolution(1, conn=conn)
        assert loaded is not None
        assert loaded["resolution_key"] == "gate_control"

        set_active_resolution(2, "bloc_sanction", conn=conn)
        all_active = list_active_resolutions(conn=conn)
        assert len(all_active) == 2

        assert clear_active_resolution(1, conn=conn) is True
        assert get_active_resolution(1, conn=conn) is None
        assert clear_active_resolution(1, conn=conn) is False
    finally:
        conn.close()


def test_set_active_resolution_upsert_no_duplicate(gdp_db):
    conn = db()
    try:
        set_active_resolution(3, "ban_directive", conn=conn)
        first_started = get_active_resolution(3, conn=conn)["started_at"]
        set_active_resolution(3, "boost_directive", conn=conn)
        updated = get_active_resolution(3, conn=conn)
        assert updated["resolution_key"] == "boost_directive"

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM gd_resolution_state WHERE galaxy = 3;"
        ).fetchone()
        assert int(count["c"]) == 1
        assert updated["started_at"] >= first_started
    finally:
        conn.close()


def test_set_active_resolution_rejects_invalid(gdp_db):
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('galaxy_count', '2');"
        )
        conn.commit()

        with pytest.raises(ValueError, match="invalid_galaxy"):
            set_active_resolution(99, "ban_directive", conn=conn)

        with pytest.raises(ValueError, match="invalid_resolution_key"):
            set_active_resolution(1, "not_a_resolution", conn=conn)

        with pytest.raises(ValueError, match="invalid_galaxy"):
            clear_active_resolution(0, conn=conn)
    finally:
        conn.close()


def test_emergency_definition_seeds(gdp_db):
    emergencies = list_emergency_definitions()
    assert len(emergencies) == len(EMERGENCY_KEYS)
    keys = {e["emergency_key"] for e in emergencies}
    assert keys == set(EMERGENCY_KEYS)

    war = get_emergency_definition("galaxy_war")
    assert war is not None
    assert war["category"] == "war"
    assert war["duration_days"] == 30
    assert war["mechanics"]["effect_resolver"]["weapon_bonus"] == pytest.approx(0.35)
    assert war["mechanics"]["flags"]["fleet_attack_bonus"] == pytest.approx(0.10)


def test_normalize_emergency_key_rejects_invalid(gdp_db):
    assert normalize_emergency_key("galaxy_war") == "galaxy_war"
    assert normalize_emergency_key("unknown") == ""


def test_set_get_clear_active_emergency(gdp_db):
    conn = db()
    try:
        active = set_active_emergency(
            1,
            "galaxy_war",
            {"source": "test"},
            conn=conn,
        )
        assert active["galaxy"] == 1
        assert active["emergency_key"] == "galaxy_war"
        assert active["definition"]["emergency_key"] == "galaxy_war"
        assert active["payload"]["source"] == "test"
        assert active["ends_at"] is not None

        loaded = get_active_emergency(1, conn=conn)
        assert loaded is not None
        assert loaded["emergency_key"] == "galaxy_war"

        set_active_emergency(2, "hyperstorm", conn=conn)
        all_active = list_active_emergencies(conn=conn)
        assert len(all_active) == 2

        assert clear_active_emergency(1, conn=conn) is True
        assert get_active_emergency(1, conn=conn) is None
        assert clear_active_emergency(1, conn=conn) is False
    finally:
        conn.close()


def test_set_active_emergency_upsert_no_duplicate(gdp_db):
    conn = db()
    try:
        set_active_emergency(3, "alien_invasion", conn=conn)
        first_started = get_active_emergency(3, conn=conn)["started_at"]
        set_active_emergency(3, "resource_crisis", conn=conn)
        updated = get_active_emergency(3, conn=conn)
        assert updated["emergency_key"] == "resource_crisis"

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM gd_emergency_state WHERE galaxy = 3;"
        ).fetchone()
        assert int(count["c"]) == 1
        assert updated["started_at"] >= first_started
    finally:
        conn.close()


def test_set_active_emergency_rejects_invalid(gdp_db):
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('galaxy_count', '2');"
        )
        conn.commit()

        with pytest.raises(ValueError, match="invalid_galaxy"):
            set_active_emergency(99, "galaxy_war", conn=conn)

        with pytest.raises(ValueError, match="invalid_emergency_key"):
            set_active_emergency(1, "not_an_emergency", conn=conn)

        with pytest.raises(ValueError, match="invalid_galaxy"):
            clear_active_emergency(0, conn=conn)
    finally:
        conn.close()


def test_merge_diplomacy_mechanics_numeric_rules(gdp_db):
    personality = {"effect_resolver": {"research_time_speed": 1.10, "weapon_bonus": 0.05}}
    resolution = {"effect_resolver": {"research_time_speed": 1.05, "weapon_bonus": 0.03}}
    emergency = {"effect_resolver": {"research_time_speed": 1.20, "metal_prod_factor": 0.85}}
    merged = merge_diplomacy_mechanics(personality, resolution, emergency)
    assert merged["effect_resolver"]["research_time_speed"] == pytest.approx(1.35)
    assert merged["effect_resolver"]["weapon_bonus"] == pytest.approx(0.08)
    assert merged["effect_resolver"]["metal_prod_factor"] == pytest.approx(0.85)


def test_merge_diplomacy_mechanics_earlier_wins_non_numeric(gdp_db):
    personality = {"flags": {"ban_directive_cycles": 1}}
    resolution = {"flags": {"ban_directive_cycles": 2}}
    merged = merge_diplomacy_mechanics(personality, resolution)
    assert merged["flags"]["ban_directive_cycles"] == 1


def test_get_galaxy_diplomacy_mechanics_combines_sources(gdp_db):
    conn = db()
    try:
        set_galaxy_personality(1, "academia_prime", conn=conn)
        set_active_resolution(1, "gate_control", conn=conn)
        set_active_emergency(1, "alien_invasion", conn=conn)

        payload = get_galaxy_diplomacy_mechanics(1, conn=conn)
        assert payload["galaxy"] == 1
        assert payload["sources"] == [
            {"type": "personality", "key": "academia_prime"},
            {"type": "resolution", "key": "gate_control"},
            {"type": "emergency", "key": "alien_invasion"},
        ]
        er = payload["mechanics"]["effect_resolver"]
        assert er["research_time_speed"] == pytest.approx(1.15)
        assert er["weapon_bonus"] == pytest.approx(0.25)
        assert payload["mechanics"]["flags"]["defense_combat_mult"] == pytest.approx(0.10)
    finally:
        conn.close()


def test_get_galaxy_diplomacy_mechanics_missing_sources_ok(gdp_db):
    payload = get_galaxy_diplomacy_mechanics(1)
    assert payload["galaxy"] == 1
    assert payload["mechanics"] == {}
    assert payload["sources"] == []


def test_get_galaxy_diplomacy_mechanics_invalid_galaxy_no_crash(gdp_db):
    payload = get_galaxy_diplomacy_mechanics(0)
    assert payload["galaxy"] == 0
    assert payload["mechanics"] == {}
    assert payload["sources"] == []
