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
    src = _read("static/main.js")
    assert "function optimisticDismissDueCardQueueBlock(block)" in src
    card_marker = "[data-gc-card-queue][data-queue-active='1']"
    card_section = src.split(card_marker)[1].split("[data-gc-card-queue][data-queue-active='0']")[0]
    assert "optimisticDismissDueCardQueueBlock(block)" in card_section
    assert card_section.index("optimisticDismissDueCardQueueBlock(block)") < card_section.index(
        "requestFinishRefresh"
    )


def test_gc838_queue_panel_refresh_coalesced():
    src = _read("static/main.js")
    fn = src.split("function refreshPageAfterQueueEvent(reason)")[1].split(
        "/** Lightweight HUD refresh"
    )[0]
    assert "_queuePanelRefreshInFlight" in fn
    assert "if (_queuePanelRefreshInFlight) return _queuePanelRefreshInFlight" in fn
    assert 'reasonStr === "page_init"' in fn
    assert "buildBuildingsFinishDeltaUrl(keys)" in fn


def test_gc838_no_double_refresh_on_timer_zero():
    src = _read("static/main.js")
    timer_zero = src.split("function requestQueueTimerZeroRefresh(meta)")[1].split(
        "function markCardQueueZeroRefresh"
    )[0]
    assert timer_zero.count('GC.refreshGameState("queue_timer_zero")') == 1
    assert "refreshShipyardStateCoalesced" not in timer_zero
    assert "refreshDefenseStateCoalesced" not in timer_zero
    assert "reloadCurrentPage" not in timer_zero


def test_gc838_production_completion_uses_game_state_not_pjax():
    src = _read("static/main.js")
    fn = src.split("function requestProductionCompletionSync(opts)")[1].split(
        "function requestQueueTimerZeroRefresh"
    )[0]
    assert "PRODUCTION_COMPLETION_DEBOUNCE_MS = 180" in src
    assert 'GC.refreshGameState("timer_done")' in fn
    assert "reloadCurrentPage" not in fn


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
    assert "function isMutationStatePatchReason(reason)" in src
    assert "forcePanel: !isPlanetSwitch" in src.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0]
    assert "patchQueuePanelsImmediate(state)" in src.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0]
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
