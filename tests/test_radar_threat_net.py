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
    assert payload["has_radar_sensor"] is True
    assert len(payload["radar_sensors"]) >= 1
    assert int(payload["radar_sensors"][0]["scan_range"]) == 10  # 2 * L5
    contact = payload["radar_contacts"][0]
    assert contact["threat_class"] == "hostile"
    assert contact["tier"] >= 1
    # Sensorphalanx: mission + ETA + coords from tier 1
    assert contact["mission_type"] == "attack"
    assert int(contact["arrival_at"] or 0) > int(now)
    assert contact["origin"] == {"galaxy": 1, "system": 12}
    assert contact["target"] == {"galaxy": 1, "system": 10, "position": 8}
    assert contact.get("eta_band") is None
    # Owner / ships still tier-gated (radar L5 → scan 10, dist 2 → eff 8 → tier 4)
    if int(contact["tier"]) >= 3:
        assert contact.get("owner_name")
    if int(contact["tier"]) < 4:
        assert contact.get("ships_by_role") is None
        assert contact.get("ships") is None


def test_radar_tier1_exposes_mission_eta_coords_not_owner():
    """Minimal effective range (tier 1) still shows phalanx-style basics."""
    ok, _, defender = create_user("def_radar_t1", "pw")
    assert ok
    ok, _, attacker = create_user("atk_radar_t1", "pw")
    assert ok
    def_id = int(defender["id"])
    atk_id = int(attacker["id"])

    hw = get_homeworld(player_id=def_id)
    # scan_range = 2*1 = 2; place fleet at dist 1 → effective 1 → tier 1
    save_planet_buildings(int(hw["id"]), {"radar_array": 1, "command_center": 1})

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET galaxy = 1, system = 20, position = 5 WHERE player_id = ?;",
        (def_id,),
    )
    cur.execute(
        "UPDATE planets SET galaxy = 1, system = 21, position = 3 WHERE player_id = ?;",
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
        ) VALUES (?, ?, ?, 1, 20, 5, 'spy', 'outbound', ?, '{}',
                  ?, ?, NULL, NULL, 50, 30, 100, 5, ?, ?);
        """,
        (
            atk_id,
            int(atk_hw["id"]),
            int(hw["id"]),
            json.dumps({"probe": 1}),
            now - 5,
            now + 90,
            now,
            now,
        ),
    )
    conn.commit()

    payload = build_radar_contacts(def_id, conn=conn, now=now)
    conn.close()
    assert payload["radar_contact_count"] == 1
    contact = payload["radar_contacts"][0]
    assert contact["tier"] == 1
    assert contact["mission_type"] == "spy"
    assert contact["threat_class"] == "intel"
    assert int(contact["arrival_at"]) == int(now + 90)
    assert contact["origin"]["system"] == 21
    assert contact["target"]["system"] == 20
    assert contact["owner_id"] is None
    assert contact["owner_name"] is None
    assert contact["ships"] is None
    assert contact["ships_by_role"] is None
    assert contact["eta_band"] is None


def test_radar_sensors_without_contacts():
    ok, _, defender = create_user("def_radar_sensors", "pw")
    assert ok
    def_id = int(defender["id"])
    hw = get_homeworld(player_id=def_id)
    save_planet_buildings(int(hw["id"]), {"radar_array": 3, "command_center": 1})
    conn = db()
    payload = build_radar_contacts(def_id, conn=conn, now=time.time())
    conn.close()
    assert payload["has_radar_sensor"] is True
    assert payload["radar_contact_count"] == 0
    assert payload["radar_contacts"] == []
    assert len(payload["radar_sensors"]) == 1
    sensor = payload["radar_sensors"][0]
    assert int(sensor["planet_id"]) == int(hw["id"])
    assert int(sensor["scan_range"]) == 6
    assert "galaxy" in sensor and "system" in sensor


def test_galaxy_radar_panel_client_row_nav_contract():
    """Radar rows navigate via data-galaxy-radar-nav (no second poller / no scan API)."""
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "function _radarContactNavPoint(contact)" in main
    assert "function _navigateRadarHref(href)" in main
    assert "data-galaxy-radar-nav=" in main
    assert "onRadarNavClick" in main
    assert "GC.navigateTo" in main.split("function _navigateRadarHref")[1].split("function _radarCoordLinkHtml")[0]
    assert "/api/radar" not in main.split("function syncGalaxyRadarPanel")[1].split("GC.syncGalaxyRadarPanel")[0]
    assert ".galaxy-radar-sensor-item.is-interactive" in css
    assert ".galaxy-radar-contact-item.is-interactive" in css
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = (ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8")
        assert "galaxy_radar_nav_sensor" in data
        assert "galaxy_radar_nav_contact" in data
