"""Deep-Space Threat Net — radar_array scan_range consumer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.fleet import (
    build_radar_contacts,
    radar_intel_tier,
    radar_system_distance,
)
from game.models import (
    create_user,
    get_homeworld,
    init_db,
    save_planet_buildings,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "radar_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


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


@pytest.fixture(autouse=True)
def _db_setup(temp_db):
    init_db()
    _run_migrate(temp_db)
    init_db()
    yield


def test_radar_system_distance_same_and_cross_galaxy():
    assert radar_system_distance(1, 10, 1, 12) == 2
    assert radar_system_distance(1, 5, 2, 5) == 8
    assert radar_system_distance(1, 5, 3, 5) is None


def test_radar_intel_tiers():
    assert radar_intel_tier(0) == 0
    assert radar_intel_tier(1) == 1
    assert radar_intel_tier(3) == 2
    assert radar_intel_tier(5) == 3
    assert radar_intel_tier(7) == 4
    assert radar_intel_tier(9) == 5


def test_radar_detects_attack_in_bubble():
    ok, _, defender = create_user("defender_radar", "pw")
    assert ok
    ok, _, attacker = create_user("attacker_radar", "pw")
    assert ok
    def_id = int(defender["id"])
    atk_id = int(attacker["id"])

    hw = get_homeworld(player_id=def_id)
    save_planet_buildings(int(hw["id"]), {"radar_array": 5, "command_center": 3})

    conn = db()
    cur = conn.cursor()
    # Place attacker origin in same galaxy, nearby system
    cur.execute(
        """
        UPDATE planets SET galaxy = 1, system = 10, position = 8
        WHERE player_id = ?;
        """,
        (def_id,),
    )
    cur.execute(
        """
        UPDATE planets SET galaxy = 1, system = 12, position = 4
        WHERE player_id = ?;
        """,
        (atk_id,),
    )
    atk_hw = get_homeworld(player_id=atk_id)
    now = time.time()
    cur.execute(
        """
        INSERT INTO fleet_movements (
            player_id, origin_planet_id, target_planet_id,
            target_galaxy, target_system, target_position,
            mission_type, status, ships_json, resources_json,
            departure_at, arrival_at, return_at, holding_until,
            distance, flight_seconds, speed_percent, fuel_cost,
            created_at, updated_at
        ) VALUES (?, ?, ?, 1, 10, 8, 'attack', 'outbound', ?, '{}',
                  ?, ?, NULL, NULL, 100, 60, 100, 10, ?, ?);
        """,
        (
            atk_id,
            int(atk_hw["id"]),
            int(hw["id"]),
            json.dumps({"falcon_interceptor": 5}),
            now - 10,
            now + 120,
            now,
            now,
        ),
    )
    conn.commit()

    payload = build_radar_contacts(def_id, conn=conn, now=now)
    conn.close()
    assert payload["radar_contact_count"] >= 1
    contact = payload["radar_contacts"][0]
    assert contact["threat_class"] == "hostile"
    assert contact["tier"] >= 1
