"""Regression contract for the lightweight building affordability refresh."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_buildings_page_detects_cost_threshold_without_new_state_poller():
    js = (ROOT / "static/js/pages/buildings.js").read_text(encoding="utf-8")
    assert '.res-value.' in js
    assert '.gc-cost-' in js
    assert 'metal >= needMetal && crystal >= needCrystal' in js
    assert 'GC.reloadCurrentPage({ force: true })' in js
    assert '[data-bld-stage-card-source] .buildings-tab-panels' in js
    assert 'GC.registerCleanup' in js
    assert 'global.clearInterval(interval)' in js
    assert '/api/game-state' not in js
    assert 'fetch(' not in js


def test_buildings_page_does_not_authorize_upgrade_locally():
    js = (ROOT / "static/js/pages/buildings.js").read_text(encoding="utf-8")
    assert 'data-action-state="warn"' in js
    assert "lastRequested" in js
    assert "30000" in js
    assert ".disabled = false" not in js
    assert 'data-action-state="go"' not in js


def test_resource_hud_changes_trigger_fast_reconcile():
    js = (ROOT / "static/js/pages/buildings.js").read_text(encoding="utf-8")
    assert "new MutationObserver(scheduleTick)" in js
    assert "observer.disconnect()" in js
    assert "requestAnimationFrame" in js
    assert "global.setInterval(tick, 750)" in js


def test_resource_only_warning_becomes_action_without_waiting_for_pjax():
    js = (ROOT / "static/js/pages/buildings.js").read_text(encoding="utf-8")
    assert 'function enableAffordableAction(container, key)' in js
    assert 'item.kind !== "resource"' in js
    assert 'Number(item.need)' in js
    assert 'button.replaceWith(link)' in js
    assert 'data-bld-stage-actions' in js
    assert 'enableAffordableAction(card, key)' in js
    assert 'link.setAttribute("data-action-state", "go")' in js
    assert 'GC.reloadCurrentPage({ force: true })' in js
