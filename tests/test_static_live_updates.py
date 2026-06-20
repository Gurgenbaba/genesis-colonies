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
    assert "bootMessagesInbox" in src


def test_messages_js_initial_load_and_stale_request_guards():
    src = _read("static/js/messages.js")
    assert "state.loading = true" in src
    assert "state.listLoaded = true" in src
    assert "isCurrentRequest(state, initSeq, requestId)" in src
    assert "showLoadingList" in src
    assert "showErrorList" in src
    assert "function bootMessagesInbox(opts" in src
    assert "GC.bootMessagesInbox = bootMessagesInbox" in src
    assert "data-messages-init" in src or "messagesInit" in src
    assert "inboxNeedsReload" in src
    assert "messagesDomMatchesState" in src
    assert "ensureInboxFetching" in src
    assert "inflightFilter" in src
    assert "inboxShowsLoadingShell" in src
    assert "messagesDomNeedsFreshInit" in src
    assert "reconcileInboxPaint" in src
    assert "whenMessagesDomReady" in src
    assert "countInboxItemsInDocument" in src
    assert "data-messages-shell" in src
    assert "attachInboxLoadPaint" in src
    assert "clearLoadingIfStale" in src
    init_section = src.split("function initMessagesPage")[1][:1200]
    assert "readActiveFilterFromDom()" in init_section
    assert "const initSeq = ++_messagesInitSeq" in init_section
    assert "bypass GC.fetchJSON" in src
    assert "await GC.fetchJSON" not in src
    assert "loadGen" not in src


def test_messages_js_pjax_repair_repaints_cached_inbox():
    src = _read("static/js/messages.js")
    assert "function repairInboxPaint" in src
    assert "function scheduleInboxPaintRepair" in src
    assert "function attachInboxLoadPaint" in src
    assert "function inboxNeedsRepaint" in src
    assert "function inboxShowsPlaceholderOnly" in src
    assert "function inboxShowsLoadingShell" in src
    assert "function inboxPaintIsHealthy" in src
    assert "function commitInboxRender" in src
    assert "state.commitInboxRender" in src
    assert "[messages] rendered" in src
    assert "GC.scheduleInboxPaintRepair" in src
    assert "startMessagesInboxLoad" in src
    boot_section = src.split("function bootMessagesInbox")[1].split("function initMessagesPage")[0]
    assert "initMessagesPage({ boot: true" not in boot_section


def test_main_js_messages_inbox_reload_only_on_unread_increase():
    src = _read("static/main.js")
    assert "function scheduleMessagesInboxBoot()" in src
    assert "GC.bootMessagesInbox" in src
    boot_fn = src.split("function scheduleMessagesInboxBoot()")[1].split("GC.initPage")[0]
    assert "repairInboxIfNeeded" in boot_fn
    assert boot_fn.count("setSafeTimeout") == 0
    assert "runMessagesPageModule" in src.split("GC.initPage = function initPage")[1].split("function formatDuration")[0]
    assert "window.GC = GC" in _read("static/main.js").split("initShellOnce")[0]
    after_init = src.split("const afterInit = async () => {")[1].split("};", 1)[0]
    assert "GC.detectPage() === \"messages\"" in after_init
    assert "bootMessagesInbox({ force: false" in after_init
    assert after_init.index("bootMessagesInbox") > after_init.index("refreshGameState")
    assert "function recoverStuckInbox" in _read("static/js/messages.js")
    assert "function ensureInboxFetching" in _read("static/js/messages.js")
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
    assert "bootMessagesInbox" in src
    assert "startMessagesInboxLoad" in src
    tab_section = src.split("tabBtn.dataset.filter")[1][:400]
    assert "loadList" in tab_section
    assert "force: true" in tab_section


def test_messages_js_format_time_always_includes_date():
    messages_js = _read("static/js/messages.js")
    fmt = messages_js.split("function formatTime(ts)")[1].split("function getMessagesDom")[0]
    assert "GC.formatLocaleDateTime" in fmt
    assert "sameDay" not in fmt
    main = _read("static/main.js")
    assert "GC.formatLocaleDateTime = formatLocaleDateTime" in main


def test_messages_js_spy_report_and_category_label():
    src = _read("static/js/messages.js")
    assert "function categoryLabel(cat)" in src
    assert "function renderSpyReportFull(meta" in src
    assert "function renderSpyReportTeaser(meta" in src
    assert "function renderExpeditionReportFull(meta" in src
    assert "function renderExpeditionReportTeaser(meta" in src
    assert "function keyFallbackLabel(raw)" in src
    assert "expeditionEventVisual" in src
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
    bootstrap = src.split("function bootstrapServerTimeFromDom()")[1].split("function getApproxServerNow()")[0]
    assert "TIME.serverNow && TIME.clientPerfAt" in bootstrap
    time_section = src.split("function getApproxServerNow()")[1].split("bootstrapServerTimeFromDom();")[0]
    assert "return serverNow();" in time_section
    server_now = src.split("function serverNow()")[1].split("function syncServerClockFromState")[0]
    assert "Math.floor(Date.now() / 1000)" in server_now
    ticker_section = src.split("GC.startProgressTicker = function startProgressTicker()")[1].split("GC.stopPolling")[0]
    assert "_progressTickerDelayMs" in ticker_section
    assert "setTimeout(tick, _progressTickerDelayMs(serverNow))" in ticker_section
    assert "requestAnimationFrame(tick)" not in ticker_section
    update_all = src.split("function updateAllProgressBars(serverNow)")[1].split("function updateBuildQueueLive")[0]
    assert "[data-gc-card-queue][data-queue-active='1']" in update_all
    assert "planet_research" in update_all
    assert "updatePlanetEvolutionResearchProgress" not in update_all


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
    assert "_hasVisibleOverviewResearchTimer()" in progress_section
    assert 'getElementById("overview-research-active")' not in progress_section
    assert "_hasStaleMovementCountdown()" not in progress_section
    assert "_maybeRefreshStaleMovementCountdowns" in src


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
    assert "function updatePageTimers(serverNow)" in src
    assert "_progressTickerDelayMs" in src
    timer_body = src.split("function updatePageTimers(serverNow)")[1].split("function updateMovementCountdowns")[0]
    assert "timerRemainingSeconds" in timer_body
    assert "movementRemainingSeconds" in src
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
    hud_section = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "patchResourceBarEnergyWarning(used, total)" in hud_section


def test_main_js_gc802_planet_switch_state_sync():
    src = _read("static/main.js")
    assert "syncScopedPlanetIds" in src
    assert 'document.getElementById("logistics-page")' in src
    assert '"logistics-page"' in src.split("function syncScopedPlanetIds")[1].split("function abortInFlight")[0]
    assert "abortInFlightGameStateFetches" in src
    switch_section = src.split('applyActionState(res, "planet_switch")')[1][:1400]
    planet_switch_apply = src.split("const isPlanetSwitch = reason === \"planet_switch\"")[1][:700]
    assert "GC.stopPolling()" in planet_switch_apply
    assert "skipHydrate: true" in switch_section
    assert "skipGameState: true" in switch_section
    assert 'refreshGameState("planet_switch")' in switch_section
    assert "refreshFleetState(fleetPage)" in switch_section
    action_body = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert 'reason === "planet_switch"' in action_body
    assert "skipScopedPanels: isPlanetSwitch" in action_body
    apply_body = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert "syncScopedPlanetIds(activePlanetId)" in apply_body
    assert "skipScopedPanels" in apply_body
    assert "overview-wrapper[data-planet-id]" in src
    hydrate_body = src.split("function hydratePageFromLastState(opts)")[1].split("let _progressTickerActive")[0]
    assert "getDomPlanetId()" in hydrate_body
    overview = _read("templates/overview.html")
    assert 'overview-wrapper" data-planet-id="{{ planet.planet_id or 0 }}"' in overview


def test_main_js_gc742_ssr_skip_init_game_state():
    """GC-742: overview SSR must not immediately re-fetch game-state."""
    src = _read("static/main.js")
    assert "function pageHasSsrLiveBoot()" in src
    assert "function shouldSkipInitGameStateAfterSsr(page, opts)" in src
    assert "initPage skip game-state (SSR fresh)" in src
    assert '"overview"' in src.split("_SSR_SKIP_INIT_GAME_STATE_PAGES")[1].split("function shouldSkipInitGameStateAfterSsr")[0]
    init_body = src.split("const afterInit = async () => {")[1].split("if (page === \"messages\")")[0]
    assert "shouldSkipInitGameStateAfterSsr(page, opts)" in init_body
    assert "bootstrapResourceLiveFromDom()" in init_body


def test_main_js_gc743_deferred_chat_and_news_boot():
    """GC-743: chat bootstrap and what's-new load after initial paint."""
    src = _read("static/main.js")
    assert "GC_DEFER_CHAT_BOOT_MS = 500" in src
    assert "GC_DEFER_WHATS_NEW_MS = 800" in src
    assert "function scheduleDeferredChatBoot()" in src
    assert "scheduleDeferredChatBoot()" in src.split("const afterInit = async () => {")[1].split("if (page === \"messages\")")[0]
    whats_new = src.split("function initWhatsNew()")[1].split("function initVisibilityPolling")[0]
    assert "GC.setSafeTimeout(loadWhatsNew, GC_DEFER_WHATS_NEW_MS)" in whats_new


def test_main_js_gc802_fleet_timer_and_url_prefill():
    src = _read("static/main.js")
    assert "function movementRemainingSeconds(countdownAt, serverNow, serverRemaining)" in src
    timer_body = src.split("function movementRemainingSeconds(countdownAt, serverNow, serverRemaining)")[1].split("function bootstrapServerTimeFromDom")[0]
    assert "Math.max(fromEndAt, fromServer)" not in timer_body
    assert "queueJobRemainingSeconds" in timer_body
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
    assert 'reason === "page_hydrate"' in apply_section
    assert "syncResourceLiveBaseline" in apply_section
    assert "patchBuildingPanel" in apply_section
    assert "location.reload()" not in action_section


def test_main_js_gc804_research_timer_pjax_safe():
    src = _read("static/main.js")
    bootstrap = src.split("function bootstrapServerTimeFromDom()")[1].split("function getApproxServerNow()")[0]
    assert "TIME.serverNow && TIME.clientPerfAt" in bootstrap
    assert "function queueJobRemainingSeconds(" in src
    assert "assignMonotonicServerRemaining" in src.split("function patchCardQueueBlockInPlace")[1].split("GC.renderCardQueueBlock = function")[0]
    assert "_syncResearchQueueLiveState" in src
    set_time = src.split("function setServerTime(serverTimeSec)")[1].split("function queueJobRemainingSeconds")[0]
    assert "v < approx - 2" in set_time
    research_tick = src.split("const researchActive = document.querySelector(\".research-job.research-job-active\")")[1].split("const shipyardActive")[0]
    assert "queueJobRemainingSeconds" in research_tick
    assert "finishTime - serverNowTs" not in research_tick


def test_galaxy_template_pjax_nav_urls():
    tpl = _read("templates/galaxy.html")
    assert 'id="galaxy-page-root"' in tpl
    assert "data-prev-url" in tpl
    assert "data-next-url" in tpl


def test_main_js_gc540_unified_page_timers():
    src = _read("static/main.js")
    assert "function updatePageTimers(serverNow)" in src
    assert "function syncTimerElement(el)" in src
    assert "data-timer-target" in src
    assert "data-refresh-on-zero" in src
    assert "gameStateWantPanelPoll" in src
    assert "timer_done" in src
    assert "_pageTimerLoopRunning" in src
    overview = _read("templates/overview.html")
    assert "data-timer-target" in overview
    assert "data-refresh-on-zero" in overview
    fleet = _read("templates/fleet.html")
    base = _read("templates/base.html")
    assert "data-timer-kind" in fleet or "data-fleet-preview" in fleet
    assert "data-timer-target" in base or "data-countdown-scope" in base
    shipyard = _read("templates/shipyard.html")
    card_queue_macros = _read("templates/partials/card_queue_macros.html")
    assert "render_card_queue_timer(qj, 'shipyard', 'shipyard')" in shipyard
    assert "data-timer-kind" in card_queue_macros
    logic = _read("game/logic.py")
    assert "live_server_timestamp" in logic
    assert "game_state_panel_finish_source" in logic
    sy = _read("game/shipyard_queue.py")
    assert "normalize_queue_job_timer_fields" in sy or '"countdown_at"' in sy
    logic = _read("game/logic.py")
    assert "normalize_queue_job_timer_fields" in logic
    assert "countdown_at" in logic


def test_main_js_gc541_queue_timer_hotfix():
    src = _read("static/main.js")
    assert "function parseTimerTarget(raw)" in src
    set_time = src.split("function setServerTime(serverTimeSec)")[1].split("function queueJobRemainingSeconds")[0]
    assert "Math.abs(v - approx) < 0.5" in set_time
    timer_now = src.split("function getTimerServerNow()")[1].split("function queryTimerElements")[0]
    assert "server_now" in timer_now
    query = src.split("function queryTimerElements(root)")[1].split("function inferTimerKind")[0]
    assert "#build-eta-live" in query
    assert "#research-eta-live" in query
    assert "#shipyard-eta-live" in query
    assert ".build-job-active[data-finish-time]" in query
    ticker = src.split("GC.startProgressTicker = function startProgressTicker()")[1].split("GC.stopPolling")[0]
    assert "_pageTimerLoopRunning && _progressTickerActive && _progressTickerTimerId" not in ticker
    assert "if (_progressTickerTimerId != null) return;" in ticker
    movement = src.split("function movementRemainingSeconds(countdownAt, serverNow, serverRemaining)")[1].split("function bootstrapServerTimeFromDom")[0]
    assert "queueJobRemainingSeconds" in movement
    remain = src.split("function timerRemainingSeconds(el, serverNow)")[1].split("function formatTimerDisplay")[0]
    assert 'scope === "overview" && kind === "fleet"' in remain
    assert "syncTimerElement(el)" in remain.split("function timerRemainingSeconds")[0] or "syncTimerElement(el);" in remain
    sync = src.split("function syncTimerElement(el)")[1].split("function timerRemainingSeconds")[0]
    assert "parseTimerTarget" in sync
    assert "data-finish-time" in sync
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert "GC.startProgressTicker();" in apply
    assert "syncServerClockFromState(data)" in apply
    build_partial = _read("templates/partials/build_queue.html")
    assert 'data-timer-target' in build_partial
    assert 'id="build-eta-live"' in build_partial
    research_partial = _read("templates/partials/research_queue.html")
    assert 'data-timer-target' in research_partial
    shipyard_partial = _read("templates/partials/shipyard_queue.html")
    assert 'data-timer-target' in shipyard_partial
    render_card_queue = src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("function _syncBuildQueueLiveState")[0]
    assert "applyQueueJobTimerAttrs" in render_card_queue
    assert "dataset.queueSig" in render_card_queue
    render_research = src.split("function renderResearchQueue(researchRaw)")[1].split("function _applyProgressFill")[0]
    assert "GC.startProgressTicker();" in render_research
    update_all = src.split("function updateAllProgressBars(serverNow)")[1].split("function updateBuildQueueLive")[0]
    assert "parseTimerTarget" in update_all
    assert "queueJobRemainingSeconds" in update_all.split("const buildActive")[1].split("const researchActive")[0]

    src = _read("static/main.js")
    assert "function patchShellHudFromState(data, opts)" in src
    assert "GC.patchShellHudFromState = patchShellHudFromState" in src
    assert "GC.mergeLastState = function mergeLastState" in src
    assert "function patchShellHudLiveResources(metal, crystal, fuelCells)" in src
    hud_section = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert 'getElementById("resource-bar")' in hud_section
    assert 'document.querySelectorAll(".res-value.metal, [data-res=\\"metal\\"]")' not in hud_section
    apply_section = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert "patchShellHudFromState(coercePollUnreadForHud(data, reason), { forceResourceBar, skipMessagesUnread })" in apply_section
    assert "scoreStale" in hud_section
    assert "data-hud-online-value" in hud_section or "data-hud-online-value" in _read("templates/base.html")
    messages_js = _read("static/js/messages.js")
    assert "GC.mergeLastState({ unread_messages_count: n }" in messages_js
    assert "GC.updateMessagesUnreadBadges(n)" not in messages_js.split("function updateLocalUnread")[1].split("function refreshBadgesFromServer")[0]


def test_main_js_gc542_research_shipyard_queue_timer_parity():
    src = _read("static/main.js")
    assert "function resolveQueueJobFinishTime(job)" in src
    assert "function resolveQueueJobCountdownAt(job)" in src
    assert "function applyQueueJobTimerAttrs(el, finishTime, kind, refreshOnZero, remaining)" in src
    assert "function patchResearchPanelFromState(data)" in src
    assert "function patchShipyardPanelFromState(data, activePlanetId)" in src
    assert "function patchShipyardCardQueues(page, queueData)" in src
    parse_section = src.split("function parseTimerTarget(raw)")[1].split("function resolveQueueJobFinishTime")[0]
    assert r"/^\d+(\.\d+)?$/" in parse_section
    research_partial = _read("templates/partials/research_queue.html")
    shipyard_partial = _read("templates/partials/shipyard_queue.html")
    assert 'data-timer-target' in research_partial
    assert 'data-countdown-at' in research_partial
    assert 'data-timer-kind="research"' in research_partial
    assert 'data-timer-target' in shipyard_partial
    assert 'data-countdown-at' in shipyard_partial
    assert 'data-timer-kind="shipyard"' in shipyard_partial
    render_card_queue = src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("GC.clearBuildingCardQueue")[0]
    assert "applyQueueJobTimerAttrs" in render_card_queue
    assert "data-countdown-at" in _read("templates/shipyard.html") or "countdown-at" in render_card_queue
    render_shipyard = src.split("function renderShipyardQueue(page, queueData)")[1].split("function parseShipyardPageData")[0]
    assert "patchShipyardCardQueues" in render_shipyard
    assert "_updateShipyardQueueCompact" in render_shipyard
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert "patchResearchPanelFromState(data)" in apply
    assert "patchShipyardPanelFromState(data, activePlanetId)" in apply
    assert "lastHadActiveShipyard" in apply
    progress = src.split("function updateAllProgressBars(serverNow)")[1].split("function updateBuildQueueLive")[0]
    assert "RESEARCHQ.active.finishTime" in progress
    assert "SHIPYARDQ.active.finishTime" in progress
    assert "DEFENSEQ.active.finishTime" in progress
    assert "assignMonotonicServerRemaining(defenseActive" in progress
    patch_queues = src.split("function patchCardQueuesFromOwnerMap(page, byOwner, listCards, ownerKeyFromCard, findCard)")[1].split("GC.renderCardQueueBlock = function renderCardQueueBlock")[0]
    assert "activeKeys.has(key)" in patch_queues
    assert "GC.clearCardQueueBlock(card)" in patch_queues
    patch_sy = src.split("function patchShipyardCardQueues(page, queueData)")[1].split("function shipyardIconUrl")[0]
    assert "patchCardQueuesFromOwnerMap" in patch_sy
    assert "GC.clearCardQueueBlock(card);" not in patch_sy.split("patchCardQueuesFromOwnerMap")[0]
    card_queue = src.split("function cardQueueJobSignature(queueJob)")[1].split("function canPatchCardQueueInPlace")[0]
    assert "target_amount" in card_queue
    assert "function canPatchCardQueueInPlace(existing, queueJob)" in src
    assert "function cardQueueTimerTarget(queueJob, isActive)" in src
    render_card = src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("function _syncBuildQueueLiveState")[0]
    assert "cardQueueTimerTarget(queueJob, isActive)" in render_card
    render_sy = src.split("function renderShipyardQueue(page, queueData)")[1].split("function parseShipyardPageData")[0]
    assert "if (!jobs.length)" in render_sy
    assert "patchShipyardCardQueues(page, qd)" in render_sy.split("if (!overdue)")[0] or "patchShipyardCardQueues(page, qd)" in render_sy
    action = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert "_lastDefenseQueueSignature = \"\"" in action
    assert "_lastPePlanetTechQueueSignature = \"\"" in action


def test_main_js_gc631_formatted_unit_inputs_and_queue_clear():
    """GC-631: de-DE qty parsing, readNumberInput submit, production queue clear."""
    src = _read("static/main.js")
    parse_fn = src.split("function parseIntNumber(n)")[1].split("function formatNumber")[0]
    assert r"^-?\d{1,3}(\.\d{3})+$" in parse_fn
    assert "GC.readNumberInput = readNumberInput" in src
    shipyard_bind = src.split("function bindShipyardOnce()")[1].split("function initShipyard")[0]
    assert "readNumberInput(qtyInp)" in shipyard_bind
    assert "parseIntNumber(maxBtn.dataset.maxQty" in shipyard_bind
    assert "function clearProductionCardQueueState(card)" in src
    patch_sy = src.split("function patchShipyardCardQueues(page, queueData)")[1].split("function shipyardIconUrl")[0]
    assert "queueData?.card_jobs_by_owner" in patch_sy
    assert ": {}" in patch_sy
    render_sy = src.split("function renderShipyardQueue(page, queueData)")[1].split("function parseShipyardPageData")[0]
    assert "card_jobs_by_owner: {}" in render_sy
    assert "clearProductionCardQueueState(card)" in src.split("function applyShipyardState(page, data)")[1].split("async function refreshShipyardState")[0]
    shipyard_tpl = _read("templates/shipyard.html")
    assert 'data-shipyard-qty' in shipyard_tpl
    assert 'type="text"' in shipyard_tpl
    assert 'type="number"' not in shipyard_tpl.split("data-shipyard-qty")[0][-400:]
    assert "shipyard_parallel_capacity" in shipyard_tpl
    defense_tpl = _read("templates/defense.html")
    assert "defense_production_capacity" in defense_tpl
    de = _read("locales/de.json")
    assert '"shipyard_parallel_capacity"' in de
    assert '"defense_production_capacity"' in de


def test_main_js_gc632_production_stat_chips():
    """GC-632: compact cycle/parallel stat chips replace long inline production text."""
    src = _read("static/main.js")
    assert "function patchProductionStatChips(card, cycleSeconds, batchCapacity, tt)" in src
    assert "fmtIntParts(cap)" in src.split("function patchProductionStatChips")[1].split("function applyShipyardShipCard")[0]
    assert ".shipyard-ship-build-time" not in src.split("function applyShipyardShipCard")[1].split("function applyShipyardState")[0]
    assert "patchProductionStatChips(card, ship.build_seconds, batchCap, tt)" in src
    assert "patchProductionStatChips(card, unit.build_seconds, batchCap, tt)" in src
    macro = _read("templates/partials/progression_cards.html")
    assert "render_production_stat_chips" in macro
    assert "gc-prod-stat-grid" in macro
    assert "data-prod-cycle-seconds" in macro
    assert "data-prod-batch-capacity" in macro
    shipyard_tpl = _read("templates/shipyard.html")
    assert "render_production_stat_chips" in shipyard_tpl
    assert "shipyard-ship-build-time" not in shipyard_tpl
    defense_tpl = _read("templates/defense.html")
    assert "render_production_stat_chips" in defense_tpl
    assert "shipyard-ship-build-time" not in defense_tpl
    css = _read("static/style.css")
    assert ".gc-prod-stat-grid" in css
    assert ".gc-prod-stat-chip" in css
    de = _read("locales/de.json")
    en = _read("locales/en.json")
    assert '"prod_stat_cycle_label"' in de
    assert '"prod_stat_parallel_label"' in de
    assert '"prod_stat_cycle_label"' in en
    assert '"prod_stat_parallel_label"' in en


def test_main_js_gc633_weighted_capacity_and_queue_clear():
    """GC-633: per-unit effective_batch_capacity; hard clear when queue empty."""
    src = _read("static/main.js")
    assert "ship.effective_batch_capacity" in src.split("function applyShipyardShipCard")[1].split("function applyShipyardState")[0]
    assert "unit.effective_batch_capacity" in src.split("function applyDefenseUnitCard")[1].split("async function refreshDefenseState")[0]
    assert "function clearAllProductionCardQueues(page)" in src
    shipyard_py = _read("game/shipyard.py")
    assert "def unit_batch_capacity(" in shipyard_py
    assert "def unit_production_weight(" in shipyard_py
    defense_py = _read("game/defense.py")
    assert "_batch_capacity_for_defense" in defense_py
    assert "orbital_production_batch_capacity(shipyard_level)" not in defense_py.split("def progressive_units_to_deliver")[1].split("def list_defense_queue_rows")[0]


def test_main_js_gc630_shipyard_game_state_panel_patch():
    """GC-630: game-state shipyard slice patches queue + stock via applyShipyardState."""
    src = _read("static/main.js")
    patch = src.split("function patchShipyardPanelFromState(data, activePlanetId)")[1].split("function patchDefensePanelFromGameState")[0]
    assert "applyShipyardState(page" in patch
    assert "data?.shipyard" in patch
    assert "slice.queue" in patch
    live = _read("game/live_state.py")
    assert "shipyard_panel_for_game_state" in live
    app_py = _read("app.py")
    assert "shipyard_panel_for_game_state" in app_py
    shipyard_py = _read("game/shipyard.py")
    assert "orbital_production_batch_capacity" in shipyard_py
    assert "production_job_duration_seconds" in shipyard_py


def test_main_js_gc640_global_fleet_hud():
    """GC-654: global fleet drawer under resource bar via game-state poll."""
    src = _read("static/main.js")
    assert "function renderGlobalFleetHud(fleetsRaw)" in src
    assert "GC.renderGlobalFleetHud = renderGlobalFleetHud" in src
    assert "function initGlobalFleetDrawer()" in src
    assert "GC.initGlobalFleetDrawer = initGlobalFleetDrawer" in src
    assert "normalizeActiveFleetsPayload" in src
    assert "FLEET_DRAWER_LS_EXPANDED" in src
    assert "FLEET_DRAWER_LS_SHOW_ALL" in src
    assert "/api/fleet/recall" in src
    hud = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "renderGlobalFleetHud(data.active_fleets)" in hud
    assert "updateFleetNavBadge(count)" in src
    base = _read("templates/base.html")
    assert "global-fleet-drawer-root" in base
    assert "data-global-fleet-drawer" in base
    assert "data-fleet-global-hud" not in base
    assert "data-fleet-drawer-fleet-link" not in base
    assert "data-fleet-nav-badge" in base
    live = _read("game/live_state.py")
    assert "fleet_hud_for_game_state" in live
    assert "build_active_fleets_payload" in live
    app_py = _read("app.py")
    assert "fleet_hud_for_game_state" in app_py
    assert "/api/fleet/recall" in app_py
    css = _read("static/style.css")
    assert ".gc-fleet-drawer-root" in css
    assert ".gc-fleet-drawer-toggle" in css
    assert ".gc-fleet-drawer-panel" in css
    assert ".gc-fleet-drawer-row" in css
    assert ".gc-fleet-nav-badge" in css
    fleet_py = _read("game/fleet.py")
    assert "build_active_fleets_payload" in fleet_py
    assert "recall_fleet_movement" in fleet_py


def test_main_js_gc657_fleet_drawer_timer_selection_separation():
    """GC-657: fleet drawer selection is UI-only; timers stay on arrival_at."""
    src = _read("static/main.js")
    css = _read("static/style.css")
    assert "fleetDrawerCountdownAt" in src
    assert "_fleetDrawerSelectedId" in src
    assert "updateFleetDrawerRowTimers" in src
    assert "formatFleetDrawerRemaining" in src
    assert "fleet_drawer_arrival_chip" in src
    assert "syncFleetDrawerRowLayout" in src
    assert "data-fleet-drawer-arrival-compact" in src
    assert "data-fleet-drawer-detail" in src
    assert "fleet_drawer_remaining" in _read("locales/de.json")
    assert ".gc-fleet-drawer-row.is-selected" in css
    assert "gc-fleet-drawer-timer-pulse" in css
    countdown = src.split("function patchFleetDrawerRowCountdown(row, mv)")[1].split("function createFleetDrawerFlightRoute")[0]
    assert "fleetDrawerCountdownAt(mv)" in countdown
    assert "prevKey !== countdownKey" in countdown


def test_main_js_gc654b_fleet_drawer_visual_polish():
    """GC-654B: drawer flight route, mission tooltip, no notch."""
    src = _read("static/main.js")
    css = _read("static/style.css")
    base = _read("templates/base.html")
    fleet_py = _read("game/fleet.py")
    assert "syncFleetDrawerList" in src
    assert "fleetDrawerRowCanAct" in src
    assert "patchFleetDrawerRowFlight" in src
    assert "data-fleet-flight-route" in src
    assert "gc-fleet-flight-dot" in css
    assert "gc-fleet-flight-stage" in css
    assert "gc-fleet-flight-timer" in css
    assert "gc-fleet-drawer-tooltip" in css
    assert ".gc-fleet-drawer-root::before" not in css
    assert "data-fleet-drawer-fleet-link" not in base
    assert "data-fleet-drawer-tooltip" in base
    assert "_movement_progress_pct" in fleet_py
    assert "ships_breakdown" in fleet_py


def test_main_js_gc640b_fleet_page_visual_redesign():
    """GC-640B/640E: fleet command layout evolved to OGame-like table + integrated logistics."""
    tpl = _read("templates/fleet.html")
    css = _read("static/style.css")
    js = _read("static/main.js")
    assert "fleet-ogame-stack" in tpl
    assert "fleet-ship-table" in tpl
    assert "data-fleet-mode-tab" in tpl
    assert "data-fleet-mode-panel" in tpl
    assert 'id="logistics-page"' in tpl
    assert "data-ship-max-image" in tpl
    assert "fleet-ship-group-row" in tpl
    assert "fleet-shipyard-link-panel" not in tpl
    assert "fleet-logistics-cta" not in tpl
    assert ".fleet-ship-table" in css
    assert ".fleet-ogame-stack" in css
    assert "data-ship-max-image" in js
    assert "function applyFleetPageMode(page)" in js
    assert "function renderGlobalFleetHud(fleetsRaw)" in js


def test_main_js_gc640c_fleet_dense_ship_cards():
    """GC-640C/640F: compact ship list — horizontal table rows, no inner scroll."""
    css = _read("static/style.css")
    tpl = _read("templates/fleet.html")
    assert ".fleet-ship-table" in css
    assert "fleet-ship-thumb" in css
    assert "width: 32px" in css
    assert "overflow: visible" in css.split(".fleet-ship-table-wrap")[1].split(".fleet-ship-table")[0]
    assert "max-height: none" in css.split(".fleet-ship-table-wrap")[1].split(".fleet-ship-table")[0]
    assert "fleet-ship-table" in tpl


def test_main_js_gc640f_fleet_no_scroll_ship_selector():
    """GC-640F: ship table stays horizontal on desktop; logistics rows stay scoped."""
    css = _read("static/style.css")
    assert ".fleet-ships-grid > .fleet-ship-row:not(.fleet-ship-card)" in css
    assert "display: table-row" in css
    assert "table-layout: fixed" in css
    assert "height: 40px" in css.split(".fleet-ship-table tbody tr.fleet-ship-row")[1].split(".fleet-ship-table tbody td")[0]
    assert ".fleet-ship-row:not(.fleet-ship-card)" not in css.replace(".fleet-ships-grid > .fleet-ship-row:not(.fleet-ship-card)", "")


def test_main_js_gc640g_fleet_mode_tabs_compact():
    """GC-640G: mode tabs are compact inline pills, not full-width nav bars."""
    tpl = _read("templates/fleet.html")
    css = _read("static/style.css")
    js = _read("static/main.js")
    assert "fleet-mode-tab gc-nav-link" not in tpl
    assert 'class="fleet-mode-tab' in tpl
    tabs_css = css.split(".fleet-mode-tabs")[1].split(".fleet-mode-tab{")[0]
    assert "display: flex" in tabs_css
    assert "width: auto" in css.split(".fleet-mode-tab{")[1].split(".fleet-mode-tab:hover")[0]
    assert "min-height: 34px" in css.split(".fleet-mode-tab{")[1].split(".fleet-mode-tab:hover")[0]
    assert "a.fleet-mode-tab" in js


def test_main_js_gc640h_fleet_mode_tabs_visual_polish():
    """GC-640H/J: mode tab bar is opaque; active uses outline/glow not cyan fill."""
    css = _read("static/style.css")
    tabs_bar = css.split(".fleet-mode-tabs{")[1].split(".fleet-mode-tab{")[0]
    tab_base = css.split(".fleet-mode-tab{")[1].split(".fleet-mode-tab:hover")[0]
    tab_active = css.split(".fleet-mode-tab.active,")[1].split("@media (max-width: 640px)")[0]
    assert "rgba(3, 12, 18, 0.96)" in tabs_bar
    assert "backdrop-filter: none" in tabs_bar
    assert "linear-gradient(180deg, #081824, #040b12)" in tab_base
    assert "linear-gradient(180deg, #0d3442, #061823)" in tab_active
    assert "#2ff3ff" in tab_active
    assert "linear-gradient(180deg, #35f2ff, #079fbd)" not in tab_active


def test_main_js_gc640j_fleet_button_consistency():
    """GC-640J: mode tabs and quicktargets share dezente dark outline control styling."""
    tpl = _read("templates/fleet.html")
    css = _read("static/style.css")
    assert "data-fleet-colony-chips" in tpl
    assert 'data-fleet-colony-chips hidden' not in tpl
    assert "fleet-colony-chips--compact" in tpl
    chip_css = css.split(".fleet-colony-chips--compact .fleet-colony-chip{")[1].split(".fleet-colony-chips--compact .fleet-colony-chip::after")[0]
    assert "linear-gradient(180deg, #081824, #040b12)" in chip_css
    assert "min-height: 32px" in chip_css
    tab_active = css.split(".fleet-mode-tab.active,")[1].split("@media (max-width: 640px)")[0]
    selected_css = css.split(".fleet-colony-chips--compact .fleet-colony-chip.is-selected{")[1].split(".fleet-colony-chips--compact .fleet-colony-chip.is-selected .fleet-chip-label")[0]
    assert "linear-gradient(180deg, #0d3442, #061823)" in tab_active
    assert "linear-gradient(180deg, #0d3442, #061823)" in selected_css
    assert "linear-gradient(180deg, #35f2ff, #079fbd)" not in selected_css
    expo_css = css.split(".fleet-colony-chips--compact .fleet-colony-chip--expedition.is-selected{")[1].split(".fleet-colony-chips--compact .fleet-colony-chip--expedition.is-selected .fleet-chip-label")[0]
    assert "linear-gradient(180deg, #3d2e0c, #241806)" in expo_css
    assert "linear-gradient(180deg, #ffd45a, #c68a00)" not in expo_css


def test_main_js_gc640e_fleet_logistics_merge():
    """GC-640E: logistics embedded on /fleet; /logistics redirects; sidebar has no logistics nav."""
    tpl = _read("templates/fleet.html")
    sidebar = _read("templates/partials/sidebar.html")
    app_py = _read("app.py")
    assert "partials/fleet_logistics_body.html" in tpl
    assert 'data-nav-module="logistics"' not in sidebar
    assert "nav_logistics" not in sidebar
    assert "build_logistics_page_context" in app_py
    logistics_view = app_py.split("def logistics_view")[1].split("def fleet_view")[0]
    assert "redirect" in logistics_view
    assert "mode=" in logistics_view


def test_main_js_gc546d_production_completion_poll_storm_guards():
    """GC-546D: debounced completion sync, no per-poll shipyard/defense API storm."""
    src = _read("static/main.js")

    assert "function requestProductionCompletionSync(opts)" in src
    assert "PRODUCTION_COMPLETION_DEBOUNCE_MS = 1100" in src
    assert "function _timerZeroAlreadyFired(el, target)" in src
    assert "el.dataset.refreshFiredAt" in src
    assert "function refreshShipyardStateCoalesced(page)" in src
    assert "function refreshDefenseStateCoalesced(page)" in src
    assert "_shipyardApiInFlight" in src
    assert "_defenseApiInFlight" in src

    prod_sync = src.split("function requestProductionCompletionSync(opts)")[1].split("function requestTimerZeroRefresh")[0]
    assert "pending.gameState" in prod_sync
    assert "refreshShipyardStateCoalesced(syPage)" in prod_sync
    assert "pending.defense && !pending.gameState" in prod_sync

    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert "syncProductionPanelsAfterGameState(data, reason, activePlanetId)" in apply
    assert "function patchDefensePanelFromGameState(data, activePlanetId)" in src
    assert "scheduleShipyardRefreshFromState(true)" not in apply
    assert "scheduleDefenseRefreshFromState(true)" not in apply

    sync_prod = src.split("function syncProductionPanelsAfterGameState(data, reason, activePlanetId)")[1].split("function applyGameStateData")[0]
    assert "patchDefensePanelFromGameState(data, activePlanetId)" in sync_prod
    assert "completionReason" in sync_prod

    progress = src.split("function updateAllProgressBars(serverNow)")[1].split("function updateBuildQueueLive")[0]
    assert 'document.getElementById("shipyard-page")?.querySelector(".shipyard-job.shipyard-job-active")' in progress
    assert 'document.getElementById("defense-page")?.querySelector(".shipyard-job.shipyard-job-active")' in progress
    assert "requestProductionCompletionSync" in progress
    assert "requestQueueTimerZeroRefresh" in progress
    assert "scheduleShipyardRefreshFromState(true)" not in progress
    assert "scheduleDefenseRefreshFromState(true)" not in progress

    finish = src.split("function requestFinishRefresh(type)")[1].split("function releaseFinishRefreshLock")[0]
    assert 'type === "shipyard"' in finish
    assert "requestProductionCompletionSync({ gameState: true, shipyard: true })" in finish

    defense_timers = src.split("function startDefenseTimers()")[1].split("function bindDefenseOnce")[0]
    assert "setInterval" not in defense_timers
    assert "GC.startProgressTicker()" in defense_timers

    refresh_gs = src.split("async function refreshGameState(reason)")[1].split("GC.refreshGameState = refreshGameState")[0]
    assert "_queuedChainRefreshReason" in refresh_gs
    assert "if (!_queuedChainRefreshReason) _queuedChainRefreshReason = reasonStr" in refresh_gs

    render_sy = src.split("function renderShipyardQueue(page, queueData)")[1].split("function parseShipyardPageData")[0]
    assert "_productionZeroHandled.shipyard" in render_sy
    render_def = src.split("function renderDefenseQueue(page, queuePayload)")[1].split("function bindDefenseOnce")[0]
    assert "_productionZeroHandled.defense" in render_def


def test_main_js_building_upgrade_icon_not_overwritten_by_poll():
    """Live game-state must not replace gc-bld-head-action-btn + icon with text label."""
    src = _read("static/main.js")
    block = src.split("const btn = document.getElementById(cfg.btnId)")[1].split("});")[0]
    assert "gc-bld-head-action-btn" in block
    assert "textContent = btnLabel" not in block.split("gc-bld-head-action-btn")[0]


def test_messages_js_report_unit_images():
    src = _read("static/js/messages.js")
    assert "function unitIconUrl(key, defenseStock)" in src
    assert "gc-combat-unit-chip-img" in src
    assert "reportBuildingChipImg" in src
    unread_local = src.split("function updateLocalUnread")[1].split("function refreshBadgesFromServer")[0]
    assert "GC.mergeLastState({ unread_messages_count: n }" in unread_local
    assert "GC.updateMessagesUnreadBadges(n)" not in unread_local


def test_main_js_gc546e_stale_poll_unread_guard():
    """GC-546E: game-state must not restore stale unread after messages.js sync."""
    src = _read("static/main.js")
    assert "function coercePollUnreadForHud(data, reason)" in src
    assert "_messagesUnreadLocalAt" in src
    assert "MESSAGES_UNREAD_LOCAL_GUARD_MS" in src
    coerce = src.split("function coercePollUnreadForHud(data, reason)")[1].split("function updateMessagesUnreadBadges")[0]
    assert "incomingUnread" in coerce
    assert "incomingUnread > _lastMessagesUnreadPoll" in coerce
    assert 'reason || "") !== "poll"' not in coerce
    assert 'reason || "") !== "poll"' not in coerce
    merge = src.split("GC.mergeLastState = function mergeLastState")[1].split("function patchOverviewScoreFromState")[0]
    assert '_messagesUnreadLocalAt = Date.now()' in merge
    assert 'String(reason || "").includes("messages")' in merge
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert "coercePollUnreadForHud(data, reason)" in apply
    messages_js = _read("static/js/messages.js")
    open_report = messages_js.split("async function openInboxReportById(messageId, kind)")[1].split("async function openCombatReportById")[0]
    assert "syncUnreadFromResponse(data)" in open_report


def test_main_js_gc546b_building_requirements_live_patch():
    """GC-546B: patchBuildingPanel must refresh requirement box + action on queue finish."""
    src = _read("static/main.js")
    assert "function patchBuildingRequirements(row, b)" in src
    patch = src.split("function patchBuildingPanel(rowsByTab, buildQueueRaw)")[1].split("function patchResearchEffects")[0]
    assert "patchBuildingRequirements(row, b)" in patch
    assert "applyBuildingRowState(row, b)" in patch
    assert "syncBuildingHeadAction(actionCell, b, summary, bqQueueFull)" in patch
    progress = src.split("function updateAllProgressBars(serverNow)")[1].split("function updateBuildQueueLive")[0]
    assert "_buildZeroHandled" in progress
    buildings_html = _read("templates/buildings.html")
    assert "data-building-req" in buildings_html


def test_main_js_gc546a_score_delta_deduplication():
    """GC-546A/A2: one delta event per score landing; HUD-only render."""
    src = _read("static/main.js")
    score_state = src.split("const _scoreState = {")[1].split("// Mapping: Buildings")[0]
    assert "lastDeltaEventTotal" in score_state
    assert "pendingOverviewDelta" not in score_state
    assert "function _purgeAllScoreDeltaNodes()" in src
    assert "function _resolveHudScoreDeltaAnchor()" in src
    assert "function _scheduleScoreDeltaRemoval(deltaEl)" in src
    purge = src.split("function _purgeAllScoreDeltaNodes()")[1].split("function _resolveHudScoreDeltaAnchor")[0]
    assert 'document.querySelectorAll(".gc-score-delta")' in purge
    show = src.split("function showScoreDelta(deltaValue, landingTotal = null)")[1].split("// Mapping: Buildings")[0]
    assert "_purgeAllScoreDeltaNodes()" in show
    assert "document.createElement(\"span\")" in show
    assert "animationend" in src.split("function _scheduleScoreDeltaRemoval")[1].split("function pulseScore")[0]
    hud = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "showScoreDelta(delta, serverTotal)" in hud
    overview = src.split("function patchOverviewScoreFromState(data)")[1].split("function patchResearchPanelFromState")[0]
    assert "showScoreDelta" not in overview
    css = _read("static/style.css")
    assert "animation-fill-mode: none" in css.split(".gc-score-pill .gc-score-delta.show")[1][:220]


def test_main_js_gc547_gpu_idle_visual_loop_guards():
    """GC-547: idle/tab-hidden must not run permanent visual loops."""
    src = _read("static/main.js")
    css = _read("static/style.css")

    assert "function shouldRunVisualLoops()" in src
    assert "function pauseVisualLoops()" in src
    assert "function resumeVisualLoops()" in src
    assert "function syncPerfBodyClasses()" in src
    assert "GC.shouldRunVisualLoops = shouldRunVisualLoops" in src
    assert "initMotionPreferenceListener()" in src
    assert "pauseVisualLoops()" in src.split("visibilitychange")[1][:500]
    assert "resumeVisualLoops()" in src.split("visibilitychange")[1][:700]
    assert "RESOURCE_TICKER_MS_IDLE" in src
    assert "function pauseResourceTicker()" in src

    ticker = src.split("GC.startProgressTicker = function startProgressTicker()")[1].split("GC.stopPolling")[0]
    assert "shouldRunVisualLoops()" in ticker
    assert "requestAnimationFrame(tick)" not in ticker

    progress = src.split("function _hasActiveProgressJobs()")[1].split("// progress ticker")[0]
    assert "_hasVisibleOverviewResearchTimer()" in progress
    assert 'getElementById("overview-research-active")' not in progress

    assert "gc-perf-idle" in css
    assert "gc-tab-hidden" in css
    assert "gc-bld-delta-pulse" not in css
    assert "ease-in-out infinite" not in css.split("gc-prog-affordable")[1][:200]
    landscape = css.split("gc-has-planet-landscape .gc-sidebar")[1][:350]
    assert "backdrop-filter" not in landscape


def test_style_gc547b_landing_login_gpu_compositor():
    """GC-547B: Landing/Login idle must not stack fullscreen GPU compositor layers."""
    css = _read("static/style.css")
    base = _read("templates/base.html")

    assert "GC-547B" in css
    block = css.split("GC-547B")[1].split("Everything above bg")[0]
    assert "body.gc-body-simple .gc-bg::after" in block
    assert "body.gc-body-simple .gc-bg-simple" in block
    assert "display: none" in block
    assert "body.gc-body-simple .gc-header" in block
    assert "backdrop-filter: none" in block
    assert "body.gc-body-simple .landing-title" in block
    assert "text-shadow: none" in block.split("body.gc-body-simple .landing-title")[1][:120]

    assert "gc-perf-idle" in base
    assert "gc-bg-simple" in base
    assert "{% if SIMPLE_LAYOUT %}gc-body-simple" in base


def test_main_js_gc547c_perf_idle_fps_compositor():
    """GC-547C: simple pages stay perf-idle; idle hides compositor repaint layers."""
    src = _read("static/main.js")
    css = _read("static/style.css")

    assert "function isPerfIdle()" in src
    sync = src.split("function syncPerfBodyClasses()")[1].split("function pauseVisualLoops()")[0]
    assert "isPerfIdle()" in sync
    assert "!shouldRunGameLoop()" in src.split("function isPerfIdle()")[1].split("function syncPerfBodyClasses()")[0]

    assert "isPerfIdle()" in src.split("function startResourceTicker()")[1][:200]
    assert "isPerfIdle()" in src.split("function tickLiveResourceBar()")[1][:200]

    assert "GC-547C" in css
    block = css.split("GC-547C")[1][:900]
    assert "body.gc-perf-idle:not(.gc-has-planet-landscape) .gc-bg" in block
    assert "body.gc-perf-idle.gc-has-planet-landscape .gc-bg" in block
    assert "display: none" in block
    assert "display: block" in block
    assert "body.gc-perf-idle .gc-panel::before" in block
    assert "body.gc-perf-idle .gc-header" in block
    assert "backdrop-filter: none" in block


def test_main_js_gc548_landscape_visible_on_perf_idle_boot():
    """GC-548: landscape from SSR/lastState before game-state; perf-idle must not hide it."""
    src = _read("static/main.js")
    css = _read("static/style.css")

    assert "function bootstrapPlanetLandscapeFromBoot()" in src
    assert "bootstrapPlanetLandscapeFromBoot()" in src.split("function initShellOnce()")[1][:600]
    assert "applyPlanetLandscapeFromState(GC.lastState)" in src

    clear = src.split("function applyPlanetLandscapeFromState(data)")[1].split("function bootstrapPlanetLandscapeFromBoot")[0]
    assert 'classList.remove("gc-has-planet-landscape")' in clear

    block = css.split("GC-547C")[1][:900]
    assert "gc-has-planet-landscape" in block
    assert "body.gc-perf-idle.gc-has-planet-landscape .gc-bg" in block


def test_main_js_gc549_ship_defense_icons_use_png():
    """GC-549: shipyard/defense cards use raster PNG assets, not SVG placeholders."""
    src = _read("static/main.js")
    ship_fn = src.split("function shipyardIconUrl(shipKey)")[1].split("function ")[0]
    defense_fn = src.split("function defenseIconUrl(defenseKey)")[1].split("function ")[0]
    assert "/static/img/ships/${sk}.png" in ship_fn
    assert ".svg" not in ship_fn
    assert "/static/img/defense/" in defense_fn
    assert ".png`" in defense_fn
    assert ".svg" not in defense_fn

    defense_tpl = _read("templates/defense.html")
    assert "unit.defense_key ~ '.png'" in defense_tpl


def test_main_js_gc550b_compact_head_actions():
    """GC-550B: compact header actions, single hero image."""
    src = _read("static/main.js")
    buildings_html = _read("templates/buildings.html")
    research_html = _read("templates/research.html")
    css = _read("static/style.css")

    assert "render_building_head_action" in buildings_html
    assert "render_research_head_action" in research_html
    assert "gc-bld-card-head-action" in buildings_html
    assert "gc-bld-head-action-btn--go" in buildings_html
    assert "gc-bld-card-icon--title" not in buildings_html
    assert "gc-bld-card-action-wrap" not in buildings_html
    assert "gc-bld-card-action-wrap" not in research_html
    assert "gc-bld-head-action-btn" in src
    assert "hideBuildingsSubnav" in src.split("function initPage")[1][:800]
    assert ".gc-bld-head-action-btn{" in css


def test_main_js_gc550c_buildings_hero_queue_and_subnav():
    """GC-550C: hero progress overlay, same-building re-queue, subnav collapse."""
    src = _read("static/main.js")
    buildings_html = _read("templates/buildings.html")
    research_html = _read("templates/research.html")
    base_html = _read("templates/base.html")
    sidebar_html = _read("templates/partials/sidebar.html")
    css = _read("static/style.css")

    assert "render_hero_img_stack" in buildings_html
    assert "render_hero_time_chip" in buildings_html
    assert "data-hero-time-chip" in buildings_html
    assert "gc-bld-hero-img-stack" in buildings_html
    assert "gc-bld-card-time" not in buildings_html
    assert "render_hero_time_chip" in research_html
    assert "gc-bld-card-hero-img--muted" in css
    assert "gc-bld-hero-time-chip" in css
    assert "renderHeroQueueOverlay" in src
    assert "applyHeroImageProgress" in src
    assert "ensureHeroQueuedBadgeTimer" in src
    assert "queue_starts_in" in buildings_html
    assert "queue_starts_in" in research_html
    assert "gc-bld-card-hero-overlay" not in buildings_html
    assert "gc-bld-card-hero-overlay" not in research_html
    assert "grayscale(1)" not in css.split(".gc-bld-hero-img-stack .gc-bld-card-hero-img--muted")[1].split("}")[0]
    assert "saturate(" in css
    assert "gc-nav-sub--collapsed" in src
    assert "BUILDINGS_NAV_PAGES" in src
    assert "gc-nav-buildings-toggle" in src
    assert "syncBuildingsSubnavFromState" in src
    assert sidebar_html.count('id="gc-nav-buildings-sub"') == 1
    assert ".gc-nav-group-body" in css
    assert "if (domain === \"building\" || domain === \"research\")" in src

    building_action = src.split("function renderBuildingActionCell")[1].split("function patchBuildingPanel")[0]
    research_action = src.split("function renderResearchActionCell")[1].split("function patchBuildingPanel")[0]
    assert "gc-bld-head-action-btn--busy" not in building_action
    assert "if (b.queue_job)" not in building_action
    assert "gc-bld-head-action-btn--busy" not in research_action
    assert "if (tech.queue_job)" not in research_action

    update_build = src.split("function updateBuildQueueActions")[1].split("function _stripCardQueueOwnerClasses")[0]
    update_research = src.split("function updateResearchQueueActions")[1].split("function updateBuildQueueActions")[0]
    assert "gc-building-card--in-queue" not in update_build
    assert "gc-research-card--in-queue" not in update_research


def test_main_js_gc550_buildings_ux_contract():
    """GC-550/550A: hero cards, sidebar-only building categories, queue slot below action."""
    src = _read("static/main.js")
    buildings_html = _read("templates/buildings.html")
    research_html = _read("templates/research.html")
    shipyard_html = _read("templates/shipyard.html")
    defense_html = _read("templates/defense.html")
    base_html = _read("templates/base.html")
    sidebar_html = _read("templates/partials/sidebar.html")
    css = _read("static/style.css")
    de = _read("locales/de.json")

    assert "gc-bld-card-hero" in buildings_html
    assert "building-tabs--prominent" not in buildings_html
    assert "data-buildings-tab-panels" in buildings_html
    assert "gc-bld-hero-queue" in buildings_html
    assert "gc-bld-card-hero" in research_html
    assert "gc-bld-card-hero" in shipyard_html
    assert "gc-bld-card-icon--title" not in shipyard_html
    assert "gc-bld-card-action-wrap" in shipyard_html
    assert "gc-bld-card-hero" in defense_html
    assert "gc-bld-card-icon--title" not in defense_html
    assert "gc-nav-buildings-sub" in sidebar_html
    assert "data-building-tab" in sidebar_html
    assert 'data-nav-section="economy"' in sidebar_html
    assert 'data-nav-section="military"' in sidebar_html
    assert "syncNavSectionAccordionState" in src
    assert "syncMilitarySubnav" in src
    assert "syncTradingSubnav" in src
    assert "activateBuildingTabByName" in src
    assert "hideBuildingsSubnav" in src
    assert 'querySelector(".gc-bld-card-queue-slot")' in src
    assert '"research_btn_queue_full"' in src
    assert '"shipyard_btn_queue_full"' in src
    assert '"defense_btn_queue_full"' in src
    assert ".gc-bld-card-hero{" in css
    assert '"research_btn_queue_full": "Forschungsliste voll"' in de
    assert '"shipyard_btn_queue_full": "Werftwarteschlange voll"' in de


def test_main_js_gc539_same_type_queue_patch_and_timer_zero():
    """GC-539: job_id keyed card queues; immediate refresh at 0s."""
    src = _read("static/main.js")

    assert "function findCardQueueBlockByJobId(cardEl, jobId)" in src
    assert "function reorderCardQueueBlocks(cardEl)" in src
    assert "function syncCardQueueOwnerClassesFromBlocks(cardEl, fallbackDomain)" in src
    assert "function requestQueueTimerZeroRefresh(meta)" in src
    assert 'GC.refreshGameState("queue_timer_zero")' in src
    assert "refreshShipyardStateCoalesced(syPage)" in src.split("function requestQueueTimerZeroRefresh(meta)")[1].split("function requestTimerZeroRefresh")[0]
    assert "QUEUE_TIMER_ZERO_DEBOUNCE_MS = 80" in src
    assert "function markCardQueueZeroRefresh(block, jobId, finishAt)" in src
    assert "function isQueueTimerComplete(remaining, finishAt, serverNow)" in src
    assert "function queueTimerDisplaySeconds(remaining)" in src

    patch_queues = src.split("function patchCardQueuesFromOwnerMap(page, byOwner, listCards, ownerKeyFromCard, findCard)")[1].split("GC.renderCardQueueBlock = function renderCardQueueBlock")[0]
    assert "activeKeys.has(key)" in patch_queues
    assert "GC.clearCardQueueBlock(card)" in patch_queues
    assert "headJob" in patch_queues
    assert "GC.renderCardQueueBlock(card, headJob)" in patch_queues
    assert "list.forEach((job) => GC.renderCardQueueBlock(card, job))" not in patch_queues
    assert "gc-card-queue-block--advance" in patch_queues

    render_card = src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("function _syncBuildQueueLiveState")[0]
    assert "findCardQueueBlockByJobId(cardEl, jobId)" in render_card
    assert 'querySelector(".gc-bld-card-queue-slot")' in render_card
    assert "dataset.queuePosition" in render_card
    assert "GC.clearCardQueueBlock(cardEl)" not in render_card.split("if (existing) existing.remove();")[0]

    apply_sy = src.split("function applyShipyardShipCard(card, ship, resources, syLevel, tt)")[1].split("function applyShipyardState(page, data)")[0]
    assert "renderCardQueueBlock" not in apply_sy
    assert "clearCardQueueBlock" not in apply_sy

    apply_def = src.split("function applyDefenseUnitCard(page, unit, resources, tt, opts = {})")[1].split("async function refreshDefenseState(page)")[0]
    assert "renderCardQueueBlock" not in apply_def
    assert "clearCardQueueBlock" not in apply_def

    clear_block = src.split("GC.clearCardQueueBlock = function clearCardQueueBlock(cardEl)")[1].split("function findCardQueueBlockByJobId")[0]
    assert 'querySelectorAll("[data-gc-card-queue], [data-hero-queue]")' in clear_block

    can_patch = src.split("function canPatchCardQueueInPlace(existing, queueJob)")[1].split("function syncCardQueueOwnerClasses")[0]
    assert "jobId !== prevJobId" in can_patch
    assert "finishAt !== prevFinish" in can_patch

    progress = src.split("function updateAllProgressBars(serverNow)")[1].split("function updateBuildQueueLive")[0]
    assert "requestQueueTimerZeroRefresh" in progress


def test_gc551a_fuel_cell_icon_and_hero_level_badge():
    """GC-551A: fuel_cells uses same resource chip family; hero level badge stays readable."""
    icons_py = _read("tools/generate_icons.py")
    base_html = _read("templates/base.html")
    sidebar_html = _read("templates/partials/sidebar.html")
    progression = _read("templates/partials/progression_cards.html")
    css = _read("static/style.css")
    fuel_png = ROOT / "static" / "icons" / "fuel_cells.png"
    fuel_svg = ROOT / "static" / "icons" / "fuel_cells.svg"

    assert '"fuel_cells"' in icons_py.split("RESOURCES = {")[1].split("}")[0]
    assert "def draw_fuel_cell" in icons_py
    assert "draw_resource_chip(c, accent, draw_fn)" in icons_py
    assert "--card-artwork" in icons_py
    assert "generate_card_artwork" in icons_py
    assert fuel_png.is_file() and fuel_png.stat().st_size > 700
    assert fuel_svg.is_file()
    assert "img/res/Brennzellen.png" in progression
    fuel_block = base_html.split('class="hud-res-panel hud-res-fuel-cells"')[1].split("</div>", 1)[0]
    assert "onerror" not in fuel_block
    assert "icons/energy.png" not in fuel_block
    assert ".gc-level-badge.gc-bld-card-level--hero" in css
    hero_badge = css.split(".gc-level-badge.gc-bld-card-level--hero")[1].split("}", 1)[0]
    assert "background:" in hero_badge
    assert "rgba(5, 14, 24" in hero_badge or "rgb(6, 12, 26)" in hero_badge
    assert ".hud-res-fuel-cells .res-icon" in css
    assert "gc-res-fuel-cells" in css
    assert "render_resource_icon('fuel_cells', 'xl')" in _read("templates/overview.html")
    assert "img/res/Ferronit.png" in _read("templates/base.html")
    assert Path("static/img/buildings/academy.png").stat().st_size > 100_000


def test_gc551_card_artwork_dirs_png_only_no_svg():
    """Card domains use real PNG artwork only — no SVG placeholders under static/img."""
    card_dirs = ("buildings", "research", "ships", "defense")
    for sub in card_dirs:
        folder = ROOT / "static" / "img" / sub
        assert folder.is_dir(), sub
        svgs = list(folder.glob("*.svg"))
        assert svgs == [], f"unexpected SVG in static/img/{sub}: {svgs[:3]}"
        pngs = list(folder.glob("*.png"))
        assert pngs, f"missing PNG artwork in static/img/{sub}"


def test_gc555_asset_audit_and_webp_loading():
    """GC-555: WebP tooling, picture macro, vote banner CSS, landscape webp var."""
    audit = _read("tools/audit_assets.py")
    convert = _read("tools/convert_webp.py")
    doc = _read("docs/GC-555_ASSET_AUDIT.md")
    report_path = ROOT / "docs" / "GC-555_asset_report.json"
    assert report_path.is_file()
    progression = _read("templates/partials/progression_cards.html")
    vote_tpl = _read("templates/vote_center.html")
    base = _read("templates/base.html")
    css = _read("static/style.css")
    main = _read("static/main.js")
    app_py = _read("app.py")

    assert "def categorize" in audit
    assert "convert_one" in convert
    assert "GC-555" in doc
    assert "render_raster_picture" in progression
    assert "<picture>" in progression
    assert "webp_static" in progression
    assert "--vote-banner" in vote_tpl
    assert "vote-center-provider-hero-img" not in vote_tpl
    assert "--planet-landscape-webp" in base
    assert "image-set" in css.split("vote-center-provider-hero")[1][:400]
    assert "landscapeWebpUrlFromRaster" in main
    assert "landscape_webp_url" in app_py
    assert "def webp_static_filter" in app_py
    assert (ROOT / "static" / "img" / "background.webp").is_file()
    assert (ROOT / "static" / "img" / "vote" / "TopG.webp").is_file()


def test_main_js_gc553_global_perf_audit():
    """GC-553: hidden-tab throttle, page-scoped patches, debugPerf, idle animation pause."""
    src = _read("static/main.js")
    css = _read("static/style.css")
    buildings = _read("templates/buildings.html")

    assert "GC.debugPerf = function debugPerf()" in src
    assert "function shouldPatchGameStateModule" in src
    apply_section = src.split("function applyGameStateData")[1].split("function gameStateIncludePanel")[0]
    assert "_syncBuildQueueLiveState(queueList)" in apply_section
    assert "shouldPatchGameStateModule(\"buildings\")" in src

    start_poll = src.split("GC.startPolling = function startPolling")[1].split("GC.initPage = function initPage")[0]
    assert "polling paused (hidden tab)" not in start_poll
    assert "polling interval adjusted" in start_poll

    vis = src.split("function initVisibilityPolling")[1].split("function initMobileNav")[0]
    hidden_branch = vis.split("if (document.hidden)")[1].split("if (!shouldRunGameLoop()")[0]
    assert "pauseVisualLoops()" in hidden_branch
    assert "GC.stopPolling()" not in hidden_branch
    assert "GC.startPolling(" in hidden_branch

    vote_poll = src.split("function startVoteCenterPoll")[1].split("function bindVoteCenterOnce")[0]
    assert "GC.setSafeInterval" in vote_poll
    assert "document.hidden" in vote_poll

    assert "animation-play-state: paused" in css
    assert "box-shadow: 0 0 8px" not in css.split("@keyframes gc-card-queue-pulse")[1][:120]
    progression = _read("templates/partials/progression_cards.html")
    assert 'decoding="async"' in progression
    assert 'fetchpriority="low"' in progression
    assert "render_raster_picture" in buildings


def test_main_js_lootbox_roll_accuracy_and_sound():
    src = _read("static/main.js")
    assert "function playLootboxOpenSound" in src
    assert "winning_index" in src
    assert "is-winning" in src
    assert "/static/sounds/lootboxes/lootbox_sound.mp3" in src
    assert "computeLootRollTarget" in src
    assert "translate3d" in src.split("function animateLootRoll")[1].split("function showLootOpeningModal")[0]
    assert (ROOT / "static/sounds/lootboxes/lootbox_sound.mp3").is_file()


def test_gc655_header_discord_status_compact():
    """GC-655: Discord in header is a compact status icon beside commander name."""
    base_html = _read("templates/base.html")
    css = _read("static/style.css")
    de = _read("locales/de.json")
    en = _read("locales/en.json")

    assert "gc-commander-discord-status" in base_html
    assert "gc-commander-identity" in base_html
    assert "auth_discord_link_start" in base_html
    assert "gc-discord-connected-badge" not in base_html
    assert ".gc-commander-discord-status--linked" in css
    assert ".gc-commander-identity{" in css
    assert '"header_discord_connected": "Mit Discord verbunden"' in de
    assert '"header_discord_connect": "Discord verbinden"' in de
    assert '"header_discord_connected": "Connected with Discord"' in en
    assert '"header_discord_connect": "Connect Discord"' in en


def test_gc557g_unified_card_level_badge():
    """GC-557G: buildings/research hero level badge matches shipyard stock badge stack."""
    src = _read("static/main.js")
    buildings_html = _read("templates/buildings.html")
    research_html = _read("templates/research.html")
    css = _read("static/style.css")

    assert "gc-bld-hero-right-stack" in buildings_html
    assert "gc-bld-hero-right-stack" in research_html
    assert "gc-hero-stat-badge" in buildings_html
    assert "gc-hero-stat-badge" in research_html
    assert "gc-bld-card-hero-action-slot" in buildings_html
    assert "gc-bld-card-hero-action-slot" in research_html
    assert "gc-card-timer" in buildings_html
    assert "tech-level-current" in research_html
    assert 'id="level-' in buildings_html

    assert "function syncResearchHeadAction" in src
    research_patch = src.split("function patchResearchPanel(techs, researchRaw)")[1].split("function patchResearchEffects")[0]
    assert "syncResearchHeadAction(actionCell, tech, summary)" in research_patch
    research_action = src.split("function getResearchActionState")[1].split("function getBuildingActionState")[0]
    assert 'data-action-state="go"' in research_action
    assert 'data-action-state="warn"' in research_action

    assert ".gc-bld-hero-right-stack{" in css
    assert ".gc-hero-stat-badge{" in css
    assert ".gc-bld-card-hero-action-slot{" in css
    assert "data-action-state" in research_html
