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
    build_galactic_diplomacy_banner,
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


def test_politics_payload_marks_blocs_as_stance_and_exposes_effects(gdp_db):
    import uuid

    from game.galactic_diplomacy.politics_surface import (
        build_bloc_landscape,
        build_diplomacy_politics_payload,
    )
    from game.galactic_diplomacy import set_galaxy_personality, set_active_resolution
    from game.models import create_user, ensure_player_and_homeworld

    conn = db()
    try:
        landscape = build_bloc_landscape(1, conn=conn, player_id=None)
        assert landscape["grants_mechanics"] is False
        assert landscape["role"] == "stance"
        for opt in landscape["options"]:
            assert opt["grants_mechanics"] is False
            assert opt["role"] == "stance"
            assert opt.get("stance_key")

        ok, err, user = create_user(f"pol_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="PolClarity", conn=conn)
        conn.commit()
        set_galaxy_personality(1, "academia_prime", conn=conn)
        set_active_resolution(1, "gate_control", conn=conn)
        conn.commit()

        payload = build_diplomacy_politics_payload(1, conn=conn, player_id=uid)
        assert payload["ready"] is True
        assert payload["blocs"]["grants_mechanics"] is False
        assert payload["personality"] is not None
        assert payload["personality"]["grants_mechanics"] is True
        assert isinstance(payload["personality"]["effects"], list)
        assert payload["personality"]["effects"], "academia should expose research chips"
        assert payload["resolution"] is not None
        assert payload["resolution"]["grants_mechanics"] is True
        assert isinstance(payload["resolution"]["effects"], list)
        gate_fx = [e for e in payload["resolution"]["effects"] if e.get("key") == "gate_control_active"]
        assert gate_fx, "gate_control should expose gate_control_active chip"
        assert gate_fx[0]["label_key"] == "gd_fx_gate_control_active"
        assert gate_fx[0]["display"] != "1"
        assert gate_fx[0]["display"] == "AKTIV"

        # Resolution flag chips must use i18n label_keys + human displays (no raw "1").
        from game.galactic_directives.voting import _serialize_tradeoff_chips

        ban = get_resolution_definition("ban_directive")
        ban_chips = _serialize_tradeoff_chips(ban["mechanics"])
        assert ban_chips[0]["key"] == "ban_directive_cycles"
        assert ban_chips[0]["label_key"] == "gd_fx_ban_directive_cycles"
        assert ban_chips[0]["display"] == "1×"

        boost = get_resolution_definition("boost_directive")
        boost_chips = _serialize_tradeoff_chips(boost["mechanics"])
        assert boost_chips[0]["key"] == "directive_boost_mult"
        assert boost_chips[0]["label_key"] == "gd_fx_directive_boost_mult"
        assert boost_chips[0]["display"] == "+20%"

        emergency = get_resolution_definition("emergency_session")
        em_chips = _serialize_tradeoff_chips(emergency["mechanics"])
        assert em_chips[0]["key"] == "trigger_emergency_session"
        assert em_chips[0]["label_key"] == "gd_fx_trigger_emergency_session"
        assert em_chips[0]["display"] == "AKTIV"

        sanction = get_resolution_definition("bloc_sanction")
        sanction_chips = _serialize_tradeoff_chips(sanction["mechanics"])
        by_key = {c["key"]: c for c in sanction_chips}
        assert by_key["bloc_vote_weight_mult"]["label_key"] == "gd_fx_bloc_vote_weight_mult"
        assert by_key["bloc_vote_weight_mult"]["display"] == "-15%"
        assert by_key["trader_daily_limit_mult"]["label_key"] == "gd_fx_trader_daily_limit_mult"
        assert by_key["trader_daily_limit_mult"]["display"] == "-10%"
    finally:
        conn.close()


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


def test_build_galactic_diplomacy_banner_empty_when_no_layers(gdp_db):
    banner = build_galactic_diplomacy_banner(1)
    assert banner["visible"] is False


def test_build_galactic_diplomacy_banner_personality_only(gdp_db):
    conn = db()
    try:
        set_galaxy_personality(1, "academia_prime", conn=conn)
        banner = build_galactic_diplomacy_banner(1, conn=conn)
        assert banner["visible"] is True
        assert banner["galaxy"] == 1
        assert banner["personality"]["key"] == "academia_prime"
        assert banner["personality"]["label_key"] == "gdp_trait_academia_prime_title"
        assert banner["resolution"] is None
        assert banner["emergency"] is None
        assert len(banner["chips"]) == 1
        assert banner["description_key"] == "gdp_trait_academia_prime_desc"
    finally:
        conn.close()


def test_build_galactic_diplomacy_banner_all_layers(gdp_db):
    conn = db()
    try:
        set_galaxy_personality(1, "forge_of_war", conn=conn)
        set_active_resolution(1, "gate_control", conn=conn)
        set_active_emergency(1, "galaxy_war", conn=conn)

        banner = build_galactic_diplomacy_banner(1, conn=conn)
        assert banner["visible"] is True
        assert banner["personality"]["key"] == "forge_of_war"
        assert banner["resolution"]["key"] == "gate_control"
        assert banner["emergency"]["key"] == "galaxy_war"
        assert [c["type"] for c in banner["chips"]] == [
            "personality",
            "resolution",
            "emergency",
        ]
        assert banner["description_key"] == "gdp_emergency_galaxy_war_desc"
    finally:
        conn.close()


def test_build_galactic_diplomacy_banner_emergency_only(gdp_db):
    conn = db()
    try:
        set_active_emergency(2, "hyperstorm", conn=conn)
        banner = build_galactic_diplomacy_banner(2, conn=conn)
        assert banner["visible"] is True
        assert banner["emergency"]["key"] == "hyperstorm"
        assert banner["personality"] is None
        assert banner["resolution"] is None
    finally:
        conn.close()


def test_build_galactic_diplomacy_banner_invalid_galaxy(gdp_db):
    assert build_galactic_diplomacy_banner(0)["visible"] is False
    assert build_galactic_diplomacy_banner(99)["visible"] is False


def test_resolution_session_vote_and_pass(gdp_db):
    import uuid
    from game.models import create_user, ensure_player_and_homeworld
    from game.galactic_diplomacy.sessions import (
        open_resolution_session,
        submit_resolution_vote,
    )

    conn = db()
    try:
        ok, err, user = create_user(f"res_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="ResVoter", conn=conn)
        conn.commit()
        planet = conn.execute(
            "SELECT galaxy FROM planets WHERE player_id = ? LIMIT 1;", (uid,)
        ).fetchone()
        galaxy = int(planet["galaxy"])

        opened = open_resolution_session(
            galaxy, "ban_directive", created_by=uid, vote_hours=24, conn=conn
        )
        assert opened["ok"] is True
        sid = int(opened["session"]["id"])
        voted = submit_resolution_vote(uid, sid, "yes", conn=conn)
        assert voted["ok"] is True
        assert voted["session"]["yes_votes"] == 1
        assert voted["session"]["player_choice"] == "yes"
    finally:
        conn.close()


def test_politics_art_pack_exists():
    base = ROOT / "static" / "img" / "politics"
    assert (base / "_placeholder.svg").is_file()
    assert (base / "directives" / "military.svg").is_file()
    assert (base / "blocs" / "scientific_bloc.svg").is_file()
    assert (base / "emergencies" / "pirate_war.svg").is_file()
    assert (base / "chamber" / "senate_hero.svg").is_file()


def test_command_map_includes_politics_overlay(gdp_db):
    import uuid
    from game.models import create_user, ensure_player_and_homeworld
    from game.planet_evolution.command_map import build_command_map_payload

    conn = db()
    try:
        ok, err, user = create_user(f"cm_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="MapPol", conn=conn)
        conn.commit()
        payload = build_command_map_payload(uid, conn=conn)
        assert "politics" in payload
        assert "galaxies" in payload["politics"]
    finally:
        conn.close()
