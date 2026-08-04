"""Ground troop detail card + surfaces smoke (capacity / techtree / scoring)."""

from __future__ import annotations

import uuid

import pytest

from game.scoring import compute_destroyed_raw_from_losses
from game.techtree import get_techtree_page_context
from game.troop_detail import build_troop_detail_card
from game.troop_defs import (
    barracks_troop_capacity,
    fleet_troop_berth_capacity,
    troop_cargo_slots,
    troop_score_value,
    troop_train_cost,
    troops_fit_fleet_berths,
)


@pytest.fixture
def troops_db(tmp_path, monkeypatch):
    from game import db as gdb
    from game.db import db, rollback
    from game.models import init_db

    db_path = tmp_path / "troop_surfaces.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    conn = db()
    try:
        yield conn
    finally:
        try:
            rollback(conn)
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        gdb._DB_PATH = None


def test_build_troop_detail_card_known_unit():
    card, err = build_troop_detail_card("militia", buildings={"barracks": 2})
    assert err is None
    assert card is not None
    assert card["troop_key"] == "militia"
    assert card["attack"] > 0
    assert card["score_value"] == troop_score_value("militia")
    assert card["train_cost_metal"] > 0
    assert any(i["key"] == "barracks" and i["met"] for i in card["requirements_items"])


def test_build_troop_detail_card_unknown():
    card, err = build_troop_detail_card("unknown_troop_xyz")
    assert card is None
    assert err == "troop_detail_not_found"


def test_techtree_includes_troops_and_barracks_preview():
    ctx = get_techtree_page_context(
        buildings={"barracks": 5, "radar_array": 3, "shield_generator": 2},
        research={},
    )
    keys = [s["key"] for s in ctx["sections"]]
    assert "troops" in keys
    troop_section = next(s for s in ctx["sections"] if s["key"] == "troops")
    assert len(troop_section["nodes"]) >= 3
    buildings = next(s for s in ctx["sections"] if s["key"] == "buildings")
    by_key = {n["key"]: n for n in buildings["nodes"]}
    assert by_key["barracks"]["effect_preview"]["effect_value"] == barracks_troop_capacity(5)
    assert by_key["shield_generator"]["effect_preview"]["effect_value"] == 4
    assert by_key["radar_array"]["effect_preview"]["effect_value"] == 6


def test_destroyed_raw_includes_troop_losses():
    troop_pts = compute_destroyed_raw_from_losses({"militia": 10})
    assert troop_pts > 0
    assert compute_destroyed_raw_from_losses({"militia": 20}) > troop_pts


def test_troop_train_costs_are_not_disposable():
    militia = troop_train_cost("militia")
    breach = troop_train_cost("breach_team")
    guard = troop_train_cost("vault_guard")
    assert militia["metal"] >= 5000
    assert militia["crystal"] >= 2000
    assert breach["metal"] > militia["metal"]
    assert guard["metal"] > breach["metal"]


def test_fleet_troop_berths_use_ship_crew_and_troop_slots():
    # 2 falcons × crew 5 = 10 berths
    assert fleet_troop_berth_capacity({"falcon_interceptor": 2}) == 10
    # 10 militia × 1 slot = 10 — fits exactly
    assert troops_fit_fleet_berths({"falcon_interceptor": 2}, {"militia": 10}) is True
    # Breach teams cost 2 slots — 6 would need 12 > 10
    assert troop_cargo_slots({"breach_team": 6}) == 12
    assert troops_fit_fleet_berths({"falcon_interceptor": 2}, {"breach_team": 6}) is False
    # Spy probes have crew 0 — cannot embark troops
    assert fleet_troop_berth_capacity({"veil_probe": 50}) == 0
    assert troops_fit_fleet_berths({"veil_probe": 50}, {"militia": 1}) is False


def test_defense_panel_game_state_includes_troops_slice(troops_db):
    """include_panel defense slice must carry troops so Bodentruppen UI can live-patch."""
    from game.live_state import defense_panel_for_game_state
    from game.models import (
        create_user,
        ensure_player_and_homeworld,
        get_homeworld,
        get_planet_buildings,
        save_planet_buildings,
    )

    conn = troops_db
    ok, err, user = create_user(f"tp_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="TroopsPanel", conn=conn)
    planet_id = int(get_homeworld(player_id=uid, conn=conn)["id"])
    bld = get_planet_buildings(planet_id, conn=conn) or {}
    bld["barracks"] = 5
    save_planet_buildings(planet_id, bld, conn=conn)
    conn.commit()

    panel = defense_panel_for_game_state(uid, conn=conn)
    assert panel is not None
    assert isinstance(panel.get("troops"), dict)
    assert "units" in panel["troops"]
    assert "mini_queue_jobs" in panel["troops"]
    assert panel["defenses"]["troops"]["units"]


def test_troops_live_refresh_client_contract():
    """Timer-zero / game-state must patch barracks troops (not only defense turrets)."""
    from pathlib import Path

    main = (Path(__file__).resolve().parents[1] / "static" / "main.js").read_text(encoding="utf-8")
    defense_js = (
        Path(__file__).resolve().parents[1] / "static" / "js" / "pages" / "defense.js"
    ).read_text(encoding="utf-8")

    assert "function miniQueueRefreshOnZero(domain)" in main
    assert 'kind === "troops"' in main
    assert 'domain === "troops"' in main
    assert "GC.applyTroopsPayload" in main
    assert "troops: slice.troops || inner.troops" in main
    assert "data.troops && typeof GC.applyTroopsPayload" in main
    assert 'data-troop-cost' in main
    assert "GC.applyTroopsPayload = applyTroopsPayload" in defense_js
    assert "costWrap.dataset.unitCostMetal" in defense_js
    assert "resourcesOpt" in defense_js
    assert "militaryPageResources(page)" in main
    assert "#resource-bar .res-value." in main.split("function militaryPageResources")[1].split("function initMilitaryUnitCostPreviewDelegation")[0]
