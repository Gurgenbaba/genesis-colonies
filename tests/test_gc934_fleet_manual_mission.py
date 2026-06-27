"""GC-934 — Manual fleet coords must not auto-select expedition mission."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import game.db as gdb
from game.db import db
from game.fleet import EXPEDITION_POSITION, build_fleet_send_preview
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fleet_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gc934_fleet.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _fleet_js_block(start_marker: str, end_marker: str) -> str:
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    body = src.split(start_marker, 1)[1]
    return body.split(end_marker, 1)[0]


def test_gc934_sync_expedition_does_not_auto_assign_mission():
    body = _fleet_js_block("const syncExpeditionMissionTarget = (page) => {", "const setColonizeRowVisible = (page, mission) => {")
    assert 'missionSel.value = "expedition"' not in body
    assert "fleet_expedition_hint_select_mission" in body


def test_gc934_sync_allowlist_preserves_mission_when_unlocked():
    body = _fleet_js_block("const syncMissionAllowlistFromTarget = (page, target) => {", "const updateFleetTargetInlineError = (page, target) => {")
    assert "const preserveMission = !locked" in body
    assert "preserveMission" in body
    assert "!locked && !preserveMission && allowed.size > 0" in body


def test_gc934_should_show_expedition_hours_only_for_expedition_mission():
    body = _fleet_js_block("const shouldShowExpeditionHours = (page, mission) => {", "const updateFleetFormMode = (page) => {")
    assert 'return mission === "expedition"' in body
    assert "expPos" not in body


def test_gc934_apply_fleet_url_prefill_only_sets_mission_when_explicit():
    body = _fleet_js_block("function applyFleetUrlPrefill(page) {", "function applyFleetPageMode(page) {")
    assert "if (missionKnown)" in body
    assert 'page.dataset.fleetUrlMission = missionRaw' in body
    assert body.index("if (missionKnown)") < body.index("syncExpeditionMissionTarget")


def test_gc934_expedition_shortcut_sets_mission_via_quick_target():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert 'data-fleet-expedition-shortcut' in src
    assert 'readAttr("data-mission")' in src
    assert "applyQuickTarget(page, expoShortcut)" in src


def test_gc934_preview_does_not_assign_mission_type():
    preview = _fleet_js_block("const runPreview = async (page) => {", "const schedulePreview = (page) => {")
    assert "mission_type: missionType" in preview
    assert 'missionSel.value = "expedition"' not in preview
    assert "const lockedMission = enforceFleetUrlMissionLock(page)" in preview


def test_gc934_backend_preview_keeps_transport_at_expedition_slot(fleet_db):
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld, get_homeworld

    ok, err, user = create_user(f"gc934_{__import__('uuid').uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, player_name="Cmdr", conn=conn)
        conn.commit()
        hw = get_homeworld(player_id=uid, conn=conn)
        assert hw
        origin = dict(hw)
        exp_pos = int(EXPEDITION_POSITION)
        preview = build_fleet_send_preview(
            player_id=uid,
            origin_planet=origin,
            target_galaxy=int(origin["galaxy"]),
            target_system=int(origin["system"]),
            target_position=exp_pos,
            mission_type="transport",
            ships={"mule_courier": 1},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert preview.get("target", {}).get("target_type") == "expedition_slot"
        assert preview.get("can_send") is False
        assert preview.get("block_reason") == "mission_blocked_expedition_slot"
    finally:
        conn.close()
