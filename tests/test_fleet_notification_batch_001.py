"""GC-FLEET-NOTIFICATION-BATCH-001 — coalesce fleet refresh + batch message toasts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_schedule_fleet_state_refresh_coalesces():
    src = _read("static/main.js")
    assert "GC.scheduleFleetStateRefresh = function scheduleFleetStateRefresh" in src
    assert "FLEET_STATE_REFRESH_COALESCE_MS = 200" in src
    assert "_fleetStateRefreshPromise" in src
    assert "_fleetStateRefreshQueued" in src
    refresh_fn = src.split("const refreshFleetState = async (page, opts) => {")[1].split(
        "GC.refreshFleetState = refreshFleetState"
    )[0]
    assert "if (_fleetStateRefreshPromise)" in refresh_fn
    assert "_fleetStateRefreshQueued = true" in refresh_fn
    assert "_fleetStateRefreshQueuedOpts" in refresh_fn


def test_countdown_zero_uses_schedule_fleet_state_refresh():
    src = _read("static/main.js")
    section = src.split("function requestMovementCountdownRefresh(scope)")[1].split(
        "function updatePageTimers(serverNow)"
    )[0]
    assert "GC.scheduleFleetStateRefresh" in section
    assert "Math.max(150, Math.min(300" in section
    assert "fleet_countdown_expired" in section
    # No per-row second refresh path for overview after fleet pending clears.
    assert "pendingKey === \"overview\"" not in section or "GC.refreshFleetState(fleetPageLater)" not in section


def test_apply_live_state_renders_active_fleets():
    src = _read("static/main.js")
    apply = src.split("const applyLiveState = (page, state, opts) => {")[1].split(
        "const refreshFleetState = async (page, opts) => {"
    )[0]
    assert "renderActiveFleets(page, rt.data.active_fleets)" in apply
    assert "GC.renderActiveFleets = renderActiveFleets" in src
    # GC-FLEET-PLANET-SWITCH-001: reject fleet state for a different planet
    assert "fleet applyLiveState stale planet" in apply
    assert "state.planet_id" in apply
    # initFleet must not be re-invoked from applyLiveState
    assert "initFleet(" not in apply


def test_refresh_fleet_state_planet_switch_opts():
    """GC-FLEET-PLANET-SWITCH-001: refresh accepts planetId/force and queues opts."""
    src = _read("static/main.js")
    refresh_fn = src.split("const refreshFleetState = async (page, opts) => {")[1].split(
        "GC.refreshFleetState = refreshFleetState"
    )[0]
    assert "refreshOpts.planetId" in refresh_fn
    assert 'reason === "planet_switch"' in refresh_fn
    assert "_fleetStateRefreshQueuedOpts" in refresh_fn
    assert "force: true" in refresh_fn


def test_message_notify_batch_and_dedupe():
    src = _read("static/main.js")
    unread = src.split("function _processUnreadMessagesPoll(data, reason, opts)")[1].split(
        "function updateNavBadges"
    )[0]
    assert "_queueMessageNotifyItems" in unread
    assert "_extractNotificationToastItems" in unread
    assert "_lastToastedMessageId" in unread
    assert "_maybePlayMessageNotifySound" in unread
    # Old singular toast-on-every-unread-increase path removed.
    assert "Neue Nachricht." not in unread
    assert "dict.messages_notify_new" not in unread

    assert "function _flushMessageNotifyBatch()" in src
    assert "messages.notify_batch_expedition_title" in src
    assert "MESSAGE_NOTIFY_BATCH_MS" in src
    assert "_messageNotifyGroupKey" in src


def test_notification_summary_includes_new_items_slice():
    py = _read("game/live_state.py")
    summary = py.split("def notification_summary_for_client")[1].split(
        "_ACTIVE_PLANET_POLL_KEYS"
    )[0]
    assert "notification_toast_items" in summary
    assert '"new_items"' in summary or "'new_items'" in summary
    assert "notifications" in summary

    msgs = _read("game/messages.py")
    assert "def notification_toast_items(" in msgs
    assert "No message bodies" in msgs or "no body" in msgs.lower() or "metadata-only" in msgs.lower() or "Lightweight unread" in msgs


def test_game_state_includes_notifications_slice():
    app = _read("app.py")
    assert "notification_toast_items" in app
    assert '"notifications"' in app or "'notifications'" in app


def test_locale_batch_keys_present_all_languages():
    keys = [
        "messages.notify_batch_expedition_title",
        "messages.notify_batch_expedition_body",
        "messages.notify_batch_combat_title",
        "messages.notify_batch_logistics_title",
    ]
    for lang in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        text = _read(f"locales/{lang}.json")
        for key in keys:
            assert f'"{key}"' in text, f"missing {key} in {lang}"


def test_sync_fleet_ui_after_mutation_bridge():
    """Fleet mutations must refresh the fleet page list when mounted (HUD already via applyActionState)."""
    src = _read("static/main.js")
    assert "function syncFleetUiAfterMutation(reason)" in src
    assert "function isFleetMutationSyncReason(reason)" in src
    bridge = src.split("function syncFleetUiAfterMutation(reason)")[1].split(
        "function resetQueueRenderSignaturesForImmediatePatch"
    )[0]
    assert "scheduleFleetStateRefresh" in bridge
    assert 'fleetPage.dataset.ready !== "1"' in bridge or 'dataset.ready !== "1"' in bridge
    mutation = src.split("function isMutationStatePatchReason(reason)")[1].split(
        "function isFleetMutationSyncReason"
    )[0]
    assert 'r === "fleet_recall"' in mutation
    assert 'r === "logistics_action"' in mutation
    apply = src.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0]
    assert "syncFleetUiAfterMutation(reasonStr)" in apply


def test_docs_mention_batch_rule():
    state = _read("docs/STATE_AJAX.md")
    assert "GC-FLEET-NOTIFICATION-BATCH-001" in state
    assert "notifications.new_items" in state
    fleet = _read("docs/FLEET_SYSTEM.md")
    assert "scheduleFleetStateRefresh" in fleet
    ajax = _read("docs/AJAX_PJAX_CONTRACT.md")
    assert "Notification batching" in ajax or "batching" in ajax.lower()


def test_fleet_countdown_in_flight_coalesces_game_state():
    src = _read("static/main.js")
    refresh = src.split("async function refreshGameState(reason)")[1].split(
        "GC.refreshGameState = refreshGameState"
    )[0]
    assert 'reasonStr === "fleet_countdown_expired"' in refresh
    assert "_queuedChainRefreshReason" in refresh


def test_render_active_fleets_preserves_scroll():
    src = _read("static/main.js")
    render = src.split("const renderActiveFleets = (page, fleets) => {")[1].split(
        "const renderPresetSelect"
    )[0]
    assert "scrollTop" in render
    assert "pageScrollY" in render or "scrollY" in render


def test_mobile_sheet_layout_resynced_every_hud_render():
    # commit 45246d4 ("fix(ui): ... restore mobile fleet expand") deliberately
    # removed the wasShowAll/nowShowAll diffing here: skipping the resync when
    # show-all state didn't change left the mobile sheet backdrop stuck open
    # after sending a fleet, blocking the drawer's expand button. The fix
    # always resyncs the portal/backdrop on every render instead
    # (GC-STABILIZE-002; static/main.js renderGlobalFleetHud).
    src = _read("static/main.js")
    hud = src.split("function renderGlobalFleetHud(fleetsRaw, opts)")[1].split(
        "function syncFleetVacationNotice"
    )[0]
    assert "Always resync portal/backdrop" in hud
    assert "syncMobileFleetSheetLayout(root)" in hud
    assert "fleetSheetSynced" in hud
