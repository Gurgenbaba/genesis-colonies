from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_timekeeper_partial_state_preserves_resource_hud_metadata():
    src = _read("static/js/core/hud_partial_state_guard.js")
    assert 'path.indexOf("/api/timekeeper/apply") !== -1' in src
    assert "previous.production_per_hour" in src
    assert "state.production_per_hour = previousProduction" in src
    assert "previous.storage" in src
    assert "state.storage = previousStorage" in src
    assert "previous.resources.storage" in src
    assert "state.resources = Object.assign" in src
    assert "GC._timekeeperHudPartialGuardInstalled" in src


def test_desktop_header_badges_are_kept_inside_continuous_topbar():
    partial = _read("templates/partials/header_icon_rail.html")
    assert "gc-shell-badge-clip-guard" in partial
    assert ".gc-header-row-top .gc-header-icon-btn__badge" in partial
    assert ".gc-header-row-top .gc-initiation-hud__badge" in partial
    assert "top: 2px !important;" in partial
    assert "right: 2px !important;" in partial
    assert "filename='js/core/hud_partial_state_guard.js'" in partial
