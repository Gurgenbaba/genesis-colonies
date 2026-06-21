"""GC-557 — Global timer & planet-scope audit (static contracts)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc557_reset_queue_live_states_on_planet_switch():
    src = _read("static/main.js")
    assert "function _resetQueueLiveStates()" in src
    switch = src.split('const isPlanetSwitch = reason === "planet_switch"')[1][:500]
    assert "_resetQueueLiveStates()" in switch
    cleanup = src.split("GC.cleanupPage = function cleanupPage()")[1].split("function logStatusPollErrorOnce")[0]
    assert "_resetQueueLiveStates()" in cleanup
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent")[0]
    assert "_resetQueueLiveStates()" in apply


def test_gc557_fleet_origin_resolves_context_planet():
    src = _read("static/main.js")
    assert "function resolveFleetOriginPlanetId(page)" in src
    assert "GC.resolveFleetOriginPlanetId = resolveFleetOriginPlanetId" in src
    preview = src.split("const runPreview = async (page) =>")[1].split("const schedulePreview = (page) =>")[0]
    assert "resolveFleetOriginPlanetId(page)" in preview
    assert "origin_planet_id: originId" in preview
    send = src.split('const sendForm = e.target.closest ? e.target.closest("#fleet-send-form")')[1][:4000]
    assert "resolveFleetOriginPlanetId(page)" in send
    init = src.split("function initFleet()")[1].split("function applyFleetUrlPrefill(page)")[0]
    assert "resolveFleetOriginPlanetId(page)" in init


def test_gc557_fleet_preview_static_arrival_not_live_countdown():
    src = _read("static/main.js")
    preview_block = src.split("const runPreview = async (page) =>")[1].split("const schedulePreview = (page) =>")[0]
    assert "p.duration_seconds ?? p.flight_seconds" in preview_block
    assert "delete previewArrival.dataset.countdownAt" in preview_block
    assert "previewArrival.dataset.countdownAt = String(arrivalAt)" not in preview_block
    assert "GC.startProgressTicker();" not in preview_block.split("if (previewArrival)")[1].split("if (sendBtn)")[0]


def test_gc557_fleet_send_always_refreshes_state():
    src = _read("static/main.js")
    send_ok = src.split('const sendForm = e.target.closest ? e.target.closest("#fleet-send-form")')[1][:5000]
    assert 'applyActionState(res, "fleet_send_success")' in send_ok
    assert "await refreshFleetState(page)" in send_ok


def test_gc557_debug_perf_timer_scope_counters():
    src = _read("static/main.js")
    perf = src.split("GC.debugPerf = function debugPerf()")[1].split("GC.isPerfIdle = isPerfIdle")[0]
    assert "movementCountdownRefresh" in perf
    assert "queueTimerZero" in perf
    assert "domPlanetId" in perf
    assert "activePlanetId" in perf
    assert "progressTickerScheduled" in perf


def test_gc557_sync_scoped_planet_updates_fleet_runtime():
    src = _read("static/main.js")
    sync = src.split("function syncScopedPlanetIds(planetId)")[1].split("function abortInFlightGameStateFetches")[0]
    assert "fleetPage._fleetRt.data.planet_id" in sync


def test_gc557_doc_present():
    doc = _read("docs/GC-557_GLOBAL_TIMER_AUDIT.md")
    assert "GC-557" in doc
    assert "Single timer source" in doc
