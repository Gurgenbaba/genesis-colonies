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
    src = _read("static/main.js")
    block = src.split("/** GC-835 — mutation fetches must not register with pageLifecycle")[1].split(
        "function newRequestId"
    )[0]
    assert "GC.fetchGameAction = async function fetchGameAction" in block
    assert "pageLifecycle.abortControllers" not in block
    assert "GC.registerCleanup" not in block
    assert "AbortController" not in block
    assert "signal:" not in block


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

    shipyard_patch = src.split("function patchShipyardCardQueues(page, queueData)")[1].split(
        "function shipyardIconUrl"
    )[0]
    assert "resolveCardJobsByOwner(queueData)" in shipyard_patch

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

    cleanup = src.split("GC.cleanupPage = function cleanupPage()")[1].split("GC.abortGameLoop")[0]
    assert "lc.cleanupFns = lc.cleanupFns.filter((fn) => fn._gcPersistent)" in cleanup
    assert "GC._gameActionsBound" not in cleanup
    assert "GC._buildingTechBound" not in cleanup
