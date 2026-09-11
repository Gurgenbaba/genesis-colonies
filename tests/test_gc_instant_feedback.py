"""Response-first UI feedback: never leave stale action/context state visible."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_instant_feedback_loads_after_partial_state_guard():
    rail = _read("templates/partials/header_icon_rail.html")
    guard = "filename='js/core/hud_partial_state_guard.js'"
    instant = "filename='js/core/instant_feedback.js'"
    assert guard in rail
    assert instant in rail
    assert rail.index(guard) < rail.index(instant)


def test_planet_switch_paints_authoritative_building_levels_before_panel_reconcile():
    src = _read("static/js/core/instant_feedback.js")
    assert 'path === "/api/planets/active"' in src
    assert "patchPlanetBuildingLevels(response.state" in src
    assert "state.buildings" in src
    assert 'querySelectorAll("[data-building-row]")' in src
    assert 'querySelectorAll("[data-bld-stage-prop]")' in src
    assert '[data-bld-stage-level]' in src
    assert ".gc-bld-hero-level" in src
    # The fast path is display-only. Canonical include_panel remains the owner of
    # prices, requirements, queue locks and every gameplay formula.
    assert "can_afford" not in src
    assert "time_seconds" not in src


def test_world_boss_attack_updates_participant_board_from_action_response():
    src = _read("static/js/core/instant_feedback.js")
    assert 'path.indexOf("/api/world-boss/") === 0' in src
    assert "response.player" in src
    assert "response.attack" in src
    assert "player.total_damage" in src
    assert "player.total_players" in src
    assert "data-gc-live-self-contrib" in src
    assert ".gc-world-boss-board-details" in src
    assert ".gc-world-boss-board-panels .ranking-table-wrapper" in src


def test_world_boss_compact_live_poll_mirrors_current_player_without_blocking_poll():
    src = _read("static/js/core/instant_feedback.js")
    assert 'parsed.pathname === "/api/world-boss"' in src
    assert 'parsed.searchParams.get("live") === "1"' in src
    assert "response.clone()" in src
    assert ".then(patchWorldBossLivePayload)" in src
    assert "return response;" in src


def test_messages_sync_uses_tiny_notification_summary_before_game_state_fallback():
    src = _read("static/js/core/instant_feedback.js")
    assert 'String(reason || "") !== "messages_sync"' in src
    assert 'window.fetch("/api/notifications/summary"' in src
    assert "applyMessageNotificationSummary(data)" in src
    assert 'GC.mergeLastState({ unread_messages_count: n }, "messages_sync")' in src
    assert "GC.setMessagesUnreadPollBaseline(n)" in src
    assert "originalRefreshGameState.apply(self, args)" in src
    assert "notification_summary_failed" in src
    assert "notification_summary_invalid" in src


def test_messages_sync_fast_path_does_not_replace_other_game_state_reasons():
    src = _read("static/js/core/instant_feedback.js")
    fast_path = src.split("function installMessagesSyncFastPath()")[1].split("function applyActionFeedback")[0]
    assert "originalRefreshGameState.apply(this, arguments)" in fast_path
    assert "__gcMessagesSyncFastPath" in fast_path
    assert "GC.refreshGameState = wrappedRefreshGameState" in fast_path


def test_instant_feedback_is_fail_open_and_keeps_canonical_state_authoritative():
    src = _read("static/js/core/instant_feedback.js")
    assert "originalFetchGameAction.call(this, url, options)" in src
    assert "UI acceleration is fail-open" in src
    assert "return response;" in src
    assert "originalRefreshGameState.apply(self, args)" in src
