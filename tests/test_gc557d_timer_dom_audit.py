"""GC-557D — Timer DOM contract & integration audit (templates + static contracts)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc557d_scoped_pages_have_planet_id():
    """Planet-scoped pages must expose data-planet-id on page root or compact queue."""
    checks = {
        "templates/buildings.html": ('data-buildings-page', 'data-planet-id="{{'),
        "templates/research.html": ('research-page', 'data-planet-id="{{'),
        "templates/shipyard.html": ('id="shipyard-page"', "data-planet-id="),
        "templates/defense.html": ('id="defense-page"', "data-planet-id="),
        "templates/fleet.html": ('id="fleet-page"', "data-planet-id="),
        "templates/trader_hub.html": ('id="trader-hub-page"', "data-planet-id="),
        "templates/fleet_logistics.html": ('id="logistics-page"', "data-planet-id="),
    }
    for path, (marker, planet_attr) in checks.items():
        body = _read(path)
        assert marker in body, f"{path} missing {marker}"
        assert planet_attr in body, f"{path} missing {planet_attr}"


def test_gc557d_queue_partials_use_canonical_timer_attrs():
    for path in (
        "templates/partials/page_mini_queue_strip.html",
        "templates/partials/card_queue_macros.html",
    ):
        body = _read(path)
        assert "data-timer-target" in body, path
        assert "data-timer-kind" in body, path
        assert "data-countdown-at" in body, path


def test_gc557d_fleet_active_timers_use_server_fields():
    # Active fleet-movement countdown rows are built client-side in
    # fleetCountdownHtml() (static/main.js) instead of server-rendered Jinja
    # markup in fleet.html; check both sources combined (GC-STABILIZE-002).
    fleet = _read("templates/fleet.html")
    js = _read("static/main.js")
    combined = fleet + "\n" + js
    assert "data-preview-arrival" in fleet
    assert "data-timer-target" in combined
    assert "data-timer-kind=\"fleet\"" in combined
    assert "data-refresh-on-zero=\"fleet\"" in combined
    assert 'data-countdown-scope="${scope}"' in js
    assert 'buildTime(countdownAt, "fleet"' in js
    assert "data-server-remaining" in combined


def test_gc557d_overview_activities_use_timer_contract():
    overview = _read("templates/overview.html")
    assert "data-timer-target" in overview
    assert "data-refresh-on-zero" in overview
    assert "data-countdown-scope=\"overview\"" in overview
    assert "countdown_at or act.finish_at" in overview


def test_gc557d_planet_evolution_card_queue_timer_attrs():
    pe = _read("templates/planet_evolution.html")
    assert "render_card_queue_data_attrs" in pe or "data-finish-at" in pe
    assert "data-gc-card-queue" in pe
    assert "planet-evolution-page" in pe
    assert "data-planet-id" in pe


def test_gc557d_main_js_no_wall_clock_in_game_timer_paths():
    src = _read("static/main.js")
    assert "function serverNow()" in src
    assert "function formatExpeditionEta(etaAt)" in src
    exp = src.split("function formatExpeditionEta(etaAt)")[1].split("function updateExpeditionActivityInspector")[0]
    assert "Date.now()" not in exp
    assert "movementRemainingSeconds" in exp
    sync = src.split("function syncScopedPlanetIds(planetId)")[1].split("function abortInFlightGameStateFetches")[0]
    assert "buildings-wrapper[data-planet-id]" in sync
    assert "research-page[data-planet-id]" in sync
    overview = src.split("function patchOverviewStatus(overview, data, buildings, prod)")[1].split("function patchOverviewResearch")[0]
    assert "queueJobRemainingSeconds" in overview
    assert "Math.ceil(endAt - getTimerServerNow())" not in overview


def test_gc557d_debug_timers_reports_scope():
    src = _read("static/main.js")
    dbg = src.split("GC.debugTimers = function debugTimers()")[1].split("function initShellOnce")[0]
    assert "SCOPE OK" in dbg
    assert "getDomPlanetId()" in dbg


def test_gc557d_doc_section_present():
    doc = _read("docs/GC-557_GLOBAL_TIMER_AUDIT.md")
    assert "GC-557D" in doc
