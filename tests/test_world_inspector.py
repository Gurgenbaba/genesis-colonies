"""GC-700D-B — debris read layer for World Inspector / Command Map."""

from __future__ import annotations

import time
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.combat import DEBRIS_FIELD_TTL_SECONDS, add_debris_field
from game.db import db
from game.galaxy import get_planet_coordinates, list_system
from game.models import create_user, get_planets_by_player
from game.planet_evolution.command_center import build_colony_command_center, build_foreign_colony_command_center
from game.world_inspector import (
    attach_debris_to_inspector_payload,
    build_debris_field_payload,
    debris_remaining_seconds,
    fleet_recycle_href,
    get_debris_field_payload,
)


@pytest.fixture()
def galaxy_db(tmp_path, monkeypatch):
    db_path = tmp_path / "world_inspector_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)
    import migrate

    migrate.ensure_db_exists()
    migrate.main()
    yield
    dbmod._DB_PATH = None


def _create_player():
    uname = f"wi_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    return int(user["id"])


def test_build_debris_field_payload_includes_ttl_and_recycle_href():
    now = 1_700_000_000.0
    updated_at = now - 3600.0
    payload = build_debris_field_payload(
        5000,
        1200,
        updated_at=updated_at,
        now=now,
        galaxy=1,
        system=42,
        position=7,
    )
    assert payload is not None
    assert payload["total"] == 6200
    assert payload["ttl_remaining_seconds"] == debris_remaining_seconds(updated_at, now=now)
    assert payload["recycle_href"] == fleet_recycle_href(1, 42, 7)
    assert "mission=recycle" in payload["recycle_href"]


def test_get_debris_field_payload_reads_db(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    conn = db()
    try:
        add_debris_field(
            coords["galaxy"],
            coords["system"],
            coords["position"],
            800,
            200,
            conn=conn,
        )
        conn.commit()
        payload = get_debris_field_payload(
            coords["galaxy"],
            coords["system"],
            coords["position"],
            conn,
            now=time.time(),
        )
    finally:
        conn.close()

    assert payload is not None
    assert payload["metal"] == 800
    assert payload["crystal"] == 200
    assert payload["has_debris"] is True
    assert payload["ttl_remaining_seconds"] <= int(DEBRIS_FIELD_TTL_SECONDS)


def test_colony_command_center_attaches_debris_and_recycle_action(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    conn = db()
    try:
        add_debris_field(
            coords["galaxy"],
            coords["system"],
            coords["position"],
            3000,
            500,
            conn=conn,
        )
        conn.commit()
        cc = build_colony_command_center(int(planet["id"]), uid, conn=conn)
    finally:
        conn.close()

    assert cc.get("debris", {}).get("has_debris") is True
    missions = cc.get("mission_actions") or []
    recycle = next((row for row in missions if row.get("action_key") == "recycle"), None)
    assert recycle is not None
    assert recycle.get("enabled") is True
    assert "mission=recycle" in str(recycle.get("href") or "")


def test_foreign_colony_inspector_gets_debris_when_present(galaxy_db):
    attacker = _create_player()
    defender = _create_player()
    def_planet = get_planets_by_player(defender)[0]
    coords = get_planet_coordinates(def_planet)
    conn = db()
    try:
        add_debris_field(
            coords["galaxy"],
            coords["system"],
            coords["position"],
            9000,
            1000,
            conn=conn,
        )
        conn.commit()
        node = {
            "node_kind": "foreign_colony",
            "planet_id": int(def_planet["id"]),
            "owner_player_id": defender,
            "owner_username": "defender",
            "name": str(def_planet.get("name") or "Colony"),
            "coordinates_formatted": coords["formatted"],
        }
        cc = build_foreign_colony_command_center(node, attacker, conn=conn)
    finally:
        conn.close()

    assert cc.get("debris", {}).get("metal") == 9000
    recycle = next(
        (row for row in (cc.get("mission_actions") or []) if row.get("action_key") == "recycle"),
        None,
    )
    assert recycle is not None


def test_attach_debris_skips_zero_amounts(galaxy_db):
    payload = {"mission_actions": []}
    conn = db()
    try:
        attach_debris_to_inspector_payload(
            payload,
            conn=conn,
            galaxy=1,
            system=499,
            position=15,
        )
    finally:
        conn.close()
    assert "debris" not in payload


def test_list_system_empty_slot_has_no_debris_without_db_row(galaxy_db):
    data = list_system(1, 498)
    empty_with_debris = [
        s for s in data["slots"]
        if not s["occupied"] and s.get("has_debris")
    ]
    assert empty_with_debris == []
