"""
Regression guards for PJAX-safe messages inbox and chat polling (static JS contracts).

Run: python -m pytest tests/test_static_live_updates.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_messages_js_always_reinits_and_persistent_cleanup():
    src = _read("static/js/messages.js")
    assert "persistent: true" in src
    assert "listLoaded" in src
    assert "readActiveFilterFromDom" in src
    assert "getMessagesDom" in src
    assert "GC.messagesPageState && !force" not in src
    assert "resetMessagesPageState" in src
    assert "_messagesInitSeq" in src
    assert "requestSeq" in src
    assert "isCurrentRequest" in src
    assert "bootMessagesIfPresent" not in src


def test_messages_js_initial_load_and_stale_request_guards():
    src = _read("static/js/messages.js")
    assert "state.loading = true" in src
    assert "state.listLoaded = true" in src
    assert "isCurrentRequest(state, initSeq, requestId)" in src
    assert "showLoadingList" in src
    assert "showErrorList" in src
    assert "queueMicrotask" in src.split("GC.messagesPageState = state")[1][:400]
    assert "force: true" in src.split("GC.messagesPageState = state")[1][:400]
    assert "clearLoadingIfStale" in src
    assert "inflightFilter" in src
    init_section = src.split("function initMessagesPage")[1][:900]
    assert 'const filter = "all"' in init_section
    assert "bypass GC.fetchJSON" in src
    assert "await GC.fetchJSON" not in src
    assert "loadGen" not in src


def test_main_js_messages_inbox_reload_only_on_unread_increase():
    src = _read("static/main.js")
    unread_section = src.split("if (typeof data.unread_messages_count === \"number\")")[1].split("// --- Overview-Ressourcen")[0]
    assert "emptyInboxNeedsFill" not in unread_section
    assert "unreadSyncedFromApi" not in unread_section
    assert "GC.messagesPageState.listLoaded" in unread_section
    assert "unreadIncreased &&" in unread_section
    tabs_section = src.split("function bindBuildingTabsOnce")[1].split("function initBuildings")[0]
    assert '#messages-tabs' in tabs_section


def test_messages_js_tab_and_initial_share_load_list():
    src = _read("static/js/messages.js")
    assert "state.loadList = loadList" in src
    assert "state.loadList?.(true, { force: true })" in src
    tab_section = src.split("tabBtn.dataset.filter")[1][:400]
    assert "loadList" in tab_section
    assert "force: true" in tab_section


def test_messages_js_spy_report_and_category_label():
    src = _read("static/js/messages.js")
    assert "function categoryLabel(cat)" in src
    assert "function renderSpyReport(meta)" in src
    assert "function renderExpeditionReport(meta)" in src
    assert "expeditionEventVisual" in src
    assert "gc-expedition-card" in src
    assert "renderMessageBody(msg)" in src


def test_chat_js_poll_updates_last_id_and_resume_bootstrap():
    src = _read("static/js/chat.js")
    assert "applyIncomingPollMessages" in src
    assert "bumpLastMsgId" in src
    assert "isActivelyViewingRoom" in src
    assert "maybeRefreshBootstrap" in src
    assert "resumeChatPolling" in src
    assert "bootstrapIntervalMs: 60000" in src
    assert "chatDebug" in src
    assert "installGlobalChatHandlers" in src
    tail = src.split("GC.initChat = initChat")[1]
    assert "DOMContentLoaded" not in tail


def test_main_js_game_state_polling_idempotent():
    src = _read("static/main.js")
    assert "started: false" in src.split("polling:")[1][:200]
    assert "scheduleGameStatePoll" in src
    assert "polling already active" in src
    assert "intervalIdle: 5000" in src
    assert "normalizePjaxUrl" in src
    assert "PJAX dedupe" in src
    assert "dataset.pjaxBusy" in src
    assert "_finishRefreshArmed" in src
    assert "resolveFlight" in src
    nav_section = src.split("GC.navigateTo = async function navigateTo")[1].split("function initPjax")[0]
    assert "GC.cleanupPage();" in nav_section
    assert "main-content missing" in nav_section
    cleanup_idx = nav_section.index("GC.cleanupPage();")
    fetch_idx = nav_section.index("await fetch(url")
    assert fetch_idx < cleanup_idx, "cleanupPage must run only after HTML fetch succeeds"
    assert 'refreshGameState("pjax_nav")' not in nav_section
    assert "if (GC.pjaxInFlight) return null;" in src


def test_main_js_progress_ticker_uses_server_time_and_interval():
    src = _read("static/main.js")
    assert "bootstrapServerTimeFromDom" in src
    assert "data-server-time" in _read("templates/base.html")
    assert "SERVER_TIME=int(time.time())" in _read("app.py")
    time_section = src.split("function getApproxServerNow()")[1].split("bootstrapServerTimeFromDom();")[0]
    assert "Math.floor(Date.now() / 1000)" in time_section
    ticker_section = src.split("GC.startProgressTicker = function startProgressTicker()")[1].split("GC.stopPolling")[0]
    assert "_progressTickerDelayMs" in ticker_section
    assert "setTimeout(tick, _progressTickerDelayMs(serverNow))" in ticker_section
    assert "requestAnimationFrame(tick)" not in ticker_section
    update_section = src.split("function updatePlanetEvolutionResearchProgress")[1].split("function updateAllProgressBars")[0]
    assert "querySelectorAll(\".planet-evolution-page .pe-planet-research-active\")" in update_section
    assert "formatEta(Math.ceil(remaining))" in update_section
    update_all = src.split("function updateAllProgressBars(serverNow)")[1].split("function updateBuildQueueLive")[0]
    assert "updatePlanetEvolutionResearchProgress(serverNowTs)" in update_all


def test_main_js_movement_countdown_expiry_debounced():
    src = _read("static/main.js")
    assert "requestMovementCountdownRefresh" in src
    assert "_movementCountdownExpiryState" in src
    assert "fleet_countdown_expired" in src
    assert "_hasLiveCountdownAt" in src
    assert "MOVEMENT_EXPIRY_REFRESH_MS" in src
    assert "_queuedChainRefreshReason" in src
    assert "_noteMovementCountdownStillStale" in src
    refresh_section = src.split("async function refreshGameState(reason)")[1].split("GC.refreshGameState = refreshGameState")[0]
    assert "isChainReason" in refresh_section
    assert 'reasonStr === "fleet_countdown_expired"' in refresh_section
    assert "_queuedChainRefreshReason = reasonStr" in refresh_section
    assert "queueMicrotask" in refresh_section
    progress_section = src.split("function _hasActiveProgressJobs()")[1].split("// progress ticker")[0]
    assert "_hasLiveCountdownAt()" in progress_section
    assert "_hasStaleMovementCountdown()" in progress_section
    assert "_movementCountdownRefreshPending.fleet" in progress_section


def test_main_js_init_page_resumes_chat_after_pjax():
    src = _read("static/main.js")
    assert "GC.initChat()" in src
    init_section = src.split("function initPage")[1].split("function formatDuration")[0]
    assert "GC.resumeChatPolling()" not in init_section


def test_chat_open_tchat_api_and_desktop_fab_scoped():
    chat_js = _read("static/js/chat.js")
    assert "GC.openTChat = openTChat" in chat_js
    assert "async function openTChat" in chat_js
    main_js = _read("static/main.js")
    assert "GC.openTChat" in main_js
    css = _read("static/style.css")
    assert ".gc-chat-fab{\n  display: none !important;\n}" not in css
    assert "@media (min-width: 769px)" in css


def test_main_js_pjax_covers_main_content_links():
    src = _read("static/main.js")
    assert "isPjaxEligibleLink" in src
    assert 'link.closest("#main-content")' in src
    assert "data-no-pjax" in src
    assert 'form.hasAttribute("data-validate")' in src


def test_main_js_galaxy_prefetch_on_init():
    src = _read("static/main.js")
    assert "GC.modules.galaxy = initGalaxy" in src
    assert "prefetchGalaxyAdjacent" in src
    assert 'path.endsWith("/galaxy")' in src
    assert "bindGalaxyKeyboardOnce" not in src


def test_fleet_form_excluded_from_pjax_get_submit():
    tpl = _read("templates/fleet.html")
    assert 'id="fleet-send-form"' in tpl
    assert "data-no-pjax" in tpl
    assert 'method="post"' in tpl
    js = _read("static/main.js")
    assert "e.defaultPrevented" in js.split("function initPjax")[1].split("function init")[0]


def test_chat_bootstrap_not_in_message_poll_tick():
    src = _read("static/js/chat.js")
    poll_body = src.split("async function pollTick")[1].split("function startPolling")[0]
    assert "if (!panelVisible)" not in poll_body or "maybeRefreshBootstrap(false)" not in poll_body
    assert "runInitialBootstrap" in src


def test_main_js_fleet_countdown_uses_integer_seconds():
    src = _read("static/main.js")
    assert "function formatCountdownRemain" in src
    assert "_progressTickerDelayMs" in src
    tick_body = src.split("const tickFleetCountdowns = () =>")[1].split("tickFleetCountdowns();")[0]
    assert "updateMovementCountdowns(getApproxServerNow())" in tick_body
    countdown_body = src.split("function updateMovementCountdowns(serverNow)")[1].split("function updateAllProgressBars")[0]
    assert "Math.ceil(countdownAt - now)" in countdown_body
    assert "MOVEMENT_EXPIRY_REFRESH_MS_SHORT" in src
    assert "movementRemainingSeconds" in src
    assert "data-server-remaining" in src
    assert "patchActiveFleetCards" in src
    assert "_anyStaleMovementCountdownDom" in src
    stale_section = src.split("function requestMovementCountdownRefresh(scope)")[1].split("function updateMovementCountdowns")[0]
    assert "requestMovementCountdownRefresh(pendingKey)" in stale_section


def test_style_uses_readable_level_font():
    css = _read("static/style.css")
    assert "--gc-font-level" in css
    assert "JetBrains Mono" in css
    assert ".gc-level-badge" in css
    badge_block = css.split(".gc-level-badge{")[1].split("}")[0]
    assert "var(--gc-font-level)" in badge_block


def test_main_js_patches_resource_bar_energy_warning():
    src = _read("static/main.js")
    assert "function patchResourceBarEnergyWarning" in src
    assert 'classList.toggle("energy-warning"' in src
    apply_body = src.split("function applyGameStateData")[1].split("function ")[0]
    assert "patchResourceBarEnergyWarning(used, total)" in apply_body


def test_main_js_gc802_planet_switch_state_sync():
    src = _read("static/main.js")
    assert "syncScopedPlanetIds" in src
    assert 'document.getElementById("logistics-page")' in src
    assert '"logistics-page"' in src.split("function syncScopedPlanetIds")[1].split("function abortInFlight")[0]
    assert "abortInFlightGameStateFetches" in src
    switch_section = src.split('applyActionState(res, "planet_switch")')[1][:1200]
    planet_switch_apply = src.split("const isPlanetSwitch = reason === \"planet_switch\"")[1][:600]
    assert "GC.stopPolling()" in planet_switch_apply
    assert "reloadCurrentPage({ force: true })" in switch_section
    assert "planet_switch_reload" in switch_section
    assert "refreshFleetState(fleetPage)" in switch_section
    action_body = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert 'reason === "planet_switch"' in action_body
    assert "planetSwitch: isPlanetSwitch" in action_body
    apply_body = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert "syncScopedPlanetIds(activePlanetId)" in apply_body
    assert "opts.planetSwitch" in apply_body


def test_main_js_gc802_fleet_timer_and_url_prefill():
    src = _read("static/main.js")
    assert "function movementRemainingSeconds(countdownAt, serverNow, serverRemaining)" in src
    timer_body = src.split("function movementRemainingSeconds(countdownAt, serverNow, serverRemaining)")[1].split("function bootstrapServerTimeFromDom")[0]
    assert "Math.max(fromEndAt, fromServer)" not in timer_body
    assert "Number.isFinite(srv)" in timer_body
    prefill = src.split("function applyFleetUrlPrefill(page)")[1].split("let _shipyardRefreshTimer")[0]
    assert "URLSearchParams(window.location.search)" in prefill
    assert "dataset.fleetUrlMission" in prefill
    assert "syncColonyChipsFromCoords" in prefill
    assert "_fleetApplySeq" in src
    assert "_fleetRefreshSeq" in src
    galaxy_tpl = _read("templates/partials/galaxy_fleet_actions.html")
    assert "slot.coordinates.galaxy" in galaxy_tpl
    assert "target_position=" in galaxy_tpl


def test_main_js_gc801_action_state_and_stale_poll_guards():
    src = _read("static/main.js")
    assert "_clientStateGen" in src
    assert "_lastAppliedServerTime" in src
    assert "resetResourceDisplayCache" in src
    action_section = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert "forceResourceBar: true" in action_section
    assert "resetResourceDisplayCache()" in action_section
    assert "_clientStateGen += 1" in action_section
    refresh_section = src.split("async function refreshGameState(reason)")[1].split("GC.refreshGameState = refreshGameState")[0]
    assert "stateGenAtStart !== _clientStateGen" in refresh_section
    apply_section = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert 'reason === "poll"' in apply_section
    assert "syncResourceLiveBaseline" in apply_section
    assert "patchBuildingPanel" in apply_section
    assert "location.reload()" not in action_section


def test_galaxy_template_pjax_nav_urls():
    tpl = _read("templates/galaxy.html")
    assert 'id="galaxy-page-root"' in tpl
    assert "data-prev-url" in tpl
    assert "data-next-url" in tpl
