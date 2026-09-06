"""GC-PERF-MASS-EXPO-004 — batch launch + due/return amplification guards."""

from __future__ import annotations

from pathlib import Path

import game.fleet as fleet_mod
from game.db import db
from game.models import get_planets_by_player
from tests.test_fleet import _fund_planet, _player, _seed_ships
from tests.test_gc981_mass_expedition_split import (
    _grant_navigation_for_mass_expo,
    _usable_slots,
)

pytest_plugins = ("tests.test_fleet",)


def _seed_mass_expo_player(conn, *, min_usable: int = 3):
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(
        cur,
        pid,
        metal=50_000_000,
        crystal=50_000_000,
        fuel_cells=50_000_000,
    )
    _grant_navigation_for_mass_expo(cur, uid, min_usable=min_usable)
    usable = _usable_slots(uid, conn)
    assert usable >= min_usable
    _seed_ships(pid, uid, {"solar_skiff": usable * 1000}, conn=conn)
    conn.commit()
    return uid, pid, usable


def test_mass_expo_bulk_launch_never_calls_send_fleet_per_wave(fleet_db, monkeypatch):
    conn = db()
    uid, pid, usable = _seed_mass_expo_player(conn)

    def forbidden_send(*_args, **_kwargs):
        raise AssertionError("mass expedition must not call send_fleet per wave")

    monkeypatch.setattr(fleet_mod, "send_fleet", forbidden_send)
    ok, reason, payload = fleet_mod.mass_expedition_from_ships(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": usable * 1000},
        conn=conn,
    )
    assert ok is True, reason
    assert int((payload or {}).get("started_count") or 0) == usable
    conn.close()


def test_mass_expo_validates_at_most_twice_not_once_per_wave(fleet_db, monkeypatch):
    conn = db()
    uid, pid, usable = _seed_mass_expo_player(conn)
    real_validate = fleet_mod.validate_fleet_send
    calls = {"n": 0}

    def counted_validate(*args, **kwargs):
        calls["n"] += 1
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(fleet_mod, "validate_fleet_send", counted_validate)
    ok, reason, payload = fleet_mod.mass_expedition_from_ships(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": usable * 1000},
        conn=conn,
    )
    assert ok is True, reason
    assert int((payload or {}).get("started_count") or 0) == usable
    # One read-only preview validation + one write-owned authoritative validation.
    assert calls["n"] == 2
    conn.close()


def test_mass_expo_deducts_hangar_once_for_whole_batch(fleet_db, monkeypatch):
    conn = db()
    uid, pid, usable = _seed_mass_expo_player(conn)
    real_deduct = fleet_mod.deduct_planet_ships
    calls = {"n": 0}

    def counted_deduct(*args, **kwargs):
        calls["n"] += 1
        return real_deduct(*args, **kwargs)

    monkeypatch.setattr(fleet_mod, "deduct_planet_ships", counted_deduct)
    ok, reason, payload = fleet_mod.mass_expedition_from_ships(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": usable * 1000},
        conn=conn,
    )
    assert ok is True, reason
    assert int((payload or {}).get("started_count") or 0) == usable
    assert calls["n"] == 1
    conn.close()


def test_expedition_shared_context_reuses_empire_aggregate(fleet_db, monkeypatch):
    conn = db()
    uid, pid, _usable = _seed_mass_expo_player(conn)
    real_empire = __import__(
        "game.empire_page", fromlist=["get_empire_production_aggregate"]
    ).get_empire_production_aggregate
    calls = {"n": 0}

    def counted_empire(player_id, *, conn=None):
        calls["n"] += 1
        return real_empire(player_id, conn=conn)

    import game.empire_page as empire_page

    monkeypatch.setattr(empire_page, "get_empire_production_aggregate", counted_empire)
    movement = {
        "player_id": uid,
        "origin_planet_id": pid,
        "target_galaxy": 1,
    }
    cache = {}
    first = fleet_mod._expedition_tick_shared_context(
        movement,
        conn=conn,
        now=1_700_000_000.0,
        cache=cache,
    )
    second = fleet_mod._expedition_tick_shared_context(
        movement,
        conn=conn,
        now=1_700_000_001.0,
        cache=cache,
    )
    assert first == second
    assert calls["n"] == 1
    conn.close()


def test_mass_expo_source_has_bulk_and_fast_return_contracts():
    src = Path("game/fleet.py").read_text(encoding="utf-8")
    mass = src.split("def mass_expedition_from_ships(", 1)[1].split(
        "\ndef mass_expedition(", 1
    )[0]
    assert "send_fleet(" not in mass
    assert "cur.executemany(" in mass
    assert "emit_fleet_missions_sent" in mass
    assert mass.count("deduct_planet_ships(") == 1

    ret = src.split("def _handle_return(", 1)[1].split("\ndef ", 1)[0]
    expo_fast = ret.split('if mission == "expedition":', 1)[1].split(
        "from .i18n import get_player_locale, tr", 1
    )[0]
    assert "_complete_movement(" in expo_fast
    assert "add_planet_ships(" in expo_fast
    assert "_credit_planet_resources(" in expo_fast
    assert "get_player_locale" not in expo_fast
    assert "_movement_batch_type" not in expo_fast


def test_expedition_outbound_arrival_skips_locale_and_report_reads():
    src = Path("game/fleet.py").read_text(encoding="utf-8")
    arrival = src.split("def _handle_arrival(", 1)[1].split("\ndef ", 1)[0]
    fast = arrival.split('if mission == "expedition":', 1)[1].split(
        "from .i18n import get_player_locale, tr", 1
    )[0]
    assert "_claim_movement_status(" in fast
    assert '"holding"' in fast
    assert "get_player_locale" not in fast
    assert "notify_" not in fast


def test_postgres_due_budget_and_single_load_contracts_are_explicit():
    src = Path("game/fleet.py").read_text(encoding="utf-8")
    tick = src.split("def _process_fleet_tick_short_tx(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "default_max_movements = 200 if is_postgres else 50" in tick
    assert "default_max_ms = 2500.0 if is_postgres else 800.0" in tick
    assert "_fleet_due_entries(" in tick

    run_one = src.split("def _run_one_movement_short_tx(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "_load_movement_row(" not in run_one
    body = src.split("def _run_one_movement_short_tx_body(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert body.count("_load_movement_row(") == 1


def test_hangar_add_and_deduct_avoid_full_catalog_rewrite():
    src = Path("game/fleet.py").read_text(encoding="utf-8")
    add_block = src.split("def add_planet_ships(", 1)[1].split("\ndef ", 1)[0]
    deduct_block = src.split("def deduct_planet_ships(", 1)[1].split("\ndef ", 1)[0]

    assert "get_planet_ships(" not in add_block
    assert "set_planet_ships(" not in add_block
    assert "ON CONFLICT(planet_id, ship_key) DO UPDATE" in add_block
    assert "executemany(" in add_block

    assert "set_planet_ships(" not in deduct_block
    assert "ship_key IN" in deduct_block
    assert "executemany(" in deduct_block

def test_mass_expo_success_has_no_direct_fleet_state_refresh_storm():
    src = Path("static/main.js").read_text(encoding="utf-8")

    bridge = src.split("function syncFleetUiAfterMutation(reason)", 1)[1].split(
        "function resetQueueRenderSignaturesForImmediatePatch", 1
    )[0]
    assert 'r === "fleet_send_success" || r === "fleet_mass_expo_success"' in bridge
    assert "immediate: false" in bridge

    split_submit = src.split("const submitMassExpeditionSplit = async (page) => {", 1)[1].split(
        "const submitMassExpedition = async (page) => {", 1
    )[0]
    preset_submit = src.split("const submitMassExpedition = async (page) => {", 1)[1].split(
        'document.addEventListener("mouseover"', 1
    )[0]

    assert 'applyActionState(res, "fleet_mass_expo_success")' in split_submit
    assert 'applyActionState(res, "fleet_mass_expo_success")' in preset_submit
    assert "await refreshFleetState(page)" not in split_submit
    assert "await refreshFleetState(page)" not in preset_submit

    # Split mode has exactly one unconditional post-submit preview refresh in
    # finally; the success branch must not schedule a second copy.
    success_tail = split_submit.split('applyActionState(res, "fleet_mass_expo_success")', 1)[1].split(
        "} else {", 1
    )[0]
    assert "scheduleMassExpoSplitPreview(page)" not in success_tail

