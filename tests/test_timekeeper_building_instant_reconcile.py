"""Timekeeper building boosts repaint cards and Research Ascension without reload."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_bridge_loads_after_existing_instant_feedback_layer():
    rail = _read("templates/partials/header_icon_rail.html")
    instant = "filename='js/core/instant_feedback.js'"
    bridge = "filename='js/core/timekeeper_building_instant_reconcile.js'"
    assert instant in rail
    assert bridge in rail
    assert rail.index(instant) < rail.index(bridge)


def test_build_timekeeper_apply_requests_selected_card_delta_without_blocking_mutation():
    src = _read("static/js/core/timekeeper_building_instant_reconcile.js")
    assert 'path !== "/api/timekeeper/apply"' in src
    assert 'domain !== "build"' in src
    assert "response.seconds_applied" in src
    assert '"/api/game-state?panel_delta_buildings="' in src
    assert 'encodeURIComponent(keys.join(","))' in src
    assert "void refreshVisibleBuildingDelta()" in src
    assert 'GC.applyActionState(data, "timekeeper_build_instant_delta")' in src
    assert "Acceleration only" in src


def test_building_delta_repaints_level_immediately():
    src = _read("static/js/core/timekeeper_building_instant_reconcile.js")
    assert 'document.querySelectorAll("[data-building-row]")' in src
    assert 'card.querySelector(".gc-bld-hero-level")' in src
    assert '[data-bld-stage-level]' in src
    assert "badge.textContent = fmtInt(row.level)" in src


def test_research_lab_gate_surfaces_ascension_cta_from_authoritative_panel_row():
    src = _read("static/js/core/timekeeper_building_instant_reconcile.js")
    assert "row.research_lab_ascension_ready" in src
    assert "row.research_lab_next_roman" in src
    assert 'button.setAttribute("data-research-lab-ascend", "")' in src
    assert 'button.className = "gc-btn gc-bld-evo-btn"' in src
    assert "row.research_lab_ascension_tribute_metal" in src
    assert "row.research_lab_ascension_tribute_crystal" in src
    assert "row.research_queue_capacity" in src
    assert "GC.normalizeBuildingAscensionCards" in src
    assert "location.reload" not in src
    assert "GC.reloadCurrentPage" not in src


def test_bridge_wrap_is_fail_open_and_pjax_persistent():
    src = _read("static/js/core/timekeeper_building_instant_reconcile.js")
    assert "originalFetchGameAction.call(this, url, options)" in src
    assert "Response-first acceleration is fail-open" in src
    assert "GC._timekeeperBuildingInstantInstalled" in src
    assert "DOMContentLoaded" in src
    assert "setInterval" in src
    assert "registerCleanup" not in src
