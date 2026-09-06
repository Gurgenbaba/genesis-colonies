"""GC-PERF-MASS-EXPO-003 — bound per-wave Fleet effect/read amplification."""

from __future__ import annotations

from pathlib import Path

from game.db import db
import game.fleet as fleet_mod
from game.models import get_planets_by_player
from tests.test_fleet import _fund_planet, _player, _seed_ships
from tests.test_gc981_mass_expedition_split import (
    _grant_navigation_for_mass_expo,
    _usable_slots,
)

pytest_plugins = ("tests.test_fleet",)


def test_preview_flight_resolves_effect_bundle_once(fleet_db, monkeypatch):
    conn = db()
    uid = _player(conn=conn)
    origin = dict(get_planets_by_player(uid, conn=conn)[0])
    calls = {"n": 0}

    def fake_mods(player_id, conn_arg, *, galaxy=None):
        calls["n"] += 1
        return {
            "fleet_speed_multiplier": 1.0,
            "fuel_efficiency_factor": 1.0,
            "cargo_multiplier": 1.0,
        }

    monkeypatch.setattr(fleet_mod, "_fleet_galactic_modifiers", fake_mods)
    fleet_mod.preview_fleet_flight(
        origin_planet=origin,
        target_galaxy=int(origin["galaxy"]),
        target_system=int(origin["system"]),
        target_position=fleet_mod.EXPEDITION_POSITION,
        ships={"solar_skiff": 1},
        resources={},
        speed_percent=100,
        player_id=uid,
        mission_type="expedition",
        conn=conn,
    )
    assert calls["n"] == 1
    conn.close()


def test_mass_expedition_reuses_one_effect_snapshot_for_all_waves(fleet_db, monkeypatch):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=5_000_000, crystal=5_000_000, fuel_cells=5_000_000)
    _grant_navigation_for_mass_expo(cur, uid, min_usable=3)
    usable = _usable_slots(uid, conn)
    assert usable >= 3
    _seed_ships(pid, uid, {"solar_skiff": usable * 1000}, conn=conn)
    conn.commit()

    original = fleet_mod._fleet_galactic_modifiers
    calls = {"n": 0}

    def counted(player_id, conn_arg, *, galaxy=None):
        calls["n"] += 1
        return original(player_id, conn_arg, galaxy=galaxy)

    monkeypatch.setattr(fleet_mod, "_fleet_galactic_modifiers", counted)
    ok, reason, result = fleet_mod.mass_expedition_from_ships(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": usable * 1000},
        conn=conn,
    )
    assert ok is True, reason
    assert int((result or {}).get("started_count") or 0) == usable
    # One validation snapshot + one immutable batch snapshot; never N x waves.
    assert calls["n"] <= 2
    conn.close()


def test_mass_expo_batch_uses_bulk_insert_not_per_wave_send():
    src = Path("game/fleet.py").read_text(encoding="utf-8")
    block = src.split("def mass_expedition_from_ships(", 1)[1].split(
        "def mass_expedition(", 1
    )[0]
    assert "fleet_modifiers=batch_fleet_modifiers" in block
    assert "send_fleet(" not in block
    assert "cur.executemany(" in block
    assert "emit_fleet_missions_sent" in block
    assert block.count("deduct_planet_ships(") == 1
    assert "GC-PERF-MASS-EXPO-004" in block


def test_admin_fleet_speed_reuses_caller_connection():
    src = Path("game/fleet.py").read_text(encoding="utf-8")
    block = src.split("def admin_fleet_speed_multiplier(", 1)[1].split(
        "def normalize_expedition_hours(", 1
    )[0]
    assert "conn=None" in block
    assert "get_game_settings(conn=conn)" in block
