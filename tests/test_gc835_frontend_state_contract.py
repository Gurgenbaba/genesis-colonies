"""
GC-835 — Frontend state & PJAX regression contract.

Run: python -m pytest tests/test_gc835_frontend_state_contract.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_fetch_game_action_not_cleanup_abortable():
    """
    GC-835 — mutation fetches must survive PJAX cleanup.

    Why updated: fetchGameAction may forward an optional caller AbortSignal
    (`signal: externalSignal`) for intentional cancel. That is not pageLifecycle wiring.

    Still required: no registration with pageLifecycle.abortControllers / registerCleanup,
    and no local AbortController owned by the helper.
    """
    src = _read("static/main.js")
    block = src.split("/** GC-835 — mutation fetches must not register with pageLifecycle")[1].split(
        "function newRequestId"
    )[0]
    assert "GC.fetchGameAction = async function fetchGameAction" in block
    assert "pageLifecycle.abortControllers" not in block
    assert "GC.registerCleanup" not in block
    assert "AbortController" not in block
    assert "const externalSignal = fetchOpts.signal" in block
    assert "signal: externalSignal" in block
    assert "pageLifecycle.abortControllers.push" not in block


def test_cancel_clears_hero_time_chip_timer():
    src = _read("static/main.js")
    clear_block = src.split("GC.clearCardQueueBlock = function clearCardQueueBlock(cardEl)")[1].split(
        "function findCardQueueBlockByJobId"
    )[0]
    assert "stripHeroTimeChipQueueTimer(cardEl)" in clear_block
    patch_queues = src.split(
        "function patchCardQueuesFromOwnerMap(page, byOwner, listCards, ownerKeyFromCard, findCard)"
    )[1].split("GC.renderCardQueueBlock = function renderCardQueueBlock")[0]
    assert "GC.clearCardQueueBlock(card)" in patch_queues
    building_patch = src.split("function patchBuildingPanel(rowsByTab, buildQueueRaw)")[1].split(
        "function patchResearchEffects"
    )[0]
    assert "setHeroTimeChipIdle(row, b.time_seconds" in building_patch


def test_missing_card_jobs_by_owner_treated_as_empty_map():
    src = _read("static/main.js")
    assert "function resolveCardJobsByOwner(queueRaw)" in src
    helper = src.split("function resolveCardJobsByOwner(queueRaw)")[1].split("function renderMaxQueueButtonLabel")[0]
    assert "return raw && typeof raw === \"object\" ? raw : {}" in helper

    building_patch = src.split("function patchBuildingPanel(rowsByTab, buildQueueRaw)")[1].split(
        "function patchResearchEffects"
    )[0]
    assert "resolveCardJobsByOwner(buildQueueRaw)" in building_patch
    assert "buildQueueRaw != null" in building_patch

    research_patch = src.split("function patchResearchPanel(techs, researchRaw)")[1].split(
        "let _finishRefreshTimer"
    )[0]
    assert "resolveCardJobsByOwner(researchRaw)" in research_patch
    assert "researchRaw != null" in research_patch

    shipyard_patch = src.split("function patchShipyardCardQueues(page")[1].split(
        "function shipyardIconUrl"
    )[0]
    assert "clearAllProductionCardQueues(page)" in shipyard_patch
    assert "patchCardQueuesFromOwnerMap" not in shipyard_patch

    pe_patch = src.split("function patchPePlanetTechCardQueues(rdx)")[1].split(
        "function patchPeAscensionCardQueues"
    )[0]
    assert "resolveCardJobsByOwner(rdx)" in pe_patch
    assert "if (!byOwner || typeof byOwner !== \"object\") return" not in pe_patch


def test_max_tooltip_refreshed_after_state_patch():
    src = _read("static/main.js")
    dismiss = src.split("function dismissProgressionTooltipsOnStatePatch()")[1].split(
        "function applyActionState(json, reason)"
    )[0]
    assert "hideMaxQueueTooltip" in dismiss
    action = src.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0]
    assert "dismissProgressionTooltipsOnStatePatch()" in action


def test_technical_modal_uses_fresh_values_after_action():
    src = _read("static/main.js")
    assert "BUILDING_TECH.activeKey" in src
    assert "BUILDING_TECH.activeKind" in src
    assert "function refreshOpenTechnicalModalIfNeeded()" in src
    action = src.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0]
    assert "refreshOpenTechnicalModalIfNeeded()" in action
    load_build = src.split("async function loadBuildingTechnicalData(buildingType)")[1].split(
        "async function loadResearchTechnicalData"
    )[0]
    assert 'BUILDING_TECH.activeKind = "building"' in load_build
    load_research = src.split("async function loadResearchTechnicalData(techKey)")[1].split(
        "function onBuildingTechnicalClick"
    )[0]
    assert 'BUILDING_TECH.activeKind = "research"' in load_research


def test_no_duplicate_listeners_after_pjax():
    src = _read("static/main.js")
    game_actions = src.split("function initGameActions()")[1].split("// =========================")[0]
    assert "if (GC._gameActionsBound) return" in game_actions
    assert "GC._gameActionsBound = true" in game_actions

    tech_once = src.split("function initBuildingTechnicalDataOnce()")[1].split(
        "function initBuildingTechnicalData()"
    )[0]
    assert "if (GC._buildingTechBound) return" in tech_once
    assert "document.addEventListener(\"click\", onBuildingTechnicalClick)" in tech_once

    max_hover = src.split("function initMaxQueueHoverOnce()")[1].split("function initPlanetEvolution")[0]
    assert "if (GC._maxQueueHoverBound) return" in max_hover


def test_gc_clean_002_pe_immediate_patch_and_action_state():
    """GC-CLEAN-002 — PE queues patch immediately; mutations use applyActionState first."""
    src = _read("static/main.js")

    patch_immediate = src.split("function patchQueuePanelsImmediate(data)")[1].split(
        "let _finishRefreshTimer"
    )[0]
    assert ".planet-evolution-page" in patch_immediate
    assert "renderPePlanetTechQueue" in patch_immediate

    reset_sigs = src.split("function resetQueueRenderSignaturesForImmediatePatch()")[1].split(
        "function logActionStatePatch"
    )[0]
    assert "_lastPePlanetTechQueueSignature" in reset_sigs
    assert "_lastPeAscensionQueueSignature" in reset_sigs

    tk_sync = src.split("function _syncTimekeeperButtonsFromState(state)")[1].split(
        "function _refreshDomTimekeeperApplyBtns"
    )[0]
    assert "planet-evolution-page" in tk_sync
    assert "planet_research" in tk_sync
    assert "_syncPeQueueListTimekeeperFromDom" in tk_sync

    apply_action = src.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0]
    assert "_schedulePlanetEvolutionRefreshAfterAction" in apply_action

    assert "const finalizePeMutationSuccess = async" in src
    assert 'await finalizePeMutationSuccess(res, "planet_research_start"' in src
    assert 'await finalizePeMutationSuccess(res, "pe_spec_pick"' in src
    assert 'await finalizePeMutationSuccess(res, "pe_spec_upgrade"' in src
    assert 'await finalizePeMutationSuccess(res, "pe_policy_activate"' in src
    assert 'await finalizePeMutationSuccess(res, "pe_event_resolve"' in src
    assert 'await finalizePeMutationSuccess(res, "pe_research_choose", { softContent: false })' in src
    assert 'await finalizePeMutationSuccess(res, "pe_spec_pick", { softContent: false })' in src
    assert 'await finalizePeMutationSuccess(res, "pe_spec_upgrade", { softContent: false })' in src
    assert 'await finalizePeMutationSuccess(res, "pe_policy_activate", { softContent: true })' in src
    assert 'await finalizePeMutationSuccess(res, "pe_event_resolve", { softContent: true })' in src

    pe_bind = src.split("const researchBtn = e.target.closest(\".pe-research-btn\")")[1].split(
        "const choiceBtn = e.target.closest(\".pe-choice-btn\")"
    )[0]
    assert "finalizePeMutationSuccess(res, \"planet_research_start\"" in pe_bind
    assert "reloadCurrentPage" not in pe_bind
    assert "softContent: false" in pe_bind

    soft = src.split("async function _softReloadPlanetEvolutionContent()")[1].split(
        "function _schedulePlanetEvolutionRefreshAfterAction"
    )[0]
    assert "skipGameState: true" in soft
    assert "skipHydrate: true" in soft
    assert "skipPolling: true" in soft