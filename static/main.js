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
    const v = Number(serverTimeSec);
    if (!Number.isFinite(v) || v <= 0) return;
    const approx = getApproxServerNow();
    if (TIME.serverNow && Number.isFinite(approx) && v + 1.0 < approx) {
      return;
    }
    TIME.serverNow = v;
    TIME.clientPerfAt = performance.now();
  }

  function bootstrapServerTimeFromDom() {
    const raw = document.body?.dataset?.serverTime;
    if (raw) setServerTime(raw);
  }

  function getApproxServerNow() {
    if (TIME.serverNow && TIME.clientPerfAt) {
      const dt = (performance.now() - TIME.clientPerfAt) / 1000;
      return TIME.serverNow + dt;
    }
    return Math.floor(Date.now() / 1000);
  }

  bootstrapServerTimeFromDom();

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

  function applyPlanetLandscapeFromState(data) {
    const url = String(data?.active_planet?.landscape_url || "").trim();
    if (!url) return;
    document.body.classList.add("gc-has-planet-landscape");
    document.body.style.setProperty("--planet-landscape", `url("${url}")`);
  }

  function getDomPlanetId() {
    const roots = [
      document.getElementById("shipyard-page"),
      document.getElementById("fleet-page"),
      document.getElementById("trader-hub-page"),
      document.getElementById("build-queue-root"),
    ];
    for (const el of roots) {
      if (!el) continue;
      const pid = Number(el.dataset.planetId || 0);
      if (pid > 0) return pid;
    }
    return 0;
  }

  let _planetPageReloadPromise = null;
  function reloadPageForActivePlanet(activePlanetId, reason) {
    if (GC.pjaxInFlight) return null;
    if (typeof GC.detectPage === "function" && GC.detectPage() === "admin") return null;
    const domPid = getDomPlanetId();
    if (!activePlanetId || !domPid || activePlanetId === domPid) return null;
    if (_planetPageReloadPromise) return _planetPageReloadPromise;
    if (typeof GC.reloadCurrentPage !== "function") return null;
    console.debug("[GC] planet page reload", { activePlanetId, domPid, reason });
    _planetPageReloadPromise = Promise.resolve(GC.reloadCurrentPage({ force: true })).finally(() => {
      _planetPageReloadPromise = null;
    });
    return _planetPageReloadPromise;
  }

  function applyActionState(json, reason) {
    if (!json) return false;
    const state = json.state || (json.data && json.data.state);
    if (!state) return false;
    const anyActive = applyGameStateData(state, reason);
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
    finishLocks: { buildings: false, research: false, planet_evolution: false },
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
      started: false,
      timeoutId: null,
      inFlight: false,
      abort: null,
      lastInterval: 0,
      backoff: 0,
      intervalActive: 3000,
      intervalIdle: 5000,
      intervalHidden: 15000,
    },
    shipyardPollMs: 5000,
    modules: {},
  };

  (function applyClientRuntimeConfig() {
    const cfg = typeof window !== "undefined" ? window.GC_CLIENT_CONFIG : null;
    if (!cfg || typeof cfg !== "object") return;
    const pol = GC.polling;
    if (Number(cfg.poll_active_ms) > 0) pol.intervalActive = Number(cfg.poll_active_ms);
    if (Number(cfg.poll_idle_ms) > 0) pol.intervalIdle = Number(cfg.poll_idle_ms);
    if (Number(cfg.poll_hidden_ms) > 0) pol.intervalHidden = Number(cfg.poll_hidden_ms);
    if (Number(cfg.shipyard_poll_ms) > 0) GC.shipyardPollMs = Number(cfg.shipyard_poll_ms);
  })();

  GC.registerCleanup = function registerCleanup(fn, opts) {
    if (typeof fn !== "function") return;
    if (opts && opts.persistent) fn._gcPersistent = true;
    GC.pageLifecycle.cleanupFns.push(fn);
  };
  // Alias used by messages.js (older name)
  GC.registerPageCleanup = GC.registerCleanup;

  GC.cleanupPage = function cleanupPage() {
    console.debug("[GC] cleanupPage");
    _clearMovementCountdownExpiryState();
    if (_movementCountdownRefreshTimer) {
      clearTimeout(_movementCountdownRefreshTimer);
      _movementCountdownRefreshTimer = null;
    }
    _movementCountdownRefreshPending.fleet = false;
    _movementCountdownRefreshPending.overview = false;
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
    stopResourceTicker();
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
    if (path.endsWith("/trader-hub")) return "trader_hub";
    if (path.endsWith("/fleet")) return "fleet";
    if (path.endsWith("/shipyard")) return "shipyard";
    if (path.endsWith("/overview") || path === "/") return "overview";
    if (path.endsWith("/ranking")) return "ranking";
    if (path.endsWith("/messages")) return "messages";
    if (path.endsWith("/options")) return "options";
    if (path.endsWith("/galaxy")) return "galaxy";
    if (path.endsWith("/techtree")) return "techtree";
    if (path.endsWith("/admin")) return "admin";
    return "other";
  };

  GC.getServerNow = getApproxServerNow;

  GC.reloadCurrentPage = function reloadCurrentPage(opts) {
    const target = `${window.location.pathname || "/"}${window.location.search || ""}`;
    if (typeof GC.navigateTo === "function") {
      return GC.navigateTo(target, { push: false, force: true, ...(opts || {}) });
    }
    window.location.reload();
    return Promise.resolve();
  };

  function hydratePageFromLastState(opts) {
    if (!GC.lastState || GC.lastState.ok !== true) return false;
    const queueRoot = document.getElementById("build-queue-root");
    const traderRoot = document.getElementById("trader-hub-page");
    const domPlanetEl = queueRoot || traderRoot;
    if (domPlanetEl && domPlanetEl.dataset.planetId) {
      const domPlanetId = Number(domPlanetEl.dataset.planetId || 0);
      const statePlanetId = Number(
        GC.lastState.active_planet_id || GC.lastState.build_queue?.planet_id || 0
      );
      if (domPlanetId > 0 && statePlanetId > 0 && domPlanetId !== statePlanetId) {
        return false;
      }
    }
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
  let _progressTickerIntervalId = null;

  GC.stopProgressTicker = function stopProgressTicker() {
    _progressTickerActive = false;
    if (_progressTickerIntervalId != null) {
      clearInterval(_progressTickerIntervalId);
      _progressTickerIntervalId = null;
    }
  };

  GC.startProgressTicker = function startProgressTicker() {
    if (!shouldRunGameLoop()) return;
    if (_progressTickerIntervalId != null) return;
    _progressTickerActive = true;
    const tick = () => {
      if (!_progressTickerActive || !shouldRunGameLoop() || _authLoopAborted) {
        GC.stopProgressTicker();
        return;
      }
      if (!_hasActiveProgressJobs()) {
        GC.stopProgressTicker();
        return;
      }
      updateAllProgressBars();
    };
    tick();
    _progressTickerIntervalId = setInterval(tick, 1000);
  };

  GC.stopPolling = function stopPolling() {
    console.debug("[GC] polling stopped");
    const p = GC.polling;
    p.running = false;
    p.started = false;
    if (p.timeoutId) {
      clearTimeout(p.timeoutId);
      p.timeoutId = null;
    }
    p.lastInterval = 0;
    try { if (p.abort) p.abort.abort(); } catch (_) {}
    p.inFlight = false;
    p.abort = null;
  };

  /** Dedicated poll timer — not registered in pageLifecycle (survives until stopPolling). */
  function scheduleGameStatePoll(ms) {
    const p = GC.polling;
    if (p.timeoutId) clearTimeout(p.timeoutId);
    p.timeoutId = setTimeout(p._pollTick || (p._pollTick = async function gameStatePollTick() {
      const pol = GC.polling;
      if (!pol.running || !shouldRunGameLoop() || _authLoopAborted) {
        GC.stopPolling();
        return;
      }
      try {
        await GC.refreshGameState("poll");
      } catch (_) {}
      if (!pol.running || !shouldRunGameLoop() || _authLoopAborted) {
        GC.stopPolling();
        return;
      }
      GC.startProgressTicker();
      const active = lastHadActiveJob || lastHadActiveResearch;
      let interval = pol.intervalIdle;
      if (active) interval = pol.intervalActive;
      if (document.hidden) interval = pol.intervalHidden;
      pol.lastInterval = interval;
      scheduleGameStatePoll(interval);
    }), Math.max(0, ms));
  }

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

    const p = GC.polling;
    let next = p.intervalIdle;
    if (anyActive) next = p.intervalActive;
    if (document.hidden) next = p.intervalHidden;
    if (p.backoff && isError) next = Math.max(next, p.backoff);

    if (p.running && p.timeoutId && !isError) {
      p.lastInterval = next;
      console.debug("[GC] polling already active", next, "ms");
      return;
    }

    GC.stopPolling();
    if (document.hidden) {
      console.debug("[GC] polling paused (hidden tab)");
      return;
    }

    p.running = true;
    p.started = true;
    p.lastInterval = next;
    console.debug("[GC] polling started", next, "ms");
    scheduleGameStatePoll(next);
  };

  GC.initPage = function initPage(opts) {
    const page = GC.detectPage();
    const force = opts && opts.force;
    const skipGameState = Boolean(opts && opts.skipGameState);

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

    const afterInit = async () => {
      bootstrapServerTimeFromDom();
      if (!skipGameState && typeof GC.refreshGameState === "function") {
        await GC.refreshGameState("page_init");
      } else if (skipGameState) {
        GC.startPolling(lastHadActiveJob || lastHadActiveResearch);
      }
      GC.startProgressTicker();
      if (typeof GC.initChat === "function") GC.initChat();
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

  function formatCountdownRemain(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const secR = s % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${secR}s`;
    return `${secR}s`;
  }

  function formatMovementCountdown(seconds, format) {
    if (format === "eta") return formatEta(seconds);
    return formatCountdownRemain(seconds);
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
      let m = 0;
      let c = 0;
      if (Array.isArray(payload)) {
        [m, c] = payload;
      } else if (payload && typeof payload === "object") {
        m = payload.metal ?? payload.deficit_metal ?? payload.cost_metal ?? 0;
        c = payload.crystal ?? payload.deficit_crystal ?? payload.cost_crystal ?? 0;
      }
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

  function renderCompactCosts(metal, crystal, targetLevel) {
    const levelLabel = t("buildings_col_level", "Level");
    const targetNote = `→ L${fmtNumber(targetLevel)}`;
    return (
      `<div class="gc-costs-compact">` +
      `<span class="gc-cost-chip gc-cost-metal"><span class="gc-res-icon gc-res-metal" aria-hidden="true"></span>` +
      `<span class="gc-cost-val">${fmtNumber(metal)}</span></span>` +
      `<span class="gc-cost-chip gc-cost-crystal"><span class="gc-res-icon gc-res-crystal" aria-hidden="true"></span>` +
      `<span class="gc-cost-val">${fmtNumber(crystal)}</span></span>` +
      `<span class="gc-cost-target" title="${levelLabel} ${fmtNumber(targetLevel)}">${targetNote}</span>` +
      `</div>`
    );
  }

  function applyBuildingRowState(row, b) {
    if (!row || !b) return;
    const isMax = (b.level >= b.max_level) || b.at_queue_max;
    row.classList.remove(
      "gc-prog-affordable",
      "gc-prog-locked",
      "gc-prog-unaffordable",
      "gc-prog-max"
    );
    if (isMax) row.classList.add("gc-prog-max");
    else if (!b.requirements_met) row.classList.add("gc-prog-locked");
    else if (!b.can_afford) row.classList.add("gc-prog-unaffordable");
    else row.classList.add("gc-prog-affordable");
  }

  function applyResearchRowState(row, tech) {
    if (!row || !tech) return;
    const locked = !tech.requirements_met;
    const unaffordable = !locked && tech.can_afford === false;
    row.classList.remove(
      "gc-prog-affordable",
      "gc-prog-locked",
      "gc-prog-unaffordable",
      "tech-row-locked"
    );
    if (locked) {
      row.classList.add("gc-prog-locked", "tech-row-locked");
    } else if (unaffordable) {
      row.classList.add("gc-prog-unaffordable");
    } else {
      row.classList.add("gc-prog-affordable");
    }
  }

  function formatResearchReqTooltip(items) {
    if (!Array.isArray(items)) return "";
    return items
      .filter((req) => !req.met)
      .map((req) => {
        const label =
          req.kind === "building"
            ? t("building_" + req.key, req.key)
            : t(req.key, req.key);
        return `${label} L${fmtNumber(req.need)}`;
      })
      .join(" · ");
  }

  function renderResearchActionCell(tech, summary) {
    const key = tech.key;
    const count = summary?.count ?? 0;
    const limit = summary?.limit ?? 3;
    const queueFull = count >= limit;
    const queueActive = count > 0;
    const btnStart = t("research_btn_start", "Forschung starten");
    const btnQueue = t("research_btn_queue", "Anreihen");
    const fullLabel = t("research_status_queue_full", "Warteschlange voll");

    if (!tech.requirements_met) {
      let lockTitle = t("research_requirements_not_met", "Voraussetzungen nicht erfüllt.");
      const reqHint = formatResearchReqTooltip(tech.requirements_items);
      if (reqHint) lockTitle += " · " + reqHint;
      return (
        `<span class="status-pill status-pill-locked status-pill-icon"` +
        ` title="${lockTitle}" aria-label="${lockTitle}">🔒</span>`
      );
    }
    if (queueFull) {
      const fullShort = t("research_status_queue_full_short", "Voll");
      return (
        `<span class="status-pill status-pill-locked status-pill-queue-full status-pill-compact"` +
        ` title="${fullLabel}">${fullShort}</span>`
      );
    }
    if (tech.can_afford === false) {
      const shortMsg = t("research_not_enough_resources", "Nicht genug Ressourcen.");
      return `<button class="gc-btn gc-btn-danger gc-btn-xs btn-research" type="button" disabled title="${shortMsg}">${btnStart}</button>`;
    }
    const label = queueActive ? btnQueue : btnStart;
    const href = `/research_start/${encodeURIComponent(key)}`;
    return `<a href="${href}" class="gc-btn gc-btn-primary gc-btn-xs btn-research">${label}</a>`;
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
      return `<button class="gc-btn gc-btn-ghost gc-btn-xs btn-upgrade" type="button" disabled title="${btnMax}">${btnMax}</button>`;
    }
    if (!b.requirements_met) {
      const lockTitle = t("msg_build_requirements", "Voraussetzungen nicht erfüllt.");
      return `<button class="gc-btn gc-btn-danger gc-btn-xs btn-upgrade status-pill-icon-btn" type="button" disabled title="${lockTitle}" aria-label="${lockTitle}">🔒</button>`;
    }
    if (!b.can_afford) {
      return `<button class="gc-btn gc-btn-danger gc-btn-xs btn-upgrade" type="button" disabled>${btnUpgrade}</button>`;
    }
    if (bqQueueFull) {
      const fullShort = t("research_status_queue_full_short", "Voll");
      return `<span class="status-pill status-pill-locked status-pill-queue-full status-pill-compact" title="${fullLabel}">${fullShort}</span>`;
    }
    const label = queueActive ? btnQueue : btnUpgrade;
    const tab = b.tab || _getActiveBuildingTab();
    const href = `/upgrade/${encodeURIComponent(key)}?src=buildings&tab=${encodeURIComponent(tab)}`;
    return `<a id="btn-${key}" data-building="${key}" href="${href}" class="gc-btn gc-btn-primary gc-btn-xs btn-upgrade">${label}</a>`;
  }

  function patchBuildingPanel(rowsByTab, buildQueueRaw) {
    if (!rowsByTab || !document.querySelector(".buildings-prog-list")) return;

    const summary = buildQueueRaw?.summary || null;
    const limit = summary?.limit ?? 3;
    const count = summary?.count ?? 0;
    const bqQueueFull = count >= limit;

    Object.values(rowsByTab).forEach((rows) => {
      (rows || []).forEach((b) => {
        const key = b.key;
        const levelEl = document.getElementById(`level-${key}`);
        if (levelEl) _setIfChanged(levelEl, fmtNumber(b.level));

        const row = document.querySelector(`[data-building-row="${key}"]`);
        if (!row) return;

        applyBuildingRowState(row, b);

        const costCell = row.querySelector(".bcell-cost");
        if (costCell) {
          const html = renderCompactCosts(b.cost_metal, b.cost_crystal, b.target_level);
          if (costCell.innerHTML.trim() !== html.trim()) costCell.innerHTML = html;
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
    const list = document.querySelector(".research-prog-list");
    if (!list || !Array.isArray(techs)) return;

    const summary = researchRaw?.summary || {};

    techs.forEach((tech) => {
      const row = document.querySelector(`[data-tech-key="${tech.key}"]`);
      if (!row) return;

      applyResearchRowState(row, tech);

      const levelEl = row.querySelector(".tech-level-current");
      if (levelEl) _setIfChanged(levelEl, fmtNumber(tech.level));

      const costCell = row.querySelector(".tech-cost-cell");
      if (costCell) {
        const html = renderCompactCosts(tech.cost_metal, tech.cost_crystal, tech.target_level);
        if (costCell.innerHTML.trim() !== html.trim()) costCell.innerHTML = html;
      }

      const timeCell = row.querySelector(".tech-time-cell");
      if (timeCell) {
        const inner = timeCell.querySelector(".tech-time") || timeCell;
        _setIfChanged(inner, formatDuration(tech.time_seconds));
      }

      const actionCell = row.querySelector(".tech-status-cell");
      if (actionCell) {
        const html = renderResearchActionCell(tech, summary);
        if (actionCell.innerHTML.trim() !== html.trim()) actionCell.innerHTML = html;
      }
    });

    const labEl = document.querySelector(".lab-level-highlight");
    if (labEl && typeof researchRaw?.lab_level !== "undefined") {
      _setIfChanged(labEl, fmtNumber(researchRaw.lab_level));
    }

    updateResearchQueueActions(researchRaw);
  }

  let _finishRefreshTimer = null;
  const _finishRefreshArmed = { buildings: false, research: false, planet_evolution: false };

  function clearFinishRefreshArmed(type, queueList) {
    const first = Array.isArray(queueList) && queueList.length ? queueList[0] : null;
    const finishAt = first ? Number(first.finish_at || first.finish_time || 0) : 0;
    const now = getApproxServerNow();
    if (!finishAt || (now && finishAt > now)) {
      _finishRefreshArmed[type] = false;
    }
  }

  function requestFinishRefresh(type) {
    if (!shouldRunGameLoop() || _authLoopAborted) return;
    const key = type === "buildings" || type === "research" || type === "planet_evolution" ? type : "buildings";
    if (_finishRefreshArmed[key] || _finishRefreshTimer) return;

    _finishRefreshTimer = GC.setSafeTimeout(() => {
      _finishRefreshTimer = null;
      _lastQueueSignature = "";
      _lastResearchQueueSignature = "";

      const run = () => {
        const refresh = () => {
          if (
            key === "planet_evolution" &&
            document.querySelector(".planet-evolution-page") &&
            typeof GC.reloadCurrentPage === "function"
          ) {
            return Promise.resolve(GC.reloadCurrentPage()).finally(() => {
              GC.finishLocks[key] = false;
            });
          }
          return Promise.resolve(GC.refreshGameState ? GC.refreshGameState(`${key}_finished`) : null).finally(() => {
            GC.finishLocks[key] = false;
          });
        };
        refresh();
      };

      if (GC.finishLocks[key]) {
        GC.setSafeTimeout(run, 150);
        return;
      }
      GC.finishLocks[key] = true;
      _finishRefreshArmed[key] = true;
      if (GC.refreshInFlight) {
        Promise.resolve(GC.refreshInFlight).finally(run);
        return;
      }
      run();
    }, 300);
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

  function patchResourceBarEnergyWarning(used, total) {
    const container = document.getElementById("energy-container");
    if (!container) return;
    const u = Math.floor(Number(used) || 0);
    const t = Math.floor(Number(total) || 0);
    container.classList.toggle("energy-warning", t > 0 && u > t);
  }

  function patchOverviewEnergyHint(overview, data) {
    const hint = document.getElementById("overview-energy-hint");
    const strip = document.getElementById("overview-energy-strip");
    if (!hint && !strip) return;

    const hintKey = overview?.energy_hint ?? overview?.status?.energy?.hint;
    const total = Math.floor(
      Number(
        data?.energy?.total ??
          overview?.status?.energy?.total ??
          data?.player?.energy_total ??
          data?.resources?.energy_total ??
          0
      )
    );
    const ratio = Number(
      data?.energy?.ratio ?? overview?.status?.energy?.ratio ?? data?.energy_ratio ?? 1
    );

    let state = hintKey;
    if (!state) {
      if (total <= 0) state = "zero";
      else if (ratio >= 1) state = "ok";
      else if (ratio >= 0.5) state = "low";
      else state = "critical";
    }

    const stateClasses = [
      "overview-energy-zero",
      "overview-energy-ok",
      "overview-energy-low",
      "overview-energy-critical",
    ];
    [hint, strip].forEach((el) => {
      if (!el) return;
      el.classList.remove(...stateClasses);
      if (state === "zero") el.classList.add("overview-energy-zero");
      else if (state === "ok") el.classList.add("overview-energy-ok");
      else if (state === "low") el.classList.add("overview-energy-low");
      else if (state === "critical") el.classList.add("overview-energy-critical");
    });
  }

  function patchOverviewStatus(overview, data, buildings, prod) {
    const status = overview?.status;
    if (status?.resources) {
      const metalPhEl = document.querySelector('[data-ph="metal"]');
      const crystalPhEl = document.querySelector('[data-ph="crystal"]');
      if (metalPhEl) {
        _setIfChanged(metalPhEl, fmtNumber(Math.floor(Number(status.resources.metal_per_hour || 0))));
      }
      if (crystalPhEl) {
        _setIfChanged(crystalPhEl, fmtNumber(Math.floor(Number(status.resources.crystal_per_hour || 0))));
      }
    } else if (prod) {
      const metalPhEl = document.querySelector('[data-ph="metal"]');
      const crystalPhEl = document.querySelector('[data-ph="crystal"]');
      if (metalPhEl) _setIfChanged(metalPhEl, fmtNumber(Math.floor(Number(prod.metal_mine || 0))));
      if (crystalPhEl) _setIfChanged(crystalPhEl, fmtNumber(Math.floor(Number(prod.crystal_mine || 0))));
    }

    patchOverviewEnergyHint(overview, data);
    patchOverviewTable(overview, buildings, prod);

    if (status?.planet?.name && typeof GC.applyOverviewPlanetName === "function") {
      const planetModal = document.getElementById("gc-planet-manage-root");
      const renameInput = document.getElementById("overview-planet-rename-input");
      const editingPlanetName =
        (planetModal && !planetModal.hidden) ||
        (renameInput && document.activeElement === renameInput);
      if (!editingPlanetName) {
        GC.applyOverviewPlanetName(status.planet.name);
      }
    }

    const actList = document.getElementById("overview-activities");
    const activities = status?.activities;
    if (!actList || !Array.isArray(activities)) return;

    const hrefFor = (key) => {
      const map = {
        build: "/buildings",
        research: "/research",
        shipyard: "/shipyard",
        fleet: "/fleet",
      };
      if (map[key]) return map[key];
      if (String(key || "").startsWith("fleet_")) return "/fleet";
      return "/overview";
    };

    const activityTypeKey = (key) => (String(key || "").startsWith("fleet_") ? "fleet" : String(key || ""));

    const activityDetailText = (act) => {
      const leg = act.status_label ? t(act.status_label, act.status_label) : "";
      const summary = act.summary || "";
      if (leg && summary) return `${leg} · ${summary}`;
      return leg || summary;
    };

    const activitySignature = (acts) => (acts || []).map((act) =>
      `${act.key}:${act.state}:${act.countdown_at || act.finish_at || 0}:${act.phase || ""}:${act.status_label || ""}:${act.label_key || ""}:${act.summary || ""}`
    ).join("|");

    const renderActivities = () => {
      actList.replaceChildren();
      actList.dataset.actSig = activitySignature(activities);
      activities.forEach((act) => {
        const li = document.createElement("li");
        li.className = `overview-activity-row overview-activity-${act.key} overview-activity-${act.state || "idle"}`;
        li.dataset.activityKey = act.key;
        const endAt = Number(act.countdown_at || act.finish_at || 0);
        if (endAt) li.dataset.finishAt = String(endAt);
        if (act.phase) li.dataset.activityPhase = String(act.phase);

        const link = document.createElement("a");
        link.className = "overview-activity-link";
        link.href = hrefFor(act.key);

        const typeSpan = document.createElement("span");
        typeSpan.className = "overview-activity-type";
        typeSpan.textContent = t(`overview_activity_${activityTypeKey(act.key)}`, act.key);

        const body = document.createElement("span");
        body.className = "overview-activity-body";

        if (act.state === "active") {
          const nameEl = document.createElement("span");
          nameEl.className = "overview-activity-name";
          nameEl.textContent = t(act.label_key, act.label_key);
          const detailEl = document.createElement("span");
          detailEl.className = "overview-activity-detail gc-mono";
          detailEl.textContent = activityDetailText(act);
          const etaEl = document.createElement("span");
          etaEl.className = "overview-activity-eta gc-mono";
          etaEl.dataset.activityEta = "1";
          if (endAt) {
            const phase = act.phase || act.state || "";
            const mvId = act.movement_id || String(act.key || "").replace(/^fleet_/, "");
            etaEl.dataset.countdownAt = String(endAt);
            etaEl.dataset.countdownScope = "overview";
            etaEl.dataset.countdownFormat = act.key.startsWith("fleet_") ? "fleet" : "eta";
            etaEl.dataset.countdownKey = `${mvId}:${phase}:${endAt}`;
            const rem = Math.max(0, Math.ceil(endAt - getApproxServerNow()));
            etaEl.textContent = act.key.startsWith("fleet_")
              ? formatCountdownRemain(rem)
              : formatEta(rem);
          } else {
            etaEl.textContent = act.remaining_display || formatEta(act.remaining || 0);
          }
          body.append(nameEl, detailEl, etaEl);
        } else {
          const idleEl = document.createElement("span");
          idleEl.className = "overview-activity-idle";
          idleEl.textContent = t(act.label_key, "Ready");
          body.appendChild(idleEl);
        }

        link.append(typeSpan, body);
        li.appendChild(link);
        actList.appendChild(li);
      });
    };

    const sig = activitySignature(activities);
    if (actList.dataset.actSig !== sig) {
      _clearMovementCountdownExpiryState();
      renderActivities();
      return;
    }

    activities.forEach((act) => {
      const row = actList.querySelector(`[data-activity-key="${act.key}"]`);
      if (!row) return;

      row.classList.remove("overview-activity-active", "overview-activity-idle");
      row.classList.add(`overview-activity-${act.state || "idle"}`);

      if (act.finish_at) row.dataset.finishAt = String(act.finish_at);
      else delete row.dataset.finishAt;

      if (act.phase) row.dataset.activityPhase = String(act.phase);
      else delete row.dataset.activityPhase;

      const etaEl = row.querySelector("[data-activity-eta]");
      const detailEl = row.querySelector(".overview-activity-detail");
      const nameEl = row.querySelector(".overview-activity-name");

      if (act.state === "active") {
        if (nameEl) _setIfChanged(nameEl, t(act.label_key, act.label_key));
        if (detailEl) _setIfChanged(detailEl, activityDetailText(act));
        const endAt = Number(act.countdown_at || act.finish_at || 0);
        if (etaEl) {
          etaEl.style.display = "";
          if (endAt) {
            const phase = act.phase || act.state || "";
            const mvId = act.movement_id || String(act.key || "").replace(/^fleet_/, "");
            etaEl.dataset.countdownAt = String(endAt);
            etaEl.dataset.countdownScope = "overview";
            etaEl.dataset.countdownFormat = act.key.startsWith("fleet_") ? "fleet" : "eta";
            etaEl.dataset.countdownKey = `${mvId}:${phase}:${endAt}`;
          } else {
            delete etaEl.dataset.countdownAt;
            delete etaEl.dataset.countdownScope;
            delete etaEl.dataset.countdownFormat;
            delete etaEl.dataset.countdownKey;
          }
        }
      } else if (etaEl) {
        etaEl.style.display = "none";
        delete etaEl.dataset.countdownAt;
        delete etaEl.dataset.countdownScope;
        delete etaEl.dataset.countdownFormat;
        delete etaEl.dataset.countdownKey;
      }
    });
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
    orbital_shipyard: { levelId: "level-orbital_shipyard", statusId: "status-orbital_shipyard", btnId: "btn-orbital_shipyard" },
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
    orbital_shipyard: "Orbitalwerft",
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

  const SHIPYARDQ = {
    active: {
      finishTime: 0,
      totalSeconds: 0,
    },
  };

  function _hasLiveCountdownAt() {
    const now = getApproxServerNow();
    for (const el of document.querySelectorAll("[data-countdown-at]")) {
      const at = Number(el.dataset.countdownAt || 0);
      if (at > now) return true;
    }
    return false;
  }

  function _hasActiveProgressJobs() {
    const now = getApproxServerNow();
    const buildFinish = BUILDQ.active.finishTime > now;
    const researchFinish = RESEARCHQ.active.finishTime > now;
    const shipyardFinish = SHIPYARDQ.active.finishTime > now;
    return (
      buildFinish ||
      researchFinish ||
      shipyardFinish ||
      !!document.querySelector(".build-job.build-job-active") ||
      !!document.querySelector(".research-job.research-job-active") ||
      !!document.querySelector(".shipyard-job.shipyard-job-active") ||
      !!document.getElementById("overview-research-active") ||
      !!document.querySelector(".planet-evolution-page .pe-planet-research-active") ||
      _hasLiveCountdownAt()
    );
  }

  // progress ticker: GC.startProgressTicker / GC.stopProgressTicker

  // =========================
  // Build-Queue panel render
  // - minimal re-render via signature
  // - BUT live progress runs independently
  // =========================
  let _lastQueueSignature = "";

  function _queueSignature(queueList, summary, planetId) {
    try {
      const pid = Number(planetId || 0);
      const count = summary?.count ?? (queueList?.length ?? 0);
      const items = (queueList || [])
        .map((j) => `${j.id || j.building_type}:${j.target_level}:${j.finish_time || 0}`)
        .join("|");
      return `${pid}|${count}|${items}`;
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
    const list = document.querySelector(".research-prog-list");
    if (!list) return;

    const summary = researchRaw?.summary || null;
    const count = summary?.count ?? (Array.isArray(researchRaw?.queue) ? researchRaw.queue.length : 0);
    const limit = summary?.limit ?? 3;
    const queueFull = count >= limit;
    const fullLabel = t("research_status_queue_full", "Warteschlange voll");
    const queueActive = count > 0;
    const btnStart = t("research_btn_start", "Forschung starten");
    const btnQueue = t("research_btn_queue", "Anreihen");

    list.querySelectorAll(".tech-status-cell[data-tech-key]").forEach((cell) => {
      const pillLocked = cell.querySelector(".status-pill-locked:not(.status-pill-queue-full)");
      if (pillLocked) return;

      const link = cell.querySelector("a.btn-research");
      const pillFull = cell.querySelector(".status-pill-queue-full");

      if (queueFull) {
        if (!pillFull) {
          const fullShort = t("research_status_queue_full_short", "Voll");
          cell.innerHTML =
            `<span class="status-pill status-pill-locked status-pill-queue-full status-pill-compact" title="${fullLabel}">${fullShort}</span>`;
        }
        return;
      }

      if (pillFull) {
        const techKey = cell.dataset.techKey;
        const href = `/research_start/${encodeURIComponent(techKey)}`;
        const label = queueActive ? btnQueue : btnStart;
        cell.innerHTML =
          `<a href="${href}" class="gc-btn gc-btn-primary gc-btn-xs btn-research">${label}</a>`;
        return;
      }

      if (link) {
        const label = queueActive ? btnQueue : btnStart;
        if (link.textContent !== label) link.textContent = label;
      }
    });
  }

  function updateBuildQueueActions(buildQueueRaw) {
    if (!document.querySelector(".buildings-prog-list")) return;

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

    document.querySelectorAll(".buildings-prog-list .bcell-action[data-building]").forEach((cell) => {
      if (cell.querySelector("button.btn-upgrade[disabled]")) return;

      const bType = cell.dataset.building;
      if (!bType) return;

      const link = cell.querySelector("a.btn-upgrade");
      const pill = cell.querySelector(".status-pill-queue-full");

      if (queueFull) {
        if (cell.querySelector("button.btn-upgrade[disabled]")) return;
        if (!cell.querySelector(".status-pill-queue-full")) {
          const fullShort = t("research_status_queue_full_short", "Voll");
          cell.innerHTML =
            `<span class="status-pill status-pill-locked status-pill-queue-full status-pill-compact" title="${fullLabel}">${fullShort}</span>`;
        }
        return;
      }

      if (pill) {
        const href = `/upgrade/${encodeURIComponent(bType)}?src=buildings&tab=${encodeURIComponent(tab)}`;
        cell.innerHTML =
          `<a id="btn-${bType}" data-building="${bType}" href="${href}"` +
          ` class="gc-btn gc-btn-primary gc-btn-xs btn-upgrade">${btnLabel}</a>`;
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
    let queuePlanetId = Number(buildQueueRaw?.planet_id || root.dataset.planetId || 0);

    if (!buildQueueRaw) {
      queueList = [];
    } else if (Array.isArray(buildQueueRaw)) {
      queueList = buildQueueRaw;
    } else if (Array.isArray(buildQueueRaw.queue)) {
      queueList = buildQueueRaw.queue;
      summary = buildQueueRaw.summary || null;
      queuePlanetId = Number(buildQueueRaw.planet_id || queuePlanetId || 0);
    }

    if (queuePlanetId > 0) {
      root.dataset.planetId = String(queuePlanetId);
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

    const sig = _queueSignature(queueList, summary, queuePlanetId);
    const count = summary?.count ?? queueList.length;
    const limit = summary?.limit ?? 3;
    const firstEta =
      typeof summary?.first_finish_in !== "undefined"
        ? formatEta(summary.first_finish_in)
        : formatEta(first?.remaining ?? 0);

    if (sig === _lastQueueSignature) {
      const overdue =
        first &&
        first.finish_time &&
        Number(first.finish_time) <= getApproxServerNow();
      if (!overdue) {
        _updateBuildQueueSubtitle(count, limit, firstEta);
        GC.startProgressTicker();
        return;
      }
    }
    _lastQueueSignature = sig;

    if (!queueList || queueList.length === 0) {
      _updateBuildQueueSubtitle(0, limit, firstEta);
      _finishRefreshArmed.buildings = false;
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
      const iconSrc = buildingIconUrl(bType);
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
    clearFinishRefreshArmed("buildings", queueList);
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
      const finishTime = first ? Number(first.finish_at || first.finish_time || 0) : 0;
      const overdue = finishTime > 0 && finishTime <= getApproxServerNow();
      if (!overdue) {
        _updateResearchQueueSubtitle(count, limit, firstEta);
        GC.startProgressTicker();
        return;
      }
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
    clearFinishRefreshArmed("research", queueList);
    GC.startProgressTicker();
  }

  function _applyProgressFill(fillEl, pct) {
    if (!fillEl) return;
    const clamped = Math.max(0, Math.min(100, pct));
    fillEl.style.width = `${clamped}%`;
    fillEl.setAttribute("aria-valuenow", String(Math.round(clamped)));
  }

  function updatePlanetEvolutionResearchProgress(serverNow) {
    const now = serverNow ?? getApproxServerNow();
    let overdue = false;
    document.querySelectorAll(".planet-evolution-page .pe-planet-research-active").forEach((peActive) => {
      const finishTime = Number(peActive.dataset.finishTime || 0);
      const total = Math.max(1, Number(peActive.dataset.total || 1));
      if (!finishTime) return;
      const remaining = Math.max(0, finishTime - now);
      const pct = Math.max(0, Math.min(100, 100 * (1 - remaining / total)));
      const fill = peActive.querySelector(".pe-planet-research-fill");
      const etaEl = peActive.querySelector("[data-pe-research-eta]");
      const pctEl = peActive.querySelector("[data-pe-research-pct]");
      if (fill) _applyProgressFill(fill, pct);
      if (etaEl) _setIfChanged(etaEl, formatEta(Math.ceil(remaining)));
      if (pctEl) _setIfChanged(pctEl, `${Math.round(pct)}%`);
      if (remaining <= 0) overdue = true;
    });
    if (overdue) {
      document.querySelectorAll(".planet-evolution-page .pe-planet-research-fill").forEach((fill) => {
        _applyProgressFill(fill, 100);
      });
      requestFinishRefresh("planet_evolution");
    }
  }

  const _movementCountdownRefreshPending = { fleet: false, overview: false };
  const _movementCountdownExpiryState = new Map();
  let _movementCountdownRefreshTimer = null;
  let _lastGlobalMovementExpiryRefreshMs = 0;
  let _queuedChainRefreshReason = null;

  const MOVEMENT_EXPIRY_REFRESH_MS = 5000;

  function _movementCountdownKey(el) {
    return String(el.dataset.countdownKey || `${el.dataset.countdownScope || ""}:${el.dataset.countdownAt || ""}`);
  }

  function _clearMovementCountdownExpiryState() {
    _movementCountdownExpiryState.clear();
    _lastGlobalMovementExpiryRefreshMs = 0;
  }

  function _movementExpiryCooldownMs(key) {
    const staleHits = _movementCountdownExpiryState.get(`${key}:stale`) || 0;
    if (staleHits >= 3) return MOVEMENT_EXPIRY_REFRESH_MS * 4;
    if (staleHits >= 1) return MOVEMENT_EXPIRY_REFRESH_MS * 2;
    return MOVEMENT_EXPIRY_REFRESH_MS;
  }

  function _shouldRefreshExpiredCountdown(key) {
    const nowMs = Date.now();
    if (nowMs - _lastGlobalMovementExpiryRefreshMs < MOVEMENT_EXPIRY_REFRESH_MS) return false;
    const last = _movementCountdownExpiryState.get(key) || 0;
    const cooldown = _movementExpiryCooldownMs(key);
    if (nowMs - last < cooldown) return false;
    _movementCountdownExpiryState.set(key, nowMs);
    return true;
  }

  function _noteMovementCountdownStillStale(key) {
    const hits = (_movementCountdownExpiryState.get(`${key}:stale`) || 0) + 1;
    _movementCountdownExpiryState.set(`${key}:stale`, hits);
  }

  function _clearMovementCountdownStale(key) {
    _movementCountdownExpiryState.delete(`${key}:stale`);
  }

  function requestMovementCountdownRefresh(scope) {
    if (!shouldRunGameLoop() || _authLoopAborted) return;
    const pendingKey = scope === "fleet" ? "fleet" : "overview";
    if (_movementCountdownRefreshPending[pendingKey]) return;

    if (_movementCountdownRefreshTimer) {
      clearTimeout(_movementCountdownRefreshTimer);
      _movementCountdownRefreshTimer = null;
    }

    _movementCountdownRefreshTimer = GC.setSafeTimeout(() => {
      _movementCountdownRefreshTimer = null;
      if (_movementCountdownRefreshPending[pendingKey]) return;
      _movementCountdownRefreshPending[pendingKey] = true;
      _lastGlobalMovementExpiryRefreshMs = Date.now();

      const staleKeys = [];
      document.querySelectorAll("[data-countdown-at]").forEach((el) => {
        const countdownAt = Number(el.dataset.countdownAt || 0);
        if (!countdownAt) return;
        const remaining = Math.max(0, Math.ceil(countdownAt - getApproxServerNow()));
        if (remaining <= 0) staleKeys.push(_movementCountdownKey(el));
      });

      const fleetPage = document.getElementById("fleet-page");
      let refreshPromise;
      if (pendingKey === "fleet" && fleetPage && typeof GC.refreshFleetState === "function") {
        fleetPage.dataset.fleetRefreshBusy = "1";
        refreshPromise = GC.refreshFleetState(fleetPage).finally(() => {
          delete fleetPage.dataset.fleetRefreshBusy;
        });
      } else if (typeof GC.refreshGameState === "function") {
        refreshPromise = GC.refreshGameState("fleet_countdown_expired");
      } else {
        refreshPromise = Promise.resolve();
      }

      Promise.resolve(refreshPromise).finally(() => {
        _movementCountdownRefreshPending[pendingKey] = false;
        staleKeys.forEach((key) => {
          let stillStale = false;
          document.querySelectorAll("[data-countdown-at]").forEach((el) => {
            if (_movementCountdownKey(el) !== key) return;
            const countdownAt = Number(el.dataset.countdownAt || 0);
            if (!countdownAt) return;
            if (Math.max(0, Math.ceil(countdownAt - getApproxServerNow())) <= 0) stillStale = true;
          });
          if (stillStale) _noteMovementCountdownStillStale(key);
          else _clearMovementCountdownStale(key);
        });
      });
    }, 300);
  }

  function updateMovementCountdowns(serverNow) {
    const now = Number.isFinite(serverNow) ? serverNow : getApproxServerNow();
    let fleetExpired = false;
    let overviewExpired = false;

    document.querySelectorAll("[data-countdown-at]").forEach((el) => {
      const countdownAt = Number(el.dataset.countdownAt || 0);
      if (!countdownAt) return;
      const remaining = Math.max(0, Math.ceil(countdownAt - now));
      _setIfChanged(el, formatMovementCountdown(remaining, el.dataset.countdownFormat || "fleet"));
      const scope = el.dataset.countdownScope || "";
      const key = _movementCountdownKey(el);
      if (remaining <= 0) {
        if (!_shouldRefreshExpiredCountdown(key)) return;
        if (scope === "fleet") fleetExpired = true;
        else if (scope === "overview") overviewExpired = true;
      } else {
        _movementCountdownExpiryState.delete(key);
        _clearMovementCountdownStale(key);
      }
    });

    if (fleetExpired) requestMovementCountdownRefresh("fleet");
    if (overviewExpired) requestMovementCountdownRefresh("overview");
  }

  function updateAllProgressBars() {
    const serverNow = getApproxServerNow();

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

    const shipyardActive = document.querySelector(".shipyard-job.shipyard-job-active");
    if (shipyardActive) {
      const orderFinish = Number(shipyardActive.getAttribute("data-finish-time") || 0);
      const nextUnitFinish = Number(shipyardActive.getAttribute("data-next-finish-time") || 0);
      const total = Math.max(1, Number(shipyardActive.getAttribute("data-total") || 1));
      if (orderFinish) {
        const orderRemaining = Math.max(0, orderFinish - serverNow);
        const pct = 100 * (1 - orderRemaining / total);
        const etaEl = document.getElementById("shipyard-eta-live");
        const fillEl = document.getElementById("shipyard-bar-fill-live");
        if (etaEl) _setIfChanged(etaEl, formatEta(Math.ceil(orderRemaining)));
        _applyProgressFill(fillEl, pct);
        const subEta = document.getElementById("shipyard-queue-subtitle-eta");
        if (subEta) _setIfChanged(subEta, formatEta(Math.ceil(orderRemaining)));
        if (nextUnitFinish > 0 && nextUnitFinish <= serverNow) {
          const unitKey = `${shipyardActive.dataset.queueJobId || ""}:${nextUnitFinish}`;
          if (_shipyardUnitFinishKey !== unitKey) {
            _shipyardUnitFinishKey = unitKey;
            scheduleShipyardRefreshFromState(true);
          }
        } else if (orderRemaining <= 0) {
          scheduleShipyardRefreshFromState(true);
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

    updateMovementCountdowns(serverNow);

    if (isOverviewPage) {
      document.querySelectorAll("#overview-activities .overview-activity-row[data-finish-at]").forEach((row) => {
        const etaEl = row.querySelector("[data-activity-eta]");
        if (!etaEl || etaEl.dataset.countdownAt) return;
        const finishAt = Number(row.dataset.finishAt || 0);
        if (!finishAt) return;
        const remaining = Math.max(0, finishAt - serverNow);
        _setIfChanged(etaEl, formatEta(Math.ceil(remaining)));
        if (remaining <= 0) {
          const actKey = String(row.dataset.activityKey || "");
          if (actKey === "build") requestFinishRefresh("buildings");
          else if (actKey === "research") requestFinishRefresh("research");
          else if (actKey === "shipyard") requestFinishRefresh("shipyard");
          else if (!actKey.startsWith("fleet")) requestFinishRefresh("planet_evolution");
        }
      });
    }

    updatePlanetEvolutionResearchProgress(serverNow);
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

  /** Client-side resource projection for the active planet (synced on each game-state). */
  const _resourceLive = {
    planetId: 0,
    syncedAt: 0,
    metal: 0,
    crystal: 0,
    fuelCells: 0,
    prodMetal: 0,
    prodCrystal: 0,
    prodFuelCells: 0,
    capMetal: 0,
    capCrystal: 0,
  };
  let _resourceTickerId = null;
  let _resourceDisplay = { metal: null, crystal: null, fuelCells: null };

  function patchLiveResourceAmounts(metal, crystal, fuelCells) {
    const m = Math.max(0, Math.floor(Number(metal) || 0));
    const c = Math.max(0, Math.floor(Number(crystal) || 0));
    const f = Math.max(0, Math.floor(Number(fuelCells) || 0));
    if (_resourceDisplay.metal !== m) {
      document.querySelectorAll(".res-value.metal, [data-res=\"metal\"]").forEach((el) => {
        _setIfChanged(el, fmtNumber(m));
      });
      _resourceDisplay.metal = m;
    }
    if (_resourceDisplay.crystal !== c) {
      document.querySelectorAll(".res-value.crystal, [data-res=\"crystal\"]").forEach((el) => {
        _setIfChanged(el, fmtNumber(c));
      });
      _resourceDisplay.crystal = c;
    }
    if (_resourceDisplay.fuelCells !== f) {
      document.querySelectorAll(".res-value.fuel_cells, [data-res=\"fuel_cells\"]").forEach((el) => {
        _setIfChanged(el, fmtNumber(f));
      });
      _resourceDisplay.fuelCells = f;
    }
    const ovMetalVal = document.querySelector('#overview-metal-val .gc-val[data-res="metal"]');
    const ovCryVal = document.querySelector('#overview-crystal-val .gc-val[data-res="crystal"]');
    if (ovMetalVal) _setIfChanged(ovMetalVal, fmtNumber(m));
    if (ovCryVal) _setIfChanged(ovCryVal, fmtNumber(c));
  }

  function syncResourceLiveBaseline(snapshot) {
    if (!snapshot || !snapshot.planetId) return;
    const planetId = Number(snapshot.planetId);
    if (!Number.isFinite(planetId) || planetId <= 0) return;
    _resourceLive.planetId = planetId;
    _resourceLive.syncedAt = getApproxServerNow();
    _resourceLive.metal = Math.max(0, Math.floor(Number(snapshot.metal) || 0));
    _resourceLive.crystal = Math.max(0, Math.floor(Number(snapshot.crystal) || 0));
    _resourceLive.fuelCells = Math.max(0, Math.floor(Number(snapshot.fuelCells) || 0));
    _resourceLive.prodMetal = Math.max(0, Math.floor(Number(snapshot.prodMetal) || 0));
    _resourceLive.prodCrystal = Math.max(0, Math.floor(Number(snapshot.prodCrystal) || 0));
    _resourceLive.prodFuelCells = Math.max(0, Math.floor(Number(snapshot.prodFuelCells) || 0));
    _resourceLive.capMetal = Math.max(0, Math.floor(Number(snapshot.storageMetal) || 0));
    _resourceLive.capCrystal = Math.max(0, Math.floor(Number(snapshot.storageCrystal) || 0));
    _resourceDisplay = { metal: null, crystal: null, fuelCells: null };
    patchLiveResourceAmounts(_resourceLive.metal, _resourceLive.crystal, _resourceLive.fuelCells);
    startResourceTicker();
  }

  function projectLiveResourceAmounts(nowSec) {
    if (!_resourceLive.planetId || !_resourceLive.syncedAt) return null;
    const elapsed = Math.max(0, Number(nowSec) - _resourceLive.syncedAt);
    if (elapsed <= 0) {
      return {
        metal: _resourceLive.metal,
        crystal: _resourceLive.crystal,
        fuelCells: _resourceLive.fuelCells,
      };
    }
    const hours = elapsed / 3600;
    const capM = _resourceLive.capMetal > 0 ? _resourceLive.capMetal : Number.MAX_SAFE_INTEGER;
    const capC = _resourceLive.capCrystal > 0 ? _resourceLive.capCrystal : Number.MAX_SAFE_INTEGER;
    return {
      metal: Math.min(capM, Math.floor(_resourceLive.metal + _resourceLive.prodMetal * hours)),
      crystal: Math.min(capC, Math.floor(_resourceLive.crystal + _resourceLive.prodCrystal * hours)),
      fuelCells: Math.floor(_resourceLive.fuelCells + _resourceLive.prodFuelCells * hours),
    };
  }

  function tickLiveResourceBar() {
    if (!shouldRunGameLoop() || _authLoopAborted || !_resourceLive.planetId) return;
    const projected = projectLiveResourceAmounts(getApproxServerNow());
    if (!projected) return;
    patchLiveResourceAmounts(projected.metal, projected.crystal, projected.fuelCells);
  }

  function startResourceTicker() {
    if (!shouldRunGameLoop() || _authLoopAborted || !_resourceLive.planetId) return;
    if (_resourceTickerId != null) return;
    tickLiveResourceBar();
    _resourceTickerId = setInterval(tickLiveResourceBar, 1000);
  }

  function stopResourceTicker() {
    if (_resourceTickerId != null) {
      clearInterval(_resourceTickerId);
      _resourceTickerId = null;
    }
    _resourceLive.planetId = 0;
    _resourceLive.syncedAt = 0;
    _resourceDisplay = { metal: null, crystal: null, fuelCells: null };
  }

  GC.syncResourceLiveBaseline = syncResourceLiveBaseline;
  GC.tickLiveResourceBar = tickLiveResourceBar;

  // Keep last values to avoid DOM churn
  const _last = {
    metal: null,
    crystal: null,
    fuelCells: null,
    energyUsed: null,
    energyTotal: null,
    storageMetal: null,
    storageCrystal: null,
    prodMetal: null,
    prodCrystal: null,
    prodFuelCells: null,
    activePlanetId: null,
  };

  const BUILDING_ICON_FILE = {
    orbital_shipyard: "shipyard",
    fuel_cell_plant: "solar_plant",
  };

  function buildingIconUrl(buildingType) {
    const key = String(buildingType || "").trim();
    const file = BUILDING_ICON_FILE[key] || key;
    return `/static/img/buildings/${file}.png`;
  }

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
      const hudOnly = Boolean(opts && opts.hudOnly);
      const forceResourceBar = Boolean(opts && (opts.forceResourceBar || hudOnly));

      if (data.server_time) setServerTime(data.server_time);

      const activePlanetId = Number(data.active_planet_id || data.build_queue?.planet_id || 0);
      if (!hudOnly) {
        if (
          _last.activePlanetId !== null &&
          activePlanetId > 0 &&
          _last.activePlanetId !== activePlanetId
        ) {
          // Build queue is per active colony — never reuse the previous planet's panel state.
          _lastQueueSignature = "";
          BUILDQ.active.finishTime = 0;
          BUILDQ.active.totalSeconds = 0;
        }
        if (activePlanetId > 0) {
          _last.activePlanetId = activePlanetId;
        }

        if (_reason !== "planet_switch") {
          reloadPageForActivePlanet(activePlanetId, _reason || "state");
        }

        if (typeof GC.updateHeaderPlanetSwitcherFromState === "function") {
          GC.updateHeaderPlanetSwitcherFromState(data);
        }

        applyPlanetLandscapeFromState(data);
      }

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
      const fuelCells = Math.floor(Number(p.fuel_cells ?? resources.fuel_cells ?? 0));
      const used = Math.floor(Number(p.energy_used ?? energy.used ?? resources.energy_used ?? 0));
      const total = Math.floor(Number(p.energy_total ?? energy.total ?? resources.energy_total ?? 0));

      const prodMetal = Math.floor(Number(prod.metal_mine ?? prod.metal ?? 0));
      const prodCrystal = Math.floor(Number(prod.crystal_mine ?? prod.crystal ?? 0));
      const prodFuelCells = Math.floor(Number(prod.fuel_cell_plant ?? prod.fuel_cells ?? 0));

      // --- Top-Bar Ressourcen (alle sichtbaren Instanzen aktualisieren) ---
      const metalValEls = document.querySelectorAll(".res-value.metal");
      const metalCapEls = document.querySelectorAll(".res-cap.metal");
      const cryValEls = document.querySelectorAll(".res-value.crystal");
      const cryCapEls = document.querySelectorAll(".res-cap.crystal");
      const fuelValEls = document.querySelectorAll(".res-value.fuel_cells");

      if (forceResourceBar || _last.metal !== metal) {
        metalValEls.forEach((el) => { el.textContent = fmtNumber(metal); });
        _last.metal = metal;
      }
      if (forceResourceBar || _last.crystal !== crystal) {
        cryValEls.forEach((el) => { el.textContent = fmtNumber(crystal); });
        _last.crystal = crystal;
      }

      if (forceResourceBar || (_last.storageMetal !== storageMetal && storageMetal > 0)) {
        metalCapEls.forEach((el) => { el.textContent = fmtNumber(storageMetal); });
        _last.storageMetal = storageMetal;
      }
      if (forceResourceBar || (_last.storageCrystal !== storageCrystal && storageCrystal > 0)) {
        cryCapEls.forEach((el) => { el.textContent = fmtNumber(storageCrystal); });
        _last.storageCrystal = storageCrystal;
      }

      if (forceResourceBar || _last.fuelCells !== fuelCells) {
        fuelValEls.forEach((el) => { el.textContent = fmtNumber(fuelCells); });
        _last.fuelCells = fuelCells;
      }

      const rateLabel = (key, perHour) => {
        const ph = Math.floor(Number(perHour) || 0);
        document.querySelectorAll(`[data-res-rate="${key}"]`).forEach((el) => {
          if (ph > 0) {
            const sign = ph >= 0 ? "+" : "";
            el.textContent = `${sign}${fmtNumber(ph)}/h`;
            el.style.visibility = "visible";
            el.removeAttribute("hidden");
            el.removeAttribute("aria-hidden");
          } else {
            el.textContent = "";
            el.style.visibility = "hidden";
            el.setAttribute("aria-hidden", "true");
          }
        });
      };

      if (forceResourceBar || _last.prodMetal !== prodMetal) {
        rateLabel("metal", prodMetal);
        _last.prodMetal = prodMetal;
      }
      if (forceResourceBar || _last.prodCrystal !== prodCrystal) {
        rateLabel("crystal", prodCrystal);
        _last.prodCrystal = prodCrystal;
      }
      if (forceResourceBar || _last.prodFuelCells !== prodFuelCells) {
        rateLabel("fuel_cells", prodFuelCells);
        _last.prodFuelCells = prodFuelCells;
      }

      const energyText = `${fmtNumber(used)}/${fmtNumber(total)}`;
      if (forceResourceBar || _last.energyUsed !== used || _last.energyTotal !== total) {
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
      patchResourceBarEnergyWarning(used, total);

      const livePlanetId = activePlanetId > 0
        ? activePlanetId
        : Number(data.active_planet_id || data.build_queue?.planet_id || 0);
      syncResourceLiveBaseline({
        planetId: livePlanetId,
        metal,
        crystal,
        fuelCells,
        prodMetal,
        prodCrystal,
        prodFuelCells,
        storageMetal,
        storageCrystal,
      });

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

      if (hudOnly) {
        GC.lastState = data;
        return false;
      }

      if (typeof data.unread_messages_count === "number") {
        const onMessagesPage = GC.detectPage() === "messages";
        const prevUnread = _lastMessagesUnreadPoll;
        const unreadIncreased =
          prevUnread !== null && data.unread_messages_count > prevUnread;
        if (!skipMessagesUnread) {
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

          // Inbox list load is owned by messages.js (init/tab). Only refresh when unread
          // count rises after the inbox has already loaded — never on empty filtered tabs.
          if (
            unreadIncreased &&
            onMessagesPage &&
            GC.messagesPageState &&
            GC.messagesPageState.listLoaded &&
            !GC.messagesPageState.loading &&
            typeof GC.messagesPageState.loadList === "function"
          ) {
            GC.messagesPageState.loadList();
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
      patchOverviewStatus(data.overview, data, buildings, prod);
      if (data.exchange) patchExchangePanel(data.exchange);
      if (data.scrapyard) patchScrapyardPanel(data.scrapyard);
      patchTraderHubBalance(metal, crystal, storageMetal, storageCrystal, data.player?.fuel_cells);
      if (data.planet_teaser) patchPlanetTeaser(data.planet_teaser);

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
      if (gameStateIncludePanel()) {
        scheduleShipyardRefreshFromState(true);
      } else {
        scheduleShipyardRefreshFromState();
      }

      return hasActiveBuild || hasActiveResearchNow;
  }

  function gameStateIncludePanel() {
    const page = typeof GC.detectPage === "function" ? GC.detectPage() : "";
    return page === "buildings" || page === "research" || page === "shipyard" || page === "trader_hub";
  }

  /** Lightweight HUD refresh — standalone fetch, no pageLifecycle abort. */
  async function refreshHudFromGameState(reason) {
    if (!shouldRunGameLoop() || _authLoopAborted) return null;
    try {
      const res = await fetch("/api/game-state", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) {
        if (res.status === 401 || res.status === 403) handleAuthFailure("admin_hud");
        return null;
      }
      const ct = (res.headers.get("content-type") || "").toLowerCase();
      if (!ct.includes("application/json")) return null;
      const data = await res.json();
      if (!data || data.ok === false) {
        if (isAuthStatusFailure(null, data)) handleAuthFailure("admin_hud");
        return null;
      }
      _statusPollErrorLogged = false;
      clearStatusWidgetOffline();
      applyGameStateData(data, reason || "admin_hud", { hudOnly: true });
      return data;
    } catch (err) {
      if (isAuthStatusFailure(err)) {
        handleAuthFailure("admin_hud");
        return null;
      }
      console.warn("[GC] HUD refresh failed", reason, err);
      return null;
    }
  }

  async function refreshGameState(reason) {
    if (!shouldRunGameLoop() || _authLoopAborted) return null;

    const reasonStr = String(reason || "");
    const isFinishReason = reasonStr.endsWith("_finished");
    const isChainReason = isFinishReason || reasonStr === "fleet_countdown_expired";

    if (GC.refreshInFlight) {
      if (isChainReason) {
        _queuedChainRefreshReason = reasonStr;
        return GC.refreshInFlight;
      }
      return GC.refreshInFlight;
    }

    const p = GC.polling;
    p.inFlight = true;
    if (p.abort && !isChainReason && reasonStr !== "poll" && reasonStr !== "pjax_nav") {
      try {
        p.abort.abort();
      } catch (_) {}
    }

    const ctrl = new AbortController();
    p.abort = ctrl;

    let resolveFlight;
    let rejectFlight;
    const flight = new Promise((resolve, reject) => {
      resolveFlight = resolve;
      rejectFlight = reject;
    });
    GC.refreshInFlight = flight;

    (async () => {
      try {
        const panelQ = gameStateIncludePanel() ? "?include_panel=1" : "";
        const data = await GC.fetchJSON(`/api/game-state${panelQ}`, { cache: "no-store", signal: ctrl.signal });
        if (!data || data.ok === false) {
          if (isAuthStatusFailure(null, data)) handleAuthFailure("game-state-payload");
          resolveFlight(null);
          return null;
        }

        p.backoff = 0;
        _statusPollErrorLogged = false;
        clearStatusWidgetOffline();
        if (data.server_time) setServerTime(data.server_time);

        const anyActive = applyGameStateData(data, reason);
        const wantPolling = anyActive || lastHadActiveJob || lastHadActiveResearch;
        if (reason === "poll") {
          const p = GC.polling;
          if (wantPolling && p.running && p.lastInterval > p.intervalActive + 100) {
            GC.stopPolling();
            GC.startPolling(true);
          }
        } else if (reason === "page_init" || reason === "tab_visible" || !GC.polling.running) {
          GC.startPolling(wantPolling);
        }
        resolveFlight(data);
        return data;
      } catch (err) {
        if (err?.name === "AbortError") {
          resolveFlight(null);
          return null;
        }

        if (isAuthStatusFailure(err)) {
          handleAuthFailure(reason);
          resolveFlight(null);
          return null;
        }

        if (!shouldRunGameLoop()) {
          GC.stopPolling();
          resolveFlight(null);
          return null;
        }

        logStatusPollErrorOnce(reason, err);
        markStatusWidgetOffline();
        p.backoff = Math.min(60000, (p.backoff || 2000) * 1.6);
        if (reason !== "poll" && shouldRunGameLoop() && !_authLoopAborted && !GC.polling.running) {
          GC.startPolling(lastHadActiveJob || lastHadActiveResearch, true);
        }
        resolveFlight(null);
        return null;
      } finally {
        p.inFlight = false;
        p.abort = null;
        if (GC.refreshInFlight === flight) {
          GC.refreshInFlight = null;
        }
        const queued = _queuedChainRefreshReason;
        if (queued) {
          _queuedChainRefreshReason = null;
          queueMicrotask(() => {
            if (shouldRunGameLoop() && !_authLoopAborted) refreshGameState(queued);
          });
        }
      }
    })();

    return flight;
  }

  GC.refreshGameState = refreshGameState;
  GC.refreshHudFromGameState = refreshHudFromGameState;
  GC.applyHudFromGameState = function applyHudFromGameState(data, reason) {
    if (!data || data.ok === false) return false;
    applyGameStateData(data, reason || "admin_hud", { hudOnly: true, forceResourceBar: true });
    clearStatusWidgetOffline();
    return true;
  };

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
      if (!btn || btn.closest("#messages-tabs")) return;
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

  function patchPlanetTeaser(teaser) {
    const root = document.getElementById("gc-planet-teaser");
    if (!root || !teaser || !teaser.visible) return;

    const levelEl = root.querySelector("[data-pe-teaser-level]");
    const scoreEl = root.querySelector("[data-pe-teaser-score]");
    const pctEl = root.querySelector("[data-pe-teaser-unlock-pct]");
    if (levelEl && teaser.planet_level != null) levelEl.textContent = String(teaser.planet_level);
    if (scoreEl && teaser.planet_score != null) scoreEl.textContent = String(teaser.planet_score);
    if (pctEl && teaser.progress_to_unlock_pct != null) {
      pctEl.style.width = `${teaser.progress_to_unlock_pct}%`;
    }
    root.className = `gc-planet-teaser gc-panel gc-planet-teaser-${teaser.status || "countdown"}`;
  }

  function initOverview() {
    const trigger = document.getElementById("overview-planet-menu-trigger");
    const modal = document.getElementById("gc-planet-manage-root");
    const renameForm = document.getElementById("overview-planet-rename-form");
    const deleteBtn = document.getElementById("overview-planet-delete-btn");
    const deleteHint = document.getElementById("overview-planet-delete-hint");
    if (!trigger || !modal) return;

    const hintEl = modal.querySelector("[data-planet-form-msg]");
    const nameInput = document.getElementById("overview-planet-rename-input");

    function isPlanetManageModalOpen() {
      return modal && !modal.hidden;
    }

    function setPlanetNameDisplay(name) {
      const label = String(name || "").trim();
      const nameEl = document.getElementById("overview-planet-name");
      if (nameEl) nameEl.textContent = label;
      const inputActive =
        nameInput &&
        (isPlanetManageModalOpen() || document.activeElement === nameInput);
      if (nameInput && !inputActive) nameInput.value = label;
      ["build-queue-planet-label", "research-planet-label"].forEach((id) => {
        const chip = document.getElementById(id);
        if (!chip) return;
        chip.textContent = id === "build-queue-planet-label" ? `· ${label}` : label;
      });
    }

    function syncDeleteState() {
      const canDelete = trigger.getAttribute("data-can-delete") === "1";
      if (deleteBtn) {
        deleteBtn.disabled = !canDelete;
        deleteBtn.setAttribute("aria-disabled", canDelete ? "false" : "true");
      }
      if (deleteHint) deleteHint.hidden = canDelete;
    }

    function openPlanetManageModal() {
      const currentName = document.getElementById("overview-planet-name");
      if (nameInput && currentName) nameInput.value = (currentName.textContent || "").trim();
      syncDeleteState();
      if (hintEl) {
        hintEl.textContent = "";
        hintEl.hidden = true;
      }
      modal.hidden = false;
      modal.setAttribute("aria-hidden", "false");
      trigger.setAttribute("aria-expanded", "true");
      document.body.classList.add("gc-planet-manage-open");
      const closeBtn = modal.querySelector("[data-planet-close].gc-player-card-close");
      if (nameInput) {
        setTimeout(() => nameInput.focus(), 0);
      } else if (closeBtn) {
        closeBtn.focus({ preventScroll: true });
      }
    }

    function closePlanetManageModal() {
      modal.hidden = true;
      modal.setAttribute("aria-hidden", "true");
      trigger.setAttribute("aria-expanded", "false");
      document.body.classList.remove("gc-planet-manage-open");
      trigger.focus({ preventScroll: true });
    }

    function setHint(text, isError) {
      if (!hintEl) return;
      hintEl.textContent = text || "";
      hintEl.hidden = !text;
      hintEl.classList.toggle("gc-options-hint-error", Boolean(isError));
      hintEl.classList.toggle("is-error", Boolean(isError));
      hintEl.classList.toggle("is-success", Boolean(text) && !isError);
    }

    if (!modal.dataset.bound) {
      modal.dataset.bound = "1";
      modal.querySelectorAll("[data-planet-close]").forEach((el) => {
        el.addEventListener("click", () => closePlanetManageModal());
      });
      document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && !modal.hidden) closePlanetManageModal();
      });
    }

    if (trigger.dataset.overviewPlanetBound) {
      GC.applyOverviewPlanetName = setPlanetNameDisplay;
      return;
    }
    trigger.dataset.overviewPlanetBound = "1";

    trigger.addEventListener("click", (ev) => {
      ev.preventDefault();
      if (modal.hidden) openPlanetManageModal();
      else closePlanetManageModal();
    });

    if (renameForm) {
      renameForm.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const planetName = String(nameInput && nameInput.value ? nameInput.value : "").trim();
        if (!planetName) return;
        setHint("", false);
        try {
          const data = await GC.fetchGameAction("/api/options/planet-name", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ planet_name: planetName }),
          });
          if (!data.ok) {
            setHint(t(data.error || "options_error_invalid_name", "Speichern fehlgeschlagen."), true);
            return;
          }
          const saved =
            data.data &&
            (data.data.active_planet_name || data.data.planet_name || data.data.homeworld_name);
          if (saved) setPlanetNameDisplay(saved);
          setHint(t("playercard_save_success", "Gespeichert."), false);
          if (typeof GC.refreshGameState === "function") GC.refreshGameState("planet_rename");
          setTimeout(() => closePlanetManageModal(), 450);
        } catch (err) {
          if (err && err.message === "auth") return;
          setHint(t("playercard_save_error", "Speichern fehlgeschlagen."), true);
        }
      });
    }

    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        if (deleteBtn.disabled) return;
        const confirmMsg = t(
          "overview_planet_delete_confirm",
          "Diese Kolonie unwiderruflich löschen?"
        );
        if (!window.confirm(confirmMsg)) return;
        setHint("", false);
        deleteBtn.disabled = true;
        try {
          const data = await GC.fetchGameAction("/api/planet/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({}),
          });
          if (!data.ok) {
            setHint(t(data.error || "planet_error_delete_failed", "Löschen fehlgeschlagen."), true);
            syncDeleteState();
            return;
          }
          closePlanetManageModal();
          window.location.href = "/overview";
        } catch (err) {
          if (err && err.message === "auth") return;
          setHint(t("planet_error_delete_failed", "Löschen fehlgeschlagen."), true);
          syncDeleteState();
        }
      });
    }

    GC.applyOverviewPlanetName = setPlanetNameDisplay;
  }

  function initTraderHub() {
    initExchangePanel();
    initScrapyardPanel();
  }

  function parseFleetPageData(page) {
    const el = document.getElementById("fleet-page-state");
    if (el && el.textContent) {
      try { return JSON.parse(el.textContent); } catch (_) {}
    }
    return {};
  }

  function getFleetRuntime(page) {
    if (!page._fleetRt) {
      page._fleetRt = {
        data: parseFleetPageData(page),
        lastPreview: null,
        sending: false,
        previewTimer: null,
      };
    }
    return page._fleetRt;
  }

  function fleetFuelLabel(tt, fuelResource) {
    if (fuelResource === "fuel_cells") return tt("resource_fuel_cells", "Fuel Cells");
    if (fuelResource === "metal") return tt("resource_metal", "Ferronit");
    return tt("resource_crystal", "Crytite");
  }

  function bindFleetOnce() {
    if (GC._fleetEventsBound) return;
    GC._fleetEventsBound = true;

    const tt = (key, fallback) => t(key, fallback);
    const fleetPayload = (res) => ((res && res.data && typeof res.data === "object") ? res.data : res) || {};
    const apiError = (res) => (res && (res.error || res.reason)) || "generic";
    const reasonText = (reason) => tt(`fleet_error_${reason}`, tt("fleet_error_generic", "Fleet action failed."));

    const getPage = () => {
      const page = document.getElementById("fleet-page");
      return page && page.dataset.ready === "1" ? page : null;
    };

    const getForm = (page) => page.querySelector("#fleet-send-form");

    const getShipsSelection = (page) => {
      const ships = {};
      page.querySelectorAll("[data-ship-input]").forEach((inp) => {
        const key = inp.getAttribute("data-ship-input");
        const val = parseInt(inp.value || "0", 10);
        if (key && val > 0) ships[key] = val;
      });
      return ships;
    };

    const getResourcesSelection = (page) => ({
      metal: parseInt(page.querySelector("[data-fleet-res-metal]")?.value || "0", 10) || 0,
      crystal: parseInt(page.querySelector("[data-fleet-res-crystal]")?.value || "0", 10) || 0,
      fuel_cells: parseInt(page.querySelector("[data-fleet-res-fuel-cells]")?.value || "0", 10) || 0,
    });

    const getTargetCoords = (page) => {
      const form = getForm(page);
      return {
        target_galaxy: parseInt(form?.querySelector('[name="target_galaxy"]')?.value || "1", 10),
        target_system: parseInt(form?.querySelector('[name="target_system"]')?.value || "1", 10),
        target_position: parseInt(form?.querySelector('[name="target_position"]')?.value || "1", 10),
      };
    };

    const formatFleetDuration = (sec) => formatCountdownRemain(sec);

    const buildShipRoleMap = (page) => {
      const rt = getFleetRuntime(page);
      const map = {};
      (rt.data.ship_defs || []).forEach((spec) => {
        if (spec?.key) map[spec.key] = spec.role || "";
      });
      return map;
    };

    const countShipsByRole = (page, ships, role) => {
      const roleMap = buildShipRoleMap(page);
      return Object.entries(ships || {}).reduce((total, [key, qty]) => {
        if (roleMap[key] !== role) return total;
        return total + (parseInt(qty, 10) || 0);
      }, 0);
    };

    const applyExpeditionTarget = (page) => {
      const form = getForm(page);
      if (!form) return;
      const rt = getFleetRuntime(page);
      const expPos = parseInt(rt.data.expedition_position || "16", 10);
      const posInp = form.querySelector('[name="target_position"]');
      if (posInp) posInp.value = String(expPos);
    };

    const syncExpeditionMissionTarget = (page) => {
      const form = getForm(page);
      if (!form) return;
      const rt = getFleetRuntime(page);
      const expPos = parseInt(rt.data.expedition_position || "16", 10);
      const g = parseInt(form.querySelector('[name="target_galaxy"]')?.value || "0", 10);
      const s = parseInt(form.querySelector('[name="target_system"]')?.value || "0", 10);
      const pos = parseInt(form.querySelector('[name="target_position"]')?.value || "0", 10);
      const missionSel = form.querySelector("[data-fleet-mission]");
      const mission = missionSel?.value || "transport";
      const strip = page.querySelector("[data-fleet-coords-strip]");
      const hint = page.querySelector("[data-fleet-coords-hint]");
      const sendPanel = page.querySelector(".fleet-send-panel");
      const previewHud = page.querySelector("[data-fleet-preview]");
      const isExpoSlot = pos === expPos;

      if (strip) strip.classList.toggle("is-expedition", isExpoSlot);
      if (sendPanel) sendPanel.classList.toggle("is-expedition-mode", mission === "expedition" || isExpoSlot);
      if (previewHud) previewHud.classList.toggle("is-expedition", mission === "expedition" && isExpoSlot);

      if (isExpoSlot && missionSel && missionSel.value !== "expedition") {
        missionSel.value = "expedition";
        const colonizeRow = page.querySelector("[data-fleet-colonize-row]");
        if (colonizeRow) colonizeRow.hidden = true;
      }

      page.querySelectorAll(".fleet-colony-chip").forEach((chip) => {
        const cg = parseInt(chip.getAttribute("data-galaxy") || chip.dataset.galaxy || "0", 10);
        const cs = parseInt(chip.getAttribute("data-system") || chip.dataset.system || "0", 10);
        const cp = parseInt(chip.getAttribute("data-position") || chip.dataset.position || "0", 10);
        const chipMission = chip.getAttribute("data-mission") || chip.dataset.mission || "";
        const coordMatch = cg === g && cs === s && cp === pos;
        const selected = chip.classList.contains("fleet-colony-chip--expedition")
          ? coordMatch && mission === "expedition"
          : coordMatch && !chipMission;
        chip.classList.toggle("is-selected", selected);
      });

      if (hint) {
        if (isExpoSlot) {
          hint.textContent = tt("fleet_expedition_coords_hint", "Deep-space expedition slot — position 16 only.");
          hint.hidden = false;
        } else if (missionSel?.value === "expedition") {
          hint.textContent = formatMissionHint("fleet_expedition_coords_hint_required", { position: expPos });
          hint.hidden = false;
        } else {
          hint.textContent = "";
          hint.hidden = true;
        }
      }
      updateFleetFormMode(page);
      if (missionSel) GC.syncHudSelect(missionSel);
    };

    const updateFleetFormMode = (page) => {
      const form = getForm(page);
      if (!form) return;
      const mission = form.querySelector("[data-fleet-mission]")?.value || "transport";
      const resFieldset = page.querySelector("[data-fleet-resources-fieldset]");
      const showResources = ["transport", "deploy", "colonize", "collect"].includes(mission);
      if (resFieldset) resFieldset.hidden = !showResources;
      page.querySelectorAll("[data-fleet-mission] option").forEach((opt) => {
        opt.disabled = false;
      });
    };

    const formatMissionHint = (key, vars = {}) => {
      let text = tt(key, key);
      Object.entries(vars).forEach(([name, value]) => {
        text = text.replace(new RegExp(`%\\(${name}\\)s`, "g"), String(value ?? ""));
      });
      return text;
    };

    const resolveMissionFeedback = (page, missionType, preview, ships) => {
      const mission = String(missionType || "transport").toLowerCase();
      const target = preview?.target || {};
      const rt = getFleetRuntime(page);
      const expPos = parseInt(rt.data.expedition_position || "16", 10);
      const hints = [];

      if (target.target_type === "expedition_slot" && mission !== "expedition") {
        hints.push({ tone: "warn", text: formatMissionHint("fleet_expedition_hint_select_mission") });
        return hints;
      }

      if (mission === "expedition") {
        const expoShips = countShipsByRole(page, ships, "expedition");
        const cargoTotal = parseInt(preview?.cargo_total || "0", 10) || 0;
        if (target.target_type && target.target_type !== "expedition_slot") {
          hints.push({
            tone: "warn",
            text: formatMissionHint("fleet_expedition_hint_wrong_position", { position: expPos }),
          });
        } else if (expoShips <= 0 && cargoTotal <= 0) {
          hints.push({ tone: "warn", text: formatMissionHint("fleet_expedition_hint_no_hull") });
        } else {
          hints.push({
            tone: "ok",
            text: formatMissionHint("fleet_expedition_hint_ready", { ships: expoShips, cargo: cargoTotal }),
          });
        }
        hints.push({ tone: "info", text: formatMissionHint("fleet_expedition_hint_events") });
        return hints;
      }

      if (mission === "spy") {
        const probes = countShipsByRole(page, ships, "spy");
        hints.push({
          tone: probes > 0 ? "info" : "warn",
          text: probes > 0
            ? formatMissionHint("fleet_mission_hint_spy", { count: probes })
            : formatMissionHint("fleet_mission_hint_spy_none"),
        });
        return hints;
      }

      const genericHints = {
        transport: "fleet_mission_hint_transport",
        collect: "fleet_mission_hint_collect",
        deploy: "fleet_mission_hint_deploy",
        attack: "fleet_mission_hint_attack",
        hold: "fleet_mission_hint_hold",
        colonize: "fleet_mission_hint_colonize",
      };
      if (genericHints[mission]) {
        hints.push({ tone: "info", text: formatMissionHint(genericHints[mission]) });
      }
      return hints;
    };

    const updateMissionFeedback = (page, preview, missionType, ships) => {
      const panel = page.querySelector("[data-fleet-mission-feedback]");
      const textEl = page.querySelector("[data-fleet-mission-feedback-text]");
      if (!panel || !textEl) return;
      const hints = resolveMissionFeedback(page, missionType, preview, ships);
      if (!hints.length || !Object.keys(ships || {}).length) {
        panel.hidden = true;
        textEl.textContent = "";
        panel.className = "fleet-mission-feedback";
        return;
      }
      const primary = hints[0];
      const extra = hints.slice(1).map((h) => h.text).join(" ");
      textEl.textContent = extra ? `${primary.text} ${extra}` : primary.text;
      panel.className = `fleet-mission-feedback is-${primary.tone || "info"}`;
      panel.hidden = false;
    };

    const renderShipChips = (ships) => Object.entries(ships || {})
      .map(([key, qty]) => `<span class="fleet-ship-chip">${tt(`fleet_ship_${key}`, key)} × ${Number(qty).toLocaleString()}</span>`)
      .join("");

    const renderActiveFleets = (page, fleets) => {
      const activeListEl = page.querySelector("[data-fleet-active-list]");
      if (!activeListEl) return;
      const list = Array.isArray(fleets) ? fleets : [];
      if (!list.length) {
        activeListEl.dataset.fleetSig = "";
        _clearMovementCountdownExpiryState();
        activeListEl.innerHTML = `<p class="fleet-empty" data-fleet-empty>${tt("fleet_no_active", "No active fleets.")}</p>`;
        return;
      }

      const signature = list.map((mv) => `${mv.id}:${mv.phase || mv.leg_phase || mv.status}:${mv.countdown_at || 0}`).join("|");
      const sigChanged = activeListEl.dataset.fleetSig !== signature;
      if (sigChanged) {
        activeListEl.dataset.fleetSig = signature;
        _clearMovementCountdownExpiryState();
        activeListEl.innerHTML = list.map((mv) => {
        const countdownAt = Number(mv.countdown_at || 0);
        const phase = mv.phase || mv.leg_phase || mv.status || "";
        const legKey = mv.status_label || mv.leg_label_key || (
          phase === "returning"
            ? "fleet_leg_returning"
            : phase === "holding"
              ? "fleet_leg_holding"
              : "fleet_leg_outbound"
        );
        const legLabel = tt(legKey, legKey);
        const countdownKey = `${mv.id}:${phase}:${countdownAt}`;
        const countdown = countdownAt > 0
          ? `<span class="fleet-active-leg">${legLabel}: <time class="fleet-active-countdown gc-mono" data-countdown-at="${countdownAt}" data-countdown-scope="fleet" data-countdown-key="${countdownKey}">–</time></span>`
          : "";
        const cargo = [];
        if (mv.resources?.metal) cargo.push(`${tt("resource_metal")}: ${Number(mv.resources.metal).toLocaleString()}`);
        if (mv.resources?.crystal) cargo.push(`${tt("resource_crystal")}: ${Number(mv.resources.crystal).toLocaleString()}`);
        if (mv.resources?.fuel_cells) cargo.push(`${tt("resource_fuel_cells")}: ${Number(mv.resources.fuel_cells).toLocaleString()}`);
        const mission = String(mv.mission_type || "custom");
        return `<article class="fleet-active-card fleet-active-card--${mission}" data-fleet-id="${mv.id}" data-status="${mv.status}" data-mission="${mission}" data-leg="${phase}">
          <div class="fleet-active-row">
            <span class="fleet-active-mission fleet-active-mission--${mission}">${tt(`fleet_mission_${mv.mission_type}`, mv.mission_type)}</span>
            <span class="fleet-active-status">${tt(`fleet_status_${mv.status}`, mv.status)}</span>
          </div>
          <div class="fleet-active-coords gc-mono">${mv.origin_coords || ""} → ${mv.target_coords || ""}</div>
          <div class="fleet-active-ships">${renderShipChips(mv.ships)}</div>
          ${cargo.length ? `<div class="fleet-active-cargo">${cargo.map((c) => `<span>${c}</span>`).join(" ")}</div>` : ""}
          <div class="fleet-active-times gc-mono">${countdown}</div>
        </article>`;
        }).join("");
      }
      updateMovementCountdowns(getApproxServerNow());
      GC.startProgressTicker();
    };

    const renderPresetSelect = (page, presets) => {
      const optionHtml = `<option value="">${tt("fleet_preset_none", "— none —")}</option>` +
        (presets || []).map((p) =>
          `<option value="${p.id}">[${tt(`fleet_preset_type_${p.preset_type}`, p.preset_type)}] ${String(p.name || "").replace(/</g, "&lt;")}</option>`
        ).join("");
      [page.querySelector("[data-fleet-preset-select]"), page.querySelector("[data-fleet-mass-preset]")].forEach((sel) => {
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = optionHtml;
        if (current) sel.value = current;
        if (typeof GC.rebuildHudSelect === "function") GC.rebuildHudSelect(sel);
        else if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(sel);
      });
    };

    const renderPresetList = (page, presets) => {
      const presetListEl = page.querySelector("[data-fleet-preset-list]");
      if (!presetListEl) return;
      const list = Array.isArray(presets) ? presets : [];
      if (!list.length) {
        presetListEl.innerHTML = `<li class="fleet-preset-empty">${tt("fleet_no_presets", "No presets saved yet.")}</li>`;
        return;
      }
      presetListEl.innerHTML = list.map((p) =>
        `<li class="fleet-preset-item" data-preset-id="${p.id}">
          <span class="fleet-preset-type">${tt(`fleet_preset_type_${p.preset_type}`, p.preset_type)}</span>
          <span class="fleet-preset-name">${String(p.name || "").replace(/</g, "&lt;")}</span>
          <div class="fleet-preset-actions">
            <button type="button" class="gc-btn gc-btn-ghost" data-preset-load="${p.id}">${tt("fleet_preset_load_btn", "Load")}</button>
            <button type="button" class="gc-btn gc-btn-ghost gc-btn-danger" data-preset-delete="${p.id}">${tt("fleet_preset_delete", "Delete")}</button>
          </div>
        </li>`
      ).join("");
    };

    const applyLiveState = (page, state) => {
      const rt = getFleetRuntime(page);
      if (!state || typeof state !== "object") return;
      if (state.server_time) setServerTime(state.server_time);
      if (state.resources) {
        rt.data.resources = state.resources;
        ["metal", "crystal", "fuel_cells"].forEach((res) => {
          page.querySelectorAll(`[data-res="${res}"]`).forEach((el) => {
            el.textContent = Number(state.resources[res] || 0).toLocaleString();
          });
        });
      }
      if (state.ships) {
        rt.data.ships = state.ships;
        const totalShips = Object.values(state.ships).reduce((a, b) => a + (Number(b) || 0), 0);
        rt.data.has_ships = totalShips > 0;
        const noShipsPanel = page.querySelector(".fleet-no-ships-panel");
        const sendPanel = page.querySelector(".fleet-send-panel");
        if (noShipsPanel) noShipsPanel.hidden = totalShips > 0;
        if (sendPanel) sendPanel.hidden = totalShips <= 0;
        page.querySelectorAll(".fleet-ship-row").forEach((row) => {
          const key = row.getAttribute("data-ship-key");
          if (!key) return;
          const have = state.ships[key] || 0;
          row.setAttribute("data-ship-have", String(have));
          row.classList.toggle("fleet-ship-row-empty", have <= 0);
          row.hidden = false;
          const inp = row.querySelector("[data-ship-input]");
          if (inp) {
            inp.max = String(have);
            if (have <= 0) {
              inp.value = "0";
              inp.disabled = true;
            } else {
              inp.disabled = false;
              if (parseInt(inp.value || "0", 10) > have) inp.value = String(have);
            }
          }
          const maxBtn = row.querySelector("[data-ship-max]");
          if (maxBtn) maxBtn.disabled = have <= 0;
        });
      }
      const slotsEl = page.querySelector("[data-fleet-slots]");
      if (state.fleet_slots && slotsEl) {
        slotsEl.textContent = `${state.fleet_slots.active} / ${state.fleet_slots.max}`;
      }
      if (state.active_fleets) {
        rt.data.active_fleets = state.active_fleets;
        renderActiveFleets(page, state.active_fleets);
      } else {
        const activeListEl = page.querySelector("[data-fleet-active-list]");
        if (activeListEl) delete activeListEl.dataset.fleetSig;
      }
      if (state.presets) {
        rt.data.presets = state.presets;
        renderPresetList(page, state.presets);
        renderPresetSelect(page, state.presets);
      }
    };

    const refreshFleetState = async (page) => {
      try {
        const rt = getFleetRuntime(page);
        let planetId = parseInt(page.dataset.planetId || rt.data?.planet_id || "0", 10);
        if (!planetId) {
          planetId = Number(GC.lastState?.active_planet_id || 0);
        }
        const q = planetId ? `?planet_id=${planetId}` : "";
        const res = await GC.fetchJSON(`/api/fleet/state${q}`, { cache: "no-store" });
        if (res?.ok) applyLiveState(page, fleetPayload(res));
      } catch (_) {}
    };
    GC.refreshFleetState = refreshFleetState;

    const runPreview = async (page) => {
      const rt = getFleetRuntime(page);
      const form = getForm(page);
      if (!form) return;
      const previewCargo = page.querySelector("[data-preview-cargo]");
      const previewCargoFree = page.querySelector("[data-preview-cargo-free]");
      const previewFuel = page.querySelector("[data-preview-fuel]");
      const previewFuelAvail = page.querySelector("[data-preview-fuel-available]");
      const previewFlight = page.querySelector("[data-preview-flight]");
      const previewTargetType = page.querySelector("[data-preview-target-type]");
      const previewTargetOwner = page.querySelector("[data-preview-target-owner]");
      const previewMissionStatus = page.querySelector("[data-preview-mission-status]");
      const previewMissionBadge = page.querySelector("[data-preview-mission-badge]");
      const previewArrival = page.querySelector("[data-preview-arrival]");
      const missionFeedback = page.querySelector("[data-fleet-mission-feedback]");
      const sendBtn = page.querySelector("[data-fleet-send-btn]");
      const ships = getShipsSelection(page);
      const missionType = form.querySelector("[data-fleet-mission]")?.value || "transport";
      const resetPreview = () => {
        rt.lastPreview = null;
        if (previewTargetType) previewTargetType.textContent = "–";
        if (previewTargetOwner) previewTargetOwner.textContent = "–";
        if (previewMissionStatus) {
          previewMissionStatus.textContent = "–";
          previewMissionStatus.classList.remove("is-ok", "is-blocked");
        }
        if (previewMissionBadge) previewMissionBadge.textContent = "–";
        if (previewCargo) previewCargo.textContent = "–";
        if (previewCargoFree) previewCargoFree.textContent = "–";
        if (previewFuel) previewFuel.textContent = "–";
        if (previewFuelAvail) previewFuelAvail.textContent = "–";
        if (previewFlight) previewFlight.textContent = "–";
        if (previewArrival) previewArrival.textContent = "–";
        if (missionFeedback) {
          missionFeedback.hidden = true;
          missionFeedback.className = "fleet-mission-feedback";
          const fbText = missionFeedback.querySelector("[data-fleet-mission-feedback-text]");
          if (fbText) fbText.textContent = "";
        }
        if (sendBtn) sendBtn.disabled = true;
      };
      if (!Object.keys(ships).length) {
        resetPreview();
        return;
      }
      try {
        const res = await GC.fetchJSON("/api/fleet/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          body: JSON.stringify({
            origin_planet_id: rt.data.planet_id,
            ships,
            resources: getResourcesSelection(page),
            speed_percent: parseInt(form.querySelector("[data-fleet-speed]")?.value || "100", 10),
            mission_type: missionType,
            ...getTargetCoords(page),
          }),
        });
        const p = fleetPayload(res).preview || res.preview;
        if (res?.ok && p) {
          rt.lastPreview = p;
          const target = p.target || {};
          if (previewTargetType) {
            previewTargetType.textContent = target.target_type
              ? tt(`fleet_target_${target.target_type}`, target.target_type)
              : "–";
          }
          if (previewTargetOwner) {
            previewTargetOwner.textContent = target.target_owner_name || (target.target_type === "expedition_slot"
              ? tt("fleet_target_expedition_label", "Deep space")
              : target.target_type === "empty_slot"
                ? tt("fleet_target_empty_label", "—")
                : "–");
          }
          if (previewMissionBadge) {
            previewMissionBadge.textContent = tt(`fleet_mission_${missionType}`, missionType);
          }
          if (previewMissionStatus) {
            previewMissionStatus.classList.remove("is-ok", "is-blocked");
            if (p.can_send) {
              previewMissionStatus.textContent = tt("fleet_preview_mission_ok", "Mission allowed");
              previewMissionStatus.classList.add("is-ok");
            } else {
              const reason = p.block_reason || p.mission_block_reason || "generic";
              previewMissionStatus.textContent = reasonText(reason);
              previewMissionStatus.classList.add("is-blocked");
            }
          }
          const previewHud = page.querySelector("[data-fleet-preview]");
          if (previewHud) {
            previewHud.classList.toggle(
              "is-expedition",
              missionType === "expedition" && target.target_type === "expedition_slot"
            );
            previewHud.classList.toggle("is-ready", !!p.can_send);
            previewHud.classList.toggle("is-blocked", !p.can_send);
          }
          updateMissionFeedback(page, p, missionType, ships);
          if (previewCargo) previewCargo.textContent = `${p.cargo_used || 0} / ${p.cargo_total || 0}`;
          if (previewCargoFree) previewCargoFree.textContent = String(p.cargo_free || 0);
          if (previewFuel) previewFuel.textContent = String(p.fuel_cost || 0);
          if (previewFuelAvail) previewFuelAvail.textContent = String(p.fuel_available ?? rt.data.resources?.fuel_cells ?? "–");
          if (previewFlight) {
            previewFlight.textContent = formatCountdownRemain(p.duration_seconds ?? p.flight_seconds ?? 0);
          }
          if (previewArrival) {
            if (p.countdown_at) {
              const nowSec = getApproxServerNow();
              previewArrival.textContent = formatCountdownRemain(Math.max(0, Math.ceil(Number(p.countdown_at) - nowSec)));
            } else if (p.arrival_at) {
              const nowSec = getApproxServerNow();
              previewArrival.textContent = formatCountdownRemain(Math.max(0, Math.ceil(Number(p.arrival_at) - nowSec)));
            } else {
              previewArrival.textContent = "–";
            }
          }
          if (sendBtn) sendBtn.disabled = !p.can_send;
        } else {
          resetPreview();
        }
      } catch (_) {
        resetPreview();
      }
    };

    const schedulePreview = (page) => {
      const rt = getFleetRuntime(page);
      if (rt.previewTimer) clearTimeout(rt.previewTimer);
      rt.previewTimer = setTimeout(() => runPreview(page), 300);
    };

    const loadPresetById = (page, presetId) => {
      const rt = getFleetRuntime(page);
      const form = getForm(page);
      const preset = (rt.data.presets || []).find((p) => String(p.id) === String(presetId));
      if (!preset || !form) return;
      page.querySelectorAll("[data-ship-input]").forEach((inp) => { inp.value = "0"; });
      Object.entries(preset.ships || {}).forEach(([key, qty]) => {
        const inp = form.querySelector(`[data-ship-input="${key}"]`);
        if (inp) inp.value = String(qty);
      });
      if (preset.speed_percent) {
        const sp = form.querySelector("[data-fleet-speed]");
        if (sp) {
          sp.value = String(preset.speed_percent);
          GC.syncHudSelect(sp);
        }
      }
      if (preset.mission_type) {
        const ms = form.querySelector("[data-fleet-mission]");
        if (ms) {
          ms.value = preset.mission_type;
          GC.syncHudSelect(ms);
        }
      }
      if (preset.target_galaxy != null) form.querySelector('[name="target_galaxy"]').value = String(preset.target_galaxy);
      if (preset.target_system != null) form.querySelector('[name="target_system"]').value = String(preset.target_system);
      if (preset.target_position != null) form.querySelector('[name="target_position"]').value = String(preset.target_position);
      syncExpeditionMissionTarget(page);
      schedulePreview(page);
    };

    const applyQuickTarget = (page, chip) => {
      const form = getForm(page);
      if (!form || !chip) return;
      const g = form.querySelector('[name="target_galaxy"]');
      const s = form.querySelector('[name="target_system"]');
      const p = form.querySelector('[name="target_position"]');
      if (g) g.value = chip.getAttribute("data-galaxy") || chip.dataset.galaxy || "";
      if (s) s.value = chip.getAttribute("data-system") || chip.dataset.system || "";
      if (p) p.value = chip.getAttribute("data-position") || chip.dataset.position || "";
      const mission = chip.getAttribute("data-mission") || chip.dataset.mission;
      const ms = form.querySelector("[data-fleet-mission]");
      if (mission && ms) {
        ms.value = mission;
        GC.syncHudSelect(ms);
        const colonizeRow = page.querySelector("[data-fleet-colonize-row]");
        if (colonizeRow) colonizeRow.hidden = mission !== "colonize";
      } else if (ms && ms.value === "expedition") {
        ms.value = "transport";
        GC.syncHudSelect(ms);
        const colonizeRow = page.querySelector("[data-fleet-colonize-row]");
        if (colonizeRow) colonizeRow.hidden = true;
      }
      page.querySelectorAll(".fleet-colony-chip").forEach((c) => c.classList.remove("is-selected"));
      chip.classList.add("is-selected");
      syncExpeditionMissionTarget(page);
      schedulePreview(page);
    };

    GC.scheduleFleetPreview = schedulePreview;
    GC.syncExpeditionMissionTarget = syncExpeditionMissionTarget;
    GC.updateFleetFormMode = updateFleetFormMode;
    GC.refreshFleetState = refreshFleetState;
    GC.runFleetPreview = runPreview;

    document.addEventListener("click", async (e) => {
      const page = getPage();
      if (!page) return;
      const rt = getFleetRuntime(page);
      const form = getForm(page);
      const fuelResource = rt.data.fuel_resource || page.dataset.fuelResource || "fuel_cells";

      const maxShip = e.target.closest("[data-ship-max]");
      if (maxShip && page.contains(maxShip)) {
        e.preventDefault();
        const key = maxShip.getAttribute("data-ship-max");
        const row = maxShip.closest("[data-ship-key]");
        const have = parseInt(row?.getAttribute("data-ship-have") || "0", 10);
        const inp = form?.querySelector(`[data-ship-input="${key}"]`);
        if (inp) inp.value = String(have);
        schedulePreview(page);
        return;
      }

      const resMax = e.target.closest("[data-fleet-res-max]");
      if (resMax && page.contains(resMax)) {
        e.preventDefault();
        const res = resMax.getAttribute("data-fleet-res-max");
        if (!rt.lastPreview) await runPreview(page);
        const cargoFree = parseInt(rt.lastPreview?.cargo_free ?? "0", 10) || 0;
        const bal = rt.data.resources?.[res] || 0;
        let val = Math.min(bal, cargoFree > 0 ? cargoFree : bal);
        const inp = page.querySelector(`[data-fleet-res-${res}]`);
        if (inp) inp.value = String(Math.max(0, val));
        schedulePreview(page);
        return;
      }

      const chip = e.target.closest(".fleet-colony-chip");
      if (chip && page.contains(chip)) {
        e.preventDefault();
        applyQuickTarget(page, chip);
        return;
      }

      const loadBtn = e.target.closest("[data-preset-load]");
      if (loadBtn && page.contains(loadBtn)) {
        e.preventDefault();
        loadPresetById(page, loadBtn.getAttribute("data-preset-load"));
        return;
      }

      const delBtn = e.target.closest("[data-preset-delete]");
      if (delBtn && page.contains(delBtn)) {
        e.preventDefault();
        const id = delBtn.getAttribute("data-preset-delete");
        if (!id || !window.confirm(tt("fleet_preset_delete_confirm", "Delete this preset?"))) return;
        try {
          const res = await GC.fetchGameAction(`/api/fleet/presets/${id}`, { method: "DELETE" });
          if (res?.ok) {
            showNotify(tt("fleet_preset_deleted", "Preset deleted."), "success");
            rt.data.presets = (rt.data.presets || []).filter((p) => String(p.id) !== String(id));
            renderPresetList(page, rt.data.presets);
            renderPresetSelect(page, rt.data.presets);
          } else {
            showNotify(reasonText(apiError(res)), "error");
          }
        } catch (_) {
          showNotify(reasonText("generic"), "error");
        }
        return;
      }

      const savePreset = e.target.closest("[data-fleet-save-preset]");
      if (savePreset && page.contains(savePreset)) {
        e.preventDefault();
        const name = window.prompt(tt("fleet_preset_name_prompt", "Preset name:"));
        if (!name || !name.trim()) return;
        const type = window.prompt(tt("fleet_preset_type_prompt", "Type (raid/farm/spy/transport/deploy/expedition/custom):"), "custom") || "custom";
        try {
          const res = await GC.fetchGameAction("/api/fleet/presets", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: name.trim(),
              preset_type: type.trim().toLowerCase(),
              ships_json: getShipsSelection(page),
              resources_json: getResourcesSelection(page),
              speed_percent: parseInt(form.querySelector("[data-fleet-speed]")?.value || "100", 10),
              mission_type: form.querySelector("[data-fleet-mission]")?.value,
              ...getTargetCoords(page),
            }),
          });
          if (res?.ok) {
            showNotify(tt("fleet_preset_saved", "Preset saved."), "success");
            const preset = fleetPayload(res).preset;
            if (preset) {
              rt.data.presets = [preset, ...(rt.data.presets || []).filter((p) => p.id !== preset.id)];
              renderPresetList(page, rt.data.presets);
              renderPresetSelect(page, rt.data.presets);
            } else {
              await refreshFleetState(page);
            }
          } else {
            showNotify(reasonText(apiError(res)), "error");
          }
        } catch (_) {
          showNotify(reasonText("generic"), "error");
        }
        return;
      }

    });

    document.addEventListener("change", (e) => {
      const page = getPage();
      if (!page) return;
      if (e.target.matches("[data-fleet-preset-select]")) {
        const id = e.target.value;
        if (id) loadPresetById(page, id);
        return;
      }
      if (e.target.matches("[data-fleet-mission]")) {
        const colonizeRow = page.querySelector("[data-fleet-colonize-row]");
        if (colonizeRow) colonizeRow.hidden = e.target.value !== "colonize";
        if (e.target.value === "expedition") applyExpeditionTarget(page);
        syncExpeditionMissionTarget(page);
        schedulePreview(page);
      }
      if (e.target.matches('[name="target_galaxy"], [name="target_system"], [name="target_position"]')) {
        syncExpeditionMissionTarget(page);
      }
      if (e.target.closest("#fleet-send-form")) schedulePreview(page);
    });

    document.addEventListener("input", (e) => {
      const page = getPage();
      if (!page) return;
      if (e.target.matches('[name="target_galaxy"], [name="target_system"], [name="target_position"]')) {
        syncExpeditionMissionTarget(page);
      }
      if (e.target.closest("#fleet-send-form")) schedulePreview(page);
    });

    document.addEventListener("submit", async (e) => {
      const sendForm = e.target.closest ? e.target.closest("#fleet-send-form") : null;
      const page = getPage();
      if (sendForm && page && page.contains(sendForm)) {
        e.preventDefault();
        e.stopPropagation();
        const rt = getFleetRuntime(page);
        const form = sendForm;
        if (rt.sending) return;
        const errorEl = page.querySelector("[data-fleet-error]");
        if (errorEl) { errorEl.hidden = true; errorEl.textContent = ""; }
        const submitBtn = form.querySelector(".fleet-send-submit") || form.querySelector("[data-fleet-send-btn]");
        rt.sending = true;
        if (submitBtn) submitBtn.disabled = true;
        if (!rt.lastPreview?.can_send) {
          if (errorEl) {
            errorEl.textContent = reasonText(rt.lastPreview?.block_reason || "generic");
            errorEl.hidden = false;
          }
          rt.sending = false;
          if (submitBtn) submitBtn.disabled = !rt.lastPreview?.can_send;
          return;
        }
        try {
          const res = await GC.fetchGameAction("/api/fleet/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              origin_planet_id: rt.data.planet_id,
              ships: getShipsSelection(page),
              resources: getResourcesSelection(page),
              speed_percent: parseInt(form.querySelector("[data-fleet-speed]")?.value || "100", 10),
              mission_type: form.querySelector("[data-fleet-mission]")?.value,
              colony_name: form.querySelector("[data-fleet-colony-name]")?.value || undefined,
              ...getTargetCoords(page),
            }),
          });
          if (res?.ok) {
            showNotify(tt("fleet_send_success", "Fleet dispatched."), "success");
            const payload = fleetPayload(res);
            applyLiveState(page, {
              resources: payload.updated_resources,
              ships: payload.updated_ships,
              fleet_slots: payload.active_slots,
            });
            if (payload.fleet) {
              const prev = Array.isArray(rt.data.active_fleets) ? rt.data.active_fleets : [];
              const fleetId = payload.fleet.id;
              applyLiveState(page, {
                active_fleets: [payload.fleet, ...prev.filter((f) => f.id !== fleetId)],
              });
            }
            if (res.state) {
              applyActionState(res, "fleet_send_success");
            } else {
              await refreshFleetState(page);
            }
            page.querySelectorAll("[data-ship-input]").forEach((inp) => { inp.value = "0"; });
            const mInp = page.querySelector("[data-fleet-res-metal]");
            const cInp = page.querySelector("[data-fleet-res-crystal]");
            const fInp = page.querySelector("[data-fleet-res-fuel-cells]");
            if (mInp) mInp.value = "0";
            if (cInp) cInp.value = "0";
            if (fInp) fInp.value = "0";
            schedulePreview(page);
          } else {
            if (errorEl) {
              errorEl.textContent = reasonText(apiError(res));
              errorEl.hidden = false;
            }
            applyActionState(res, "fleet_send_error");
          }
        } catch (_) {
          if (errorEl) {
            errorEl.textContent = reasonText("generic");
            errorEl.hidden = false;
          }
        } finally {
          rt.sending = false;
          if (submitBtn) submitBtn.disabled = !(rt.lastPreview && rt.lastPreview.can_send);
        }
        return;
      }

      if (!page) return;
      const rt = getFleetRuntime(page);
      const form = getForm(page);

      const massForm = e.target.closest("#fleet-mass-expo-form");
      if (massForm && page.contains(massForm)) {
        e.preventDefault();
        if (massForm.dataset.submitting === "1") return;
        massForm.dataset.submitting = "1";
        const massBtn = massForm.querySelector('button[type="submit"]');
        const massResult = page.querySelector("[data-fleet-mass-result]");
        if (massBtn) massBtn.disabled = true;
        if (massResult) { massResult.hidden = true; massResult.textContent = ""; }
        const presetId = page.querySelector("[data-fleet-mass-preset]")?.value;
        const waves = parseInt(page.querySelector("[data-fleet-mass-waves]")?.value || "1", 10);
        if (!presetId) {
          massForm.dataset.submitting = "0";
          if (massBtn) massBtn.disabled = false;
          return;
        }
        try {
          const res = await GC.fetchGameAction("/api/fleet/mass-expedition", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              origin_planet_id: rt.data.planet_id,
              preset_id: parseInt(presetId, 10),
              waves,
            }),
          });
          if (res?.ok) {
            const data = fleetPayload(res);
            const started = (data.started || []).length;
            const skipped = (data.skipped || []).length;
            if (massResult) {
              massResult.textContent = tt("fleet_mass_expo_result", "Started %(started)s, skipped %(skipped)s.")
                .replace("%(started)s", String(started)).replace("%(skipped)s", String(skipped));
              massResult.hidden = false;
            }
            showNotify(tt("fleet_mass_expo_success", "Mass expedition launched."), "success");
            await refreshFleetState(page);
            schedulePreview(page);
          } else {
            showNotify(reasonText(apiError(res)), "error");
          }
        } catch (_) {
          showNotify(reasonText("generic"), "error");
        } finally {
          massForm.dataset.submitting = "0";
          if (massBtn) massBtn.disabled = false;
        }
      }
    });
  }

  function initFleet() {
    bindFleetOnce();
    const page = document.getElementById("fleet-page");
    if (!page || page.dataset.ready !== "1") return;

    const rt = getFleetRuntime(page);
    rt.data = parseFleetPageData(page);
    if (rt.data?.planet_id) page.dataset.planetId = String(rt.data.planet_id);
    if (typeof GC.refreshFleetState === "function") GC.refreshFleetState(page);

    const fuelResource = rt.data.fuel_resource || page.dataset.fuelResource || "fuel_cells";
    const fuelLabelEl = page.querySelector("[data-fuel-resource-label]");
    if (fuelLabelEl) {
      fuelLabelEl.textContent = fleetFuelLabel((k, f) => t(k, f), fuelResource);
    }

    const tickFleetCountdowns = () => {
      const p = document.getElementById("fleet-page");
      if (!p || p.dataset.ready !== "1") return;
      updateMovementCountdowns(getApproxServerNow());
    };
    tickFleetCountdowns();
    GC.startProgressTicker();
    if (typeof GC.initHudSelects === "function") GC.initHudSelects(page);
    applyFleetUrlPrefill(page);
  }

  function applyFleetUrlPrefill(page) {
    const params = new URLSearchParams(window.location.search);
    const form = page.querySelector("#fleet-send-form");
    if (!form) return;
    const mission = params.get("mission");
    const g = params.get("target_galaxy");
    const s = params.get("target_system");
    const p = params.get("target_position");
    if (mission) {
      const ms = form.querySelector("[data-fleet-mission]");
      if (ms) {
        ms.value = mission;
        if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(ms);
      }
      const colonizeRow = page.querySelector("[data-fleet-colonize-row]");
      if (colonizeRow) colonizeRow.hidden = mission !== "colonize";
      if (mission === "expedition" && p == null) {
        let expPos = 16;
        try {
          const st = JSON.parse(page.querySelector("#fleet-page-state")?.textContent || "{}");
          expPos = parseInt(st.expedition_position || "16", 10) || 16;
        } catch (_) {}
        const posInp = form.querySelector('[name="target_position"]');
        if (posInp) posInp.value = String(expPos);
      }
    }
    if (g != null) form.querySelector('[name="target_galaxy"]').value = g;
    if (s != null) form.querySelector('[name="target_system"]').value = s;
    if (p != null) form.querySelector('[name="target_position"]').value = p;
    const colonyName = params.get("colony_name");
    if (colonyName) {
      const inp = form.querySelector("[data-fleet-colony-name]");
      if (inp) inp.value = colonyName;
    }
    if (typeof GC.syncExpeditionMissionTarget === "function") {
      GC.syncExpeditionMissionTarget(page);
    }
    GC.runFleetPreview(page);
  }

  let _shipyardRefreshTimer = null;
  let _shipyardUnitFinishKey = "";

  function scheduleShipyardRefreshFromState(immediate) {
    const page = document.getElementById("shipyard-page");
    if (!page || page.dataset.ready !== "1") return;
    if (_shipyardRefreshTimer != null) {
      clearTimeout(_shipyardRefreshTimer);
      _shipyardRefreshTimer = null;
    }
    _lastShipyardQueueSignature = "";
    const delay = immediate ? 0 : 150;
    _shipyardRefreshTimer = GC.setSafeTimeout(() => {
      _shipyardRefreshTimer = null;
      if (page.dataset.queueRefreshBusy === "1") return;
      page.dataset.queueRefreshBusy = "1";
      refreshShipyardState(page)
        .then((data) => {
          if (data?.current_ships) renderShipyardInventory(page, data.current_ships);
          _shipyardUnitFinishKey = "";
          if (typeof GC.refreshFleetState === "function") {
            const fleetPage = document.getElementById("fleet-page");
            if (fleetPage && fleetPage.dataset.ready === "1") GC.refreshFleetState(fleetPage);
          }
        })
        .finally(() => {
          delete page.dataset.queueRefreshBusy;
        });
    }, delay);
  }

  let _shipyardBound = false;
  let _shipyardPollIntervalId = null;
  let _lastShipyardQueueSignature = "";

  function stopShipyardTimers() {
    if (_shipyardPollIntervalId != null) {
      clearInterval(_shipyardPollIntervalId);
      _shipyardPollIntervalId = null;
    }
  }

  function startShipyardTimers() {
    stopShipyardTimers();
    const page = document.getElementById("shipyard-page");
    if (!page || page.dataset.ready !== "1") return;
    GC.startProgressTicker();
    _shipyardPollIntervalId = GC.setSafeInterval(() => {
      const p = document.getElementById("shipyard-page");
      if (!p || p.dataset.ready !== "1" || !document.body.contains(p)) {
        stopShipyardTimers();
        return;
      }
      if (!p.dataset.queueRefreshBusy) refreshShipyardState(p).catch(() => {});
    }, Math.max(3000, Number(GC.shipyardPollMs) || 5000));
  }

  function _shipyardQueueSignature(queueList, summary) {
    try {
      const count = summary?.count ?? (queueList?.length ?? 0);
      const items = (queueList || [])
        .map(
          (j) =>
            `${j.id}:${j.units_delivered ?? 0}:${j.amount_remaining ?? j.amount}:${j.next_finish_at || j.finish_at || 0}`
        )
        .join("|");
      return `${count}|${items}`;
    } catch (_) {
      return "";
    }
  }

  function _updateShipyardQueueSubtitle(count, limit, firstEta) {
    const subEl = document.querySelector("[data-shipyard-queue-subtitle]");
    if (!subEl) return;

    if (!count) {
      const fb = t("shipyard_queue_slots", "%(count)s / %(limit)s orders");
      _setIfChanged(
        subEl,
        fb.replace("%(count)s", "0").replace("%(limit)s", String(limit || 3))
      );
      return;
    }

    const jobsLabel = t("shipyard_queue_jobs", "Aufträge");
    const nextLabel = t("build_queue_next", "Nächste Fertigstellung in");
    const lim = limit || 3;
    const html = `${count}/${lim} ${jobsLabel} · ${nextLabel}: <span id="shipyard-queue-subtitle-eta">${firstEta}</span>`;
    if (subEl.innerHTML !== html) subEl.innerHTML = html;
  }

  function shipyardIconUrl(shipKey) {
    const sk = String(shipKey || "").trim();
    return `/static/img/ships/${sk}.svg`;
  }

  function renderShipyardQueue(page, queueData) {
    const list = page.querySelector("[data-shipyard-queue-list]");
    if (!list) return;
    const tt = (key, fb) => t(key, fb);
    const qd = queueData || { queue: [], summary: { count: 0, limit: 3, refund_percent: 60 } };
    const jobs = qd.queue || [];
    const summary = qd.summary || {};
    const count = summary.count ?? jobs.length;
    const limit = summary.limit ?? 3;
    const first = jobs.length ? jobs[0] : null;

    if (first && first.is_active && first.finish_at) {
      const finishTime = Number(first.finish_at || 0);
      const totalRaw = Number(first.order_total_seconds || first.total_seconds || 0);
      const now = getApproxServerNow();
      const remaining = Math.max(0, Math.floor(finishTime - (now || 0)));
      const total = totalRaw > 0 ? Math.floor(totalRaw) : Math.max(1, remaining + 1);
      SHIPYARDQ.active.finishTime = finishTime;
      SHIPYARDQ.active.totalSeconds = total;
    } else {
      SHIPYARDQ.active.finishTime = 0;
      SHIPYARDQ.active.totalSeconds = 0;
    }

    const sig = _shipyardQueueSignature(jobs, summary);
    const firstEta =
      typeof summary?.first_finish_in !== "undefined"
        ? formatEta(summary.first_finish_in)
        : formatEta(first?.order_remaining ?? first?.remaining ?? 0);

    if (sig === _lastShipyardQueueSignature) {
      const finishTime = first ? Number(first.finish_at || 0) : 0;
      const nextUnitFinish = first ? Number(first.next_finish_at || 0) : 0;
      const now = getApproxServerNow();
      const overdue =
        (finishTime > 0 && finishTime <= now) ||
        (nextUnitFinish > 0 && nextUnitFinish <= now);
      if (!overdue) {
        _updateShipyardQueueSubtitle(count, limit, firstEta);
        GC.startProgressTicker();
        return;
      }
    }
    _lastShipyardQueueSignature = sig;

    _updateShipyardQueueSubtitle(count, limit, firstEta);
    list.replaceChildren();

    if (!jobs.length) {
      const empty = document.createElement("p");
      empty.className = "shipyard-empty";
      empty.dataset.shipyardQueueEmpty = "1";
      empty.textContent = tt("shipyard_queue_empty", "No ships in production.");
      list.appendChild(empty);
      if (!_hasActiveProgressJobs()) GC.stopProgressTicker();
      return;
    }

    const wrap = document.createElement("div");
    wrap.className = "shipyard-queue-list-inner";

    jobs.forEach((job, index) => {
      const isActive = Boolean(job.is_active || index === 0);
      const shipName = tt(`fleet_ship_${job.ship_key}`, job.ship_key);
      const totalUnits = Math.max(1, Number(job.amount_total || job.amount || 1));
      const delivered = Math.max(0, Number(job.units_delivered || 0));
      const remainingUnits = Math.max(0, Number(job.amount_remaining ?? totalUnits - delivered));
      const progressLabel = tt("shipyard_queue_progress", "%(done)s / %(total)s")
        .replace("%(done)s", fmtNumber(delivered))
        .replace("%(total)s", fmtNumber(totalUnits));
      const orderRemaining = parseInt(job.order_remaining ?? job.remaining, 10) || 0;
      const orderTotal = Math.max(
        1,
        parseInt(job.order_total_seconds || job.total_seconds, 10) || orderRemaining + 1
      );
      const pct = isActive ? Math.max(0, Math.min(100, 100 * (1 - orderRemaining / orderTotal))) : 0;
      const iconSrc = job.icon || shipyardIconUrl(job.ship_key);

      const art = document.createElement("article");
      art.className = `shipyard-job${isActive ? " shipyard-job-active" : " shipyard-job-queued"}`;
      art.dataset.queueJobId = String(job.id);
      if (isActive) {
        art.dataset.finishTime = String(job.finish_at || 0);
        art.dataset.nextFinishTime = String(job.next_finish_at || 0);
        art.dataset.total = String(orderTotal);
      }

      const icon = document.createElement("div");
      icon.className = "shipyard-job-icon";
      const img = document.createElement("img");
      img.src = iconSrc;
      img.alt = "";
      img.loading = "lazy";
      img.onerror = function onShipyardIconError() {
        this.onerror = null;
        this.src = shipyardIconUrl(job.ship_key).replace(".svg", ".png");
      };
      icon.appendChild(img);

      const body = document.createElement("div");
      body.className = "shipyard-job-body";

      const header = document.createElement("div");
      header.className = "job-header";
      const nameEl = document.createElement("span");
      nameEl.className = "job-name";
      nameEl.textContent =
        totalUnits > 1 ? `${shipName} · ${progressLabel}` : shipName;
      const timeEl = document.createElement("span");
      timeEl.className = `job-time${isActive ? "" : " job-time-muted"}`;
      if (isActive) timeEl.id = "shipyard-eta-live";
      timeEl.textContent = isActive
        ? formatEta(orderRemaining)
        : tt("status_in_queue", "In Warteschlange");
      header.append(nameEl, timeEl);

      const bar = document.createElement("div");
      bar.className = "build-bar build-bar-large";
      const fill = document.createElement("div");
      fill.className = "build-bar-fill gc-progress-smooth";
      if (isActive) fill.id = "shipyard-bar-fill-live";
      fill.style.width = `${isActive ? pct : 0}%`;
      fill.setAttribute("role", "progressbar");
      fill.setAttribute("aria-valuenow", String(isActive ? pct : 0));
      fill.setAttribute("aria-valuemin", "0");
      fill.setAttribute("aria-valuemax", "100");
      bar.appendChild(fill);

      const actions = document.createElement("div");
      actions.className = "shipyard-queue-job-actions job-actions";
      const upBtn = document.createElement("button");
      upBtn.type = "button";
      upBtn.className = "gc-btn gc-btn-ghost gc-btn-xs";
      upBtn.dataset.shipyardQueueUp = String(job.id);
      upBtn.setAttribute("aria-label", tt("shipyard_queue_move_up", "Raise priority"));
      upBtn.textContent = "▲";
      if (index === 0) upBtn.disabled = true;
      const downBtn = document.createElement("button");
      downBtn.type = "button";
      downBtn.className = "gc-btn gc-btn-ghost gc-btn-xs";
      downBtn.dataset.shipyardQueueDown = String(job.id);
      downBtn.setAttribute("aria-label", tt("shipyard_queue_move_down", "Lower priority"));
      downBtn.textContent = "▼";
      if (index === jobs.length - 1) downBtn.disabled = true;
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "gc-btn gc-btn-ghost gc-btn-xs gc-btn-danger";
      cancelBtn.dataset.shipyardQueueCancel = String(job.id);
      cancelBtn.textContent = tt("shipyard_queue_cancel_btn", "Cancel");
      actions.append(upBtn, downBtn, cancelBtn);

      const badge = document.createElement("span");
      badge.className = isActive ? "job-badge-active" : "job-badge-queued";
      badge.textContent = isActive
        ? tt("buildings_btn_active", "Aktiv")
        : `#${index + 1}`;

      body.append(header, bar, actions, badge);
      art.append(icon, body);
      wrap.appendChild(art);
    });

    list.appendChild(wrap);
    GC.startProgressTicker();
  }

  function parseShipyardPageData(page) {
    const el = document.getElementById("shipyard-page-state");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || "{}");
    } catch (_) {
      return null;
    }
  }

  function renderShipyardInventory(page, ships) {
    const inv = page.querySelector("[data-shipyard-inventory]");
    if (!inv) return;
    const tt = (key, fb) => t(key, fb);
    const entries = Object.entries(ships || {}).filter(([, qty]) => Number(qty) > 0);
    inv.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "shipyard-empty";
      empty.dataset.shipyardNoShips = "1";
      empty.textContent = tt("shipyard_no_ships", "No ships on this planet.");
      inv.appendChild(empty);
      return;
    }
    entries.sort(([a], [b]) => a.localeCompare(b));
    entries.forEach(([sk, qty]) => {
      const row = document.createElement("div");
      row.className = "shipyard-inventory-row";
      row.dataset.invShip = sk;
      const nameBtn = document.createElement("button");
      nameBtn.type = "button";
      nameBtn.className = "gc-ship-detail-trigger shipyard-ship-name";
      nameBtn.dataset.shipDetail = sk;
      nameBtn.title = tt("ship_detail_open", "View ship properties");
      nameBtn.textContent = tt(`fleet_ship_${sk}`, sk);
      const qtyEl = document.createElement("span");
      qtyEl.className = "shipyard-ship-qty gc-mono";
      qtyEl.textContent = fmtNumber(Number(qty) || 0);
      row.append(nameBtn, qtyEl);
      inv.appendChild(row);
    });
  }

  function applyShipyardState(page, data) {
    if (!page || !data) return;
    const tt = (key, fb) => t(key, fb);

    if (data.planet_id) page.dataset.planetId = String(data.planet_id);

    if (data.orbital_shipyard_level != null) {
      page.dataset.shipyardLevel = String(data.orbital_shipyard_level);
      const lvlEl = page.querySelector("[data-shipyard-level-label]");
      if (lvlEl) {
        const lvlText = tt("shipyard_level_value", "Level %(level)s");
        lvlEl.textContent = lvlText.replace("%(level)s", fmtNumber(data.orbital_shipyard_level));
      }
    }

    if (data.planet_name) {
      const scopeEl = page.querySelector("[data-shipyard-planet-scope]");
      if (scopeEl) {
        const label = tt("shipyard_planet_scope", "Active planet: %(name)s").replace(
          "%(name)s",
          String(data.planet_name)
        );
        scopeEl.textContent = label;
        let coordsEl = scopeEl.querySelector("[data-shipyard-planet-coords]");
        if (data.planet_coords) {
          if (!coordsEl) {
            coordsEl = document.createElement("span");
            coordsEl.className = "shipyard-planet-coords";
            coordsEl.dataset.shipyardPlanetCoords = "1";
            scopeEl.appendChild(document.createTextNode(" "));
            scopeEl.appendChild(coordsEl);
          }
          coordsEl.textContent = `(${data.planet_coords})`;
        } else if (coordsEl) {
          coordsEl.remove();
        }
      }
    }

    const res = data.resources || {};
    page.querySelectorAll("[data-sy-res]").forEach((node) => {
      const key = node.getAttribute("data-sy-res");
      if (key && res[key] != null) node.textContent = fmtNumber(Number(res[key]) || 0);
    });

    if (data.current_ships) renderShipyardInventory(page, data.current_ships);
    if (data.shipyard_queue) renderShipyardQueue(page, data.shipyard_queue);

    (data.buildable_ships || []).forEach((ship) => {
      const card = page.querySelector(`[data-ship-card="${ship.ship_key}"]`);
      if (!card || card.dataset.unlocked !== "1") return;
      const btn = card.querySelector("[data-shipyard-build]");
      const maxBtn = card.querySelector("[data-shipyard-max]");
      if (btn) {
        btn.disabled = !ship.can_build;
        btn.dataset.canBuild = ship.can_build ? "1" : "0";
        if (btn.dataset.building !== "1") btn.classList.remove("is-loading");
      }
      if (maxBtn) maxBtn.dataset.maxQty = String(ship.max_build || 0);
      const buildTimeEl = card.querySelector(".shipyard-ship-build-time");
      if (buildTimeEl && ship.build_seconds != null) {
        const tpl = tt("shipyard_build_time_per_unit", "Build time: %(seconds)s s per ship");
        buildTimeEl.textContent = tpl.replace("%(seconds)s", fmtNumber(Number(ship.build_seconds) || 0));
      }
      const warn = card.querySelector(".shipyard-hint-warn");
      if (warn) {
        if (ship.can_build) {
          warn.hidden = true;
        } else {
          warn.hidden = false;
          const br = ship.block_reason || "not_enough_resources";
          warn.dataset.shipyardBlockReason = br;
          warn.textContent = tt(
            `shipyard_block_${br}`,
            tt("shipyard_not_enough_resources", "Not enough resources for this build.")
          );
        }
      }
    });
  }

  async function refreshShipyardState(page) {
    const planetId = parseInt(page.dataset.planetId || "0", 10);
    const q = planetId ? `?planet_id=${planetId}` : "";
    const res = await GC.fetchGameAction(`/api/shipyard${q}`, { method: "GET" });
    if (res?.ok && res.data) {
      applyShipyardState(page, res.data);
      return res.data;
    }
    return null;
  }

  function bindShipyardOnce() {
    if (_shipyardBound) return;
    _shipyardBound = true;
    const tt = (key, fallback) => t(key, fallback);
    const apiError = (res) => (res && (res.error || res.reason)) || "generic";
    const reasonText = (reason) => tt(`shipyard_error_${reason}`, tt(`fleet_error_${reason}`, reason || "Error"));

    document.addEventListener("click", async (e) => {
      const page = document.getElementById("shipyard-page");
      if (!page || page.dataset.ready !== "1") return;

      const maxBtn = e.target.closest("[data-shipyard-max]");
      if (maxBtn && page.contains(maxBtn)) {
        e.preventDefault();
        const shipKey = maxBtn.getAttribute("data-shipyard-max");
        const qtyInp = page.querySelector(`[data-shipyard-qty="${shipKey}"]`);
        const maxQty = parseInt(maxBtn.dataset.maxQty || "0", 10);
        if (qtyInp && maxQty > 0) qtyInp.value = String(maxQty);
        return;
      }

      const cancelBtn = e.target.closest("[data-shipyard-queue-cancel]");
      if (cancelBtn && page.contains(cancelBtn)) {
        e.preventDefault();
        const jobId = parseInt(cancelBtn.getAttribute("data-shipyard-queue-cancel") || "0", 10);
        const planetId = parseInt(page.dataset.planetId || "0", 10);
        if (!jobId) return;
        cancelBtn.disabled = true;
        try {
          const res = await GC.fetchGameAction("/api/shipyard/queue/cancel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job_id: jobId, planet_id: planetId || undefined }),
          });
          if (res?.ok) {
            showNotify(tt("shipyard_cancel_ok", "Order cancelled."), "success");
            if (res.data) applyShipyardState(page, res.data);
            else await refreshShipyardState(page);
            if (typeof GC.refreshGameState === "function") await GC.refreshGameState("shipyard_cancel");
          } else {
            showNotify(reasonText(res?.error || apiError(res)), "error");
          }
        } catch (_) {
          showNotify(reasonText("generic"), "error");
        } finally {
          cancelBtn.disabled = false;
        }
        return;
      }

      const moveUp = e.target.closest("[data-shipyard-queue-up]");
      const moveDown = e.target.closest("[data-shipyard-queue-down]");
      const moveBtn = moveUp || moveDown;
      if (moveBtn && page.contains(moveBtn)) {
        e.preventDefault();
        const jobId = parseInt(
          moveBtn.getAttribute("data-shipyard-queue-up") ||
          moveBtn.getAttribute("data-shipyard-queue-down") || "0",
          10
        );
        const planetId = parseInt(page.dataset.planetId || "0", 10);
        if (!jobId) return;
        moveBtn.disabled = true;
        try {
          const res = await GC.fetchGameAction("/api/shipyard/queue/move", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              job_id: jobId,
              direction: moveUp ? "up" : "down",
              planet_id: planetId || undefined,
            }),
          });
          if (res?.ok) {
            if (res.data) applyShipyardState(page, res.data);
            else await refreshShipyardState(page);
          } else {
            showNotify(reasonText(res?.error || apiError(res)), "error");
          }
        } catch (_) {
          showNotify(reasonText("generic"), "error");
        } finally {
          moveBtn.disabled = false;
        }
        return;
      }

      const buildBtn = e.target.closest("[data-shipyard-build]");
      if (!buildBtn || !page.contains(buildBtn) || buildBtn.disabled) return;
      if (buildBtn.dataset.building === "1" || buildBtn.dataset.canBuild === "0") return;
      e.preventDefault();
      const shipKey = buildBtn.getAttribute("data-shipyard-build");
      const qtyInp = page.querySelector(`[data-shipyard-qty="${shipKey}"]`);
      const amount = parseInt(qtyInp?.value || "1", 10) || 1;
      const planetId = parseInt(page.dataset.planetId || "0", 10);
      buildBtn.dataset.building = "1";
      buildBtn.disabled = true;
      buildBtn.classList.add("is-loading");
      try {
        const res = await GC.fetchGameAction("/api/shipyard/build", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ship_key: shipKey, amount, planet_id: planetId || undefined }),
        });
        if (res?.ok) {
          showNotify(tt("shipyard_queue_enqueued", "Ships queued for construction."), "success");
          if (res.data) applyShipyardState(page, res.data);
          else await refreshShipyardState(page);
          if (typeof GC.refreshGameState === "function") await GC.refreshGameState("shipyard_build");
        } else {
          const errKey = res?.error || apiError(res);
          showNotify(reasonText(errKey), "error");
        }
      } catch (_) {
        showNotify(reasonText("generic"), "error");
      } finally {
        delete buildBtn.dataset.building;
        buildBtn.classList.remove("is-loading");
        buildBtn.disabled = buildBtn.dataset.canBuild !== "1";
      }
    });
  }

  function initShipyard() {
    bindShipyardOnce();
    const page = document.getElementById("shipyard-page");
    if (!page || page.dataset.ready !== "1") return;
    const data = parseShipyardPageData(page);
    if (!data) return;
    applyShipyardState(page, data);
    startShipyardTimers();
    GC.registerCleanup(stopShipyardTimers);
    GC.startProgressTicker();
  }

  function initExchangePanel() {
    const panel = document.getElementById("gc-exchange-panel");
    if (!panel || panel.dataset.disabled === "1") return;

    const page = document.getElementById("trader-hub-page");
    const form = panel.querySelector("#gc-exchange-form");
    const amountInput = panel.querySelector("#gc-exchange-amount");
    const routeSelect = panel.querySelector("[data-exchange-route]");
    const previewEl = panel.querySelector("[data-exchange-preview]");
    const receiveSummaryEl = panel.querySelector("[data-exchange-receive-summary]");
    const errorEl = panel.querySelector("[data-exchange-error]");
    const remainingEl = page?.querySelector("[data-exchange-daily-remaining]") || panel.querySelector("[data-exchange-daily-remaining]");
    const dailyLimitEl = page?.querySelector("[data-exchange-daily-limit]");
    const submitBtn = panel.querySelector(".gc-exchange-submit");
    const rateDisplayEl = panel.querySelector("[data-exchange-rate-display]");
    const giveTiles = panel.querySelectorAll("[data-exchange-give]");
    const receiveTiles = panel.querySelectorAll("[data-exchange-receive]");
    if (!form || !amountInput || !previewEl) return;

    const tt = (key, fallback) => t(key, fallback);
    const iconBase = "/static/icons/";
    const resourceLabels = {
      metal: () => tt("resource_metal", "Ferronit"),
      crystal: () => tt("resource_crystal", "Crytite"),
      fuel_cells: () => tt("resource_fuel_cells", "Fuel cells"),
    };
    const ROUTES = {
      metal_to_crystal: { from: "metal", to: "crystal" },
      crystal_to_metal: { from: "crystal", to: "metal" },
      metal_to_fuel_cells: { from: "metal", to: "fuel_cells" },
      crystal_to_fuel_cells: { from: "crystal", to: "fuel_cells" },
      fuel_cells_to_metal: { from: "fuel_cells", to: "metal" },
      fuel_cells_to_crystal: { from: "fuel_cells", to: "crystal" },
    };
    const ROUTE_BY_PAIR = {
      "metal:crystal": "metal_to_crystal",
      "crystal:metal": "crystal_to_metal",
      "metal:fuel_cells": "metal_to_fuel_cells",
      "crystal:fuel_cells": "crystal_to_fuel_cells",
      "fuel_cells:metal": "fuel_cells_to_metal",
      "fuel_cells:crystal": "fuel_cells_to_crystal",
    };

    const readRates = () => ({
      m2c: parseFloat(panel.dataset.rateM2c || "0.8"),
      c2m: parseFloat(panel.dataset.rateC2m || "0.8"),
      fuelMetalPer: parseInt(panel.dataset.fuelMetalPer || "45", 10),
      fuelCrystalPer: parseInt(panel.dataset.fuelCrystalPer || "28", 10),
      minAmount: parseInt(panel.dataset.min || "100", 10),
      fuelMin: parseInt(panel.dataset.fuelMin || "10", 10),
    });

    const reasonText = (reason) => tt(`exchange_error_${reason}`, tt("exchange_error_generic", "Exchange failed."));

    const selectedDirection = () => panel.dataset.dir || routeSelect?.value || "metal_to_crystal";

    const routeParts = (dir) => ROUTES[dir] || ROUTES.metal_to_crystal;

    const directionForPair = (give, receive) => ROUTE_BY_PAIR[`${give}:${receive}`] || null;

    const alternateReceive = (give, currentReceive) => {
      if (give === "metal") return currentReceive === "crystal" ? "fuel_cells" : "crystal";
      if (give === "crystal") return currentReceive === "metal" ? "fuel_cells" : "metal";
      return currentReceive === "metal" ? "crystal" : "metal";
    };

    const alternateGive = (receive, currentGive) => {
      if (receive === "metal") return currentGive === "crystal" ? "fuel_cells" : "crystal";
      if (receive === "crystal") return currentGive === "metal" ? "fuel_cells" : "metal";
      return currentGive === "metal" ? "crystal" : "metal";
    };

    const updateTileStates = (give, receive) => {
      giveTiles.forEach((btn) => {
        const active = btn.getAttribute("data-exchange-give") === give;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
      receiveTiles.forEach((btn) => {
        const active = btn.getAttribute("data-exchange-receive") === receive;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
    };

    const minForRoute = (dir) => {
      const cfg = readRates();
      const { from, to } = routeParts(dir);
      if (from === "fuel_cells") return cfg.fuelMin;
      if (to === "fuel_cells") {
        const per = from === "metal" ? cfg.fuelMetalPer : cfg.fuelCrystalPer;
        return Math.max(cfg.minAmount, per);
      }
      return cfg.minAmount;
    };

    const computeReceive = (dir, amount) => {
      const cfg = readRates();
      const { from, to } = routeParts(dir);
      const raw = parseInt(String(amount || "0"), 10);
      if (!raw || raw <= 0) return 0;
      if (from === "metal" && to === "crystal") return Math.floor(raw * cfg.m2c);
      if (from === "crystal" && to === "metal") return Math.floor(raw * cfg.c2m);
      if (from === "metal" && to === "fuel_cells") return Math.floor(raw / Math.max(1, cfg.fuelMetalPer));
      if (from === "crystal" && to === "fuel_cells") return Math.floor(raw / Math.max(1, cfg.fuelCrystalPer));
      if (from === "fuel_cells" && to === "metal") return raw * Math.max(1, cfg.fuelMetalPer);
      if (from === "fuel_cells" && to === "crystal") return raw * Math.max(1, cfg.fuelCrystalPer);
      return 0;
    };

    const displayRate = (dir) => {
      const cfg = readRates();
      const { from, to } = routeParts(dir);
      if (from === "metal" && to === "crystal") return cfg.m2c;
      if (from === "crystal" && to === "metal") return cfg.c2m;
      if (from === "metal" && to === "fuel_cells") return 1 / Math.max(1, cfg.fuelMetalPer);
      if (from === "crystal" && to === "fuel_cells") return 1 / Math.max(1, cfg.fuelCrystalPer);
      if (from === "fuel_cells" && to === "metal") return cfg.fuelMetalPer;
      if (from === "fuel_cells" && to === "crystal") return cfg.fuelCrystalPer;
      return 0;
    };

    const formatRate = (rate) => (rate >= 1 ? String(Math.round(rate)) : rate.toFixed(3).replace(/\.?0+$/, ""));

    const setDirection = (dir) => {
      const next = ROUTES[dir] ? dir : "metal_to_crystal";
      panel.dataset.dir = next;
      if (routeSelect && routeSelect.value !== next) routeSelect.value = next;
      const { from, to } = routeParts(next);
      updateTileStates(from, to);
      if (rateDisplayEl) rateDisplayEl.textContent = formatRate(displayRate(next));
      const minNow = minForRoute(next);
      panel.dataset.routeMin = String(minNow);
      amountInput.min = String(minNow);
      amountInput.dataset.exchangeMin = String(minNow);
      if (!amountInput.value || parseInt(amountInput.value, 10) < minNow) {
        amountInput.value = String(minNow);
      }
      updatePreview();
    };

    const setResourcePair = (give, receive) => {
      let nextGive = give;
      let nextReceive = receive;
      if (nextGive === nextReceive) {
        nextReceive = alternateReceive(nextGive, nextReceive);
      }
      let dir = directionForPair(nextGive, nextReceive);
      if (!dir) {
        nextGive = alternateGive(nextReceive, nextGive);
        dir = directionForPair(nextGive, nextReceive) || "metal_to_crystal";
      }
      setDirection(dir);
    };

    const updatePreview = () => {
      const raw = parseInt(amountInput.value || "0", 10);
      const minNow = parseInt(panel.dataset.routeMin || String(minForRoute(selectedDirection())), 10);
      const dir = selectedDirection();
      const { to } = routeParts(dir);
      if (!raw || raw < minNow) {
        previewEl.textContent = "–";
        if (receiveSummaryEl) receiveSummaryEl.textContent = "–";
        return;
      }
      const receive = computeReceive(dir, raw);
      const receiveLabel = resourceLabels[to]();
      previewEl.textContent = receive.toLocaleString();
      if (receiveSummaryEl) {
        receiveSummaryEl.textContent = `${receive.toLocaleString()} ${receiveLabel}`;
      }
    };

    const patchExchangeFromState = (exchange) => {
      if (!exchange) return;
      if (typeof exchange.daily_remaining === "number" && remainingEl) {
        remainingEl.textContent = fmtNumber(exchange.daily_remaining);
      }
      if (typeof exchange.daily_limit === "number" && dailyLimitEl) {
        dailyLimitEl.textContent = fmtNumber(exchange.daily_limit);
      }
      if (typeof exchange.rate_metal_to_crystal === "number") {
        panel.dataset.rateM2c = String(exchange.rate_metal_to_crystal);
      }
      if (typeof exchange.rate_crystal_to_metal === "number") {
        panel.dataset.rateC2m = String(exchange.rate_crystal_to_metal);
      }
      if (typeof exchange.fuel_metal_per_unit === "number") {
        panel.dataset.fuelMetalPer = String(exchange.fuel_metal_per_unit);
      }
      if (typeof exchange.fuel_crystal_per_unit === "number") {
        panel.dataset.fuelCrystalPer = String(exchange.fuel_crystal_per_unit);
      }
      if (typeof exchange.fuel_min_units === "number") {
        panel.dataset.fuelMin = String(exchange.fuel_min_units);
      }
      if (typeof exchange.min_amount === "number") {
        panel.dataset.min = String(exchange.min_amount);
      }
      setDirection(selectedDirection());
    };

    if (!panel.dataset.exchangeBound) {
      panel.dataset.exchangeBound = "1";

      giveTiles.forEach((btn) => {
        btn.addEventListener("click", () => {
          const give = btn.getAttribute("data-exchange-give") || "metal";
          const { to } = routeParts(selectedDirection());
          setResourcePair(give, to);
        });
      });
      receiveTiles.forEach((btn) => {
        btn.addEventListener("click", () => {
          const receive = btn.getAttribute("data-exchange-receive") || "crystal";
          const { from } = routeParts(selectedDirection());
          setResourcePair(from, receive);
        });
      });
      if (routeSelect) {
        routeSelect.addEventListener("change", () => {
          setDirection(routeSelect.value || "metal_to_crystal");
        });
      }
      amountInput.addEventListener("input", updatePreview);

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (errorEl) {
          errorEl.hidden = true;
          errorEl.textContent = "";
        }

        const amount = parseInt(amountInput.value || "0", 10);
        const dir = selectedDirection();
        const minNow = minForRoute(dir);
        if (!amount || amount < minNow) {
          if (errorEl) {
            errorEl.textContent = reasonText("below_minimum");
            errorEl.hidden = false;
          }
          return;
        }

        const { from, to } = routeParts(dir);
        const receive = computeReceive(dir, amount);
        const confirmMsg = tt(
          "exchange_confirm_prompt",
          "Exchange %(amount)s %(give)s for ~%(receive)s %(get)s?"
        )
          .replace("%(amount)s", String(amount))
          .replace("%(give)s", resourceLabels[from]())
          .replace("%(receive)s", String(receive))
          .replace("%(get)s", resourceLabels[to]());

        if (!window.confirm(confirmMsg)) return;

        if (submitBtn) submitBtn.disabled = true;
        try {
          const res = await GC.fetchGameAction("/api/exchange", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
            body: JSON.stringify({ direction: dir, from, to, amount }),
          });
          if (res?.ok) {
            amountInput.value = String(minNow);
            updatePreview();
            applyActionState(res, "exchange_success");
            showNotify(tt("exchange_success", "Exchange completed."), "success");
          } else {
            applyActionState(res, "exchange_error");
            if (errorEl) {
              errorEl.textContent = reasonText(res?.reason);
              errorEl.hidden = false;
            }
          }
        } catch (_) {
          if (errorEl) {
            errorEl.textContent = reasonText("generic");
            errorEl.hidden = false;
          }
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    }

    panel._patchExchangeFromState = patchExchangeFromState;
    if (!amountInput.value) amountInput.value = String(minForRoute(selectedDirection()));
    setDirection(selectedDirection());
  }

  function renderScrapyardRows(ships) {
    const tt = (key, fallback, vars) => t(key, fallback, vars);
    if (!Array.isArray(ships) || ships.length === 0) {
      return `<p class="hint" data-scrapyard-empty>${tt("scrapyard_empty", "No ships to recycle.")}</p>`;
    }
    return ships.map((row) => {
      const key = String(row.ship_key || "");
      const amount = Number(row.amount || 0);
      const icon = String(row.icon || "");
      const shipName = tt(`fleet_ship_${key}`, key);
      const minM = Number(row.preview_refund_min?.metal || 0);
      const maxM = Number(row.preview_refund_max?.metal || 0);
      const minC = Number(row.preview_refund_min?.crystal || 0);
      const maxC = Number(row.preview_refund_max?.crystal || 0);
      const haveLabel = tt("scrapyard_have", "Available: %(count)s").replace("%(count)s", amount.toLocaleString());
      const refundLabel = tt("scrapyard_refund_range", "Refund");
      const metalLabel = tt("resource_metal", "Ferronit");
      const crystalLabel = tt("resource_crystal", "Crytite");
      const recycleLabel = tt("scrapyard_recycle_btn", "Recycle");
      const amountLabel = tt("scrapyard_amount", "Amount");
      return `
        <article class="gc-scrapyard-row gc-trader-scrap-card" data-scrap-ship="${key}" data-scrap-max="${amount}">
          <div class="gc-trader-scrap-icon-wrap">
            <img src="${icon}" alt="" class="gc-scrapyard-ship-icon" width="44" height="44" loading="lazy">
          </div>
          <div class="gc-trader-scrap-body">
            <span class="gc-scrapyard-ship-name">${shipName.toUpperCase()}</span>
            <span class="gc-scrapyard-have gc-mono">${haveLabel}</span>
            <span class="gc-trader-scrap-refund hint gc-mono">
              ${tt("scrapyard_refund_estimate", "Refund (approx.)")}:
              ${minM.toLocaleString()}–${maxM.toLocaleString()} ${metalLabel},
              ${minC.toLocaleString()}–${maxC.toLocaleString()} ${crystalLabel}
            </span>
          </div>
          <div class="gc-scrapyard-actions gc-trader-scrap-actions">
            <input type="number" class="gc-trader-input gc-scrapyard-qty" min="1" max="${amount}" value="1"
                   data-scrap-qty="${key}" aria-label="${amountLabel}">
            <button type="button" class="gc-btn gc-btn-secondary gc-trader-scrap-btn" data-scrap-recycle="${key}">
              ${recycleLabel.toUpperCase()}
            </button>
          </div>
        </article>`;
    }).join("");
  }

  function initScrapyardPanel() {
    const panel = document.getElementById("gc-scrapyard-panel");
    if (!panel || panel.dataset.disabled === "1") return;
    if (panel.dataset.scrapyardBound) return;
    panel.dataset.scrapyardBound = "1";

    const tt = (key, fallback) => t(key, fallback);
    const errorEl = panel.querySelector("[data-scrapyard-error]");
    const reasonText = (reason) => tt(`scrapyard_error_${reason}`, tt("scrapyard_error_generic", "Recycle failed."));

    panel.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-scrap-recycle]");
      if (!btn) return;
      const shipKey = btn.getAttribute("data-scrap-recycle");
      const row = btn.closest("[data-scrap-ship]");
      const qtyInp = row?.querySelector(`[data-scrap-qty="${shipKey}"]`);
      const amount = parseInt(qtyInp?.value || "0", 10);
      const max = parseInt(row?.getAttribute("data-scrap-max") || "0", 10);
      if (!amount || amount > max) return;
      if (!window.confirm(tt("scrapyard_confirm", "Recycle ships for partial refund?"))) return;

      btn.disabled = true;
      if (errorEl) { errorEl.hidden = true; errorEl.textContent = ""; }
      try {
        const res = await GC.fetchGameAction("/api/trader/scrapyard", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          body: JSON.stringify({ ship_key: shipKey, amount }),
        });
        if (res?.ok) {
          applyActionState(res, "scrapyard_success");
          showNotify(tt("scrapyard_success", "Ships recycled."), "success");
        } else {
          applyActionState(res, "scrapyard_error");
          if (errorEl) {
            errorEl.textContent = reasonText(res?.reason);
            errorEl.hidden = false;
          }
        }
      } catch (_) {
        if (errorEl) {
          errorEl.textContent = reasonText("generic");
          errorEl.hidden = false;
        }
      } finally {
        btn.disabled = false;
      }
    });
  }

  function patchExchangePanel(exchange) {
    const panel = document.getElementById("gc-exchange-panel");
    if (panel && typeof panel._patchExchangeFromState === "function") {
      panel._patchExchangeFromState(exchange);
    }
  }

  function patchScrapyardPanel(scrapyard) {
    const panel = document.getElementById("gc-scrapyard-panel");
    if (!panel || !scrapyard || scrapyard.ready === false) return;
    const list = panel.querySelector("[data-scrapyard-list]");
    if (!list || !Array.isArray(scrapyard.ships)) return;
    list.innerHTML = renderScrapyardRows(scrapyard.ships);
  }

  function patchTraderHubBalance(metal, crystal, storageMetal, storageCrystal, fuelCells) {
    const page = document.getElementById("trader-hub-page");
    if (!page) return;
    const metalVal = page.querySelector('[data-res="metal"]');
    const crystalVal = page.querySelector('[data-res="crystal"]');
    const fuelVal = page.querySelector('[data-res="fuel_cells"]');
    const metalCap = page.querySelector('[data-cap="metal"]');
    const crystalCap = page.querySelector('[data-cap="crystal"]');
    const metalBar = page.querySelector('[data-res-bar="metal"]');
    const crystalBar = page.querySelector('[data-res-bar="crystal"]');
    if (metalVal) _setIfChanged(metalVal, fmtNumber(metal));
    if (crystalVal) _setIfChanged(crystalVal, fmtNumber(crystal));
    if (fuelVal && typeof fuelCells === "number") _setIfChanged(fuelVal, fmtNumber(fuelCells));
    if (metalCap && storageMetal > 0) _setIfChanged(metalCap, `/ ${fmtNumber(storageMetal)}`);
    if (crystalCap && storageCrystal > 0) _setIfChanged(crystalCap, `/ ${fmtNumber(storageCrystal)}`);
    if (metalBar && storageMetal > 0) {
      const pct = Math.min(100, Math.floor((Number(metal) / storageMetal) * 100));
      metalBar.style.width = `${pct}%`;
    }
    if (crystalBar && storageCrystal > 0) {
      const pct = Math.min(100, Math.floor((Number(crystal) / storageCrystal) * 100));
      crystalBar.style.width = `${pct}%`;
    }
  }

  function initResearch() {}

  function syncPlanetEvolutionResearchTicker() {
    if (!document.querySelector(".planet-evolution-page .pe-planet-research-active")) return;
    updatePlanetEvolutionResearchProgress();
    GC.startProgressTicker();
  }

  function planetSwitchReasonText(reason) {
    if (!reason) return t("pe_error_generic", "Aktion fehlgeschlagen.");
    const pe = t(`pe_reason_${reason}`, "");
    if (pe && pe !== `pe_reason_${reason}`) return pe;
    return String(reason);
  }

  function closeAllHudSelects(except) {
    document.querySelectorAll(".gc-hud-select.is-open").forEach((wrap) => {
      if (except && wrap === except) return;
      const menu = wrap.querySelector(".gc-hud-select-menu");
      const trigger = wrap.querySelector(".gc-hud-select-trigger");
      if (menu) menu.hidden = true;
      wrap.classList.remove("is-open");
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
  }

  function syncHudSelect(select) {
    if (!select || !select._gcHudSelect) return;
    const { menu, valueEl, trigger } = select._gcHudSelect;
    const opt = select.options[select.selectedIndex];
    if (valueEl) valueEl.textContent = opt ? opt.textContent.trim() : "";
    if (trigger) trigger.disabled = !!select.disabled;
    if (menu) {
      menu.querySelectorAll(".gc-hud-select-item").forEach((item) => {
        const active = item.dataset.value === select.value;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", active ? "true" : "false");
      });
    }
  }

  function rebuildHudSelect(select) {
    if (!select || !select._gcHudSelect) return;
    const { menu } = select._gcHudSelect;
    if (!menu) return;
    menu.innerHTML = "";
    Array.from(select.options).forEach((opt) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "gc-hud-select-item";
      btn.dataset.value = opt.value;
      btn.setAttribute("role", "option");
      btn.textContent = opt.textContent.trim();
      if (opt.disabled) btn.disabled = true;
      menu.appendChild(btn);
    });
    syncHudSelect(select);
  }

  function enhanceHudSelect(select) {
    if (!select || select.dataset.gcHudSelectEnhanced === "1") return;
    select.dataset.gcHudSelectEnhanced = "1";
    select.classList.add("gc-hud-select-native");

    const wrap = document.createElement("div");
    wrap.className = "gc-hud-select";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "gc-hud-panel gc-hud-select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    if (select.id) trigger.setAttribute("aria-controls", `${select.id}-hud-menu`);

    const valueEl = document.createElement("span");
    valueEl.className = "gc-hud-select-value";

    const chevron = document.createElement("span");
    chevron.className = "gc-hud-select-chevron";
    chevron.setAttribute("aria-hidden", "true");
    chevron.textContent = "▾";

    trigger.appendChild(valueEl);
    trigger.appendChild(chevron);

    const menu = document.createElement("div");
    menu.className = "gc-hud-select-menu";
    menu.hidden = true;
    menu.setAttribute("role", "listbox");
    if (select.id) menu.id = `${select.id}-hud-menu`;

    wrap.insertBefore(trigger, select);
    wrap.appendChild(menu);

    select._gcHudSelect = { wrap, trigger, menu, valueEl };

    rebuildHudSelect(select);

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      if (select.disabled || trigger.disabled) return;
      const isOpen = !menu.hidden;
      closeAllHudSelects();
      if (!isOpen) {
        menu.hidden = false;
        wrap.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
      }
    });

    menu.addEventListener("click", (e) => {
      const item = e.target.closest(".gc-hud-select-item");
      if (!item || item.disabled) return;
      const next = item.dataset.value ?? "";
      if (select.value !== next) {
        select.value = next;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        syncHudSelect(select);
      }
      menu.hidden = true;
      wrap.classList.remove("is-open");
      trigger.setAttribute("aria-expanded", "false");
    });

    select.addEventListener("change", () => syncHudSelect(select));
  }

  function initHudSelects(root) {
    if (!GC._hudSelectBound) {
      GC._hudSelectBound = true;
      document.addEventListener("click", () => closeAllHudSelects());
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeAllHudSelects();
      });
    }
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("select[data-gc-hud-select]").forEach(enhanceHudSelect);
  }

  GC.initHudSelects = initHudSelects;
  GC.syncHudSelect = syncHudSelect;
  GC.rebuildHudSelect = rebuildHudSelect;

  function rebuildHeaderPlanetSwitcher(planets) {
    const root = document.getElementById("gc-planet-switcher");
    if (!root || !Array.isArray(planets) || !planets.length) return;

    const active = planets.find((p) => p.is_active) || planets[0];
    const multi = planets.length > 1;

    root.dataset.multi = multi ? "1" : "0";
    root.dataset.activePlanetId = String(active.planet_id || "");

    const trigger = document.getElementById("gc-planet-switcher-trigger");
    const nameEl = root.querySelector("[data-planet-switcher-name]");
    const coordEl = root.querySelector("[data-planet-switcher-coord]");
    if (nameEl) nameEl.textContent = active.name || "";
    if (coordEl) {
      const coord = active.coordinates_formatted || "";
      coordEl.textContent = coord;
      coordEl.hidden = !coord;
    }

    if (trigger) {
      trigger.setAttribute("aria-haspopup", multi ? "listbox" : "false");
      if (multi) {
        trigger.removeAttribute("aria-disabled");
        trigger.setAttribute("aria-controls", "gc-planet-switcher-menu");
      } else {
        trigger.setAttribute("aria-disabled", "true");
        trigger.removeAttribute("aria-controls");
      }
    }

    let chevron = root.querySelector(".gc-planet-switcher-chevron");
    if (multi && !chevron && trigger) {
      chevron = document.createElement("span");
      chevron.className = "gc-planet-switcher-chevron";
      chevron.setAttribute("aria-hidden", "true");
      chevron.textContent = "▾";
      trigger.appendChild(chevron);
    } else if (!multi && chevron) {
      chevron.remove();
    }

    let menu = document.getElementById("gc-planet-switcher-menu");
    if (!multi) {
      if (menu) menu.remove();
      root.classList.remove("is-open");
      document.querySelector(".gc-header-cmd")?.classList.remove("gc-header-planet-menu-open");
      if (trigger) trigger.setAttribute("aria-expanded", "false");
      return;
    }

    if (!menu) {
      menu = document.createElement("div");
      menu.id = "gc-planet-switcher-menu";
      menu.className = "gc-planet-switcher-menu";
      menu.setAttribute("role", "listbox");
      menu.setAttribute("aria-label", t("header_planet_switcher_menu", "Deine Kolonien"));
      menu.hidden = true;
      root.appendChild(menu);
    }

    menu.replaceChildren();
    const hwLabel = t("header_planet_homeworld", "Heimatwelt");
    const colLabel = t("header_planet_colony", "Kolonie");

    planets.forEach((p) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "gc-planet-switcher-item" + (p.is_active ? " is-active" : "");
      btn.setAttribute("role", "option");
      btn.setAttribute("aria-selected", p.is_active ? "true" : "false");
      btn.dataset.planetId = String(p.planet_id || "");
      btn.dataset.planetName = p.name || "";
      btn.dataset.planetCoord = p.coordinates_formatted || "";
      btn.dataset.planetClassKey = p.planet_class_label_key || "";
      btn.dataset.planetClass = p.planet_class || "";
      btn.dataset.planetHomeworld = p.is_homeworld ? "1" : "0";

      const nameSpan = document.createElement("span");
      nameSpan.className = "gc-planet-switcher-item-name";
      nameSpan.textContent = p.name || "";

      const metaSpan = document.createElement("span");
      metaSpan.className = "gc-planet-switcher-item-meta gc-mono";
      const coord = p.coordinates_formatted || "";
      const suffix = p.is_homeworld ? hwLabel : colLabel;
      metaSpan.textContent = coord ? `${coord} · ${suffix}` : suffix;

      btn.appendChild(nameSpan);
      btn.appendChild(metaSpan);
      menu.appendChild(btn);
    });
  }

  function updateHeaderPlanetSwitcherFromPlanets(planets) {
    rebuildHeaderPlanetSwitcher(planets);
  }

  GC.updateHeaderPlanetSwitcherFromState = function updateHeaderPlanetSwitcherFromState(data) {
    if (!data) return;
    if (Array.isArray(data.planets) && data.planets.length) {
      rebuildHeaderPlanetSwitcher(data.planets);
      return;
    }
    const ap = data.active_planet;
    if (ap && ap.planet_id) {
      updateHeaderPlanetSwitcherFromPlanets([
        {
          planet_id: ap.planet_id,
          name: ap.name,
          coordinates_formatted: ap.coordinates_formatted,
          planet_class: ap.planet_class,
          planet_class_label_key: ap.planet_class_label_key,
          is_active: true,
        },
      ]);
      return;
    }
    const activeId = Number(data.active_planet_id || 0);
    if (!activeId) return;
    const root = document.getElementById("gc-planet-switcher");
    if (!root) return;
    root.dataset.activePlanetId = String(activeId);
    root.querySelectorAll(".gc-planet-switcher-item").forEach((btn) => {
      const pid = Number(btn.dataset.planetId || 0);
      const on = pid === activeId;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      if (on && btn.dataset.planetName) {
        const nameEl = root.querySelector("[data-planet-switcher-name]");
        if (nameEl) nameEl.textContent = btn.dataset.planetName;
        const coordEl = root.querySelector("[data-planet-switcher-coord]");
        if (coordEl) {
          const coord = btn.dataset.planetCoord || "";
          coordEl.textContent = coord;
          coordEl.hidden = !coord;
        }
      }
    });
  };

  function initHeaderPlanetSwitcher() {
    if (GC._headerPlanetSwitcherBound) return;
    GC._headerPlanetSwitcherBound = true;

    const root = document.getElementById("gc-planet-switcher");
    if (!root) return;

    const trigger = document.getElementById("gc-planet-switcher-trigger");
    const menu = document.getElementById("gc-planet-switcher-menu");
    const multi = root.dataset.multi === "1";

    const headerEl = document.querySelector(".gc-header-cmd");

    const closeMenu = () => {
      if (!menu) return;
      menu.hidden = true;
      root.classList.remove("is-open");
      headerEl?.classList.remove("gc-header-planet-menu-open");
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    };

    const openMenu = () => {
      if (!menu || !multi) return;
      menu.hidden = false;
      root.classList.add("is-open");
      headerEl?.classList.add("gc-header-planet-menu-open");
      if (trigger) trigger.setAttribute("aria-expanded", "true");
    };

    if (trigger && multi) {
      trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        if (menu && menu.hidden) openMenu();
        else closeMenu();
      });
    }

    document.addEventListener("click", (e) => {
      if (!root.contains(e.target)) closeMenu();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMenu();
    });

    root.addEventListener("click", async (e) => {
      const item = e.target.closest(".gc-planet-switcher-item");
      if (!item || !root.contains(item)) return;
      if (item.classList.contains("is-active")) {
        closeMenu();
        return;
      }
      const planetId = parseInt(item.dataset.planetId || "0", 10);
      if (!planetId) return;

      root.classList.add("is-busy");
      item.disabled = true;
      closeMenu();

      try {
        const res = await GC.fetchGameAction("/api/planets/active", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          body: JSON.stringify({ planet_id: planetId }),
        });
        if (res?.ok) {
          applyActionState(res, "planet_switch");
          if (Array.isArray(res.planets)) {
            updateHeaderPlanetSwitcherFromPlanets(res.planets);
          } else if (res.state) {
            GC.updateHeaderPlanetSwitcherFromState(res.state);
          }
          const name = item.dataset.planetName || "";
          ["build-queue-planet-label", "research-planet-label"].forEach((id) => {
            const el = document.getElementById(id);
            if (!el || !name) return;
            el.textContent = id === "build-queue-planet-label" ? `· ${name}` : name;
          });
          await GC.reloadCurrentPage();
        } else {
          showNotify(planetSwitchReasonText(res?.reason), "error");
        }
      } catch (err) {
        if (!err?.authRedirect) {
          showNotify(t("pe_error_generic", "Aktion fehlgeschlagen."), "error");
        }
      } finally {
        root.classList.remove("is-busy");
        item.disabled = false;
      }
    });
  }

  function bindPlanetEvolutionOnce() {
    if (GC._peActionsBound) return;
    GC._peActionsBound = true;

    const tt = (key, fallback) => t(key, fallback);
    const PE_REASON_ALIASES = {
      requirements: "research_locked",
    };
    const reasonText = (reason) => {
      if (!reason) return tt("pe_error_generic", "Aktion fehlgeschlagen.");
      const key = PE_REASON_ALIASES[reason] || reason;
      const pe = tt(`pe_reason_${key}`, "");
      if (pe && pe !== `pe_reason_${key}`) return pe;
      const alt = tt(`reason_${key}`, "");
      if (alt && alt !== `reason_${key}`) return alt;
      return reason;
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

    const tabPanels = { events: "events", research: "research", policies: "policies", history: "history" };

    const peHighlightEl = (el) => {
      if (!el) return;
      el.classList.remove("pe-highlight-pulse");
      void el.offsetWidth;
      el.classList.add("pe-highlight-pulse");
      window.setTimeout(() => el.classList.remove("pe-highlight-pulse"), 2600);
    };

    const openPeSection = (sectionId) => {
      const section = document.getElementById(sectionId);
      if (section && section.tagName === "DETAILS") section.open = true;
    };

    const focusPeTarget = (root, { action, target, highlight, techKey }) => {
      const actionType = action || "focus_section";
      const sectionId = scrollTargets[target] || `pe-section-${target}`;
      const needsTab = actionType === "focus_tab" || Boolean(tabPanels[target]);
      if (needsTab && tabPanels[target]) {
        const tab = root.querySelector(`.pe-sec-tab[data-panel="${tabPanels[target]}"]`);
        if (tab) tab.click();
        else openPeSection(sectionId);
      } else if (sectionId) {
        openPeSection(sectionId);
      }

      let el = null;
      const highlightId = highlight || sectionId;
      if (highlightId) el = document.getElementById(highlightId);
      if (!el && techKey) {
        el = root.querySelector(`#pe-research-card-${techKey}, [data-tech-key="${techKey}"]`);
      }
      if (!el) el = document.getElementById(scrollTargets[target] || `pe-section-${target}`);

      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        peHighlightEl(el);
      }
    };

    document.addEventListener("click", async (e) => {
      const root = document.querySelector(".planet-evolution-page");
      if (!root) return;

      const actionBtn = e.target.closest(".pe-action-btn");
      if (actionBtn && root.contains(actionBtn)) {
        focusPeTarget(root, {
          action: actionBtn.dataset.ctaAction,
          target: actionBtn.dataset.ctaTarget,
          highlight: actionBtn.dataset.ctaHighlight,
          techKey: actionBtn.dataset.techKey,
        });
        return;
      }

      const scrollBtn = e.target.closest(".pe-scroll-btn");
      if (scrollBtn && root.contains(scrollBtn)) {
        focusPeTarget(root, { target: scrollBtn.dataset.scroll });
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

      const researchBtn = e.target.closest(".pe-research-btn");
      if (researchBtn && root.contains(researchBtn)) {
        if (researchBtn.disabled || researchBtn.getAttribute("aria-disabled") === "true") return;
        researchBtn.disabled = true;
        const planetId = parseInt(researchBtn.dataset.planetId || "0", 10);
        const techKey = researchBtn.dataset.techKey || "";
        const requestId = (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
        let res;
        try {
          res = await postAction(`/api/planets/${planetId}/research/start`, { tech_key: techKey, request_id: requestId });
          if (res?.ok) await GC.reloadCurrentPage();
          else showNotify(reasonText(res?.reason), "error");
        } finally {
          if (!res?.ok) researchBtn.disabled = false;
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

    });
  }

  function initGcPopoversOnce() {
    if (GC._popoverBound) return;
    GC._popoverBound = true;

    let activePopover = null;
    let activeTrigger = null;

    const closePopover = () => {
      if (activePopover) {
        activePopover.remove();
        activePopover = null;
      }
      if (activeTrigger) {
        activeTrigger.setAttribute("aria-expanded", "false");
        activeTrigger = null;
      }
    };

    const positionPopover = (pop, trigger) => {
      const rect = trigger.getBoundingClientRect();
      const margin = 8;
      pop.style.visibility = "hidden";
      pop.style.display = "block";
      const popRect = pop.getBoundingClientRect();
      let left = rect.left + rect.width / 2 - popRect.width / 2;
      left = Math.max(margin, Math.min(left, window.innerWidth - popRect.width - margin));
      let top = rect.bottom + margin;
      if (top + popRect.height > window.innerHeight - margin) {
        top = Math.max(margin, rect.top - popRect.height - margin);
      }
      pop.style.left = `${left}px`;
      pop.style.top = `${top}px`;
      pop.style.visibility = "visible";
    };

    const openPopover = (trigger) => {
      const text = (trigger.dataset.popover || trigger.getAttribute("title") || "").trim();
      if (!text) return;
      closePopover();

      const pop = document.createElement("div");
      pop.className = "gc-popover";
      pop.setAttribute("role", "tooltip");
      pop.textContent = text;
      document.body.appendChild(pop);
      positionPopover(pop, trigger);

      activePopover = pop;
      activeTrigger = trigger;
      trigger.setAttribute("aria-expanded", "true");
    };

    document.addEventListener("click", (e) => {
      const trigger = e.target.closest(".gc-popover-trigger");
      if (trigger) {
        e.preventDefault();
        e.stopPropagation();
        if (activeTrigger === trigger) closePopover();
        else openPopover(trigger);
        return;
      }
      if (!e.target.closest(".gc-popover")) closePopover();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closePopover();
    });

    window.addEventListener("resize", closePopover);
    window.addEventListener("scroll", closePopover, true);
  }

  function initPlanetEvolution() {
    if (!document.querySelector(".planet-evolution-page")) return;
    bindPlanetEvolutionOnce();
    syncPlanetEvolutionResearchTicker();
  }

  // =========================
  // Galaxy page — prefetch adjacent systems (PJAX)
  // =========================
  const _galaxyPrefetchUrls = new Set();

  function getGalaxyPageRoot() {
    return document.getElementById("galaxy-page-root") || document.querySelector(".galaxy-page");
  }

  function prefetchGalaxyHref(href) {
    if (!href || _galaxyPrefetchUrls.has(href)) return;
    if (_galaxyPrefetchUrls.size >= 48) return;
    try {
      const url = new URL(href, window.location.origin);
      if (url.origin !== window.location.origin) return;
      if (!url.pathname.endsWith("/galaxy")) return;
    } catch (_) {
      return;
    }
    _galaxyPrefetchUrls.add(href);
    const link = document.createElement("link");
    link.rel = "prefetch";
    link.as = "document";
    link.href = href;
    document.head.appendChild(link);
  }

  function prefetchGalaxyAdjacent() {
    const page = getGalaxyPageRoot();
    if (!page) return;
    if (page.dataset.prevUrl) prefetchGalaxyHref(page.dataset.prevUrl);
    if (page.dataset.nextUrl) prefetchGalaxyHref(page.dataset.nextUrl);
    page.querySelectorAll(".galaxy-nav-step[href], .galaxy-range-item[href]").forEach((a) => {
      prefetchGalaxyHref(a.href);
    });
  }

  function initGalaxy() {
    if (!document.querySelector(".galaxy-page")) return;
    prefetchGalaxyAdjacent();
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
    {
      id: "total",
      scoreKey: "total_score",
      rankKey: "rank_total",
      labelKey: "ranking_tab_total",
      colLabelKey: "ranking_col_total",
      fallback: "Total",
      colFallback: "Total Score",
    },
    {
      id: "building",
      scoreKey: "building_score",
      rankKey: "rank_building",
      labelKey: "ranking_tab_buildings",
      colLabelKey: "ranking_col_buildings",
      fallback: "Buildings",
      colFallback: "Buildings",
    },
    {
      id: "research",
      scoreKey: "research_score",
      rankKey: "rank_research",
      labelKey: "ranking_tab_research",
      colLabelKey: "ranking_col_research",
      fallback: "Research",
      colFallback: "Research",
    },
    {
      id: "evolution",
      scoreKey: "evolution_score",
      rankKey: null,
      labelKey: "ranking_tab_evolution",
      colLabelKey: "ranking_col_evolution",
      fallback: "Planet Evolution",
      colFallback: "Evolution",
    },
    {
      id: "fleet",
      scoreKey: "fleet_score",
      rankKey: "rank_fleet",
      labelKey: "ranking_tab_fleet",
      colLabelKey: "ranking_col_fleet",
      fallback: "Fleet",
      colFallback: "Fleet",
    },
    {
      id: "defense",
      scoreKey: "defense_score",
      rankKey: null,
      labelKey: "ranking_tab_defense",
      colLabelKey: "ranking_col_defense",
      fallback: "Defense",
      colFallback: "Defense",
    },
  ];

  function rankingColLabel(tab) {
    return rankingT(tab.colLabelKey || tab.labelKey, tab.colFallback || tab.fallback);
  }

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
      if (tab.id === "total" || tab.id === "building" || tab.id === "research" || tab.id === "fleet" || tab.id === "evolution") return true;
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
    const name = rankingEscapeHtml(row.commander_display || row.commander_name || "—");
    return `<span class="gc-ranking-player-name">${name}</span>`;
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
      `<span class="gc-ranking-my-label">${rankingEscapeHtml(rankingColLabel(tab))}</span>` +
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
    const scoreLabel = rankingEscapeHtml(rankingColLabel(tab));

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
  GC.modules.trader_hub = initTraderHub;
  GC.modules.fleet = initFleet;
  GC.modules.shipyard = initShipyard;
  GC.modules.buildings = initBuildings;
  GC.modules.research = initResearch;
  GC.modules.planet_evolution = initPlanetEvolution;
  GC.modules.galaxy = initGalaxy;
  GC.modules.ranking = function initRankingPage() {
    GC.initRanking();
  };
  GC.modules.techtree = function initTechtree() {};
  GC.modules.options = function initOptionsModule() {
    if (typeof GC.initOptionsPage === "function") {
      GC.initOptionsPage();
    } else {
      console.warn("[GC] options.js not loaded – Options forms inactive");
    }
  };

  const OPTIONS_FORM_ROUTES = {
    "options-form-player-name": {
      url: "/api/options/player-name",
      fields: ["player_name"],
      apply(form, data) {
        const name = data.player_name || "";
        const cur = document.getElementById("options-current-player-name");
        if (cur) cur.textContent = name || t("options_not_set", "—");
        const inp = form.querySelector('[name="player_name"]');
        if (inp) inp.value = name;
        const page = document.getElementById("options-page");
        if (page) page.setAttribute("data-player-name", name);
        const pid = page && page.getAttribute("data-player-id");
        if (pid && name) {
          const esc = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(String(pid)) : String(pid);
          document.querySelectorAll(`.gc-player-name[data-player-id="${esc}"]`).forEach((el) => {
            el.textContent = name;
            el.setAttribute("data-player-name", name);
          });
          document.querySelectorAll(".gc-hud-panel-user .gc-user-name").forEach((el) => {
            el.textContent = name;
            el.setAttribute("data-player-name", name);
          });
        }
        if (typeof GC.refreshGameState === "function") GC.refreshGameState("options_name_change");
      },
    },
    "options-form-email": {
      url: "/api/options/email",
      fields: ["email"],
      apply(form, data) {
        const email = data.email || "";
        const cur = document.getElementById("options-current-email");
        if (cur) cur.textContent = email || t("options_not_set", "—");
        const inp = form.querySelector('[name="email"]');
        if (inp) inp.value = email;
        const page = document.getElementById("options-page");
        if (page) page.setAttribute("data-email", email);
        if (typeof GC.initOptionsPage === "function") GC.initOptionsPage();
      },
    },
    "options-form-password": {
      url: "/api/options/password",
      fields: ["current_password", "new_password", "confirm_password"],
      apply(form) {
        form.reset();
      },
    },
  };

  function optionsFieldValue(form, name) {
    const el = form.querySelector(`[name="${name}"]`);
    return el ? String(el.value || "").trim() : "";
  }

  function setOptionsFormHint(form, text, isError) {
    const hint = form.querySelector(".gc-options-form-hint");
    if (!hint) return;
    hint.textContent = text || "";
    if (text) {
      hint.hidden = false;
      hint.removeAttribute("hidden");
    } else {
      hint.hidden = true;
    }
    hint.classList.toggle("gc-options-hint-error", Boolean(isError));
    hint.classList.toggle("gc-options-hint-success", Boolean(text) && !isError);
  }

  function setOptionsFormBusy(form, busy) {
    if (!form) return;
    form.dataset.gcSubmitting = busy ? "1" : "0";
    form.querySelectorAll('button[type="submit"]').forEach((btn) => {
      btn.disabled = busy;
    });
  }

  GC.runOptionsFormSave = async function runOptionsFormSave(form, ev) {
    if (ev && typeof ev.preventDefault === "function") ev.preventDefault();
    if (!form || !form.id) return false;

    const route = OPTIONS_FORM_ROUTES[form.id];
    if (!route) return false;
    if (form.dataset.gcSubmitting === "1") return false;

    setOptionsFormHint(form, "", false);
    setOptionsFormBusy(form, true);

    const payload = {};
    route.fields.forEach((name) => {
      payload[name] = optionsFieldValue(form, name);
    });

    try {
      if (typeof GC.fetchGameAction !== "function") {
        throw new Error("fetchGameAction missing");
      }
      const data = await GC.fetchGameAction(route.url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });

      if (!data || data.ok !== true) {
        const errKey = (data && data.error) || "options_error_invalid_name";
        const msg = t(errKey, errKey);
        setOptionsFormHint(form, msg, true);
        showNotify(msg, "error");
        return false;
      }

      const savedMsg = t("options_saved", "Gespeichert.");
      setOptionsFormHint(form, savedMsg, false);
      if (typeof route.apply === "function") route.apply(form, data.data || {});
      showNotify(savedMsg, "success");
      return true;
    } catch (err) {
      if (err && err.name === "AuthError") return false;
      const msg = t("options_error_invalid_name", "Eingabe ungültig.");
      setOptionsFormHint(form, msg, true);
      showNotify(msg, "error");
      return false;
    } finally {
      setOptionsFormBusy(form, false);
    }
  };

  GC.handleOptionsFormSubmit = GC.runOptionsFormSave;

  function initOptionsFormsCapture() {
    if (GC._optionsCaptureBound) return;
    GC._optionsCaptureBound = true;

    const dispatchSave = (form, ev) => {
      if (!form || !form.id || !OPTIONS_FORM_ROUTES[form.id]) return;
      if (ev) {
        ev.preventDefault();
        ev.stopPropagation();
      }
      void GC.runOptionsFormSave(form, ev);
    };

    document.addEventListener(
      "submit",
      (ev) => {
        const form = ev.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (!form.classList.contains("gc-options-form")) return;
        dispatchSave(form, ev);
      },
      true
    );

    document.addEventListener(
      "click",
      (ev) => {
        const btn = ev.target.closest("button.gc-options-save");
        if (!btn) return;
        const form = btn.closest("form.gc-options-form");
        if (!form) return;
        dispatchSave(form, ev);
      },
      true
    );
  }

  // =========================
  // PJAX navigation
  // =========================
  const PJAX_NAV_LINK =
    "a.gc-nav-link, a.gc-bottom-nav-item, a.gc-nav-drawer-link, a.gc-hud-panel-messages";

  function isPjaxEligibleLink(link) {
    if (!link || link.tagName !== "A") return false;
    if (link.hasAttribute("data-no-pjax") || link.target === "_blank" || link.hasAttribute("download")) {
      return false;
    }
    if (link.hasAttribute("data-player-card") || link.closest("[data-player-card]")) return false;
    if (link.matches(".btn-upgrade, .btn-research, a.logout-btn, a[href*='/logout']")) return false;
    const href = link.getAttribute("href");
    if (!href || href.startsWith("#") || href.startsWith("javascript:") || href.startsWith("mailto:")) {
      return false;
    }
    let dest;
    try {
      dest = new URL(href, window.location.origin);
      if (dest.origin !== window.location.origin) return false;
      if (dest.pathname.includes("/logout")) return false;
    } catch (_) {
      return false;
    }
    return !!(link.matches(PJAX_NAV_LINK) || link.closest("#main-content"));
  }

  function normalizePjaxUrl(url) {
    try {
      const u = new URL(url, window.location.origin);
      return `${u.pathname}${u.search}`;
    } catch (_) {
      return String(url || "");
    }
  }

  function pjaxNavigateFromLink(link) {
    const href = link.getAttribute("href");
    if (!href) return;
    if (link.dataset.pjaxBusy === "1") return;
    link.dataset.pjaxBusy = "1";
    Promise.resolve(GC.navigateTo(href)).finally(() => {
      link.dataset.pjaxBusy = "0";
    });
  }

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
    const target = normalizePjaxUrl(url);

    if (GC.pjaxInFlight && GC._pjaxTarget === target) {
      console.debug("[GC] PJAX dedupe", target);
      return GC.pjaxInFlight;
    }

    const current = normalizePjaxUrl(window.location.href);
    if (!push && target === current && !opts.force) {
      console.debug("[GC] PJAX skip same URL", target);
      return Promise.resolve();
    }

    if (GC._pjaxAbort) {
      try { GC._pjaxAbort.abort(); } catch (_) {}
    }

    GC._pjaxTarget = target;
    GC.pjaxInFlight = (async () => {
      const ctrl = new AbortController();
      GC._pjaxAbort = ctrl;
      try {
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

        GC.cleanupPage();

        const main = document.getElementById("main-content");
        main.innerHTML = newMain.innerHTML;
        if (doc.title) document.title = doc.title;

        const fetchedBody = doc.body;
        if (fetchedBody?.dataset && fetchedBody.dataset.endpoint !== undefined) {
          document.body.dataset.endpoint = fetchedBody.dataset.endpoint || "";
        }
        const landscape = fetchedBody?.style?.getPropertyValue("--planet-landscape");
        if (landscape && landscape.trim()) {
          document.body.classList.add("gc-has-planet-landscape");
          document.body.style.setProperty("--planet-landscape", landscape.trim());
        } else {
          document.body.classList.remove("gc-has-planet-landscape");
          document.body.style.removeProperty("--planet-landscape");
        }

        _syncNavActive(url);
        if (push) history.pushState({ gcPjax: true }, "", url);

        await GC.initPage({ force: true });
        if (document.querySelector(".galaxy-page")) prefetchGalaxyAdjacent();
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
        if (shouldRunGameLoop() && !_authLoopAborted && !GC.polling.running) {
          GC.startPolling(lastHadActiveJob || lastHadActiveResearch);
        }
      }
    })();

    return GC.pjaxInFlight;
  };

  function initPjax() {
    if (GC._pjaxBound) return;
    GC._pjaxBound = true;

    document.addEventListener("click", (e) => {
      if (e.defaultPrevented) return;
      const link = e.target.closest("a[href]");
      if (!isPjaxEligibleLink(link)) return;
      e.preventDefault();
      pjaxNavigateFromLink(link);
    });

    document.addEventListener("submit", (e) => {
      if (e.defaultPrevented) return;
      const form = e.target;
      if (!form || form.tagName !== "FORM" || form.hasAttribute("data-no-pjax")) return;
      if ((form.getAttribute("method") || "get").toLowerCase() !== "get") return;
      if (form.hasAttribute("data-validate")) return;
      if (!form.closest("#main-content")) return;
      e.preventDefault();
      let url;
      try {
        url = new URL(form.getAttribute("action") || window.location.pathname, window.location.origin);
      } catch (_) {
        return;
      }
      const fd = new FormData(form);
      url.search = "";
      fd.forEach((value, key) => {
        if (value != null && String(value).trim() !== "") url.searchParams.set(key, value);
      });
      GC.navigateTo(`${url.pathname}${url.search}`);
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

        const buildingType =
          upgradeEl.dataset.building ||
          (() => {
            const m = (upgradeEl.getAttribute("href") || "").match(/\/upgrade\/([^/?#]+)/);
            return m ? decodeURIComponent(m[1]) : "";
          })();
        const tab = _getActiveBuildingTab();

        if (!buildingType) {
          upgradeEl.dataset.busy = "0";
          GC.actionLocks.build = false;
          showNotify(t("msg_action_failed", "Aktion fehlgeschlagen. Bitte erneut versuchen."), "error");
          return;
        }

        try {
          const json = await GC.fetchGameAction("/api/buildings/upgrade", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ building_type: buildingType, tab, request_id: newRequestId() }),
          });
          applyActionState(json, json.ok ? "upgrade_success" : "upgrade_error");
          if (!json.ok) {
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
          if (!json.ok) {
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
          if (!json.ok) {
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
          if (!json.ok) {
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
      GC.refreshGameState("tab_visible");
      GC.startProgressTicker();
      if (typeof GC.initChat === "function") GC.initChat();
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
        setActiveBarButton("chat");
        if (typeof GC.openTChat === "function") {
          void Promise.resolve(GC.openTChat()).catch((err) => {
            console.error("[GC] openTChat failed", err);
          });
        } else if (typeof GC.initChat === "function") {
          void Promise.resolve(GC.initChat()).catch((err) => {
            console.error("[GC] initChat failed", err);
          });
        }
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

  const SHIP_DETAIL = {
    root: null,
    dialog: null,
    titleEl: null,
    content: null,
    loadingEl: null,
    errorEl: null,
    abort: null,
    open: false,
    currentKey: null,
    reqId: 0,
  };

  function cacheShipDetailElements() {
    if (SHIP_DETAIL.root && SHIP_DETAIL.content) return SHIP_DETAIL.root;
    SHIP_DETAIL.root = document.getElementById("gc-ship-detail-root");
    if (!SHIP_DETAIL.root) return null;
    SHIP_DETAIL.dialog = SHIP_DETAIL.root.querySelector(".gc-player-card-dialog");
    SHIP_DETAIL.titleEl = document.getElementById("gc-ship-detail-title");
    SHIP_DETAIL.content = SHIP_DETAIL.root.querySelector("[data-sd-content]");
    SHIP_DETAIL.loadingEl = SHIP_DETAIL.root.querySelector("[data-sd-loading]");
    SHIP_DETAIL.errorEl = SHIP_DETAIL.root.querySelector("[data-sd-error]");
    return SHIP_DETAIL.root;
  }

  function sdSetLoading(on) {
    cacheShipDetailElements();
    const show = !!on;
    if (SHIP_DETAIL.loadingEl) {
      SHIP_DETAIL.loadingEl.hidden = !show;
      SHIP_DETAIL.loadingEl.setAttribute("aria-hidden", show ? "false" : "true");
    }
    if (show && SHIP_DETAIL.errorEl) {
      SHIP_DETAIL.errorEl.hidden = true;
      SHIP_DETAIL.errorEl.textContent = "";
    }
    if (SHIP_DETAIL.root) {
      SHIP_DETAIL.root.classList.toggle("is-loading", show);
      SHIP_DETAIL.root.setAttribute("aria-busy", show ? "true" : "false");
    }
  }

  function sdSetError(msg) {
    cacheShipDetailElements();
    sdSetLoading(false);
    if (SHIP_DETAIL.content) SHIP_DETAIL.content.innerHTML = "";
    if (SHIP_DETAIL.errorEl) {
      SHIP_DETAIL.errorEl.textContent = msg || t("ship_detail_load_error", "Could not load ship data.");
      SHIP_DETAIL.errorEl.hidden = false;
      SHIP_DETAIL.errorEl.setAttribute("aria-hidden", "false");
    }
  }

  function sdClearError() {
    cacheShipDetailElements();
    if (SHIP_DETAIL.errorEl) {
      SHIP_DETAIL.errorEl.hidden = true;
      SHIP_DETAIL.errorEl.textContent = "";
      SHIP_DETAIL.errorEl.setAttribute("aria-hidden", "true");
    }
  }

  function sdAbortFetch() {
    if (SHIP_DETAIL.abort) {
      try { SHIP_DETAIL.abort.abort(); } catch (_) {}
      SHIP_DETAIL.abort = null;
    }
  }

  function sdResetModalState() {
    cacheShipDetailElements();
    sdAbortFetch();
    sdSetLoading(false);
    sdClearError();
    if (SHIP_DETAIL.content) SHIP_DETAIL.content.innerHTML = "";
    if (SHIP_DETAIL.dialog) SHIP_DETAIL.dialog.setAttribute("data-theme", "cyan");
    if (SHIP_DETAIL.titleEl) {
      SHIP_DETAIL.titleEl.textContent = t("ship_detail_title", "Ship specifications");
    }
  }

  function openShipDetailModal(focusClose) {
    const root = cacheShipDetailElements();
    if (!root) return;
    root.hidden = false;
    root.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-ship-detail-open");
    SHIP_DETAIL.open = true;
    if (focusClose) {
      const closeBtn = root.querySelector("[data-sd-close].gc-player-card-close");
      if (closeBtn) closeBtn.focus({ preventScroll: true });
    }
  }

  function closeShipDetailModal() {
    const root = cacheShipDetailElements();
    if (!root) return;
    sdResetModalState();
    root.hidden = true;
    root.setAttribute("aria-hidden", "true");
    document.body.classList.remove("gc-ship-detail-open");
    SHIP_DETAIL.open = false;
    SHIP_DETAIL.currentKey = null;
  }

  async function fetchShipDetailHtml(shipKey, reqToken) {
    sdAbortFetch();
    const ctrl = new AbortController();
    SHIP_DETAIL.abort = ctrl;
    const key = encodeURIComponent(String(shipKey || "").trim());
    try {
      const res = await fetch(`/api/ships/${key}`, {
        method: "GET",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "text/html",
        },
        signal: ctrl.signal,
      });
      if (reqToken !== SHIP_DETAIL.reqId) {
        return { ok: false, aborted: true };
      }
      const html = await res.text();
      if (reqToken !== SHIP_DETAIL.reqId) {
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
      if (SHIP_DETAIL.abort === ctrl) SHIP_DETAIL.abort = null;
    }
  }

  function mountShipDetailHtml(html) {
    cacheShipDetailElements();
    if (!SHIP_DETAIL.content) return;
    sdClearError();
    sdSetLoading(false);

    const wrap = document.createElement("div");
    wrap.innerHTML = html;
    const shell = wrap.querySelector(".gc-ship-detail-shell, .gc-player-card-shell");
    SHIP_DETAIL.content.innerHTML = "";
    if (shell) {
      SHIP_DETAIL.content.appendChild(shell);
      const nameEl = shell.querySelector(".gc-player-card-commander");
      if (nameEl && SHIP_DETAIL.titleEl) {
        SHIP_DETAIL.titleEl.textContent = nameEl.textContent.trim();
      }
      const theme = shell.getAttribute("data-theme") || "cyan";
      if (SHIP_DETAIL.dialog) SHIP_DETAIL.dialog.setAttribute("data-theme", theme);
    } else {
      SHIP_DETAIL.content.appendChild(wrap);
    }
  }

  function sdPrepareOpen(shipKey) {
    const key = String(shipKey || "").trim();
    if (!key) return false;
    const wasOpen = SHIP_DETAIL.open;
    SHIP_DETAIL.reqId += 1;
    SHIP_DETAIL.currentKey = key;
    sdResetModalState();
    openShipDetailModal(!wasOpen);
    sdSetLoading(true);
    return true;
  }

  async function loadShipDetail(shipKey) {
    if (!sdPrepareOpen(shipKey)) return;
    const reqToken = SHIP_DETAIL.reqId;
    try {
      const result = await fetchShipDetailHtml(shipKey, reqToken);
      if (result.aborted || reqToken !== SHIP_DETAIL.reqId) return;
      if (!result.ok) {
        if (result.html && result.html.includes("gc-ship-detail-shell")) {
          mountShipDetailHtml(result.html);
        } else {
          sdSetError(t("ship_detail_not_found", t("ship_detail_load_error", "Could not load ship data.")));
        }
        return;
      }
      mountShipDetailHtml(result.html);
    } catch (_) {
      if (reqToken !== SHIP_DETAIL.reqId) return;
      sdSetError(t("ship_detail_load_error", "Could not load ship data."));
    }
  }

  function initShipDetailOnce() {
    if (GC._shipDetailBound) return;
    GC._shipDetailBound = true;

    document.addEventListener("click", (e) => {
      const closeEl = e.target.closest("[data-sd-close]");
      if (closeEl) {
        const root = cacheShipDetailElements();
        if (root && SHIP_DETAIL.open) {
          e.preventDefault();
          closeShipDetailModal();
        }
        return;
      }

      const trigger = e.target.closest("[data-ship-detail]");
      if (!trigger) return;
      const shipKey = trigger.getAttribute("data-ship-detail");
      if (!shipKey) return;
      e.preventDefault();
      e.stopPropagation();
      loadShipDetail(shipKey);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const trigger = e.target.closest("[data-ship-detail]");
      if (!trigger || document.activeElement !== trigger) return;
      e.preventDefault();
      loadShipDetail(trigger.getAttribute("data-ship-detail"));
    });
  }

  GC.openShipDetail = loadShipDetail;
  GC.closeShipDetail = closeShipDetailModal;

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
      if (SHIP_DETAIL.open) closeShipDetailModal();
      else if (PLAYER_CARD.open) closePlayerCardModal();
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
    initOptionsFormsCapture();
    initSkipLink();
    initGameActions();
    bindPlanetEvolutionOnce();
    bindFleetOnce();
    initHeaderPlanetSwitcher();
    initGcPopoversOnce();
    initVisibilityPolling();
    initMobileNav();
    initSpecialPanel();
    initSupportModule();
    initStickyResourceBar();
    initPjax();
    initShipDetailOnce();
    initPlayerCardOnce();

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
