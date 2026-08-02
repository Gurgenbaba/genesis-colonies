"""GC-980 — shared GalaxyQuickAction module (spy, attack, debris recycle)."""

from __future__ import annotations

from pathlib import Path


def _read_js() -> str:
    return Path("static/js/galaxy-quick-action.js").read_text(encoding="utf-8")


def test_galaxy_quick_action_module_loaded_on_galaxy_page():
    """GC-PERF-JS-002: galaxy QA is page-scoped (not paid on every shell boot)."""
    base = Path("templates/base.html").read_text(encoding="utf-8")
    assert "js/galaxy-quick-action.js" not in base
    galaxy = Path("templates/galaxy.html").read_text(encoding="utf-8")
    assert "js/galaxy-quick-action.js" in galaxy


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


def test_galaxy_quick_action_origin_planet_fallbacks():
    """PJAX Galaxy may omit HEADER_ACTIVE_PLANET; origin must still resolve."""
    js = _read_js()
    assert "data-gc-planet-registry" in js
    assert "lastState?.active_planet_id" in js
    assert "galaxy-page-root" in js
    assert "galaxy_asteroid_harvest_bad_target" in js
    assert "galaxy_debris_recycle_bad_target" in js


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
    assert "sendDebrisRecycle" in js
    assert "data-galaxy-ring-debris-recycle" in js
    assert 'mission_type: "recycle"' in js


def test_galaxy_quick_action_debris_live_sync_contract():
    """GC-DEBRIS-LIVE-01 / GC-GAL-TFS-01: arrival reload + stale-target self-heal."""
    js = _read_js()
    main_js = Path("static/main.js").read_text(encoding="utf-8")
    assert "watchRecycleArrivals" in js
    assert "onActiveFleetsForRecycleSync" in js
    assert "handleStaleRecycleTargetError" in js
    assert "galaxy_debris_gone_reload" in js
    assert "no_debris_at_target" in js
    assert "registerActiveFleetsListener" in main_js
    assert "notifyActiveFleetsListeners" in main_js
    # Arrival path invalidates + force reload; send-success must not reload debris HTML.
    reload_fn = js.split("async reloadGalaxyAfterRecycle()")[1].split("scheduleGalaxyReloadAfterRecycleArrival")[0]
    assert "invalidateGalaxyPjaxCache" in reload_fn
    assert "reloadCurrentPage" in reload_fn
    debris_handler = js.split("async handleDebrisRecycleClick")[1].split("async handleAsteroidRecycleClick")[0]
    assert "await this.reloadGalaxyAfterRecycle()" not in debris_handler
    post = js.split("async postFleetSend")[1].split("async handleStaleRecycleTargetError")[0]
    if "async handleStaleRecycleTargetError" not in js:
        post = js.split("async postFleetSend")[1][:2500]
    apply_idx = post.find("applyActionState(res, applyReason)")
    success_idx = post.find("onSuccess(res)")
    assert apply_idx != -1 and success_idx != -1
    assert apply_idx < success_idx


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
