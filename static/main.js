/* ============================================================================
   GENESIS COLONIES – main.js (final unified)
   - safer globals (IIFE + "use strict")
   - i18n: t() + tf() with %(var)s and {var}
   - Score: animate + delta pop (single implementation)
   - Polling: no overlap, abortable, adaptive setTimeout loop
   - Server time sync: drift-safe for research + build queue
   - Build queue: correct i18n + LIVE progress per second (no extra fetch)
   ============================================================================ */

(() => {
  "use strict";

  // =========================
  // i18n helpers
  // =========================
  function t(key, fallback) {
    try {
      const dict = window.GC_LOCALE || window.I18N || window.LOCALE || null;
      if (dict && Object.prototype.hasOwnProperty.call(dict, key)) {
        const val = dict[key];
        if (val !== null && val !== undefined && String(val).length > 0) return String(val);
      }
    } catch (_) {}
    return fallback || key;
  }

  // supports "%(var)s" and "{var}"
  function tf(key, vars = {}, fallback = "") {
    let s = t(key, fallback || key);
    if (typeof s !== "string") return fallback || "";
    s = String(s);

    // %(name)s
    s = s.replace(/%\(([^)]+)\)s/g, (_, k) => {
      const v = vars[k];
      return v === undefined || v === null ? "" : String(v);
    });

    // {name}
    s = s.replace(/\{([^}]+)\}/g, (_, k) => {
      const v = vars[k];
      return v === undefined || v === null ? "" : String(v);
    });

    return s;
  }

  // =========================
  // DOM helpers
  // =========================
  function qs(root, sel) {
    return (root || document).querySelector(sel);
  }
  function qsa(root, sel) {
    return Array.from((root || document).querySelectorAll(sel));
  }
  function setText(id, value) {
    const el = document.getElementById(id);
    const s = String(value);
    if (el && el.textContent !== s) el.textContent = s;
  }
  function _setIfChanged(el, text) {
    if (!el) return;
    const s = String(text);
    if (el.textContent !== s) el.textContent = s;
  }

  // =========================
  // Format helpers
  // =========================
  function fmtNumber(n) {
    const num = Number(n || 0);
    if (!Number.isFinite(num)) return "0";
    return num.toLocaleString("de-DE");
  }

  // UI-style ETA: "3m 12s" etc
  function formatEta(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  // robust parsing for text like "3m 12s", "1h 02m 01s", "75s", "02:15", "1:02:03"
  function parseDurationToSeconds(text) {
    if (!text) return NaN;
    const s = String(text).trim();

    if (/^\d+:\d{2}(:\d{2})?$/.test(s)) {
      const parts = s.split(":").map((x) => parseInt(x, 10));
      if (parts.length === 2) return parts[0] * 60 + parts[1];
      if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    }

    let total = 0;
    let matched = false;

    const h = s.match(/(\d+)\s*h/);
    const m = s.match(/(\d+)\s*m/);
    const sec = s.match(/(\d+)\s*s/);

    if (h) { total += parseInt(h[1], 10) * 3600; matched = true; }
    if (m) { total += parseInt(m[1], 10) * 60; matched = true; }
    if (sec) { total += parseInt(sec[1], 10); matched = true; }

    if (matched) return total;
    if (/^\d+$/.test(s)) return parseInt(s, 10);
    return NaN;
  }

  // =========================
  // time sync (server_time)
  // =========================
  const TIME = {
    serverNow: 0,        // seconds
    clientPerfAt: 0,     // performance.now() at sync
  };

  function setServerTime(serverTimeSec) {
    const v = parseInt(serverTimeSec, 10);
    if (!Number.isFinite(v) || v <= 0) return;
    TIME.serverNow = v;
    TIME.clientPerfAt = performance.now();
  }

  function getApproxServerNow() {
    if (!TIME.serverNow || !TIME.clientPerfAt) return 0;
    const dt = (performance.now() - TIME.clientPerfAt) / 1000;
    return TIME.serverNow + dt;
  }

  let _statusPollErrorLogged = false;
  let _authLoopAborted = false;

  const AUTH_ROUTE_RE = /^\/(login|register|logout)(\/|$)/i;

  function isAuthRoutePath() {
    const path = (window.location.pathname || "").replace(/\/$/, "") || "/";
    if (AUTH_ROUTE_RE.test(path)) return true;
    if (path === "/" && document.body?.dataset?.authPage === "1") return true;
    return false;
  }

  function hasLiveStatusRoot() {
    return !!document.querySelector(
      "#resource-bar, [data-live-status], #live-status-root, #game-status-root, .js-status-poller"
    );
  }

  function shouldRunGameLoop() {
    const body = document.body;
    if (!body) return false;
    if (body.classList.contains("gc-body-simple")) return false;
    if (body.dataset.authPage === "1") return false;
    if (isAuthRoutePath()) return false;
    if (!body.classList.contains("gc-body-ingame")) return false;
    if (!document.querySelector("#main-content")) return false;
    return hasLiveStatusRoot();
  }

  /** @deprecated use shouldRunGameLoop */
  function shouldRunStatusPolling() {
    return shouldRunGameLoop();
  }

  function handleAuthFailure(reason) {
    if (_authLoopAborted) return;
    _authLoopAborted = true;
    console.debug("[GC] auth redirect detected", reason || "");
    console.debug("[GC] polling aborted");
    GC.stopPolling();
    GC.stopProgressTicker();
    _statusPollErrorLogged = true;
  }

  function throwAuthError() {
    const err = new Error("not_logged_in");
    err.authRedirect = true;
    err.status = 401;
    throw err;
  }

  function isAuthRedirectResponse(res) {
    if (!res) return false;
    if (res.type === "opaqueredirect") return true;
    const status = Number(res.status || 0);
    if (status >= 300 && status < 400) return true;
    if (res.redirected && /\/login|\/register/i.test(String(res.url || ""))) return true;
    return false;
  }

  function inspectFetchResponseForAuth(res, contentType) {
    if (isAuthRedirectResponse(res)) {
      handleAuthFailure("redirect");
      throwAuthError();
    }
    const ct = (contentType || res.headers.get("content-type") || "").toLowerCase();
    if (ct.includes("text/html") && /\/api\//i.test(String(res.url || ""))) {
      handleAuthFailure("html-on-api");
      throwAuthError();
    }
  }

  function isAuthStatusFailure(err, data) {
    if (err?.authRedirect) return true;
    if (data?.error === "not_logged_in") return true;
    const status = Number(err?.status || 0);
    if (status === 401 || status === 403) return true;
    const msg = String(err?.message || "");
    return /HTTP 401|HTTP 403|not_logged_in|non_json_response|invalid_json_response/i.test(msg);
  }

  function applyActionState(json, reason) {
    if (!json || !json.state) return false;
    const anyActive = applyGameStateData(json.state, reason);
    GC.startPolling(anyActive || lastHadActiveJob || lastHadActiveResearch);
    GC.startProgressTicker();
    return anyActive;
  }

  function logStatusPollErrorOnce(reason, err) {
    if (_statusPollErrorLogged) return;
    _statusPollErrorLogged = true;
    console.warn("[GC] Status polling unavailable:", reason, err);
  }

  function markStatusWidgetOffline() {
    const root = document.querySelector(
      "[data-live-status], #live-status-root, #game-status-root, .js-status-poller, #resource-bar"
    );
    if (!root) return;
    root.setAttribute("data-connection", "offline");
    root.classList.add("is-status-offline");
  }

  function clearStatusWidgetOffline() {
    const root = document.querySelector(
      "[data-live-status], #live-status-root, #game-status-root, .js-status-poller, #resource-bar"
    );
    if (!root) return;
    root.removeAttribute("data-connection");
    root.classList.remove("is-status-offline");
  }

  // =========================
  // GC – zentraler Spielzustand + Page Lifecycle (SPA/PJAX)
  // =========================
  const GC = {
    finishLocks: { buildings: false, research: false },
    refreshInFlight: null,
    lastState: null,
    refreshGameState: null,
    currentPage: null,
    pjaxInFlight: null,
    _shellReady: false,
    _visibilityBound: false,
    _gameActionsBound: false,
    _tabsBound: false,
    _pjaxBound: false,
    pageLifecycle: {
      initialized: false,
      rafIds: [],
      intervals: [],
      timeouts: [],
      abortControllers: [],
      cleanupFns: [],
    },
    polling: {
      running: false,
      timeoutId: null,
      inFlight: false,
      abort: null,
      lastInterval: 0,
      backoff: 0,
      intervalActive: 1000,
      intervalIdle: 4000,
      intervalHidden: 12000,
    },
    modules: {},
  };

  GC.registerCleanup = function registerCleanup(fn, opts) {
    if (typeof fn !== "function") return;
    if (opts && opts.persistent) fn._gcPersistent = true;
    GC.pageLifecycle.cleanupFns.push(fn);
  };
  // Alias used by messages.js (older name)
  GC.registerPageCleanup = GC.registerCleanup;

  GC.cleanupPage = function cleanupPage() {
    console.debug("[GC] cleanupPage");
    const lc = GC.pageLifecycle;
    lc.rafIds.forEach((id) => { try { cancelAnimationFrame(id); } catch (_) {} });
    lc.intervals.forEach((id) => clearInterval(id));
    lc.timeouts.forEach((id) => clearTimeout(id));
    lc.abortControllers.forEach((c) => { try { c.abort(); } catch (_) {} });
    lc.cleanupFns.forEach((fn) => {
      try { fn(); } catch (e) { console.error("[GC] cleanup fn error", e); }
    });
    lc.cleanupFns = lc.cleanupFns.filter((fn) => fn._gcPersistent);
    lc.rafIds = [];
    lc.intervals = [];
    lc.timeouts = [];
    lc.abortControllers = [];
    GC.stopProgressTicker();
    GC.stopPolling();
    _statusPollErrorLogged = false;
    _lastQueueSignature = "";
    _lastResearchQueueSignature = "";
    _numAnim.forEach((st) => { if (st?.raf) cancelAnimationFrame(st.raf); });
    _numAnim.clear();
    if (typeof rankingAbortInFlight === "function") rankingAbortInFlight();
    _lastMessagesUnreadPoll = null;
    GC.currentPage = null;
    lc.initialized = false;
  };

  GC.requestFrame = function requestFrame(fn) {
    const id = requestAnimationFrame((ts) => {
      const idx = GC.pageLifecycle.rafIds.indexOf(id);
      if (idx >= 0) GC.pageLifecycle.rafIds.splice(idx, 1);
      fn(ts);
    });
    GC.pageLifecycle.rafIds.push(id);
    return id;
  };

  GC.setSafeTimeout = function setSafeTimeout(fn, ms) {
    const id = setTimeout(() => {
      const idx = GC.pageLifecycle.timeouts.indexOf(id);
      if (idx >= 0) GC.pageLifecycle.timeouts.splice(idx, 1);
      fn();
    }, ms);
    GC.pageLifecycle.timeouts.push(id);
    return id;
  };

  GC.setSafeInterval = function setSafeInterval(fn, ms) {
    const id = setInterval(fn, ms);
    GC.pageLifecycle.intervals.push(id);
    return id;
  };

  GC.fetchGameAction = async function fetchGameAction(url, options = {}) {
    const ctrl = new AbortController();
    GC.pageLifecycle.abortControllers.push(ctrl);
    const fetchOpts = { ...options };
    delete fetchOpts.signal;
    try {
      const res = await fetch(url, {
        ...fetchOpts,
        signal: ctrl.signal,
        credentials: fetchOpts.credentials || "same-origin",
        redirect: fetchOpts.redirect || "manual",
      });
      const ct = (res.headers.get("content-type") || "").toLowerCase();
      inspectFetchResponseForAuth(res, ct);
      let data = {};
      if (ct.includes("application/json")) {
        try {
          data = await res.json();
        } catch (_) {}
      }
      if (res.status === 401 || res.status === 403 || data.error === "not_logged_in") {
        handleAuthFailure(`action-http-${res.status}`);
        throwAuthError();
      }
      return data;
    } finally {
      const idx = GC.pageLifecycle.abortControllers.indexOf(ctrl);
      if (idx >= 0) GC.pageLifecycle.abortControllers.splice(idx, 1);
    }
  };

  function newRequestId() {
    try {
      if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    } catch (_) {}
    return `r${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }

  GC.actionLocks = { build: false, research: false };

  GC.fetchJSON = async function fetchJSON(url, options = {}) {
    const ctrl = new AbortController();
    GC.pageLifecycle.abortControllers.push(ctrl);
    const extSignal = options.signal;
    if (extSignal) {
      if (extSignal.aborted) ctrl.abort();
      else extSignal.addEventListener("abort", () => ctrl.abort(), { once: true });
    }
    const fetchOpts = { ...options };
    delete fetchOpts.signal;
    try {
      const res = await fetch(url, {
        ...fetchOpts,
        signal: ctrl.signal,
        credentials: fetchOpts.credentials || "same-origin",
        redirect: fetchOpts.redirect || "manual",
      });
      const status = res.status;
      const ct = (res.headers.get("content-type") || "").toLowerCase();

      inspectFetchResponseForAuth(res, ct);

      if (!res.ok) {
        if (status === 401 || status === 403) {
          handleAuthFailure(`http-${status}`);
          throwAuthError();
        }
        const err = new Error(`HTTP ${status}`);
        err.status = status;
        throw err;
      }
      if (!ct.includes("application/json")) {
        if (/login|register/i.test(String(res.url || ""))) {
          handleAuthFailure("non-json-login-url");
          throwAuthError();
        }
        const err = new Error("non_json_response");
        err.status = status;
        err.nonJson = true;
        throw err;
      }
      try {
        return await res.json();
      } catch (parseErr) {
        const err = new Error("invalid_json_response");
        err.status = status;
        err.parseError = parseErr;
        throw err;
      }
    } finally {
      const idx = GC.pageLifecycle.abortControllers.indexOf(ctrl);
      if (idx >= 0) GC.pageLifecycle.abortControllers.splice(idx, 1);
    }
  };

  GC.detectPage = function detectPage() {
    const path = (window.location.pathname || "").replace(/\/$/, "") || "/";
    if (path.endsWith("/buildings")) return "buildings";
    if (path.endsWith("/research")) return "research";
    if (path.endsWith("/planet-evolution")) return "planet_evolution";
    if (path.endsWith("/overview") || path === "/") return "overview";
    if (path.endsWith("/ranking")) return "ranking";
    if (path.endsWith("/messages")) return "messages";
    if (path.endsWith("/techtree")) return "techtree";
    if (path.endsWith("/admin")) return "admin";
    return "other";
  };

  GC.getServerNow = getApproxServerNow;

  GC.reloadCurrentPage = function reloadCurrentPage() {
    const target = `${window.location.pathname || "/"}${window.location.search || ""}`;
    if (typeof GC.navigateTo === "function") {
      return GC.navigateTo(target, { push: false });
    }
    window.location.reload();
    return Promise.resolve();
  };

  function hydratePageFromLastState(opts) {
    if (!GC.lastState || GC.lastState.ok !== true) return false;
    try {
      applyGameStateData(GC.lastState, "page_hydrate", opts);
      GC.startProgressTicker();
      return true;
    } catch (err) {
      console.error("[GC] page hydrate failed", err);
      return false;
    }
  }

  let _progressTickerActive = false;

  GC.stopProgressTicker = function stopProgressTicker() {
    _progressTickerActive = false;
  };

  GC.startProgressTicker = function startProgressTicker() {
    if (!shouldRunGameLoop()) return;
    if (_progressTickerActive) return;
    _progressTickerActive = true;
    const tick = () => {
      if (!_progressTickerActive || !shouldRunGameLoop() || _authLoopAborted) {
        _progressTickerActive = false;
        return;
      }
      updateAllProgressBars();
      if (_hasActiveProgressJobs()) {
        GC.requestFrame(tick);
      } else {
        _progressTickerActive = false;
      }
    };
    GC.requestFrame(tick);
  };

  GC.stopPolling = function stopPolling() {
    console.debug("[GC] polling stopped");
    const p = GC.polling;
    p.running = false;
    if (p.timeoutId) {
      clearTimeout(p.timeoutId);
      p.timeoutId = null;
    }
    p.lastInterval = 0;
    try { if (p.abort) p.abort.abort(); } catch (_) {}
    p.inFlight = false;
    p.abort = null;
  };

  GC.stopStatusPoller = GC.stopPolling;
  GC.shouldRunGameLoop = shouldRunGameLoop;
  GC.shouldRunStatusPolling = shouldRunStatusPolling;
  GC.abortGameLoop = handleAuthFailure;

  GC.startPolling = function startPolling(anyActive, isError = false) {
    if (!shouldRunGameLoop()) {
      console.debug("[GC] polling skipped (auth page)");
      GC.stopPolling();
      return;
    }
    if (_authLoopAborted) {
      console.debug("[GC] polling skipped (auth aborted)");
      return;
    }
    GC.stopPolling();
    const p = GC.polling;
    if (document.hidden) {
      console.debug("[GC] polling paused (hidden tab)");
      return;
    }
    let next = p.intervalIdle;
    if (anyActive) next = p.intervalActive;
    if (p.backoff && isError) next = Math.max(next, p.backoff);

    p.running = true;
    p.lastInterval = next;
    console.debug("[GC] polling started", next, "ms");

    const tick = async () => {
      if (!p.running || !shouldRunGameLoop() || _authLoopAborted) {
        GC.stopPolling();
        return;
      }
      try {
        await GC.refreshGameState("poll");
      } catch (_) {}
      if (!p.running || !shouldRunGameLoop() || _authLoopAborted) {
        GC.stopPolling();
        return;
      }
      GC.startProgressTicker();
      const active = lastHadActiveJob || lastHadActiveResearch;
      let interval = p.intervalIdle;
      if (active) interval = p.intervalActive;
      if (document.hidden) interval = p.intervalHidden;
      p.lastInterval = interval;
      p.timeoutId = GC.setSafeTimeout(tick, interval);
    };
    p.timeoutId = GC.setSafeTimeout(tick, next);
  };

  GC.initPage = function initPage(opts) {
    const page = GC.detectPage();
    const force = opts && opts.force;

    if (GC.pageLifecycle.initialized && GC.currentPage === page && !force) {
      console.debug("[GC] initPage skipped (same page)", page);
      return;
    }

    GC.currentPage = page;
    GC.pageLifecycle.initialized = true;
    console.debug("[GC] initPage", page);

    const mod = GC.modules[page];
    if (typeof mod === "function") {
      try {
        mod();
      } catch (err) {
        console.error("[GC] page module error", page, err);
      }
    } else if (page === "messages" && typeof GC.initMessagesPage === "function") {
      try {
        GC.initMessagesPage();
      } catch (err) {
        console.error("[GC] messages init fallback error", err);
      }
    }

    initFlashAutohide();

    if (shouldRunGameLoop()) {
      hydratePageFromLastState({ skipMessagesUnread: page === "messages" });
    }

    if (!shouldRunGameLoop()) {
      console.debug("[GC] game loop skipped (auth/simple page)");
      GC.abortGameLoop("initPage");
      return;
    }

    _authLoopAborted = false;
    _statusPollErrorLogged = false;

    const afterInit = () => {
      GC.refreshGameState("page_init");
      GC.startProgressTicker();
      if (typeof GC.initChat === "function") GC.initChat();
      if (typeof GC.resumeChatPolling === "function") GC.resumeChatPolling();
    };

    if (page === "messages") {
      const runAfter = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (fn) => queueMicrotask(fn);
      runAfter(afterInit);
    } else {
      afterInit();
    }
  };

  function formatDuration(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
    return `${m}:${String(sec).padStart(2, "0")}`;
  }

  function showNotify(message, category = "info") {
    const text = String(message || "").trim();
    if (!text) return;

    let box = document.getElementById("messages");
    if (!box) {
      box = document.createElement("div");
      box.id = "messages";
      box.className = "gc-flash-container";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      const main = document.getElementById("main-content") || document.body;
      main.prepend(box);
    }

    const item = document.createElement("div");
    item.className = `gc-flash gc-flash-${category}`;
    item.innerHTML =
      `<span class="gc-flash-dot" aria-hidden="true"></span>` +
      `<span class="gc-flash-text">${text.replace(/</g, "&lt;")}</span>`;
    box.appendChild(item);

    GC.setSafeTimeout(() => {
      item.style.transition = "opacity 0.35s ease";
      item.style.opacity = "0";
      GC.setSafeTimeout(() => item.remove(), 400);
    }, 4200);
  }
  GC.showNotify = showNotify;

  function mapActionError(reason, payload) {
    if (reason === "not_enough_resources" && payload) {
      const [m, c] = Array.isArray(payload) ? payload : [payload?.metal, payload?.crystal];
      return tf("msg_upgrade_fail_resources", { metal: m, crystal: c }, "Nicht genug Ressourcen.");
    }
    const map = {
      queue_full: t("msg_build_queue_full", "Bau-Warteschlange voll."),
      research_queue_full: t("research_msg_queue_full", "Forschungs-Warteschlange voll."),
      requirements: t("msg_build_requirements", "Voraussetzungen nicht erfüllt."),
      no_research_lab: t("research_msg_no_lab", "Forschungslabor erforderlich."),
      unknown_tech: t("research_msg_unknown", "Unbekannte Forschung."),
      not_found: t("msg_job_not_found", "Auftrag nicht gefunden."),
      forbidden: t("msg_action_forbidden", "Aktion nicht erlaubt."),
      missing_job_id: t("msg_action_failed", "Aktion fehlgeschlagen. Bitte erneut versuchen."),
    };
    return map[reason] || t("msg_generic_error", "Aktion fehlgeschlagen.");
  }

  function renderBuildingActionCell(b, bqSummary, bqQueueFull) {
    const key = b.key;
    const btnUpgrade = t("buildings_btn_upgrade", "Ausbau starten");
    const btnMax = t("buildings_btn_max_level", "Max. Level");
    const fullLabel = t("research_status_queue_full", "Warteschlange voll");
    const btnQueue = t("research_btn_queue", "Anreihen");
    const queueActive = (bqSummary?.count || 0) > 0;
    const isMax = (b.level >= b.max_level) || b.at_queue_max;

    if (isMax) {
      return `<button class="gc-btn gc-btn-ghost gc-btn-sm btn-upgrade" type="button" disabled title="${btnMax}">${btnMax}</button>`;
    }
    if (!b.requirements_met) {
      return `<button class="gc-btn gc-btn-danger gc-btn-sm btn-upgrade" type="button" disabled>${btnUpgrade}</button>`;
    }
    if (!b.can_afford) {
      return `<button class="gc-btn gc-btn-danger gc-btn-sm btn-upgrade" type="button" disabled>${btnUpgrade}</button>`;
    }
    if (bqQueueFull) {
      return `<span class="status-pill status-pill-locked status-pill-queue-full">${fullLabel}</span>`;
    }
    const label = queueActive ? btnQueue : btnUpgrade;
    const tab = b.tab || _getActiveBuildingTab();
    const href = `/upgrade/${encodeURIComponent(key)}?src=buildings&tab=${encodeURIComponent(tab)}`;
    return `<a id="btn-${key}" data-building="${key}" href="${href}" class="gc-btn gc-btn-primary gc-btn-sm btn-upgrade">${label}</a>`;
  }

  function patchBuildingPanel(rowsByTab, buildQueueRaw) {
    if (!rowsByTab || !document.querySelector(".buildings-table")) return;

    const summary = buildQueueRaw?.summary || null;
    const limit = summary?.limit ?? 3;
    const count = summary?.count ?? 0;
    const bqQueueFull = count >= limit;
    const metalLabel = t("resource_metal", "Ferronit");
    const crystalLabel = t("resource_crystal", "Crytite");
    const levelLabel = t("buildings_col_level", "Level");

    Object.values(rowsByTab).forEach((rows) => {
      (rows || []).forEach((b) => {
        const key = b.key;
        const levelEl = document.getElementById(`level-${key}`);
        if (levelEl) _setIfChanged(levelEl, fmtNumber(b.level));

        const row = document.querySelector(`tr[data-building-row="${key}"]`);
        if (!row) return;

        const costCell = row.querySelector(".bcell-cost");
        if (costCell) {
          let note = `${levelLabel} ${fmtNumber(b.target_level)}`;
          if (b.queue_count) {
            note += ` · ${tf("research_tech_queue_count", { count: b.queue_count }, `In Warteschlange ×${b.queue_count}`)}`;
          }
          const html =
            `<span class="cost-metal">${fmtNumber(b.cost_metal)} ${metalLabel}</span>` +
            `<span class="cost-sep">/</span>` +
            `<span class="cost-crystal">${fmtNumber(b.cost_crystal)} ${crystalLabel}</span>` +
            `<div class="cost-note">${note}</div>`;
          if (costCell.innerHTML !== html) costCell.innerHTML = html;
        }

        const durCell = row.querySelector(".bcell-duration");
        if (durCell) _setIfChanged(durCell, formatDuration(b.time_seconds));

        const actionCell = row.querySelector(".bcell-action");
        if (actionCell) {
          const html = renderBuildingActionCell(b, summary, bqQueueFull);
          if (actionCell.innerHTML.trim() !== html.trim()) actionCell.innerHTML = html;
        }
      });
    });
  }

  function patchResearchPanel(techs, researchRaw) {
    const table = document.querySelector(".research-tech-table");
    if (!table || !Array.isArray(techs)) return;

    const summary = researchRaw?.summary || {};
    const activeKey = researchRaw?.active?.tech_key || researchRaw?.active?.key || null;
    const metalLabel = t("resource_metal", "Ferronit");
    const crystalLabel = t("resource_crystal", "Crytite");

    techs.forEach((tech) => {
      const row = document.querySelector(`tr[data-tech-key="${tech.key}"]`);
      if (!row) return;

      const qCount = tech.queue_count || 0;
      const isActive = !!tech.is_active || (activeKey && activeKey === tech.key);
      const locked = !tech.requirements_met;

      row.classList.toggle("tech-row-locked", locked);
      row.classList.toggle("tech-row-queued", qCount > 0);

      const levelEl = row.querySelector(".tech-level-current");
      if (levelEl) {
        levelEl.textContent = tf("research_tech_level_current", { level: tech.level }, `Aktuell L${tech.level}`);
      }

      const stack = row.querySelector(".tech-level-stack");
      if (stack) {
        let badges = stack.querySelector(".tech-queue-badges");
        if (qCount > 0) {
          const badgesHtml =
            `<div class="tech-queue-badges">` +
            (isActive ? `<span class="tech-queue-badge tech-queue-badge-active">${t("research_btn_active", "Aktiv")}</span>` : "") +
            `<span class="tech-queue-badge">${tf("research_tech_queue_count", { count: qCount }, `In Warteschlange ×${qCount}`)}</span>` +
            `<span class="tech-target-level">${tf("research_tech_target_level", { level: tech.level + qCount }, `Ziel L${tech.level + qCount}`)}</span>` +
            `</div>`;
          if (badges) badges.outerHTML = badgesHtml;
          else stack.insertAdjacentHTML("beforeend", badgesHtml);
        } else if (badges) {
          badges.remove();
        }
      }

      const costCell = row.querySelector(".tech-cost-cell");
      if (costCell) {
        costCell.innerHTML =
          `<div class="tech-meta"><span>${fmtNumber(tech.cost_metal)} ${metalLabel}</span><br>` +
          `<span>${fmtNumber(tech.cost_crystal)} ${crystalLabel}</span></div>`;
      }

      const timeCell = row.querySelector(".tech-time-cell");
      if (timeCell) {
        const inner = timeCell.querySelector(".tech-time") || timeCell;
        _setIfChanged(inner, formatDuration(tech.time_seconds));
      }
    });

    const labEl = document.querySelector(".lab-level-highlight");
    if (labEl && typeof researchRaw?.lab_level !== "undefined") {
      _setIfChanged(labEl, fmtNumber(researchRaw.lab_level));
    }

    updateResearchQueueActions(researchRaw);
  }

  function requestFinishRefresh(type) {
    if (!shouldRunGameLoop() || _authLoopAborted) return;
    if (GC.finishLocks[type]) return;
    GC.finishLocks[type] = true;
    Promise.resolve(GC.refreshGameState ? GC.refreshGameState(`${type}_finished`) : null).finally(() => {
      GC.finishLocks[type] = false;
    });
  }

  function patchOverviewTable(overview, buildings, prod) {
    const table = document.querySelector(".overview-table tbody");
    if (!table) return;

    const rows = overview?.rows;
    if (Array.isArray(rows) && rows.length > 0) {
      const trs = table.querySelectorAll("tr");
      rows.forEach((row, idx) => {
        const tr = trs[idx];
        if (!tr) return;
        const cells = tr.querySelectorAll("td");
        if (cells[1]) _setIfChanged(cells[1], fmtNumber(row.level || 0));
        if (cells[2]) {
          const ph = Math.floor(Number(row.production_per_hour || 0));
          _setIfChanged(cells[2], ph > 0 ? `+${fmtNumber(ph)} / h` : "–");
        }
      });
      return;
    }

    const keys = ["metal_mine", "crystal_mine", "solar_plant"];
    const trs = table.querySelectorAll("tr");
    keys.forEach((key, idx) => {
      const tr = trs[idx];
      if (!tr) return;
      const cells = tr.querySelectorAll("td");
      const lvl = buildings?.[key];
      if (cells[1] && typeof lvl !== "undefined") _setIfChanged(cells[1], fmtNumber(lvl));
      if (cells[2]) {
        const ph = Math.floor(Number(prod?.[key] || 0));
        _setIfChanged(cells[2], ph > 0 ? `+${fmtNumber(ph)} / h` : "–");
      }
    });
  }

  function patchOverviewEnergyHint(overview, data) {
    const hint = document.querySelector(".overview-hint");
    if (!hint) return;

    const hintKey = overview?.energy_hint;
    const total = Math.floor(
      Number(data?.energy?.total ?? data?.player?.energy_total ?? data?.resources?.energy_total ?? 0)
    );
    const ratio = Number(data?.energy?.ratio ?? data?.energy_ratio ?? 1);

    let state = hintKey;
    if (!state) {
      if (total <= 0) state = "zero";
      else if (ratio >= 1) state = "ok";
      else state = "low";
    }

    hint.classList.remove("overview-energy-zero", "overview-energy-ok", "overview-energy-low");
    if (state === "zero") hint.classList.add("overview-energy-zero");
    else if (state === "ok") hint.classList.add("overview-energy-ok");
    else hint.classList.add("overview-energy-low");
  }

  function patchOverviewResearch(research) {
    const box = document.getElementById("overview-research-active");
    const emptyHint = document.querySelector(".research-empty-hint");
    const active = research?.active || null;

    if (!box && !emptyHint) return;

    if (!active) {
      if (box) box.style.display = "none";
      if (emptyHint) emptyHint.style.display = "";
      return;
    }

    if (box) box.style.display = "";
    if (emptyHint) emptyHint.style.display = "none";

    const nameEl = document.getElementById("overview-research-active-name");
    if (nameEl) {
      const label = active.label || active.tech_key || active.key || "Forschung";
      const cur = active.current_level ?? active.level ?? 0;
      const targ = active.target_level ?? (cur + 1);
      nameEl.textContent = `${label} (L${cur} → L${targ})`;
    }
  }

  // =========================
  // Number animation (anti-spam)
  // =========================
  const _numAnim = new Map();      // el -> state
  const _lastNum = new WeakMap();  // el -> lastTarget

  function animateNumber(el, target, opts = {}) {
    if (!el) return;

    const tgt = Math.max(0, Math.floor(Number(target || 0)));
    const last = _lastNum.get(el);
    if (last === tgt) return;
    _lastNum.set(el, tgt);

    const { duration = 650, minStep = 1, fmt = fmtNumber } = opts;
    const now = performance.now();

    const currentText = (el.textContent || "").replace(/\./g, "").replace(/,/g, "");
    let cur = Number(currentText);
    if (!Number.isFinite(cur)) cur = 0;
    cur = Math.max(0, Math.floor(cur));

    const st = _numAnim.get(el);
    if (st && st.target === tgt) return;

    if (Math.abs(tgt - cur) <= minStep) {
      el.textContent = fmt(tgt);
      _numAnim.delete(el);
      return;
    }

    const startVal = st ? st.value : cur;
    const state = {
      raf: 0,
      start: startVal,
      value: startVal,
      target: tgt,
      t0: now,
      dur: Math.max(120, duration),
    };

    if (st && st.raf) cancelAnimationFrame(st.raf);

    function tick(t) {
      const p = Math.min(1, (t - state.t0) / state.dur);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      const v = Math.round(state.start + (state.target - state.start) * eased);

      state.value = v;
      el.textContent = fmt(v);

      if (p < 1) {
        state.raf = GC.requestFrame(tick);
        _numAnim.set(el, state);
      } else {
        el.textContent = fmt(state.target);
        _numAnim.delete(el);
      }
    }

    state.raf = GC.requestFrame(tick);
    _numAnim.set(el, state);
  }

  // =========================
  // Score delta pop + pulse
  // =========================
  const _scoreState = {
    lastServerTotal: null,
    lastAnimatedTotal: null,
  };

  let _deltaTimerHud = 0;
  let _deltaTimerOv = 0;

  function pulseScore(anchorEl) {
    if (!anchorEl) return;
    anchorEl.classList.remove("gc-score-pulse");
    void anchorEl.offsetWidth;
    anchorEl.classList.add("gc-score-pulse");
  }

  function ensureDeltaEl(anchorEl) {
    if (!anchorEl) return null;

    const style = getComputedStyle(anchorEl);
    if (style.position === "static") anchorEl.style.position = "relative";

    let delta = anchorEl.querySelector(".gc-score-delta");
    if (!delta) {
      delta = document.createElement("span");
      delta.className = "gc-score-delta";
      delta.setAttribute("aria-hidden", "true");
      delta.textContent = "";
      anchorEl.appendChild(delta);
    }
    return delta;
  }

  function showScoreDelta(anchorEl, deltaValue, which = "hud") {
    if (!anchorEl) return;
    const d = Math.floor(Number(deltaValue || 0));
    if (!Number.isFinite(d) || d === 0) return;

    const deltaEl = ensureDeltaEl(anchorEl);
    if (!deltaEl) return;

    const sign = d > 0 ? "+" : "";
    deltaEl.textContent = `${sign}${fmtNumber(d)}`;

    deltaEl.classList.remove("show");
    void deltaEl.offsetWidth;
    deltaEl.classList.add("show");

    pulseScore(anchorEl);

    if (which === "overview") {
      if (_deltaTimerOv) clearTimeout(_deltaTimerOv);
      _deltaTimerOv = GC.setSafeTimeout(() => deltaEl.classList.remove("show"), 1200);
    } else {
      if (_deltaTimerHud) clearTimeout(_deltaTimerHud);
      _deltaTimerHud = GC.setSafeTimeout(() => deltaEl.classList.remove("show"), 1200);
    }
  }

  // =========================
  // Mapping: Buildings -> DOM-IDs
  // =========================
  const BUILDINGS = {
    metal_mine: { levelId: "level-metal_mine", statusId: "status-metal_mine", btnId: "btn-metal_mine" },
    crystal_mine: { levelId: "level-crystal_mine", statusId: "status-crystal_mine", btnId: "btn-crystal_mine" },
    solar_plant: { levelId: "level-solar_plant", statusId: "status-solar_plant", btnId: "btn-solar_plant" },
    research_lab: { levelId: "level-research_lab", statusId: "status-research_lab", btnId: "btn-research_lab" },
    academy: { levelId: "level-academy", statusId: "status-academy", btnId: "btn-academy" },
    metal_storage: { levelId: "level-metal_storage", statusId: "status-metal_storage", btnId: "btn-metal_storage" },
    crystal_storage: { levelId: "level-crystal_storage", statusId: "status-crystal_storage", btnId: "btn-crystal_storage" },
    command_center: { levelId: "level-command_center", statusId: "status-command_center", btnId: "btn-command_center" },
    shipyard: { levelId: "level-shipyard", statusId: "status-shipyard", btnId: "btn-shipyard" },
    defense_factory: { levelId: "level-defense_factory", statusId: "status-defense_factory", btnId: "btn-defense_factory" },
    barracks: { levelId: "level-barracks", statusId: "status-barracks", btnId: "btn-barracks" },
    radar_array: { levelId: "level-radar_array", statusId: "status-radar_array", btnId: "btn-radar_array" },
    shield_generator: { levelId: "level-shield_generator", statusId: "status-shield_generator", btnId: "btn-shield_generator" },
    terraformer: { levelId: "level-terraformer", statusId: "status-terraformer", btnId: "btn-terraformer" },
    nanofactory: { levelId: "level-nanofactory", statusId: "status-nanofactory", btnId: "btn-nanofactory" },
    geothermal_nexus: { levelId: "level-geothermal_nexus", statusId: "status-geothermal_nexus", btnId: "btn-geothermal_nexus" },
    planet_core_nexus: { levelId: "level-planet_core_nexus", statusId: "status-planet_core_nexus", btnId: "btn-planet_core_nexus" },
  };

  const BUILDING_LABELS = {
    metal_mine: "Ferronit-Mine",
    crystal_mine: "Crytite-Extraktor",
    solar_plant: "Solarkollektor-Feld",
    research_lab: "Forschungslabor",
    academy: "Genesis-Akademie",
    metal_storage: "Ferronit-Depot",
    crystal_storage: "Crytite-Silo",
    command_center: "Kommandozentrale",
    shipyard: "Werft",
    defense_factory: "Verteidigungsfabrik",
    barracks: "Orbital-Kaserne",
    radar_array: "Deep-Space-Radar-Array",
    shield_generator: "Aegis-Schildprojektor",
    terraformer: "Terraformer",
    nanofactory: "Nano-Assemblierungsanlage",
    geothermal_nexus: "Geothermie-Nexus",
    planet_core_nexus: "Planetenkern-Nexus",
  };

  // =========================
  // Build Queue live state
  // =========================
  const BUILDQ = {
    active: {
      finishTime: 0,
      totalSeconds: 0,
    },
  };

  const RESEARCHQ = {
    active: {
      finishTime: 0,
      totalSeconds: 0,
    },
  };

  function _hasActiveProgressJobs() {
    return (
      BUILDQ.active.finishTime > 0 ||
      RESEARCHQ.active.finishTime > 0 ||
      !!document.querySelector(".build-job.build-job-active") ||
      !!document.querySelector(".research-job.research-job-active") ||
      !!document.getElementById("overview-research-active")
    );
  }

  // progress ticker: GC.startProgressTicker / GC.stopProgressTicker

  // =========================
  // Build-Queue panel render
  // - minimal re-render via signature
  // - BUT live progress runs independently
  // =========================
  let _lastQueueSignature = "";

  function _queueSignature(queueList, summary) {
    try {
      const count = summary?.count ?? (queueList?.length ?? 0);
      const items = (queueList || [])
        .map((j) => `${j.id || j.building_type}:${j.target_level}:${j.finish_time || 0}`)
        .join("|");
      return `${count}|${items}`;
    } catch (_) {
      return "";
    }
  }

  function _updateBuildQueueSubtitle(count, limit, firstEta) {
    const subEl = document.getElementById("build-queue-subtitle");
    if (!subEl) return;

    if (!count) {
      _setIfChanged(subEl, t("build_queue_hint_fallback", "Verwalte laufende Bauaufträge und starte Upgrades."));
      return;
    }

    const jobsLabel = t("build_queue_jobs", "Aufträge");
    const nextLabel = t("build_queue_next", "Nächste Fertigstellung in");
    const lim = limit || 3;
    const html = `${count}/${lim} ${jobsLabel} · ${nextLabel}: <span id="build-queue-subtitle-eta">${firstEta}</span>`;
    if (subEl.innerHTML !== html) subEl.innerHTML = html;
  }

  function _getActiveBuildingTab() {
    const active = document.querySelector(".building-tabs .tab-btn.active");
    return active?.dataset?.tab || "resources";
  }

  function updateResearchQueueActions(researchRaw) {
    const table = document.querySelector(".research-tech-table");
    if (!table) return;

    const summary = researchRaw?.summary || null;
    const count = summary?.count ?? (Array.isArray(researchRaw?.queue) ? researchRaw.queue.length : 0);
    const limit = summary?.limit ?? 3;
    const queueFull = count >= limit;
    const fullLabel = t("research_status_queue_full", "Warteschlange voll");
    const queueActive = count > 0;
    const btnStart = t("research_btn_start", "Forschung starten");
    const btnQueue = t("research_btn_queue", "Anreihen");

    table.querySelectorAll(".tech-status-cell[data-tech-key]").forEach((cell) => {
      const pillLocked = cell.querySelector(".status-pill-locked:not(.status-pill-queue-full)");
      if (pillLocked) return;

      const link = cell.querySelector("a.btn-research");
      const pillFull = cell.querySelector(".status-pill-queue-full");

      if (queueFull) {
        if (!pillFull) {
          cell.innerHTML = `<span class="status-pill status-pill-locked status-pill-queue-full">${fullLabel}</span>`;
        }
        return;
      }

      if (pillFull) {
        const techKey = cell.dataset.techKey;
        const href = `/research_start/${encodeURIComponent(techKey)}`;
        const label = queueActive ? btnQueue : btnStart;
        cell.innerHTML =
          `<a href="${href}" class="gc-btn gc-btn-primary gc-btn-sm btn-research">${label}</a>`;
        return;
      }

      if (link) {
        const label = queueActive ? btnQueue : btnStart;
        if (link.textContent !== label) link.textContent = label;
      }
    });
  }

  function updateBuildQueueActions(buildQueueRaw) {
    if (!document.querySelector(".buildings-table")) return;

    const summary = buildQueueRaw?.summary || null;
    const count = summary?.count ?? (Array.isArray(buildQueueRaw?.queue) ? buildQueueRaw.queue.length : 0);
    const limit = summary?.limit ?? 3;
    const queueFull = count >= limit;
    const fullLabel = t("research_status_queue_full", "Warteschlange voll");
    const queueActive = count > 0;
    const btnLabel = queueActive
      ? t("research_btn_queue", "Anreihen")
      : t("buildings_btn_upgrade", "Ausbau starten");
    const tab = _getActiveBuildingTab();

    document.querySelectorAll(".buildings-table .bcell-action[data-building]").forEach((cell) => {
      if (cell.querySelector("button.btn-upgrade[disabled]")) return;

      const bType = cell.dataset.building;
      if (!bType) return;

      const link = cell.querySelector("a.btn-upgrade");
      const pill = cell.querySelector(".status-pill-queue-full");

      if (queueFull) {
        if (cell.querySelector("button.btn-upgrade[disabled]")) return;
        if (!cell.querySelector(".status-pill-queue-full")) {
          cell.innerHTML = `<span class="status-pill status-pill-locked status-pill-queue-full">${fullLabel}</span>`;
        }
        return;
      }

      if (pill) {
        const href = `/upgrade/${encodeURIComponent(bType)}?src=buildings&tab=${encodeURIComponent(tab)}`;
        cell.innerHTML =
          `<a id="btn-${bType}" data-building="${bType}" href="${href}"` +
          ` class="gc-btn gc-btn-primary gc-btn-sm btn-upgrade">${btnLabel}</a>`;
        return;
      }

      if (link && link.textContent !== btnLabel) {
        link.textContent = btnLabel;
      }
    });
  }

  function renderBuildQueue(buildQueueRaw) {
    const root = document.getElementById("build-queue-root");
    if (!root) return;

    let queueList = [];
    let summary = null;

    if (!buildQueueRaw) {
      queueList = [];
    } else if (Array.isArray(buildQueueRaw)) {
      queueList = buildQueueRaw;
    } else if (Array.isArray(buildQueueRaw.queue)) {
      queueList = buildQueueRaw.queue;
      summary = buildQueueRaw.summary || null;
    }

    // update live state regardless of DOM churn
    const first = queueList && queueList.length ? queueList[0] : null;
    if (first && first.finish_time) {
      const now = getApproxServerNow();
      const remaining = Math.max(0, Math.floor((Number(first.finish_time) - (now || 0))));
      const totalRaw = Number(first.total || first.total_seconds || 0);
      const total = totalRaw > 0 ? Math.floor(totalRaw) : Math.max(1, remaining + 1);

      BUILDQ.active.finishTime = Number(first.finish_time) || 0;
      BUILDQ.active.totalSeconds = total;
    } else {
      BUILDQ.active.finishTime = 0;
      BUILDQ.active.totalSeconds = 0;
    }

    const sig = _queueSignature(queueList, summary);
    const count = summary?.count ?? queueList.length;
    const limit = summary?.limit ?? 3;
    const firstEta =
      typeof summary?.first_finish_in !== "undefined"
        ? formatEta(summary.first_finish_in)
        : formatEta(first?.remaining ?? 0);

    if (sig === _lastQueueSignature) {
      _updateBuildQueueSubtitle(count, limit, firstEta);
      GC.startProgressTicker();
      return;
    }
    _lastQueueSignature = sig;

    if (!queueList || queueList.length === 0) {
      _updateBuildQueueSubtitle(0, limit, firstEta);
      const none =
        t("build_queue_none", null) ||
        t("build_queue_empty", null) ||
        t("build_queue_no_active", null) ||
        "Keine Bauaufträge aktiv.";
      root.innerHTML = `<div class="build-queue-empty">${none}</div>`;
      return;
    }

    _updateBuildQueueSubtitle(count, limit, firstEta);

    let html = `<div class="build-queue-list">`;

    queueList.forEach((job, index) => {
      const bType = job.building_type;
      const i18nKey = "building_" + bType;
      const fallbackName = bType || i18nKey;

      const name =
        BUILDING_LABELS[bType] ||
        (job.label_key ? t(job.label_key, fallbackName) : t(i18nKey, fallbackName));

      const remaining = parseInt(job.remaining, 10) || 0;
      const totalRaw = job.total || job.total_seconds || 0;
      const total = Math.max(1, parseInt(totalRaw, 10) || (remaining + 1));
      const pct = Math.max(0, Math.min(100, 100 * (1 - remaining / total)));
      const iconSrc = `/static/img/buildings/${bType}.png`;
      const isActive = index === 0;
      const finishTime = Number(job.finish_time || 0);

      html += `
        <div class="build-job${isActive ? " build-job-active" : " build-job-queued"}"
             ${isActive ? `data-finish-time="${finishTime}" data-total="${total}"` : ""}>
          <div class="build-job-icon">
            <img src="${iconSrc}" alt="" loading="lazy" onerror="this.src='/static/img/buildings/default.png'">
          </div>
          <div class="build-job-body">
            <div class="job-header">
              <span class="job-name">${name} → ${t("label_level_short", "L")} ${job.target_level}</span>
              <span class="job-time${isActive ? "" : " job-time-muted"}"${isActive ? ' id="build-eta-live"' : ""}>
                ${isActive ? formatEta(remaining) : t("status_in_queue", "In Warteschlange")}
              </span>
            </div>
            <div class="build-bar build-bar-large">
              <div class="build-bar-fill gc-progress-smooth"${isActive ? ' id="build-bar-fill-live"' : ""}
                   style="width:${isActive ? pct : 0}%"
                   role="progressbar" aria-valuenow="${isActive ? pct : 0}" aria-valuemin="0" aria-valuemax="100"></div>
            </div>
            <div class="job-actions">
              <button type="button" class="gc-btn gc-btn-ghost gc-btn-xs" data-build-cancel-id="${job.id}">
                ${t("action_cancel", "Abbrechen")}
              </button>
            </div>
            ${isActive ? `<span class="job-badge-active">${t("buildings_btn_active", "Aktiv")}</span>` : `<span class="job-badge-queued">#${index + 1}</span>`}
          </div>
        </div>`;
    });

    html += `</div>`;
    root.innerHTML = html;
    GC.startProgressTicker();
  }

  // =========================
  // Research Queue panel render
  // =========================
  let _lastResearchQueueSignature = "";

  function _researchQueueSignature(queueList, summary) {
    try {
      const count = summary?.count ?? (queueList?.length ?? 0);
      const items = (queueList || [])
        .map((j) => `${j.id || j.tech_key}:${j.target_level}:${j.finish_at || j.finish_time || 0}`)
        .join("|");
      return `${count}|${items}`;
    } catch (_) {
      return "";
    }
  }

  function _updateResearchQueueSubtitle(count, limit, firstEta) {
    const subEl = document.getElementById("research-queue-subtitle");
    if (!subEl) return;

    if (!count) {
      _setIfChanged(
        subEl,
        t("research_queue_hint_fallback", "Starte Forschungen — bis zu 3 können angereiht werden.")
      );
      return;
    }

    const jobsLabel = t("research_queue_jobs", "Aufträge");
    const nextLabel = t("build_queue_next", "Nächste Fertigstellung in");
    const lim = limit || 3;
    const html = `${count}/${lim} ${jobsLabel} · ${nextLabel}: <span id="research-queue-subtitle-eta">${firstEta}</span>`;
    if (subEl.innerHTML !== html) subEl.innerHTML = html;
  }

  function renderResearchQueue(researchRaw) {
    const root = document.getElementById("research-queue-root");
    if (!root) return;

    let queueList = [];
    let summary = null;

    if (!researchRaw) {
      queueList = [];
    } else if (Array.isArray(researchRaw.queue)) {
      queueList = researchRaw.queue;
      summary = researchRaw.summary || null;
    } else if (researchRaw.active) {
      queueList = [researchRaw.active];
      summary = { count: 1, limit: 3, first_finish_in: researchRaw.active.remaining || 0 };
    }

    const first = queueList.length ? queueList[0] : null;
    if (first && (first.finish_at || first.finish_time)) {
      const finishTime = Number(first.finish_at || first.finish_time || 0);
      const totalRaw = Number(first.total || first.total_seconds || 0);
      const now = getApproxServerNow();
      const remaining = Math.max(0, Math.floor(finishTime - (now || 0)));
      const total = totalRaw > 0 ? Math.floor(totalRaw) : Math.max(1, remaining + 1);

      RESEARCHQ.active.finishTime = finishTime;
      RESEARCHQ.active.totalSeconds = total;
    } else {
      RESEARCHQ.active.finishTime = 0;
      RESEARCHQ.active.totalSeconds = 0;
    }

    const sig = _researchQueueSignature(queueList, summary);
    const count = summary?.count ?? queueList.length;
    const limit = summary?.limit ?? 3;
    const firstEta =
      typeof summary?.first_finish_in !== "undefined"
        ? formatEta(summary.first_finish_in)
        : formatEta(first?.remaining ?? 0);

    if (sig === _lastResearchQueueSignature) {
      _updateResearchQueueSubtitle(count, limit, firstEta);
      GC.startProgressTicker();
      return;
    }
    _lastResearchQueueSignature = sig;

    if (!queueList.length) {
      _updateResearchQueueSubtitle(0, limit, firstEta);
      const none =
        t("research_queue_none", null) ||
        t("research_active_none", null) ||
        "Keine Forschungsaufträge in der Warteschlange.";
      root.innerHTML = `<div class="research-queue-empty">${none}</div>`;
      if (!_hasActiveProgressJobs()) GC.stopProgressTicker();
      return;
    }

    _updateResearchQueueSubtitle(count, limit, firstEta);

    let html = `<div class="research-queue-list">`;

    queueList.forEach((job, index) => {
      const techKey = job.tech_key || job.key;
      const i18nKey = job.label_key || techKey;
      const fallbackName = job.label || techKey || i18nKey;
      const name = t(i18nKey, fallbackName);

      const remaining = parseInt(job.remaining, 10) || 0;
      const totalRaw = job.total || job.total_seconds || 0;
      const total = Math.max(1, parseInt(totalRaw, 10) || remaining + 1);
      const pct = Math.max(0, Math.min(100, 100 * (1 - remaining / total)));
      const iconFile = job.icon || `${techKey}.png`;
      const iconSrc = `/static/img/research/${iconFile}`;
      const isActive = index === 0;
      const finishTime = Number(job.finish_at || job.finish_time || 0);
      const currLvl = job.current_level ?? 0;
      const targLvl = job.target_level ?? currLvl + 1;

      html += `
        <div class="research-job${isActive ? " research-job-active" : " research-job-queued"}"
             ${isActive ? `data-finish-time="${finishTime}" data-total="${total}"` : ""}>
          <div class="research-job-icon">
            <img src="${iconSrc}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
          </div>
          <div class="research-job-body">
            <div class="job-header">
              <span class="job-name">${name} → ${t("label_level_short", "L")}${currLvl} → ${t("label_level_short", "L")}${targLvl}</span>
              <span class="job-time${isActive ? "" : " job-time-muted"}"${isActive ? ' id="research-eta-live"' : ""}>
                ${isActive ? formatEta(remaining) : t("status_in_queue", "In Warteschlange")}
              </span>
            </div>
            <div class="research-bar research-bar-large">
              <div class="research-bar-fill gc-progress-smooth"${isActive ? ' id="research-bar-fill-live"' : ""}
                   style="width:${isActive ? pct : 0}%"
                   role="progressbar" aria-valuenow="${isActive ? pct : 0}" aria-valuemin="0" aria-valuemax="100"></div>
            </div>
            <div class="job-actions">
              <button type="button" class="gc-btn gc-btn-ghost gc-btn-xs" data-research-cancel-id="${job.id}">
                ${t("action_cancel", "Abbrechen")}
              </button>
            </div>
            ${isActive ? `<span class="job-badge-active">${t("research_btn_active", "Aktiv")}</span>` : `<span class="job-badge-queued">#${index + 1}</span>`}
          </div>
        </div>`;
    });

    html += `</div>`;
    root.innerHTML = html;
    GC.startProgressTicker();
  }

  function _applyProgressFill(fillEl, pct) {
    if (!fillEl) return;
    const clamped = Math.max(0, Math.min(100, pct));
    fillEl.style.width = `${clamped}%`;
    fillEl.setAttribute("aria-valuenow", String(Math.round(clamped)));
  }

  function updateAllProgressBars() {
    const serverNow = getApproxServerNow();
    if (!serverNow) return;

    const path = window.location.pathname || "";
    const isResearchPage = path.endsWith("/research");
    const isOverviewPage = path.endsWith("/overview") || path === "/" || path === "";

    const buildActive = document.querySelector(".build-job.build-job-active");
    const buildFinishFromDom = buildActive ? Number(buildActive.getAttribute("data-finish-time") || 0) : 0;
    const buildTotalFromDom = buildActive ? Math.max(1, Number(buildActive.getAttribute("data-total") || 1)) : 1;
    const buildFinishFromState = Number(BUILDQ.active.finishTime || 0);
    const buildTotalFromState = Math.max(1, Number(BUILDQ.active.totalSeconds || 1));
    const buildFinish = buildFinishFromDom || buildFinishFromState;
    const buildTotal = buildFinishFromDom ? buildTotalFromDom : buildTotalFromState;
    if (buildFinish) {
      const remaining = Math.max(0, buildFinish - serverNow);
      const pct = 100 * (1 - remaining / buildTotal);
      const etaEl = document.getElementById("build-eta-live");
      const fillEl = document.getElementById("build-bar-fill-live");
      if (etaEl) _setIfChanged(etaEl, formatEta(Math.ceil(remaining)));
      _applyProgressFill(fillEl, pct);
      const subEta = document.getElementById("build-queue-subtitle-eta");
      if (subEta) _setIfChanged(subEta, formatEta(Math.ceil(remaining)));
      if (remaining <= 0) {
        _applyProgressFill(fillEl, 100);
        requestFinishRefresh("buildings");
      }
    }

    const researchActive = document.querySelector(".research-job.research-job-active");
    if (researchActive) {
      const finishTime = Number(researchActive.getAttribute("data-finish-time") || 0);
      const total = Math.max(1, Number(researchActive.getAttribute("data-total") || 1));
      if (finishTime) {
        const remaining = Math.max(0, finishTime - serverNow);
        const pct = 100 * (1 - remaining / total);
        const etaEl = document.getElementById("research-eta-live");
        const fillEl = document.getElementById("research-bar-fill-live");
        if (etaEl) _setIfChanged(etaEl, formatEta(Math.ceil(remaining)));
        _applyProgressFill(fillEl, pct);
        const subEta = document.getElementById("research-queue-subtitle-eta");
        if (subEta) _setIfChanged(subEta, formatEta(Math.ceil(remaining)));
        if (remaining <= 0) {
          _applyProgressFill(fillEl, 100);
          requestFinishRefresh("research");
        }
      }
    }

    const ovBox = document.getElementById("overview-research-active");
    if (ovBox) {
      const finishAt = Number(ovBox.dataset.finishAt || 0);
      const total = Math.max(1, Number(ovBox.dataset.total || 1));
      if (finishAt) {
        const remaining = Math.max(0, finishAt - serverNow);
        const pct = 100 * (1 - remaining / total);
        const cdEl = document.getElementById("research-remaining");
        const barEl = document.getElementById("research-bar-fill");
        if (cdEl) _setIfChanged(cdEl, formatEta(Math.ceil(remaining)));
        _applyProgressFill(barEl, pct);
        if (remaining <= 0) {
          _applyProgressFill(barEl, 100);
          requestFinishRefresh("research");
        }
      }
    }
  }

  function updateBuildQueueLive() {
    updateAllProgressBars();
  }

  // =========================
  // Polling state (singleton via GC.polling)
  // =========================

  let lastHadActiveJob = false;
  let lastHadActiveResearch = false;
  let lastBuildQueueCount = null;
  let lastBuildQueueFull = null;
  let lastResearchQueueCount = null;
  let lastResearchQueueFull = null;

  // Keep last values to avoid DOM churn
  const _last = {
    metal: null,
    crystal: null,
    energyUsed: null,
    energyTotal: null,
    storageMetal: null,
    storageCrystal: null,
  };

  // =========================
  // Messages unread badges (game-state polling)
  // =========================
  let _lastMessagesUnreadPoll = null;

  function updateMessagesUnreadBadges(count) {
    const n = Math.max(0, Number(count) || 0);
    const label = n > 99 ? "99+" : String(n);
    document.querySelectorAll("[data-messages-unread-badge]").forEach((el) => {
      if (n > 0) {
        el.textContent = label;
        el.hidden = false;
        el.classList.remove("hidden");
        el.setAttribute("aria-hidden", "false");
      } else {
        el.textContent = "";
        el.hidden = true;
        el.classList.add("hidden");
        el.setAttribute("aria-hidden", "true");
      }
    });
  }
  GC.updateMessagesUnreadBadges = updateMessagesUnreadBadges;
  GC.setMessagesUnreadPollBaseline = function setMessagesUnreadPollBaseline(count) {
    _lastMessagesUnreadPoll = Math.max(0, Number(count) || 0);
  };

  // =========================
  // Status polling / GC.refreshGameState
  // =========================
  function applyGameStateData(data, _reason, opts) {
      if (!data || data.ok === false) return false;
      const skipMessagesUnread = Boolean(opts && opts.skipMessagesUnread);

      if (data.server_time) setServerTime(data.server_time);

      const p = data.player || {};
      const energy = data.energy || {};
      const resources = data.resources || {};
      const buildings = data.buildings || {};
      const buildQueueRaw = data.build_queue || null;
      const prod = data.production_per_hour || {};
      const research = data.research || {};
      const activeResearch = research.active || null;
      const storage = data.storage || {};

      const storageMetal = Math.floor(Number(storage.metal || 0));
      const storageCrystal = Math.floor(Number(storage.crystal || 0));

      const metal = Math.floor(Number(p.metal ?? resources.metal ?? 0));
      const crystal = Math.floor(Number(p.crystal ?? resources.crystal ?? 0));
      const used = Math.floor(Number(p.energy_used ?? energy.used ?? resources.energy_used ?? 0));
      const total = Math.floor(Number(p.energy_total ?? energy.total ?? resources.energy_total ?? 0));

      // --- Top-Bar Ressourcen (alle sichtbaren Instanzen aktualisieren) ---
      const metalValEls = document.querySelectorAll(".res-value.metal");
      const metalCapEls = document.querySelectorAll(".res-cap.metal");
      const cryValEls = document.querySelectorAll(".res-value.crystal");
      const cryCapEls = document.querySelectorAll(".res-cap.crystal");

      if (_last.metal !== metal) {
        metalValEls.forEach((el) => { el.textContent = fmtNumber(metal); });
        _last.metal = metal;
      }
      if (_last.crystal !== crystal) {
        cryValEls.forEach((el) => { el.textContent = fmtNumber(crystal); });
        _last.crystal = crystal;
      }

      if (_last.storageMetal !== storageMetal && storageMetal > 0) {
        metalCapEls.forEach((el) => { el.textContent = fmtNumber(storageMetal); });
        _last.storageMetal = storageMetal;
      }
      if (_last.storageCrystal !== storageCrystal && storageCrystal > 0) {
        cryCapEls.forEach((el) => { el.textContent = fmtNumber(storageCrystal); });
        _last.storageCrystal = storageCrystal;
      }

      const energyText = `${fmtNumber(used)}/${fmtNumber(total)}`;
      if (_last.energyUsed !== used || _last.energyTotal !== total) {
        setText("res-energy", energyText);
        document.querySelectorAll("[data-energy-used]").forEach((el) => {
          _setIfChanged(el, fmtNumber(used));
        });
        document.querySelectorAll("[data-energy-total]").forEach((el) => {
          _setIfChanged(el, fmtNumber(total));
        });
        _last.energyUsed = used;
        _last.energyTotal = total;
      }

      // === SCORE / RANK ===
      if (data.score) {
        const s = data.score;

        const serverTotal = Number(s.total || 0);
        const rank = typeof s.rank === "number" ? s.rank : Number(s.rank || 0);
        const totalPlayers = Number(s.total_players || 0);

        const scoreBuildings = Number(s.buildings || 0);
        const scoreResearch = Number(s.research || 0);

        let delta = 0;
        if (_scoreState.lastServerTotal !== null && serverTotal > _scoreState.lastServerTotal) {
          delta = serverTotal - _scoreState.lastServerTotal;
        }
        _scoreState.lastServerTotal = serverTotal;

        // HUD
        const hudScoreEl = document.getElementById("hud-score-total");
        const hudRankEl = document.getElementById("hud-score-rank");

        if (hudScoreEl && _scoreState.lastAnimatedTotal !== serverTotal) {
          animateNumber(hudScoreEl, serverTotal, { duration: 700 });
          if (delta !== 0) showScoreDelta(hudScoreEl.closest(".gc-score-pill") || hudScoreEl, delta, "hud");
          _scoreState.lastAnimatedTotal = serverTotal;
        }

        const rankText = (rank >= 1 && totalPlayers > 0) ? `#${rank}/${totalPlayers}` : "#–";
        if (hudRankEl) hudRankEl.textContent = rankText;

        // Overview
        const ovScoreVal = document.getElementById("overview-score-value");
        const ovScoreRank = document.getElementById("overview-score-rank");
        const ovScoreBuild = document.getElementById("overview-score-buildings");
        const ovScoreRes = document.getElementById("overview-score-research");

        if (ovScoreVal) {
          animateNumber(ovScoreVal, serverTotal, { duration: 750 });
          if (delta !== 0) showScoreDelta(ovScoreVal.parentElement || ovScoreVal, delta, "overview");
        }

        if (ovScoreRank) {
          ovScoreRank.textContent = (rank >= 1 && totalPlayers > 0) ? `#${rank}/${totalPlayers}` : "#–/–";
        }

        if (ovScoreBuild) animateNumber(ovScoreBuild, scoreBuildings, { duration: 650 });
        if (ovScoreRes) animateNumber(ovScoreRes, scoreResearch, { duration: 650 });
      }

      if (typeof data.unread_messages_count === "number") {
        const onMessagesPage = GC.detectPage() === "messages";
        const inboxSynced =
          onMessagesPage &&
          GC.messagesPageState &&
          GC.messagesPageState.unreadSyncedFromApi;
        const prevUnread = _lastMessagesUnreadPoll;
        const unreadIncreased =
          prevUnread !== null && data.unread_messages_count > prevUnread;
        if (!skipMessagesUnread && (!inboxSynced || unreadIncreased)) {
          _lastMessagesUnreadPoll = data.unread_messages_count;
          updateMessagesUnreadBadges(data.unread_messages_count);

          if (unreadIncreased && !onMessagesPage) {
            const msg =
              data.unread_messages_count === 1
                ? t("messages.notify_new", "Neue Nachricht im Posteingang.")
                : t("messages.notify_new_count", "Du hast %(count)s ungelesene Nachrichten.")
                    .replace("%(count)s", String(data.unread_messages_count))
                    .replace("{count}", String(data.unread_messages_count));
            showNotify(msg, "info");
          }

          if (
            onMessagesPage &&
            GC.messagesPageState &&
            typeof GC.messagesPageState.loadList === "function"
          ) {
            const emptyInboxNeedsFill =
              data.unread_messages_count > 0 &&
              (!Array.isArray(GC.messagesPageState.messages) ||
                GC.messagesPageState.messages.length === 0);
            if (unreadIncreased || (prevUnread === null && emptyInboxNeedsFill)) {
              GC.messagesPageState.unreadSyncedFromApi = false;
              GC.messagesPageState.loadList();
            }
          }
        }
      }

      // --- Overview-Ressourcen-Karten ---
      const ovMetalVal = document.querySelector('#overview-metal-val .gc-val[data-res="metal"]');
      const ovMetalCap = document.querySelector('#overview-metal-val .gc-cap');
      if (ovMetalVal) _setIfChanged(ovMetalVal, fmtNumber(metal));
      if (ovMetalCap) _setIfChanged(ovMetalCap, `/ ${fmtNumber(storageMetal)}`);

      const ovCryVal = document.querySelector('#overview-crystal-val .gc-val[data-res="crystal"]');
      const ovCryCap = document.querySelector('#overview-crystal-val .gc-cap');
      if (ovCryVal) _setIfChanged(ovCryVal, fmtNumber(crystal));
      if (ovCryCap) _setIfChanged(ovCryCap, `/ ${fmtNumber(storageCrystal)}`);

      const ovEnergyUsed = document.querySelector('#overview-energy-val .gc-val[data-energy-used]');
      const ovEnergyTotal = document.querySelector('#overview-energy-val [data-energy-total]');
      if (ovEnergyUsed) _setIfChanged(ovEnergyUsed, fmtNumber(used));
      if (ovEnergyTotal) _setIfChanged(ovEnergyTotal, fmtNumber(total));

      // Effizienz (nur Serverwerte — keine lokale Gameplay-Formel)
      const ovEff = document.getElementById("overview-efficiency");
      if (ovEff) {
        const pct = Number.isFinite(Number(data.energy_efficiency_pct))
          ? Math.round(Number(data.energy_efficiency_pct))
          : 100;
        _setIfChanged(ovEff, pct);
      }

      // --- Build Queue / Buildings ---
      let queueList = [];
      if (Array.isArray(buildQueueRaw)) queueList = buildQueueRaw;
      else if (buildQueueRaw && Array.isArray(buildQueueRaw.queue)) queueList = buildQueueRaw.queue;

      const activeJob = queueList.length > 0 ? queueList[0] : null;

      Object.keys(BUILDINGS).forEach((key) => {
        const cfg = BUILDINGS[key];
        const lvl = buildings[key];

        if (typeof lvl !== "undefined" && cfg.levelId) setText(cfg.levelId, lvl);

        const prodCell = document.querySelector(`.bcell-prod[data-building="${key}"]`);
        if (prodCell) {
          if (key === "metal_storage" && storageMetal > 0) {
            _setIfChanged(prodCell, `${fmtNumber(metal)} / ${fmtNumber(storageMetal)}`);
          } else if (key === "crystal_storage" && storageCrystal > 0) {
            _setIfChanged(prodCell, `${fmtNumber(crystal)} / ${fmtNumber(storageCrystal)}`);
          } else {
            const val = Math.floor(prod[key] || 0);
            _setIfChanged(prodCell, val > 0 ? `+${fmtNumber(val)} / h` : "-");
          }
        }

        const queueActive = queueList.length > 0;
        const bqLimit = buildQueueRaw?.summary?.limit ?? 3;
        const bqCount = buildQueueRaw?.summary?.count ?? queueList.length;
        const bqFull = bqCount >= bqLimit;
        let statusText = t("status_ready", "Bereit");
        let btnLabel = queueActive ? t("action_queue_upgrade", "Upgrade (anreihen)") : t("action_upgrade", "Upgrade");

        if (queueActive && activeJob && activeJob.building_type === key) {
          statusText = `${t("status_building", "Im Bau")} (${formatEta(activeJob.remaining)})`;
        }

        if (cfg.statusId) setText(cfg.statusId, statusText);

        const btn = document.getElementById(cfg.btnId);
        if (btn && btn.tagName === "A" && !bqFull && btn.textContent !== btnLabel) btn.textContent = btnLabel;
      });

      renderBuildQueue(buildQueueRaw);
      updateBuildQueueActions(buildQueueRaw);
      renderResearchQueue(research);
      updateResearchQueueActions(research);

      if (activeResearch) {
        const totalSec = Math.max(
          1,
          parseInt(activeResearch.total_seconds, 10) ||
            parseInt(activeResearch.total, 10) ||
            (parseInt(activeResearch.remaining, 10) || 0) + 1
        );
        const finishAt = parseInt(activeResearch.finish_at, 10) || 0;

        const ovBox = document.getElementById("overview-research-active");
        if (ovBox) {
          ovBox.dataset.total = String(totalSec);
          if (finishAt > 0) ovBox.dataset.finishAt = String(finishAt);
        }

        const totalLabel = document.getElementById("research-total");
        if (totalLabel) _setIfChanged(totalLabel, `${totalSec}s`);

        RESEARCHQ.active.finishTime = finishAt;
        RESEARCHQ.active.totalSeconds = totalSec;
      } else {
        RESEARCHQ.active.finishTime = 0;
        RESEARCHQ.active.totalSeconds = 0;
      }

      patchOverviewResearch(research);
      patchOverviewTable(data.overview, buildings, prod);
      patchOverviewEnergyHint(data.overview, data);

      if (data.buildings_panel) {
        patchBuildingPanel(data.buildings_panel, buildQueueRaw);
      }

      if (research.techs) {
        patchResearchPanel(research.techs, research);
      }

      const hasActiveBuild = !!activeJob;
      const bqLimitFinal = buildQueueRaw?.summary?.limit ?? 3;
      const bqCountFinal = buildQueueRaw?.summary?.count ?? queueList.length;
      lastBuildQueueCount = bqCountFinal;
      lastBuildQueueFull = bqCountFinal >= bqLimitFinal;
      lastHadActiveJob = hasActiveBuild;

      const researchQueue = Array.isArray(research.queue) ? research.queue : (activeResearch ? [activeResearch] : []);
      const hasActiveResearchNow = researchQueue.length > 0;
      const rqLimitFinal = research?.summary?.limit ?? 3;
      const rqCountFinal = research?.summary?.count ?? researchQueue.length;
      lastResearchQueueCount = rqCountFinal;
      lastResearchQueueFull = rqCountFinal >= rqLimitFinal;
      lastHadActiveResearch = hasActiveResearchNow;

      GC.lastState = data;
      GC.startProgressTicker();

      return hasActiveBuild || hasActiveResearchNow;
  }

  async function refreshGameState(reason) {
    if (!shouldRunGameLoop() || _authLoopAborted) return null;
    if (GC.refreshInFlight) return GC.refreshInFlight;

    const p = GC.polling;
    p.inFlight = true;
    try {
      if (p.abort) p.abort.abort();
    } catch (_) {}

    const ctrl = new AbortController();
    p.abort = ctrl;

    GC.refreshInFlight = (async () => {
      try {
        const data = await GC.fetchJSON("/api/game-state", { cache: "no-store", signal: ctrl.signal });
        if (!data || data.ok === false) {
          if (isAuthStatusFailure(null, data)) handleAuthFailure("game-state-payload");
          return null;
        }

        p.backoff = 0;
        _statusPollErrorLogged = false;
        clearStatusWidgetOffline();
        if (data.server_time) setServerTime(data.server_time);

        const anyActive = applyGameStateData(data, reason);
        if (reason !== "poll") {
          GC.startPolling(anyActive);
        }
        return data;
      } catch (err) {
        if (err?.name === "AbortError") return null;

        if (isAuthStatusFailure(err)) {
          handleAuthFailure(reason);
          return null;
        }

        if (!shouldRunGameLoop()) {
          GC.stopPolling();
          return null;
        }

        logStatusPollErrorOnce(reason, err);
        markStatusWidgetOffline();
        p.backoff = Math.min(60000, (p.backoff || 2000) * 1.6);
        if (reason !== "poll" && shouldRunGameLoop() && !_authLoopAborted) {
          GC.startPolling(lastHadActiveJob || lastHadActiveResearch, true);
        }
        throw err;
      } finally {
        p.inFlight = false;
        p.abort = null;
        GC.refreshInFlight = null;
      }
    })();

    return GC.refreshInFlight;
  }

  GC.refreshGameState = refreshGameState;

  // =========================
  // Building tabs (delegated – survives PJAX)
  // =========================
  function activateBuildingTab(btn, focus = true) {
    const tablist = btn.closest(".building-tabs");
    if (!tablist) return;

    const targetTab = btn.dataset.tab;
    const tabBtns = Array.from(tablist.querySelectorAll(".tab-btn"));
    const tabContents = Array.from(document.querySelectorAll(".tab-content[data-tab]"));

    tabBtns.forEach((b) => {
      const isActive = b === btn;
      b.classList.toggle("active", isActive);
      if (b.getAttribute("role") === "tab") {
        b.setAttribute("aria-selected", isActive ? "true" : "false");
        b.setAttribute("tabindex", isActive ? "0" : "-1");
      }
    });

    tabContents.forEach((c) => {
      const isActive = c.dataset.tab === targetTab;
      c.classList.toggle("active", isActive);
      if (c.getAttribute("role") === "tabpanel") c.hidden = !isActive;
    });

    if (focus) btn.focus();
  }

  function bindBuildingTabsOnce() {
    if (GC._tabsBound) return;
    GC._tabsBound = true;

    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".building-tabs .tab-btn");
      if (!btn) return;
      if (btn.tagName === "A") e.preventDefault();
      activateBuildingTab(btn, true);
    });

    document.addEventListener("keydown", (e) => {
      const tablist = e.target.closest(".building-tabs[role='tablist']");
      if (!tablist) return;
      const current = document.activeElement;
      if (!current || !current.classList.contains("tab-btn")) return;

      const tabBtns = Array.from(tablist.querySelectorAll(".tab-btn"));
      const idx = tabBtns.indexOf(current);
      if (idx < 0) return;

      let nextIdx = idx;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        nextIdx = (idx + 1) % tabBtns.length;
        e.preventDefault();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        nextIdx = (idx - 1 + tabBtns.length) % tabBtns.length;
        e.preventDefault();
      } else if (e.key === "Home") {
        nextIdx = 0;
        e.preventDefault();
      } else if (e.key === "End") {
        nextIdx = tabBtns.length - 1;
        e.preventDefault();
      } else if (e.key === "Enter" || e.key === " ") {
        activateBuildingTab(current, true);
        e.preventDefault();
        return;
      } else return;

      tabBtns[nextIdx].focus();
    });
  }

  function initBuildings() {
    const tablist = document.querySelector(".building-tabs");
    if (!tablist) return;
    const tabBtns = Array.from(tablist.querySelectorAll(".tab-btn"));
    if (!tabBtns.length) return;
    const activeBtn = tabBtns.find((b) => b.classList.contains("active")) || tabBtns[0];
    activateBuildingTab(activeBtn, false);
  }

  function initOverview() {}

  function initResearch() {}

  function syncPlanetEvolutionResearchTicker() {
    const active = document.querySelector(".planet-evolution-page .pe-planet-research-active");
    if (!active) return;

    const finish = Number(active.dataset.finishTime || 0);
    const total = Math.max(1, Number(active.dataset.total || 1));
    const fill = active.querySelector(".pe-planet-research-fill");
    const etaEl = active.querySelector("[data-pe-research-eta]");
    const pctEl = active.querySelector("[data-pe-research-pct]");

    const formatEta = (sec) => {
      const s = Math.max(0, Math.ceil(sec));
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      return h > 0 ? `~${h}h ${m}m` : `~${m}m`;
    };

    const tick = () => {
      const now = getApproxServerNow() || Math.floor(Date.now() / 1000);
      const remaining = Math.max(0, finish - now);
      const pct = Math.max(0, Math.min(100, 100 * (1 - remaining / total)));
      if (fill) {
        fill.style.width = `${pct}%`;
        fill.setAttribute("aria-valuenow", String(Math.round(pct)));
      }
      if (etaEl) etaEl.textContent = formatEta(remaining);
      if (pctEl) pctEl.textContent = `${Math.round(pct)}%`;
    };

    tick();
    GC.setSafeInterval(tick, 1000);
  }

  function bindPlanetEvolutionOnce() {
    if (GC._peActionsBound) return;
    GC._peActionsBound = true;

    const tt = (key, fallback) => t(key, fallback);
    const reasonText = (reason) => {
      if (!reason) return tt("pe_error_generic", "Aktion fehlgeschlagen.");
      return tt(`pe_reason_${reason}`, reason);
    };

    const postAction = async (url, body) => {
      if (typeof GC.fetchGameAction === "function") {
        return GC.fetchGameAction(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          body: JSON.stringify(body || {}),
        });
      }
      return GC.fetchJSON(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify(body || {}),
      });
    };

    const scrollTargets = {
      events: "pe-section-events",
      research: "pe-section-research",
      specialization: "pe-section-specialization",
      economy: "pe-section-economy",
      progression: "pe-section-progression",
      traits: "pe-section-traits",
      policies: "pe-section-policies",
      action: "pe-section-action",
    };

    document.addEventListener("click", async (e) => {
      const root = document.querySelector(".planet-evolution-page");
      if (!root) return;

      const scrollBtn = e.target.closest(".pe-scroll-btn");
      if (scrollBtn && root.contains(scrollBtn)) {
        const target = scrollBtn.dataset.scroll;
        const panelMap = { events: "events", research: "research", policies: "policies", history: "history" };
        if (panelMap[target]) {
          const tab = root.querySelector(`.pe-sec-tab[data-panel="${panelMap[target]}"]`);
          if (tab) tab.click();
        }
        const id = scrollTargets[target] || `pe-section-${target}`;
        const el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }

      const tab = e.target.closest(".pe-sec-tab");
      if (tab && root.contains(tab)) {
        const name = tab.dataset.panel;
        root.querySelectorAll(".pe-sec-tab").forEach((tEl) => tEl.classList.toggle("is-active", tEl === tab));
        root.querySelectorAll(".pe-sec-panel").forEach((panel) => {
          const active = panel.dataset.panel === name;
          panel.classList.toggle("is-active", active);
          panel.hidden = !active;
        });
        return;
      }

      const planetBtn = e.target.closest(".pe-planet-btn");
      if (planetBtn && root.contains(planetBtn)) {
        planetBtn.disabled = true;
        const planetId = parseInt(planetBtn.dataset.planetId || "0", 10);
        const res = await postAction("/api/planets/active", { planet_id: planetId });
        if (res?.ok) await GC.reloadCurrentPage();
        else {
          planetBtn.disabled = false;
          alert(reasonText(res?.reason));
        }
        return;
      }

      const researchBtn = e.target.closest(".pe-research-btn");
      if (researchBtn && root.contains(researchBtn)) {
        researchBtn.disabled = true;
        const planetId = parseInt(researchBtn.dataset.planetId || "0", 10);
        const techKey = researchBtn.dataset.techKey || "";
        const requestId = (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
        const res = await postAction(`/api/planets/${planetId}/research/start`, { tech_key: techKey, request_id: requestId });
        if (res?.ok) await GC.reloadCurrentPage();
        else {
          researchBtn.disabled = false;
          alert(reasonText(res?.reason));
        }
        return;
      }

      const choiceBtn = e.target.closest(".pe-choice-btn");
      if (choiceBtn && root.contains(choiceBtn)) {
        if (!confirm(tt("pe_confirm_choice", "Diese Wahl ist permanent."))) return;
        choiceBtn.disabled = true;
        const planetId = parseInt(choiceBtn.dataset.planetId || "0", 10);
        const res = await postAction(`/api/planets/${planetId}/research/choose`, {
          choice_group: choiceBtn.dataset.choiceGroup,
          choice_key: choiceBtn.dataset.choiceKey,
        });
        if (res?.ok) await GC.reloadCurrentPage();
        else {
          choiceBtn.disabled = false;
          alert(reasonText(res?.reason));
        }
        return;
      }

      const specBtn = e.target.closest(".pe-spec-btn");
      if (specBtn && root.contains(specBtn)) {
        if (!confirm(tt("pe_confirm_spec", "Die Spezialisierung ist permanent."))) return;
        const picker = root.querySelector("#pe-spec-picker");
        if (!picker) return;
        specBtn.disabled = true;
        const planetId = parseInt(picker.dataset.planetId || "0", 10);
        const res = await postAction(`/api/planets/${planetId}/specialization/pick`, { spec_key: specBtn.dataset.specKey });
        if (res?.ok) await GC.reloadCurrentPage();
        else {
          specBtn.disabled = false;
          alert(reasonText(res?.reason));
        }
        return;
      }

      const specUpgradeBtn = e.target.closest(".pe-spec-upgrade-btn");
      if (specUpgradeBtn && root.contains(specUpgradeBtn)) {
        specUpgradeBtn.disabled = true;
        const planetId = parseInt(specUpgradeBtn.dataset.planetId || "0", 10);
        const res = await postAction(`/api/planets/${planetId}/specialization/upgrade`, {});
        if (res?.ok) await GC.reloadCurrentPage();
        else {
          specUpgradeBtn.disabled = false;
          alert(reasonText(res?.reason));
        }
        return;
      }

      const policyBtn = e.target.closest(".pe-policy-btn");
      if (policyBtn && root.contains(policyBtn)) {
        if (!confirm(tt("pe_confirm_policy", "Politik in diesem Slot aktivieren?"))) return;
        policyBtn.disabled = true;
        const planetId = parseInt(policyBtn.dataset.planetId || "0", 10);
        const slot = parseInt(policyBtn.dataset.slot || "0", 10);
        const res = await postAction(`/api/planets/${planetId}/policies/activate`, {
          slot,
          policy_key: policyBtn.dataset.policyKey,
        });
        if (res?.ok) await GC.reloadCurrentPage();
        else {
          policyBtn.disabled = false;
          alert(reasonText(res?.reason));
        }
        return;
      }

      const eventChoiceBtn = e.target.closest(".pe-event-choice-btn");
      const eventRoot = root.querySelector("#pe-event-choices");
      if (eventChoiceBtn && eventRoot && root.contains(eventChoiceBtn)) {
        eventChoiceBtn.disabled = true;
        const planetId = parseInt(eventRoot.dataset.planetId || "0", 10);
        const eventId = parseInt(eventRoot.dataset.eventId || "0", 10);
        const res = await postAction(`/api/planets/${planetId}/events/resolve`, {
          event_id: eventId,
          choice_key: eventChoiceBtn.dataset.choiceKey,
        });
        if (res?.ok) await GC.reloadCurrentPage();
        else {
          eventChoiceBtn.disabled = false;
          alert(reasonText(res?.reason));
        }
        return;
      }

      const colonizeBtn = e.target.closest("#pe-colonize-btn");
      if (colonizeBtn && root.contains(colonizeBtn)) {
        const name = prompt(tt("pe_colonize_prompt", "Name der neuen Kolonie:"));
        if (!name) return;
        colonizeBtn.disabled = true;
        const res = await postAction("/api/planets/colonize", {
          name,
          galaxy: 1,
          system: Math.floor(Math.random() * 900) + 100,
          position: Math.floor(Math.random() * 15) + 1,
        });
        if (res?.ok) await GC.reloadCurrentPage();
        else {
          colonizeBtn.disabled = false;
          alert(reasonText(res?.reason));
        }
      }
    });
  }

  function initPlanetEvolution() {
    if (!document.querySelector(".planet-evolution-page")) return;
    bindPlanetEvolutionOnce();
    syncPlanetEvolutionResearchTicker();
  }

  // =========================
  // Ranking page (PJAX-safe singleton)
  // =========================
  const _rankingLifecycle = { abort: null, loadId: 0, payload: null, tab: "total" };

  function rankingAbortInFlight() {
    if (_rankingLifecycle.abort) {
      try {
        _rankingLifecycle.abort.abort();
      } catch (_) {}
      _rankingLifecycle.abort = null;
    }
    _rankingLifecycle.loadId += 1;
  }

  const RANKING_TABS = [
    { id: "total", scoreKey: "total_score", rankKey: "rank_total", labelKey: "ranking_tab_total", fallback: "Total" },
    { id: "building", scoreKey: "building_score", rankKey: "rank_building", labelKey: "ranking_tab_buildings", fallback: "Buildings" },
    { id: "research", scoreKey: "research_score", rankKey: "rank_research", labelKey: "ranking_tab_research", fallback: "Research" },
    { id: "fleet", scoreKey: "fleet_score", rankKey: null, labelKey: "ranking_tab_fleet", fallback: "Fleet" },
    { id: "defense", scoreKey: "defense_score", rankKey: null, labelKey: "ranking_tab_defense", fallback: "Defense" },
  ];

  function rankingT(key, fallback) {
    const loc = window.GC_LOCALE || {};
    const v = loc[key];
    if (v && v !== key) return v;
    return fallback || key;
  }

  function rankingEscapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function rankingScoreValue(row, tabId) {
    const tab = RANKING_TABS.find((t) => t.id === tabId) || RANKING_TABS[0];
    return Number(row[tab.scoreKey]) || 0;
  }

  function rankingVisibleTabs(payload) {
    const cur = payload?.current_player || {};
    const top = Array.isArray(payload?.top_players) ? payload.top_players : [];
    return RANKING_TABS.filter((tab) => {
      if (tab.id === "total" || tab.id === "building" || tab.id === "research") return true;
      const curScore = Number(cur[tab.scoreKey]) || 0;
      const anyScore = top.some((row) => (Number(row[tab.scoreKey]) || 0) > 0);
      return curScore > 0 || anyScore;
    });
  }

  function rankingSortedRows(payload, tabId) {
    const top = Array.isArray(payload?.top_players) ? [...payload.top_players] : [];
    const tab = RANKING_TABS.find((t) => t.id === tabId) || RANKING_TABS[0];
    top.sort((a, b) => {
      const diff = rankingScoreValue(b, tabId) - rankingScoreValue(a, tabId);
      if (diff !== 0) return diff;
      return (Number(a.player_id) || 0) - (Number(b.player_id) || 0);
    });
    return top.map((row, idx) => {
      const displayRank = tab.rankKey && row[tab.rankKey] != null ? Number(row[tab.rankKey]) : idx + 1;
      return { ...row, display_rank: displayRank, display_score: rankingScoreValue(row, tabId) };
    });
  }

  function rankingCurrentRank(payload, tabId) {
    const cur = payload?.current_player || {};
    const ranks = cur.ranks || {};
    if (ranks[tabId] != null) return Number(ranks[tabId]);
    if (tabId === "total" && cur.rank != null) return Number(cur.rank);
    return null;
  }

  function rankingCurrentScore(payload, tabId) {
    const cur = payload?.current_player || {};
    const tab = RANKING_TABS.find((t) => t.id === tabId) || RANKING_TABS[0];
    return Number(cur[tab.scoreKey]) || 0;
  }

  function rankingAvatarInner(row) {
    const initial = rankingEscapeHtml(row.avatar_initial || "?");
    const theme = rankingEscapeHtml(row.theme || "cyan");
    if (row.show_avatar && row.avatar_url) {
      const src = rankingEscapeHtml(row.avatar_url);
      return `<img class="gc-ranking-avatar-img" src="${src}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">`;
    }
    return `<span class="gc-ranking-avatar-fallback gc-ranking-avatar-fallback--${theme}" aria-hidden="true">${initial}</span>`;
  }

  function bustAvatarUrl(url, version) {
    const raw = String(url || "").trim();
    if (!raw) return "";
    const v = Number(version) || 0;
    if (v <= 0) return raw;
    if (!/^https?:\/\//i.test(raw)) return raw;
    const sep = raw.includes("?") ? "&" : "?";
    return `${raw}${sep}v=${v}`;
  }

  GC.syncPlayerAvatarVisuals = function syncPlayerAvatarVisuals(sync) {
    const pid = Number(sync?.player_id);
    if (!Number.isFinite(pid) || pid <= 0) return;

    const busted = String(sync.avatar_url || "").trim();
    const show = !!(sync.show_avatar && busted);
    const initial = String(sync.avatar_initial || "?").slice(0, 1).toUpperCase() || "?";
    const theme = String(sync.theme || "cyan");

    document.querySelectorAll(`[data-player-card][data-player-id="${pid}"]`).forEach((trigger) => {
      const avatarWrap = trigger.querySelector(".gc-ranking-avatar");
      if (!avatarWrap) return;
      if (show) {
        avatarWrap.innerHTML =
          `<img class="gc-ranking-avatar-img" src="${rankingEscapeHtml(busted)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">`;
      } else {
        avatarWrap.innerHTML =
          `<span class="gc-ranking-avatar-fallback gc-ranking-avatar-fallback--${rankingEscapeHtml(theme)}" aria-hidden="true">${rankingEscapeHtml(initial)}</span>`;
      }
    });

    const modalImg = PLAYER_CARD.content?.querySelector(".gc-player-card-avatar[src]");
    if (modalImg && PLAYER_CARD.currentId === pid && show) {
      modalImg.src = busted;
      modalImg.hidden = false;
      const ph = PLAYER_CARD.content.querySelector(".gc-player-card-avatar-placeholder");
      if (ph) ph.hidden = true;
    }

    const top = GC._rankingLastPayload || _rankingLifecycle.payload;
    if (top?.top_players) {
      const row = top.top_players.find((r) => Number(r.player_id) === pid);
      if (row) {
        row.avatar_url = busted;
        row.show_avatar = show;
        row.avatar_initial = initial;
        row.theme = theme;
        if (document.getElementById("ranking-page")) {
          rankingRenderList(top, _rankingLifecycle.tab);
        }
      }
    }
  };

  function rankingBadgesHtml(row) {
    const badges = Array.isArray(row.badges) ? row.badges : [];
    if (!badges.length) return "";
    const chips = badges
      .map((badge) => {
        const label = rankingEscapeHtml(rankingT(badge.name_key, badge.icon || "★"));
        const icon = rankingEscapeHtml(badge.icon || "★");
        const rarity = rankingEscapeHtml(badge.rarity || "common");
        return (
          `<span class="gc-ranking-badge gc-ranking-badge--${rarity}" title="${label}" aria-label="${label}">` +
          `<span class="gc-ranking-badge-icon" aria-hidden="true">${icon}</span>` +
          `</span>`
        );
      })
      .join("");
    return `<div class="gc-ranking-badges" aria-label="${rankingEscapeHtml(rankingT("ranking_badges", "Badges"))}">${chips}</div>`;
  }

  function rankingAllianceHtml(row) {
    const noAlliance = rankingEscapeHtml(rankingT("ranking_no_alliance", "No alliance"));
    if (row.alliance_id && (row.alliance_tag || row.alliance_name)) {
      const tag = row.alliance_tag ? `[${rankingEscapeHtml(row.alliance_tag)}]` : "";
      const name = row.alliance_name ? ` ${rankingEscapeHtml(row.alliance_name)}` : "";
      const label = `${tag}${name}`.trim();
      return `<span class="gc-ranking-alliance" title="${label}">${label}</span>`;
    }
    return `<span class="gc-ranking-alliance gc-ranking-alliance--none">${noAlliance}</span>`;
  }

  function rankingTopClass(rank) {
    const r = Number(rank) || 0;
    if (r >= 1 && r <= 3) return ` gc-ranking-row--top gc-ranking-row--top-${r}`;
    return "";
  }

  function rankingYouPill(isMe) {
    if (!isMe) return "";
    const you = rankingEscapeHtml(rankingT("ranking_you", "You"));
    return `<span class="you-pill" aria-label="${you}">${you}</span>`;
  }

  function rankingCommanderNameHtml(row) {
    const display = row.commander_display || row.commander_name || "—";
    const prefix = rankingEscapeHtml(rankingT("commander", "Commander"));
    const name = rankingEscapeHtml(display);
    return (
      `<span class="gc-commander-prefix">${prefix}</span>` +
      `<span class="gc-ranking-player-name">${name}</span>`
    );
  }

  function rankingPlayerCell(row, isMe) {
    const pid = Number(row.player_id) || 0;
    const openLabel = rankingEscapeHtml(rankingT("ranking_open_playercard", "Open player card"));
    const displayName = rankingEscapeHtml(row.commander_display || row.commander_name || "—");
    const nameRow = rankingCommanderNameHtml(row);
    const title = row.title
      ? `<span class="gc-ranking-player-title">${rankingEscapeHtml(row.title)}</span>`
      : "";

    if (pid <= 0) {
      return (
        `<div class="gc-ranking-player">` +
        `<span class="gc-ranking-avatar">${rankingAvatarInner(row)}</span>` +
        `<div class="gc-ranking-player-meta"><div class="gc-ranking-player-name-row">${nameRow}</div>${title}${rankingBadgesHtml(row)}</div>` +
        `</div>`
      );
    }

    return (
      `<button type="button" class="gc-ranking-player gc-ranking-player-trigger" ` +
      `data-player-id="${pid}" data-player-card="1" aria-label="${openLabel}: ${displayName}">` +
      `<span class="gc-ranking-avatar">${rankingAvatarInner(row)}</span>` +
      `<div class="gc-ranking-player-meta">` +
      `<div class="gc-ranking-player-name-row">${rankingYouPill(isMe)}${nameRow}</div>` +
      title +
      rankingBadgesHtml(row) +
      `</div>` +
      `</button>`
    );
  }

  function rankingRenderMyStrip(payload, tabId) {
    const stripEl = document.getElementById("ranking-my-strip");
    if (!stripEl || !payload?.ok) {
      if (stripEl) stripEl.innerHTML = "";
      return;
    }
    const rank = rankingCurrentRank(payload, tabId);
    const totalPlayers = Number(payload.current_player?.total_players) || 0;
    const score = rankingCurrentScore(payload, tabId);
    const tab = RANKING_TABS.find((t) => t.id === tabId) || RANKING_TABS[0];
    const rankText = rank ? `#${fmtNumber(rank)} / ${fmtNumber(totalPlayers)}` : "—";
    stripEl.innerHTML =
      `<div class="gc-ranking-my-rank">` +
      `<span class="gc-ranking-my-label">${rankingEscapeHtml(rankingT("ranking_my_rank", "Your rank"))}</span>` +
      `<span class="gc-ranking-my-value">${rankText}</span>` +
      `</div>` +
      `<div class="gc-ranking-my-score">` +
      `<span class="gc-ranking-my-label">${rankingEscapeHtml(rankingT(tab.labelKey, tab.fallback))}</span>` +
      `<span class="gc-ranking-my-value gc-mono">${fmtNumber(score)}</span>` +
      `</div>`;
  }

  function rankingRenderTabs(payload, tabId) {
    const tabsEl = document.getElementById("ranking-tabs");
    if (!tabsEl) return;
    const tabs = rankingVisibleTabs(payload);
    if (!tabs.some((t) => t.id === tabId)) {
      _rankingLifecycle.tab = tabs[0]?.id || "total";
    }
    const activeTab = _rankingLifecycle.tab;
    tabsEl.innerHTML = tabs
      .map((tab) => {
        const label = rankingEscapeHtml(rankingT(tab.labelKey, tab.fallback));
        const active = tab.id === activeTab ? " active" : "";
        return (
          `<button type="button" class="gc-btn gc-btn-outline tab-btn${active}" ` +
          `data-ranking-tab="${tab.id}" role="tab" aria-selected="${tab.id === activeTab ? "true" : "false"}">` +
          label +
          `</button>`
        );
      })
      .join("");
  }

  function rankingRenderList(payload, tabId) {
    const tableEl = document.getElementById("ranking-table-content");
    if (!tableEl) return;

    if (!payload || !payload.ok) {
      const errMsg = rankingT("ranking_error", "Could not load ranking.");
      tableEl.innerHTML = `<div class="ranking-state ranking-state-error">${rankingEscapeHtml(errMsg)}</div>`;
      return;
    }

    const rows = rankingSortedRows(payload, tabId);
    const tab = RANKING_TABS.find((t) => t.id === tabId) || RANKING_TABS[0];
    const scoreLabel = rankingEscapeHtml(rankingT(tab.labelKey, tab.fallback));

    if (!rows.length) {
      tableEl.innerHTML = `<p class="ranking-empty">${rankingEscapeHtml(rankingT("ranking_empty", "No data yet."))}</p>`;
      return;
    }

    const desktopRows = rows
      .map((row) => {
        const isMe = !!row.is_current_player;
        return (
          `<tr class="gc-ranking-row${isMe ? " is-me" : ""}${rankingTopClass(row.display_rank)}">` +
          `<td class="gc-ranking-place"><span class="gc-ranking-place-num">#${fmtNumber(row.display_rank)}</span></td>` +
          `<td class="gc-ranking-col-player">${rankingPlayerCell(row, isMe)}</td>` +
          `<td class="gc-ranking-col-alliance">${rankingAllianceHtml(row)}</td>` +
          `<td class="gc-ranking-score gc-ranking-score--active">${fmtNumber(row.display_score)}</td>` +
          `</tr>`
        );
      })
      .join("");

    const mobileCards = rows
      .map((row) => {
        const isMe = !!row.is_current_player;
        return (
          `<article class="gc-ranking-mobile-card${isMe ? " is-me" : ""}${rankingTopClass(row.display_rank)}">` +
          `<div class="gc-ranking-mobile-head">` +
          `<span class="gc-ranking-place gc-ranking-place-num">#${fmtNumber(row.display_rank)}</span>` +
          rankingAllianceHtml(row) +
          `<span class="gc-ranking-mobile-score-inline gc-mono">${fmtNumber(row.display_score)}</span>` +
          `</div>` +
          `<div class="gc-ranking-mobile-player">${rankingPlayerCell(row, isMe)}</div>` +
          `</article>`
        );
      })
      .join("");

    tableEl.innerHTML =
      `<div class="gc-ranking">` +
      `<div class="gc-ranking-desktop ranking-table-wrapper">` +
      `<table class="gc-ranking-table">` +
      `<thead><tr>` +
      `<th class="gc-ranking-place">${rankingEscapeHtml(rankingT("ranking_rank", "Rank"))}</th>` +
      `<th class="gc-ranking-col-player">${rankingEscapeHtml(rankingT("ranking_commander", "Commander"))}</th>` +
      `<th class="gc-ranking-col-alliance">${rankingEscapeHtml(rankingT("ranking_alliance", "Alliance"))}</th>` +
      `<th class="gc-ranking-score gc-ranking-score--active">${scoreLabel}</th>` +
      `</tr></thead>` +
      `<tbody>${desktopRows}</tbody>` +
      `</table>` +
      `</div>` +
      `<div class="gc-ranking-mobile">${mobileCards}</div>` +
      `</div>`;
  }

  function renderRankingPayload(payload) {
    if (payload?.ok) GC._rankingLastPayload = payload;
    _rankingLifecycle.payload = payload && payload.ok ? payload : null;
    if (_rankingLifecycle.payload) {
      const visible = rankingVisibleTabs(_rankingLifecycle.payload);
      if (!visible.some((t) => t.id === _rankingLifecycle.tab)) {
        _rankingLifecycle.tab = visible[0]?.id || "total";
      }
    }
    rankingRenderMyStrip(_rankingLifecycle.payload, _rankingLifecycle.tab);
    rankingRenderTabs(_rankingLifecycle.payload, _rankingLifecycle.tab);
    rankingRenderList(_rankingLifecycle.payload, _rankingLifecycle.tab);
  }

  function bindRankingTabsOnce() {
    if (GC._rankingTabsBound) return;
    GC._rankingTabsBound = true;
    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-ranking-tab]");
      if (!btn || !document.getElementById("ranking-page")) return;
      const tabId = btn.getAttribute("data-ranking-tab");
      if (!tabId || tabId === _rankingLifecycle.tab) return;
      e.preventDefault();
      _rankingLifecycle.tab = tabId;
      renderRankingPayload(_rankingLifecycle.payload);
    });
  }

  function loadRankingData() {
    const tableEl = document.getElementById("ranking-table-content");
    if (!tableEl) return;

    if (_rankingLifecycle.abort) {
      try {
        _rankingLifecycle.abort.abort();
      } catch (_) {}
    }
    _rankingLifecycle.abort = new AbortController();
    const loadId = ++_rankingLifecycle.loadId;
    const signal = _rankingLifecycle.abort.signal;

    const loadingMsg = rankingEscapeHtml(rankingT("ranking_loading", "Loading…"));
    tableEl.innerHTML = `<div class="ranking-state ranking-state-loading">${loadingMsg}</div>`;

    const initialEl = document.getElementById("ranking-initial-data");
    if (initialEl) {
      try {
        const data = JSON.parse(initialEl.textContent || "{}");
        initialEl.remove();
        if (loadId === _rankingLifecycle.loadId) renderRankingPayload(data);
        return;
      } catch (_) {
        initialEl.remove();
      }
    }

    GC.fetchJSON("/api/ranking", {
      cache: "no-store",
      signal,
    })
      .then((data) => {
        if (loadId !== _rankingLifecycle.loadId) return;
        renderRankingPayload(data);
      })
      .catch((err) => {
        if (err && err.name === "AbortError") return;
        if (loadId !== _rankingLifecycle.loadId) return;
        renderRankingPayload(null);
      });
  }

  GC.initRanking = function initRanking() {
    if (!document.getElementById("ranking-page")) return;
    bindRankingTabsOnce();
    loadRankingData();
  };

  GC.modules.overview = initOverview;
  GC.modules.buildings = initBuildings;
  GC.modules.research = initResearch;
  GC.modules.planet_evolution = initPlanetEvolution;
  GC.modules.ranking = function initRankingPage() {
    GC.initRanking();
  };
  GC.modules.techtree = function initTechtree() {};

  // =========================
  // PJAX navigation
  // =========================
  function _syncNavActive(url) {
    let path;
    try {
      path = new URL(url, window.location.origin).pathname.replace(/\/$/, "") || "/";
    } catch (_) {
      return;
    }
    document.querySelectorAll(
      ".gc-nav-link, .gc-bottom-nav-item, .gc-nav-drawer-link, a.gc-hud-panel-messages"
    ).forEach((link) => {
      const href = link.getAttribute("href");
      if (!href) return;
      let linkPath;
      try {
        linkPath = new URL(href, window.location.origin).pathname.replace(/\/$/, "") || "/";
      } catch (_) {
        return;
      }
      link.classList.toggle("active", linkPath === path);
    });
  }

  GC.navigateTo = async function navigateTo(url, opts = {}) {
    const push = opts.push !== false;
    if (GC._pjaxAbort) {
      try { GC._pjaxAbort.abort(); } catch (_) {}
    }

    GC.pjaxInFlight = (async () => {
      const ctrl = new AbortController();
      GC._pjaxAbort = ctrl;
      try {
        GC.cleanupPage();
        const res = await fetch(url, {
          credentials: "same-origin",
          cache: "no-store",
          signal: ctrl.signal,
          headers: {
            "X-PJAX": "true",
            "X-Requested-With": "XMLHttpRequest",
            Accept: "text/html",
          },
        });
        if (!res.ok) throw new Error(`PJAX ${res.status}`);
        const html = await res.text();
        const doc = new DOMParser().parseFromString(html, "text/html");
        const newMain = doc.getElementById("main-content");
        if (!newMain) throw new Error("main-content missing");

        const main = document.getElementById("main-content");
        main.innerHTML = newMain.innerHTML;
        if (doc.title) document.title = doc.title;

        const fetchedBody = doc.body;
        if (fetchedBody?.dataset && fetchedBody.dataset.endpoint !== undefined) {
          document.body.dataset.endpoint = fetchedBody.dataset.endpoint || "";
        }

        _syncNavActive(url);
        if (push) history.pushState({ gcPjax: true }, "", url);

        await GC.initPage({ force: true });
      } catch (err) {
        if (err?.name === "AbortError") return;
        console.error("[GC] PJAX navigation failed:", err);
        showNotify(
          t("msg_status_refresh_failed", "Seite konnte nicht geladen werden. Bitte erneut versuchen."),
          "error"
        );
      } finally {
        GC.pjaxInFlight = null;
        if (GC._pjaxAbort === ctrl) GC._pjaxAbort = null;
      }
    })();

    return GC.pjaxInFlight;
  };

  function initPjax() {
    if (GC._pjaxBound) return;
    GC._pjaxBound = true;

    const PJAX_LINK =
      "a.gc-nav-link, a.gc-bottom-nav-item, a.gc-nav-drawer-link, a.gc-hud-panel-messages";

    document.addEventListener("click", (e) => {
      const link = e.target.closest(PJAX_LINK);
      if (!link || link.tagName !== "A") return;
      if (link.hasAttribute("data-no-pjax") || link.target === "_blank") return;
      const href = link.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
      try {
        const dest = new URL(href, window.location.origin);
        if (dest.origin !== window.location.origin) return;
      } catch (_) {
        return;
      }
      e.preventDefault();
      GC.navigateTo(href);
    });

    window.addEventListener("popstate", (e) => {
      if (!e.state?.gcPjax) return;
      GC.navigateTo(window.location.pathname + window.location.search, { push: false });
    });
  }

  // =========================
  // Forms: validation + loading state
  // =========================
  function setClientError(form, message) {
    const box = qs(form, "#client-error");
    if (!box) return;

    if (!message) {
      box.classList.add("hidden");
      box.textContent = "";
      return;
    }

    box.textContent = message;
    box.classList.remove("hidden");
    try { box.focus(); } catch (_) {}
  }

  function markInvalid(input, isInvalid) {
    if (!input) return;
    if (isInvalid) {
      input.classList.add("is-invalid");
      input.setAttribute("aria-invalid", "true");
    } else {
      input.classList.remove("is-invalid");
      input.removeAttribute("aria-invalid");
    }
  }

  function validateLogin(form) {
    const username = qs(form, "#username");
    const password = qs(form, "#password");

    const u = (username?.value || "").trim();
    const p = password?.value || "";

    markInvalid(username, false);
    markInvalid(password, false);
    setClientError(form, "");

    if (u.length < 3) {
      markInvalid(username, true);
      setClientError(form, t("err_username_short", "Benutzername ist zu kurz (min. 3 Zeichen)."));
      username?.focus();
      return false;
    }
    if (u.length > 24) {
      markInvalid(username, true);
      setClientError(form, t("err_username_long", "Benutzername ist zu lang (max. 24 Zeichen)."));
      username?.focus();
      return false;
    }

    const isAdmin = u.toLowerCase() === "admin";
    const minLen = isAdmin ? 4 : 6;

    if (p.length < minLen) {
      markInvalid(password, true);
      setClientError(form, t("err_password_short", `Passwort ist zu kurz (min. ${minLen} Zeichen).`));
      password?.focus();
      return false;
    }

    return true;
  }

  function validateRegister(form) {
    const username = qs(form, "#username");
    const password = qs(form, "#password");
    const password2 = qs(form, "#password2");

    const u = (username?.value || "").trim();
    const p = password?.value || "";
    const p2 = password2?.value || "";

    [username, password, password2].forEach((el) => markInvalid(el, false));
    setClientError(form, "");

    if (u.length < 3) {
      markInvalid(username, true);
      setClientError(form, t("err_username_short", "Commander-Name ist zu kurz (min. 3 Zeichen)."));
      username?.focus();
      return false;
    }
    if (u.length > 24) {
      markInvalid(username, true);
      setClientError(form, t("err_username_long", "Commander-Name ist zu lang (max. 24 Zeichen)."));
      username?.focus();
      return false;
    }
    if (/\s/.test(u)) {
      markInvalid(username, true);
      setClientError(form, t("err_username_spaces", "Commander-Name darf keine Leerzeichen enthalten."));
      username?.focus();
      return false;
    }
    if (p.length < 8) {
      markInvalid(password, true);
      setClientError(form, t("err_password_short", "Passwort ist zu kurz (min. 8 Zeichen empfohlen)."));
      password?.focus();
      return false;
    }
    if (p2.length < 8) {
      markInvalid(password2, true);
      setClientError(form, t("err_password2_short", "Bitte Passwort wiederholen (min. 8 Zeichen)."));
      password2?.focus();
      return false;
    }
    if (p !== p2) {
      markInvalid(password, true);
      markInvalid(password2, true);
      setClientError(form, t("err_password_mismatch", "Passwörter stimmen nicht überein."));
      password2?.focus();
      return false;
    }
    return true;
  }

  function setButtonLoading(btn, isLoading) {
    if (!btn) return;

    const loadingText = btn.getAttribute("data-loading-text") || t("loading", "Lädt…");
    if (!btn.dataset.originalText) btn.dataset.originalText = btn.innerHTML;

    if (isLoading) {
      btn.disabled = true;
      btn.setAttribute("aria-disabled", "true");
      btn.innerHTML = loadingText;
    } else {
      btn.disabled = false;
      btn.removeAttribute("aria-disabled");
      btn.innerHTML = btn.dataset.originalText || btn.innerHTML;
    }
  }

  function initForms() {
    const forms = qsa(document, 'form[data-validate]');
    if (!forms.length) return;

    forms.forEach((form) => {
      const mode = form.getAttribute("data-validate");

      const serverErr = qs(form, "#form-error");
      if (serverErr) {
        setTimeout(() => { try { serverErr.focus(); } catch (_) {} }, 20);
      }

      qsa(form, ".auth-input").forEach((inp) => {
        inp.addEventListener("input", () => markInvalid(inp, false));
      });

      form.addEventListener("submit", (e) => {
        const btn = qs(form, 'button[type="submit"]');

        let ok = true;
        if (mode === "login") ok = validateLogin(form);
        if (mode === "register") ok = validateRegister(form);

        if (!ok) {
          e.preventDefault();
          setButtonLoading(btn, false);
          return;
        }

        setClientError(form, "");
        setButtonLoading(btn, true);

        setTimeout(() => setButtonLoading(btn, false), 12000);
      });
    });
  }

  // =========================
  // Skip link
  // =========================
  function initSkipLink() {
    const skip = document.querySelector(".gc-skip-link");
    const main = document.getElementById("main-content");
    if (!skip || !main) return;

    skip.addEventListener("click", () => {
      setTimeout(() => { try { main.focus(); } catch (_) {} }, 0);
    });
  }

  // =========================
  // Game actions (AJAX, kein Form-Reload)
  // =========================
  function initGameActions() {
    if (GC._gameActionsBound) return;
    GC._gameActionsBound = true;

    document.addEventListener("click", async (e) => {
      const upgradeEl = e.target.closest("a.btn-upgrade, button.btn-upgrade:not([disabled])");
      if (upgradeEl && !upgradeEl.hasAttribute("disabled")) {
        if (upgradeEl.tagName === "A") e.preventDefault();
        if (upgradeEl.dataset.busy === "1" || GC.actionLocks.build) return;
        upgradeEl.dataset.busy = "1";
        GC.actionLocks.build = true;

        const buildingType = upgradeEl.dataset.building || "";
        const tab = _getActiveBuildingTab();

        try {
          const json = await GC.fetchGameAction("/api/buildings/upgrade", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ building_type: buildingType, tab, request_id: newRequestId() }),
          });
          applyActionState(json, json.ok ? "upgrade_success" : "upgrade_error");
          if (json.ok) {
            showNotify(t("msg_build_queued", "Bauauftrag angereiht."), "success");
          } else {
            showNotify(mapActionError(json.reason, json.payload), "error");
          }
        } catch (err) {
          console.error("Upgrade AJAX fehlgeschlagen:", err);
          showNotify(
            t("msg_action_failed", "Aktion fehlgeschlagen. Bitte erneut versuchen."),
            "error"
          );
        } finally {
          upgradeEl.dataset.busy = "0";
          GC.actionLocks.build = false;
        }
        return;
      }

      const researchLink = e.target.closest("a.btn-research, button.btn-research:not([disabled])");
      if (researchLink && !researchLink.hasAttribute("disabled")) {
        if (researchLink.tagName === "A") e.preventDefault();
        if (researchLink.dataset.busy === "1" || GC.actionLocks.research) return;
        researchLink.dataset.busy = "1";
        GC.actionLocks.research = true;

        const match = (researchLink.getAttribute("href") || "").match(/\/research_start\/([^/?#]+)/);
        const techKey = match ? decodeURIComponent(match[1]) : "";

        try {
          const json = await GC.fetchGameAction("/api/research/start", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ tech_key: techKey, request_id: newRequestId() }),
          });
          applyActionState(json, json.ok ? "research_start_success" : "research_start_error");
          if (json.ok) {
            showNotify(t("research_msg_started_short", "Forschung angereiht."), "success");
          } else {
            showNotify(mapActionError(json.reason, json.payload), "error");
          }
        } catch (err) {
          console.error("Research AJAX fehlgeschlagen:", err);
          showNotify(
            t("msg_action_failed", "Aktion fehlgeschlagen. Bitte erneut versuchen."),
            "error"
          );
        } finally {
          researchLink.dataset.busy = "0";
          GC.actionLocks.research = false;
        }
        return;
      }

      const buildCancelBtn = e.target.closest("[data-build-cancel-id]");
      if (buildCancelBtn) {
        e.preventDefault();
        if (buildCancelBtn.dataset.busy === "1" || GC.actionLocks.build) return;
        buildCancelBtn.dataset.busy = "1";
        GC.actionLocks.build = true;
        try {
          const json = await GC.fetchGameAction("/api/buildings/cancel", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ job_id: Number(buildCancelBtn.dataset.buildCancelId || 0) }),
          });
          applyActionState(json, json.ok ? "build_cancel_success" : "build_cancel_error");
          if (json.ok) {
            showNotify(t("msg_build_cancelled", "Bauauftrag abgebrochen."), "success");
          } else {
            showNotify(mapActionError(json.reason, json.payload), "error");
          }
        } catch (err) {
          console.error("Build cancel AJAX fehlgeschlagen:", err);
          showNotify(t("msg_action_failed", "Aktion fehlgeschlagen. Bitte erneut versuchen."), "error");
        } finally {
          buildCancelBtn.dataset.busy = "0";
          GC.actionLocks.build = false;
        }
        return;
      }

      const researchCancelBtn = e.target.closest("[data-research-cancel-id]");
      if (researchCancelBtn) {
        e.preventDefault();
        if (researchCancelBtn.dataset.busy === "1" || GC.actionLocks.research) return;
        researchCancelBtn.dataset.busy = "1";
        GC.actionLocks.research = true;
        try {
          const json = await GC.fetchGameAction("/api/research/cancel", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ job_id: Number(researchCancelBtn.dataset.researchCancelId || 0) }),
          });
          applyActionState(json, json.ok ? "research_cancel_success" : "research_cancel_error");
          if (json.ok) {
            showNotify(t("msg_research_cancelled", "Forschungsauftrag abgebrochen."), "success");
          } else {
            showNotify(mapActionError(json.reason, json.payload), "error");
          }
        } catch (err) {
          console.error("Research cancel AJAX fehlgeschlagen:", err);
          showNotify(t("msg_action_failed", "Aktion fehlgeschlagen. Bitte erneut versuchen."), "error");
        } finally {
          researchCancelBtn.dataset.busy = "0";
          GC.actionLocks.research = false;
        }
      }
    });
  }

  // =========================
  // Flash autohide
  // =========================
  function initFlashAutohide() {
    GC.setSafeTimeout(() => {
      const box = document.getElementById("messages");
      if (!box) return;
      box.style.transition = "opacity 0.4s ease";
      box.style.opacity = "0";
      GC.setSafeTimeout(() => box.remove(), 450);
    }, 4000);
  }

  // =========================
  // Visibility listener
  // =========================
  function initVisibilityPolling() {
    if (GC._visibilityBound) return;
    GC._visibilityBound = true;

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        GC.stopPolling();
        return;
      }
      if (!shouldRunGameLoop() || _authLoopAborted) return;
      _authLoopAborted = false;
      GC.refreshGameState("tab_visible").then(() => {
        GC.startPolling(lastHadActiveJob || lastHadActiveResearch);
      });
      GC.startProgressTicker();
      if (typeof GC.resumeChatPolling === "function") GC.resumeChatPolling();
    });
  }

  // =========================
  // Mobile nav drawer
  // =========================
  function initMobileNav() {
    const moreBtn = document.getElementById("gc-nav-more-btn");
    const drawer = document.getElementById("gc-nav-drawer");
    const backdrop = document.getElementById("gc-nav-drawer-backdrop");
    const closeBtn = document.getElementById("gc-nav-drawer-close");
    const panel = drawer ? drawer.querySelector(".gc-nav-drawer-panel") : null;
    if (!moreBtn || !drawer) return;

    const DRAWER_MS = 280;

    function openDrawer() {
      drawer.hidden = false;
      document.body.classList.add("gc-nav-drawer-open");
      moreBtn.setAttribute("aria-expanded", "true");
      moreBtn.classList.add("active");
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          drawer.classList.add("is-open");
        });
      });
    }

    function closeDrawer() {
      drawer.classList.remove("is-open");
      document.body.classList.remove("gc-nav-drawer-open");
      moreBtn.setAttribute("aria-expanded", "false");
      moreBtn.classList.remove("active");

      const finish = () => {
        drawer.hidden = true;
      };

      if (panel) {
        let done = false;
        const onEnd = (e) => {
          if (e.target !== panel || e.propertyName !== "transform") return;
          done = true;
          panel.removeEventListener("transitionend", onEnd);
          finish();
        };
        panel.addEventListener("transitionend", onEnd);
        setTimeout(() => {
          if (!done) {
            panel.removeEventListener("transitionend", onEnd);
            finish();
          }
        }, DRAWER_MS + 40);
      } else {
        setTimeout(finish, DRAWER_MS);
      }
    }

    moreBtn.addEventListener("click", () => {
      if (drawer.hidden || !drawer.classList.contains("is-open")) openDrawer();
      else closeDrawer();
    });

    if (backdrop) backdrop.addEventListener("click", closeDrawer);
    if (closeBtn) closeBtn.addEventListener("click", closeDrawer);

    drawer.querySelectorAll("a.gc-nav-drawer-link").forEach((link) => {
      link.addEventListener("click", closeDrawer);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && drawer.classList.contains("is-open")) closeDrawer();
    });
  }

  // =========================
  // Special panel (Wiki/Support)
  // =========================
  function initSpecialPanel() {
    const root = document.querySelector("[data-special-root]");
    if (!root || root.dataset.bound === "1") return;
    root.dataset.bound = "1";

    const openButtons = root.querySelectorAll("[data-special-open-window]");
    const closeButtons = root.querySelectorAll("[data-special-window-close]");
    const windows = root.querySelectorAll("[data-special-window]");
    const barButtons = root.querySelectorAll(".gc-special-bar [data-special-open-window]");

    const setActiveBarButton = (target) => {
      barButtons.forEach((btn) => {
        const isActive = (btn.dataset.specialOpenWindow || "") === target;
        btn.classList.toggle("is-active", isActive);
      });
    };

    const closeAllWindows = () => {
      windows.forEach((win) => {
        win.hidden = true;
      });
      root.classList.remove("is-open");
      setActiveBarButton("");
    };

    const openWindow = (target) => {
      if (!target) return;

      if (target === "chat") {
        windows.forEach((win) => {
          win.hidden = true;
        });
        root.classList.remove("is-open");
        const chatFab = document.querySelector("[data-chat-fab]");
        if (chatFab) chatFab.click();
        setActiveBarButton("chat");
        return;
      }

      let found = false;
      windows.forEach((win) => {
        const active = (win.dataset.specialWindow || "") === target;
        win.hidden = !active;
        if (active) found = true;
      });
      if (!found) return;
      root.classList.add("is-open");
      setActiveBarButton(target);
    };

    openButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.specialOpenWindow || "";
        openWindow(target);
      });
    });

    closeButtons.forEach((btn) => {
      btn.addEventListener("click", () => closeAllWindows());
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAllWindows();
    });
  }

  function openSpecialWindow(target) {
    const root = document.querySelector("[data-special-root]");
    if (!root) return;
    const btn = root.querySelector(`[data-special-open-window="${target}"]`);
    if (btn) btn.click();
  }

  function initSupportModule() {
    const createRoot = document.querySelector("[data-special-window='support']");
    const ticketsRoot = document.querySelector("[data-special-window='my-tickets']");
    if ((!createRoot && !ticketsRoot) || window._GC_SUPPORT_BOUND === "1") return;
    window._GC_SUPPORT_BOUND = "1";

    const form = createRoot && createRoot.querySelector("[data-support-form]");
    const subjectEl = createRoot && createRoot.querySelector("[data-support-subject]");
    const categoryEl = createRoot && createRoot.querySelector("[data-support-category]");
    const priorityEl = createRoot && createRoot.querySelector("[data-support-priority]");
    const messageEl = createRoot && createRoot.querySelector("[data-support-message]");
    const createFeedbackEl = createRoot && createRoot.querySelector("[data-support-feedback]");
    const openTicketsBtn = createRoot && createRoot.querySelector("[data-support-open-tickets]");
    const refreshBtn = ticketsRoot && ticketsRoot.querySelector("[data-support-refresh]");
    const listEl = ticketsRoot && ticketsRoot.querySelector("[data-support-list]");
    const ticketsFeedbackEl = ticketsRoot && ticketsRoot.querySelector("[data-support-tickets-feedback]");
    if (!listEl) return;

    const dtf = new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" });

    const setFeedback = (el, text, kind = "") => {
      if (!el) return;
      el.textContent = text || "";
      el.classList.remove("is-ok", "is-error");
      if (kind) el.classList.add(kind === "ok" ? "is-ok" : "is-error");
    };

    const formatTs = (ts) => {
      const n = Number(ts || 0);
      if (!n) return "-";
      try {
        return dtf.format(new Date(n * 1000));
      } catch (_) {
        return "-";
      }
    };

    const createMessageNode = (m) => {
      const row = document.createElement("div");
      row.className = "gc-support-msg";
      const meta = document.createElement("div");
      meta.className = "gc-support-msg-meta";
      meta.textContent = `${m.sender_name || "Unbekannt"} · ${formatTs(m.created_at)}`;
      const body = document.createElement("div");
      body.className = "gc-support-msg-body";
      body.textContent = m.message || "";
      row.appendChild(meta);
      row.appendChild(body);
      return row;
    };

    const createTicketNode = (ticket) => {
      const wrap = document.createElement("details");
      wrap.className = "gc-support-ticket";
      wrap.open = ticket.status !== "closed";
      const head = document.createElement("summary");
      head.innerHTML =
        `<span class="gc-support-ticket-subject">${ticket.subject || "-"}</span>` +
        `<span class="gc-support-ticket-meta">${ticket.status_label || ticket.status} · ${ticket.priority_label || ticket.priority} · ${ticket.category_label || ticket.category}</span>`;
      wrap.appendChild(head);

      const body = document.createElement("div");
      body.className = "gc-support-ticket-body";

      const timeline = document.createElement("div");
      timeline.className = "gc-support-timeline";
      (ticket.messages || []).forEach((m) => timeline.appendChild(createMessageNode(m)));
      body.appendChild(timeline);

      const controls = document.createElement("div");
      controls.className = "gc-support-ticket-controls";

      const reply = document.createElement("textarea");
      reply.className = "gc-support-reply";
      reply.rows = 2;
      reply.maxLength = 1200;
      reply.placeholder = "Antwort schreiben...";
      controls.appendChild(reply);

      const actions = document.createElement("div");
      actions.className = "gc-support-actions";
      const sendBtn = document.createElement("button");
      sendBtn.type = "button";
      sendBtn.className = "gc-btn gc-btn-primary gc-btn-xs";
      sendBtn.textContent = "Antwort senden";
      sendBtn.addEventListener("click", async () => {
        const msg = (reply.value || "").trim();
        if (!msg) {
          setFeedback(ticketsFeedbackEl, "Bitte zuerst eine Antwort schreiben.", "error");
          return;
        }
        sendBtn.disabled = true;
        try {
          const res = await fetch(`/api/support/tickets/${ticket.id}/reply`, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ message: msg }),
          });
          const data = await res.json();
          if (!res.ok || !data.ok) {
            setFeedback(ticketsFeedbackEl, "Antwort konnte nicht gesendet werden.", "error");
            return;
          }
          setFeedback(ticketsFeedbackEl, "Antwort gesendet.", "ok");
          await loadTickets();
        } catch (_) {
          setFeedback(ticketsFeedbackEl, "Verbindungsfehler beim Antworten.", "error");
        } finally {
          sendBtn.disabled = false;
        }
      });
      actions.appendChild(sendBtn);

      if (ticket.status !== "closed") {
        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.className = "gc-btn gc-btn-ghost gc-btn-xs";
        closeBtn.textContent = "Ticket schliessen";
        closeBtn.addEventListener("click", async () => {
          closeBtn.disabled = true;
          try {
            const res = await fetch(`/api/support/tickets/${ticket.id}/status`, {
              method: "POST",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify({ status: "closed" }),
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
              setFeedback(ticketsFeedbackEl, "Ticket konnte nicht geschlossen werden.", "error");
              return;
            }
            setFeedback(ticketsFeedbackEl, "Ticket geschlossen.", "ok");
            await loadTickets();
          } catch (_) {
            setFeedback(ticketsFeedbackEl, "Verbindungsfehler beim Schliessen.", "error");
          } finally {
            closeBtn.disabled = false;
          }
        });
        actions.appendChild(closeBtn);
      }

      controls.appendChild(actions);
      body.appendChild(controls);
      wrap.appendChild(body);
      return wrap;
    };

    async function loadTickets() {
      listEl.innerHTML = '<div class="gc-support-empty">Tickets werden geladen...</div>';
      try {
        const res = await fetch("/api/support/tickets", {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          listEl.innerHTML = '<div class="gc-support-empty">Support ist aktuell nicht verfuegbar.</div>';
          return;
        }
        const tickets = (data.data && data.data.tickets) || [];
        if (!tickets.length) {
          listEl.innerHTML = '<div class="gc-support-empty">Noch keine Tickets vorhanden.</div>';
          return;
        }
        listEl.innerHTML = "";
        tickets.forEach((ticket) => listEl.appendChild(createTicketNode(ticket)));
      } catch (_) {
        listEl.innerHTML = '<div class="gc-support-empty">Tickets konnten nicht geladen werden.</div>';
      }
    }

    if (form && subjectEl && categoryEl && priorityEl && messageEl) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {
          subject: subjectEl.value || "",
          category: categoryEl.value || "general",
          priority: priorityEl.value || "normal",
          message: messageEl.value || "",
        };
        if (!String(payload.subject).trim() || !String(payload.message).trim()) {
          setFeedback(createFeedbackEl, "Bitte Betreff und Nachricht ausfuellen.", "error");
          return;
        }
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        try {
          const res = await fetch("/api/support/tickets", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify(payload),
          });
          const data = await res.json();
          if (!res.ok || !data.ok) {
            setFeedback(createFeedbackEl, "Ticket konnte nicht erstellt werden.", "error");
            return;
          }
          setFeedback(createFeedbackEl, "Ticket erfolgreich erstellt.", "ok");
          form.reset();
          if (priorityEl) priorityEl.value = "normal";
        } catch (_) {
          setFeedback(createFeedbackEl, "Verbindungsfehler beim Senden.", "error");
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    }

    if (openTicketsBtn) {
      openTicketsBtn.addEventListener("click", () => {
        openSpecialWindow("my-tickets");
        loadTickets();
      });
    }

    if (refreshBtn) refreshBtn.addEventListener("click", () => loadTickets());

    document.querySelectorAll("[data-special-open-window='my-tickets']").forEach((btn) => {
      btn.addEventListener("click", () => {
        setTimeout(() => loadTickets(), 0);
      });
    });
  }

  function initStickyResourceBar() {
    const sticky = document.querySelector(".gc-resource-sticky");
    if (!sticky) return;

    const mq = window.matchMedia("(max-width: 768px)");
    let ticking = false;

    function update() {
      ticking = false;
      if (!mq.matches) {
        sticky.classList.remove("is-scrolled");
        return;
      }
      sticky.classList.toggle("is-scrolled", window.scrollY > 8);
    }

    function onScroll() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(update);
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    mq.addEventListener("change", update);
    update();
  }

  // =========================
  // Player Card (global modal, PJAX-safe)
  // =========================
  const PLAYER_CARD = {
    root: null,
    dialog: null,
    content: null,
    loadingEl: null,
    errorEl: null,
    abort: null,
    open: false,
    currentId: null,
    mode: "view",
    reqId: 0,
  };

  function cachePlayerCardElements() {
    if (PLAYER_CARD.root && PLAYER_CARD.content) return PLAYER_CARD.root;
    PLAYER_CARD.root = document.getElementById("gc-player-card-root");
    if (!PLAYER_CARD.root) return null;
    PLAYER_CARD.dialog = PLAYER_CARD.root.querySelector(".gc-player-card-dialog");
    PLAYER_CARD.content = PLAYER_CARD.root.querySelector("[data-pc-content]");
    PLAYER_CARD.loadingEl = PLAYER_CARD.root.querySelector("[data-pc-loading]");
    PLAYER_CARD.errorEl = PLAYER_CARD.root.querySelector("[data-pc-error]");
    return PLAYER_CARD.root;
  }

  function pcSetLoading(on) {
    cachePlayerCardElements();
    const show = !!on;
    if (PLAYER_CARD.loadingEl) {
      PLAYER_CARD.loadingEl.hidden = !show;
      PLAYER_CARD.loadingEl.setAttribute("aria-hidden", show ? "false" : "true");
    }
    if (show && PLAYER_CARD.errorEl) {
      PLAYER_CARD.errorEl.hidden = true;
      PLAYER_CARD.errorEl.textContent = "";
    }
    if (PLAYER_CARD.root) {
      PLAYER_CARD.root.classList.toggle("is-loading", show);
      PLAYER_CARD.root.setAttribute("aria-busy", show ? "true" : "false");
    }
  }

  function pcSetError(msg) {
    cachePlayerCardElements();
    pcSetLoading(false);
    if (PLAYER_CARD.content) PLAYER_CARD.content.innerHTML = "";
    if (PLAYER_CARD.errorEl) {
      PLAYER_CARD.errorEl.textContent = msg || t("playercard_load_error", "Profil konnte nicht geladen werden.");
      PLAYER_CARD.errorEl.hidden = false;
      PLAYER_CARD.errorEl.setAttribute("aria-hidden", "false");
    }
  }

  function pcClearError() {
    cachePlayerCardElements();
    if (PLAYER_CARD.errorEl) {
      PLAYER_CARD.errorEl.hidden = true;
      PLAYER_CARD.errorEl.textContent = "";
      PLAYER_CARD.errorEl.setAttribute("aria-hidden", "true");
    }
  }

  function pcAbortFetch() {
    if (PLAYER_CARD.abort) {
      try { PLAYER_CARD.abort.abort(); } catch (_) {}
      PLAYER_CARD.abort = null;
    }
  }

  function pcResetModalState() {
    cachePlayerCardElements();
    pcAbortFetch();
    pcSetLoading(false);
    pcClearError();
    if (PLAYER_CARD.content) PLAYER_CARD.content.innerHTML = "";
    if (PLAYER_CARD.dialog) {
      PLAYER_CARD.dialog.setAttribute("data-theme", "cyan");
    }
    PLAYER_CARD.mode = "view";
  }

  function openPlayerCardModal(focusClose) {
    const root = cachePlayerCardElements();
    if (!root) return;
    root.hidden = false;
    root.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-player-card-open");
    PLAYER_CARD.open = true;
    if (focusClose) {
      const closeBtn = root.querySelector(".gc-player-card-close");
      if (closeBtn) closeBtn.focus({ preventScroll: true });
    }
  }

  function closePlayerCardModal() {
    const root = cachePlayerCardElements();
    if (!root) return;
    pcResetModalState();
    root.hidden = true;
    root.setAttribute("aria-hidden", "true");
    document.body.classList.remove("gc-player-card-open");
    PLAYER_CARD.open = false;
    PLAYER_CARD.currentId = null;
  }

  function applyPlayerCardTheme(theme) {
    cachePlayerCardElements();
    if (!PLAYER_CARD.dialog) return;
    const th = String(theme || "cyan");
    PLAYER_CARD.dialog.setAttribute("data-theme", th);
  }

  async function fetchPlayerCardHtml(url, reqToken) {
    pcAbortFetch();
    const ctrl = new AbortController();
    PLAYER_CARD.abort = ctrl;
    try {
      const res = await fetch(url, {
        method: "GET",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "text/html",
        },
        signal: ctrl.signal,
      });
      if (reqToken !== PLAYER_CARD.reqId) {
        return { ok: false, aborted: true };
      }
      const html = await res.text();
      if (reqToken !== PLAYER_CARD.reqId) {
        return { ok: false, aborted: true };
      }
      if (!res.ok) {
        return { ok: false, html, status: res.status };
      }
      return { ok: true, html, status: res.status };
    } catch (e) {
      if (e && e.name === "AbortError") {
        return { ok: false, aborted: true };
      }
      throw e;
    } finally {
      if (PLAYER_CARD.abort === ctrl) PLAYER_CARD.abort = null;
    }
  }

  function mountPlayerCardHtml(html, mode) {
    cachePlayerCardElements();
    if (!PLAYER_CARD.content) return;
    pcClearError();
    pcSetLoading(false);
    PLAYER_CARD.mode = mode || "view";

    const wrap = document.createElement("div");
    wrap.innerHTML = html;
    const shell = wrap.querySelector(".gc-player-card-shell");
    PLAYER_CARD.content.innerHTML = "";
    if (shell) {
      PLAYER_CARD.content.appendChild(shell);
      applyPlayerCardTheme(shell.getAttribute("data-theme"));
    } else {
      PLAYER_CARD.content.appendChild(wrap);
    }
    bindPlayerCardInnerActions();
  }

  function pcPrepareOpen(playerId, mode) {
    const pid = Number(playerId);
    if (!Number.isFinite(pid) || pid <= 0) return false;
    const wasOpen = PLAYER_CARD.open;
    PLAYER_CARD.reqId += 1;
    PLAYER_CARD.currentId = pid;
    PLAYER_CARD.mode = mode || "view";
    pcResetModalState();
    openPlayerCardModal(!wasOpen);
    pcSetLoading(true);
    return true;
  }

  async function loadPlayerCardView(playerId) {
    if (!pcPrepareOpen(playerId, "view")) return;
    const reqToken = PLAYER_CARD.reqId;
    try {
      const result = await fetchPlayerCardHtml(`/api/player-card/${playerId}`, reqToken);
      if (result.aborted || reqToken !== PLAYER_CARD.reqId) return;
      if (!result.ok) {
        if (result.html && result.html.includes("gc-player-card-shell")) {
          mountPlayerCardHtml(result.html, "view");
        } else {
          pcSetError(t("playercard_load_error", "Profil konnte nicht geladen werden."));
        }
        return;
      }
      mountPlayerCardHtml(result.html, "view");
    } catch (_) {
      if (reqToken !== PLAYER_CARD.reqId) return;
      pcSetError(t("playercard_load_error", "Profil konnte nicht geladen werden."));
    }
  }

  async function loadPlayerCardEdit(playerId) {
    if (!pcPrepareOpen(playerId, "edit")) return;
    const reqToken = PLAYER_CARD.reqId;
    try {
      const result = await fetchPlayerCardHtml(`/api/player-card/${playerId}/edit`, reqToken);
      if (result.aborted || reqToken !== PLAYER_CARD.reqId) return;
      if (!result.ok) {
        const msg = result.status === 403
          ? t("playercard_forbidden", "Keine Berechtigung.")
          : t("playercard_load_error", "Profil konnte nicht geladen werden.");
        if (result.html && result.html.includes("gc-player-card-shell")) {
          mountPlayerCardHtml(result.html, "edit");
        } else {
          pcSetError(msg);
        }
        return;
      }
      mountPlayerCardHtml(result.html, "edit");
      initPlayerCardEditPreview();
    } catch (_) {
      if (reqToken !== PLAYER_CARD.reqId) return;
      pcSetError(t("playercard_load_error", "Profil konnte nicht geladen werden."));
    }
  }

  function initPlayerCardEditPreview() {
    const form = PLAYER_CARD.content?.querySelector("#gc-player-card-form");
    if (!form || form.dataset.pcPreviewBound === "1") return;
    form.dataset.pcPreviewBound = "1";

    const preview = form.querySelector("#gc-player-card-preview");
    const avatarImg = form.querySelector("#pc-preview-avatar");
    const avatarPh = form.querySelector("#pc-preview-avatar-ph");
    const titleEl = form.querySelector("#pc-preview-title");
    const bioEl = form.querySelector("#pc-preview-bio");
    const themeSel = form.querySelector('[data-pc-field="theme"]');

    function syncBadgePreview() {
      const host = form.querySelector("#pc-preview-badges");
      if (!host) return;
      host.innerHTML = "";
      const checked = form.querySelectorAll('input[name="badge_slot"]:checked');
      let n = 0;
      checked.forEach((inp) => {
        if (n >= 3) return;
        const icon = inp.getAttribute("data-pc-badge-icon") || "★";
        const name = inp.getAttribute("data-pc-badge-name") || "";
        const span = document.createElement("span");
        span.className = "gc-player-card-badge";
        span.innerHTML =
          `<span class="gc-player-card-badge-icon" aria-hidden="true">${icon}</span>` +
          `<span class="gc-player-card-badge-name">${name}</span>`;
        host.appendChild(span);
        n += 1;
      });
    }

    function syncPreview() {
      const avatarUrl = (form.querySelector('[data-pc-field="avatar_url"]')?.value || "").trim();
      if (avatarImg && avatarPh) {
        if (avatarUrl) {
          avatarImg.src = avatarUrl;
          avatarImg.hidden = false;
          avatarPh.hidden = true;
        } else {
          avatarImg.removeAttribute("src");
          avatarImg.hidden = true;
          avatarPh.hidden = false;
        }
      }
      if (titleEl) titleEl.textContent = form.querySelector('[data-pc-field="title"]')?.value || "";
      if (bioEl) bioEl.textContent = form.querySelector('[data-pc-field="bio"]')?.value || "";
      const th = themeSel?.value || "cyan";
      if (preview) preview.setAttribute("data-theme", th);
      applyPlayerCardTheme(th);
      syncBadgePreview();
    }

    form.querySelectorAll("[data-pc-field]").forEach((el) => {
      el.addEventListener("input", syncPreview);
      el.addEventListener("change", syncPreview);
    });
    form.querySelectorAll('input[name="badge_slot"]').forEach((el) => {
      el.addEventListener("change", () => {
        const checked = form.querySelectorAll('input[name="badge_slot"]:checked');
        if (checked.length > 3) el.checked = false;
        syncBadgePreview();
      });
    });
    syncPreview();
  }

  async function savePlayerCardForm(form) {
    const msgEl = form.querySelector("[data-pc-form-msg]");
    const saveBtn = form.querySelector("[data-pc-save]");
    const badges = Array.from(form.querySelectorAll('input[name="badge_slot"]:checked'))
      .slice(0, 3)
      .map((inp) => inp.value);

    const payload = {
      avatar_url: form.querySelector('[name="avatar_url"]')?.value || "",
      title: form.querySelector('[name="title"]')?.value || "",
      bio: form.querySelector('[name="bio"]')?.value || "",
      theme: form.querySelector('[name="theme"]')?.value || "cyan",
      is_public: form.querySelector('[name="is_public"]')?.checked ? "1" : "0",
      selected_badge_1: badges[0] || null,
      selected_badge_2: badges[1] || null,
      selected_badge_3: badges[2] || null,
    };

    if (msgEl) { msgEl.hidden = true; msgEl.textContent = ""; }
    if (saveBtn) saveBtn.disabled = true;
    pcSetLoading(true);

    try {
      const res = await fetch("/api/player-card/me", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      pcSetLoading(false);
      if (!data.ok) {
        const key = data.reason || "playercard_save_error";
        const txt = t(key, t("playercard_save_error", "Speichern fehlgeschlagen."));
        if (msgEl) { msgEl.textContent = txt; msgEl.hidden = false; }
        showNotify(txt, "error");
        return;
      }
      showNotify(t("playercard_save_success", "Profil gespeichert."), "success");
      if (data.html) mountPlayerCardHtml(data.html, "view");
      if (data.card && typeof GC.syncPlayerAvatarVisuals === "function") {
        GC.syncPlayerAvatarVisuals(data.card);
      }
    } catch (_) {
      pcSetLoading(false);
      const txt = t("playercard_save_error", "Speichern fehlgeschlagen.");
      if (msgEl) { msgEl.textContent = txt; msgEl.hidden = false; }
      showNotify(txt, "error");
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function bindPlayerCardInnerActions() {
    cachePlayerCardElements();
    if (!PLAYER_CARD.content) return;

    const editBtn = PLAYER_CARD.content.querySelector("[data-pc-edit]");
    if (editBtn && editBtn.dataset.pcBound !== "1") {
      editBtn.dataset.pcBound = "1";
      editBtn.addEventListener("click", (e) => {
        e.preventDefault();
        const pid = editBtn.getAttribute("data-player-id") || PLAYER_CARD.currentId;
        loadPlayerCardEdit(pid);
      });
    }

    const form = PLAYER_CARD.content.querySelector("#gc-player-card-form");
    if (form && form.dataset.pcBound !== "1") {
      form.dataset.pcBound = "1";
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        savePlayerCardForm(form);
      });
      const cancel = form.querySelector("[data-pc-cancel]");
      if (cancel) {
        cancel.addEventListener("click", (e) => {
          e.preventDefault();
          if (PLAYER_CARD.currentId) loadPlayerCardView(PLAYER_CARD.currentId);
        });
      }
      initPlayerCardEditPreview();
    }
  }

  function initPlayerCardOnce() {
    if (GC._playerCardBound) return;
    GC._playerCardBound = true;

    document.addEventListener("click", (e) => {
      const closeEl = e.target.closest("[data-pc-close]");
      if (closeEl) {
        const root = cachePlayerCardElements();
        if (root && PLAYER_CARD.open) {
          e.preventDefault();
          closePlayerCardModal();
        }
        return;
      }

      const trigger = e.target.closest("[data-player-card]");
      if (!trigger) return;
      const pid = trigger.getAttribute("data-player-id");
      if (!pid) return;
      e.preventDefault();
      e.stopPropagation();
      loadPlayerCardView(pid);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const trigger = e.target.closest("[data-player-card]");
      if (!trigger || document.activeElement !== trigger) return;
      e.preventDefault();
      loadPlayerCardView(trigger.getAttribute("data-player-id"));
    });

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (PLAYER_CARD.open) closePlayerCardModal();
    });
  }

  GC.openPlayerCard = loadPlayerCardView;
  GC.closePlayerCard = closePlayerCardModal;

  function initShellOnce() {
    if (GC._shellReady) return;
    GC._shellReady = true;

    window.GC = GC;
    bindBuildingTabsOnce();
    initForms();
    initSkipLink();
    initGameActions();
    bindPlanetEvolutionOnce();
    initVisibilityPolling();
    initMobileNav();
    initSpecialPanel();
    initSupportModule();
    initStickyResourceBar();
    initPjax();
    initPlayerCardOnce();
    if (typeof GC.initChat === "function") GC.initChat();

    document.addEventListener("click", (e) => {
      const link = e.target.closest('a.logout-btn, a[href*="/logout"]');
      if (link) GC.abortGameLoop("logout-click");
    }, true);

    try {
      history.replaceState({ gcPjax: true }, "", window.location.href);
    } catch (_) {}
  }

  // =========================
  // Boot
  // =========================
  document.addEventListener("DOMContentLoaded", () => {
    initShellOnce();
    GC.initPage();
  });
})();
