"""GC-583B — World expedition reports with strategic world context."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.expedition_events import build_expedition_report, resolve_expedition_outcome
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.strategic_worlds import (
    build_strategic_world_presentation_from_key,
    strategic_world_type_for_coords,
)
from game.planet_evolution.world_colonization import build_world_key, is_expedition_world_type

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def world_report_db(tmp_path, monkeypatch):
    db_file = tmp_path / "world_report.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
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
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def _expedition_world_key() -> str:
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_expedition_world_type(wt):
                return build_world_key(float(wx), float(wy), world_type=wt)
    raise AssertionError("no expedition world in sample grid")


def test_build_strategic_world_presentation_from_key():
    world_key = _expedition_world_key()
    presentation = build_strategic_world_presentation_from_key(world_key)
    assert presentation["world_key"] == world_key
    assert presentation["name_key"].startswith("strategic_world_name_")
    assert presentation["type_key"].startswith("strategic_world_type_")
    assert presentation["risk_key"]


def test_build_expedition_report_with_world_context():
    world_key = _expedition_world_key()
    world = build_strategic_world_presentation_from_key(world_key)
    outcome = resolve_expedition_outcome(
        4242,
        cargo_total=5000,
        expedition_ship_count=2,
        flight_seconds=120,
    )
    body, meta = build_expedition_report(
        world_key,
        {"solar_skiff": 1},
        outcome,
        locale="en",
        world_context=world,
    )
    assert meta["report_kind"] == "world_expedition"
    assert meta["world_key"] == world_key
    assert meta["world_name_key"] == world["name_key"]
    assert meta["world_risk_key"] == world["risk_key"]
    assert meta["losses"] == {}
    assert meta["losses_total"] == 0
    assert "Location:" in body or "Ort:" in body
    assert "Losses: none" in body or "Verluste: keine" in body


def test_build_expedition_report_classic_slot_unchanged():
    outcome = resolve_expedition_outcome(
        99,
        cargo_total=1000,
        expedition_ship_count=1,
        flight_seconds=60,
    )
    body, meta = build_expedition_report("1:2:16", {"solar_skiff": 1}, outcome, locale="en")
    assert meta.get("report_kind") != "world_expedition"
    assert "world_name_key" not in meta
    assert "Coordinates:" in body


def test_fleet_world_expedition_report_metadata(world_report_db):
    import time

    from game.fleet import add_planet_ships, process_fleet_tick, send_fleet
    from game.models import get_planets_by_player

    world_key = _expedition_world_key()
    from game.db import db

    conn = db()
    try:
        ok, err, user = create_user(f"rep_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok and user, err
        player_id = int(user["id"])
        ensure_player_and_homeworld(player_id, player_name="Commander", conn=conn)
        pid = int(get_planets_by_player(player_id, conn=conn)[0]["id"])
        conn.execute(
            "UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE id = ?;",
            (pid,),
        )
        add_planet_ships(pid, player_id, {"solar_skiff": 1}, conn=conn)
        conn.commit()

        ok, reason, result = send_fleet(
            player_id=player_id,
            origin_planet_id=pid,
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            world_key=world_key,
            conn=conn,
        )
        assert ok, reason
        fleet_id = int(result["fleet"]["id"])
        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (time.time() - 1, fleet_id),
        )
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()

        conn.execute(
            "UPDATE fleet_movements SET holding_until = ? WHERE id = ?;",
            (time.time() - 1, fleet_id),
        )
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()

        msg = conn.execute(
            """
            SELECT subject, metadata_json FROM player_messages
            WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;
            """,
            (player_id,),
        ).fetchone()
        assert msg
        meta = json.loads(msg["metadata_json"])
        assert meta["report_kind"] == "world_expedition"
        assert meta["world_key"] == world_key
        assert meta["world_name_key"]
        world = build_strategic_world_presentation_from_key(world_key)
        assert meta["world_name_key"] == world["name_key"]
        assert world_key not in msg["subject"]
    finally:
        conn.close()


def test_gc583b_locale_keys_present():
    keys = (
        "fleet_report_expedition_subject_world",
        "fleet_world_expedition_report_location",
        "fleet_world_expedition_report_risk",
        "fleet_world_expedition_report_section_loot",
        "fleet_world_expedition_report_loot_line",
        "fleet_world_expedition_report_losses_none",
    )
    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    for key in keys:
        assert key in de, f"missing de locale key {key}"
        assert key in en, f"missing en locale key {key}"
