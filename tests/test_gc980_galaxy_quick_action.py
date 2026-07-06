"""GC-980 — shared GalaxyQuickAction module (spy, attack, debris recycle)."""

from __future__ import annotations

from pathlib import Path


def _read_js() -> str:
    return Path("static/js/galaxy-quick-action.js").read_text(encoding="utf-8")


def test_galaxy_quick_action_module_loaded_in_base():
    base = Path("templates/base.html").read_text(encoding="utf-8")
    assert "js/galaxy-quick-action.js" in base


def test_galaxy_quick_action_exports_gc_namespace():
    js = _read_js()
    assert "GC.GalaxyQuickAction = GalaxyQuickAction" in js
    assert "bindRingView" in js


def test_galaxy_quick_action_shared_fleet_send_contract():
    js = _read_js()
    assert "postFleetSend" in js
    assert "makeRequestId" in js
    assert "runGuarded" in js
    assert "applyActionState" in js
    assert "request_id" in js


def test_galaxy_quick_action_spy_handler():
    js = _read_js()
    assert "handleSpyClick" in js
    assert "data-galaxy-quick-spy" in js
    assert "galaxy_quick_spy: true" in js


def test_galaxy_quick_action_attack_handler_with_preview():
    js = _read_js()
    assert "handleAttackClick" in js
    assert "data-galaxy-quick-attack" in js
    assert "galaxy_quick_attack: true" in js
    assert "galaxy_attack=1" in js
    assert "galaxy-quick-attack-item-preview" in js
    assert "entries.slice(0, 3)" in js


def test_galaxy_quick_action_debris_recycle_handler():
    js = _read_js()
    assert "handleDebrisRecycleClick" in js
    assert "data-galaxy-ring-debris-recycle" in js
    assert 'mission_type: "recycle"' in js


def test_galaxy_quick_action_relocation_handler():
    js = _read_js()
    assert "handleRelocationClick" in js
    assert "data-galaxy-relocation-start" in js
    assert "/api/planet/relocation/start" in js


def test_main_js_wires_galaxy_quick_action():
    main_js = Path("static/main.js").read_text(encoding="utf-8")
    assert "GC.GalaxyQuickAction" in main_js
    assert "bindRingView(root)" in main_js
    assert "onQuickSpyClick" not in main_js
    assert "onDebrisRecycleClick" not in main_js


def test_gc_exports_for_galaxy_quick_action():
    main_js = Path("static/main.js").read_text(encoding="utf-8")
    assert "GC.applyActionState = applyActionState" in main_js
    assert "GC.getDomPlanetId = getDomPlanetId" in main_js
    assert "GC.mapActionError = mapActionError" in main_js
