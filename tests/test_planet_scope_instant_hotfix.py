from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_planet_scope_hotfix_wraps_only_planet_switch_action():
    src = _read("static/js/core/planet_scope_instant_hotfix.js")
    assert 'requestPath(url) === "/api/planets/active"' in src
    assert "requestedPlanetId(options)" in src
    assert "requestedId !== planetId" in src
    assert "response.ok !== false" in src


def test_planet_scope_hotfix_paints_authoritative_shell_state_first():
    src = _read("static/js/core/planet_scope_instant_hotfix.js")
    assert "GC.patchShellHudFromState(state" in src
    assert "forceResourceBar: true" in src
    assert 'reason: "planet_switch_scope_hotfix"' in src
    assert "GC.instantFeedback.patchPlanetBuildingLevels(state)" in src


def test_planet_scope_hotfix_never_shows_previous_planet_stock():
    src = _read("static/js/core/planet_scope_instant_hotfix.js")
    assert 'document.querySelectorAll("[data-shipyard-stock]")' in src
    assert 'document.querySelectorAll("[data-defense-stock]")' in src
    assert 'document.querySelectorAll("[data-fleet-ship-stock]")' in src
    assert 'node.textContent = "✦ …"' in src
    assert 'node.textContent = "×…"' in src


def test_planet_scope_hotfix_keeps_account_research_global_and_has_no_gameplay_math():
    src = _read("static/js/core/planet_scope_instant_hotfix.js")
    assert "Account research is empire-wide by design" in src
    assert "Planet-Evolution research is planet-scoped" in src
    assert "Math.pow(" not in src
    assert "production_per_hour" not in src
    assert "calculate" not in src.lower()


def test_planet_scope_hotfix_loaded_after_instant_feedback():
    header = _read("templates/partials/header_icon_rail.html")
    instant = header.index("js/core/instant_feedback.js")
    scope = header.index("js/core/planet_scope_instant_hotfix.js")
    tk = header.index("js/core/timekeeper_building_instant_reconcile.js")
    assert instant < scope < tk
