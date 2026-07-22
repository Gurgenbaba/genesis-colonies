"""
Regression guards for PJAX-safe messages inbox and chat polling (static JS contracts).

Run: python -m pytest tests/test_static_live_updates.py -v
"""

from __future__ import annotations

import json
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
    unread_section = src.split("function _processUnreadMessagesPoll(data, reason, opts)")[1].split("function updateNavBadges")[0]
    assert "emptyInboxNeedsFill" not in unread_section
    assert "unreadSyncedFromApi" not in unread_section
    assert "GC.messagesPageState.listLoaded" in unread_section
    assert "unreadIncreased" in unread_section
    assert "function playNewMessageNotifySound()" in src
    assert "playNotificationSound(\"message\")" in src
    assert "_maybePlayMessageNotifySound(data, { unreadIncreased: true })" in unread_section
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


def test_messages_js_spy_battle_lab_button():
    src = _read("static/js/messages.js")
    assert "function combatSimulatorSpyHref(messageId)" in src
    assert "spy_report_battle_lab_btn" in src
    assert "data-spy-action=\"simulate\"" in src
    assert "/combat-simulator?spy_report_id=" in src


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


def test_gc620e_expedition_report_delivery_and_effective_cargo():
    """GC-620E: report UI uses effective cargo cap + delivery notice; no frontend loot math."""
    src = _read("static/js/messages.js")
    assert "function expeditionEffectiveCargoCap(meta)" in src
    assert "function expeditionCargoJackpotMult(meta)" in src
    assert "function renderExpeditionCargoStatHtml(lootTotal, meta)" in src
    assert "gc-expedition-report-delivery-notice" in src
    assert "gc-expedition-cargo-jackpot-badge" in src
    assert "expedition_report_delivery_notice" in src
    assert "cargo_jackpot_mult" in src
    assert "Math.pow" not in src.split("function renderExpeditionReportFull(meta)")[1].split("function renderInboxReportTeaser")[0]
    de = json.loads(_read("locales/de.json"))
    en = json.loads(_read("locales/en.json"))
    for key in (
        "expedition_report_delivery_notice",
        "expedition_report_cargo_jackpot_badge",
        "expedition_report_cargo_base",
    ):
        assert key in de, f"missing de locale key {key}"
        assert key in en, f"missing en locale key {key}"


def test_gc620f_expedition_preview_jackpot_hint():
    """GC-620F: fleet preview hints mention rare cargo jackpots; no frontend cap math."""
    main = _read("static/main.js")
    assert "fleet_expedition_hint_jackpot" in main
    assert "syncExpeditionDailyEfficiencyUi" in main
    assert "data-preview-expedition-daily-row" in main
    de = json.loads(_read("locales/de.json"))
    en = json.loads(_read("locales/en.json"))
    assert "fleet_expedition_hint_jackpot" in de
    assert "fleet_expedition_hint_jackpot" in en
    for key in (
        "fleet_expedition_daily_efficiency_label",
        "fleet_expedition_daily_efficiency_reset",
        "fleet_expedition_daily_efficiency_tooltip",
    ):
        assert key in de, f"missing de locale key {key}"
        assert key in en, f"missing en locale key {key}"


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
    pre_nav = nav_section.split("beginPjaxNavigation")[0]
    assert "abortInFlightGameStateFetches()" in pre_nav
    assert "GC.stopPolling()" in pre_nav
    assert "releaseShellNavigationBlockers(\"pjax_nav\")" in pre_nav
    # Light-nav must still abort hung game-state polls (idle SQLite starvation).
    assert "!opts.preserveGameLoop && typeof GC.abortInFlightGameStateFetches" not in pre_nav
    pjax_apply = src.split("async function applyPjaxPayload(url, payload, doc, opts = {})")[1].split("function pjaxPayloadFromDoc")[0]
    assert "GC.cleanupPage({ preserveGameLoop:" in pjax_apply
    assert "preserveShell" not in pjax_apply
    assert "main-content missing" in pjax_apply
    fetch_section = src.split("GC.navigateTo = async function navigateTo")[1].split("async function applyPjaxPayload")[0]
    assert "await fetch(url" in fetch_section
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
    assert "setTimeout(tick, _progressTickerDelayMs(getTimerServerNow()))" in ticker_section
    assert "requestAnimationFrame(tick)" not in ticker_section
    update_all = src.split("function updateAllProgressBars(serverNow)")[1].split("let lastHadActiveJob = false")[0]
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
    assert "isHudOnlyGameStateReason" in src
    assert '"fleet_countdown_expired"' in src.split("function isHudOnlyGameStateReason(reason)")[1].split("function isPageReloadGameStateReason")[0]
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
    assert "initGalaxyPrefetchHints" in src
    assert "prefetchGalaxyNavHints" in src
    assert "initGalaxyPrefetchHints();" in src.split("function initShellOnce()")[1].split("function init")[0]
    assert 'path.endsWith("/galaxy")' in src
    assert "bindGalaxyKeyboardOnce" not in src
    # GC-PERF-GALAXY-PREFETCH-GATE-001
    assert "shouldPauseGalaxyPrefetch" in src
    assert "GALAXY_PREFETCH_CONCURRENCY = 1" in src
    assert "_galaxyPrefetchQueue" in src
    assert "pumpGalaxyPrefetchQueue" in src
    assert "scheduleBootPrefetch" not in src
    assert "prefetchGalaxyNavHints(document)" not in src
    hints = src.split("function initGalaxyPrefetchHints()")[1].split("GC.prefetchGalaxyNavHints")[0]
    assert "mouseover" in hints
    assert "visibilitychange" in hints
    nav_hints = src.split("function prefetchGalaxyNavHints(scope)")[1].split("function initGalaxyPrefetchHints()")[0]
    assert "getGalaxyPageRoot()" in nav_hints
    assert "scope !== document" in nav_hints


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
    assert "function patchHudCapacityBars" in src
    assert "function computeHudCapacityState" in src
    hud_section = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "patchResourceBarEnergyWarning(used, total)" in hud_section
    assert "patchHudCapacityBars(metal, crystal, fuelCells" in hud_section


def test_main_js_patches_boost_hud_from_game_state():
    src = _read("static/main.js")
    assert "function patchShellHudBoosters(data)" in src
    assert "function bootstrapHeaderBoostersFromDom()" in src
    assert "function patchInventoryActiveBoosters(inventory)" in src
    assert '"/api/inventory/use"' in src
    hud_section = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "patchShellHudBoosters(data)" in hud_section
    boost_section = src.split("function patchShellHudBoosters(data)")[1].split("function patchShellHudFromState(data, opts)")[0]
    assert "data-res-boost" in boost_section
    assert "resource_impacts" in src.split("function _normalizeBoostEffects")[1][:800]
    assert "active_effects" in boost_section
    assert "_BOOST_DOMAIN_RES_KEYS" in src
    assert "bootstrapHeaderBoostersFromDom()" in src
    base = _read("templates/base.html")
    assert 'data-res-boost="metal"' in base
    assert "hud-res-footer" in base
    assert "gc-header-boosters-state" in base
    assert 'data-gc-boost-hud' not in base


def test_gc_instant_ux_ssr_hud_boot_contract():
    """GC-INSTANT-UX-001A: fleet + unread hydrate from SSR before deferred poll."""
    src = _read("static/main.js")
    base = _read("templates/base.html")
    app_py = _read("app.py")
    assert 'id="gc-hud-boot-state"' in base
    assert "HEADER_HUD_BOOT" in base
    assert "HEADER_HUD_BOOT=header_hud_boot" in app_py
    assert "fleet_hud_for_game_state" in app_py.split("header_hud_boot")[1][:2500]
    assert "function bootstrapHudFromDom()" in src
    assert "GC.bootstrapHudFromDom = bootstrapHudFromDom" in src
    shell = src.split("function initShellOnce()")[1].split("document.addEventListener(\"DOMContentLoaded\"")[0]
    assert "bootstrapHudFromDom()" in shell
    assert shell.index("bootstrapHudFromDom()") < shell.index("initGlobalFleetDrawer()")
    boot_fn = src.split("function bootstrapHudFromDom()")[1].split("GC.bootstrapHudFromDom")[0]
    assert 'getElementById("gc-hud-boot-state")' in boot_fn
    assert 'mergeLastState(boot, "ssr_hud_boot")' in boot_fn or 'ssr_hud_boot' in boot_fn
    assert "patchShellHudFromState" in boot_fn
    assert "unread_messages_count" in boot_fn
    assert "active_fleets" in boot_fn
    # Partial HUD boot must not wipe SSR resource amounts to 0.
    hud_fn = src.split("function patchShellHudFromState(data, opts)")[1].split(
        "GC.patchShellHudFromState = patchShellHudFromState"
    )[0]
    assert "hasResourceSnapshot" in hud_fn
    # GC-742 skip remains: no forced page_init when SSR live boot is present.
    skip_fn = src.split("function shouldSkipInitGameStateAfterSsr")[1].split("function bootstrapResourceLiveFromDom")[0]
    assert "pageHasSsrLiveBoot()" in skip_fn


def test_gc_instant_ux_action_busy_contract():
    """GC-INSTANT-UX-001B: shared busy helper wires progression CSS + fleet/TK submit."""
    src = _read("static/main.js")
    css = _read("static/style.css")
    busy_fn = src.split("function setProgressionActionBusy")[1].split("function initGameActions")[0]
    assert 'classList.add("is-loading", "is-busy", "gc-bld-head-action-btn--busy")' in busy_fn
    assert "GC.setActionBusy = setProgressionActionBusy" in src
    assert ".gc-bld-head-action-btn--busy" in css
    assert ".fleet-send-submit.is-busy" in css
    assert ".gc-queue-timekeeper-btn:disabled.is-busy" in css
    tk_fn = src.split("async function submitTimekeeperApplyFromBtn")[1].split("function initTimekeeperOnce")[0]
    assert "setProgressionActionBusy(openBtn, true)" in tk_fn
    assert "setProgressionActionBusy(openBtn, false)" in tk_fn
    assert "setProgressionActionBusy(submitBtn, true)" in src
    assert "setProgressionActionBusy(submitBtn, false)" in src


def test_gc_instant_ux_fleet_ssr_skip_refresh_contract():
    """GC-INSTANT-UX-001C: initFleet skips /api/fleet/state when SSR ready."""
    src = _read("static/main.js")
    init_fn = src.split("function initFleet()")[1].split("function applyFleetUrlPrefill")[0]
    assert "hasSsrFleetBoot" in init_fn
    assert "rt.data.ready === true" in init_fn
    assert "GC.refreshFleetState(page)" in init_fn
    assert "!hasSsrFleetBoot && typeof GC.refreshFleetState" in init_fn
    contract = _read("docs/AJAX_PJAX_CONTRACT.md")
    assert "pageHasSsrLiveBoot" in contract
    assert "bootstrapHudFromDom" in contract
    assert "refreshFleetState" in contract


def test_admin_balance_save_skips_blocking_game_state():
    admin_src = _read("static/admin.js")
    balance_section = admin_src.split("async function afterBalanceMutation")[1].split("async function loadAdminBalance")[0]
    assert "skipGameState: true" in balance_section
    assert "hud: extras && extras.hud" in balance_section
    assert "abortInFlightGameStateFetches" in balance_section
    assert "stopPolling" in balance_section
    assert "stopChatPolling" in balance_section
    assert "quiesceLiveClientFetches" in balance_section
    assert "scheduleDeferredHudRefresh" not in admin_src
    assert "releaseShellNavigationBlockers" in balance_section
    assert "syncAdminHudSelects(qs('[data-admin-panel=\"balance\"]')" not in balance_section
    snapshot_fn = admin_src.split("function applyBalanceHudSnapshot")[1].split("function focusAdminDetail")[0]
    assert "patchShellHudFromState" in snapshot_fn
    assert "applyHudFromGameState" not in snapshot_fn
    assert "build_balance_hud_snapshot" in _read("game/admin_balance.py")
    api_src = _read("game/admin_api.py")
    assert "build_balance_hud_snapshot" in api_src.split("def api_save_balance_settings")[1].split("def api_apply_balance_preset_b")[0]
    main_src = _read("static/main.js")
    assert "GC.teardownHudSelectPortals = teardownHudSelectPortals" in main_src
    assert "function reparentHudSelectMenu" in main_src
    assert "shouldSyncRoleSidebarFromHudData" in main_src
    assert "shouldPollGameState" in main_src
    assert "function isAdminRoutePath(pathname)" in main_src
    should_run = main_src.split("function shouldRunGameLoop()")[1].split("function isAdminShellPage")[0]
    assert "isAdminRoutePath(window.location.pathname)" in should_run
    assert "quiesceLiveClientFetches" in main_src
    landscape_fn = main_src.split("function applyPlanetLandscapeFromState(data)")[1].split("function applyPlanetHeroThemeFromState")[0]
    assert "hasOwnProperty.call(ap, \"landscape_url\")" in landscape_fn
    assert "GC.releaseShellNavigationBlockers = releaseShellNavigationBlockers" in main_src
    chat_boot = main_src.split("function scheduleDeferredChatBoot()")[1].split("function syncScopedPlanetIds")[0]
    assert "isAdminShellPage()" in chat_boot
    pjax_fn = main_src.split("function isPjaxEligibleLink(link)")[1].split("function normalizePjaxUrl")[0]
    assert "isAdminRoutePath(dest.pathname)" in pjax_fn
    assert 'if (GC.detectPage() === "admin") return false' not in pjax_fn
    apply_hud = main_src.split("GC.applyHudFromGameState = function applyHudFromGameState")[1][:400]
    assert "if (!planetId) return false" in apply_hud
    sync_section = admin_src.split("async function syncAfterAdminChange")[1].split("async function afterBalanceMutation")[0]
    assert "skipGameState !== true" in sync_section
    assert "applyBalanceHudSnapshot" in sync_section


def test_admin_pjax_exit_hard_load_entry():
    """Admin entry is full page; leaving admin uses PJAX like other ingame nav."""
    src = _read("static/main.js")
    pjax_fn = src.split("function isPjaxEligibleLink(link)")[1].split("function normalizePjaxUrl")[0]
    assert "isAdminRoutePath(dest.pathname)" in pjax_fn
    assert 'GC.detectPage() === "admin"' not in pjax_fn
    mobile_sys = _read("templates/partials/sidebar_system_mobile.html")
    assert "gc-nav-admin" in mobile_sys
    admin_nav = mobile_sys.split("gc-nav-admin")[1][:300]
    assert "data-no-pjax" in admin_nav
    nav = src.split("GC.navigateTo = async function navigateTo")[1].split("function initPjax")[0]
    assert "leavingAdmin" in nav
    assert "teardownHudSelectPortals" in nav
    assert "quiesceLiveClientFetches" in nav
    # Safety: ensure stale nav blockers cannot survive admin → ingame PJAX.
    assert "releaseShellNavigationBlockers" in src.split("GC.cleanupPage = function cleanupPage()")[1][:2500]
    assert "beginPjaxNavigation" in nav
    assert "shouldPjaxHardLoad" in nav
    assert "shouldPjaxHardLoad" in nav


def test_pjax_navigation_owner_clears_stale_timeouts():
    """PJAX nav ID guard — stale timeouts must not hard-load superseded destinations."""
    src = _read("static/main.js")
    assert "let _pjaxNavigationSeq = 0" in src
    assert "let _activePjaxNavigation = null" in src
    assert "function clearPjaxNavigation(nav" in src
    assert "function supersedePjaxNavigation(reason)" in src
    assert "function beginPjaxNavigation(url, target)" in src
    assert "function shouldPjaxHardLoad(nav, fetchTimedOut, userAborted)" in src
    dedupe = src.split("GC.navigateTo = async function navigateTo")[1].split("function initPjax")[0]
    assert "_activePjaxNavigation.normalizedUrl === target" in dedupe
    assert "nav.fetchTimeoutId" in dedupe
    hard_load_fn = src.split("function shouldPjaxHardLoad")[1].split("GC.navigateTo = async function navigateTo")[0]
    assert "_activePjaxNavigation.id !== nav.id" in hard_load_fn
    assert "normalizePjaxUrl(window.location.href) === nav.normalizedUrl" in hard_load_fn
    blockers = src.split("function releaseShellNavigationBlockers(reason)")[1].split("function syncHudSelectLabelsInRoot")[0]
    assert "GC.pjaxInFlight = null" not in blockers
    assert "GC._pjaxAbort" not in blockers
    preload = src.split("function isValidLcpPreloadHref(href)")[1].split("GC.syncLcpHeroPreload = syncLcpHeroPreload")[0]
    assert '"null"' in preload
    assert '"undefined"' in preload
    assert "normalizeLcpPreloadHref" in preload
    assert "removeLcpHeroPreloadLinks" in preload
    version = _read("VERSION").strip()
    assert version == "0.5.9.16"


def test_main_js_gc802_planet_switch_state_sync():
    src = _read("static/main.js")
    assert "syncScopedPlanetIds" in src
    assert '"logistics-page"' in src.split("function syncScopedPlanetIds")[1].split("function abortInFlight")[0]
    assert "abortInFlightGameStateFetches" in src
    switch_section = src.split('applyActionState(res, "planet_switch")')[1][:1800]
    planet_switch_apply = src.split("const isPlanetSwitch = reason === \"planet_switch\"")[1].split("function logStatusPollErrorOnce")[0]
    assert "GC.stopPolling()" in planet_switch_apply
    assert "hudOnly: isPlanetSwitch" in planet_switch_apply
    assert "PLANET_SWITCH_SKIP_SSR" in switch_section
    assert "skipHydrate: true" in switch_section
    assert "skipGameState: true" in switch_section
    assert "preserveGameLoop" in src.split("GC.reloadCurrentPage = function reloadCurrentPage")[1].split("function hydratePageFromLastState", 1)[0]
    assert 'refreshGameState("planet_switch")' not in switch_section
    assert "bootstrapResourceLiveFromDom()" in switch_section
    action_body = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert 'reason === "planet_switch"' in action_body
    apply_body = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent")[0]
    assert "applyHudOnlyGameState" in apply_body
    assert "isHudOnlyGameStateReason" in apply_body
    overview = _read("templates/overview.html")
    assert "overview-wrapper" in overview
    assert 'data-planet-id="{{ planet.planet_id or 0 }}"' in overview


def test_main_js_reload_purge_logistics_alliance():
    """Wave2 — logistics/alliance success paths avoid redundant full PJAX when patched."""
    src = _read("static/main.js")
    success = src.split('mode === "collect" ? "logistics_collect_success"')[1].split("function initLogistics")[0]
    assert "applyLogisticsActionState(page, res)" in success
    assert "await refreshLogisticsLiveState(page)" in success
    assert "reloadCurrentPage" not in success
    assert "async function allianceFinalizeSuccess" in src
    assert "ALLIANCE_PATCH_ONLY" in src
    assert 'await allianceFinalizeSuccess("alliance_profile", out)' in src
    assert 'await allianceFinalizeSuccess("alliance_create", out)' in src


def test_main_js_gc742_ssr_skip_init_game_state():
    """GC-742: overview SSR must not immediately re-fetch game-state."""
    src = _read("static/main.js")
    assert "function pageHasSsrLiveBoot()" in src
    assert "function shouldSkipInitGameStateAfterSsr(page, opts)" in src
    assert "initPage skip game-state (SSR fresh)" in src
    skip_fn = src.split("function shouldSkipInitGameStateAfterSsr(page, opts)")[1].split("function bootstrapResourceLiveFromDom")[0]
    assert "return pageHasSsrLiveBoot()" in skip_fn
    assert "opts.pjax) return false" not in skip_fn
    assert "_SSR_SKIP_INIT_GAME_STATE_PAGES" not in skip_fn
    assert "function isIngameShellPjaxNavigation(url, opts" in src
    nav_to = src.split("GC.navigateTo = async function navigateTo(url, opts = {})")[1].split("const push = opts.push")[0]
    assert "isIngameShellPjaxNavigation(url, opts)" in nav_to
    assert "skipGameState: true, preserveGameLoop: true" in nav_to
    assert "opts && opts.force) return false" not in skip_fn
    init_body = src.split("const afterInit = async () => {")[1].split("if (page === \"messages\")")[0]
    assert "shouldSkipInitGameStateAfterSsr(page, opts)" in init_body
    assert 'await GC.refreshGameState("page_init")' in init_body
    assert "bootstrapResourceLiveFromDom()" in init_body
    assert "Boolean(skipInitFetch)" in init_body
    assert 'void GC.refreshGameState("page_init")' not in init_body
    pjax_apply = src.split("async function applyPjaxPayload(url, payload, doc, opts = {})")[1].split("function pjaxPayloadFromDoc")[0]
    assert "skipHydrate: opts.skipHydrate !== false" in pjax_apply
    assert "pjax: true" in pjax_apply
    assert "return afterInit()" in src.split("GC.initPage = function initPage(opts)")[1].split("GC.stopPolling = function stopPolling")[0]
    cleanup = src.split("GC.cleanupPage = function cleanupPage(opts = {})")[1].split("GC.requestFrame = function requestFrame")[0]
    assert "preserveShell" not in cleanup
    assert "preserveGameLoop" in cleanup
    assert "abortInFlightGameStateFetches()" in cleanup
    assert "_preservePollingOnCleanup" not in cleanup
    assert "GC.cleanupPage({ preserveGameLoop:" in pjax_apply
    abort_fn = src.split("function abortInFlightGameStateFetches()")[1].split("let _planetPageReloadPromise")[0]
    assert "_activeRefreshFlightResolve" in abort_fn
    assert "GC.refreshInFlight = null" in abort_fn


def test_app_gc745_pjax_server_fastpath():
    """GC-745: PJAX requests skip heavy shell globals and use poll live path."""
    app_py = _read("app.py")
    assert "def _is_pjax_request()" in app_py
    assert "def _is_lightweight_layout_request()" in app_py
    assert "def _use_poll_live_path(finish_source: str)" in app_py
    poll_fn = app_py.split("def _use_poll_live_path(finish_source: str)")[1].split("def ", 1)[0]
    assert "_is_pjax_request()" in poll_fn
    assert 'src == "game_state"' in poll_fn
    assert "_SSR_POLL_LIVE_SOURCES" not in app_py
    load_ctx = app_py.split("def _load_page_live_context(")[1].split("\ndef ", 1)[0]
    assert "_use_poll_live_path(src)" in load_ctx
    assert "api_notifications_summary" in app_py.split("_FLEET_TICK_SKIP_ENDPOINTS = frozenset")[1].split(")")[0]
    inject = app_py.split("def inject_globals()")[1].split("@app.route", 1)[0]
    assert "_is_lightweight_layout_request()" in inject
    # GC-PERF-PJAX-CTX-SHELL-001: score/rank + planet switcher are shell-only.
    score_block = inject.split("# score + rank")[1].split("header_planets:")[0]
    assert "not simple_layout" in score_block
    assert "get_player_score_cached" in score_block
    planets_block = inject.split("header_planets:")[1].split("current_planet_landscape_url")[0]
    assert "not simple_layout" in planets_block
    assert "list_player_planets_for_switcher" in planets_block
    landscape_block = inject.split("current_planet_landscape_url = None")[1].split(
        "from game.config import get_client_runtime_config"
    )[0]
    assert "not simple_layout" in landscape_block
    # Codex stays available for #main-content on PJAX.
    assert "build_codex_template_context" in inject
    galaxy_view = app_py.split("def galaxy_view()")[1].split("@app.route", 1)[0]
    assert "_load_player_view_with_resources()" in galaxy_view
    assert "build_minimap_range" not in galaxy_view
    assert "minimap=" not in galaxy_view
    assert "list_system(" in galaxy_view
    assert "conn=conn" in galaxy_view.split("list_system(")[1].split(")", 1)[0]

    js = _read("static/main.js")
    cleanup = js.split("GC.cleanupPage = function cleanupPage(opts = {})")[1].split("GC.requestFrame = function requestFrame")[0]
    assert "preserveShell" not in cleanup
    assert "GC.cleanupPage({ preserveGameLoop:" in js.split("async function applyPjaxPayload")[1].split("function pjaxPayloadFromDoc")[0]
    assert "quiesceLiveClientFetches(\"logout-click\")" in js
    nav = js.split("GC.navigateTo = async function navigateTo")[1].split("function initPjax")[0]
    pre_nav = nav.split("beginPjaxNavigation")[0]
    assert "isIngameShellPjaxNavigation(url, opts)" in nav
    assert "abortInFlightGameStateFetches()" in pre_nav
    assert "GC.stopPolling()" in pre_nav
    assert "releaseShellNavigationBlockers(\"pjax_nav\")" in pre_nav
    assert "!opts.preserveGameLoop && typeof GC.abortInFlightGameStateFetches" not in pre_nav
    assert "AUTH_ROUTE_RE.test(destUrl.pathname" in pre_nav


def test_gc746_overview_ssr_slim_context():
    """GC-746: overview SSR skips dead slices and reuses one DB conn."""
    overview_py = _read("game/overview_page.py")
    page_ctx = overview_py.split("def build_overview_page_context(")[1].split("def ", 1)[0]
    assert "get_overview_building_rows" not in page_ctx
    assert "include_log=False" in page_ctx
    assert "get_overview_planet_teaser" not in _read("app.py").split("def overview()")[1].split("@app.route", 1)[0]
    app_overview = _read("app.py").split("def overview()")[1].split("def empire_view")[0]
    assert "close_conn=False" in app_overview
    assert "ctx.get(\"planet\")" in app_overview


def test_gc746_routes_reuse_ctx_planet():
    """GC-746: buildings/research/fleet reuse planet from page live context."""
    app_py = _read("app.py")
    buildings = app_py.split("def buildings_view()")[1].split("def upgrade")[0]
    research = app_py.split("def research_view()")[1].split("def research_start")[0]
    fleet = app_py.split("def fleet_view()")[1].split("@app.route(\"/alliance\")")[0]
    assert "ctx.get(\"planet\")" in buildings
    assert "ctx.get(\"planet\")" in research
    assert "ctx.get(\"planet\")" in fleet
    assert "_load_page_live_context(finish_source=\"fleet\"" in fleet


def test_gc803_simple_hud_poll_contract():
    src = _read("static/main.js")
    assert "function patchHudLastState(data, reason)" in src
    assert "function applyHudOnlyGameState(data, reason, opts)" in src
    assert "function isHudOnlyGameStateReason(reason)" in src
    assert "function mergePollStatePreserveHeavy" not in src
    assert "function gameStateIncludePanel" not in src
    assert "function gameStateWantPanelPoll" not in src
    refresh = src.split("async function refreshGameState(reason)")[1].split("GC.refreshGameState = refreshGameState")[0]
    assert "include_panel=1" not in refresh
    assert 'gameStateUrl = "/api/game-state"' in refresh or 'fetchJSON("/api/game-state"' in refresh
    assert "GC.fetchJSON(gameStateUrl" in refresh or 'fetchJSON("/api/game-state"' in refresh
    live = _read("game/live_state.py")
    assert "def apply_lightweight_game_state_diet(payload" in live
    assert "def research_poll_slice(research" in live
    assert "mini_queue_jobs" in live.split("def research_poll_slice(research")[1].split("def account_safety_hud_for_game_state")[0]


def test_gc_perf_live_001_diet_since_and_busy_fleet_contract():
    """GC-PERF-LIVE-001: client sends ?since=, skips unchanged apply, busy includes fleets."""
    src = _read("static/main.js")
    refresh = src.split("async function refreshGameState(reason)")[1].split("GC.refreshGameState = refreshGameState")[0]
    assert "since=" in refresh
    assert "_lastPollVersion" in refresh
    assert "data.unchanged === true" in refresh
    assert "function hasBusyLiveActivity()" in src
    assert "lastHadActiveFleet" in src
    assert "lastHadActiveDefense" in src
    assert "syncActiveFleetBusyFromState" in src
    assert "hasBusyLiveActivity()" in src.split("function scheduleGameStatePoll")[1].split("GC.stopStatusPoller")[0]


def test_gc744_resource_icons_use_webp():
    """GC-744 / GC-807: resource icons use optimized WebP assets directly."""
    macro = _read("templates/partials/progression_cards.html")
    assert "render_resource_icon(res_key, size='', lazy=true, priority='', hud=false, alt='')" in macro
    assert "img/res/Ferronit.webp" in macro
    assert "img/res/Crytite.webp" in macro
    assert "img/res/Brennzellen.webp" in macro
    assert "img/res/Energie.webp" in macro
    assert "img/res/timekeeper.webp" in macro
    assert "gc-res-timekeeper" in macro
    assert "img/res/Ferronit.png" not in macro
    assert "loading=\"lazy\"" in macro
    assert "loading=\"eager\"" in macro
    overview = _read("templates/overview.html")
    assert "overview-planet-hero" in overview
    assert "gc-planet-hero" in overview
    assert "gc-planet-theme--" in overview
    assert "data-overview-hero-bg" in overview
    assert "planet_slot_" in overview or "hero_label_key" in overview
    assert "render_resource_icon('metal'" not in overview
    base = _read("templates/base.html")
    assert "render_resource_icon('metal', hud=true, lazy=false, priority='high'" in base
    assert "render_resource_icon('timekeeper', hud=true, lazy=false, priority='high'" in base
    assert "hud-res-icon--timekeeper" not in base
    tk_panel = base.split("hud-res-panel hud-res-timekeeper")[1].split("</div>", 1)[0]
    assert "⏳" not in tk_panel


def test_codex_shell_init_before_game_loop_gate():
    """Codex/support bottom-bar clicks must bind even when game-state polling is skipped."""
    src = _read("static/main.js")
    init_shell = src.split("function initShellOnce", 1)[1].split("function initPage", 1)[0]
    shell_chrome = src.split("function initShellChrome", 1)[1].split("function initShellOnce", 1)[0]
    early = init_shell.find("if (!shouldRunGameLoop())")
    assert early != -1
    assert "initShellChrome();" in init_shell
    assert init_shell.index("initShellChrome();") < early
    for needle in ("initSpecialPanel();", "initRoleBasedSidebar();", "initCodex();"):
        assert needle in shell_chrome, needle
    assert "dataset.gcSpecialOpenBound" in shell_chrome
    after = init_shell[early:]
    assert "initSpecialPanel();" not in after
    assert "initCodex();" not in after


def test_gc807b_hud_capacity_polish():
    """GC-807B-R1: compact HUD bars, energy always visible, fuel storage same pipeline as metal/crystal."""
    macro = _read("templates/partials/progression_cards.html")
    base = _read("templates/base.html")
    js = _read("static/main.js")
    css = _read("static/style.css")

    assert "hud-cap-pct" not in macro
    assert "data-hud-cap-pct" not in macro
    assert 'data-hud-capacity="{{ res_key }}"' in macro
    assert 'data-cap-seg="{{ i }}"' in macro
    assert "{% if cap > 0 %}" not in macro.split("render_hud_capacity_bar")[1].split("{% endmacro %}")[0]

    assert "render_hud_capacity_bar('energy', eu, et)" in base
    assert "{% if et > 0 %}{{ render_hud_capacity_bar('energy'" not in base
    assert "data-energy-total>{% if et > 0 %}" in base
    assert "hud-res-no-storage" not in base
    assert "fc_cap <= 0" not in base
    assert "render_hud_capacity_bar('fuel_cells'" in base
    assert "icons/energy.png" not in base
    assert "img/res/Energie.webp" in base

    bld_icon = js.split("function renderBuildingEffectIcon(resKey)")[1].split("function renderBuildingEffectValue")[0]
    assert "img/res/Energie.webp" in bld_icon
    assert "/static/icons/energy.png" not in js
    assert "function patchHudFuelStorageState" not in js
    assert "function setHudCapacityBarVisible" not in js
    cap_patch = js.split("function patchHudCapacityBar(resKey")[1].split("function patchHudCapacityBars")[0]
    assert "wrap.hidden = true" not in cap_patch
    assert "wrap.hidden = false" in cap_patch
    assert "wrap.className =" not in cap_patch
    bars_fn = js.split("function patchHudCapacityBars(")[1].split("function patchHudStorageWarnings")[0]
    assert 'patchHudCapacityBar("fuel_cells", fuelCells, storageFuelCells, opts)' in bars_fn
    assert 'patchHudCapacityBar("energy", energyUsed, energyTotal, opts)' in bars_fn
    assert "energyUsed != null && energyTotal != null" in bars_fn
    assert "setHudCapacityBarVisible" not in bars_fn
    live_fn = js.split("function patchShellHudLiveResources(metal, crystal, fuelCells)")[1].split("function syncResourceLiveBaseline(snapshot)")[0]
    assert "_resourceLive.energyUsed" in live_fn
    assert "_resourceLive.energyTotal" in live_fn
    assert "null," not in live_fn.split("patchHudCapacityBars(")[1].split(");")[0]
    assert "{ animate: false }" in live_fn
    hud_patch = js.split("function patchShellHudFromState(data, opts)")[1].split("function patchHeaderPlanetLimitFromState")[0]
    assert 'storage.fuel_cells || 0' in hud_patch
    assert "storageFuelCells > 0 ? fmtNumber" not in hud_patch

    assert "overview-res-dashboard" not in css
    assert "overview-res-chip" not in css
    assert ".overview-res-card{" in css
    assert "function updateMiniQueueProgressBars" in js
    assert "job.progress_pct" not in js.split("function miniQueueJobSignature")[1].split("function _miniQueueIconUrl")[0]
    assert "flex-shrink: 0" in css.split(".gc-header-cmd .hud-res-capacity")[1].split("}")[0]
    assert "gc-hud-energy-bar-flicker" in css
    assert ".gc-header-cmd .hud-res-energy.energy-warning .hud-cap-bar" in css


def test_gc700a_combat_report_v2_presentation():
    """GC-700A: battle report layout — duel cards, conditional loot/debris, no combat math."""
    js = _read("static/js/messages.js")
    css = _read("static/style.css")
    modal = _read("templates/partials/combat_report_modal.html")

    full_fn = js.split("function renderCombatReportFull(meta)")[1].split("function cacheReportModalElements")[0]
    assert "function renderCombatForcesDuel" in js
    assert "function renderCombatDebrisPanel" in js
    assert "function combatDebrisPayload" in js
    assert "renderCombatForcesDuel(safeMeta, defenseStock)" in full_fn
    assert "renderCombatBattleOverview(meta)" not in full_fn
    assert "lootTotal > 0" in full_fn
    assert "renderCombatDebrisPanel(safeMeta)" in full_fn
    assert "renderCombatResearchPanel(safeMeta)" in full_fn
    assert 'data-result="${esc(' in full_fn
    assert "/static/icons/energy.png" not in js.split("function renderCombatReportFull")[1][:8000]

    assert ".gc-combat-side-card--winner" in css
    assert ".gc-combat-report-panel--loot-found" in css
    assert ".gc-combat-report-panel--debris" in css
    assert "gc-combat-report-body" in modal

    en = _read("locales/en.json")
    de = _read("locales/de.json")
    assert '"combat_report_section_debris"' in en
    assert '"combat_report_side_winner"' in de


def test_gc700d_combat_debris_recycler_ux():
    """GC-700D: debris metadata UX — recycler hint + fleet prefill CTA."""
    js = _read("static/js/messages.js")
    css = _read("static/style.css")
    en = _read("locales/en.json")
    de = _read("locales/de.json")

    assert "function fleetRecycleHrefFromCoords" in js
    assert "mission=recycle" in js
    assert "combat_report_send_recycler" in js
    assert "recycler_slots_needed" in js
    assert "renderCombatDebrisPanel(safeMeta)" in js.split("function renderCombatReportFull")[1]
    assert "gc-combat-debris-footer" in css
    assert "gc-combat-debris-actions" in css
    assert '"combat_report_debris_recycler_needed"' in en
    assert '"combat_report_send_recycler"' in de


def test_gc700db_galaxy_debris_ux():
    """GC-700D-B: debris visible in galaxy + command map inspector."""
    html = _read("templates/partials/galaxy_debris_block.html")
    galaxy = _read("templates/galaxy.html")
    js = _read("static/main.js")
    css = _read("static/style.css")
    de = _read("locales/de.json")

    assert "galaxy-debris-block" in html
    assert "☄" in html
    assert "galaxy-debris-recycle-btn" in html
    assert "mission=recycle" in html
    assert "galaxy-orbit-debris-marker" in galaxy
    assert "initGalaxyDebrisUx" in js
    assert "worldInspectorDebrisHtml" in js
    assert "gc-world-inspector-debris" in css
    assert '"galaxy_debris_total"' in de
    assert '"galaxy_debris_ttl_remaining"' in de


def test_gc700c_chronicles_pvp_overview():
    """GC-700C: Chronicles hub with PvP section, stats, tabs, combat report modal hook."""
    html = _read("templates/chronicles.html")
    js = _read("static/main.js")
    css = _read("static/style.css")
    de = _read("locales/de.json")

    assert "chronicles-page" in html
    assert "gc-chronicles-section-tabs" in html
    assert "gc-pvp-stats" in html
    assert "data-pvp-report" in html
    assert "building-tabs" not in html.split("gc-pvp-tabs")[1].split("</nav>")[0]
    assert "GC.modules.chronicles" in js or "initChroniclesPage" in js
    assert "gc-chronicles-section-tab" in css
    assert "gc-pvp-outcome--victory" in css
    assert '"chronicles_title"' in de
    assert '"chronicles_section_pvp"' in de
    assert '"pvp_tab_wins"' in de


def test_gc700cb_chronicles_expeditions_and_records():
    """GC-700C-B: Chronicles expeditions tabs, records cards, report hooks."""
    html = _read("templates/chronicles.html")
    js = _read("static/main.js")
    css = _read("static/style.css")
    de = _read("locales/de.json")

    assert 'section=\'expeditions\'' in html or "section=expeditions" in html
    assert "gc-chronicles-expo-stats" in html
    assert "data-expedition-report" in html
    assert "gc-chronicles-records-grid" in html
    assert "data-chronicles-report" in html
    assert "data-expedition-report" in js
    assert "data-chronicles-report" in js
    assert ".gc-chronicles-records-grid" in css
    assert ".gc-chronicles-record-card" in css
    assert '"chronicles_expo_tab_loot"' in de
    assert '"chronicles_record_biggest_battle"' in de


def test_gc700cd_chronicles_genesis_design():
    """GC-700C-D: Chronicles Genesis-level visual polish."""
    html = _read("templates/chronicles.html")
    css = _read("static/style.css")
    de = _read("locales/de.json")

    assert "gc-chronicles-page--" in html
    assert "gc-chronicles-kicker" in html
    assert "gc-chronicles-section-tabs" in html
    assert "gc-hof-tab gc-chronicles-section-tab" not in html
    assert "gc-hof-tabs gc-chronicles-section-tabs" in html
    assert "gc-chronicles-shell" in html
    assert "gc-chronicles-stats" in html
    assert "gc-chronicles-stat--win" in html
    assert "gc-chronicles-expo-cat--" in html
    assert "gc-chronicles-record-card--{{ card.key }}" in html
    assert "gc-chronicles-my-strip" in html
    assert ".gc-chronicles-kicker" in css
    assert ".gc-chronicles-stat::before" in css
    assert ".gc-chronicles-panel::before" in css
    assert ".gc-chronicles-record-card--biggest_expo_find" in css
    assert '"chronicles_records_strip"' in de


def test_gc700b_hall_of_fame_v2():
    """GC-700B: HoF ranking layout — tabs, compact hero strip, table rows."""
    html = _read("templates/hall_of_fame.html")
    css = _read("static/style.css")
    de = _read("locales/de.json")

    assert "building-tabs" not in html.split("gc-hof-tabs")[1].split("</nav>")[0]
    assert "gc-nav-link" in html
    assert "gc-hof-tab" in html
    assert "gc-hof-col-date" not in html
    assert "hof_col_rounds" not in html.split("gc-hof-table")[1].split("</table>")[0]
    assert "gc-hof-table" in html
    assert "gc-hof-my-strip" in html
    assert "gc-hof-mobile-row" in html
    assert "gc-hof-tab-icon" not in html
    assert "gc-hof-card" not in html
    assert "gc-hof-hero-panel" not in html
    assert "gc-btn-primary" not in html
    assert "combat_report_send_recycler" not in html
    assert "hof_hero_line" in de
    assert ".gc-hof-table" in css
    assert ".gc-hof-my-strip" in css
    assert '"hof_tab_debris"' in de


def test_main_js_apply_planet_hero_theme_border_fx():
    src = _read("static/main.js")
    hero_fn = src.split("function applyPlanetHeroThemeFromState(data)")[1].split("function bootstrapPlanetLandscapeFromBoot")[0]
    assert "gc-planet-theme--" in hero_fn
    assert "gc-planet-theme-group--" in hero_fn
    assert "--planet-glow" in hero_fn
    assert "--planet-landscape" in hero_fn
    assert "overview-temp-value" in hero_fn
    css = _read("static/style.css")
    overview = _read("templates/overview.html")
    assert ".overview-hero-border" in css
    assert "--hero-frame-url" in overview
    assert "herocardsframe/frame.png" in overview
    assert ".overview-hero-hud-frame::after" in css
    assert "prefers-reduced-motion" in css
    assert ".gc-planet-theme-group--hot" in css
    assert ".gc-planet-theme-group--frozen" in css
    assert "overview-hero-border" in overview
    assert "overview-hero-hud-frame" in overview
    assert "overview-hero-frame-glow" not in overview
    assert "width: 100%" in css.split(".overview-hero.gc-planet-hero")[1].split("aspect-ratio")[0]
    assert "--hero-hole-left: 6.84%" in css
    assert "--hero-bg-left: 3.4%" in css
    hero_bg = css.split(".overview-hero--themed.gc-planet-hero .overview-hero-bg,")[1].split(".overview-hero--themed.gc-planet-hero .overview-hero-atmo")[0]
    assert "var(--hero-bg-top" in hero_bg
    assert "herocardsframe/frame.webp" in overview
    assert "background: transparent" in css.split(".overview-hero.gc-planet-hero")[1].split("body.gc-body-ingame")[0]
    assert "aspect-ratio: 1536 / 1024" in css
    assert ".overview-hero--themed.gc-planet-hero .overview-hero-hud" in css
    assert "border: none" in css.split(".gc-planet-hero.gc-panel")[1].split("body.gc-body-ingame")[0]
    assert "z-index: 4" in css.split(".overview-hero-hud-frame,")[1].split(".overview-hero-frame-glow")[0]
    assert "overview-hero-activity-panel" in overview
    assert 'id="overview-activities"' in overview
    assert "overview-activities-panel--primary" not in overview
    assert "overview-hero-corner--tl" in overview
    assert "overview-hero-corner--br" in overview
    assert "galactic_directive_banner" not in overview
    assert ".overview-hero-corner--bl" in css
    assert ".overview-hero-activity-panel" in css
    assert 'getElementById("overview-activities")' in src
    assert "overview-hero-title-plate" in overview
    assert "top: var(--hero-activity-top" in css.split(".overview-hero-activity-panel")[1].split(".overview-hero-activity-head")[0]
    assert "scale(1.05)" in css
    idx = css.find(".overview-hero-activity-panel .overview-activity-link,")
    assert idx >= 0
    assert "flex-direction: column" in css[idx : idx + 520]
    assert "--hero-activity-glass" in css
    assert "blur(2.5px)" in css
    assert ".overview-hero--themed.gc-planet-hero:hover .overview-hero-bg::after" in css
    assert "radial-gradient" in css.split(".overview-hero--themed.gc-planet-hero:hover .overview-hero-bg::after")[1][:800]
    assert "overview-hero-activity-panel .overview-activity-row::after" in css
    assert "opacity: 0" in css.split(".overview-hero-activity-panel{")[1].split(".overview-hero-activity-head")[0]
    assert ".overview-hero--themed.gc-planet-hero:hover .overview-hero-activity-panel" in css
    assert "--hero-frame-top-name: color-mix" in css
    assert "var(--planet-accent-secondary" in css.split("--hero-frame-top-name")[1].split("--hero-frame-top-coords")[0]


def test_main_js_gc743_deferred_chat_and_news_boot():
    """GC-743: chat bootstrap and what's-new load after initial paint."""
    src = _read("static/main.js")
    assert "GC_DEFER_CHAT_BOOT_MS = 500" in src
    assert "GC_DEFER_WHATS_NEW_MS = 800" in src
    assert "function scheduleDeferredChatBoot()" in src
    chat_boot = src.split("function scheduleDeferredChatBoot()")[1].split("function syncScopedPlanetIds")[0]
    assert "GC._chatBootScheduled || GC._chatBootstrapDone" in chat_boot
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
    assert "GC.lastAppliedStateVersion" in src
    assert "shouldRejectStaleGameState" in src
    assert "extractStateVersion" in src
    assert "monotonicResourceBaseline" in src
    assert "resetResourceDisplayCache" in src
    action_section = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert "forceResourceBar: true" in action_section
    assert "allowResourceRegression: true" in action_section
    assert "resetResourceDisplayCache()" in action_section
    assert "_clientStateGen += 1" in action_section
    refresh_section = src.split("async function refreshGameState(reason)")[1].split("GC.refreshGameState = refreshGameState")[0]
    assert "stateGenAtStart !== _clientStateGen" in refresh_section
    apply_section = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent")[0]
    assert "shouldRejectStaleGameState" in apply_section
    assert "markGameStateVersionApplied" in apply_section
    assert "syncResourceLiveBaseline" in apply_section
    assert "patchBuildingPanel" in apply_section
    assert "location.reload()" not in action_section
    poll_apply = src.split("function applyHudOnlyGameState", 1)[1].split("function applyGameStateData", 1)[0]
    assert "shouldRejectStaleGameState" in poll_apply
    assert "markGameStateVersionApplied" in poll_apply


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
    assert "isPageReloadGameStateReason" in src
    assert "refreshPageAfterQueueEvent" in src
    assert "timer_done" in src
    assert "_pageTimerLoopRunning" in src
    overview = _read("templates/overview.html")
    assert "data-timer-target" in overview
    assert "data-refresh-on-zero" in overview
    fleet = _read("templates/fleet.html")
    base = _read("templates/base.html")
    assert "data-timer-kind" in fleet or "data-fleet-preview" in fleet
    assert "id=\"resource-bar\"" in base or "data-countdown-scope" in base
    shipyard = _read("templates/shipyard.html")
    card_queue_macros = _read("templates/partials/card_queue_macros.html")
    mini_strip = _read("templates/partials/page_mini_queue_strip.html")
    assert "render_page_mini_queue_strip" in shipyard
    assert "shipyard-mini-queue" in shipyard
    assert "data-timer-target" in mini_strip
    assert "data-timer-kind" in mini_strip
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
    assert "if (_progressTickerTimerId != null || _progressTickerInTick) return;" in ticker
    movement = src.split("function movementRemainingSeconds(countdownAt, serverNow, serverRemaining)")[1].split("function bootstrapServerTimeFromDom")[0]
    assert "queueJobRemainingSeconds" in movement
    remain = src.split("function timerRemainingSeconds(el, serverNow)")[1].split("function formatTimerDisplay")[0]
    assert 'scope === "overview" && kind === "fleet"' in remain
    assert "syncTimerElement(el)" in remain.split("function timerRemainingSeconds")[0] or "syncTimerElement(el);" in remain
    sync = src.split("function syncTimerElement(el)")[1].split("function timerRemainingSeconds")[0]
    assert "parseTimerTarget" in sync
    assert "data-finish-time" in sync
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent")[0]
    assert "GC.startProgressTicker();" in apply
    assert "syncServerClockFromState(data)" in apply
    mini_partial = _read("templates/partials/page_mini_queue_strip.html")
    card_macros = _read("templates/partials/card_queue_macros.html")
    assert 'data-timer-target' in mini_partial
    assert 'data-countdown-at' in mini_partial
    assert 'data-timer-target' in card_macros
    assert 'data-countdown-at' in card_macros
    render_card_queue = src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("function _syncBuildQueueLiveState")[0]
    assert "applyQueueJobTimerAttrs" in render_card_queue
    assert "dataset.queueSig" in render_card_queue
    render_research = src.split("function renderResearchQueue(researchRaw)")[1].split("function _applyProgressFill")[0]
    assert "GC.startProgressTicker();" in render_research
    update_all = src.split("function updateAllProgressBars(serverNow)")[1].split("let lastHadActiveJob = false")[0]
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
    apply_section = src.split("function applyGameStateData(data, _reason, opts)")[1].split("async function forceCanonicalGameStateRefresh")[0]
    assert "patchShellHudFromState(coercePollUnreadForHud(data, reason)" in apply_section
    assert "skipMessagesUnread" in apply_section
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
    assert "function patchShipyardCardQueues(page, _queueData)" in src or "function patchShipyardCardQueues(page, queueData)" in src
    assert "GC.renderMiniQueueStrip = function renderMiniQueueStrip" in src
    assert 'domain === "shipyard" || domain === "defense"' in src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("const sig = cardQueueJobSignature")[0]
    parse_section = src.split("function parseTimerTarget(raw)")[1].split("function resolveQueueJobFinishTime")[0]
    assert r"/^\d+(\.\d+)?$/" in parse_section
    mini_partial = _read("templates/partials/page_mini_queue_strip.html")
    card_macros = _read("templates/partials/card_queue_macros.html")
    assert 'data-timer-target' in mini_partial
    assert 'data-countdown-at' in mini_partial
    assert 'data-timer-kind="{{ domain }}"' in mini_partial
    assert 'data-timer-target' in card_macros
    assert 'data-countdown-at' in card_macros
    assert 'data-timer-kind="{{ timer_kind }}"' in card_macros
    render_card_queue = src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("function _syncBuildQueueLiveState")[0]
    assert "applyQueueJobTimerAttrs" in render_card_queue
    assert "data-countdown-at" in mini_partial or "countdown-at" in render_card_queue
    render_shipyard = src.split("function renderShipyardQueue(page, queueData)")[1].split("function parseShipyardPageData")[0]
    assert "_renderProductionMiniQueue" in render_shipyard
    assert "_updateShipyardQueueCompact" not in src
    assert "_updatePageQueueCompact" not in src
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent")[0]
    assert "patchResearchPanelFromState(data)" in apply
    assert "patchShipyardPanelFromState(data, activePlanetId)" in apply
    assert "lastHadActiveShipyard" in apply
    progress = src.split("function updateAllProgressBars(serverNow)")[1].split("let lastHadActiveJob = false")[0]
    assert "RESEARCHQ.active.finishTime" in progress
    assert "SHIPYARDQ.active.finishTime" in progress
    assert "DEFENSEQ.active.finishTime" in progress
    assert "assignMonotonicServerRemaining(defenseActive" in progress
    patch_queues = src.split("function patchCardQueuesFromOwnerMap(page, byOwner, listCards, ownerKeyFromCard, findCard)")[1].split("GC.renderCardQueueBlock = function renderCardQueueBlock")[0]
    assert "activeKeys.has(key)" in patch_queues
    assert "GC.clearCardQueueBlock(card)" in patch_queues
    patch_sy = src.split("function patchShipyardCardQueues(page")[1].split("function shipyardIconUrl")[0]
    assert "clearAllProductionCardQueues(page)" in patch_sy
    assert "patchCardQueuesFromOwnerMap" not in patch_sy
    card_queue = src.split("function cardQueueJobSignature(queueJob)")[1].split("function canPatchCardQueueInPlace")[0]
    assert "target_amount" in card_queue
    assert "function canPatchCardQueueInPlace(existing, queueJob)" in src
    assert "function cardQueueTimerTarget(queueJob, isActive)" in src
    render_card = src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("function _syncBuildQueueLiveState")[0]
    assert "cardQueueTimerTarget(queueJob, isActive)" in render_card
    render_sy = src.split("function renderShipyardQueue(page, queueData)")[1].split("function parseShipyardPageData")[0]
    assert "if (!jobs.length)" in render_sy
    assert "_renderProductionMiniQueue" in render_sy
    action = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert "_lastDefenseQueueSignature = \"\"" in action
    assert "_lastPePlanetTechQueueSignature = \"\"" in action


def test_main_js_gc631_formatted_unit_inputs_and_queue_clear():
    """GC-631: de-DE qty parsing, readNumberInput submit, production queue clear."""
    src = _read("static/main.js")
    parse_fn = src.split("function parseIntNumber(n)")[1].split("function formatNumber")[0]
    assert r"^-?\d{1,3}(\.\d{3})+$" in parse_fn
    assert "GC.readNumberInput = readNumberInput" in src
    # GC-PERF-JS-002 — binder extracted to pages/shipyard.js
    shipyard_bind = _read("static/js/pages/shipyard.js").split("function bindShipyardOnce()")[1].split(
        "function initShipyard"
    )[0]
    assert "readNumberInput(qtyInp)" in shipyard_bind
    assert "maxBtn.dataset.maxQty" in shipyard_bind
    assert "parseIntNumber(" in shipyard_bind
    assert "function clearProductionCardQueueState(card)" in src
    patch_sy = src.split("function patchShipyardCardQueues(page")[1].split("function shipyardIconUrl")[0]
    assert "clearAllProductionCardQueues(page)" in patch_sy
    assert "function resolveCardJobsByOwner(queueRaw)" in src
    render_sy_clear = src.split("function renderShipyardQueue(page, queueData)")[1].split("function parseShipyardPageData")[0]
    assert "clearAllProductionCardQueues(page)" in render_sy_clear
    assert "patchShipyardCardQueues" not in render_sy_clear
    owner_helper = src.split("function resolveCardJobsByOwner(queueRaw)")[1].split("function renderMaxQueueButtonLabel")[0]
    assert "return raw && typeof raw === \"object\" ? raw : {}" in owner_helper
    patch_queues = src.split("function patchCardQueuesFromOwnerMap(page, byOwner, listCards, ownerKeyFromCard, findCard)")[1].split("GC.renderCardQueueBlock = function renderCardQueueBlock")[0]
    assert "GC.clearCardQueueBlock(card)" in patch_queues
    assert "activeKeys.has(key)" in patch_queues
    render_sy = src.split("function renderShipyardQueue(page, queueData)")[1].split("function parseShipyardPageData")[0]
    assert "clearAllProductionCardQueues(page)" in render_sy
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
    """GC-632 / GC-827: compact unit stat row on ship/defense cards."""
    src = _read("static/main.js")
    assert "function patchCompactUnitStatChips(card, attack, shield, hull, buildSeconds, tt)" in src
    assert "patchCompactUnitStatChips(" in src
    assert "ship.attack" in src.split("function applyShipyardShipCard")[1].split("function applyShipyardState")[0]
    assert "unit.attack" in src.split("function applyDefenseUnitCard")[1].split("async function refreshDefenseState")[0]
    macro = _read("templates/partials/progression_cards.html")
    assert "render_compact_unit_stat_chips" in macro
    assert "data-unit-stats" in macro
    assert "gc-compact-stat-row" in macro
    shipyard_tpl = _read("templates/shipyard.html")
    assert "render_compact_unit_stat_chips" in shipyard_tpl
    assert "data-production-stats" not in shipyard_tpl
    defense_tpl = _read("templates/defense.html")
    assert "render_compact_unit_stat_chips" in defense_tpl
    css = _read("static/style.css")
    assert ".gc-compact-stat-row" in css
    assert ".gc-compact-chip" in css
    de = _read("locales/de.json")
    en = _read("locales/en.json")
    assert '"ship_stat_attack"' in de
    assert '"ship_stat_hull"' in de
    assert '"ship_stat_attack"' in en


def test_main_js_gc633_weighted_capacity_and_queue_clear():
    """GC-633: yard batch capacity on cards; hard clear when queue empty."""
    src = _read("static/main.js")
    assert "function clearAllProductionCardQueues(page)" in src
    shipyard_py = _read("game/shipyard.py")
    assert "def unit_batch_capacity(" in shipyard_py
    assert "def orbital_production_batch_capacity(" in shipyard_py
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
    assert "function renderGlobalFleetHud(fleetsRaw, opts)" in src
    assert "GC.renderGlobalFleetHud = renderGlobalFleetHud" in src
    assert "function initGlobalFleetDrawer()" in src
    assert "GC.initGlobalFleetDrawer = initGlobalFleetDrawer" in src
    assert "normalizeActiveFleetsPayload" in src
    assert "FLEET_DRAWER_LS_SHOW_ALL" in src
    assert "FLEET_DRAWER_VISIBLE_LIMIT_DEFAULT = 1" in src
    assert "FLEET_DRAWER_LS_EXPANDED" not in src
    assert "data-fleet-drawer-empty" in src
    assert "fleetDrawerTotalShips" in src
    assert "is-show-all" in src
    assert "/api/fleet/recall" in src
    hud = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "resolveFleetHudPayload(data.active_fleets" in hud
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
    assert ".gc-fleet-hud-row" in css
    assert ".gc-fleet-drawer-panel" in css
    assert ".is-show-all" in css
    assert ".gc-fleet-sheet-backdrop" in css
    assert "body.gc-fleet-sheet-open" in css
    assert "--gc-fleet-sheet-top" in css
    assert "syncMobileFleetSheetLayout" in src
    assert "gc-fleet-sheet-backdrop" in src
    assert "gc-fleet-sheet-portal" in src
    assert ".gc-bottom-nav-item[hidden]" in css
    pe = _read("templates/planet_evolution.html")
    assert "pe_establishment_scope_hint" in pe
    assert "pe_establishment_build_level" in pe
    assert "ascension_ancient" in _read("locales/de.json")
    assert "ascension_machine" in _read("locales/en.json")
    assert ".gc-fleet-drawer-row" in css
    assert "data-fleet-drawer-empty" in base
    assert "data-fleet-drawer-toggle" not in base
    assert ".gc-fleet-nav-badge" in css
    fleet_py = _read("game/fleet.py")
    assert "FLEET_DRAWER_VISIBLE_LIMIT = 1" in fleet_py
    assert "build_active_fleets_payload" in fleet_py
    assert "recall_fleet_movement" in fleet_py


def test_main_js_gc_fleet_incoming_attack_alert_row():
    """GC-FLEET-ALERT UX: incoming attack uses fleet HUD row, not separate button."""
    src = _read("static/main.js")
    css = _read("static/style.css")
    assert "function createFleetAttackAlertRow()" in src
    assert "gc-fleet-hud-row--incoming-alert" in src
    assert "gc-fleet-alert--danger" not in css
    assert "gcFleetAttackPulse" not in css
    assert 'document.createElement("button")' not in src.split("function syncFleetAttackAlert")[1].split("GC.syncFleetAttackAlert")[0]
    alert_fn = src.split("function syncFleetAttackAlert(alerts)")[1].split("GC.syncFleetAttackAlert = syncFleetAttackAlert")[0]
    assert "function playIncomingAttackNotifySound()" in src
    assert "playNotificationSound(\"attack\")" in src
    assert "GC_NOTIFY_SOUNDS" in src
    assert "_maybePlayIncomingAttackNotify" not in alert_fn
    patch_shell = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "_maybePlayIncomingAttackNotify(data.fleet_alerts)" in patch_shell
    assert "shouldPlayNotifySoundForKey" in src
    assert "resolveAttackAlertSoundKey" in src
    assert "GC_NOTIFY_SOUND_LS_ATTACK" in src
    assert "_incomingAttackNotifyPrimed" not in src


def test_notify_sound_assets_and_main_js_wiring():
    """Attack + mailbox notify sounds use primed audio + real game-state fields."""
    src = _read("static/main.js")
    fleet_py = _read("game/fleet.py")
    assert (ROOT / "static/sounds/notify/notify.mp3").is_file()
    assert (ROOT / "static/sounds/notify/message.mp3").is_file()
    assert "function initNotificationSounds()" in src
    assert "GC.initNotificationSounds = initNotificationSounds" in src
    assert "function playNotificationSound(kind)" in src
    assert 'attack: "/static/sounds/notify/notify.mp3"' in src
    assert 'message: "/static/sounds/notify/message.mp3"' in src
    assert "initNotificationSounds();" in src.split("function initShellOnce()")[1].split("document.addEventListener(\"click\"")[0]
    assert "playNotificationSound(\"attack\")" in src.split("function playIncomingAttackNotifySound()")[1].split("function playNewMessageNotifySound()")[0]
    assert "playNotificationSound(\"message\")" in src.split("function playNewMessageNotifySound()")[1].split("function lootTileAmountLabel")[0]
    assert "notifySoundVolumeForKind(kind)" in src.split("function playNotificationSound(kind)")[1].split("GC.playNotificationSound = playNotificationSound")[0]
    assert "incoming_attack_count" in fleet_py
    assert "has_incoming_attack" in fleet_py
    assert "next_attack_arrival" in fleet_py
    assert "alert_key" in fleet_py
    unread_fn = src.split("function _processUnreadMessagesPoll(data, reason, opts)")[1].split("function updateNavBadges")[0]
    assert "data.unread_messages_count" in unread_fn
    assert "coercePollUnreadForHud" in unread_fn
    assert "_maybePlayMessageNotifySound(data, { unreadIncreased: true })" in unread_fn
    assert "_queueMessageNotifyItems" in unread_fn
    assert "latest_message_id" in unread_fn
    assert "_processUnreadMessagesPoll(data, reason" in src
    attack_fn = src.split("function _maybePlayIncomingAttackNotify(alerts)")[1].split("function syncFleetAttackAlert(alerts)")[0]
    assert "incoming_attack_count" in attack_fn
    assert "has_incoming_attack" in attack_fn
    assert "resolveAttackAlertSoundKey" in attack_fn
    assert "shouldPlayNotifySoundForKey" in attack_fn
    assert "playIncomingAttackNotifySound();" in attack_fn
    patch_shell = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "_maybePlayIncomingAttackNotify(data.fleet_alerts)" in patch_shell
    assert '[GC] notify check' in src


def test_main_js_gc657_fleet_drawer_timer_selection_separation():
    """GC-657+: compact fleet HUD rows with per-row countdown and hover tooltip."""
    src = _read("static/main.js")
    css = _read("static/style.css")
    assert "fleetDrawerCountdownAt" in src
    assert "_fleetDrawerSelectedId" not in src
    assert "updateFleetDrawerRowTimers" in src
    assert "formatFleetDrawerArrivalCompact" in src
    assert "fleetDrawerTotalShips" in src
    assert "toggleFleetDrawerSelection" not in src
    assert "data-fleet-drawer-detail" not in src
    assert "gc-fleet-drawer-timer-pulse" in css
    assert ".gc-fleet-hud-row" in css
    countdown = src.split("function patchFleetDrawerRowCountdown(row, mv)")[1].split("function createFleetDrawerFlightRoute")[0]
    assert "fleetDrawerCountdownAt(mv)" in countdown
    assert "prevKey !== countdownKey" in countdown
    assert 'row.querySelector("[data-fleet-drawer-countdown]")' in countdown
    row_fn = src.split("function createFleetDrawerRow(mv)")[1].split("function renderGlobalFleetHud")[0]
    assert "fleetDrawerCountdown" in row_fn
    assert "gc-fleet-hud-route" in row_fn
    assert "gc-fleet-hud-main" in row_fn
    assert "createFleetHudFlightTrack()" in row_fn
    assert "[data-fleet-hud-track]" in src
    assert "patchFleetHudFlightTrack" in src
    assert "fleetHudFlightVisual" in src
    assert "_maybeRefreshStaleMovementCountdowns()" in src.split("function updatePageTimers(serverNow)")[1].split("function updateMovementCountdowns")[0]
    assert ".gc-fleet-hud-track" in css
    assert "gc-fleet-hud-track-dot" in css
    assert "is-snap" in css
    assert "gc-fleet-hud-meta" in css
    row_css = css.split(".gc-fleet-hud-row,")[1].split(".gc-fleet-hud-main{")[0]
    assert "grid-template-columns: minmax(0, 38%) minmax(96px, 1fr) 18.5rem" in row_css
    meta_css = css.split(".gc-fleet-hud-meta{")[1].split(".gc-fleet-hud-leg{")[0]
    assert "grid-template-columns: 3.6rem 4.5rem 3.4rem 6rem" in meta_css


def test_main_js_gc654b_fleet_drawer_visual_polish():
    """GC-654B: compact fleet HUD, mission tooltip, recall action."""
    src = _read("static/main.js")
    css = _read("static/style.css")
    base = _read("templates/base.html")
    fleet_py = _read("game/fleet.py")
    assert "syncFleetDrawerList" in src
    assert "fleetDrawerRowCanAct" in src
    assert "fleetDrawerResolveMovementId" in src
    assert "upsertFleetDrawerActionBtn" in src
    assert "gc-fleet-hud-action-wrap" in src
    assert "document.addEventListener(\"click\"" in src.split("function initGlobalFleetDrawer()")[1].split("function patchFleetDrawerRowFlight")[0]
    assert "res.data?.state" in src.split("async function handleFleetDrawerRecall")[1].split("function initGlobalFleetDrawer")[0]
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


def test_main_js_fleet_hud_sticky_live_state():
    """Fleet header must not flash empty between valid poll/action states (GC-FLEET-HUD-STABLE)."""
    src = _read("static/main.js")
    assert "function resolveFleetHudPayload(raw, opts)" in src
    assert "GC.resolveFleetHudPayload = resolveFleetHudPayload" in src
    assert "function isActiveFleetsPayloadMissing(raw)" in src
    assert "function isFleetHudConfirmedEmpty(raw)" in src
    assert "function mergeFleetMovementIntoHud(mv, opts)" in src
    assert "function preserveFleetHudAcrossNavigation()" in src
    assert "function patchFleetHudFromActionPayload(json, reason)" in src
    assert "function canClearFleetHudToEmpty(raw, opts, stateVersion)" in src
    assert "_fleetHudStickyPayload" in src
    assert "_fleetHudActionVersion" in src
    assert "_gameStateFetchSeq" in src
    assert "_gameStateFetchAppliedSeq" in src
    assert "markGameStateFetchApplied" in src
    assert "_fetchSeq: fetchSeq" in src
    assert "preserveFleetHudAcrossNavigation()" in src.split("async function applyPjaxPayload(url, payload, doc, opts = {})")[1].split("function pjaxPayloadFromDoc")[0]
    assert "patchFleetHudFromActionPayload(json, reasonStr)" in src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert "mergeFleetMovementIntoHud(payload.fleet" in src

    render_fn = src.split("function renderGlobalFleetHud(fleetsRaw, opts)")[1].split("function syncFleetVacationNotice")[0]
    assert "resolveFleetHudPayload(fleetsRaw" in render_fn
    assert "syncFleetDrawerList(listEl, visibleItems, {" in render_fn
    assert "innerHTML" not in render_fn

    sync_list = src.split("function syncFleetDrawerList(listEl, visibleItems, opts)")[1].split("function patchFleetDrawerRowFlight")[0]
    assert "allowRemove" in sync_list
    assert "insertBefore(row, targetBefore)" in sync_list
    assert "listEl.innerHTML" not in sync_list

    shell_vis = src.split("function _syncFleetHudShellVisibility(root, fleetCount, alerts, opts)")[1].split("function createFleetAttackAlertRow")[0]
    assert "hasExistingRows" in shell_vis
    assert "explicitEmpty" in shell_vis

    assert "function resolveFleetHudShellVisibilityMeta()" in src
    assert "GC.resolveFleetHudShellVisibilityMeta = resolveFleetHudShellVisibilityMeta" in src
    sync_alert = src.split("function syncFleetAttackAlert(alerts)")[1].split("GC.syncFleetAttackAlert = syncFleetAttackAlert")[0]
    assert "resolveFleetHudShellVisibilityMeta()" in sync_alert
    assert "GC.lastState?.active_fleets).count" not in sync_alert

    patch_hud = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "resolveFleetHudPayload(data.active_fleets" in patch_hud

    patch_last = src.split("function patchHudLastState(data, reason)")[1].split("function commitGameStateCache")[0]
    assert 'key === "active_fleets"' in patch_last
    assert "isFleetHudConfirmedEmpty(incoming)" in patch_last

    notif = src.split("function applyNotificationSummary(data, reason)")[1].split("function scheduleNotificationPoll")[0]
    assert "_lastAppliedNotificationRevision" in notif
    assert "notification_revision" in notif
    assert "fleetAlertsHudSignature" in notif

    shell_once = src.split("function initShellOnce()")[1].split("// Boot")[0]
    assert "if (!shouldRunGameLoop())" in shell_once
    assert "pageHasSsrLiveBoot()" in src.split("function initGlobalFleetDrawer()")[1].split("GC.initGlobalFleetDrawer = initGlobalFleetDrawer")[0]

    fleet_py = _read("game/fleet.py")
    assert "fleets_confirmed_empty" in fleet_py
    assert "active_fleet_count" in fleet_py


def test_main_js_gc640b_fleet_page_visual_redesign():
    """GC-640B/640E: fleet command layout evolved to OGame-like table + integrated logistics."""
    tpl = _read("templates/fleet.html")
    css = _read("static/style.css")
    js = _read("static/main.js")
    assert "fleet-ogame-stack" in tpl
    assert "fleet-ship-card-grid" in tpl
    assert "data-fleet-mode-tab" in tpl
    assert "data-fleet-mode-panel" in tpl
    assert 'id="logistics-page"' in tpl
    assert "data-ship-max-image" in tpl
    assert "fleet-ship-card-role-badge" in tpl
    assert "fleet-ship-card-stock-badge" in tpl
    assert "data-fleet-ship-stock" in tpl
    assert "fleet-shipyard-link-panel" not in tpl
    assert "fleet-logistics-cta" not in tpl
    assert ".fleet-ship-card" in css
    assert ".fleet-ogame-stack" in css
    assert "data-ship-max-image" in js
    assert "function applyFleetPageMode(page)" in js
    assert "normalizeFleetDrawerItem" in js
    assert "normalizeActiveFleetsPayload" in js


def test_main_js_gc640c_fleet_dense_ship_cards():
    """GC-640C/640F: compact ship cards — grouped grid, no inner scroll."""
    css = _read("static/style.css")
    tpl = _read("templates/fleet.html")
    assert ".fleet-ship-card" in css
    assert "fleet-ship-thumb" in css
    assert "fleet-ship-card-grid" in tpl
    assert "data-fleet-ships-grid" in tpl


def test_main_js_gc640f_fleet_no_scroll_ship_selector():
    """GC-640F: ship cards in responsive grid; logistics rows stay scoped."""
    css = _read("static/style.css")
    assert ".fleet-ships-grid > .fleet-ship-row:not(.fleet-ship-card)" in css
    assert "grid-template-columns: repeat(auto-fill, minmax(100px, 112px))" in css
    assert ".fleet-ship-card-grid" in css
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
    """GC-640J: mode tabs and quicktargets use dezente dark outline control styling."""
    tpl = _read("templates/fleet.html")
    css = _read("static/style.css")
    assert "data-fleet-quick-target-select" in tpl
    assert "data-fleet-expedition-shortcut" in tpl
    assert "fleet-colony-chips" not in tpl
    assert "data-gc-hud-select" in tpl
    assert ".fleet-expedition-shortcut" in css
    tab_active = css.split(".fleet-mode-tab.active,")[1].split("@media (max-width: 640px)")[0]
    assert "linear-gradient(180deg, #0d3442, #061823)" in tab_active


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
    """GC-546D: timer-zero completion routes through one canonical include_panel refresh."""
    src = _read("static/main.js")

    assert "function requestProductionCompletionSync(opts)" in src
    assert "function _timerZeroAlreadyFired(el, target)" in src
    assert "el.dataset.refreshFiredAt" in src
    assert "function refreshShipyardStateCoalesced(page)" in src
    assert "function refreshDefenseStateCoalesced(page)" in src
    assert "_shipyardApiInFlight" in src
    assert "_defenseApiInFlight" in src

    prod_sync = src.split("function requestProductionCompletionSync(opts)")[1].split("function requestQueueTimerZeroRefresh")[0]
    assert "requestQueueTimerZeroRefresh" in prod_sync
    assert "refreshShipyardStateCoalesced(syPage)" not in prod_sync

    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent")[0]
    assert "syncProductionPanelsAfterGameState(data, reason, activePlanetId)" in apply
    assert "function patchDefensePanelFromGameState(data, activePlanetId)" in src
    assert "scheduleShipyardRefreshFromState(true)" not in apply
    assert "scheduleDefenseRefreshFromState(true)" not in apply

    sync_prod = src.split("function syncProductionPanelsAfterGameState(data, reason, activePlanetId)")[1].split("function applyGameStateData")[0]
    assert "patchDefensePanelFromGameState(data, activePlanetId)" in sync_prod
    assert "completionReason" in sync_prod

    progress = src.split("function updateAllProgressBars(serverNow)")[1].split("let lastHadActiveJob = false")[0]
    assert 'document.getElementById("shipyard-page")?.querySelector(".shipyard-job.shipyard-job-active")' in progress
    assert 'document.getElementById("defense-page")?.querySelector(".shipyard-job.shipyard-job-active")' in progress
    assert "requestProductionCompletionSync" in progress
    assert "requestQueueTimerZeroRefresh" in progress
    assert "scheduleShipyardRefreshFromState(true)" not in progress
    assert "scheduleDefenseRefreshFromState(true)" not in progress

    finish = src.split("function requestFinishRefresh(type)")[1].split("function releaseFinishRefreshLock")[0]
    assert 'type === "shipyard"' in finish
    assert "requestQueueTimerZeroRefresh" in finish

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
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent")[0]
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
    progress = src.split("function updateAllProgressBars(serverNow)")[1].split("let lastHadActiveJob = false")[0]
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


def test_main_js_auth_session_recovery_on_failure():
    """Lost session must notify and redirect — not leave a dead ingame shell."""
    src = _read("static/main.js")
    assert "function scheduleAuthSessionRecovery(reason)" in src
    recovery = src.split("function scheduleAuthSessionRecovery(reason)")[1].split("function handleAuthFailure", 1)[0]
    assert "msg_session_expired" in recovery
    assert 'window.location.assign("/login")' in recovery
    assert "quiesceLiveClientFetches" in recovery
    auth = src.split("function handleAuthFailure(reason)")[1].split("function throwAuthError", 1)[0]
    # Soft failures need a streak; hard 401/redirect still recover immediately.
    assert "scheduleAuthSessionRecovery(reasonStr)" in auth
    assert "noteConfirmedAuthFailure" in auth
    vis = src.split("function initVisibilityPolling()")[1].split("function initMobileNav", 1)[0]
    assert "_authRecoveryStarted" in vis
    assert 'GC.refreshGameState("tab_visible")' in vis


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
    # Requirement unchanged: on the ingame boot path, landscape before final syncPerfBodyClasses.
    shell = src.split("function initShellOnce()")[1].split("// =========================\n  // Boot")[0]
    boot_at = shell.find("bootstrapPlanetLandscapeFromBoot()")
    assert boot_at >= 0
    assert shell.find("syncPerfBodyClasses()", boot_at) > boot_at
    assert "applyPlanetLandscapeFromState(GC.lastState)" in src

    clear = src.split("function applyPlanetLandscapeFromState(data)")[1].split("function ensurePlanetLandscapeAfterSoftNav")[0]
    assert 'classList.remove("gc-has-planet-landscape")' in clear

    block = css.split("GC-547C")[1][:900]
    assert "gc-has-planet-landscape" in block
    assert "body.gc-perf-idle.gc-has-planet-landscape .gc-bg" in block


def test_main_js_pjax_preserves_shell_landscape_when_payload_empty():
    """PJAX lightweight SSR omits landscape — must not clear shell; restore from lastState/boot."""
    src = _read("static/main.js")
    assert "function ensurePlanetLandscapeAfterSoftNav()" in src
    pjax = src.split("async function applyPjaxPayload(url, payload, doc, opts = {})")[1].split(
        "function pjaxPayloadFromDoc"
    )[0]
    assert "ensurePlanetLandscapeAfterSoftNav()" in pjax
    assert 'classList.remove("gc-has-planet-landscape")' not in pjax
    assert 'removeProperty("--planet-landscape")' not in pjax
    soft_pe = src.split("async function _softReloadPlanetEvolutionContent()")[1].split(
        "function _schedulePlanetEvolutionRefreshAfterAction"
    )[0]
    assert "ensurePlanetLandscapeAfterSoftNav()" in soft_pe
    switch = src.split('applyActionState(res, "planet_switch")')[1][:2200]
    assert "ensurePlanetLandscapeAfterSoftNav()" in switch


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
    init_page = src.split("GC.initPage = function initPage", 1)[1].split("GC.cleanupPage", 1)[0]
    assert "GC.restoreLeftmenuState(window.location.href)" in init_page
    assert ".gc-bld-head-action-btn{" in css


def test_main_js_gc550c_buildings_hero_queue_and_subnav():
    """GC-550C: hero progress overlay, same-building re-queue, subnav collapse."""
    src = _read("static/main.js")
    buildings_html = _read("templates/buildings.html")
    research_html = _read("templates/research.html")
    base_html = _read("templates/base.html")
    sidebar_html = _read("templates/partials/sidebar.html")
    sidebar_right_html = _read("templates/partials/sidebar_right.html")
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
    sidebar_html = _read("templates/partials/sidebar.html")
    sidebar_right_html = _read("templates/partials/sidebar_right.html")
    assert "gc-nav-buildings-toggle" in sidebar_html
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
    sidebar_right_html = _read("templates/partials/sidebar_right.html")
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
    assert 'data-nav-section="economy"' in sidebar_right_html
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
    assert "function reorderCardQueueBlocks(cardEl)" not in src
    assert "GC.clearBuildingCardQueue" not in src
    assert "function syncCardQueueOwnerClassesFromBlocks(cardEl, fallbackDomain)" in src
    assert "function requestQueueTimerZeroRefresh(meta)" in src
    assert "forceCanonicalGameStateRefresh(\"queue_timer_zero\")" in src
    timer_zero_fn = src.split("function requestQueueTimerZeroRefresh(meta)")[1].split(
        "function markCardQueueZeroRefresh"
    )[0]
    assert "forceCanonicalGameStateRefresh" in timer_zero_fn
    assert "refreshShipyardStateCoalesced" not in timer_zero_fn
    assert "QUEUE_TIMER_ZERO_DEBOUNCE_MS = 150" in src
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

    can_patch = src.split("function canPatchCardQueueInPlace(existing, queueJob)")[1].split(
        "function _patchCardQueueTimingDatasets"
    )[0]
    assert "jobId !== prevJobId" in can_patch
    assert "wasActive !== isActive" in can_patch
    assert "function _patchCardQueueTimingDatasets(block, queueJob)" in src

    progress = src.split("function updateAllProgressBars(serverNow)")[1].split("let lastHadActiveJob = false")[0]
    assert "requestQueueTimerZeroRefresh" in progress


def test_gc551a_fuel_cell_icon_and_hero_level_badge():
    """GC-551A: fuel_cells uses same resource chip family; hero level badge stays readable."""
    icons_py = _read("tools/generate_icons.py")
    base_html = _read("templates/base.html")
    sidebar_html = _read("templates/partials/sidebar.html")
    sidebar_right_html = _read("templates/partials/sidebar_right.html")
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
    assert "img/res/Brennzellen.webp" in progression
    fuel_block = base_html.split('class="hud-res-panel hud-res-fuel-cells"')[1].split("</div>", 1)[0]
    assert "onerror" not in fuel_block
    assert "icons/energy.png" not in fuel_block
    assert ".gc-level-badge.gc-bld-card-level--hero" in css
    hero_badge = css.split(".gc-level-badge.gc-bld-card-level--hero")[1].split("}", 1)[0]
    assert "background:" in hero_badge
    assert "rgba(5, 14, 24" in hero_badge or "rgb(6, 12, 26)" in hero_badge
    assert ".hud-res-fuel-cells .res-icon" in css
    assert "gc-res-fuel-cells" in css
    assert "render_resource_icon" in _read("templates/base.html")
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
    apply_section = src.split("function applyGameStateData")[1].split("function refreshPageAfterQueueEvent")[0]
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
    assert "webp_static" in buildings
    assert 'fetchpriority="high"' in buildings


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


def test_gc804_leftmenu_ui_state_independent_from_game_state_poll():
    """GC-804: leftmenu accordion state is client-owned, not tied to game-state poll."""
    src = _read("static/main.js")
    assert "GC.restoreLeftmenuState = function restoreLeftmenuState" in src
    restore_left = src.split("GC.restoreLeftmenuState = function restoreLeftmenuState", 1)[1].split("function applyMobileBottomNav", 1)[0]
    assert "restoreSidebarMenuState(" in restore_left
    assert "markLeftmenuActiveLinks(targetUrl, routeCtx)" in restore_left
    assert "sidebar_nav" not in restore_left
    assert "NAV_SECTION_STORAGE_KEY_RIGHT" in src
    poll_apply = src.split("function applyHudOnlyGameState", 1)[1].split("function applyGameStateData", 1)[0]
    assert "restoreLeftmenuState" not in poll_apply
    sync_role = src.split("GC.syncRoleBasedSidebar = function syncRoleBasedSidebar", 1)[1].split("function initRoleBasedSidebar", 1)[0]
    assert "applyDesktopSidebarNav(sidebar, nav)" in sync_role
    assert "applyDesktopSidebarNav(sidebarRight, nav)" in sync_role
    assert "GC.restoreLeftmenuState(window.location.href)" in sync_role
    buildings_tabs = src.split("function bindBuildingTabsOnce", 1)[1].split("function initBuildings", 1)[0]
    assert 'GC.navigateTo(`/buildings?tab=${encodeURIComponent(tab)}`)' in buildings_tabs
    assert 'data-building-tab="military"' in _read("templates/partials/sidebar.html")


def test_main_js_mini_queue_research_label_resolution():
    """Research mini-queue titles resolve i18n keys, not raw tech_key."""
    src = _read("static/main.js")
    assert "function _resolveQueueJobDisplayName(job, domain)" in src
    mini = src.split("function _resolveMiniQueueLabel(job, domain)")[1].split("GC.renderMiniQueueStrip = function")[0]
    assert "_resolveQueueJobDisplayName(job, domain)" in mini
    collect = src.split("function _collectResearchQueueCardJobs(researchRaw)")[1].split("function _globalQueueHudDomainTitle")[0]
    assert "label_key: raw.label_key || ownerKey" in collect


def test_main_js_timekeeper_apply_btn_survives_live_queue_patch():
    """Live queue re-renders must keep ⚡ Zeit einsetzen on active jobs."""
    src = _read("static/main.js")
    assert "function _syncTimekeeperApplyBtn(parent, domain, queueJob)" in src
    mini = src.split("GC.renderMiniQueueStrip = function renderMiniQueueStrip")[1].split("function _renderProductionMiniQueue")[0]
    assert "_syncTimekeeperApplyBtn(card, domain, job)" in mini
    hero = src.split("function renderHeroQueueOverlay(cardEl, queueJob, opts)")[1].split("function _cardQueueTimerMeta")[0]
    assert "_syncTimekeeperApplyBtn(block, domain, queueJob)" in hero
    card_block = src.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split("function _syncBuildQueueLiveState")[0]
    assert "_syncTimekeeperApplyBtn(block, domain, queueJob)" in card_block


def test_main_js_timekeeper_queue_btn_is_compact_icon():
    src = _read("static/main.js")
    assert 'className = "gc-queue-timekeeper-btn"' in src
    assert 'innerHTML = \'<span aria-hidden="true">⚡</span>\'' in src
    macro = _read("templates/partials/card_queue_macros.html")
    assert "gc-queue-timekeeper-btn" in macro
    assert '<span aria-hidden="true">⚡</span>' in macro
    css = _read("static/style.css")
    assert ".gc-queue-timekeeper-btn" in css
    assert "grid-column: 1 / -1" not in css.split(".gc-queue-timekeeper-btn")[1].split("@media")[0]


def test_main_js_timekeeper_one_click_apply_flow():
    """⚡ on queue cards must POST mode=max directly — no modal."""
    src = _read("static/main.js")
    tk = src.split("function initTimekeeperOnce()")[1].split("function patchShellHudFromState")[0]
    assert "submitTimekeeperApplyFromBtn(openBtn)" in tk
    assert 'mode: "max"' in src.split("function submitTimekeeperApplyFromBtn")[1].split("function initTimekeeperOnce")[0]
    assert "openTimekeeperModal" not in src
    assert "gc-timekeeper-modal" not in src
    assert 'applyActionState(res, "timekeeper_apply")' in src
    assert "_timekeeperApplying" in src
    assert "_timekeeperOpenContext(openBtn)" in src
    assert 'GC.fetchGameAction("/api/timekeeper/apply"' in src
    assert "gc-timekeeper-modal" not in _read("templates/base.html")


def test_main_js_timekeeper_research_card_selector():
    src = _read("static/main.js")
    assert "function _findResearchCard(ownerKey)" in src
    assert '[data-research-card][data-tech-key="' in src
    assert "function _syncActiveMiniQueueTimekeeperButtons()" in src
    sync_state = src.split("function _syncTimekeeperButtonsFromState(state)")[1].split("function _refreshDomTimekeeperApplyBtns", 1)[0]
    assert '_findResearchCard(ownerKey)' in sync_state
    assert "querySelectorAll(\"[data-tech-key]\")" not in sync_state
    # GC-UNIT-QUEUE-DEDUP-001: unit-queue TK only via mini strip, never unit cards.
    assert 'data-ship-key="${shipKey}"' not in sync_state
    assert 'data-defense-card="${defKey}"' not in sync_state
    assert "_syncMiniQueueTimekeeperFromState(state)" in sync_state
    finalize = src.split("function _finalizeTimekeeperQueueButtons(state)")[1].split("function _queueJobTimekeeperRemaining")[0]
    assert "_syncActiveMiniQueueTimekeeperButtons()" in finalize
    assert "_syncTimekeeperButtonsFromState(state)" in finalize


def test_main_js_timekeeper_buttons_sync_immediately_after_action_state():
    """⚡ must appear on queue start without waiting for the next poll."""
    src = _read("static/main.js")
    apply = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert "_primeActionStateTimekeeper(state)" in apply
    assert "_finalizeTimekeeperQueueButtons(state)" in apply
    assert "patchQueuePanelsImmediate(state)" in apply
    assert "resetQueueRenderSignaturesForImmediatePatch()" in apply
    assert "function _finalizeTimekeeperQueueButtons(state)" in src
    assert "function _findGlobalActiveCardJob(queueRaw)" in src
    assert "function _iterActiveCardJobsByOwner(queueRaw)" in src
    assert "function _refreshDomTimekeeperApplyBtns(serverNowTs)" in src
    assert "function _syncMiniQueueTimekeeperFromState(state)" in src
    assert "function _syncTimekeeperButtonsFromState(state)" in src
    assert '"timekeeper"' in src.split("const _HUD_LAST_STATE_KEYS = [")[1].split("];")[0]
    patch_immediate = src.split("function patchQueuePanelsImmediate(data)")[1].split("let _finishRefreshTimer", 1)[0]
    assert "buildings_panel_delta || data.buildings_panel" in patch_immediate
    assert "patchShipyardPanelFromState(data, activePlanetId)" in patch_immediate
    assert "patchDefensePanelFromGameState(data, activePlanetId)" in patch_immediate
    assert "patchResearchPanel(researchRaw.techs, researchRaw)" in patch_immediate
    finalize = src.split("function _finalizeTimekeeperQueueButtons(state)")[1].split("function _queueJobTimekeeperRemaining")[0]
    assert "_clearScopeTimekeeperApplyBtns(document)" not in finalize
    assert "_syncTimekeeperButtonsFromState(state)" in finalize
    assert "_refreshDomTimekeeperApplyBtns(getTimerServerNow())" in finalize
    can_patch = src.split("function canPatchCardQueueInPlace(existing, queueJob)")[1].split("function _patchCardQueueTimingDatasets")[0]
    assert "finishAt !== prevFinish" not in can_patch
    ticker = src.split("function updateAllProgressBars(serverNow)")[1].split("function updateMiniQueueProgressBars", 1)[0]
    assert "_refreshDomTimekeeperApplyBtns(serverNowTs)" in ticker
    tab = src.split("function activateBuildingTabByName(targetTab, focusEl)")[1].split("function bindBuildingTabsOnce", 1)[0]
    assert "_finalizeTimekeeperQueueButtons(GC.lastState)" in tab
    mutation = src.split("function isMutationStatePatchReason(reason)")[1].split("function resetQueueRenderSignaturesForImmediatePatch")[0]
    assert 'r.endsWith("_apply")' in mutation


def test_main_js_inventory_tk_chip_deposits_without_scroll_jump():
    src = _read("static/main.js")
    assert "function depositTimekeeperChip(chipBtn, domain)" in src
    assert "function listDepositableLegacyTimeItems(domain)" in src
    assert "function countDepositableLegacyTimeItems(domain)" in src
    assert "deposit_domain:" in src
    assert 'reason !== "invalid_item"' in src
    inv = src.split("function bindInventoryOnce()")[1].split("function tickInventoryCooldowns")[0]
    assert "depositTimekeeperChip(tkChip" in inv
    assert "ev.preventDefault()" in inv.split("depositTimekeeperChip(tkChip")[0][-400:]
    effect = src.split("function renderInventoryEffect(effect, opts)")[1].split("function isInventoryPayload")[0]
    assert 'effect?.kind === "timekeeper_credit"' in effect
    assert "showNotify(text, \"success\")" in effect
    scroll = src.split("function scrollInventoryToFeedback(opts)")[1].split("function renderInventoryEffect")[0]
    assert "window.scrollTo" not in scroll
    assert "preserveScroll" in scroll

def test_main_js_trader_hub_exchange_live_preview():
    """Trader Hub: preview runs after formatted number input; locale parsing covers grouped ints."""
    src = _read("static/main.js")
    parse_fn = src.split("function parseIntNumber(n)")[1].split("function formatNumber")[0]
    assert r"^-?\d{1,3}(,\d{3})+$" in parse_fn
    assert "digitsOnly" in parse_fn
    exchange = src.split("function initExchangePanel()")[1].split("function renderScrapyardRows")[0]
    assert "scheduleUpdatePreview" in exchange
    assert "requestAnimationFrame" in exchange
    assert 'amountInput.addEventListener("input", scheduleUpdatePreview)' in exchange
    assert 'amountInput.addEventListener("change", scheduleUpdatePreview)' in exchange
    assert 'amountInput.addEventListener("paste"' in exchange
    assert "readNumberInput(amountInput)" in exchange
    assert "parseIntNumber(amount)" in exchange
    assert "setNumberInputValue(amountInput, minNow)" in exchange


def test_main_js_imperial_directives_full_state_endpoint():
    """Cards must load from /api/imperial-directives/state, not game-state summary."""
    src = _read("static/main.js")
    assert '"/api/imperial-directives/state"' in src
    assert "function refreshImperialDirectivesFullState" in src
    assert "function _patchImperialDirectivesFromGameStateSummary" in src
    assert "patchImperialDirectivesDom(data.imperial_directives)" not in src
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent", 1)[0]
    assert '_patchImperialDirectivesFromGameStateSummary(data.imperial_directives, reason)' in apply
    assert 'reason !== "page_hydrate"' in apply
    summary_fn = src.split("function _patchImperialDirectivesFromGameStateSummary(summary, reason)")[1].split("async function refreshImperialDirectivesFullState", 1)[0]
    assert "Array.isArray(summary.directives)" in summary_fn
    assert "return;" in summary_fn
    assert "dailyList.innerHTML" not in summary_fn
    patch_fn = src.split("function patchImperialDirectivesDom(state, opts)")[1].split("let _imperialDirectivesBound", 1)[0]
    assert "_imperialDirectivesStateUsable(state)" in patch_fn
    assert "_imperialDirectivesHasSsrCards(page)" in patch_fn
    assert "if (dailyList && daily.length)" in patch_fn
    card_html = src.split("function _idDirectiveCardHtml(d)")[1].split("let _idCountdownTimer", 1)[0]
    assert "inventory-loot-card-name" in card_html
    assert "data-directive-progress-fill" in card_html
    assert "data-directive-claim" in card_html
    init = src.split("function initImperialDirectives()")[1].split("function parseGalacticPoliticsPageState", 1)[0]
    assert "_imperialDirectivesHasSsrCards(page)" in init
    assert "refreshImperialDirectivesFullState" in init
    assert "if (!hasSsrCards)" in init
    assert "_logImperialDirectivesRender" in src


def test_main_js_imperial_directive_expire_timer_targets_label_only():
    """Expire countdown must not set textContent on the card root."""
    src = _read("static/main.js")
    sync_fn = src.split("function _syncImperialDirectiveCountdowns(page)")[1].split("function patchImperialDirectivesDom", 1)[0]
    assert "[data-directive-expires-label]" in sync_fn
    assert "label.textContent" in sync_fn
    assert 'querySelectorAll("[data-directive-expires]")' not in sync_fn
    card_html = src.split("function _idDirectiveCardHtml(d)")[1].split("let _idCountdownTimer", 1)[0]
    assert "data-directive-expires-at" in card_html
    assert "data-directive-expires-label" in card_html
    assert 'data-directive-expires="' not in card_html
    tpl = _read("templates/imperial_directives.html")
    assert "data-directive-expires-at" in tpl
    assert "data-directive-expires-label" in tpl
    assert 'data-directive-expires="{{' not in tpl


def test_main_js_notification_poll_singleton_heartbeat():
    """Lightweight notification poll — unread/attack only, deduped against game-state."""
    src = _read("static/main.js")
    assert "const NOTIFICATION_POLL_MS = 12000" in src
    assert "const NOTIFICATION_POLL_HIDDEN_MS = 20000" in src
    assert "NOTIFICATION_GAME_STATE_DEDUP_MS" in src
    assert "shouldSkipNotificationPollFetch" in src
    assert "markNotificationFreshFromGameState" in src
    assert '"/api/notifications/summary"' in src
    assert "function applyNotificationSummary(data, reason)" in src
    assert "GC.startNotificationPoll" in src
    assert "GC.stopNotificationPoll" in src
    assert "_lastAppliedNotificationRevision" in src
    assert "fleetAlertsHudSignature" in src
    start_poll = src.split("GC.startPolling = function startPolling")[1].split("function scheduleMessagesInboxBoot")[0]
    assert "GC.startNotificationPoll()" in start_poll or "GC.startNotificationPoll(deferFirstPoll" in start_poll
    assert "Math.min(next, 3000)" in start_poll
    coerce = src.split("function coercePollUnreadForHud(data, reason)")[1].split("function updateMessagesUnreadBadges")[0]
    assert 'r === "notification_poll"' in coerce
    assert 'r === "queue_timer_zero"' in coerce


def test_main_js_force_canonical_refresh_on_timer_zero():
    """Timer zero must fetch include_panel=1 and apply with forcePanel."""
    src = _read("static/main.js")
    assert "async function forceCanonicalGameStateRefresh(reason, opts)" in src
    assert '"/api/game-state?include_panel=1"' in src.split("async function forceCanonicalGameStateRefresh")[1].split("GC.forceCanonicalGameStateRefresh")[0]
    timer_zero = src.split("function requestQueueTimerZeroRefresh(meta)")[1].split("function markCardQueueZeroRefresh")[0]
    assert "forceCanonicalGameStateRefresh" in timer_zero
    assert "QUEUE_TIMER_ZERO_DEBOUNCE_MS = 150" in src
    assert "TIMER_ZERO_REFRESH_MIN_MS = 250" in src


def test_main_js_unread_increase_plays_sound_without_inbox():
    """Unread increase triggers sound via notification poll — inbox open not required."""
    src = _read("static/main.js")
    unread_fn = src.split("function _processUnreadMessagesPoll(data, reason, opts)")[1].split("function updateNavBadges")[0]
    assert "_maybePlayMessageNotifySound(data, { unreadIncreased: true })" in unread_fn
    assert "_queueMessageNotifyItems" in unread_fn
    assert "_lastMessagesUnreadPoll = hudUnread" in unread_fn
    notif = src.split("function applyNotificationSummary(data, reason)")[1].split("function scheduleNotificationPoll")[0]
    assert "_processUnreadMessagesPoll(hudSlice, reasonStr, {})" in notif
    assert "notifications: data.notifications" in notif
