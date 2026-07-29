"""
GC-838 — Queue action latency & panel patch performance contracts.

Run: python -m pytest tests/test_gc838_queue_action_latency.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc838_optimistic_dismiss_before_finish_refresh():
    """[data-gc-card-queue][data-queue-active='1'] now appears at three call
    sites in main.js (this one plus two other queue-render helpers added
    since this test was written), so a plain src.split(marker)[1] no longer
    reliably lands on the updateAllProgressBars timer-zero block. Anchor on
    the enclosing function name first to keep the split unambiguous.
    """
    src = _read("static/main.js")
    assert "function optimisticDismissDueCardQueueBlock(block)" in src
    progress_fn = src.split("function updateAllProgressBars(serverNow)")[1].split(
        "\n  function ", 1
    )[0]
    card_marker = "[data-gc-card-queue][data-queue-active='1']"
    card_section = progress_fn.split(card_marker)[1].split("[data-gc-card-queue][data-queue-active='0']")[0]
    assert "optimisticDismissDueCardQueueBlock(block)" in card_section
    assert card_section.index("optimisticDismissDueCardQueueBlock(block)") < card_section.index(
        "requestFinishRefresh"
    )


def test_gc838_queue_panel_refresh_coalesced():
    """refreshPageAfterQueueEvent's own page_init branching + delta-refresh
    call were consolidated (commit afd88f1, "Timer-zero queue completion now
    forces a canonical include_panel refresh") into forceCanonicalGameStateRefresh,
    which now owns both the include_panel fetch AND the single-flight
    _queuePanelRefreshInFlight coalescing guard for every queue-event reason
    (page_init included) — see
    test_gc838_production_completion_uses_game_state_not_pjax. The "concurrent
    refresh requests share one in-flight fetch" invariant this test protects
    still holds, just in the new canonical owner.
    """
    src = _read("static/main.js")
    delegator = src.split("function refreshPageAfterQueueEvent(reason)")[1].split(
        "/** Lightweight HUD refresh"
    )[0]
    assert "forceCanonicalGameStateRefresh(" in delegator
    canonical = src.split("async function forceCanonicalGameStateRefresh(reason, opts)")[1].split(
        "\n  }\n", 1
    )[0]
    assert "_queuePanelRefreshInFlight" in canonical
    assert "if (_queuePanelRefreshInFlight) return _queuePanelRefreshInFlight" in canonical


def test_gc838_no_double_refresh_on_timer_zero():
    """Timer-zero completions call forceCanonicalGameStateRefresh directly now
    rather than routing through the generic GC.refreshGameState(reason)
    dispatcher (see test_gc838_production_completion_uses_game_state_not_pjax),
    but the "exactly one refresh per debounced batch, not one per queued
    domain" invariant this test protects is unchanged.
    """
    src = _read("static/main.js")
    timer_zero = src.split("function requestQueueTimerZeroRefresh(meta)")[1].split(
        "function markCardQueueZeroRefresh"
    )[0]
    assert timer_zero.count('forceCanonicalGameStateRefresh("queue_timer_zero")') == 1
    assert "refreshShipyardStateCoalesced" not in timer_zero
    assert "refreshDefenseStateCoalesced" not in timer_zero
    assert "reloadCurrentPage" not in timer_zero


def test_gc838_production_completion_uses_game_state_not_pjax():
    """requestProductionCompletionSync used to run its own
    PRODUCTION_COMPLETION_DEBOUNCE_MS=180 timer and call
    GC.refreshGameState("timer_done") directly. It has since been
    consolidated (GC-546D) into the single canonical debounce+coalesce
    owner, requestQueueTimerZeroRefresh — removing a duplicate debounce
    timer for the same "queue completed -> refresh game state" event. The
    invariant this test protects — completion syncs via the canonical
    game-state fetch path, never a full/PJAX page reload — still holds.
    """
    src = _read("static/main.js")
    fn = src.split("function requestProductionCompletionSync(opts)")[1].split(
        "function requestQueueTimerZeroRefresh"
    )[0]
    assert "requestQueueTimerZeroRefresh(" in fn
    assert "reloadCurrentPage" not in fn
    timer_zero = src.split("function requestQueueTimerZeroRefresh(meta)")[1].split(
        "function markCardQueueZeroRefresh"
    )[0]
    assert 'forceCanonicalGameStateRefresh("queue_timer_zero")' in timer_zero
    assert "reloadCurrentPage" not in timer_zero
    canonical_refresh = src.split("async function forceCanonicalGameStateRefresh(reason, opts)")[1].split(
        "\n  }\n", 1
    )[0]
    assert 'GC.fetchJSON("/api/game-state' in canonical_refresh


def test_gc838_finish_refresh_debounce_tightened():
    src = _read("static/main.js")
    assert "FINISH_REFRESH_MIN_MS = 450" in src
    assert "FINISH_REFRESH_DEBOUNCE_MS = 80" in src
    finish = src.split("function requestFinishRefresh(type)")[1].split(
        "let _overviewWidgetsPlanetId"
    )[0]
    assert "FINISH_REFRESH_DEBOUNCE_MS" in finish
    assert ", 300)" not in finish


def test_gc838_technical_modal_not_on_cancel():
    src = _read("static/main.js")
    assert "function shouldRefreshTechnicalModalAfterAction(reason)" in src
    gate = src.split("function shouldRefreshTechnicalModalAfterAction(reason)")[1].split(
        "async function loadBuildingTechnicalData"
    )[0]
    assert "_cancel_success" in gate
    action = src.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0]
    assert "shouldRefreshTechnicalModalAfterAction(reasonStr)" in action
    assert action.index("shouldRefreshTechnicalModalAfterAction") < action.index(
        "refreshOpenTechnicalModalIfNeeded"
    )


def test_gc838_cancel_uses_single_action_state_patch():
    src = _read("static/main.js")
    cancel_block = src.split('const json = await GC.fetchGameAction("/api/buildings/cancel"')[1].split(
        'const json = await GC.fetchGameAction("/api/research/cancel"'
    )[0]
    assert cancel_block.count("applyActionState(json") == 1
    assert "refreshGameState" not in cancel_block
    assert "reloadCurrentPage" not in cancel_block


def test_gc838_immediate_action_patch_no_poll_wait():
    src = _read("static/main.js")
    assert "function patchQueuePanelsImmediate(data)" in src
    assert "function syncMountedQueuePagesFromState(state, reason)" in src
    assert "function isMutationStatePatchReason(reason)" in src
    apply_action = src.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0]
    assert "forcePanel: !isPlanetSwitch" in apply_action
    # Immediate patch still required — owned by syncMountedQueuePagesFromState → patchQueuePanelsImmediate.
    assert "syncMountedQueuePagesFromState(state, reasonStr)" in apply_action
    assert "logActionStatePatch(" in src
    skip_fn = src.split("function shouldSkipInitGameStateAfterSsr(page, opts)")[1].split(
        "function bootstrapResourceLiveFromDom"
    )[0]
    assert "return pageHasSsrLiveBoot()" in skip_fn
    assert "_SSR_SKIP_INIT_GAME_STATE_PAGES" not in skip_fn
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split(
        "function refreshPageAfterQueueEvent"
    )[0]
    assert "forcePanel" in apply
    assert "isMutationStatePatchReason(reason)" in apply
