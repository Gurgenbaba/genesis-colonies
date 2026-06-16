"""GC-583E — Fleet URL prefill must keep colonize/expedition mission after ship change."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _fleet_js() -> str:
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    start = src.index("const getFleetUrlParams = ()")
    end = src.index("let _shipyardRefreshTimer", start)
    return src[start:end]


def test_gc583e_mission_lock_helpers_present():
    js = _fleet_js()
    for needle in (
        "refreshFleetUrlMissionLock",
        "enforceFleetUrlMissionLock",
        "isFleetUrlPrefillLocked",
        "hasFleetWorldKeyPrefill",
    ):
        assert needle in js, f"missing helper: {needle}"


def test_gc583e_pick_default_skips_url_prefill():
    js = _fleet_js()
    body = js.split("const pickDefaultFleetTargetIfNeeded = (page) => {", 1)[1]
    body = body.split("const applyQuickTarget = (page, chip) => {", 1)[0]
    assert 'params.has("world_key")' in body
    assert 'params.get("mission")' in body


def test_gc583e_schedule_preview_enforces_lock():
    js = _fleet_js()
    body = js.split("const schedulePreview = (page) => {", 1)[1]
    body = body.split("const loadPresetById = (page, presetId) => {", 1)[0]
    assert body.index("enforceFleetUrlMissionLock(page)") < body.index("runPreview(page)")


def test_gc583e_sync_allowlist_respects_prefill_lock():
    js = _fleet_js()
    body = js.split("const syncMissionAllowlistFromTarget = (page, target) => {", 1)[1]
    body = body.split("const formatDebrisPreview = (debris) => {", 1)[0]
    assert "delete page.dataset.fleetUrlMission" not in body
    assert "opt.value === urlMission" in body
    assert "opt.disabled = false" in body
    assert "isFleetUrlPrefillLocked(page)" in body
    assert "!locked && allowed.size > 0" in body


def test_gc583e_preview_enforces_lock_before_and_after_allowlist():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    preview = js.split("const runPreview = async (page) => {", 1)[1]
    preview = preview.split("const schedulePreview = (page) => {", 1)[0]
    assert preview.index("enforceFleetUrlMissionLock(page)") < preview.index("mission_type: missionType")
    assert "const lockedMission = enforceFleetUrlMissionLock(page)" in preview
    assert "mission_type: missionType" in preview


def test_gc583e_apply_quick_target_respects_prefill_lock():
    js = _fleet_js()
    body = js.split("const applyQuickTarget = (page, chip) => {", 1)[1]
    body = body.split("GC.scheduleFleetPreview = schedulePreview", 1)[0]
    assert "isFleetUrlPrefillLocked(page)" in body
    assert body.index("isFleetUrlPrefillLocked(page)") < body.index("clearFleetWorldKey(page)")


def test_gc583e_world_key_falls_back_to_url():
    js = _fleet_js()
    body = js.split("const getFleetWorldKey = (page) => {", 1)[1]
    body = body.split("const clearFleetWorldKey = (page) => {", 1)[0]
    assert "getFleetUrlParams().get(\"world_key\")" in body


def test_gc583e_send_enforces_mission_lock():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    submit = js.split('e.target.closest("#fleet-send-form")', 1)[1]
    submit = submit.split("page.querySelectorAll(\"[data-ship-input]\")", 1)[0]
    assert "enforceFleetUrlMissionLock(page)" in submit
