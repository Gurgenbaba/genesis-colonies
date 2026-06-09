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

  // supports "%(var)s" and "{var}" — single pass, unknown placeholders left intact
  function tf(key, vars = {}, fallback = "") {
    let s = t(key, fallback || key);
    if (typeof s !== "string") return fallback || "";
    s = String(s);

    s = s.replace(/%\(([^)]+)\)s/g, (_, k) => {
      if (!Object.prototype.hasOwnProperty.call(vars, k)) return `%(${k})s`;
      const v = vars[k];
      return v === undefined || v === null ? "" : String(v);
    });

    s = s.replace(/\{([^}]+)\}/g, (_, k) => {
      if (!Object.prototype.hasOwnProperty.call(vars, k)) return `{${k}}`;
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
  // Format helpers (mirrors game/number_format.py)
  // =========================
  function parseIntNumber(n) {
    if (typeof n === "number" && Number.isFinite(n)) return Math.trunc(n);
    const raw = String(n ?? "").trim();
    if (!raw) return 0;
    if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
    let cleaned = raw.replace(/\s/g, "");
    if (cleaned.includes(",") && cleaned.includes(".")) {
      cleaned = cleaned.replace(/\./g, "").replace(",", ".");
    } else if ((cleaned.match(/\./g) || []).length > 1) {
      cleaned = cleaned.replace(/\./g, "");
    } else if (cleaned.includes(",")) {
      cleaned = cleaned.replace(",", ".");
    }
    const num = Number(cleaned);
    return Number.isFinite(num) ? Math.trunc(num) : 0;
  }

  function formatCompactMantissa(val) {
    const absVal = Math.abs(val);
    let body;
    if (absVal >= 1000) body = Math.round(val).toString();
    else if (absVal >= 10) body = val.toFixed(1);
    else if (absVal >= 1) body = val.toFixed(1);
    else body = val.toFixed(2);
    if (body.includes(".")) {
      body = body.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
    }
    return body.replace(".", ",");
  }

  function fmtIntParts(n) {
    const num = parseIntNumber(n);
    const full = num.toLocaleString("de-DE", { maximumFractionDigits: 0 });
    const abs = Math.abs(num);
    if (abs < 10000000) return { display: full, full };

    if (abs >= 1e18) return { display: "∞", full };

    const sign = num < 0 ? "-" : "";
    let suffix;
    let div;
    if (abs >= 1e12) {
      suffix = "Bio.";
      div = 1e12;
    } else if (abs >= 1e9) {
      suffix = "Mrd.";
      div = 1e9;
    } else if (abs >= 1e6) {
      suffix = "Mio.";
      div = 1e6;
    } else {
      suffix = "Tsd.";
      div = 1e3;
    }

    const val = abs / div;
    const body = formatCompactMantissa(val);
    return { display: `${sign}${body} ${suffix}`, full };
  }

  function fmtNumber(n) {
    return fmtIntParts(n).display;
  }

  function fmtIntFull(n) {
    return parseIntNumber(n).toLocaleString("de-DE", { maximumFractionDigits: 0 });
  }

  function renderMonoCompact(n, prefix = "", suffix = "") {
    const p = fmtIntParts(n);
    const text = `${prefix}${p.display}${suffix}`;
    if (p.display === p.full && !prefix && !suffix) {
      return `<span class="gc-mono gc-num-compact">${text}</span>`;
    }
    const title = `${prefix}${p.full}${suffix}`.replace(/"/g, "&quot;");
    return `<span class="gc-mono gc-num-compact" title="${title}">${text}</span>`;
  }

  function renderCostVal(n) {
    const p = fmtIntParts(n);
    if (p.display === p.full) {
      return `<span class="gc-cost-val gc-num-compact">${p.display}</span>`;
    }
    return `<span class="gc-cost-val gc-num-compact" title="${p.full}">${p.display}</span>`;
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

  function forceServerTimeSync(serverTimeSec) {
    const v = Number(serverTimeSec);
    if (!Number.isFinite(v) || v <= 0) return;
    TIME.serverNow = v;
    TIME.clientPerfAt = performance.now();
  }

  function setServerTime(serverTimeSec) {
    const v = Number(serverTimeSec);
    if (!Number.isFinite(v) || v <= 0) return;
    if (TIME.serverNow && TIME.clientPerfAt) {
      const approx = TIME.serverNow + (performance.now() - TIME.clientPerfAt) / 1000;
      if (v < approx - 2) return;
      // GC-541: same poll snapshot must not reset perf anchor every tick
      if (Math.abs(v - approx) < 0.5) return;
    }
    forceServerTimeSync(v);
  }

  /** Normalize unix seconds, unix ms, or ISO finish timestamps. */
  function parseTimerTarget(raw) {
    if (raw == null || raw === "") return 0;
    if (typeof raw === "number") {
      if (!Number.isFinite(raw) || raw <= 0) return 0;
      return raw > 1e12 ? Math.floor(raw / 1000) : Math.floor(raw);
    }
    const s = String(raw).trim();
    if (!s) return 0;
    if (/^\d+(\.\d+)?$/.test(s)) {
      const n = Number(s);
      if (!Number.isFinite(n) || n <= 0) return 0;
      return n > 1e12 ? Math.floor(n / 1000) : Math.floor(n);
    }
    const parsed = Date.parse(s);
    if (Number.isFinite(parsed) && parsed > 0) return Math.floor(parsed / 1000);
    return 0;
  }

  /** Read canonical finish unix seconds from queue job payloads (build/research/shipyard). */
  function resolveQueueJobFinishTime(job) {
    if (!job || typeof job !== "object") return 0;
    return parseTimerTarget(
      job.countdown_at
      ?? job.finish_at
      ?? job.finish_time
      ?? job.next_countdown_at
      ?? job.next_finish_at
      ?? 0
    );
  }

  function resolveQueueJobCountdownAt(job) {
    if (!job || typeof job !== "object") return 0;
    return parseTimerTarget(
      job.countdown_at
      ?? job.next_countdown_at
      ?? job.finish_at
      ?? job.finish_time
      ?? job.next_finish_at
      ?? 0
    );
  }

  function resolveQueueJobRemaining(job) {
    if (!job || typeof job !== "object") return 0;
    const raw = job.remaining_seconds ?? job.order_remaining ?? job.remaining;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? Math.ceil(n) : 0;
  }

  /** Kanonische Queue-Regel: aktiver Job → finish_at; wartender Job → finish_at (Vorgänger + eigene Dauer). */
  function cardQueueTimerTarget(queueJob, isActive) {
    const finishAt = Math.floor(Number(queueJob.finish_at || 0));
    const startAt = Math.floor(Number(queueJob.start_at || 0));
    if (finishAt > 0) return finishAt;
    return isActive ? startAt : startAt;
  }

  function assignMonotonicServerRemaining(el, remaining, target) {
    if (!el) return;
    if (!Number.isFinite(remaining) || remaining < 0) {
      delete el.dataset.serverRemaining;
      return;
    }
    const next = Math.ceil(remaining);
    const prev = Number(el.dataset.serverRemaining);
    const prevTarget = parseTimerTarget(el.dataset.timerTarget || el.dataset.countdownAt || 0);
    const targetInt = parseTimerTarget(target || 0);
    if (targetInt > 0 && prevTarget > 0 && targetInt !== prevTarget) {
      el.dataset.serverRemaining = String(next);
      return;
    }
    if (!Number.isFinite(prev) || next <= prev) {
      el.dataset.serverRemaining = String(next);
    }
  }

  function applyQueueJobTimerAttrs(el, finishTime, kind, refreshOnZero, remaining) {
    if (!el || !finishTime) return;
    const target = parseTimerTarget(finishTime);
    if (!target) return;
    el.dataset.timerTarget = String(target);
    el.dataset.countdownAt = String(target);
    if (kind) el.dataset.timerKind = kind;
    if (refreshOnZero) el.dataset.refreshOnZero = refreshOnZero;
    if (el.dataset.refreshFiredAt && el.dataset.refreshFiredAt !== String(target)) {
      delete el.dataset.refreshFiredAt;
    }
    if (Number.isFinite(remaining) && remaining >= 0) {
      assignMonotonicServerRemaining(el, remaining, target);
    } else {
      delete el.dataset.serverRemaining;
    }
  }

  function queueJobRemainingSeconds(finishAt, serverNow, serverRemaining) {
    const endAt = parseTimerTarget(finishAt);
    if (!endAt) return 0;
    const now = Number.isFinite(serverNow) ? serverNow : getApproxServerNow();
    if (endAt <= now) return 0;
    const fromFinish = Math.ceil(endAt - now);
    const srv = Number(serverRemaining);
    if (Number.isFinite(srv) && srv >= 0) {
      if (srv <= 0 && fromFinish > 1) return fromFinish;
      // Ignore stale poll snapshots that still carry the full duration.
      if (srv > fromFinish + 1) return fromFinish;
      return Math.min(fromFinish, Math.max(0, Math.ceil(srv)));
    }
    return fromFinish;
  }

  /** Countdown label: floor so 0.9s shows 0s and completion can fire (avoids stuck at 1s). */
  function queueTimerDisplaySeconds(remaining) {
    return Math.max(0, Math.floor(Number(remaining) || 0));
  }

  function isQueueTimerComplete(remaining, finishAt, serverNow) {
    const finish = parseTimerTarget(finishAt);
    const now = Number.isFinite(serverNow) ? serverNow : getTimerServerNow();
    if (finish > 0 && finish <= now) return true;
    return queueTimerDisplaySeconds(remaining) <= 0;
  }

  function movementRemainingSeconds(countdownAt, serverNow, serverRemaining) {
    return queueJobRemainingSeconds(countdownAt, serverNow, serverRemaining);
  }

  function bootstrapServerTimeFromDom() {
    const raw = document.body?.dataset?.serverTime;
    if (!raw) return;
    if (TIME.serverNow && TIME.clientPerfAt) return;
    setServerTime(raw);
  }

  function resyncServerTimeFromDom(force) {
    const raw = document.body?.dataset?.serverTime;
    if (!raw) return;
    const v = Number(raw);
    if (!Number.isFinite(v) || v <= 0) return;
    if (force) {
      forceServerTimeSync(v);
      return;
    }
    bootstrapServerTimeFromDom();
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

  /** GC-547 — visual loops (rAF/ticker/CSS-driven updates) only when tab is visible. */
  function isTabVisible() {
    return typeof document === "undefined" || !document.hidden;
  }

  function shouldRunVisualLoops() {
    return shouldRunGameLoop() && isTabVisible();
  }

  /** GC-547C — perf-idle: simple/auth always; ingame when no active progress jobs. */
  function isPerfIdle() {
    if (!shouldRunGameLoop()) return true;
    return !_hasActiveProgressJobs();
  }

  let _prefersReducedMotion = false;

  function syncPerfBodyClasses() {
    const body = document.body;
    if (!body) return;
    body.classList.toggle("gc-tab-hidden", !isTabVisible());
    body.classList.toggle("gc-reduced-motion", _prefersReducedMotion);
    const perfIdle = isPerfIdle();
    body.classList.toggle("gc-perf-idle", perfIdle);
    if (perfIdle) {
      pauseResourceTicker();
    } else if (shouldRunVisualLoops() && _resourceLive.planetId) {
      startResourceTicker();
    }
  }

  function initMotionPreferenceListener() {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      _prefersReducedMotion = !!mq.matches;
      syncPerfBodyClasses();
    };
    apply();
    if (typeof mq.addEventListener === "function") mq.addEventListener("change", apply);
    else if (typeof mq.addListener === "function") mq.addListener(apply);
  }

  function pauseVisualLoops() {
    GC.stopProgressTicker();
    pauseResourceTicker();
    syncPerfBodyClasses();
  }

  function resumeVisualLoops() {
    syncPerfBodyClasses();
    if (!shouldRunVisualLoops() || _authLoopAborted) return;
    startResourceTicker();
    if (_hasActiveProgressJobs()) GC.startProgressTicker();
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
    if (!url) {
      document.body.classList.remove("gc-has-planet-landscape");
      document.body.style.removeProperty("--planet-landscape");
      return;
    }
    document.body.classList.add("gc-has-planet-landscape");
    document.body.style.setProperty("--planet-landscape", `url("${url}")`);
  }

  /** GC-548 — SSR/PJAX landscape before first game-state poll (perf-idle must not hide it). */
  function bootstrapPlanetLandscapeFromBoot() {
    const body = document.body;
    if (!body || !body.classList.contains("gc-body-ingame")) return;
    if (GC.lastState?.ok === true) {
      applyPlanetLandscapeFromState(GC.lastState);
      return;
    }
    const landscape = body.style.getPropertyValue("--planet-landscape");
    if (landscape?.trim()) {
      body.classList.add("gc-has-planet-landscape");
    }
  }

  function getDomPlanetId() {
    const roots = [
      document.querySelector(".overview-wrapper[data-planet-id]"),
      document.getElementById("build-queue-compact"),
      document.getElementById("research-queue-compact"),
      document.getElementById("shipyard-page"),
      document.getElementById("defense-page"),
      document.getElementById("fleet-page"),
      document.getElementById("logistics-page"),
      document.getElementById("trader-hub-page"),
      document.querySelector(".planet-evolution-page[data-planet-id]"),
    ];
    for (const el of roots) {
      if (!el) continue;
      const pid = Number(el.dataset.planetId || 0);
      if (pid > 0) return pid;
    }
    return 0;
  }

  function syncScopedPlanetIds(planetId) {
    const pid = Number(planetId || 0);
    if (!pid) return;
    [
      "fleet-page",
      "logistics-page",
      "shipyard-page",
      "defense-page",
      "trader-hub-page",
      "build-queue-compact",
      "research-queue-compact",
    ].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.dataset.planetId = String(pid);
    });
    document.querySelectorAll(".planet-evolution-page[data-planet-id]").forEach((el) => {
      el.dataset.planetId = String(pid);
    });
    document.querySelectorAll(".overview-wrapper[data-planet-id]").forEach((el) => {
      el.dataset.planetId = String(pid);
    });
  }

  function abortInFlightGameStateFetches() {
    const pol = GC.polling;
    if (pol.abort) {
      try {
        pol.abort.abort();
      } catch (_) {}
      pol.abort = null;
    }
    pol.inFlight = false;
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

  // Bumped on every POST action state apply — stale in-flight polls must not overwrite.
  let _clientStateGen = 0;
  let _lastAppliedServerTime = 0;
  let _fleetRefreshSeq = 0;

  function applyActionState(json, reason) {
    if (!json) return false;
    const state = json.state || (json.data && json.data.state);
    if (!state) return false;

    const isPlanetSwitch = reason === "planet_switch";
    if (isPlanetSwitch) {
      GC.stopPolling();
      GC.stopProgressTicker();
      _clearMovementCountdownExpiryState();
      _timerZeroRefreshLastAt.clear();
      _lastShipyardQueueSignature = "";
    }

    _clientStateGen += 1;
    _fleetRefreshSeq += 1;
    _lastQueueSignature = "";
    _lastResearchQueueSignature = "";
    _lastShipyardQueueSignature = "";
    _lastDefenseQueueSignature = "";
    _lastPePlanetTechQueueSignature = "";
    _lastPeAscensionQueueSignature = "";
    abortInFlightGameStateFetches();

    resetResourceDisplayCache();
    const st = Number(state.server_time || 0);
    if (st) _lastAppliedServerTime = Math.max(_lastAppliedServerTime, st);

    const anyActive = applyGameStateData(state, reason, {
      forceResourceBar: true,
      planetSwitch: isPlanetSwitch,
      skipScopedPanels: isPlanetSwitch,
    });

    if (!isPlanetSwitch) {
      GC.startPolling(anyActive || lastHadActiveJob || lastHadActiveResearch || lastHadActiveShipyard);
      GC.startProgressTicker();
    }
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

  GC.parseIntNumber = parseIntNumber;
  GC.fmtIntParts = fmtIntParts;
  GC.fmtNumber = fmtNumber;
  GC.fmtIntFull = fmtIntFull;

  (function applyClientRuntimeConfig() {
    const cfg = typeof window !== "undefined" ? window.GC_CLIENT_CONFIG : null;
    if (!cfg || typeof cfg !== "object") return;
    const pol = GC.polling;
    if (Number(cfg.poll_active_ms) > 0) pol.intervalActive = Number(cfg.poll_active_ms);
    if (Number(cfg.poll_idle_ms) > 0) pol.intervalIdle = Number(cfg.poll_idle_ms);
    if (Number(cfg.poll_hidden_ms) > 0) pol.intervalHidden = Number(cfg.poll_hidden_ms);
    if (Number(cfg.shipyard_poll_ms) > 0) GC.shipyardPollMs = Number(cfg.shipyard_poll_ms);
  })();

  function gcEscHtml(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  GC.parseCoordString = function parseCoordString(raw) {
    const text = String(raw || "").trim();
    const m = text.match(/^\[?(\d+):(\d+):(\d+)\]?$/);
    if (!m) return null;
    const galaxy = parseInt(m[1], 10);
    const system = parseInt(m[2], 10);
    const position = parseInt(m[3], 10);
    if (!Number.isFinite(galaxy) || !Number.isFinite(system) || !Number.isFinite(position)) {
      return null;
    }
    return {
      galaxy,
      system,
      position,
      formatted: `[${galaxy}:${system}:${position}]`,
    };
  };

  GC.galaxyUrlForCoords = function galaxyUrlForCoords(raw) {
    const parsed = GC.parseCoordString(raw);
    if (!parsed) return null;
    return `/galaxy?q=${encodeURIComponent(parsed.formatted)}`;
  };

  GC.coordLinkHtml = function coordLinkHtml(raw, opts = {}) {
    const label = opts.label != null ? String(opts.label) : String(raw || "");
    const display = gcEscHtml(label);
    if (!label || label === "—") return display;
    const url = GC.galaxyUrlForCoords(raw);
    if (!url) return display;
    const cls = gcEscHtml(opts.className || "gc-galaxy-coord-link gc-mono");
    const title = gcEscHtml(opts.title || t("galaxy_coord_link_title", "View in galaxy"));
    return `<a href="${gcEscHtml(url)}" class="${cls}" title="${title}">${display}</a>`;
  };

  GC.coordRouteHtml = function coordRouteHtml(fromRaw, toRaw, sep) {
    const sepStr = sep != null ? String(sep) : " → ";
    const from = String(fromRaw || "").trim();
    const to = String(toRaw || "").trim();
    const parts = [];
    if (from) parts.push(GC.coordLinkHtml(from, { label: from }));
    if (from && to) parts.push(gcEscHtml(sepStr));
    if (to) parts.push(GC.coordLinkHtml(to, { label: to }));
    return parts.length ? parts.join("") : gcEscHtml("—");
  };

  GC.linkifyCoordsSegment = function linkifyCoordsSegment(segment) {
    const raw = String(segment ?? "");
    if (!raw) return "";
    const bracketRe = /\[(\d+):(\d+):(\d+)\]/g;
    let out = "";
    let last = 0;
    let match;
    while ((match = bracketRe.exec(raw)) !== null) {
      out += gcEscHtml(raw.slice(last, match.index));
      out += GC.coordLinkHtml(match[0], { label: match[0] });
      last = match.lastIndex;
    }
    let rest = raw.slice(last);
    const plainRe = /(?<![\d:])(\d+):(\d+):(\d+)(?![\d:])/g;
    let plainLast = 0;
    let plainMatch;
    while ((plainMatch = plainRe.exec(rest)) !== null) {
      out += gcEscHtml(rest.slice(plainLast, plainMatch.index));
      const token = plainMatch[0];
      out += GC.coordLinkHtml(token, { label: token });
      plainLast = plainRe.lastIndex;
    }
    out += gcEscHtml(rest.slice(plainLast));
    return out;
  };

  GC.linkifyCoordsInText = function linkifyCoordsInText(text) {
    const raw = String(text ?? "");
    if (!raw) return gcEscHtml("—");
    const routeRe = /(\[?\d+:\d+:\d+\]?)\s*(?:→|->)\s*(\[?\d+:\d+:\d+\]?)/g;
    let out = "";
    let last = 0;
    let routeMatch;
    while ((routeMatch = routeRe.exec(raw)) !== null) {
      out += GC.linkifyCoordsSegment(raw.slice(last, routeMatch.index));
      out += GC.coordLinkHtml(routeMatch[1], { label: routeMatch[1] });
      out += gcEscHtml(" → ");
      out += GC.coordLinkHtml(routeMatch[2], { label: routeMatch[2] });
      last = routeRe.lastIndex;
    }
    out += GC.linkifyCoordsSegment(raw.slice(last));
    return out || gcEscHtml("—");
  };

  if (!GC._coordLinkBound) {
    GC._coordLinkBound = true;
    // Bubble only: allow <a> navigation, stop parent row handlers (inbox item, switcher).
    document.addEventListener(
      "click",
      (e) => {
        if (!e.target.closest("a.gc-galaxy-coord-link")) return;
        e.stopPropagation();
      },
      false
    );
  }

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
    GC.actionLocks.build = false;
    GC.actionLocks.research = false;
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
    if (path.endsWith("/logistics")) return "logistics";
    if (path.endsWith("/inventory")) return "inventory";
    if (path.endsWith("/auction-house")) return "auction_house";
    if (path.endsWith("/galactic-politics")) return "galactic_politics";
    if (path.endsWith("/skilltree")) return "skilltree";
    if (path.endsWith("/premium")) return "premium";
    if (path.endsWith("/alliance")) return "alliance";
    if (path.endsWith("/shipyard")) return "shipyard";
    if (path.endsWith("/defense")) return "defense";
    if (path.endsWith("/empire")) return "empire";
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
    const domPlanetId = getDomPlanetId();
    const statePlanetId = Number(
      GC.lastState.active_planet_id || GC.lastState.build_queue?.planet_id || 0
    );
    if (domPlanetId > 0 && statePlanetId > 0 && domPlanetId !== statePlanetId) {
      return false;
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
  let _progressTickerTimerId = null;

  GC.stopProgressTicker = function stopProgressTicker() {
    _progressTickerActive = false;
    _pageTimerLoopRunning = false;
    if (_progressTickerTimerId != null) {
      clearTimeout(_progressTickerTimerId);
      _progressTickerTimerId = null;
    }
  };

  function _minMovementCountdownRemaining(serverNow) {
    const now = Number.isFinite(serverNow) ? serverNow : getTimerServerNow();
    let min = Infinity;
    const scan = (el) => {
      syncTimerElement(el);
      const rem = timerRemainingSeconds(el, now);
      if (rem > 0 && rem < min) min = rem;
    };
    queryTimerElements().forEach(scan);
    document.querySelectorAll("[data-preview-arrival][data-countdown-at]").forEach(scan);
    return Number.isFinite(min) ? min : Infinity;
  }

  function _progressTickerDelayMs(serverNow) {
    const minRem = _minMovementCountdownRemaining(serverNow);
    if (minRem <= 3) return 50;
    if (minRem <= 10) return 100;
    if (minRem <= 30) return 250;
    if (minRem <= 120) return 500;
    return 1000;
  }

  GC.startProgressTicker = function startProgressTicker() {
    if (!shouldRunVisualLoops()) return;
    if (!_hasActiveProgressJobs()) {
      syncPerfBodyClasses();
      return;
    }
    _progressTickerActive = true;
    _pageTimerLoopRunning = true;
    if (_progressTickerTimerId != null) return;
    const tick = () => {
      _progressTickerTimerId = null;
      if (!_progressTickerActive || !shouldRunVisualLoops() || _authLoopAborted) {
        _pageTimerLoopRunning = false;
        GC.stopProgressTicker();
        syncPerfBodyClasses();
        return;
      }
      if (!_hasActiveProgressJobs()) {
        _pageTimerLoopRunning = false;
        GC.stopProgressTicker();
        syncPerfBodyClasses();
        return;
      }
      const serverNow = getTimerServerNow();
      updateAllProgressBars(serverNow);
      syncPerfBodyClasses();
      _progressTickerTimerId = setTimeout(tick, _progressTickerDelayMs(serverNow));
    };
    tick();
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
      const active = lastHadActiveJob || lastHadActiveResearch || lastHadActiveShipyard;
      let interval = pol.intervalIdle;
      if (active) interval = pol.intervalActive;
      if (document.hidden) interval = pol.intervalHidden;
      pol.lastInterval = interval;
      scheduleGameStatePoll(interval);
    }), Math.max(0, ms));
  }

  GC.stopStatusPoller = GC.stopPolling;
  GC.shouldRunGameLoop = shouldRunGameLoop;
  GC.shouldRunVisualLoops = shouldRunVisualLoops;
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
    const skipHydrate = Boolean(opts && opts.skipHydrate);

    if (GC.pageLifecycle.initialized && GC.currentPage === page && !force) {
      console.debug("[GC] initPage skipped (same page)", page);
      return;
    }

    GC.currentPage = page;
    GC.pageLifecycle.initialized = true;
    console.debug("[GC] initPage", page);

    if (page !== "buildings") {
      hideBuildingsSubnav();
    }

    syncTradingSubnav(page);
    syncMilitarySubnav(page);

    if (typeof normalizePopoverTriggers === "function") {
      normalizePopoverTriggers(document.getElementById("main-content") || document);
    }

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

    if (shouldRunGameLoop() && !skipHydrate) {
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
      resyncServerTimeFromDom(true);
      if (!skipGameState && typeof GC.refreshGameState === "function") {
        await GC.refreshGameState("page_init");
      } else if (skipGameState) {
        GC.startPolling(lastHadActiveJob || lastHadActiveResearch || lastHadActiveShipyard);
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

  /** Unix seconds (or ms) → locale date + time for messages, chat, support. */
  function formatLocaleDateTime(ts) {
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return "–";
    const ms = n < 1e12 ? n * 1000 : n;
    const d = new Date(ms);
    if (Number.isNaN(d.getTime())) return "–";
    const lang = String(document.documentElement.lang || "de").trim().toLowerCase();
    let locale = "de-DE";
    if (lang === "en") locale = "en-GB";
    else if (lang.includes("-")) locale = lang;
    else if (lang === "de") locale = "de-DE";
    else if (lang) locale = lang;
    try {
      return new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(d);
    } catch (_) {
      try {
        return new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(d);
      } catch (__) {
        return "–";
      }
    }
  }
  GC.formatLocaleDateTime = formatLocaleDateTime;

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

  const BUILDING_PROD_RESOURCE = {
    metal_mine: "metal",
    crystal_mine: "crystal",
    fuel_cell_plant: "fuel_cells",
  };

  function buildingEffectMetricLabel(kind, resKey, buildingKey, effectMetricKey) {
    if (effectMetricKey) {
      const localized = t(effectMetricKey, "");
      if (localized) return localized;
    }
    if (kind === "production") return t("buildings_effect_production", "Produktion");
    if (kind === "energy") return t("buildings_effect_energy", "Energie");
    if (kind === "energy_use") return t("buildings_effect_energy_use", "Energieverbrauch");
    if (kind === "storage") return t("buildings_effect_storage", "Lager");
    if (kind === "max_level") return t("buildings_effect_max_mine", "Max. Minenstufe");
    if (kind === "scan") return t("buildings_effect_scan", "Scan-Reichweite");
    if (kind === "level") return t("buildings_effect_level", "Stufe");
    if (kind === "bonus_percent") {
      if (resKey === "research") return t("buildings_effect_research_speed", "Forschungstempo");
      if (resKey === "build" && buildingKey === "command_center") {
        return t("buildings_effect_nanofactory_build", "Nanofabrik-Bau");
      }
      if (resKey === "build") return t("buildings_effect_build_speed", "Baugeschwindigkeit");
      if (resKey === "storage") return t("buildings_effect_storage_bonus", "Lagerbonus");
      return t("buildings_effect_bonus", "Bonus");
    }
    return t("buildings_effect_level", "Stufe");
  }

  function renderBuildingEffectIcon(resKey) {
    if (resKey === "energy") {
      return (
        '<img src="/static/icons/energy.png" alt="" class="gc-bld-effect-icon gc-bld-effect-icon-energy" ' +
        'loading="lazy" aria-hidden="true">'
      );
    }
    if (resKey === "research") {
      return '<span class="gc-bld-effect-icon gc-bld-effect-icon-fallback" aria-hidden="true">🔬</span>';
    }
    if (resKey === "build") {
      return '<span class="gc-bld-effect-icon gc-bld-effect-icon-fallback" aria-hidden="true">⚙</span>';
    }
    if (resKey === "storage") {
      return '<span class="gc-bld-effect-icon gc-bld-effect-icon-fallback" aria-hidden="true">📦</span>';
    }
    if (resKey === "metal" || resKey === "crystal" || resKey === "fuel_cells") {
      const mod = ` gc-res-${resKey.replace(/_/g, "-")}`;
      return `<span class="gc-res-icon gc-res-icon--sm${mod}" aria-hidden="true"></span>`;
    }
    return "";
  }

  function renderBuildingEffectValue(kind, resKey, amount, unit) {
    const val = Math.floor(Number(amount) || 0);
    if (kind === "reduction_percent") {
      return renderMonoCompact(val, "-", unit || "%");
    }
    if (kind === "bonus_percent") {
      return renderMonoCompact(val, "+", unit || "%");
    }
    if (kind === "level") {
      return renderMonoCompact(val);
    }
    if (kind === "max_level" || kind === "scan") {
      return renderMonoCompact(val, "", unit || "");
    }
    const icon = renderBuildingEffectIcon(resKey);
    const unitHtml = unit ? `<span class="gc-bld-prod-unit">${unit}</span>` : "";
    return `${icon}${renderMonoCompact(val)}${unitHtml}`;
  }

  function buildingEffectDeltaLabel(kind) {
    if (kind === "energy_use") {
      return t("buildings_prod_delta_cost", "Mehrverbrauch");
    }
    return t("buildings_prod_delta", "Gewinn");
  }

  function renderBuildingEffectDelta(kind, delta, unit) {
    const d = Math.floor(Number(delta) || 0);
    if (d <= 0) return "";
    if (kind === "reduction_percent") return renderMonoCompact(d, "-", "%");
    if (kind === "bonus_percent") return renderMonoCompact(d, "+", "%");
    if (kind === "level") return renderMonoCompact(d, "+", "");
    if (kind === "production") return renderMonoCompact(d, "+", "/h");
    return renderMonoCompact(d, "+", unit || "");
  }

  function renderBuildingEffectStripHtml(effectRow, buildingKey, opts = {}) {
    const compact = !!opts.compact;
    const stripClass = opts.stripClass || "";
    const kind =
      effectRow.effect_kind ||
      (effectRow.production_resource || BUILDING_PROD_RESOURCE[buildingKey] ? "production" : "level");
    const resKey =
      effectRow.effect_resource ||
      effectRow.production_resource ||
      BUILDING_PROD_RESOURCE[buildingKey] ||
      "";
    const unit =
      effectRow.effect_unit ||
      (kind === "production" ? "/h" : kind === "bonus_percent" ? "%" : "");
    const cur = Math.floor(
      Number(effectRow.effect_current ?? effectRow.production_per_hour ?? effectRow.level) || 0
    );
    const nxt = Math.floor(
      Number(effectRow.effect_next ?? effectRow.production_next_per_hour ?? effectRow.target_level) ||
        0
    );
    const delta = Math.floor(Number(effectRow.effect_delta ?? effectRow.production_delta) || 0);
    const metricLabel = buildingEffectMetricLabel(
      kind,
      resKey,
      buildingKey,
      effectRow.effect_metric_key || ""
    );
    const curLabel = t("buildings_prod_current", "Aktuell");
    const nextLabel = t("buildings_prod_after", "Nach Upgrade");
    const deltaLabel = buildingEffectDeltaLabel(kind);
    const deltaText = renderBuildingEffectDelta(kind, delta, unit);
    const deltaCostCls = kind === "energy_use" ? " gc-bld-prod-delta-cost" : "";
    const deltaHtml = deltaText
      ? `<div class="gc-bld-prod-delta bcell-prod-delta${deltaCostCls}">` +
        `<span class="gc-bld-prod-delta-label">${deltaLabel}</span>` +
        `<span class="gc-bld-prod-delta-val">${deltaText}</span></div>`
      : "";
    const compactCls = compact ? " gc-bld-effect-compact" : "";
    const extraCls = stripClass ? ` ${stripClass}` : "";
    return (
      `<div class="gc-bld-prod bcell-prod gc-bld-effect${compactCls}${extraCls}"` +
      ` data-building-prod="${buildingKey}" data-effect-kind="${kind}">` +
      `<div class="gc-bld-prod-metric" title="${metricLabel}">${metricLabel}</div>` +
      `<div class="gc-bld-prod-line">` +
      `<span class="gc-bld-prod-label">${curLabel}</span>` +
      `<span class="gc-bld-prod-val gc-bld-prod-cur bcell-prod-current">` +
      renderBuildingEffectValue(kind, resKey, cur, unit) +
      `</span></div>` +
      `<div class="gc-bld-prod-line">` +
      `<span class="gc-bld-prod-label">${nextLabel}</span>` +
      `<span class="gc-bld-prod-val gc-bld-prod-next bcell-prod-next">` +
      renderBuildingEffectValue(kind, resKey, nxt, unit) +
      `</span></div>` +
      deltaHtml +
      `</div>`
    );
  }

  function renderBuildingEffectBundleHtml(b, opts = {}) {
    let html = renderBuildingEffectStripHtml(b, b.key, opts);
    const sec = b.secondary_effect;
    if (sec && typeof sec === "object") {
      html += renderBuildingEffectStripHtml(
        { ...sec, key: b.key },
        b.key,
        { ...opts, stripClass: "gc-bld-effect-secondary" }
      );
    }
    return html;
  }

  function patchBuildingProduction(row, b) {
    if (!row || !b) return;
    const html = renderBuildingEffectBundleHtml(b);
    const head = row.querySelector(".gc-bld-card-head");
    const meta = row.querySelector(".gc-bld-card-meta");

    const bundles = [...row.querySelectorAll(".gc-bld-effect-bundle")];
    let bundle = bundles[0] || null;
    for (let i = 1; i < bundles.length; i += 1) bundles[i].remove();

    if (bundle) {
      if (bundle.innerHTML.trim() !== html.trim()) bundle.innerHTML = html;
      row.querySelectorAll(":scope > .gc-bld-prod.bcell-prod").forEach((el) => el.remove());
      return;
    }

    row.querySelectorAll(".bcell-prod").forEach((el) => el.remove());

    bundle = document.createElement("div");
    bundle.className = "gc-bld-effect-bundle";
    bundle.innerHTML = html;

    if (head && meta) head.insertAdjacentElement("afterend", bundle);
    else if (head) head.insertAdjacentElement("afterend", bundle);
    else row.prepend(bundle);
  }

  function renderCompactCosts(metal, crystal, targetLevel, showTarget = true) {
    const levelLabel = t("buildings_col_level", "Level");
    const targetNote = showTarget ? `→ L${fmtNumber(targetLevel)}` : "";
    const targetHtml = showTarget
      ? `<span class="gc-cost-target" title="${levelLabel} ${fmtNumber(targetLevel)}">${targetNote}</span>`
      : "";
    return (
      `<div class="gc-costs-compact">` +
      `<span class="gc-cost-chip gc-cost-metal"><span class="gc-res-icon gc-res-metal" aria-hidden="true"></span>` +
      `${renderCostVal(metal)}</span>` +
      `<span class="gc-cost-chip gc-cost-crystal"><span class="gc-res-icon gc-res-crystal" aria-hidden="true"></span>` +
      `${renderCostVal(crystal)}</span>` +
      targetHtml +
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
      "gc-prog-max",
      "gc-building-card--in-queue",
      "gc-building-card--queue-active",
      "gc-building-card--queue-pending"
    );
    if (isMax) row.classList.add("gc-prog-max");
    else if (!b.requirements_met) row.classList.add("gc-prog-locked");
    else if (!b.can_afford) row.classList.add("gc-prog-unaffordable");
    else row.classList.add("gc-prog-affordable");

    const qj = b.queue_job;
    if (qj && typeof qj === "object") {
      row.classList.add("gc-building-card--in-queue");
      if (String(qj.status) === "active") row.classList.add("gc-building-card--queue-active");
      else row.classList.add("gc-building-card--queue-pending");
    }
  }

  function applyResearchRowState(row, tech) {
    if (!row || !tech) return;
    const locked = !tech.requirements_met;
    const unaffordable = !locked && tech.can_afford === false;
    row.classList.remove(
      "gc-prog-affordable",
      "gc-prog-locked",
      "gc-prog-unaffordable",
      "tech-row-locked",
      "gc-research-card--in-queue",
      "gc-research-card--queue-active",
      "gc-research-card--queue-pending"
    );
    if (locked) {
      row.classList.add("gc-prog-locked", "tech-row-locked");
    } else if (unaffordable) {
      row.classList.add("gc-prog-unaffordable");
    } else {
      row.classList.add("gc-prog-affordable");
    }

    const qj = tech.queue_job;
    if (qj && typeof qj === "object") {
      row.classList.add("gc-research-card--in-queue");
      if (String(qj.status) === "active") row.classList.add("gc-research-card--queue-active");
      else row.classList.add("gc-research-card--queue-pending");
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

  function patchBuildingRequirements(row, b) {
    if (!row || !b) return;
    const lockTitle = t("msg_build_requirements", "Voraussetzungen nicht erfüllt.");
    let reqEl = row.querySelector(".gc-bld-card-req");
    if (b.requirements_met) {
      if (reqEl) reqEl.remove();
      return;
    }
    const tooltip = formatResearchReqTooltip(b.requirements_items);
    if (!tooltip) {
      if (reqEl) reqEl.remove();
      return;
    }
    if (!reqEl) {
      reqEl = document.createElement("p");
      reqEl.className = "gc-bld-card-req gc-mono";
      reqEl.dataset.buildingReq = String(b.key || "");
      reqEl.title = lockTitle;
      const actionCell = row.querySelector(".bcell-action");
      if (actionCell) row.insertBefore(reqEl, actionCell);
      else row.appendChild(reqEl);
    }
    _setIfChanged(reqEl, tooltip);
  }

  function renderResearchActionCell(tech, summary) {
    const key = tech.key;
    const count = summary?.count ?? 0;
    const limit = summary?.limit ?? 3;
    const queueFull = count >= limit;
    const queueActive = count > 0;
    const btnStart = t("research_btn_start", "Forschung starten");
    const btnQueue = t("research_btn_queue", "Anreihen");
    const fullLabel = t("research_btn_queue_full", "Forschungsliste voll");
    const actionLabel = queueActive ? btnQueue : btnStart;

    if (!tech.requirements_met) {
      let lockTitle = t("research_requirements_not_met", "Voraussetzungen nicht erfüllt.");
      const reqHint = formatResearchReqTooltip(tech.requirements_items);
      if (reqHint) lockTitle += " · " + reqHint;
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--warn btn-research status-pill-icon-btn" type="button" disabled` +
        ` title="${lockTitle}" aria-label="${lockTitle}"><span class="gc-bld-head-action-icon">⚠</span></button>`
      );
    }
    if (queueFull) {
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--locked btn-research" type="button" disabled` +
        ` aria-disabled="true" title="${fullLabel}" aria-label="${fullLabel}"><span class="gc-bld-head-action-icon">🔒</span></button>`
      );
    }
    if (tech.can_afford === false) {
      const shortMsg = t("research_not_enough_resources", "Nicht genug Ressourcen.");
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--afford btn-research" type="button" disabled` +
        ` title="${shortMsg}" aria-label="${shortMsg}"><span class="gc-bld-head-action-icon">+</span></button>`
      );
    }
    const href = `/research_start/${encodeURIComponent(key)}`;
    return (
      `<a href="${href}" class="gc-bld-head-action-btn gc-bld-head-action-btn--go btn-research"` +
      ` title="${actionLabel}" aria-label="${actionLabel}"><span class="gc-bld-head-action-icon">+</span></a>`
    );
  }

  function renderBuildingActionCell(b, bqSummary, bqQueueFull) {
    const key = b.key;
    const btnUpgrade = t("buildings_btn_upgrade", "Ausbau starten");
    const btnMax = t("buildings_btn_max_level", "Max. Level");
    const fullLabel = t("buildings_btn_queue_full", "Warteschlange voll");
    const btnQueue = t("research_btn_queue", "Anreihen");
    const queueActive = (bqSummary?.count || 0) > 0;
    const actionLabel = queueActive ? btnQueue : btnUpgrade;
    const isMax = (b.level >= b.max_level) || b.at_queue_max;

    if (isMax) {
      return (
        `<span class="gc-bld-head-action-btn gc-bld-head-action-btn--max" title="${btnMax}"` +
        ` aria-label="${btnMax}"><span class="gc-bld-head-action-icon">✓</span></span>`
      );
    }
    if (!b.requirements_met) {
      const lockTitle = t("msg_build_requirements", "Voraussetzungen nicht erfüllt.");
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--warn btn-upgrade status-pill-icon-btn" type="button" disabled` +
        ` title="${lockTitle}" aria-label="${lockTitle}"><span class="gc-bld-head-action-icon">⚠</span></button>`
      );
    }
    if (bqQueueFull) {
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--locked btn-upgrade" type="button" disabled` +
        ` aria-disabled="true" title="${fullLabel}" aria-label="${fullLabel}"><span class="gc-bld-head-action-icon">🔒</span></button>`
      );
    }
    if (!b.can_afford) {
      const shortMsg = t("msg_build_not_enough_resources", "Nicht genug Ressourcen.");
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--afford btn-upgrade" type="button" disabled` +
        ` title="${shortMsg}" aria-label="${shortMsg}"><span class="gc-bld-head-action-icon">+</span></button>`
      );
    }
    const tab = b.tab || _getActiveBuildingTab();
    const href = `/upgrade/${encodeURIComponent(key)}?src=buildings&tab=${encodeURIComponent(tab)}`;
    return (
      `<a id="btn-${key}" data-building="${key}" href="${href}"` +
      ` class="gc-bld-head-action-btn gc-bld-head-action-btn--go btn-upgrade"` +
      ` title="${actionLabel}" aria-label="${actionLabel}"><span class="gc-bld-head-action-icon">+</span></a>`
    );
  }

  function patchBuildingPanel(rowsByTab, buildQueueRaw) {
    if (!rowsByTab || !document.querySelector(".buildings-prog-list")) return;

    const summary = buildQueueRaw?.summary || null;
    const limit = summary?.limit ?? 3;
    const count = summary?.count ?? 0;
    const bqQueueFull = count >= limit;
    const byOwner = buildQueueRaw?.card_jobs_by_owner;
    const useOwnerMap = byOwner && typeof byOwner === "object";
    if (useOwnerMap) {
      patchCardQueuesFromOwnerMap(
        document,
        byOwner,
        (root) => root.querySelectorAll("[data-building-row]"),
        (row) => row.getAttribute("data-building-row") || "",
        (root, key) => root.querySelector(`[data-building-row="${key}"]`)
      );
    }

    Object.values(rowsByTab).forEach((rows) => {
      (rows || []).forEach((b) => {
        const key = b.key;
        const levelEl = document.getElementById(`level-${key}`);
        if (levelEl) _setIfChanged(levelEl, fmtNumber(b.level));

        const row = document.querySelector(`[data-building-row="${key}"]`);
        if (!row) return;

        applyBuildingRowState(row, b);
        patchBuildingRequirements(row, b);
        patchBuildingProduction(row, b);

        const costCell = row.querySelector(".bcell-cost");
        if (costCell) {
          const html = renderCompactCosts(b.cost_metal, b.cost_crystal, b.target_level, false);
          if (costCell.innerHTML.trim() !== html.trim()) costCell.innerHTML = html;
        }

        const durCell = row.querySelector(".bcell-duration");
        if (durCell) {
          setHeroTimeChipIdle(row, b.time_seconds, t("buildings_col_time", "Bauzeit"));
        }

        const actionCell = row.querySelector(".bcell-action");
        if (actionCell) {
          const html = renderBuildingActionCell(b, summary, bqQueueFull);
          if (actionCell.innerHTML.trim() !== html.trim()) actionCell.innerHTML = html;
        }

        if (useOwnerMap) {
          /* queue blocks synced via card_jobs_by_owner */
        } else if (b.queue_job) GC.renderCardQueueBlock(row, b.queue_job);
        else GC.clearCardQueueBlock(row);
      });
    });
  }

  function patchResearchEffects(row, tech) {
    if (!row || !tech) return;
    patchBuildingProduction(row, tech);
  }

  function patchResearchPanel(techs, researchRaw) {
    const list = document.querySelector(".research-prog-list");
    if (!list || !Array.isArray(techs)) return;

    const summary = researchRaw?.summary || {};
    const byOwner = researchRaw?.card_jobs_by_owner;
    const useOwnerMap = byOwner && typeof byOwner === "object";
    if (useOwnerMap) {
      patchCardQueuesFromOwnerMap(
        document,
        byOwner,
        (root) => root.querySelectorAll("[data-tech-key]"),
        (row) => row.getAttribute("data-tech-key") || "",
        (root, key) => root.querySelector(`[data-tech-key="${key}"]`)
      );
    }

    techs.forEach((tech) => {
      const row = document.querySelector(`[data-tech-key="${tech.key}"]`);
      if (!row) return;

      applyResearchRowState(row, tech);
      patchResearchEffects(row, tech);

      const levelEl = row.querySelector(".tech-level-current");
      if (levelEl) {
        const target = tech.target_level ?? tech.level + 1;
        _setIfChanged(levelEl, `${fmtNumber(tech.level)}→${fmtNumber(target)}`);
      }

      const costCell = row.querySelector(".tech-cost-cell, .bcell-cost");
      if (costCell) {
        const html = renderCompactCosts(tech.cost_metal, tech.cost_crystal, tech.target_level, false);
        if (costCell.innerHTML.trim() !== html.trim()) costCell.innerHTML = html;
      }

      if (!row.classList.contains("gc-research-card--in-queue")) {
        setHeroTimeChipIdle(row, tech.time_seconds, t("research_col_time", "Forschungszeit"));
      }

      const actionCell = row.querySelector(".tech-status-cell, .gc-bld-card-action[data-tech-key]");
      if (actionCell) {
        const html = renderResearchActionCell(tech, summary);
        if (actionCell.innerHTML.trim() !== html.trim()) actionCell.innerHTML = html;
      }

      if (useOwnerMap) {
        /* queue blocks synced via card_jobs_by_owner */
      } else if (tech.queue_job) GC.renderCardQueueBlock(row, tech.queue_job);
      else GC.clearCardQueueBlock(row);
    });

    const labEl = document.querySelector(".lab-level-highlight");
    if (labEl && typeof researchRaw?.lab_level !== "undefined") {
      _setIfChanged(labEl, fmtNumber(researchRaw.lab_level));
    }

    updateResearchQueueActions(researchRaw);
  }

  let _finishRefreshTimer = null;
  const _finishRefreshArmed = { buildings: false, research: false, planet_evolution: false };
  const _finishRefreshLastAt = { buildings: 0, research: 0, planet_evolution: 0 };
  const FINISH_REFRESH_MIN_MS = 2500;

  function clearFinishRefreshArmed(type, queueList) {
    if (!Array.isArray(queueList) || !queueList.length) {
      _finishRefreshArmed[type] = false;
      return;
    }
    const first = queueList[0];
    const finishAt = first ? Number(first.finish_at || first.finish_time || 0) : 0;
    const now = getApproxServerNow();
    if (!finishAt || (now && finishAt > now)) {
      _finishRefreshArmed[type] = false;
    }
  }

  function releaseFinishRefreshLock(key) {
    GC.finishLocks[key] = false;
    _finishRefreshArmed[key] = false;
  }

  function requestFinishRefresh(type) {
    if (!shouldRunGameLoop() || _authLoopAborted) return;
    if (type === "shipyard") {
      requestProductionCompletionSync({ gameState: true, shipyard: true });
      return;
    }
    const key = type === "buildings" || type === "research" || type === "planet_evolution" ? type : "buildings";
    const nowMs = Date.now();
    if (nowMs - (_finishRefreshLastAt[key] || 0) < FINISH_REFRESH_MIN_MS) return;
    if (_finishRefreshArmed[key] || _finishRefreshTimer) return;

    _finishRefreshTimer = GC.setSafeTimeout(() => {
      _finishRefreshTimer = null;
      _lastQueueSignature = "";
      _lastResearchQueueSignature = "";

      const run = () => {
        const refresh = () => {
          if (
            key === "planet_evolution" &&
            document.querySelector(".planet-evolution-page")
          ) {
            const page = document.querySelector(".planet-evolution-page");
            const pid = parseInt(page?.dataset.planetId || "0", 10);
            const refreshPe = pid
              ? refreshPlanetEvolutionState(pid)
              : Promise.resolve(null);
            return Promise.resolve(refreshPe).finally(() => {
              if (typeof GC.refreshGameState === "function") {
                return Promise.resolve(GC.refreshGameState("planet_evolution_finished")).finally(() => {
                  releaseFinishRefreshLock(key);
                });
              }
              releaseFinishRefreshLock(key);
            });
          }
          return Promise.resolve(GC.refreshGameState ? GC.refreshGameState(`${key}_finished`) : null).finally(() => {
            releaseFinishRefreshLock(key);
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
      _finishRefreshLastAt[key] = nowMs;
      if (GC.refreshInFlight) {
        Promise.resolve(GC.refreshInFlight).finally(run);
        return;
      }
      run();
    }, 300);
  }

  let _overviewWidgetsPlanetId = 0;

  function patchOverviewUpgradeWidgets(overview, activePlanetId) {
    const root = document.getElementById("overview-upgrade-widgets");
    const rows = overview?.rows;
    if (!root || !Array.isArray(rows)) return;

    const pid = Number(activePlanetId || 0);
    if (pid > 0 && _overviewWidgetsPlanetId > 0 && pid !== _overviewWidgetsPlanetId) {
      root.replaceChildren();
      root.hidden = true;
      root.setAttribute("aria-hidden", "true");
    }
    if (pid > 0) _overviewWidgetsPlanetId = pid;

    if (rows.length === 0) {
      if (root.childElementCount > 0) root.replaceChildren();
      root.hidden = true;
      root.setAttribute("aria-hidden", "true");
      return;
    }

    const rowKeys = new Set(rows.map((b) => b && b.key).filter(Boolean));
    root.querySelectorAll("[data-overview-building]").forEach((card) => {
      if (!rowKeys.has(card.dataset.overviewBuilding || "")) card.remove();
    });

    rows.forEach((b) => {
      if (!b || !b.key) return;
      let card = root.querySelector(`[data-overview-building="${b.key}"]`);
      if (!card) {
        card = document.createElement("a");
        card.className = "overview-upgrade-card";
        card.href = "/buildings";
        card.dataset.overviewBuilding = b.key;
        card.innerHTML =
          `<div class="overview-upgrade-card-head">` +
          `<span class="overview-upgrade-name"></span>` +
          `<span class="overview-upgrade-level gc-mono"></span>` +
          `</div>` +
          `<div class="gc-bld-effect-bundle"></div>`;
        root.appendChild(card);
        root.hidden = false;
        root.removeAttribute("aria-hidden");
      }
      const nameEl = card.querySelector(".overview-upgrade-name");
      const lvlEl = card.querySelector(".overview-upgrade-level");
      if (nameEl) {
        _setIfChanged(nameEl, t(`overview_building_${b.key}`, t(`building_${b.key}`, b.key)));
      }
      if (lvlEl) _setIfChanged(lvlEl, `L${fmtNumber(b.level || 0)}`);
      const bundle = card.querySelector(".gc-bld-effect-bundle");
      if (bundle) {
        const html = renderBuildingEffectBundleHtml(b, { compact: true });
        if (bundle.innerHTML.trim() !== html.trim()) bundle.innerHTML = html;
      }
    });
  }

  function patchOverviewTable(overview, buildings, prod, activePlanetId) {
    patchOverviewUpgradeWidgets(overview, activePlanetId);
  }

  function patchResourceBarEnergyWarning(used, total) {
    const container = document.getElementById("energy-container");
    if (!container) return;
    const u = Math.floor(Number(used) || 0);
    const t = Math.floor(Number(total) || 0);
    container.classList.toggle("energy-warning", t > 0 && u > t);
  }

  function patchOverviewEnergyHint(overview, data) {
    const card = document.getElementById("overview-energy-card");
    if (!card) return;

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
    const used = Math.floor(
      Number(
        data?.energy?.used ??
          overview?.status?.energy?.used ??
          data?.player?.energy_used ??
          data?.resources?.energy_used ??
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
    card.classList.remove(...stateClasses);
    if (state === "zero") card.classList.add("overview-energy-zero");
    else if (state === "ok") card.classList.add("overview-energy-ok");
    else if (state === "low") card.classList.add("overview-energy-low");
    else if (state === "critical") card.classList.add("overview-energy-critical");

    const surplus = total - used;
    const balEl = document.getElementById("overview-energy-balance");
    if (balEl) {
      const sign = surplus >= 0 ? "+" : "";
      _setIfChanged(balEl, `${sign}${fmtNumber(surplus)}`);
      balEl.classList.toggle("overview-res-dash-balance--pos", surplus >= 0);
      balEl.classList.toggle("overview-res-dash-balance--neg", surplus < 0);
    }

    const statusEl = document.getElementById("overview-energy-status");
    if (statusEl) {
      const labels = statusEl.dataset;
      let label = labels.labelSurplus || "Überschuss";
      if (total <= 0) label = labels.labelNone || "Keine Energie";
      else if (surplus < 0) label = labels.labelDeficit || "Defizit";
      _setIfChanged(statusEl, label);
    }

    const fillEl = card.querySelector('[data-res-fill="energy"]');
    if (fillEl && total > 0) {
      const pct = Math.min(100, Math.max(0, (used / total) * 100));
      fillEl.style.width = `${pct}%`;
    }

    const pctEl = card.querySelector('[data-res-pct="energy"]');
    if (pctEl && total > 0) {
      const pct = Math.min(100, Math.max(0, Math.round((used / total) * 100)));
      _setIfChanged(pctEl, `${pct}%`);
    }
  }

  function patchOverviewResourceBars(metal, crystal, fuelCells, storageMetal, storageCrystal, storageFuelCells) {
    const pairs = [
      ["metal", metal, storageMetal],
      ["crystal", crystal, storageCrystal],
      ["fuel_cells", fuelCells, storageFuelCells],
    ];
    pairs.forEach(([key, val, cap]) => {
      const fillEl = document.querySelector(`[data-res-fill="${key}"]`);
      const pctEl = document.querySelector(`[data-res-pct="${key}"]`);
      if (fillEl && cap > 0) {
        const pct = Math.min(100, Math.max(0, (Number(val) / Number(cap)) * 100));
        fillEl.style.width = `${pct}%`;
        if (pctEl) _setIfChanged(pctEl, `${Math.round(pct)}%`);
      } else if (pctEl) {
        _setIfChanged(pctEl, "0%");
      }
    });
  }

  function patchOverviewStatus(overview, data, buildings, prod) {
    const status = overview?.status;
    if (status?.resources) {
      const metalPhEl = document.querySelector('[data-ph="metal"]');
      const crystalPhEl = document.querySelector('[data-ph="crystal"]');
      const fuelPhEl = document.querySelector('[data-ph="fuel_cells"]');
      const metalPh = Math.floor(Number(status.resources.metal_per_hour || 0));
      const crystalPh = Math.floor(Number(status.resources.crystal_per_hour || 0));
      const fuelPh = Math.floor(Number(status.resources.fuel_cells_per_hour || 0));
      if (metalPhEl) _setIfChanged(metalPhEl, metalPh > 0 ? `+${fmtNumber(metalPh)}/h` : "–");
      if (crystalPhEl) _setIfChanged(crystalPhEl, crystalPh > 0 ? `+${fmtNumber(crystalPh)}/h` : "–");
      if (fuelPhEl) _setIfChanged(fuelPhEl, fuelPh > 0 ? `+${fmtNumber(fuelPh)}/h` : "–");
    } else if (prod) {
      const metalPhEl = document.querySelector('[data-ph="metal"]');
      const crystalPhEl = document.querySelector('[data-ph="crystal"]');
      const fuelPhEl = document.querySelector('[data-ph="fuel_cells"]');
      const metalPh = Math.floor(Number(prod.metal_mine || 0));
      const crystalPh = Math.floor(Number(prod.crystal_mine || 0));
      const fuelPh = Math.floor(Number(prod.fuel_cell_plant ?? prod.fuel_cells ?? 0));
      if (metalPhEl) _setIfChanged(metalPhEl, metalPh > 0 ? `+${fmtNumber(metalPh)}/h` : "–");
      if (crystalPhEl) _setIfChanged(crystalPhEl, crystalPh > 0 ? `+${fmtNumber(crystalPh)}/h` : "–");
      if (fuelPhEl) _setIfChanged(fuelPhEl, fuelPh > 0 ? `+${fmtNumber(fuelPh)}/h` : "–");
    }

    patchOverviewEnergyHint(overview, data);
    if (status?.resources) {
      patchOverviewResourceBars(
        Number(status.resources.metal || 0),
        Number(status.resources.crystal || 0),
        Number(status.resources.fuel_cells || 0),
        Number(status.resources.metal_cap || 0),
        Number(status.resources.crystal_cap || 0),
        Number(status.resources.fuel_cells_cap || 0)
      );
    }
    patchOverviewTable(overview, buildings, prod, data?.active_planet_id || 0);

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
            etaEl.dataset.timerTarget = String(endAt);
            etaEl.dataset.timerKind = act.key.startsWith("fleet_") ? "fleet" : "queue";
            etaEl.dataset.refreshOnZero = act.key.startsWith("fleet_") ? "fleet" : "game-state";
            etaEl.dataset.countdownAt = String(endAt);
            etaEl.dataset.countdownScope = "overview";
            etaEl.dataset.countdownFormat = act.key.startsWith("fleet_") ? "fleet" : "eta";
            etaEl.dataset.countdownKey = `${mvId}:${phase}:${endAt}`;
            if (act.key.startsWith("fleet_") && Number.isFinite(Number(act.remaining))) {
              assignMonotonicServerRemaining(
                etaEl,
                Math.max(0, Math.ceil(Number(act.remaining))),
                endAt
              );
            } else {
              delete etaEl.dataset.serverRemaining;
            }
            const rem = act.key.startsWith("fleet_")
              ? movementRemainingSeconds(endAt, getTimerServerNow(), act.remaining)
              : Math.max(0, Math.ceil(endAt - getTimerServerNow()));
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
            etaEl.dataset.timerTarget = String(endAt);
            etaEl.dataset.timerKind = act.key.startsWith("fleet_") ? "fleet" : "queue";
            etaEl.dataset.refreshOnZero = act.key.startsWith("fleet_") ? "fleet" : "game-state";
            etaEl.dataset.countdownAt = String(endAt);
            etaEl.dataset.countdownScope = "overview";
            etaEl.dataset.countdownFormat = act.key.startsWith("fleet_") ? "fleet" : "eta";
            etaEl.dataset.countdownKey = `${mvId}:${phase}:${endAt}`;
            if (act.key.startsWith("fleet_") && Number.isFinite(Number(act.remaining))) {
              assignMonotonicServerRemaining(
                etaEl,
                Math.max(0, Math.ceil(Number(act.remaining))),
                endAt
              );
            } else {
              delete etaEl.dataset.serverRemaining;
            }
            const rem = act.key.startsWith("fleet_")
              ? movementRemainingSeconds(endAt, getTimerServerNow(), act.remaining)
              : Math.max(0, Math.ceil(endAt - getTimerServerNow()));
            _setIfChanged(
              etaEl,
              act.key.startsWith("fleet_") ? formatCountdownRemain(rem) : formatEta(rem)
            );
          } else {
            delete etaEl.dataset.countdownAt;
            delete etaEl.dataset.countdownScope;
            delete etaEl.dataset.countdownFormat;
            delete etaEl.dataset.countdownKey;
            delete etaEl.dataset.serverRemaining;
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
    updateMovementCountdowns(getApproxServerNow());
    GC.startProgressTicker();
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
    const fmt = opts.fmt || fmtNumber;
    if (_prefersReducedMotion || !shouldRunVisualLoops()) {
      el.textContent = fmt(tgt);
      _lastNum.set(el, tgt);
      return;
    }
    const last = _lastNum.get(el);
    if (last === tgt) return;
    _lastNum.set(el, tgt);

    const { duration = 650, minStep = 1 } = opts;
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
    lastDeltaEventTotal: null,
  };

  const SCORE_DELTA_ANIM_MS = 980;
  const SCORE_DELTA_REMOVE_FALLBACK_MS = 1400;
  let _scoreDeltaRemoveTimer = null;
  let _scoreDeltaEl = null;

  function _purgeAllScoreDeltaNodes() {
    document.querySelectorAll(".gc-score-delta").forEach((el) => el.remove());
    _scoreDeltaEl = null;
    if (_scoreDeltaRemoveTimer != null) {
      clearTimeout(_scoreDeltaRemoveTimer);
      _scoreDeltaRemoveTimer = null;
    }
  }

  function _resolveHudScoreDeltaAnchor() {
    const hudScoreEl = document.getElementById("hud-score-total");
    if (!hudScoreEl) return null;
    return (
      hudScoreEl.closest(".gc-score-pill")
      || hudScoreEl.closest(".gc-hud-panel-score")
      || hudScoreEl.parentElement
    );
  }

  function _scheduleScoreDeltaRemoval(deltaEl) {
    if (!deltaEl) return;
    if (_scoreDeltaRemoveTimer != null) clearTimeout(_scoreDeltaRemoveTimer);

    const remove = () => {
      deltaEl.removeEventListener("animationend", onAnimEnd);
      if (deltaEl.isConnected) deltaEl.remove();
      if (_scoreDeltaEl === deltaEl) _scoreDeltaEl = null;
      _scoreDeltaRemoveTimer = null;
    };
    const onAnimEnd = (ev) => {
      if (ev.target !== deltaEl) return;
      remove();
    };

    deltaEl.addEventListener("animationend", onAnimEnd);
    _scoreDeltaRemoveTimer = GC.setSafeTimeout(remove, SCORE_DELTA_REMOVE_FALLBACK_MS);
  }

  function pulseScore(anchorEl) {
    if (!anchorEl) return;
    anchorEl.classList.remove("gc-score-pulse");
    void anchorEl.offsetWidth;
    anchorEl.classList.add("gc-score-pulse");
  }

  function showScoreDelta(deltaValue, landingTotal = null) {
    const anchorEl = _resolveHudScoreDeltaAnchor();
    if (!anchorEl) return false;

    const d = Math.floor(Number(deltaValue || 0));
    if (!Number.isFinite(d) || d === 0) return false;

    const landing = Number.isFinite(Number(landingTotal))
      ? Number(landingTotal)
      : Number(_scoreState.lastServerTotal);
    if (Number.isFinite(landing) && _scoreState.lastDeltaEventTotal === landing) {
      return false;
    }

    _purgeAllScoreDeltaNodes();

    if (Number.isFinite(landing)) {
      _scoreState.lastDeltaEventTotal = landing;
    }

    const style = getComputedStyle(anchorEl);
    if (style.position === "static") anchorEl.style.position = "relative";

    const deltaEl = document.createElement("span");
    deltaEl.className = "gc-score-delta";
    deltaEl.setAttribute("aria-hidden", "true");
    const sign = d > 0 ? "+" : "";
    deltaEl.textContent = `${sign}${fmtNumber(d)}`;
    anchorEl.appendChild(deltaEl);
    _scoreDeltaEl = deltaEl;

    void deltaEl.offsetWidth;
    deltaEl.classList.add("show");

    pulseScore(anchorEl);
    _scheduleScoreDeltaRemoval(deltaEl);
    return true;
  }

  if (!GC._scoreDeltaCleanupRegistered) {
    GC._scoreDeltaCleanupRegistered = true;
    GC.registerCleanup(_purgeAllScoreDeltaNodes);
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
    fuel_storage: { levelId: "level-fuel_storage", statusId: "status-fuel_storage", btnId: "btn-fuel_storage" },
    fuel_cell_plant: { levelId: "level-fuel_cell_plant", statusId: "status-fuel_cell_plant", btnId: "btn-fuel_cell_plant" },
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
    fuel_storage: "Brennzellen-Depot",
    fuel_cell_plant: "Brennzellenfabrik",
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

  const DEFENSEQ = {
    active: {
      finishTime: 0,
      totalSeconds: 0,
    },
  };

  function _hasLiveCountdownAt() {
    const now = getTimerServerNow();
    for (const el of queryTimerElements()) {
      syncTimerElement(el);
      if (timerRemainingSeconds(el, now) > 0) return true;
    }
    const previewArrival = document.querySelector("[data-preview-arrival][data-countdown-at]");
    if (previewArrival) {
      syncTimerElement(previewArrival);
      if (timerRemainingSeconds(previewArrival, now) > 0) return true;
    }
    return false;
  }

  function _hasStaleMovementCountdown() {
    const now = getTimerServerNow();
    for (const el of queryTimerElements()) {
      syncTimerElement(el);
      const scope = el.dataset.countdownScope || "";
      const kind = el.dataset.timerKind || inferTimerKind(el);
      if (scope !== "fleet" && scope !== "overview" && kind !== "fleet") continue;
      if (Number(el.dataset.timerTarget || el.dataset.countdownAt || 0) && timerRemainingSeconds(el, now) <= 0) {
        return true;
      }
    }
    return false;
  }

  function _hasVisibleOverviewResearchTimer() {
    const box = document.getElementById("overview-research-active");
    if (!box || box.hidden || box.style.display === "none") return false;
    const finishAt = parseTimerTarget(box.dataset.finishAt || 0);
    if (!finishAt) return false;
    const srvRem = box.dataset.serverRemaining;
    return queueJobRemainingSeconds(
      finishAt,
      getTimerServerNow(),
      srvRem === undefined || srvRem === "" ? NaN : Number(srvRem)
    ) > 0;
  }

  function _hasActiveProgressJobs() {
    const now = getTimerServerNow();
    const buildFinish = BUILDQ.active.finishTime > now;
    const researchFinish = RESEARCHQ.active.finishTime > now;
    const shipyardFinish = SHIPYARDQ.active.finishTime > now;
    const defenseFinish = DEFENSEQ.active.finishTime > now;
    return (
      buildFinish ||
      researchFinish ||
      shipyardFinish ||
      defenseFinish ||
      !!document.querySelector(".build-job.build-job-active") ||
      !!document.querySelector(".research-job.research-job-active") ||
      !!document.querySelector(".shipyard-job.shipyard-job-active") ||
      _hasVisibleOverviewResearchTimer() ||
      !!document.querySelector(".planet-evolution-page .gc-card-queue-block[data-gc-card-queue='1']") ||
      _hasLiveCountdownAt()
    );
  }

  function _maybeRefreshStaleMovementCountdowns() {
    if (!shouldRunGameLoop() || _authLoopAborted) return;
    if (!_anyStaleMovementCountdownDom()) return;
    if (_movementCountdownRefreshPending.fleet) requestMovementCountdownRefresh("fleet");
    else requestMovementCountdownRefresh("overview");
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

  function _updateBuildQueueCompact(count) {
    const labelEl = document.getElementById("build-queue-compact-label");
    if (!labelEl) return;

    const n = Math.max(0, Math.floor(Number(count || 0)));
    if (!n) {
      _setIfChanged(labelEl, t("build_queue_compact_idle", "Keine Bauaufträge"));
      return;
    }
    _setIfChanged(
      labelEl,
      tf("build_queue_compact_active", { count: n }, `${n} Bauaufträge aktiv`)
    );
  }

  function _getActiveBuildingTab() {
    const pageRoot = document.querySelector("[data-buildings-page]");
    if (pageRoot?.dataset?.activeBuildingTab) return pageRoot.dataset.activeBuildingTab;
    const sub = document.getElementById("gc-nav-buildings-sub");
    const active = sub?.querySelector("[data-building-tab].active");
    return active?.dataset?.buildingTab || "resources";
  }

  function hideBuildingsSubnav() {
    const sub = document.getElementById("gc-nav-buildings-sub");
    if (!sub) return;
    sub.hidden = true;
    sub.classList.add("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "true");
    sub.querySelectorAll("[data-building-tab]").forEach((btn) => {
      btn.disabled = true;
      btn.tabIndex = -1;
    });
  }

  function showBuildingsSubnav() {
    const sub = document.getElementById("gc-nav-buildings-sub");
    if (!sub) return;
    sub.hidden = false;
    sub.classList.remove("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "false");
    sub.querySelectorAll("[data-building-tab]").forEach((btn) => {
      btn.disabled = false;
      btn.tabIndex = 0;
    });
  }

  function syncBuildingSidebarTab(tab) {
    const sub = document.getElementById("gc-nav-buildings-sub");
    if (!sub) return;
    const target = String(tab || "resources");
    sub.querySelectorAll("[data-building-tab]").forEach((el) => {
      el.classList.toggle("active", el.dataset.buildingTab === target);
    });
  }

  function activateBuildingTabByName(targetTab, focusEl) {
    const pageRoot = document.querySelector("[data-buildings-page]");
    if (!pageRoot) return;
    const tab = String(targetTab || "resources");
    pageRoot.querySelectorAll(".tab-content[data-tab]").forEach((c) => {
      const isActive = c.dataset.tab === tab;
      c.classList.toggle("active", isActive);
      if (c.getAttribute("role") === "tabpanel") c.hidden = !isActive;
    });
    syncBuildingSidebarTab(tab);
    pageRoot.dataset.activeBuildingTab = tab;
    if (focusEl && typeof focusEl.focus === "function") focusEl.focus();
  }

  function bindBuildingTabsOnce() {
    if (GC._tabsBound) return;
    GC._tabsBound = true;

    document.addEventListener("click", (e) => {
      const subBtn = e.target.closest("#gc-nav-buildings-sub [data-building-tab]");
      if (subBtn) {
        if (GC.detectPage() !== "buildings") return;
        if (subBtn.disabled || subBtn.closest("#gc-nav-buildings-sub")?.hidden) return;
        activateBuildingTabByName(subBtn.dataset.buildingTab, subBtn);
        return;
      }

      const btn = e.target.closest(".building-tabs .tab-btn");
      if (!btn || btn.closest("#messages-tabs")) return;
      if (btn.tagName === "A") e.preventDefault();
      activateBuildingTabByName(btn.dataset.tab, btn);
    });
  }

  function initBuildings() {
    bindBuildingTabsOnce();
    showBuildingsSubnav();
    const pageRoot = document.querySelector("[data-buildings-page]");
    if (!pageRoot) return;
    const initialTab = pageRoot.dataset.activeBuildingTab || "resources";
    activateBuildingTabByName(initialTab, null);
    GC.startProgressTicker();
    GC.registerCleanup(hideBuildingsSubnav);
  }

  const TRADING_NAV_PAGES = new Set([
    "trader_hub",
    "logistics",
    "inventory",
    "auction_house",
    "galactic_politics",
    "skilltree",
    "premium",
  ]);
  const MILITARY_NAV_PAGES = new Set(["shipyard", "defense"]);

  function isTradingNavPage(page) {
    return TRADING_NAV_PAGES.has(String(page || ""));
  }

  function isMilitaryNavPage(page) {
    return MILITARY_NAV_PAGES.has(String(page || ""));
  }

  function hideTradingSubnav() {
    const sub = document.getElementById("gc-nav-trading-sub");
    if (!sub) return;
    sub.hidden = true;
    sub.classList.add("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "true");
  }

  function showTradingSubnav() {
    const sub = document.getElementById("gc-nav-trading-sub");
    if (!sub) return;
    sub.hidden = false;
    sub.classList.remove("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "false");
  }

  function syncTradingSubnav(page) {
    const sub = document.getElementById("gc-nav-trading-sub");
    const parent = document.getElementById("gc-nav-trading-parent");
    if (!sub || !parent) return;

    const activePage = page || GC.detectPage();
    const onTradingPage = isTradingNavPage(activePage);

    parent.classList.toggle("active", onTradingPage);
    sub.querySelectorAll("[data-trading-nav]").forEach((el) => {
      el.classList.toggle("active", el.dataset.tradingNav === activePage);
    });

    if (onTradingPage) {
      showTradingSubnav();
      return;
    }
    hideTradingSubnav();
  }

  function hideMilitarySubnav() {
    const sub = document.getElementById("gc-nav-military-sub");
    if (!sub) return;
    sub.hidden = true;
    sub.classList.add("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "true");
  }

  function showMilitarySubnav() {
    const sub = document.getElementById("gc-nav-military-sub");
    if (!sub) return;
    sub.hidden = false;
    sub.classList.remove("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "false");
  }

  function syncMilitarySubnav(page) {
    const sub = document.getElementById("gc-nav-military-sub");
    const parent = document.getElementById("gc-nav-military-parent");
    if (!sub || !parent) return;

    const activePage = page || GC.detectPage();
    const onMilitaryPage = isMilitaryNavPage(activePage);

    parent.classList.toggle("active", onMilitaryPage);
    sub.querySelectorAll("[data-military-nav]").forEach((el) => {
      el.classList.toggle("active", el.dataset.militaryNav === activePage);
    });

    if (onMilitaryPage) {
      showMilitarySubnav();
      return;
    }
    hideMilitarySubnav();
  }

  function updateResearchQueueActions(researchRaw) {
    const list = document.querySelector(".research-prog-list");
    if (!list) return;

    const summary = researchRaw?.summary || null;
    const count = summary?.count ?? (Array.isArray(researchRaw?.queue) ? researchRaw.queue.length : 0);
    const limit = summary?.limit ?? 3;
    const queueFull = count >= limit;

    list.querySelectorAll(".gc-bld-card-head-action[data-tech-key], .tech-status-cell[data-tech-key]").forEach((cell) => {
      if (cell.querySelector(".gc-bld-head-action-btn--warn[disabled]")) return;
      if (cell.querySelector(".gc-bld-head-action-btn--afford[disabled]")) return;

      const techKey = cell.dataset.techKey;
      if (!techKey) return;

      if (queueFull) {
        const fullLabel = t("research_btn_queue_full", "Forschungsliste voll");
        const queueBtn = cell.querySelector(".gc-bld-head-action-btn--locked");
        if (!queueBtn) {
          cell.innerHTML =
            `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--locked btn-research" type="button" disabled` +
            ` aria-disabled="true" title="${fullLabel}" aria-label="${fullLabel}"><span class="gc-bld-head-action-icon">🔒</span></button>`;
        }
        return;
      }

      if (cell.querySelector(".gc-bld-head-action-btn--locked")) {
        const queueActive = count > 0;
        const actionLabel = queueActive
          ? t("research_btn_queue", "Anreihen")
          : t("research_btn_start", "Forschung starten");
        const href = `/research_start/${encodeURIComponent(techKey)}`;
        cell.innerHTML =
          `<a href="${href}" class="gc-bld-head-action-btn gc-bld-head-action-btn--go btn-research"` +
          ` title="${actionLabel}" aria-label="${actionLabel}"><span class="gc-bld-head-action-icon">+</span></a>`;
      }
    });
  }

  function updateBuildQueueActions(buildQueueRaw) {
    if (!document.querySelector(".buildings-prog-list")) return;

    const summary = buildQueueRaw?.summary || null;
    const count = summary?.count ?? (Array.isArray(buildQueueRaw?.queue) ? buildQueueRaw.queue.length : 0);
    const limit = summary?.limit ?? 3;
    const queueFull = count >= limit;
    const fullLabel = t("buildings_btn_queue_full", "Warteschlange voll");
    const queueActive = count > 0;
    const actionLabel = queueActive
      ? t("research_btn_queue", "Anreihen")
      : t("buildings_btn_upgrade", "Ausbau starten");
    const tab = _getActiveBuildingTab();

    document.querySelectorAll(".buildings-prog-list .gc-bld-card-head-action[data-building], .buildings-prog-list .bcell-action[data-building]").forEach((cell) => {
      if (cell.querySelector(".gc-bld-head-action-btn--warn[disabled]")) return;
      if (cell.querySelector(".gc-bld-head-action-btn--afford[disabled]")) return;
      if (cell.querySelector(".gc-bld-head-action-btn--max")) return;

      const bType = cell.dataset.building;
      if (!bType) return;

      if (queueFull) {
        const queueBtn = cell.querySelector(".gc-bld-head-action-btn--locked");
        if (!queueBtn) {
          cell.innerHTML =
            `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--locked btn-upgrade" type="button" disabled` +
            ` aria-disabled="true" title="${fullLabel}" aria-label="${fullLabel}"><span class="gc-bld-head-action-icon">🔒</span></button>`;
        }
        return;
      }

      if (cell.querySelector(".gc-bld-head-action-btn--locked")) {
        const href = `/upgrade/${encodeURIComponent(bType)}?src=buildings&tab=${encodeURIComponent(tab)}`;
        cell.innerHTML =
          `<a id="btn-${bType}" data-building="${bType}" href="${href}"` +
          ` class="gc-bld-head-action-btn gc-bld-head-action-btn--go btn-upgrade"` +
          ` title="${actionLabel}" aria-label="${actionLabel}"><span class="gc-bld-head-action-icon">+</span></a>`;
      }
    });
  }

  function _stripCardQueueOwnerClasses(cardEl) {
    if (!cardEl) return;
    cardEl.classList.remove(
      "gc-building-card--in-queue",
      "gc-building-card--queue-active",
      "gc-building-card--queue-pending",
      "gc-research-card--in-queue",
      "gc-research-card--queue-active",
      "gc-research-card--queue-pending",
      "gc-ship-card--in-queue",
      "gc-ship-card--queue-active",
      "gc-ship-card--queue-pending",
      "gc-planet-tech-card--in-queue",
      "gc-planet-tech-card--queue-active",
      "gc-planet-tech-card--queue-pending",
      "gc-ascension-card--in-queue",
      "gc-ascension-card--queue-active",
      "gc-ascension-card--queue-pending"
    );
  }

  GC.clearCardQueueBlock = function clearCardQueueBlock(cardEl) {
    if (!cardEl) return;
    cardEl.querySelectorAll("[data-gc-card-queue], [data-hero-queue]").forEach((block) => block.remove());
    resetHeroImageProgress(cardEl);
    _stripCardQueueOwnerClasses(cardEl);
  };

  function findCardQueueBlockByJobId(cardEl, jobId) {
    if (!cardEl) return null;
    const id = Math.floor(Number(jobId || 0));
    if (id <= 0) return null;
    return cardEl.querySelector(`[data-gc-card-queue][data-job-id="${id}"]`);
  }

  function syncCardQueueOwnerClassesFromBlocks(cardEl, fallbackDomain) {
    if (!cardEl) return;
    const blocks = Array.from(cardEl.querySelectorAll("[data-gc-card-queue]")).filter(
      (block) => block.dataset.heroQueue === "1" || block.classList.contains("gc-card-queue-block")
    );
    if (!blocks.length) {
      _stripCardQueueOwnerClasses(cardEl);
      return;
    }
    const domain =
      fallbackDomain || String(blocks[0].dataset.timerDomain || "building");
    const cardPrefix = _cardQueueClassPrefix(domain);
    const hasActive = Array.from(blocks).some((b) => b.dataset.queueActive === "1");
    cardEl.classList.add(`${cardPrefix}--in-queue`);
    cardEl.classList.toggle(`${cardPrefix}--queue-active`, hasActive);
    cardEl.classList.toggle(`${cardPrefix}--queue-pending`, !hasActive);
  }

  function reorderCardQueueBlocks(cardEl) {
    if (!cardEl) return;
    const blocks = Array.from(cardEl.querySelectorAll("[data-gc-card-queue]"));
    if (blocks.length < 2) return;
    blocks.sort((a, b) => {
      const pa = Math.floor(Number(a.dataset.queuePosition || 0));
      const pb = Math.floor(Number(b.dataset.queuePosition || 0));
      if (pa !== pb) return pa - pb;
      const ja = Math.floor(Number(a.dataset.jobId || 0));
      const jb = Math.floor(Number(b.dataset.jobId || 0));
      return ja - jb;
    });
    const slot = cardEl.querySelector(".gc-bld-card-queue-slot");
    if (slot) {
      blocks.forEach((block) => slot.appendChild(block));
      return;
    }
    const anchor = cardEl.querySelector(".gc-bld-card-meta, .gc-prog-main");
    blocks.forEach((block) => {
      if (anchor) cardEl.insertBefore(block, anchor);
      else cardEl.appendChild(block);
    });
  }

  GC.clearBuildingCardQueue = GC.clearCardQueueBlock;

  function _cardQueueDomain(queueJob, opts) {
    const fromOpts = opts && opts.domain ? String(opts.domain) : "";
    if (fromOpts) return fromOpts;
    const ownerType = String(queueJob.owner_type || "");
    if (ownerType === "research") return "research";
    if (ownerType === "shipyard") return "shipyard";
    if (ownerType === "planet_research") return "planet_research";
    if (ownerType === "ascension") return "ascension";
    if (ownerType === "defense") return "defense";
    return "building";
  }

  function _cardQueueClassPrefix(domain) {
    if (domain === "research") return "gc-research-card";
    if (domain === "shipyard" || domain === "defense") return "gc-ship-card";
    if (domain === "planet_research") return "gc-planet-tech-card";
    if (domain === "ascension") return "gc-ascension-card";
    return "gc-building-card";
  }

  /**
   * GC-536B/C — queue status inside building/research cards.
   * Safe DOM: createElement + textContent (+ progress width style only).
   */
  function cardQueueJobSignature(queueJob) {
    if (!queueJob || typeof queueJob !== "object") return "";
    return [
      queueJob.owner_type || "",
      queueJob.owner_key || "",
      queueJob.job_id || 0,
      queueJob.status || "",
      queueJob.queue_position || 0,
      Math.floor(Number(queueJob.finish_at || 0)),
      Math.floor(Number(queueJob.start_at || 0)),
      Math.floor(Number(queueJob.target_amount || 0)),
      Math.floor(Number(queueJob.target_level || 0)),
      Math.floor(Number(queueJob.target_phase || 0)),
    ].join(":");
  }

  /** In-place timer patch only when the same live job is still active/queued with stable targets. */
  function canPatchCardQueueInPlace(existing, queueJob) {
    if (!existing || !queueJob || typeof queueJob !== "object") return false;
    const jobId = Math.floor(Number(queueJob.job_id || 0));
    const prevJobId = Math.floor(Number(existing.dataset.jobId || 0));
    if (jobId <= 0 || jobId !== prevJobId) return false;

    const status = String(queueJob.status || "");
    const wasActive = existing.dataset.queueActive === "1";
    const isActive = status === "active";
    if (wasActive !== isActive) return false;

    const finishAt = Math.floor(Number(queueJob.finish_at || 0));
    const prevFinish = parseTimerTarget(existing.dataset.finishAt || 0);

    if (!finishAt || finishAt !== prevFinish) return false;

    return true;
  }

  function syncCardQueueOwnerClasses(cardEl, queueJob, domain) {
    if (!cardEl || !queueJob) return;
    const cardPrefix = _cardQueueClassPrefix(domain);
    const isActive = String(queueJob.status || "") === "active";
    cardEl.classList.add(`${cardPrefix}--in-queue`);
    cardEl.classList.toggle(`${cardPrefix}--queue-active`, isActive);
    cardEl.classList.toggle(`${cardPrefix}--queue-pending`, !isActive);
  }

  function findHeroQueue(cardEl) {
    return cardEl?.querySelector("[data-hero-queue]");
  }

  function findHeroImgStack(cardEl) {
    return cardEl?.querySelector(".gc-bld-hero-img-stack");
  }

  function ensureHeroDualImageStack(stack) {
    if (!stack || stack.querySelector(".gc-bld-card-hero-img--color")) return;
    const single = stack.querySelector(":scope > .gc-bld-card-hero-img:not(.gc-bld-card-hero-img--muted):not(.gc-bld-card-hero-img--color)");
    if (!single) return;
    const muted = single.cloneNode(true);
    muted.classList.add("gc-bld-card-hero-img--muted");
    const color = single.cloneNode(true);
    color.classList.add("gc-bld-card-hero-img--color");
    color.setAttribute("aria-hidden", "true");
    single.replaceWith(muted, color);
  }

  function resetHeroSingleImage(stack) {
    if (!stack) return;
    const muted = stack.querySelector(".gc-bld-card-hero-img--muted");
    if (!muted) return;
    const single = muted.cloneNode(true);
    single.classList.remove("gc-bld-card-hero-img--muted", "gc-bld-card-hero-img--color");
    single.removeAttribute("aria-hidden");
    single.style.clipPath = "";
    stack.querySelector(".gc-bld-card-hero-img--color")?.remove();
    muted.replaceWith(single);
  }

  function applyHeroImageProgress(cardEl, pct) {
    const stack = findHeroImgStack(cardEl);
    if (!stack) return;
    const progress = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    stack.classList.add("gc-bld-hero-img-stack--progress");
    stack.style.setProperty("--hero-progress-pct", `${progress}%`);
    ensureHeroDualImageStack(stack);
    const color = stack.querySelector(".gc-bld-card-hero-img--color");
    if (color) color.style.clipPath = `inset(${100 - progress}% 0 0 0)`;
  }

  function applyHeroQueuedMark(cardEl) {
    resetHeroImageProgress(cardEl);
  }

  function resetHeroImageProgress(cardEl) {
    const stack = findHeroImgStack(cardEl);
    if (!stack) return;
    stack.classList.remove("gc-bld-hero-img-stack--progress");
    stack.style.removeProperty("--hero-progress-pct");
    resetHeroSingleImage(stack);
  }

  function setHeroTimeChipIdle(cardEl, seconds, title) {
    if (!cardEl || cardEl.classList.contains("gc-building-card--in-queue") || cardEl.classList.contains("gc-research-card--in-queue")) {
      return;
    }
    const chip = cardEl.querySelector("[data-hero-time-chip]");
    if (!chip) return;
    const label = formatDuration(seconds);
    chip.title = title || chip.title || "";
    chip.innerHTML = `<span class="gc-hero-time-text">${label}</span>`;
  }

  function ensureHeroTimeChipTimer(cardEl, queueJob, timerKind, refreshOnZero) {
    const chip = cardEl?.querySelector("[data-hero-time-chip]");
    if (!chip || !queueJob) return null;
    if (String(queueJob.status || "") !== "active") return null;
    let timerEl = chip.querySelector(".gc-card-queue-timer");
    const timerTarget = cardQueueTimerTarget(queueJob, true);
    if (!timerEl) {
      timerEl = document.createElement("div");
      timerEl.className = "gc-card-queue-timer gc-mono";
      chip.innerHTML = "";
      chip.appendChild(timerEl);
    }
    if (timerTarget > 0) {
      const remaining = queueJobRemainingSeconds(
        timerTarget,
        getTimerServerNow(),
        resolveQueueJobRemaining(queueJob)
      );
      applyQueueJobTimerAttrs(timerEl, timerTarget, timerKind, refreshOnZero, remaining);
      timerEl.textContent = formatEta(queueTimerDisplaySeconds(remaining));
    }
    return timerEl;
  }

  function ensureHeroQueuedBadgeTimer(block, queueJob, timerKind, refreshOnZero) {
    if (!block || !queueJob) return null;
    const position = Math.max(1, Math.floor(Number(queueJob.queue_position || block.dataset.queuePosition || 1)));
    let badge = block.querySelector(".gc-bld-hero-queue-badge");
    if (!badge) {
      badge = document.createElement("div");
      badge.className = "gc-bld-hero-queue-badge gc-mono";
      block.innerHTML = "";
      block.appendChild(badge);
    }
    let lineEl = badge.querySelector(".gc-bld-hero-queue-badge-line");
    let subEl = badge.querySelector(".gc-bld-hero-queue-badge-sub");
    if (!lineEl || !subEl) {
      badge.innerHTML =
        '<span class="gc-bld-hero-queue-badge-line"></span>' +
        '<span class="gc-bld-hero-queue-badge-sub">' +
        `<span class="gc-bld-hero-queue-starts-label">${t("queue_starts_in", "Startet in")}</span> ` +
        "</span>";
      lineEl = badge.querySelector(".gc-bld-hero-queue-badge-line");
      subEl = badge.querySelector(".gc-bld-hero-queue-badge-sub");
    }
    const queuedLabel = tf("queue_card_status_queued", { n: position }, `QUEUE #${position}`);
    _setIfChanged(lineEl, queuedLabel);
    let timerEl = subEl?.querySelector(".gc-card-queue-timer");
    if (!timerEl && subEl) {
      timerEl = document.createElement("div");
      timerEl.className = "gc-card-queue-timer gc-mono";
      subEl.appendChild(timerEl);
    }
    const timerTarget = cardQueueTimerTarget(queueJob, false);
    if (timerEl && timerTarget > 0) {
      const remaining = queueJobRemainingSeconds(
        timerTarget,
        getTimerServerNow(),
        resolveQueueJobRemaining(queueJob)
      );
      applyQueueJobTimerAttrs(timerEl, timerTarget, timerKind, refreshOnZero, remaining);
      timerEl.textContent = formatEta(queueTimerDisplaySeconds(remaining));
    }
    return timerEl;
  }

  function applyHeroQueueVisual(cardEl, block, queueJob, pct, remaining, timerKind, refreshOnZero) {
    if (!cardEl || !block || !queueJob) return;
    const isActive = String(queueJob.status || "") === "active";
    const progress = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    const pctEl = block.querySelector(".gc-bld-hero-queue-pct");
    const centerEl = block.querySelector(".gc-bld-hero-queue-center");
    block.classList.toggle("gc-bld-hero-queue--active", isActive);
    block.classList.toggle("gc-bld-hero-queue--queued", !isActive);
    if (isActive) {
      applyHeroImageProgress(cardEl, progress);
      if (pctEl) _setIfChanged(pctEl, `${progress}%`);
      if (centerEl) {
        centerEl.setAttribute("role", "progressbar");
        centerEl.setAttribute("aria-valuemin", "0");
        centerEl.setAttribute("aria-valuemax", "100");
        centerEl.setAttribute("aria-valuenow", String(progress));
      }
      const timerEl = cardEl.querySelector("[data-hero-time-chip] .gc-card-queue-timer");
      if (timerEl && Number.isFinite(remaining)) {
        const eta = formatEta(queueTimerDisplaySeconds(remaining));
        _setIfChanged(timerEl, eta);
        block.title = eta;
      }
    } else {
      applyHeroQueuedMark(cardEl);
      if (timerKind) ensureHeroQueuedBadgeTimer(block, queueJob, timerKind, refreshOnZero || "game-state");
      centerEl?.removeAttribute("role");
      centerEl?.removeAttribute("aria-valuemin");
      centerEl?.removeAttribute("aria-valuemax");
      centerEl?.removeAttribute("aria-valuenow");
      const position = Math.max(1, Math.floor(Number(queueJob.queue_position || 1)));
      const queuedLabel = tf("queue_card_status_queued", { n: position }, `QUEUE #${position}`);
      block.title = queuedLabel;
    }
  }

  function patchHeroQueueInPlace(block, queueJob, opts) {
    const cardEl = block.closest("[data-building-row], [data-research-card], [data-building-card]");
    const { timerKind, refreshOnZero } = _cardQueueTimerMeta(queueJob, opts);
    const isActive = String(queueJob.status || "") === "active";
    const finishAt = Math.floor(Number(queueJob.finish_at || 0));
    const totalSeconds = Math.max(1, Math.floor(Number(queueJob.duration_seconds || block.dataset.totalSeconds || 1)));
    const now = getTimerServerNow();
    const timerTarget = cardQueueTimerTarget(queueJob, isActive);
    const remaining = timerTarget > 0
      ? queueJobRemainingSeconds(timerTarget, now, resolveQueueJobRemaining(queueJob))
      : Math.max(0, Math.floor(Number(queueJob.remaining_seconds || 0)));
    const progressPct = Math.max(0, Math.min(100, Math.floor(Number(queueJob.progress_pct || 0))));
    const pct = isActive
      ? (totalSeconds > 0 ? 100 * (1 - remaining / totalSeconds) : progressPct)
      : 0;

    if (isActive) {
      ensureHeroTimeChipTimer(cardEl, queueJob, timerKind, refreshOnZero);
    } else {
      ensureHeroQueuedBadgeTimer(block, queueJob, timerKind, refreshOnZero);
    }

    if (isActive && finishAt > 0) assignMonotonicServerRemaining(block, remaining, finishAt);
    applyHeroQueueVisual(cardEl, block, queueJob, pct, remaining, timerKind, refreshOnZero);
    return block;
  }

  function renderHeroQueueOverlay(cardEl, queueJob, opts) {
    const hero = cardEl.querySelector(".gc-bld-card-hero");
    if (!hero || !queueJob) return null;

    const options = opts && typeof opts === "object" ? opts : {};
    const domain = _cardQueueDomain(queueJob, options);
    if (domain !== "building" && domain !== "research") return null;

    const sig = cardQueueJobSignature(queueJob);
    const jobId = Math.floor(Number(queueJob.job_id || 0));
    let block = findHeroQueue(cardEl);
    if (!block) {
      block = document.createElement("div");
      block.className = "gc-bld-hero-queue gc-card-queue-block gc-card-queue-block--hero";
      block.dataset.heroQueue = "1";
      const levelBadge = hero.querySelector(".gc-bld-card-level");
      if (levelBadge) hero.insertBefore(block, levelBadge);
      else hero.appendChild(block);
    }

    cardEl.querySelectorAll("[data-hero-queue]").forEach((existing) => {
      if (existing !== block) existing.remove();
    });

    if (block && canPatchCardQueueInPlace(block, queueJob)) {
      block.dataset.queueSig = sig;
      patchHeroQueueInPlace(block, queueJob, options);
      syncCardQueueOwnerClassesFromBlocks(cardEl, domain);
      return block;
    }

    const { timerKind, refreshOnZero } = _cardQueueTimerMeta(queueJob, options);
    const status = String(queueJob.status || "");
    const position = Math.max(1, Math.floor(Number(queueJob.queue_position || 1)));
    const finishAt = Math.floor(Number(queueJob.finish_at || 0));
    const startAt = Math.floor(Number(queueJob.start_at || 0));
    const totalSeconds = Math.max(1, Math.floor(Number(queueJob.duration_seconds || 1)));
    const isActive = status === "active";
    const remaining = Math.max(0, Math.floor(Number(queueJob.remaining_seconds || 0)));
    const progressPct = Math.max(0, Math.min(100, Math.floor(Number(queueJob.progress_pct || 0))));

    block.className = `gc-bld-hero-queue gc-card-queue-block gc-card-queue-block--hero gc-card-queue-block--${isActive ? "active" : "queued"} gc-bld-hero-queue--${isActive ? "active" : "queued"}`;
    block.dataset.heroQueue = "1";
    block.dataset.gcCardQueue = "1";
    block.dataset.queueSig = sig;
    block.dataset.queueActive = isActive ? "1" : "0";
    block.dataset.timerDomain = domain;
    block.dataset.queuePosition = String(position);
    if (jobId > 0) block.dataset.jobId = String(jobId);
    if (startAt > 0) block.dataset.startAt = String(startAt);
    if (finishAt > 0) block.dataset.finishAt = String(finishAt);
    block.dataset.totalSeconds = String(totalSeconds);
    if (isActive && Number.isFinite(remaining)) assignMonotonicServerRemaining(block, remaining, finishAt);

    if (isActive) {
      block.innerHTML =
        '<div class="gc-bld-hero-queue-center"><span class="gc-bld-hero-queue-pct gc-mono"></span></div>';
    } else {
      block.innerHTML =
        '<div class="gc-bld-hero-queue-badge gc-mono">' +
        '<span class="gc-bld-hero-queue-badge-line"></span>' +
        '<span class="gc-bld-hero-queue-badge-sub">' +
        `<span class="gc-bld-hero-queue-starts-label">${t("queue_starts_in", "Startet in")}</span> ` +
        "</span></div>";
    }

    if (isActive) {
      ensureHeroTimeChipTimer(cardEl, queueJob, timerKind, refreshOnZero);
    } else {
      ensureHeroQueuedBadgeTimer(block, queueJob, timerKind, refreshOnZero);
    }

    let cancelBtn = block.querySelector(".gc-bld-hero-queue-cancel");
    if (jobId > 0) {
      if (!cancelBtn) {
        cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "gc-bld-hero-queue-cancel";
        cancelBtn.innerHTML = '<span class="gc-bld-head-action-icon">×</span>';
        block.appendChild(cancelBtn);
      }
      if (domain === "research") {
        cancelBtn.dataset.researchCancelId = String(jobId);
        delete cancelBtn.dataset.buildCancelId;
      } else {
        cancelBtn.dataset.buildCancelId = String(jobId);
        delete cancelBtn.dataset.researchCancelId;
      }
      cancelBtn.title = t("action_cancel", "Abbrechen");
      cancelBtn.setAttribute("aria-label", t("action_cancel", "Abbrechen"));
    } else if (cancelBtn) {
      cancelBtn.remove();
    }

    const pct = isActive
      ? (totalSeconds > 0 ? 100 * (1 - remaining / totalSeconds) : progressPct)
      : 0;
    applyHeroQueueVisual(cardEl, block, queueJob, pct, remaining, timerKind, refreshOnZero);
    syncCardQueueOwnerClassesFromBlocks(cardEl, domain);
    return block;
  }

  function _cardQueueTimerMeta(queueJob, opts) {
    const options = opts && typeof opts === "object" ? opts : {};
    const domain = _cardQueueDomain(queueJob, options);
    const timerKind = String(
      options.timerKind ||
        (domain === "research"
          ? "research"
          : domain === "shipyard"
            ? "shipyard"
            : domain === "planet_research"
              ? "planet_research"
              : domain === "ascension"
                ? "ascension"
              : domain === "defense"
                ? "defense"
                : "build")
    );
    const refreshOnZero = String(
      options.refreshOnZero ||
        (domain === "shipyard"
          ? "shipyard"
          : domain === "defense"
            ? "defense"
          : domain === "planet_research" || domain === "ascension"
            ? "planet_evolution"
            : "game-state")
    );
    return { domain, timerKind, refreshOnZero };
  }

  function patchCardQueueBlockInPlace(block, cardEl, queueJob, opts) {
    if (block?.dataset?.heroQueue === "1" || block?.classList?.contains("gc-bld-hero-queue")) {
      return patchHeroQueueInPlace(block, queueJob, opts);
    }
    const { domain, timerKind, refreshOnZero } = _cardQueueTimerMeta(queueJob, opts);
    const status = String(queueJob.status || "");
    const isActive = status === "active";
    const finishAt = Math.floor(Number(queueJob.finish_at || 0));
    const startAt = Math.floor(Number(queueJob.start_at || 0));
    const totalSeconds = Math.max(1, Math.floor(Number(queueJob.duration_seconds || block.dataset.totalSeconds || 1)));
    const now = getTimerServerNow();
    const timerTarget = cardQueueTimerTarget(queueJob, isActive);
    const remaining = timerTarget > 0
      ? queueJobRemainingSeconds(timerTarget, now, resolveQueueJobRemaining(queueJob))
      : Math.max(0, Math.floor(Number(queueJob.remaining_seconds || 0)));
    const progressPct = Math.max(0, Math.min(100, Math.floor(Number(queueJob.progress_pct || 0))));

    const timerEl = block.querySelector(".gc-card-queue-timer");
    if (timerEl && timerTarget > 0) {
      applyQueueJobTimerAttrs(timerEl, timerTarget, timerKind, refreshOnZero, remaining);
      const label = formatEta(queueTimerDisplaySeconds(remaining));
      _setIfChanged(timerEl, label);
    }

    const statusEl = block.querySelector(".gc-card-queue-status");
    if (statusEl) {
      const position = Math.max(1, Math.floor(Number(queueJob.queue_position || 1)));
      const statusLabel = isActive
        ? t("queue_card_status_active", "AKTIV")
        : tf("queue_card_status_queued", { n: position }, `QUEUE #${position}`);
      _setIfChanged(statusEl, statusLabel);
    }

    if (isActive) {
      assignMonotonicServerRemaining(block, remaining, finishAt);
      const pct = totalSeconds > 0 ? 100 * (1 - remaining / totalSeconds) : progressPct;
      const fillEl = block.querySelector(".gc-card-queue-bar-fill");
      const barEl = block.querySelector(".gc-card-queue-bar");
      _applyProgressFill(fillEl, pct);
      if (barEl) barEl.setAttribute("aria-valuenow", String(Math.max(0, Math.min(100, Math.round(pct)))));
    } else if (finishAt > 0) {
      assignMonotonicServerRemaining(block, remaining, finishAt);
    }

    return block;
  }

  /** Sync card queue blocks from owner map — one visible job per card (head only; rest hidden). */
  function patchCardQueuesFromOwnerMap(page, byOwner, listCards, ownerKeyFromCard, findCard) {
    if (!page || !byOwner || typeof byOwner !== "object") return;
    const activeKeys = new Set(Object.keys(byOwner));
    listCards(page).forEach((card) => {
      const key = ownerKeyFromCard(card);
      if (key && !activeKeys.has(key)) {
        delete card.dataset.queueHeadJobId;
        delete card.dataset.queuePending;
        GC.clearCardQueueBlock(card);
      }
    });
    Object.entries(byOwner).forEach(([ownerKey, jobs]) => {
      const card = findCard(page, ownerKey);
      if (!card) return;
      const list = (Array.isArray(jobs) ? jobs : [])
        .filter((job) => job && typeof job === "object")
        .slice()
        .sort((a, b) => {
          const pa = Math.floor(Number(a.queue_position || 0));
          const pb = Math.floor(Number(b.queue_position || 0));
          if (pa !== pb) return pa - pb;
          return Math.floor(Number(a.job_id || 0)) - Math.floor(Number(b.job_id || 0));
        });
      if (!list.length) {
        delete card.dataset.queueHeadJobId;
        delete card.dataset.queuePending;
        GC.clearCardQueueBlock(card);
        return;
      }
      const headJob = list.find((j) => String(j.status || "") === "active") || list[0];
      const headId = Math.floor(Number(headJob.job_id || 0));
      const prevHead = card.dataset.queueHeadJobId || "";
      const advanced = prevHead && headId > 0 && prevHead !== String(headId);

      card.querySelectorAll("[data-gc-card-queue]").forEach((block) => {
        const blockJobId = Math.floor(Number(block.dataset.jobId || 0));
        if (blockJobId !== headId) block.remove();
      });

      if (headId > 0) card.dataset.queueHeadJobId = String(headId);
      else delete card.dataset.queueHeadJobId;
      if (list.length > 1) card.dataset.queuePending = String(list.length - 1);
      else delete card.dataset.queuePending;

      const block = GC.renderCardQueueBlock(card, headJob);
      if (advanced && block) {
        block.classList.add("gc-card-queue-block--advance");
        block.addEventListener(
          "animationend",
          () => block.classList.remove("gc-card-queue-block--advance"),
          { once: true }
        );
      }
      syncCardQueueOwnerClassesFromBlocks(card, _cardQueueDomain(headJob));
    });
  }

  GC.renderCardQueueBlock = function renderCardQueueBlock(cardEl, queueJob, opts) {
    if (!cardEl || !queueJob || typeof queueJob !== "object") return null;

    const options = opts && typeof opts === "object" ? opts : {};
    const domain = _cardQueueDomain(queueJob, options);
    if (domain === "building" || domain === "research") {
      return renderHeroQueueOverlay(cardEl, queueJob, options);
    }

    const sig = cardQueueJobSignature(queueJob);
    const jobId = Math.floor(Number(queueJob.job_id || 0));
    const existing =
      jobId > 0 ? findCardQueueBlockByJobId(cardEl, jobId) : cardEl.querySelector("[data-gc-card-queue]");
    if (existing && canPatchCardQueueInPlace(existing, queueJob)) {
      existing.dataset.queueSig = sig;
      if (String(existing.dataset.queueZeroFiredFor || "").split(":")[0] !== String(jobId)) {
        delete existing.dataset.queueZeroFiredFor;
      }
      patchCardQueueBlockInPlace(existing, cardEl, queueJob, options);
      syncCardQueueOwnerClassesFromBlocks(cardEl, domain);
      return existing;
    }

    const { timerKind, refreshOnZero } = _cardQueueTimerMeta(queueJob, options);

    if (existing) existing.remove();

    const status = String(queueJob.status || "");
    const position = Math.max(1, Math.floor(Number(queueJob.queue_position || 1)));
    const remaining = Math.max(0, Math.floor(Number(queueJob.remaining_seconds || 0)));
    const progressPct = Math.max(0, Math.min(100, Math.floor(Number(queueJob.progress_pct || 0))));
    const finishAt = Math.floor(Number(queueJob.finish_at || 0));
    const startAt = Math.floor(Number(queueJob.start_at || 0));
    const totalSeconds = Math.max(1, Math.floor(Number(queueJob.duration_seconds || 1)));
    const isActive = status === "active";
    const targetLevel = Math.floor(Number(queueJob.target_level || 0));
    const currentLevel = Math.max(
      0,
      Math.floor(Number(queueJob.current_level ?? (targetLevel > 0 ? targetLevel - 1 : 0)))
    );

    const block = document.createElement("div");
    block.className = `gc-card-queue-block gc-card-queue-block--${domain} gc-card-queue-block--${isActive ? "active" : "queued"}`;
    block.dataset.gcCardQueue = "1";
    block.dataset.queueSig = sig;
    block.dataset.queueActive = isActive ? "1" : "0";
    block.dataset.timerDomain = domain;
    block.dataset.queuePosition = String(position);
    if (jobId > 0) block.dataset.jobId = String(jobId);
    delete block.dataset.queueZeroFiredFor;
    delete block.dataset.queueZeroFiredAt;
    if (startAt > 0) block.dataset.startAt = String(startAt);
    if (finishAt > 0) block.dataset.finishAt = String(finishAt);
    block.dataset.totalSeconds = String(totalSeconds);
    if (isActive && Number.isFinite(remaining)) {
      assignMonotonicServerRemaining(block, remaining, finishAt);
    }

    const head = document.createElement("div");
    head.className = "gc-card-queue-head";

    const glyph = document.createElement("span");
    glyph.className = "gc-card-queue-glyph";
    if (domain === "research") glyph.classList.add("gc-card-queue-glyph--research");
    else if (domain === "shipyard") glyph.classList.add("gc-card-queue-glyph--shipyard");
    else if (domain === "planet_research") glyph.classList.add("gc-card-queue-glyph--planet-research");
    else if (domain === "ascension") glyph.classList.add("gc-card-queue-glyph--ascension");
    else if (domain === "defense") glyph.classList.add("gc-card-queue-glyph--defense");
    glyph.setAttribute("aria-hidden", "true");
    head.appendChild(glyph);

    const statusEl = document.createElement("span");
    statusEl.className = "gc-card-queue-status";
    if (isActive) {
      statusEl.textContent = t("queue_card_status_active", "AKTIV");
    } else {
      statusEl.textContent = tf("queue_card_status_queued", { n: position }, `QUEUE #${position}`);
    }
    head.appendChild(statusEl);
    block.appendChild(head);

    const labelKey = String(queueJob.label_key || queueJob.label || "");
    if (labelKey && (domain === "planet_research" || domain === "ascension")) {
      const titleEl = document.createElement("div");
      titleEl.className = "gc-card-queue-target gc-mono";
      titleEl.textContent = t(labelKey, String(queueJob.owner_key || ""));
      block.appendChild(titleEl);
    }

    const targetAmount = Math.floor(Number(queueJob.target_amount || 0));
    const shipKey = String(queueJob.owner_key || "");
    if ((domain === "shipyard" || domain === "defense") && targetAmount > 1 && shipKey) {
      const qtyEl = document.createElement("div");
      qtyEl.className = "gc-card-queue-quantity gc-mono";
      const itemLabel =
        domain === "defense"
          ? t(queueJob.defense_label_key || `defense_${shipKey}`, shipKey)
          : t(queueJob.ship_label_key || `fleet_ship_${shipKey}`, shipKey);
      qtyEl.textContent = `${fmtNumber(targetAmount)}× ${itemLabel}`;
      block.appendChild(qtyEl);
    } else if (targetLevel > 0) {
      const levelEl = document.createElement("div");
      levelEl.className = "gc-card-queue-level gc-mono";
      const lvlShort = t("label_level_short", "L");
      levelEl.textContent = `${lvlShort}${currentLevel} → ${lvlShort}${targetLevel}`;
      block.appendChild(levelEl);
    } else if (domain === "ascension") {
      const targetPhase = Math.floor(Number(queueJob.target_phase || 0));
      if (targetPhase > 0) {
        const phaseEl = document.createElement("div");
        phaseEl.className = "gc-card-queue-phase gc-mono";
        phaseEl.textContent = tf("pe_ascension_phase", { n: targetPhase }, `Phase ${targetPhase}`);
        block.appendChild(phaseEl);
      } else if (queueJob.label_key || queueJob.label) {
        const labelEl = document.createElement("div");
        labelEl.className = "gc-card-queue-target gc-mono";
        labelEl.textContent = t(queueJob.label_key || queueJob.label, String(queueJob.owner_key || ""));
        block.appendChild(labelEl);
      }
    }

    const timerEl = document.createElement("div");
    timerEl.className = "gc-card-queue-timer gc-mono";
    const waitTarget = cardQueueTimerTarget(queueJob, isActive);
    if (waitTarget > 0) {
      const displayRemaining = queueJobRemainingSeconds(
        waitTarget,
        getTimerServerNow(),
        resolveQueueJobRemaining(queueJob)
      );
      applyQueueJobTimerAttrs(timerEl, waitTarget, timerKind, refreshOnZero, displayRemaining);
      timerEl.textContent = formatEta(queueTimerDisplaySeconds(displayRemaining));
    } else if (!isActive) {
      timerEl.textContent = formatEta(Math.max(0, Math.floor(Number(queueJob.remaining_seconds || 0))));
    }
    block.appendChild(timerEl);

    if (isActive) {
      const bar = document.createElement("div");
      bar.className = "gc-card-queue-bar";
      bar.setAttribute("role", "progressbar");
      bar.setAttribute("aria-valuemin", "0");
      bar.setAttribute("aria-valuemax", "100");
      bar.setAttribute("aria-valuenow", String(progressPct));

      const fill = document.createElement("div");
      fill.className = "gc-card-queue-bar-fill gc-progress-smooth";
      fill.style.width = `${progressPct}%`;
      bar.appendChild(fill);

      const scanline = document.createElement("div");
      scanline.className = "gc-card-queue-scanline";
      if (domain === "research") scanline.classList.add("gc-card-queue-scanline--research");
      else if (domain === "shipyard") scanline.classList.add("gc-card-queue-scanline--shipyard");
      else if (domain === "planet_research") scanline.classList.add("gc-card-queue-scanline--planet-research");
      else if (domain === "ascension") scanline.classList.add("gc-card-queue-scanline--ascension");
      else if (domain === "defense") scanline.classList.add("gc-card-queue-scanline--defense");
      scanline.setAttribute("aria-hidden", "true");
      bar.appendChild(scanline);

      block.appendChild(bar);
    }

    if (jobId > 0 && domain !== "planet_research" && domain !== "ascension") {
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "gc-btn gc-btn-ghost gc-btn-xs gc-card-queue-cancel";
      if (domain === "research") cancelBtn.dataset.researchCancelId = String(jobId);
      else if (domain === "shipyard") cancelBtn.dataset.shipyardQueueCancel = String(jobId);
      else if (domain === "defense") cancelBtn.dataset.defenseQueueCancel = String(jobId);
      else cancelBtn.dataset.buildCancelId = String(jobId);
      cancelBtn.textContent =
        domain === "shipyard" || domain === "defense"
          ? t("shipyard_queue_cancel_btn", "Abbrechen")
          : t("action_cancel", "Abbrechen");
      block.appendChild(cancelBtn);
    }

    const slot = cardEl.querySelector(".gc-bld-card-queue-slot");
    if (slot) {
      slot.appendChild(block);
    } else {
      const anchor = cardEl.querySelector(".gc-bld-card-meta, .gc-prog-main");
      if (anchor) cardEl.insertBefore(block, anchor);
      else cardEl.appendChild(block);
    }

    syncCardQueueOwnerClassesFromBlocks(cardEl, domain);
    return block;
  };

  function _syncBuildQueueLiveState(queueList) {
    const first = queueList && queueList.length ? queueList[0] : null;
    if (first) {
      const finishTime = resolveQueueJobFinishTime(first);
      if (finishTime) {
        const now = getTimerServerNow();
        const remaining = queueJobRemainingSeconds(finishTime, now, resolveQueueJobRemaining(first));
        const totalRaw = Number(first.total || first.total_seconds || 0);
        const total = totalRaw > 0 ? Math.floor(totalRaw) : Math.max(1, remaining + 1);
        BUILDQ.active.finishTime = finishTime;
        BUILDQ.active.totalSeconds = total;
      } else {
        BUILDQ.active.finishTime = 0;
        BUILDQ.active.totalSeconds = 0;
      }
    } else {
      BUILDQ.active.finishTime = 0;
      BUILDQ.active.totalSeconds = 0;
    }
  }

  function renderBuildQueue(buildQueueRaw) {
    const compact = document.getElementById("build-queue-compact");
    if (!compact) return;

    let queueList = [];
    let summary = null;
    let queuePlanetId = Number(buildQueueRaw?.planet_id || compact.dataset.planetId || 0);

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
      compact.dataset.planetId = String(queuePlanetId);
    }

    _syncBuildQueueLiveState(queueList);

    const sig = _queueSignature(queueList, summary, queuePlanetId);
    const count = summary?.count ?? queueList.length;

    if (sig === _lastQueueSignature) {
      const first = queueList[0];
      const overdue =
        first &&
        resolveQueueJobFinishTime(first) &&
        resolveQueueJobFinishTime(first) <= getTimerServerNow();
      if (!overdue) {
        _updateBuildQueueCompact(count);
        GC.startProgressTicker();
        return;
      }
    }
    _lastQueueSignature = sig;
    _buildZeroHandled = "";

    _updateBuildQueueCompact(count);
    if (!queueList.length) _finishRefreshArmed.buildings = false;
    else clearFinishRefreshArmed("buildings", queueList);

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

  function _updateResearchQueueCompact(count) {
    const labelEl = document.getElementById("research-queue-compact-label");
    if (!labelEl) return;

    const n = Math.max(0, Math.floor(Number(count || 0)));
    if (!n) {
      _setIfChanged(labelEl, t("research_queue_compact_idle", "Keine Forschungen aktiv"));
      return;
    }
    _setIfChanged(
      labelEl,
      tf("research_queue_compact_active", { count: n }, `${n} Forschungen aktiv`)
    );
  }

  function _syncResearchQueueLiveState(queueList) {
    const first = queueList && queueList.length ? queueList[0] : null;
    if (first) {
      const finishTime = resolveQueueJobFinishTime(first);
      if (finishTime) {
        const now = getTimerServerNow();
        const remaining = queueJobRemainingSeconds(finishTime, now, resolveQueueJobRemaining(first));
        const totalRaw = Number(first.total || first.total_seconds || 0);
        const total = totalRaw > 0 ? Math.floor(totalRaw) : Math.max(1, remaining + 1);
        RESEARCHQ.active.finishTime = finishTime;
        RESEARCHQ.active.totalSeconds = total;
      } else {
        RESEARCHQ.active.finishTime = 0;
        RESEARCHQ.active.totalSeconds = 0;
      }
    } else {
      RESEARCHQ.active.finishTime = 0;
      RESEARCHQ.active.totalSeconds = 0;
    }
  }

  function renderResearchQueue(researchRaw) {
    const compact = document.getElementById("research-queue-compact");
    if (!compact) return;

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

    _syncResearchQueueLiveState(queueList);

    const sig = _researchQueueSignature(queueList, summary);
    const count = summary?.count ?? queueList.length;

    if (sig === _lastResearchQueueSignature) {
      const first = queueList[0];
      const finishTime = first ? resolveQueueJobFinishTime(first) : 0;
      const overdue = finishTime > 0 && finishTime <= getTimerServerNow();
      if (!overdue) {
        _updateResearchQueueCompact(count);
        GC.startProgressTicker();
        return;
      }
    }
    _lastResearchQueueSignature = sig;

    _updateResearchQueueCompact(count);
    if (!queueList.length) _finishRefreshArmed.research = false;
    else clearFinishRefreshArmed("research", queueList);

    GC.startProgressTicker();
  }

  function _applyProgressFill(fillEl, pct) {
    if (!fillEl) return;
    const clamped = Math.max(0, Math.min(100, pct));
    fillEl.style.width = `${clamped}%`;
    fillEl.setAttribute("aria-valuenow", String(Math.round(clamped)));
  }

  let _lastPePlanetTechQueueSignature = "";
  let _lastPeAscensionQueueSignature = "";

  function _pePlanetTechQueueSignature(rdx) {
    try {
      const count = rdx?.queue_count ?? 0;
      const byOwner = rdx?.card_jobs_by_owner || {};
      const items = Object.entries(byOwner)
        .map(([k, jobs]) => `${k}:${(jobs[0] || {}).job_id}:${(jobs[0] || {}).finish_at || 0}`)
        .join("|");
      return `${count}|${items}`;
    } catch (_) {
      return "";
    }
  }

  function _peAscensionQueueSignature(asc) {
    try {
      const count = asc?.summary?.count ?? asc?.queue?.length ?? 0;
      const byOwner = asc?.card_jobs_by_owner || {};
      const items = Object.entries(byOwner)
        .map(([k, jobs]) => `${k}:${(jobs[0] || {}).job_id}:${(jobs[0] || {}).finish_at || 0}`)
        .join("|");
      return `${count}|${items}`;
    } catch (_) {
      return "";
    }
  }

  function _updatePePlanetTechQueueCompact(count, limit) {
    const labelEl = document.getElementById("pe-planet-tech-queue-compact-label");
    const countEl = document.getElementById("pe-planet-tech-queue-compact-count");
    const n = Math.max(0, Math.floor(Number(count || 0)));
    const lim = Math.max(1, Math.floor(Number(limit || 2)));
    if (countEl) {
      _setIfChanged(
        countEl,
        `${n}/${lim} ${t("research_queue_jobs", "Aufträge")}`
      );
    }
    if (!labelEl) return;
    if (!n) {
      _setIfChanged(labelEl, t("pe_planet_tech_queue_compact_idle", "Keine Planet-Tech-Aufträge"));
      return;
    }
    _setIfChanged(
      labelEl,
      tf("pe_planet_tech_queue_compact_active", { count: n }, `${n} Planet-Tech-Aufträge`)
    );
  }

  function _updatePeAscensionQueueCompact(count) {
    const labelEl = document.getElementById("pe-ascension-queue-compact-label");
    if (!labelEl) return;
    const n = Math.max(0, Math.floor(Number(count || 0)));
    if (!n) {
      _setIfChanged(labelEl, t("pe_ascension_queue_compact_idle", "Keine Ascension-Aufträge"));
      return;
    }
    _setIfChanged(
      labelEl,
      tf("pe_ascension_queue_compact_active", { count: n }, `${n} Ascension-Aufträge`)
    );
  }

  function patchPePlanetTechCardQueues(rdx) {
    const page = document.querySelector(".planet-evolution-page");
    if (!page) return;
    const byOwner = rdx?.card_jobs_by_owner;
    if (!byOwner || typeof byOwner !== "object") return;
    patchCardQueuesFromOwnerMap(
      page,
      byOwner,
      (root) => root.querySelectorAll("[data-planet-tech-card]"),
      (card) => card.getAttribute("data-tech-key") || "",
      (root, techKey) => root.querySelector(`[data-tech-key="${techKey}"][data-planet-tech-card]`)
    );
  }

  function patchPeAscensionCardQueues(asc) {
    const page = document.querySelector(".planet-evolution-page");
    if (!page) return;
    const byOwner = asc?.card_jobs_by_owner;
    if (!byOwner || typeof byOwner !== "object") return;
    patchCardQueuesFromOwnerMap(
      page,
      byOwner,
      (root) => root.querySelectorAll("[data-ascension-card]"),
      (card) => card.getAttribute("data-ascension-key") || "",
      (root, ascKey) => root.querySelector(`[data-ascension-key="${ascKey}"][data-ascension-card]`)
    );
  }

  function applyPeResearchCardQueueJobs(cards) {
    if (!Array.isArray(cards)) return;
    const page = document.querySelector(".planet-evolution-page");
    if (!page) return;
    cards.forEach((tech) => {
      const card = page.querySelector(`[data-tech-key="${tech.tech_key}"][data-planet-tech-card]`);
      if (!card) return;
      if (tech.queue_job) GC.renderCardQueueBlock(card, tech.queue_job);
      else GC.clearCardQueueBlock(card);
    });
  }

  function applyPeAscensionCardQueueJobs(cards) {
    if (!Array.isArray(cards)) return;
    const page = document.querySelector(".planet-evolution-page");
    if (!page) return;
    cards.forEach((row) => {
      const card = page.querySelector(`[data-ascension-key="${row.ascension_key}"][data-ascension-card]`);
      if (!card) return;
      if (row.queue_job) GC.renderCardQueueBlock(card, row.queue_job);
      else GC.clearCardQueueBlock(card);
    });
  }

  function renderPePlanetTechQueue(rdx) {
    if (!document.getElementById("pe-planet-tech-queue-compact")) return;
    const data = rdx || { queue_count: 0, card_jobs_by_owner: {}, queue_limit: 2 };
    const count = data.queue_count ?? 0;
    const limit = data.queue_limit ?? 2;
    const sig = _pePlanetTechQueueSignature(data);
    if (sig === _lastPePlanetTechQueueSignature) {
      _updatePePlanetTechQueueCompact(count, limit);
      patchPePlanetTechCardQueues(data);
      return;
    }
    _lastPePlanetTechQueueSignature = sig;
    _updatePePlanetTechQueueCompact(count, limit);
    patchPePlanetTechCardQueues(data);
    applyPeResearchCardQueueJobs([...(data.queue_cards || []), ...(data.recommended || [])]);
  }

  function renderPeAscensionQueue(asc) {
    if (!document.getElementById("pe-ascension-queue-compact")) return;
    const data = asc || { summary: { count: 0 }, card_jobs_by_owner: {}, ascensions: [] };
    const count = data.summary?.count ?? data.queue?.length ?? 0;
    const sig = _peAscensionQueueSignature(data);
    if (sig === _lastPeAscensionQueueSignature) {
      _updatePeAscensionQueueCompact(count);
      patchPeAscensionCardQueues(data);
      return;
    }
    _lastPeAscensionQueueSignature = sig;
    _updatePeAscensionQueueCompact(count);
    patchPeAscensionCardQueues(data);
    applyPeAscensionCardQueueJobs(data.ascensions || []);
  }

  function applyPlanetEvolutionState(res) {
    const payload = res?.planet || res;
    if (!payload || payload.ok === false) return;
    const dash = payload.dashboard || {};
    if (dash.research_ux) renderPePlanetTechQueue(dash.research_ux);
    if (dash.ascension_ux) renderPeAscensionQueue(dash.ascension_ux);
    GC.startProgressTicker();
  }

  async function refreshPlanetEvolutionState(planetId) {
    const pid = Math.floor(Number(planetId || 0));
    if (!pid) return null;
    const res = await GC.fetchGameAction(`/api/planets/${pid}/state`);
    if (res?.ok && res.planet) {
      applyPlanetEvolutionState(res);
      return res.planet;
    }
    return null;
  }

  // =========================
  // GC-540 — unified page timers (single tick via startProgressTicker)
  // =========================
  let _pageTimerLoopRunning = false;

  function getTimerServerNow() {
    const st = Number(GC.lastState?.server_time || GC.lastState?.server_now || 0);
    if (st) {
      const approx = getApproxServerNow();
      if (!TIME.serverNow || st > approx - 0.5) setServerTime(st);
    }
    return getApproxServerNow();
  }

  function queryTimerElements(root) {
    const base = root || document;
    const seen = new Set();
    const out = [];
    const add = (el) => {
      if (el && el.nodeType === 1 && !seen.has(el)) {
        seen.add(el);
        out.push(el);
      }
    };
    base.querySelectorAll("[data-timer-target], [data-countdown-at]").forEach(add);
    [
      "#build-eta-live",
      "#research-eta-live",
      "#shipyard-eta-live",
      "#build-queue-subtitle-eta",
      "#research-queue-subtitle-eta",
      "#shipyard-queue-subtitle-eta",
    ].forEach((sel) => {
      const el = base.querySelector(sel);
      if (el) add(el);
    });
    base.querySelectorAll(
      ".build-job-active[data-finish-time], .research-job-active[data-finish-time], .shipyard-job-active[data-finish-time]"
    ).forEach((job) => {
      const eta = job.querySelector("[data-timer-target], [data-countdown-at], .job-time, [data-activity-eta]");
      add(eta || job);
    });
    return out;
  }

  function inferTimerKind(el) {
    if (el.dataset.timerKind) return el.dataset.timerKind;
    if (el.dataset.countdownFormat === "fleet" || el.classList.contains("fleet-active-countdown")) return "fleet";
    if (el.dataset.activityEta) {
      return el.dataset.countdownFormat === "fleet" ? "fleet" : "queue";
    }
    if (el.closest(".shipyard-job-active")) return "shipyard";
    if (el.closest(".build-job-active")) return "build";
    if (el.closest(".research-job-active")) return "research";
    return el.dataset.countdownFormat || "eta";
  }

  function inferRefreshOnZero(el, kind) {
    if (el.dataset.refreshOnZero) return el.dataset.refreshOnZero;
    const scope = el.dataset.countdownScope || "";
    if (scope === "fleet" || kind === "fleet") return "fleet";
    if (kind === "shipyard") return "shipyard";
    if (kind === "defense") return "defense";
    if (scope === "overview" || kind === "build" || kind === "research" || kind === "queue") return "game-state";
    return "";
  }

  function syncTimerElement(el) {
    if (!el) return;
    let target = parseTimerTarget(el.dataset.timerTarget);
    if (!target) target = parseTimerTarget(el.dataset.countdownAt);
    if (!target) {
      const parent = el.closest("[data-finish-time], [data-finish-at]");
      if (parent) {
        target = parseTimerTarget(parent.dataset.finishTime || parent.dataset.finishAt || parent.getAttribute("data-finish-time"));
      }
    }
    if (!target) target = parseTimerTarget(el.getAttribute("data-finish-time"));
    if (target > 0) {
      if (!el.dataset.timerTarget) el.dataset.timerTarget = String(target);
      if (!el.dataset.countdownAt) el.dataset.countdownAt = String(target);
      if (el.dataset.refreshFiredAt && el.dataset.refreshFiredAt !== String(target)) {
        delete el.dataset.refreshFiredAt;
      }
    }
    const kind = inferTimerKind(el);
    if (!el.dataset.timerKind) el.dataset.timerKind = kind;
    const refresh = inferRefreshOnZero(el, kind);
    if (refresh && !el.dataset.refreshOnZero) el.dataset.refreshOnZero = refresh;
  }

  function timerRemainingSeconds(el, serverNow) {
    syncTimerElement(el);
    const target = parseTimerTarget(el.dataset.timerTarget || el.dataset.countdownAt || 0);
    if (!target) return 0;
    const srvRem = el.dataset.serverRemaining;
    const kind = el.dataset.timerKind || inferTimerKind(el);
    const scope = el.dataset.countdownScope || "";
    const useMovement =
      kind === "fleet"
      || scope === "fleet"
      || (scope === "overview" && kind === "fleet");
    if (useMovement) {
      return movementRemainingSeconds(
        target,
        serverNow,
        srvRem === undefined || srvRem === "" ? NaN : Number(srvRem)
      );
    }
    return queueJobRemainingSeconds(
      target,
      serverNow,
      srvRem === undefined || srvRem === "" ? NaN : Number(srvRem)
    );
  }

  function formatTimerDisplay(remaining, kind) {
    if (kind === "fleet") return formatCountdownRemain(remaining);
    return formatEta(Math.max(0, Math.ceil(remaining)));
  }

  // GC-546D — production completion refresh (shipyard/defense): one debounced sync per timer zero.
  const PRODUCTION_COMPLETION_DEBOUNCE_MS = 1100;
  let _productionCompletionTimer = null;
  let _productionCompletionPending = { gameState: false, shipyard: false, defense: false };
  let _shipyardApiInFlight = null;
  let _defenseApiInFlight = null;
  const _productionZeroHandled = { shipyard: "", defense: "" };

  function _timerZeroAlreadyFired(el, target) {
    return !!(el && target > 0 && el.dataset.refreshFiredAt === String(target));
  }

  function _markTimerZeroFired(el, target) {
    if (el && target > 0) el.dataset.refreshFiredAt = String(target);
  }

  function requestProductionCompletionSync(opts) {
    if (!shouldRunGameLoop() || _authLoopAborted) return;
    const o = opts && typeof opts === "object" ? opts : {};
    if (o.gameState !== false) _productionCompletionPending.gameState = true;
    if (o.shipyard) _productionCompletionPending.shipyard = true;
    if (o.defense) _productionCompletionPending.defense = true;
    if (_productionCompletionTimer != null) return;
    _productionCompletionTimer = GC.setSafeTimeout(() => {
      _productionCompletionTimer = null;
      const pending = { ..._productionCompletionPending };
      _productionCompletionPending = { gameState: false, shipyard: false, defense: false };
      if (pending.gameState && typeof GC.refreshGameState === "function") {
        GC.refreshGameState("timer_done");
      }
      if (pending.shipyard) {
        const syPage = document.getElementById("shipyard-page");
        if (syPage?.dataset.ready === "1") refreshShipyardStateCoalesced(syPage);
      }
      if (pending.defense && !pending.gameState) {
        const defPage = document.getElementById("defense-page");
        if (defPage?.dataset.ready === "1") refreshDefenseStateCoalesced(defPage);
      }
    }, PRODUCTION_COMPLETION_DEBOUNCE_MS);
  }

  function requestQueueTimerZeroRefresh(meta) {
    if (!shouldRunGameLoop() || _authLoopAborted) return;
    const o = meta && typeof meta === "object" ? meta : {};
    const domain = String(o.domain || "");
    const jobId = Math.floor(Number(o.jobId || 0));
    const finishAt = Math.floor(Number(o.finishAt || 0));
    const key = jobId > 0 ? `${domain}:${jobId}:${finishAt}` : `${domain}:panel:${finishAt || 0}`;
    if (_queueTimerZeroRefreshKeys.has(key)) return;
    _queueTimerZeroRefreshKeys.add(key);
    if (_queueTimerZeroPendingDomains && domain) _queueTimerZeroPendingDomains.add(domain);
    if (_queueTimerZeroRefreshTimer != null) return;
    _queueTimerZeroRefreshTimer = GC.setSafeTimeout(() => {
      _queueTimerZeroRefreshTimer = null;
      const domains = _queueTimerZeroPendingDomains
        ? new Set(_queueTimerZeroPendingDomains)
        : new Set();
      _queueTimerZeroPendingDomains = new Set();
      const keysSnapshot = Array.from(_queueTimerZeroRefreshKeys);
      if (typeof GC.refreshGameState !== "function") {
        keysSnapshot.forEach((k) => _queueTimerZeroRefreshKeys.delete(k));
        return;
      }
      Promise.resolve(GC.refreshGameState("queue_timer_zero")).finally(() => {
        if (domains.has("shipyard")) {
          const syPage = document.getElementById("shipyard-page");
          if (syPage?.dataset.ready === "1") refreshShipyardStateCoalesced(syPage);
        }
        if (domains.has("defense")) {
          const defPage = document.getElementById("defense-page");
          if (defPage?.dataset.ready === "1") refreshDefenseStateCoalesced(defPage);
        }
        GC.setSafeTimeout(() => {
          keysSnapshot.forEach((k) => _queueTimerZeroRefreshKeys.delete(k));
        }, 1500);
      });
    }, QUEUE_TIMER_ZERO_DEBOUNCE_MS);
  }

  function markCardQueueZeroRefresh(block, jobId, finishAt) {
    if (!block) return false;
    const fireKey = `${Math.floor(Number(jobId || 0))}:${Math.floor(Number(finishAt || 0))}`;
    const prev = block.dataset.queueZeroFiredFor || "";
    const prevAt = Number(block.dataset.queueZeroFiredAt || 0);
    if (prev === fireKey && Date.now() - prevAt < 2500) return false;
    block.dataset.queueZeroFiredFor = fireKey;
    block.dataset.queueZeroFiredAt = String(Date.now());
    return true;
  }

  function requestTimerZeroRefresh(refreshKind, timerKind, opts) {
    const kind = String(refreshKind || "game-state");
    const o = opts && typeof opts === "object" ? opts : {};
    if (kind === "fleet") {
      requestMovementCountdownRefresh("fleet");
      return;
    }
    if (kind === "shipyard" || kind === "defense") {
      if (o.jobId != null || o.finishAt != null || o.domain) {
        requestQueueTimerZeroRefresh({
          domain: o.domain || kind,
          jobId: o.jobId,
          finishAt: o.finishAt,
        });
        return;
      }
      requestQueueTimerZeroRefresh({ domain: kind, jobId: 0, finishAt: 0 });
      return;
    }
    const actKey = timerKind === "research" ? "research" : "buildings";
    requestFinishRefresh(actKey);
  }

  const _movementCountdownRefreshPending = { fleet: false, overview: false };
  const _movementCountdownExpiryState = new Map();
  let _movementCountdownRefreshTimer = null;
  let _lastGlobalMovementExpiryRefreshMs = 0;
  let _queuedChainRefreshReason = null;
  const _timerZeroRefreshLastAt = new Map();
  const TIMER_ZERO_REFRESH_MIN_MS = 900;
  const _queueTimerZeroRefreshKeys = new Set();
  let _queueTimerZeroRefreshTimer = null;
  let _queueTimerZeroPendingDomains = new Set();
  const QUEUE_TIMER_ZERO_DEBOUNCE_MS = 80;

  const MOVEMENT_EXPIRY_REFRESH_MS = 900;
  const MOVEMENT_EXPIRY_REFRESH_MS_SHORT = 200;

  function _movementCountdownKey(el) {
    return String(el.dataset.countdownKey || `${el.dataset.countdownScope || ""}:${el.dataset.countdownAt || ""}`);
  }

  function _clearMovementCountdownExpiryState() {
    _movementCountdownExpiryState.clear();
    _lastGlobalMovementExpiryRefreshMs = 0;
  }

  function _movementExpiryCooldownMs(key, urgent) {
    if (urgent) return MOVEMENT_EXPIRY_REFRESH_MS_SHORT;
    const staleHits = _movementCountdownExpiryState.get(`${key}:stale`) || 0;
    if (staleHits >= 3) return MOVEMENT_EXPIRY_REFRESH_MS * 4;
    if (staleHits >= 1) return MOVEMENT_EXPIRY_REFRESH_MS * 2;
    return MOVEMENT_EXPIRY_REFRESH_MS;
  }

  function _shouldRefreshExpiredCountdown(key, urgent) {
    const nowMs = Date.now();
    const globalCooldown = urgent ? MOVEMENT_EXPIRY_REFRESH_MS_SHORT : MOVEMENT_EXPIRY_REFRESH_MS;
    if (nowMs - _lastGlobalMovementExpiryRefreshMs < globalCooldown) return false;
    if (urgent) {
      _movementCountdownExpiryState.set(key, nowMs);
      return true;
    }
    const last = _movementCountdownExpiryState.get(key) || 0;
    const cooldown = _movementExpiryCooldownMs(key, false);
    if (nowMs - last < cooldown) return false;
    _movementCountdownExpiryState.set(key, nowMs);
    return true;
  }

  function _movementExpiryRefreshDebounceMs() {
    let maxStale = 0;
    _movementCountdownExpiryState.forEach((val, k) => {
      if (!String(k).endsWith(":stale")) return;
      maxStale = Math.max(maxStale, Number(val) || 0);
    });
    if (maxStale >= 8) return 400;
    if (maxStale >= 4) return 200;
    return 60;
  }

  function _anyStaleMovementCountdownDom() {
    const now = getApproxServerNow();
    for (const el of document.querySelectorAll("[data-countdown-at]")) {
      const scope = el.dataset.countdownScope || "";
      if (scope !== "fleet" && scope !== "overview") continue;
      const at = Number(el.dataset.countdownAt || 0);
      if (at && Math.ceil(at - now) <= 0) return true;
    }
    return false;
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

    const debounceMs = _movementExpiryRefreshDebounceMs();
    _movementCountdownRefreshTimer = GC.setSafeTimeout(() => {
      _movementCountdownRefreshTimer = null;
      if (_movementCountdownRefreshPending[pendingKey]) return;
      _movementCountdownRefreshPending[pendingKey] = true;
      _lastGlobalMovementExpiryRefreshMs = Date.now();

      const staleKeys = [];
      document.querySelectorAll("[data-countdown-at]").forEach((el) => {
        const countdownAt = Number(el.dataset.countdownAt || 0);
        if (!countdownAt) return;
        const srvRem = el.dataset.serverRemaining;
        const remaining = movementRemainingSeconds(
          countdownAt,
          getApproxServerNow(),
          srvRem === undefined || srvRem === "" ? NaN : Number(srvRem)
        );
        if (remaining <= 0) staleKeys.push(_movementCountdownKey(el));
      });

      const fleetPage = document.getElementById("fleet-page");
      const fleetReady = fleetPage && fleetPage.dataset.ready === "1";
      let refreshPromise = Promise.resolve();
      if (pendingKey === "fleet" && fleetReady && typeof GC.refreshFleetState === "function") {
        fleetPage.dataset.fleetRefreshBusy = "1";
        refreshPromise = GC.refreshFleetState(fleetPage).finally(() => {
          delete fleetPage.dataset.fleetRefreshBusy;
        });
      }
      if (typeof GC.refreshGameState === "function") {
        refreshPromise = refreshPromise.then(() =>
          GC.refreshGameState("fleet_countdown_expired")
        );
      } else if (pendingKey !== "fleet" || !fleetReady) {
        refreshPromise = Promise.resolve();
      }

      Promise.resolve(refreshPromise).finally(() => {
        _movementCountdownRefreshPending[pendingKey] = false;
        const fleetPageLater = document.getElementById("fleet-page");
        if (
          fleetPageLater &&
          fleetPageLater.dataset.ready === "1" &&
          typeof GC.refreshFleetState === "function" &&
          pendingKey === "overview"
        ) {
          GC.refreshFleetState(fleetPageLater);
        }
        staleKeys.forEach((key) => {
          let stillStale = false;
          document.querySelectorAll("[data-countdown-at]").forEach((el) => {
            if (_movementCountdownKey(el) !== key) return;
            const countdownAt = Number(el.dataset.countdownAt || 0);
            if (!countdownAt) return;
            const srvRem = el.dataset.serverRemaining;
            if (movementRemainingSeconds(
              countdownAt,
              getApproxServerNow(),
              srvRem === undefined || srvRem === "" ? NaN : Number(srvRem)
            ) <= 0) stillStale = true;
          });
          if (stillStale) _noteMovementCountdownStillStale(key);
          else _clearMovementCountdownStale(key);
        });
        if (_anyStaleMovementCountdownDom()) {
          requestMovementCountdownRefresh(pendingKey);
        } else {
          GC.startProgressTicker();
        }
      });
    }, debounceMs);
  }

  function updatePageTimers(serverNow) {
    const now = Number.isFinite(serverNow) ? serverNow : getTimerServerNow();
    let fleetExpired = false;
    let overviewExpired = false;

    queryTimerElements().forEach((el) => {
      syncTimerElement(el);
      const target = parseTimerTarget(el.dataset.timerTarget || el.dataset.countdownAt || 0);
      if (!target) return;
      const kind = el.dataset.timerKind || inferTimerKind(el);
      const remaining = timerRemainingSeconds(el, now);
      const cardBlock = el.closest("[data-gc-card-queue]");
      const cardDomain = cardBlock ? String(cardBlock.dataset.timerDomain || "") : "";
      const isProductionCardTimer =
        cardBlock && (kind === "shipyard" || kind === "defense" || cardDomain === "shipyard" || cardDomain === "defense");
      if (isProductionCardTimer) {
        _setIfChanged(el, formatEta(queueTimerDisplaySeconds(remaining)));
      } else {
        _setIfChanged(el, formatTimerDisplay(remaining, kind));
      }
      const scope = el.dataset.countdownScope || "";
      const key = _movementCountdownKey(el);
      const isFleetTimer = scope === "fleet" || kind === "fleet";
      const isOverviewFleet = scope === "overview" && kind === "fleet";
      const cardFinish = cardBlock ? parseTimerTarget(cardBlock.dataset.finishAt || target) : 0;
      const refreshKind = el.dataset.refreshOnZero || inferRefreshOnZero(el, kind);
      const queueTimerDone =
        isProductionCardTimer && isQueueTimerComplete(remaining, cardFinish, now);
      if (remaining <= 0 || queueTimerDone) {
        if (isFleetTimer) {
          fleetExpired = true;
        } else if (isOverviewFleet) {
          overviewExpired = true;
        } else if (scope === "overview" && kind === "queue") {
          const actRow = el.closest("[data-activity-key]");
          const actKey = actRow?.dataset?.activityKey || "";
          const zeroKey = `${refreshKind}:${actKey}:${key}`;
          const lastAt = _timerZeroRefreshLastAt.get(zeroKey) || 0;
          if (Date.now() - lastAt >= TIMER_ZERO_REFRESH_MIN_MS) {
            _timerZeroRefreshLastAt.set(zeroKey, Date.now());
            if (actKey === "shipyard") requestFinishRefresh("shipyard");
            else if (actKey === "research") requestFinishRefresh("research");
            else if (actKey === "build") requestFinishRefresh("buildings");
            else if (typeof GC.refreshGameState === "function") GC.refreshGameState("timer_done");
          }
        } else if (queueTimerDone && cardBlock) {
          const jobId = Math.floor(Number(cardBlock.dataset.jobId || 0));
          const finishAt = cardFinish || target;
          if (markCardQueueZeroRefresh(cardBlock, jobId, finishAt)) {
            requestQueueTimerZeroRefresh({
              domain: cardDomain || refreshKind || kind,
              jobId,
              finishAt,
            });
          }
        } else if (remaining <= 0 && refreshKind && !_timerZeroAlreadyFired(el, target)) {
          const zeroKey = `${refreshKind}:${key}`;
          const lastAt = _timerZeroRefreshLastAt.get(zeroKey) || 0;
          if (Date.now() - lastAt >= TIMER_ZERO_REFRESH_MIN_MS) {
            _timerZeroRefreshLastAt.set(zeroKey, Date.now());
            _markTimerZeroFired(el, target);
            requestTimerZeroRefresh(refreshKind, kind);
          }
        }
      } else {
        _movementCountdownExpiryState.delete(key);
        _clearMovementCountdownStale(key);
      }
    });

    document.querySelectorAll("[data-preview-arrival][data-countdown-at]").forEach((el) => {
      syncTimerElement(el);
      const remaining = timerRemainingSeconds(el, now);
      _setIfChanged(el, formatCountdownRemain(remaining));
    });

    if (fleetExpired) requestMovementCountdownRefresh("fleet");
    if (overviewExpired) requestMovementCountdownRefresh("overview");
  }

  function updateMovementCountdowns(serverNow) {
    updatePageTimers(serverNow);
  }

  let _buildZeroHandled = "";

  function updateAllProgressBars(serverNow) {
    const serverNowTs = Number.isFinite(serverNow) ? serverNow : getApproxServerNow();

    const path = window.location.pathname || "";
    const isResearchPage = path.endsWith("/research");
    const isOverviewPage = path.endsWith("/overview") || path === "/" || path === "";

    const buildActive = document.querySelector(".build-job.build-job-active");
    const buildFinishFromDom = buildActive ? parseTimerTarget(buildActive.getAttribute("data-finish-time")) : 0;
    const buildTotalFromDom = buildActive ? Math.max(1, Number(buildActive.getAttribute("data-total") || 1)) : 1;
    const buildFinishFromState = parseTimerTarget(BUILDQ.active.finishTime || 0);
    const buildTotalFromState = Math.max(1, Number(BUILDQ.active.totalSeconds || 1));
    const buildFinish = buildFinishFromDom || buildFinishFromState;
    const buildTotal = buildFinishFromDom ? buildTotalFromDom : buildTotalFromState;
    if (buildFinish) {
      const srvRemRaw = buildActive?.dataset?.serverRemaining;
      const remaining = queueJobRemainingSeconds(
        buildFinish,
        serverNowTs,
        srvRemRaw === undefined || srvRemRaw === "" ? NaN : Number(srvRemRaw)
      );
      if (buildActive) assignMonotonicServerRemaining(buildActive, remaining, buildFinish);
      const pct = 100 * (1 - remaining / buildTotal);
      const etaEl = document.getElementById("build-eta-live");
      const fillEl = document.getElementById("build-bar-fill-live");
      if (etaEl) {
        applyQueueJobTimerAttrs(etaEl, buildFinish, "build", "game-state", remaining);
        _setIfChanged(etaEl, formatEta(Math.ceil(remaining)));
      }
      _applyProgressFill(fillEl, pct);
      if (remaining <= 0) {
        _applyProgressFill(fillEl, 100);
        const zeroKey = `build:${buildFinish}`;
        if (_buildZeroHandled !== zeroKey) {
          _buildZeroHandled = zeroKey;
          requestFinishRefresh("buildings");
        }
      }
    }

    document.querySelectorAll("[data-gc-card-queue][data-queue-active='1']").forEach((block) => {
      const finish = parseTimerTarget(block.dataset.finishAt || 0);
      if (!finish) return;
      const total = Math.max(1, Number(block.dataset.totalSeconds || 1));
      const domain = String(block.dataset.timerDomain || "building");
      const timerKind =
        domain === "research"
          ? "research"
          : domain === "shipyard"
            ? "shipyard"
            : domain === "defense"
              ? "defense"
            : domain === "planet_research"
              ? "planet_research"
              : domain === "ascension"
                ? "ascension"
                : "build";
      const refreshOnZero =
        domain === "shipyard"
          ? "shipyard"
          : domain === "defense"
            ? "defense"
          : domain === "planet_research" || domain === "ascension"
            ? "planet_evolution"
            : "game-state";
      const srvRemRaw = block.dataset.serverRemaining;
      const remaining = queueJobRemainingSeconds(
        finish,
        serverNowTs,
        srvRemRaw === undefined || srvRemRaw === "" ? NaN : Number(srvRemRaw)
      );
      assignMonotonicServerRemaining(block, remaining, finish);
      const pct = 100 * (1 - remaining / total);
      const cardEl = block.closest("[data-building-row], [data-research-card], [data-building-card]");
      const timerEl = block.dataset.heroQueue === "1"
        ? cardEl?.querySelector("[data-hero-time-chip] .gc-card-queue-timer")
        : block.querySelector(".gc-card-queue-timer");
      const fillEl = block.querySelector(".gc-card-queue-bar-fill");
      const barEl = block.querySelector(".gc-card-queue-bar");
      if (block.dataset.heroQueue === "1" && cardEl) {
        const rounded = Math.max(0, Math.min(100, Math.round(pct)));
        applyHeroImageProgress(cardEl, rounded);
        const heroPctEl = block.querySelector(".gc-bld-hero-queue-pct");
        const centerEl = block.querySelector(".gc-bld-hero-queue-center");
        if (heroPctEl) _setIfChanged(heroPctEl, `${rounded}%`);
        if (centerEl) centerEl.setAttribute("aria-valuenow", String(rounded));
        if (timerEl) {
          applyQueueJobTimerAttrs(timerEl, finish, timerKind, refreshOnZero, remaining);
          const eta = formatEta(queueTimerDisplaySeconds(remaining));
          _setIfChanged(timerEl, eta);
          block.title = eta;
        }
      } else {
        if (timerEl) {
          applyQueueJobTimerAttrs(timerEl, finish, timerKind, refreshOnZero, remaining);
          _setIfChanged(timerEl, formatEta(queueTimerDisplaySeconds(remaining)));
        }
        _applyProgressFill(fillEl, pct);
        if (barEl) barEl.setAttribute("aria-valuenow", String(Math.max(0, Math.min(100, Math.round(pct)))));
      }
      if (isQueueTimerComplete(remaining, finish, serverNowTs)) {
        const jobId = Math.floor(Number(block.dataset.jobId || 0));
        if (domain === "research") {
          const zeroKey = `research-card:${finish}:${jobId}`;
          if (_buildZeroHandled !== zeroKey) {
            _buildZeroHandled = zeroKey;
            requestFinishRefresh("research");
          }
        } else if (domain === "shipyard" || domain === "defense") {
          if (markCardQueueZeroRefresh(block, jobId, finish)) {
            requestQueueTimerZeroRefresh({ domain, jobId, finishAt: finish });
          }
        } else if (domain === "planet_research" || domain === "ascension") {
          const zeroKey = `${domain}-card:${finish}:${jobId}`;
          if (_buildZeroHandled !== zeroKey) {
            _buildZeroHandled = zeroKey;
            requestFinishRefresh("planet_evolution");
          }
        } else {
          const zeroKey = `build-card:${finish}:${jobId}`;
          if (_buildZeroHandled !== zeroKey) {
            _buildZeroHandled = zeroKey;
            requestFinishRefresh("buildings");
          }
        }
      }
    });

    document.querySelectorAll("[data-gc-card-queue][data-queue-active='0']").forEach((block) => {
      const finishAt = parseTimerTarget(block.dataset.finishAt || 0);
      const startAt = parseTimerTarget(block.dataset.startAt || 0);
      const target = finishAt > 0 ? finishAt : startAt;
      if (!target) return;
      const cardEl = block.closest("[data-building-row], [data-research-card], [data-building-card]");
      const timerEl = block.dataset.heroQueue === "1"
        ? block.querySelector(".gc-bld-hero-queue-badge .gc-card-queue-timer")
        : block.querySelector(".gc-card-queue-timer");
      if (!timerEl) return;
      const domain = String(block.dataset.timerDomain || "building");
      const timerKind =
        domain === "research"
          ? "research"
          : domain === "shipyard"
            ? "shipyard"
            : domain === "defense"
              ? "defense"
            : domain === "planet_research"
              ? "planet_research"
              : domain === "ascension"
                ? "ascension"
                : "build";
      const refreshOnZero =
        domain === "shipyard"
          ? "shipyard"
          : domain === "defense"
            ? "defense"
          : domain === "planet_research" || domain === "ascension"
            ? "planet_evolution"
            : "game-state";
      const srvRemRaw = block.dataset.serverRemaining;
      const remaining = queueJobRemainingSeconds(
        target,
        serverNowTs,
        srvRemRaw === undefined || srvRemRaw === "" ? NaN : Number(srvRemRaw)
      );
      assignMonotonicServerRemaining(block, remaining, target);
      applyQueueJobTimerAttrs(timerEl, target, timerKind, refreshOnZero, remaining);
      _setIfChanged(timerEl, formatEta(queueTimerDisplaySeconds(remaining)));
    });

    const researchActive = document.querySelector(".research-job.research-job-active");
    if (researchActive) {
      const finishTimeFromDom = parseTimerTarget(researchActive.getAttribute("data-finish-time"));
      const finishTimeFromState = parseTimerTarget(RESEARCHQ.active.finishTime || 0);
      const finishTime = finishTimeFromDom || finishTimeFromState;
      const totalFromDom = Math.max(1, Number(researchActive.getAttribute("data-total") || 1));
      const totalFromState = Math.max(1, Number(RESEARCHQ.active.totalSeconds || 1));
      const total = finishTimeFromDom ? totalFromDom : totalFromState;
      if (finishTime) {
        const srvRemRaw = researchActive.dataset.serverRemaining;
        const remaining = queueJobRemainingSeconds(
          finishTime,
          serverNowTs,
          srvRemRaw === undefined || srvRemRaw === "" ? NaN : Number(srvRemRaw)
        );
        const pct = 100 * (1 - remaining / total);
        const etaEl = document.getElementById("research-eta-live");
        const fillEl = document.getElementById("research-bar-fill-live");
        if (etaEl) {
          applyQueueJobTimerAttrs(etaEl, finishTime, "research", "game-state", remaining);
          _setIfChanged(etaEl, formatEta(remaining));
        }
        _applyProgressFill(fillEl, pct);
        const subEta = document.getElementById("research-queue-subtitle-eta");
        if (subEta) _setIfChanged(subEta, formatEta(remaining));
        if (remaining <= 0) {
          _applyProgressFill(fillEl, 100);
          requestFinishRefresh("research");
        }
      }
    }

    const shipyardActive = document.getElementById("shipyard-page")?.querySelector(".shipyard-job.shipyard-job-active");
    if (shipyardActive) {
      const orderFinishFromDom = parseTimerTarget(shipyardActive.getAttribute("data-finish-time"));
      const orderFinishFromState = parseTimerTarget(SHIPYARDQ.active.finishTime || 0);
      const orderFinish = orderFinishFromDom || orderFinishFromState;
      const nextUnitFinish = parseTimerTarget(shipyardActive.getAttribute("data-next-finish-time"));
      const totalFromDom = Math.max(1, Number(shipyardActive.getAttribute("data-total") || 1));
      const totalFromState = Math.max(1, Number(SHIPYARDQ.active.totalSeconds || 1));
      const total = orderFinishFromDom ? totalFromDom : totalFromState;
      if (orderFinish) {
        const srvRemRaw = shipyardActive.dataset.serverRemaining;
        const orderRemaining = queueJobRemainingSeconds(
          orderFinish,
          serverNowTs,
          srvRemRaw === undefined || srvRemRaw === "" ? NaN : Number(srvRemRaw)
        );
        assignMonotonicServerRemaining(shipyardActive, orderRemaining, orderFinish);
        const pct = 100 * (1 - orderRemaining / total);
        const etaEl = document.getElementById("shipyard-eta-live");
        const fillEl = document.getElementById("shipyard-bar-fill-live");
        if (etaEl) {
          applyQueueJobTimerAttrs(etaEl, orderFinish, "shipyard", "shipyard", orderRemaining);
          _setIfChanged(etaEl, formatEta(queueTimerDisplaySeconds(orderRemaining)));
        }
        _applyProgressFill(fillEl, pct);
        const subEta = document.getElementById("shipyard-queue-subtitle-eta");
        if (subEta) _setIfChanged(subEta, formatEta(queueTimerDisplaySeconds(orderRemaining)));
        if (nextUnitFinish > 0 && nextUnitFinish <= serverNowTs) {
          const unitKey = `${shipyardActive.dataset.queueJobId || ""}:${nextUnitFinish}`;
          if (_shipyardUnitFinishKey !== unitKey) {
            _shipyardUnitFinishKey = unitKey;
            requestProductionCompletionSync({ gameState: true, shipyard: true });
          }
        } else if (isQueueTimerComplete(orderRemaining, orderFinish, serverNowTs)) {
          const jobId = Math.floor(Number(shipyardActive.dataset.queueJobId || 0));
          if (markCardQueueZeroRefresh(shipyardActive, jobId, orderFinish)) {
            requestQueueTimerZeroRefresh({
              domain: "shipyard",
              jobId,
              finishAt: orderFinish,
            });
          }
        }
      }
    }

    const defenseActive = document.getElementById("defense-page")?.querySelector(".shipyard-job.shipyard-job-active");
    if (defenseActive) {
      const orderFinishFromDom = parseTimerTarget(defenseActive.getAttribute("data-finish-time"));
      const orderFinishFromState = parseTimerTarget(DEFENSEQ.active.finishTime || 0);
      const orderFinish = orderFinishFromDom || orderFinishFromState;
      const nextUnitFinish = parseTimerTarget(defenseActive.getAttribute("data-next-finish-time"));
      const totalFromDom = Math.max(1, Number(defenseActive.getAttribute("data-total") || 1));
      const totalFromState = Math.max(1, Number(DEFENSEQ.active.totalSeconds || 1));
      const total = orderFinishFromDom ? totalFromDom : totalFromState;
      if (orderFinish) {
        const srvRemRaw = defenseActive.dataset.serverRemaining;
        const orderRemaining = queueJobRemainingSeconds(
          orderFinish,
          serverNowTs,
          srvRemRaw === undefined || srvRemRaw === "" ? NaN : Number(srvRemRaw)
        );
        assignMonotonicServerRemaining(defenseActive, orderRemaining, orderFinish);
        const pct = 100 * (1 - orderRemaining / total);
        const etaEl = document.getElementById("defense-eta-live");
        const fillEl = document.getElementById("defense-bar-fill-live");
        if (etaEl) {
          applyQueueJobTimerAttrs(etaEl, orderFinish, "defense", "defense", orderRemaining);
          _setIfChanged(etaEl, formatEta(queueTimerDisplaySeconds(orderRemaining)));
        }
        _applyProgressFill(fillEl, pct);
        const subEta = document.getElementById("defense-queue-subtitle-eta");
        if (subEta) _setIfChanged(subEta, formatEta(queueTimerDisplaySeconds(orderRemaining)));
        if (nextUnitFinish > 0 && nextUnitFinish <= serverNowTs) {
          const unitKey = `${defenseActive.dataset.queueJobId || ""}:${nextUnitFinish}`;
          if (_defenseUnitFinishKey !== unitKey) {
            _defenseUnitFinishKey = unitKey;
            requestProductionCompletionSync({ gameState: true });
          }
        } else if (isQueueTimerComplete(orderRemaining, orderFinish, serverNowTs)) {
          const jobId = Math.floor(Number(defenseActive.dataset.queueJobId || 0));
          if (markCardQueueZeroRefresh(defenseActive, jobId, orderFinish)) {
            requestQueueTimerZeroRefresh({
              domain: "defense",
              jobId,
              finishAt: orderFinish,
            });
          }
        }
      }
    }

    const ovBox = document.getElementById("overview-research-active");
    if (ovBox) {
      const finishAt = Number(ovBox.dataset.finishAt || 0);
      const total = Math.max(1, Number(ovBox.dataset.total || 1));
      if (finishAt) {
        const srvRemRaw = ovBox.dataset.serverRemaining;
        const remaining = queueJobRemainingSeconds(
          finishAt,
          serverNowTs,
          srvRemRaw === undefined || srvRemRaw === "" ? NaN : Number(srvRemRaw)
        );
        const pct = 100 * (1 - remaining / total);
        const cdEl = document.getElementById("research-remaining");
        const barEl = document.getElementById("research-bar-fill");
        if (cdEl) _setIfChanged(cdEl, formatEta(remaining));
        _applyProgressFill(barEl, pct);
        if (remaining <= 0) {
          _applyProgressFill(barEl, 100);
          requestFinishRefresh("research");
        }
      }
    }

    updateMovementCountdowns(serverNowTs);

    if (isOverviewPage) {
      document.querySelectorAll("#overview-activities .overview-activity-row[data-finish-at]").forEach((row) => {
        const etaEl = row.querySelector("[data-activity-eta]");
        if (!etaEl) return;
        syncTimerElement(etaEl);
        const finishAt = parseTimerTarget(row.dataset.finishAt || etaEl.dataset.timerTarget || etaEl.dataset.countdownAt);
        if (!finishAt) return;
        const srvRemRaw = etaEl.dataset.serverRemaining;
        const remaining = queueJobRemainingSeconds(
          finishAt,
          serverNowTs,
          srvRemRaw === undefined || srvRemRaw === "" ? NaN : Number(srvRemRaw)
        );
        _setIfChanged(etaEl, formatTimerDisplay(remaining, etaEl.dataset.timerKind || inferTimerKind(etaEl)));
        if (remaining <= 0) {
          const actKey = String(row.dataset.activityKey || "");
          if (actKey === "build") requestFinishRefresh("buildings");
          else if (actKey === "research") requestFinishRefresh("research");
          else if (actKey === "shipyard") requestFinishRefresh("shipyard");
          else if (!actKey.startsWith("fleet")) requestFinishRefresh("planet_evolution");
        }
      });
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
  let lastHadActiveShipyard = false;
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
    capFuelCells: 0,
  };
  let _resourceTickerId = null;
  let _resourceTickerPaused = false;
  const RESOURCE_TICKER_MS_ACTIVE = 1000;
  const RESOURCE_TICKER_MS_IDLE = 5000;
  let _resourceDisplay = { metal: null, crystal: null, fuelCells: null };

  /** Shell HUD resource values only (#resource-bar) — never fleet/page [data-res] nodes. */
  function patchShellHudLiveResources(metal, crystal, fuelCells) {
    const bar = document.getElementById("resource-bar");
    if (!bar) return;
    const m = Math.max(0, Math.floor(Number(metal) || 0));
    const c = Math.max(0, Math.floor(Number(crystal) || 0));
    const f = Math.max(0, Math.floor(Number(fuelCells) || 0));
    if (_resourceDisplay.metal !== m) {
      bar.querySelectorAll(".res-value.metal").forEach((el) => {
        _setIfChanged(el, fmtNumber(m));
      });
      _resourceDisplay.metal = m;
    }
    if (_resourceDisplay.crystal !== c) {
      bar.querySelectorAll(".res-value.crystal").forEach((el) => {
        _setIfChanged(el, fmtNumber(c));
      });
      _resourceDisplay.crystal = c;
    }
    if (_resourceDisplay.fuelCells !== f) {
      bar.querySelectorAll(".res-value.fuel_cells").forEach((el) => {
        _setIfChanged(el, fmtNumber(f));
      });
      _resourceDisplay.fuelCells = f;
    }
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
    _resourceLive.capFuelCells = Math.max(0, Math.floor(Number(snapshot.storageFuelCells) || 0));
    _resourceDisplay = { metal: null, crystal: null, fuelCells: null };
    startResourceTicker();
  }

  function projectLiveResourceAmount(current, prodPerHour, cap, hours) {
    const cur = Math.max(0, Math.floor(Number(current) || 0));
    const prod = Math.max(0, Math.floor(Number(prodPerHour) || 0));
    const h = Math.max(0, Number(hours) || 0);
    const capN = Math.floor(Number(cap) || 0);
    if (capN <= 0) return Math.floor(cur + prod * h);
    // Overflow (trader/scrapyard/rewards): never clamp existing stock; production only fills to cap.
    if (cur >= capN) return cur;
    return Math.min(capN, Math.floor(cur + prod * h));
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
    return {
      metal: projectLiveResourceAmount(_resourceLive.metal, _resourceLive.prodMetal, _resourceLive.capMetal, hours),
      crystal: projectLiveResourceAmount(_resourceLive.crystal, _resourceLive.prodCrystal, _resourceLive.capCrystal, hours),
      fuelCells: projectLiveResourceAmount(_resourceLive.fuelCells, _resourceLive.prodFuelCells, _resourceLive.capFuelCells, hours),
    };
  }

  function tickLiveResourceBar() {
    if (!shouldRunVisualLoops() || _authLoopAborted || !_resourceLive.planetId || isPerfIdle()) return;
    const projected = projectLiveResourceAmounts(getApproxServerNow());
    if (!projected) return;
    patchShellHudLiveResources(projected.metal, projected.crystal, projected.fuelCells);
  }

  function _resourceTickerIntervalMs() {
    if (_hasActiveProgressJobs()) return RESOURCE_TICKER_MS_ACTIVE;
    return RESOURCE_TICKER_MS_IDLE;
  }

  function pauseResourceTicker() {
    _resourceTickerPaused = true;
    if (_resourceTickerId != null) {
      clearInterval(_resourceTickerId);
      _resourceTickerId = null;
    }
  }

  function startResourceTicker() {
    if (!shouldRunVisualLoops() || _authLoopAborted || !_resourceLive.planetId || isPerfIdle()) return;
    _resourceTickerPaused = false;
    if (_resourceTickerId != null) return;
    tickLiveResourceBar();
    _resourceTickerId = setInterval(tickLiveResourceBar, _resourceTickerIntervalMs());
  }

  function stopResourceTicker() {
    pauseResourceTicker();
    _resourceTickerPaused = false;
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
    storageFuelCells: null,
    prodMetal: null,
    prodCrystal: null,
    prodFuelCells: null,
    activePlanetId: null,
    planetLimitCurrent: null,
    planetLimitMax: null,
  };

  function patchHeaderPlanetLimitFromState(data, force) {
    const block = data && data.planet_limit;
    const planets = data && data.planets;
    let current = Number(block && block.current);
    if (!Number.isFinite(current) && Array.isArray(planets)) {
      current = planets.length;
    }
    if (!Number.isFinite(current) || current < 0) {
      current = 0;
    }
    let max = Number(block && block.max);
    if (!Number.isFinite(max) || max < 1) {
      max = 9;
    }
    current = Math.floor(current);
    max = Math.floor(max);
    if (
      !force
      && _last.planetLimitCurrent === current
      && _last.planetLimitMax === max
    ) {
      return;
    }
    _last.planetLimitCurrent = current;
    _last.planetLimitMax = max;
    const text = `${fmtNumber(current)} / ${fmtNumber(max)}`;
    document.querySelectorAll("[data-planet-limit-value]").forEach((el) => {
      _setIfChanged(el, text);
    });
  }
  GC.patchHeaderPlanetLimitFromState = patchHeaderPlanetLimitFromState;

  function resetResourceDisplayCache() {
    _last.metal = null;
    _last.crystal = null;
    _last.fuelCells = null;
    _last.energyUsed = null;
    _last.energyTotal = null;
    _last.storageMetal = null;
    _last.storageCrystal = null;
    _last.storageFuelCells = null;
    _last.prodMetal = null;
    _last.prodCrystal = null;
    _last.prodFuelCells = null;
    _resourceDisplay = { metal: null, crystal: null, fuelCells: null };
  }

  const BUILDING_ICON_FILE = {
    orbital_shipyard: "shipyard",
    fuel_storage: "fuel_cell_storage",
  };

  function buildingIconUrl(buildingType) {
    const key = String(buildingType || "").trim();
    const file = BUILDING_ICON_FILE[key] || key;
    return `/static/img/buildings/${file}.png`;
  }
  GC.buildingIconUrl = buildingIconUrl;

  // =========================
  // Messages unread badges (game-state polling)
  // =========================
  let _lastMessagesUnreadPoll = null;
  let _messagesUnreadLocalAt = 0;
  const MESSAGES_UNREAD_LOCAL_GUARD_MS = 30000;

  function coercePollUnreadForHud(data, reason) {
    if (!data || typeof data.unread_messages_count !== "number") return data;
    const localUnread = GC.lastState?.unread_messages_count;
    if (typeof localUnread !== "number") return data;
    const incomingUnread = data.unread_messages_count;
    if (incomingUnread <= localUnread) return data;
    if (_messagesUnreadLocalAt && Date.now() - _messagesUnreadLocalAt < MESSAGES_UNREAD_LOCAL_GUARD_MS) {
      return { ...data, unread_messages_count: localUnread };
    }
    return data;
  }

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

  let _lastHudOnline = null;

  /** Single write path for shell HUD (header score/rank/online/messages + resource bar). */
  function patchShellHudFromState(data, opts) {
    if (!data || data.ok === false) return;
    const forceResourceBar = Boolean(opts && opts.forceResourceBar);
    const resourceOverrides = opts && opts.resourceOverrides;

    const p = data.player || {};
    const energy = data.energy || {};
    const resources = data.resources || {};
    const storage = data.storage || {};
    const prod = data.production_per_hour || {};

    const storageMetal = Math.floor(Number(storage.metal || 0));
    const storageCrystal = Math.floor(Number(storage.crystal || 0));
    const storageFuelCells = Math.floor(Number(storage.fuel_cells || 0));

    const metal = resourceOverrides && resourceOverrides.metal != null
      ? Math.floor(Number(resourceOverrides.metal))
      : Math.floor(Number(p.metal ?? resources.metal ?? 0));
    const crystal = resourceOverrides && resourceOverrides.crystal != null
      ? Math.floor(Number(resourceOverrides.crystal))
      : Math.floor(Number(p.crystal ?? resources.crystal ?? 0));
    const fuelCells = resourceOverrides && resourceOverrides.fuelCells != null
      ? Math.floor(Number(resourceOverrides.fuelCells))
      : Math.floor(Number(p.fuel_cells ?? resources.fuel_cells ?? 0));
    const used = Math.floor(Number(p.energy_used ?? energy.used ?? resources.energy_used ?? 0));
    const total = Math.floor(Number(p.energy_total ?? energy.total ?? resources.energy_total ?? 0));

    const prodMetal = Math.floor(Number(prod.metal_mine ?? prod.metal ?? 0));
    const prodCrystal = Math.floor(Number(prod.crystal_mine ?? prod.crystal ?? 0));
    const prodFuelCells = Math.floor(Number(prod.fuel_cell_plant ?? prod.fuel_cells ?? 0));

    const bar = document.getElementById("resource-bar");
    if (bar) {
      if (forceResourceBar || _last.metal !== metal) {
        bar.querySelectorAll(".res-value.metal").forEach((el) => { _setIfChanged(el, fmtNumber(metal)); });
        _last.metal = metal;
        _resourceDisplay.metal = metal;
      }
      if (forceResourceBar || _last.crystal !== crystal) {
        bar.querySelectorAll(".res-value.crystal").forEach((el) => { _setIfChanged(el, fmtNumber(crystal)); });
        _last.crystal = crystal;
        _resourceDisplay.crystal = crystal;
      }
      if (forceResourceBar || (_last.storageMetal !== storageMetal && storageMetal > 0)) {
        bar.querySelectorAll(".res-cap.metal").forEach((el) => { _setIfChanged(el, fmtNumber(storageMetal)); });
        _last.storageMetal = storageMetal;
      }
      if (forceResourceBar || (_last.storageCrystal !== storageCrystal && storageCrystal > 0)) {
        bar.querySelectorAll(".res-cap.crystal").forEach((el) => { _setIfChanged(el, fmtNumber(storageCrystal)); });
        _last.storageCrystal = storageCrystal;
      }
      if (forceResourceBar || _last.fuelCells !== fuelCells) {
        bar.querySelectorAll(".res-value.fuel_cells").forEach((el) => { _setIfChanged(el, fmtNumber(fuelCells)); });
        _last.fuelCells = fuelCells;
        _resourceDisplay.fuelCells = fuelCells;
      }
      if (forceResourceBar || (_last.storageFuelCells !== storageFuelCells && storageFuelCells > 0)) {
        bar.querySelectorAll(".res-cap.fuel_cells").forEach((el) => { _setIfChanged(el, fmtNumber(storageFuelCells)); });
        _last.storageFuelCells = storageFuelCells;
      }

      const rateLabel = (key, perHour) => {
        const ph = Math.floor(Number(perHour) || 0);
        bar.querySelectorAll(`[data-res-rate="${key}"]`).forEach((el) => {
          if (ph > 0) {
            const sign = ph >= 0 ? "+" : "";
            _setIfChanged(el, `${sign}${fmtNumber(ph)}/h`);
            el.style.visibility = "visible";
            el.removeAttribute("hidden");
            el.removeAttribute("aria-hidden");
          } else {
            _setIfChanged(el, "");
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
        const energyEl = bar.querySelector("#res-energy") || document.getElementById("res-energy");
        if (energyEl) _setIfChanged(energyEl, energyText);
        bar.querySelectorAll("[data-energy-used]").forEach((el) => {
          _setIfChanged(el, fmtNumber(used));
        });
        bar.querySelectorAll("[data-energy-total]").forEach((el) => {
          _setIfChanged(el, fmtNumber(total));
        });
        _last.energyUsed = used;
        _last.energyTotal = total;
      }
      patchResourceBarEnergyWarning(used, total);
    }

    patchHeaderPlanetLimitFromState(data, forceResourceBar);

    if (data.score) {
      const s = data.score;
      const serverTotal = Number(s.total || 0);
      const rank = typeof s.rank === "number" ? s.rank : Number(s.rank || 0);
      const totalPlayers = Number(s.total_players || 0);
      const scoreStale = _scoreState.lastServerTotal !== null
        && serverTotal < _scoreState.lastServerTotal
        && !forceResourceBar;

      if (!scoreStale) {
        let delta = 0;
        if (_scoreState.lastServerTotal !== null && serverTotal > _scoreState.lastServerTotal) {
          delta = serverTotal - _scoreState.lastServerTotal;
        }
        _scoreState.lastServerTotal = serverTotal;

        const hudScoreEl = document.getElementById("hud-score-total");
        const hudRankEl = document.getElementById("hud-score-rank");

        if (hudScoreEl && _scoreState.lastAnimatedTotal !== serverTotal) {
          animateNumber(hudScoreEl, serverTotal, { duration: 700 });
          if (delta !== 0) showScoreDelta(delta, serverTotal);
          _scoreState.lastAnimatedTotal = serverTotal;
        }

        const rankText = (rank >= 1 && totalPlayers > 0) ? `#${rank}/${totalPlayers}` : "#–";
        if (hudRankEl) _setIfChanged(hudRankEl, rankText);
      }
    }

    const stats = data.player_stats || {};
    const onlineNow = Number(stats.online_now);
    const onlineTotal = Number(stats.total_players);
    if (Number.isFinite(onlineNow) && Number.isFinite(onlineTotal)) {
      const onlineText = `${fmtNumber(onlineNow)}/${fmtNumber(onlineTotal)}`;
      if (_lastHudOnline !== onlineText) {
        document.querySelectorAll("[data-hud-online-value]").forEach((el) => {
          _setIfChanged(el, onlineText);
        });
        _lastHudOnline = onlineText;
      }
    }

    if (typeof data.unread_messages_count === "number" && !(opts && opts.skipMessagesUnread)) {
      updateMessagesUnreadBadges(data.unread_messages_count);
    }
  }

  GC.patchShellHudFromState = patchShellHudFromState;

  GC.mergeLastState = function mergeLastState(partial, reason) {
    if (!partial || typeof partial !== "object") return GC.lastState;
    const base = GC.lastState && GC.lastState.ok === true ? GC.lastState : { ok: true };
    GC.lastState = { ...base, ...partial };
    if (typeof partial.unread_messages_count === "number" && String(reason || "").includes("messages")) {
      _messagesUnreadLocalAt = Date.now();
    }
    patchShellHudFromState(GC.lastState, { forceResourceBar: true, reason: reason || "merge" });
    return GC.lastState;
  };

  function patchOverviewScoreFromState(data) {
    if (!data || !data.score) return;
    const s = data.score;
    const serverTotal = Number(s.total || 0);
    const rank = typeof s.rank === "number" ? s.rank : Number(s.rank || 0);
    const totalPlayers = Number(s.total_players || 0);
    const scoreBuildings = Number(s.buildings || 0);
    const scoreResearch = Number(s.research || 0);

    const scoreStale = _scoreState.lastServerTotal !== null && serverTotal < _scoreState.lastServerTotal;
    if (scoreStale) return;

    const ovScoreVal = document.getElementById("overview-score-value");
    const ovScoreRank = document.getElementById("overview-score-rank");
    const ovScoreBuild = document.getElementById("overview-score-buildings");
    const ovScoreRes = document.getElementById("overview-score-research");

    if (ovScoreVal) {
      animateNumber(ovScoreVal, serverTotal, { duration: 750 });
    }
    if (ovScoreRank) {
      ovScoreRank.textContent = (rank >= 1 && totalPlayers > 0) ? `#${rank}/${totalPlayers}` : "#–/–";
    }
    if (ovScoreBuild) animateNumber(ovScoreBuild, scoreBuildings, { duration: 650 });
    if (ovScoreRes) animateNumber(ovScoreRes, scoreResearch, { duration: 650 });
  }

  // =========================
  function patchResearchPanelFromState(data) {
    renderResearchQueue((data && data.research) || null);
  }

  function patchShipyardPanelFromState(data, activePlanetId) {
    const page = document.getElementById("shipyard-page");
    if (!page || page.dataset.ready !== "1") return;
    const statePid = Number(
      activePlanetId || data?.active_planet_id || GC.lastState?.active_planet_id || 0
    );
    const pagePid = Number(page.dataset.planetId || 0);
    if (statePid > 0 && pagePid > 0 && pagePid !== statePid) {
      _lastShipyardQueueSignature = "";
      SHIPYARDQ.active.finishTime = 0;
      SHIPYARDQ.active.totalSeconds = 0;
      refreshShipyardStateCoalesced(page);
      return;
    }
    if (data?.shipyard_queue) {
      renderShipyardQueue(page, data.shipyard_queue);
    }
  }

  function patchDefensePanelFromGameState(data, activePlanetId) {
    const page = document.getElementById("defense-page");
    if (!page || page.dataset.ready !== "1" || !data?.defense) return;
    const statePid = Number(
      activePlanetId || data?.active_planet_id || GC.lastState?.active_planet_id || 0
    );
    const pagePid = Number(page.dataset.planetId || 0);
    if (statePid > 0 && pagePid > 0 && pagePid !== statePid) return;
    const slice = data.defense;
    const inner = slice.defenses && typeof slice.defenses === "object" ? slice.defenses : slice;
    if (!inner || inner.ready === false) return;
    const payload = {
      ...inner,
      defense_queue: slice.queue || inner.defense_queue,
    };
    applyDefenseState(page, payload);
  }

  function syncProductionPanelsAfterGameState(data, reason, activePlanetId) {
    patchDefensePanelFromGameState(data, activePlanetId);
    const reasonStr = String(reason || "");
    const onShipyard = document.getElementById("shipyard-page")?.dataset.ready === "1";
    const completionReason =
      reasonStr === "timer_done"
      || reasonStr === "queue_timer_zero"
      || reasonStr.endsWith("_finished")
      || reasonStr === "shipyard_build"
      || reasonStr === "shipyard_cancel"
      || reasonStr === "defense_build"
      || reasonStr === "defense_cancel";
    if (onShipyard && completionReason && !data?.shipyard_queue) {
      const syPage = document.getElementById("shipyard-page");
      if (syPage) refreshShipyardStateCoalesced(syPage);
    }
  }

  // Status polling / GC.refreshGameState
  // =========================
  function applyGameStateData(data, _reason, opts) {
      if (!data || data.ok === false) return false;
      const reason = String(_reason || "");
      const skipMessagesUnread = Boolean(opts && opts.skipMessagesUnread);
      const hudOnly = Boolean(opts && opts.hudOnly);
      const forceResourceBar = Boolean(opts && (opts.forceResourceBar || hudOnly || opts.planetSwitch));
      const planetSwitch = Boolean(opts && opts.planetSwitch);
      const planetSwitchReload = Boolean(opts && opts.planetSwitchReload);
      const skipScopedPanels = Boolean(
        (opts && opts.skipScopedPanels) || (planetSwitch && !planetSwitchReload)
      );

      if (reason === "poll" || reason === "page_hydrate") {
        const st = Number(data.server_time || 0);
        if (st && _lastAppliedServerTime && st < _lastAppliedServerTime) {
          return false;
        }
      }

      if (data.server_time) setServerTime(data.server_time);
      else if (data.server_now) setServerTime(data.server_now);

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
          if (!skipScopedPanels) syncScopedPlanetIds(activePlanetId);
        }

        if (planetSwitch && activePlanetId > 0) {
          const fleetPage = document.getElementById("fleet-page");
          if (fleetPage) {
            fleetPage._fleetApplySeq = 0;
            fleetPage._fleetLiveServerTime = 0;
            delete fleetPage.dataset.fleetUrlMission;
            if (fleetPage._fleetRt) {
              fleetPage._fleetRt.lastPreview = null;
              if (fleetPage._fleetRt.previewTimer) {
                clearTimeout(fleetPage._fleetRt.previewTimer);
                fleetPage._fleetRt.previewTimer = null;
              }
            }
          }
        } else if (_reason !== "planet_switch") {
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
      const storageFuelCells = Math.floor(Number(storage.fuel_cells || 0));

      const metal = Math.floor(Number(p.metal ?? resources.metal ?? 0));
      const crystal = Math.floor(Number(p.crystal ?? resources.crystal ?? 0));
      const fuelCells = Math.floor(Number(p.fuel_cells ?? resources.fuel_cells ?? 0));
      const used = Math.floor(Number(p.energy_used ?? energy.used ?? resources.energy_used ?? 0));
      const total = Math.floor(Number(p.energy_total ?? energy.total ?? resources.energy_total ?? 0));

      const prodMetal = Math.floor(Number(prod.metal_mine ?? prod.metal ?? 0));
      const prodCrystal = Math.floor(Number(prod.crystal_mine ?? prod.crystal ?? 0));
      const prodFuelCells = Math.floor(Number(prod.fuel_cell_plant ?? prod.fuel_cells ?? 0));

      patchShellHudFromState(coercePollUnreadForHud(data, reason), { forceResourceBar, skipMessagesUnread });

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
        storageFuelCells,
      });

      if (hudOnly) {
        GC.lastState = GC.lastState && GC.lastState.ok === true ? { ...GC.lastState, ...data } : data;
        return false;
      }

      if (skipScopedPanels) {
        const stApplied = Number(data.server_time || 0);
        if (stApplied) _lastAppliedServerTime = Math.max(_lastAppliedServerTime, stApplied);
        GC.lastState = coercePollUnreadForHud(data, reason);
        return false;
      }

      patchOverviewScoreFromState(data);

      if (typeof data.unread_messages_count === "number") {
        const onMessagesPage = GC.detectPage() === "messages";
        const hudUnread = coercePollUnreadForHud(data, reason).unread_messages_count;
        const prevUnread = _lastMessagesUnreadPoll;
        const unreadIncreased =
          prevUnread !== null && hudUnread > prevUnread;
        if (!skipMessagesUnread) {
          _lastMessagesUnreadPoll = hudUnread;

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
      if (ovMetalVal) _setIfChanged(ovMetalVal, fmtNumber(metal));

      const ovCryVal = document.querySelector('#overview-crystal-val .gc-val[data-res="crystal"]');
      if (ovCryVal) _setIfChanged(ovCryVal, fmtNumber(crystal));

      const ovFuelVal = document.querySelector('#overview-fuel-val .gc-val[data-res="fuel_cells"]');
      if (ovFuelVal) _setIfChanged(ovFuelVal, fmtNumber(fuelCells));

      patchOverviewResourceBars(metal, crystal, fuelCells, storageMetal, storageCrystal, storageFuelCells);

      const ovEnergyUsed = document.querySelector('#overview-energy-card .gc-val[data-energy-used]');
      const ovEnergyTotal = document.querySelector('#overview-energy-card [data-energy-total]');
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
          } else if (key === "fuel_storage" && storageFuelCells > 0) {
            _setIfChanged(prodCell, `${fmtNumber(fuelCells)} / ${fmtNumber(storageFuelCells)}`);
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
          const finishAt = resolveQueueJobFinishTime(activeJob);
          const rem = finishAt
            ? queueJobRemainingSeconds(finishAt, getTimerServerNow(), resolveQueueJobRemaining(activeJob))
            : Math.max(0, Math.floor(Number(activeJob.remaining || activeJob.remaining_seconds || 0)));
          statusText = `${t("status_building", "Im Bau")} (${formatEta(Math.ceil(rem))})`;
        }

        if (cfg.statusId) setText(cfg.statusId, statusText);

        const btn = document.getElementById(cfg.btnId);
        if (btn && btn.classList.contains("gc-bld-head-action-btn")) {
          if (btn.getAttribute("aria-label") !== btnLabel) {
            btn.setAttribute("aria-label", btnLabel);
            btn.title = btnLabel;
          }
        } else if (btn && btn.tagName === "A" && !bqFull && btn.textContent !== btnLabel) {
          btn.textContent = btnLabel;
        }
      });

      renderBuildQueue(buildQueueRaw);
      updateBuildQueueActions(buildQueueRaw);
      patchResearchPanelFromState(data);
      updateResearchQueueActions(research);

      if (activeResearch) {
        const totalSec = Math.max(
          1,
          parseInt(activeResearch.total_seconds, 10) ||
            parseInt(activeResearch.total, 10) ||
            (resolveQueueJobRemaining(activeResearch) || 0) + 1
        );
        const finishAt = resolveQueueJobFinishTime(activeResearch);

        const ovBox = document.getElementById("overview-research-active");
        if (ovBox) {
          ovBox.dataset.total = String(totalSec);
          if (finishAt > 0) ovBox.dataset.finishAt = String(finishAt);
          const rem = resolveQueueJobRemaining(activeResearch);
          if (Number.isFinite(rem) && rem >= 0) {
            assignMonotonicServerRemaining(ovBox, rem, finishAt);
          } else {
            delete ovBox.dataset.serverRemaining;
          }
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
      patchTraderHubBalance(metal, crystal, storageMetal, storageCrystal, fuelCells, storageFuelCells);
      if (data.planet_teaser) patchPlanetTeaser(data.planet_teaser);

      if (data.buildings_panel) {
        patchBuildingPanel(data.buildings_panel, buildQueueRaw);
      }

      if (research.techs) {
        patchResearchPanel(research.techs, research);
      }

      patchShipyardPanelFromState(data, activePlanetId);

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
      lastHadActiveShipyard = SHIPYARDQ.active.finishTime > getTimerServerNow();

      const stApplied = Number(data.server_time || 0);
      if (stApplied) _lastAppliedServerTime = Math.max(_lastAppliedServerTime, stApplied);

      GC.lastState = coercePollUnreadForHud(data, reason);
      GC.startProgressTicker();
      _maybeRefreshStaleMovementCountdowns();
      syncProductionPanelsAfterGameState(data, reason, activePlanetId);
      syncPerfBodyClasses();

      if (typeof GC.scheduleLogisticsRefreshFromState === "function") {
        GC.scheduleLogisticsRefreshFromState();
      }

      return hasActiveBuild || hasActiveResearchNow || lastHadActiveShipyard;
  }

  function gameStateIncludePanel() {
    const page = typeof GC.detectPage === "function" ? GC.detectPage() : "";
    return (
      page === "buildings"
      || page === "research"
      || page === "shipyard"
      || page === "defense"
      || page === "trader_hub"
      || page === "overview"
      || page === "fleet"
      || page === "logistics"
    );
  }

  function gameStateWantPanelPoll(reason) {
    const reasonStr = String(reason || "");
    if (gameStateIncludePanel()) return true;
    return (
      reasonStr.endsWith("_finished")
      || reasonStr === "fleet_countdown_expired"
      || reasonStr === "timer_done"
      || reasonStr === "queue_timer_zero"
    );
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
    const isChainReason = isFinishReason || reasonStr === "fleet_countdown_expired" || reasonStr === "timer_done";

    if (GC.refreshInFlight) {
      if (isChainReason) {
        if (!_queuedChainRefreshReason) _queuedChainRefreshReason = reasonStr;
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
    const stateGenAtStart = _clientStateGen;

    let resolveFlight;
    let rejectFlight;
    const flight = new Promise((resolve, reject) => {
      resolveFlight = resolve;
      rejectFlight = reject;
    });
    GC.refreshInFlight = flight;

    (async () => {
      try {
        const panelQ = gameStateWantPanelPoll(reason) ? "?include_panel=1" : "";
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

        if (stateGenAtStart !== _clientStateGen) {
          resolveFlight(null);
          return null;
        }

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
          GC.startPolling(lastHadActiveJob || lastHadActiveResearch || lastHadActiveShipyard, true);
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
  // Building category panels (sidebar-driven – survives PJAX)
  // =========================

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
          if (typeof GC.navigateTo === "function") {
            await GC.navigateTo("/overview", { push: true, force: true });
          } else if (typeof GC.reloadCurrentPage === "function") {
            await GC.reloadCurrentPage({ force: true });
          }
        } catch (err) {
          if (err && err.message === "auth") return;
          setHint(t("planet_error_delete_failed", "Löschen fehlgeschlagen."), true);
          syncDeleteState();
        }
      });
    }

    GC.applyOverviewPlanetName = setPlanetNameDisplay;
  }

  function parseInventoryPageState() {
    const el = document.getElementById("inventory-page-state");
    if (el && el.textContent) {
      try {
        return JSON.parse(el.textContent);
      } catch (_) {}
    }
    return { ready: false, containers: [], other_items: [] };
  }

  function inventoryResourceLabel(key) {
    if (key === "metal") return t("resource_metal", "Ferronit");
    if (key === "crystal") return t("resource_crystal", "Crytite");
    if (key === "fuel_cells") return t("resource_fuel_cells", "Brennzellen");
    return key;
  }

  function inventoryEffectMessage(effect) {
    if (!effect) return "";
    const params = { ...(effect.message_params || {}) };

    if (effect.kind === "time_boost") {
      const sec = parseInt(
        effect.seconds_shifted ?? params.seconds ?? effect.seconds_reduced,
        10
      ) || 0;
      const minutes = Math.max(1, Math.round(sec / 60));
      const target = String(effect.target || "build");
      const key = effect.message_key || `inv_effect_${target}_boost`;
      const fallbacks = {
        inv_effect_build_boost: "Bauzeit um %(minutes)s Minuten reduziert",
        inv_effect_research_boost: "Forschungszeit um %(minutes)s Minuten reduziert",
        inv_effect_shipyard_boost: "Schiffsbauzeit um %(minutes)s Minuten reduziert",
      };
      return tf(key, { ...params, minutes, seconds: sec }, fallbacks[key] || key);
    }

    if (effect.kind === "resource") {
      const label = inventoryResourceLabel(effect.resource_key || "metal");
      return tf(
        "inv_effect_resource_fmt",
        {
          amount: (params.amount || effect.amount || 0).toLocaleString(),
          resource: label,
        },
        "+%(amount)s %(resource)s erhalten"
      );
    }

    if (effect.kind === "planet_xp") {
      const key = effect.message_key || "inv_effect_planet_xp";
      return tf(
        key,
        { ...params, xp: params.xp ?? effect.xp_gained ?? 0 },
        "Planet erhielt +%(xp)s XP"
      );
    }

    if (effect.kind === "craft") {
      const outName = t(`inv_${params.output_key}`, params.output_key || "");
      const key = effect.message_key || "inv_effect_craft";
      return tf(
        key,
        { ...params, item: outName },
        "%(amount)s× %(item)s hergestellt"
      );
    }

    if (effect.message_key) {
      return tf(effect.message_key, params, effect.message_key);
    }
    return "";
  }

  function isInventoryPayload(inv) {
    return Boolean(inv && typeof inv === "object" && Array.isArray(inv.other_items));
  }

  function syncInventoryPageStateScript(inv) {
    const el = document.getElementById("inventory-page-state");
    if (el && inv) {
      try {
        el.textContent = JSON.stringify(inv);
      } catch (_) {}
    }
  }

  function applyInventoryConsumption(base, itemKey, consumed) {
    const inv = {
      ...(base || {}),
      other_items: [...((base && base.other_items) || [])],
    };
    const key = String(itemKey || "");
    const useCount = Math.max(1, parseInt(consumed, 10) || 1);
    if (!key) return inv;
    inv.other_items = inv.other_items
      .map((it) => {
        if (String(it.item_key) !== key) return it;
        const next = (parseInt(it.amount, 10) || 0) - useCount;
        return next > 0 ? { ...it, amount: next } : null;
      })
      .filter(Boolean);
    return inv;
  }

  function resolveInventoryFromAction(res) {
    if (isInventoryPayload(res?.inventory)) return res.inventory;
    const base = _inventoryLastState || parseInventoryPageState();
    if (res?.ok && res.item_key) {
      return applyInventoryConsumption(base, res.item_key, res.consumed);
    }
    return base;
  }

  async function refreshInventoryFromServer() {
    try {
      const res = await GC.fetchGameAction("/api/inventory/state");
      if (res?.ok && isInventoryPayload(res.inventory)) {
        _inventoryLastState = res.inventory;
        syncInventoryPageStateScript(_inventoryLastState);
        patchInventoryDom(_inventoryLastState);
        return true;
      }
    } catch (_) {}
    return false;
  }

  function applyInventoryActionResult(res) {
    _inventoryLastState = resolveInventoryFromAction(res);
    syncInventoryPageStateScript(_inventoryLastState);
    patchInventoryDom(_inventoryLastState);
    if (res?.ok && res.item_key && !isInventoryPayload(res?.inventory)) {
      refreshInventoryFromServer();
    }
  }

  function inventoryUseReasonText(reason) {
    const map = {
      no_build_queue: t("inv_error_no_build_queue", "Keine Bauaufträge in der Warteschlange."),
      no_effect_target: t("inv_error_no_effect_target", "Kein gültiges Ziel für dieses Item."),
      insufficient_items: t("inv_error_insufficient_items", "Nicht genug Items im Inventar."),
      item_not_usable: t("inv_error_item_not_usable", "Dieses Item kann nicht benutzt werden."),
      invalid_item: t("inv_error_invalid_item", "Unbekanntes Item."),
      inventory_unavailable: t("inv_unavailable", "Inventar ist derzeit nicht verfügbar."),
    };
    return map[reason] || t("msg_generic_error", "Aktion fehlgeschlagen.");
  }

  function renderInventoryEffect(effect) {
    const panel = document.getElementById("inventory-rewards-panel");
    const msgEl = document.querySelector("[data-inventory-effect-message]");
    const list = document.querySelector("[data-inventory-rewards-list]");
    if (!panel) return;
    const text = inventoryEffectMessage(effect);
    const icons = {
      time_boost: effect?.target === "research" ? "📡" : effect?.target === "shipyard" ? "🛰️" : "🔧",
      resource: "📦",
      planet_xp: "🪐",
      craft: "🧬",
      production_grant: "⚡",
      research_instant: "📜",
    };
    const icon = icons[effect?.kind] || "✨";
    if (msgEl) {
      if (text) {
        msgEl.className = "inventory-effect-message inventory-effect-message--success";
        msgEl.innerHTML = `<span class="inventory-effect-icon" aria-hidden="true">${icon}</span><span class="inventory-effect-text">${escapeHtml(text)}</span>`;
        msgEl.hidden = false;
      } else {
        msgEl.textContent = "";
        msgEl.hidden = true;
      }
    }
    if (list) list.innerHTML = "";
    if (text) panel.hidden = false;
  }

  function buildInventoryItemRowHtml(item) {
    const rarity = item.rarity || "common";
    const name = t(item.name_key || `inv_item_${item.item_key}`, item.item_key);
    const amount = parseInt(item.amount, 10) || 0;
    const craftProgress = (item.craft_progress || [])
      .map(
        (cp) =>
          `<span class="inventory-craft-progress gc-mono">${amount.toLocaleString()} / ${parseInt(cp.required, 10) || 0} ${escapeHtml(t(cp.name_key, cp.output_key))}</span>`
      )
      .join("");
    const collectibleBadge = item.collectible
      ? `<span class="inventory-collectible-badge">${escapeHtml(t("inv_collectible_badge", "Sammlerstück"))}</span>`
      : "";
    const useBtn = item.usable
      ? `<button type="button" class="gc-btn gc-btn-primary gc-btn-xs inventory-use-btn" data-inventory-use="${escapeHtml(item.item_key)}">${escapeHtml(t("inv_use_btn", "Benutzen"))}</button>`
      : "";
    const craftBtns = (item.craft_progress || [])
      .filter((cp) => cp.can_craft)
      .map(
        (cp) =>
          `<button type="button" class="gc-btn gc-btn-secondary gc-btn-xs inventory-craft-btn" data-inventory-craft="${escapeHtml(cp.recipe_key)}">${escapeHtml(t("inv_craft_btn", "Craften"))}</button>`
      )
      .join("");
    return `<span class="inventory-item-icon" aria-hidden="true">${item.icon || "📦"}</span><div class="inventory-item-body"><span class="inventory-item-name">${escapeHtml(name)}</span>${craftProgress}</div><span class="inventory-rarity-badge inventory-rarity-badge--${escapeHtml(rarity)}">${escapeHtml(t(`inv_rarity_${rarity}`, rarity))}</span>${collectibleBadge}<span class="inventory-item-amount gc-mono" data-inventory-item-amount="${escapeHtml(item.item_key)}">×${amount.toLocaleString()}</span>${useBtn}${craftBtns}`;
  }

  let _lootModalState = null;

  function playLootboxOpenSound() {
    if (window.GC?.settings?.sound === false) return;
    try {
      const audio = new Audio("/static/sounds/lootboxes/lootbox_sound.mp3");
      audio.volume = 0.45;
      audio.play().catch(() => {});
    } catch (_) {}
  }

  function lootTileAmountLabel(tile) {
    const amt = parseInt(tile.amount, 10) || 0;
    const type = String(tile.type || "");
    if (type === "resource") return `+${amt.toLocaleString()}`;
    if (type === "booster" && String(tile.key || "").includes("booster")) {
      const sec = parseInt(tile.booster_seconds, 10) || 0;
      if (sec >= 3600) return `${Math.round(sec / 3600)} h`;
      if (sec >= 60) return `${Math.round(sec / 60)} Min`;
    }
    return `×${amt.toLocaleString()}`;
  }

  function lootTileName(tile) {
    if (tile.name_key) return t(tile.name_key, tile.label || tile.key || "");
    if (tile.label) return tile.label;
    if (tile.type === "resource") return inventoryResourceLabel(tile.key?.split(":")[1] || tile.key);
    return tile.key || "";
  }

  function buildLootRollTileHtml(tile, index) {
    const rarity = tile.rarity || "common";
    const name = lootTileName(tile);
    const amount = lootTileAmountLabel(tile);
    const icon = tile.icon || "📦";
    const rarityLabel = t(`inv_rarity_${rarity}`, rarity);
    return `<div class="gc-loot-tile rarity-${escapeHtml(rarity)}" data-loot-tile-index="${index}" data-rarity="${escapeHtml(rarity)}">
      <span class="gc-loot-tile-icon" aria-hidden="true">${icon}</span>
      <span class="gc-loot-tile-name">${escapeHtml(name)}</span>
      <span class="gc-loot-tile-amount gc-mono">${escapeHtml(amount)}</span>
      <span class="gc-loot-tile-rarity">${escapeHtml(rarityLabel)}</span>
    </div>`;
  }

  function buildLootRollTiles(payload) {
    const tiles = payload.roll_preview || [];
    return tiles.map((tile, i) => buildLootRollTileHtml(tile, i)).join("");
  }

  function buildLootRewardResultHtml(reward, primary) {
    const amt = parseInt(reward.amount, 10) || 0;
    const rarity = reward.rarity || "common";
    const primaryClass = primary ? " gc-loot-result-row--primary" : "";
    if (reward.reward_type === "resource") {
      const label = inventoryResourceLabel(reward.reward_key);
      return `<div class="gc-loot-result-row rarity-${escapeHtml(rarity)}${primaryClass}">
        <span class="gc-loot-result-icon" aria-hidden="true">${reward.icon || "📦"}</span>
        <div class="gc-loot-result-body">
          <span class="gc-loot-result-name">${escapeHtml(label)}</span>
          <span class="gc-loot-result-amount gc-mono">+${amt.toLocaleString()}</span>
        </div>
        <span class="gc-loot-result-rarity">${escapeHtml(t(`inv_rarity_${rarity}`, rarity))}</span>
      </div>`;
    }
    const name = t(reward.name_key || `inv_item_${reward.reward_key}`, reward.reward_key);
    const icon = reward.icon || (reward.reward_type === "ship" ? "🛰️" : reward.reward_type === "defense" ? "🛡️" : "📦");
    return `<div class="gc-loot-result-row rarity-${escapeHtml(rarity)}${primaryClass}">
      <span class="gc-loot-result-icon" aria-hidden="true">${icon}</span>
      <div class="gc-loot-result-body">
        <span class="gc-loot-result-name">${escapeHtml(name)}</span>
        <span class="gc-loot-result-amount gc-mono">×${amt.toLocaleString()}</span>
      </div>
      <span class="gc-loot-result-rarity">${escapeHtml(t(`inv_rarity_${rarity}`, rarity))}</span>
    </div>`;
  }

  function lootPrimaryRewardKey(payload) {
    const wr = payload.winning_reward || {};
    if (wr.preview_key) return String(wr.preview_key);
    if (wr.key && wr.type) return `${wr.type}:${wr.key}`;
    if (wr.key) return String(wr.key);
    const rewards = payload.rewards || [];
    if (!rewards.length) return "";
    const r = rewards[0];
    return `${r.reward_type}:${r.reward_key}`;
  }

  function canOpenContainerAgain(payload) {
    const key = payload.container_key || payload.item_key;
    const inv = payload.inventory || payload._deferredInventory || {};
    const row = (inv.containers || []).find((c) => c.item_key === key);
    if (!row) return false;
    if (key === "container_basic") {
      return (parseInt(row.amount, 10) || 0) > 0 || Boolean(row.free_open_available);
    }
    return (parseInt(row.amount, 10) || 0) > 0;
  }

  function closeLootModal() {
    if (_lootModalState?.timerId) {
      clearTimeout(_lootModalState.timerId);
    }
    if (_lootModalState?.onKeydown) {
      document.removeEventListener("keydown", _lootModalState.onKeydown);
    }
    const modal = document.querySelector(".gc-loot-modal");
    if (modal) modal.remove();
    document.body.classList.remove("gc-loot-modal-open");
    _lootModalState = null;
  }

  function revealLootRewards(modal, payload) {
    if (!modal || !payload) return;
    if (_lootModalState?.revealed) return;
    if (_lootModalState) _lootModalState.revealed = true;
    if (_lootModalState?.timerId) {
      clearTimeout(_lootModalState.timerId);
      _lootModalState.timerId = null;
    }

    const strip = modal.querySelector(".gc-loot-strip");
    if (strip) strip.classList.add("gc-loot-strip--done");

    const status = modal.querySelector(".gc-loot-status");
    const results = modal.querySelector(".gc-loot-results");
    const skipBtn = modal.querySelector(".gc-loot-skip");
    const closeBtn = modal.querySelector(".gc-loot-close");
    if (status) status.hidden = true;
    if (skipBtn) skipBtn.hidden = true;
    if (closeBtn) closeBtn.disabled = false;

    if (results) {
      const rewards = payload.rewards || [];
      const primaryKey = lootPrimaryRewardKey(payload);
      const card = modal.querySelector(".gc-loot-card");
      if (card && payload.winning_reward?.rarity) {
        card.classList.add(`gc-loot-card--win-${payload.winning_reward.rarity}`);
      }
      results.innerHTML = `
        <div class="gc-loot-results-panel">
          <div class="gc-loot-results-title">${escapeHtml(t("inv_loot_modal_your_reward", "Deine Belohnung"))}</div>
          <div class="gc-loot-results-grid">${rewards
            .map((r) => {
              const rk = `${r.reward_type}:${r.reward_key}`;
              return buildLootRewardResultHtml(r, rk === primaryKey);
            })
            .join("")}</div>
          <div class="gc-loot-results-actions">
            <button type="button" class="gc-btn gc-btn-primary gc-loot-to-inventory">${escapeHtml(t("inv_loot_modal_to_inventory", "Zum Inventar"))}</button>
            ${canOpenContainerAgain(payload) ? `<button type="button" class="gc-btn gc-btn-secondary gc-loot-open-again">${escapeHtml(t("inv_loot_modal_open_again", "Noch einmal öffnen"))}</button>` : ""}
            <button type="button" class="gc-btn gc-btn-ghost gc-loot-close-action">${escapeHtml(t("inv_loot_modal_close", "Schließen"))}</button>
          </div>
        </div>`;
      results.hidden = false;
    }

    if (payload._deferredState) {
      applyActionState({ ok: true, state: payload._deferredState }, "inventory_open");
    }
    applyInventoryActionResult({
      ok: true,
      inventory: payload.inventory || payload._deferredInventory,
      item_key: payload.item_key || payload.container_key,
      consumed: payload.consumed || payload.opened || 1,
    });

    const page = document.getElementById("inventory-page");
    if (page) {
      page.querySelectorAll("[data-inventory-open]").forEach((btn) => {
        btn.disabled = false;
      });
      patchInventoryDom(_inventoryLastState || parseInventoryPageState());
    }
  }

  function computeLootRollTarget(strip, roller, winningIndex) {
    const tiles = strip.querySelectorAll(".gc-loot-tile");
    const tile = tiles[winningIndex];
    if (!tile || !roller) return 0;
    const tileCenter = tile.offsetLeft + tile.offsetWidth / 2;
    const rollerCenter = roller.clientWidth / 2;
    return rollerCenter - tileCenter;
  }

  function animateLootRoll(modal, payload) {
    const strip = modal.querySelector(".gc-loot-strip");
    const roller = modal.querySelector(".gc-loot-roller");
    if (!strip || !roller) {
      revealLootRewards(modal, payload);
      return;
    }

    playLootboxOpenSound();

    const winningIndex = Math.max(
      0,
      Math.min(
        parseInt(payload.winning_index, 10) || 0,
        (payload.roll_preview || []).length - 1
      )
    );

    const runAnimation = () => {
      const targetX = computeLootRollTarget(strip, roller, winningIndex);

      const finish = () => {
        strip.style.transition = "none";
        strip.style.transform = `translate3d(${targetX}px, 0, 0)`;
        strip.querySelectorAll(".gc-loot-tile.is-winning").forEach((el) => el.classList.remove("is-winning"));
        strip.querySelector(`.gc-loot-tile[data-loot-tile-index="${winningIndex}"]`)?.classList.add("is-winning");
        revealLootRewards(modal, payload);
      };

      if (_prefersReducedMotion) {
        finish();
        return;
      }

      strip.style.transform = "translate3d(0, 0, 0)";
      strip.style.transition = "transform 2.4s cubic-bezier(0.12, 0.85, 0.18, 1)";
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          strip.style.transform = `translate3d(${targetX}px, 0, 0)`;
        });
      });

      if (_lootModalState) {
        _lootModalState.timerId = window.setTimeout(finish, 2400);
        _lootModalState.skip = finish;
      }
    };

    requestAnimationFrame(() => {
      requestAnimationFrame(runAnimation);
    });
  }

  function showLootOpeningModal(payload) {
    closeLootModal();
    const containerKey = payload.container_key || payload.item_key || "container_basic";
    const containerName = t(
      payload.container_name_key || `inv_${containerKey}`,
      containerKey
    );
    const containerRarity = payload.container_rarity || "common";
    const root = document.getElementById("gc-loot-modal-root") || document.body;

    const modal = document.createElement("div");
    modal.className = "gc-loot-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", t("inv_loot_modal_title", "Container geöffnet"));
    modal.innerHTML = `
      <div class="gc-loot-card gc-loot-card--hud rarity-${escapeHtml(containerRarity)}">
        <div class="gc-loot-card-corners" aria-hidden="true"></div>
        <div class="gc-loot-card-scanlines" aria-hidden="true"></div>
        <button type="button" class="gc-loot-close gc-btn gc-btn-ghost gc-btn-xs" aria-label="${escapeHtml(t("inv_loot_modal_close", "Schließen"))}" disabled>×</button>
        <div class="gc-loot-header">
          <div class="gc-loot-title gc-mono">${escapeHtml(t("inv_loot_modal_title", "Container geöffnet"))}</div>
          <div class="gc-loot-subtitle gc-mono rarity-${escapeHtml(containerRarity)}">${escapeHtml(containerName)}</div>
        </div>
        <div class="gc-loot-crate" aria-hidden="true"></div>
        <div class="gc-loot-roller">
          <div class="gc-loot-roller-rail" aria-hidden="true"></div>
          <div class="gc-loot-marker" aria-hidden="true"></div>
          <div class="gc-loot-strip">${buildLootRollTiles(payload)}</div>
        </div>
        <div class="gc-loot-status gc-mono">${escapeHtml(t("inv_loot_modal_status", "Wird geöffnet…"))}</div>
        <div class="gc-loot-results" hidden></div>
        <button type="button" class="gc-btn gc-btn-secondary gc-loot-skip">${escapeHtml(t("inv_loot_modal_skip", "Überspringen"))}</button>
      </div>`;

    root.appendChild(modal);
    document.body.classList.add("gc-loot-modal-open");

    const onKeydown = (ev) => {
      if (ev.key !== "Escape") return;
      if (_lootModalState?.revealed) {
        closeLootModal();
      } else if (typeof _lootModalState?.skip === "function") {
        _lootModalState.skip();
      }
    };
    document.addEventListener("keydown", onKeydown);

    _lootModalState = {
      payload,
      revealed: false,
      timerId: null,
      skip: null,
      onKeydown,
    };

    modal.addEventListener("click", (ev) => {
      const skipBtn = ev.target.closest(".gc-loot-skip");
      if (skipBtn && !skipBtn.hidden && typeof _lootModalState?.skip === "function") {
        _lootModalState.skip();
        return;
      }
      const closeBtn = ev.target.closest(".gc-loot-close");
      if (closeBtn && !closeBtn.disabled) {
        closeLootModal();
        return;
      }
      const toInv = ev.target.closest(".gc-loot-to-inventory");
      if (toInv) {
        closeLootModal();
        return;
      }
      const closeAction = ev.target.closest(".gc-loot-close-action");
      if (closeAction) {
        closeLootModal();
        return;
      }
      const openAgain = ev.target.closest(".gc-loot-open-again");
      if (openAgain) {
        const openPayload = { ..._lootModalState.payload };
        const itemKey = openPayload.container_key || openPayload.item_key;
        closeLootModal();
        const btn = document.querySelector(`[data-inventory-open="${CSS.escape(itemKey)}"][data-open-amount="1"]`)
          || document.querySelector(`[data-inventory-open="${CSS.escape(itemKey)}"]`);
        if (btn && !btn.disabled) btn.click();
      }
    });

    requestAnimationFrame(() => animateLootRoll(modal, payload));
  }

  GC.showLootOpeningModal = showLootOpeningModal;
  GC.revealLootRewards = revealLootRewards;
  GC.closeLootModal = closeLootModal;
  GC.playLootboxOpenSound = playLootboxOpenSound;

  function renderInventoryRewards(rewards) {
    const panel = document.getElementById("inventory-rewards-panel");
    const list = document.querySelector("[data-inventory-rewards-list]");
    if (!panel || !list) return;
    const rows = (rewards || []).filter((r) => (parseInt(r.amount, 10) || 0) > 0);
    if (!rows.length) {
      panel.hidden = true;
      list.innerHTML = "";
      return;
    }
    list.innerHTML = rows
      .map((r) => {
        const amt = parseInt(r.amount, 10) || 0;
        if (r.reward_type === "resource") {
          const label = inventoryResourceLabel(r.reward_key);
          return `<li class="inventory-reward-row inventory-reward-row--resource"><span class="inventory-reward-label">${escapeHtml(label)}</span><span class="inventory-reward-amount gc-mono">+${amt.toLocaleString()}</span></li>`;
        }
        if (r.reward_type === "ship" || r.reward_type === "defense") {
          const name = t(r.name_key || `${r.reward_type}_${r.reward_key}`, r.reward_key);
          const icon = r.reward_type === "ship" ? "🛰️" : "🛡️";
          return `<li class="inventory-reward-row inventory-reward-row--${escapeHtml(r.reward_type)}"><span class="inventory-reward-icon" aria-hidden="true">${icon}</span><span class="inventory-reward-label">${escapeHtml(name)}</span><span class="inventory-reward-amount gc-mono">+${amt.toLocaleString()}</span></li>`;
        }
        const name = t(r.name_key || `inv_item_${r.reward_key}`, r.reward_key);
        const rarity = t(`inv_rarity_${r.rarity || "common"}`, r.rarity || "common");
        const icon = r.icon || "📦";
        return `<li class="inventory-reward-row inventory-reward-row--item" data-rarity="${escapeHtml(r.rarity || "common")}"><span class="inventory-reward-icon" aria-hidden="true">${icon}</span><span class="inventory-reward-label">${escapeHtml(name)}</span><span class="inventory-rarity-badge inventory-rarity-badge--${escapeHtml(r.rarity || "common")}">${escapeHtml(rarity)}</span><span class="inventory-reward-amount gc-mono">×${amt.toLocaleString()}</span></li>`;
      })
      .join("");
    panel.hidden = false;
  }

  function patchInventoryDom(inventory) {
    const inv = inventory || {};
    const containers = inv.containers || [];
    const items = inv.other_items || [];

    document.querySelectorAll("[data-inventory-container]").forEach((card) => {
      const key = card.dataset.inventoryContainer;
      const row = containers.find((c) => c.item_key === key);
      const amount = row ? parseInt(row.amount, 10) || 0 : 0;
      const owned = amount > 0;
      const isBasic = key === "container_basic";
      const freeOpenReady = Boolean(isBasic && row && row.free_open_available);
      const amountEl = card.querySelector(`[data-inventory-amount="${key}"]`);
      if (amountEl) amountEl.textContent = String(amount);
      card.classList.toggle("inventory-loot-card--owned", owned);
      card.classList.toggle("inventory-loot-card--free-ready", freeOpenReady);
      card.classList.toggle("inventory-loot-card--empty", !owned && !freeOpenReady);
      card.hidden = false;
      const cooldownSeconds = row ? parseInt(row.cooldown_seconds, 10) || 0 : 0;
      const openBlocked = Boolean(row && row.open_blocked);
      const maxOpen = row ? parseInt(row.max_open_amount, 10) || 10 : 10;
      const hint = card.querySelector(".inventory-loot-card-hint");
      if (hint) {
        hint.dataset.cooldownSeconds = String(cooldownSeconds);
        if (owned) {
          hint.textContent = t("inv_card_owned_hint", "Bereit zum Öffnen");
        } else if (freeOpenReady) {
          hint.textContent = t("inv_basic_free_ready", "Gratis-Öffnung verfügbar");
        } else if (openBlocked && cooldownSeconds > 0) {
          hint.textContent = t("inv_basic_cooldown_active", "Cooldown aktiv — 1× alle 24 Stunden");
        } else {
          hint.textContent = t("inv_card_empty_hint", "Noch nicht im Besitz");
        }
      }
      const cooldownEl = card.querySelector("[data-inventory-cooldown]");
      if (cooldownEl) {
        cooldownEl.dataset.cooldownSeconds = String(cooldownSeconds);
        cooldownEl.hidden = false;
        cooldownEl.textContent = cooldownSeconds > 0
          ? `${t("inv_basic_cooldown_timer", "Gratis-Öffnung in")} ${formatCountdownRemain(cooldownSeconds)}`
          : t("inv_basic_cooldown_ready", "Jetzt verfügbar");
      }
      card.querySelectorAll("[data-inventory-open]").forEach((btn) => {
        const need = parseInt(btn.dataset.openAmount, 10) || 1;
        const overMax = need > maxOpen;
        if (isBasic && need === 1) {
          btn.disabled = (openBlocked && !owned) || overMax;
        } else {
          btn.disabled = !owned || openBlocked || amount < need || overMax;
        }
      });
    });

    const itemList = document.querySelector("[data-inventory-item-list]");
    if (!itemList) return;

    const emptyItems = itemList.querySelector("[data-inventory-empty-items]");
    if (emptyItems) emptyItems.hidden = items.length > 0;

    items.forEach((item) => {
      let row = itemList.querySelector(`[data-inventory-item="${item.item_key}"]`);
      if (!row) {
        row = document.createElement("li");
        row.className = "inventory-item-row";
        row.dataset.inventoryItem = item.item_key;
        row.dataset.rarity = item.rarity || "common";
        itemList.appendChild(row);
      }
      row.dataset.usable = item.usable ? "1" : "0";
      row.dataset.collectible = item.collectible ? "1" : "0";
      row.dataset.canCraft = item.can_craft ? "1" : "0";
      row.innerHTML = buildInventoryItemRowHtml(item);
      row.hidden = false;
    });

    itemList.querySelectorAll("[data-inventory-item]").forEach((row) => {
      const key = row.dataset.inventoryItem;
      if (!items.some((i) => i.item_key === key)) row.remove();
    });

    if (items.length === 0 && !itemList.querySelector("[data-inventory-empty-items]")) {
      const empty = document.createElement("li");
      empty.className = "inventory-empty";
      empty.dataset.inventoryEmptyItems = "";
      empty.textContent = t("inv_no_items", "Noch keine Items.");
      itemList.appendChild(empty);
    }
  }

  let _inventoryLastState = null;

  function bindInventoryOnce() {
    if (GC._inventoryEventsBound) return;
    GC._inventoryEventsBound = true;

    document.addEventListener("click", async (ev) => {
      const useBtn = ev.target.closest("[data-inventory-use]");
      if (useBtn && !useBtn.disabled) {
        const page = document.getElementById("inventory-page");
        if (!page || page.dataset.ready !== "1") return;
        const itemKey = useBtn.dataset.inventoryUse;
        if (!itemKey) return;
        useBtn.disabled = true;
        try {
          const res = await GC.fetchGameAction("/api/inventory/use-item", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
            body: JSON.stringify({
              item_key: itemKey,
              amount: 1,
              request_id: `inv-use-${itemKey}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            }),
          });
          if (res?.ok) {
            applyActionState(res, "inventory_use");
            renderInventoryEffect(res.effect || {});
            applyInventoryActionResult(res);
            void refreshInventoryFromServer();
          } else {
            const reason = res?.reason || "generic";
            console.warn("[GC] inventory use failed:", reason);
            showNotify(inventoryUseReasonText(reason), "error");
            patchInventoryDom(_inventoryLastState || parseInventoryPageState());
          }
        } catch (err) {
          console.warn("[GC] inventory use error", err);
          showNotify(inventoryUseReasonText("generic"), "error");
          patchInventoryDom(_inventoryLastState || parseInventoryPageState());
        } finally {
          const liveBtn = document.querySelector(`[data-inventory-use="${CSS.escape(itemKey)}"]`);
          if (liveBtn) liveBtn.disabled = false;
        }
        return;
      }

      const craftBtn = ev.target.closest("[data-inventory-craft]");
      if (craftBtn && !craftBtn.disabled) {
        const page = document.getElementById("inventory-page");
        if (!page || page.dataset.ready !== "1") return;
        const recipeKey = craftBtn.dataset.inventoryCraft;
        if (!recipeKey) return;
        craftBtn.disabled = true;
        try {
          const res = await GC.fetchGameAction("/api/inventory/craft", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
            body: JSON.stringify({
              recipe_key: recipeKey,
              amount: 1,
              request_id: `inv-craft-${recipeKey}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            }),
          });
          if (res?.ok) {
            applyActionState(res, "inventory_craft");
            renderInventoryEffect(res.effect || {});
            applyInventoryActionResult(res);
            void refreshInventoryFromServer();
          } else {
            const reason = res?.reason || "generic";
            console.warn("[GC] inventory craft failed:", reason);
            showNotify(inventoryUseReasonText(reason), "error");
            patchInventoryDom(_inventoryLastState || parseInventoryPageState());
          }
        } catch (err) {
          console.warn("[GC] inventory craft error", err);
          showNotify(inventoryUseReasonText("generic"), "error");
          patchInventoryDom(_inventoryLastState || parseInventoryPageState());
        } finally {
          const liveBtn = document.querySelector(`[data-inventory-craft="${CSS.escape(recipeKey)}"]`);
          if (liveBtn) liveBtn.disabled = false;
        }
        return;
      }

      const openBtn = ev.target.closest("[data-inventory-open]");
      if (!openBtn || openBtn.disabled) return;
      const page = document.getElementById("inventory-page");
      if (!page || page.dataset.ready !== "1") return;

      const itemKey = openBtn.dataset.inventoryOpen;
      const amount = parseInt(openBtn.dataset.openAmount, 10) || 1;
      if (!itemKey) return;

      page.querySelectorAll("[data-inventory-open]").forEach((btn) => {
        btn.disabled = true;
      });

      try {
        const res = await GC.fetchGameAction("/api/inventory/open-container", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          body: JSON.stringify({
            item_key: itemKey,
            amount,
            request_id: `inv-open-${itemKey}-${amount}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          }),
        });
        if (res?.ok) {
          showLootOpeningModal({
            ...res,
            item_key: itemKey,
            consumed: res.opened || amount,
            _deferredState: res.state,
            _deferredInventory: res.inventory,
          });
        } else {
          const reason = res?.reason || "generic";
          console.warn("[GC] inventory open failed:", reason);
          showNotify(inventoryUseReasonText(reason), "error");
          patchInventoryDom(_inventoryLastState || parseInventoryPageState());
          page.querySelectorAll("[data-inventory-open]").forEach((btn) => {
            btn.disabled = false;
          });
        }
      } catch (err) {
        console.warn("[GC] inventory open error", err);
        showNotify(inventoryUseReasonText("generic"), "error");
        patchInventoryDom(_inventoryLastState || parseInventoryPageState());
        page.querySelectorAll("[data-inventory-open]").forEach((btn) => {
          btn.disabled = false;
        });
      }
    });

    document.addEventListener("click", (ev) => {
      const closeBtn = ev.target.closest("[data-inventory-rewards-close]");
      if (!closeBtn) return;
      const panel = document.getElementById("inventory-rewards-panel");
      if (panel) panel.hidden = true;
    });
  }

  function tickInventoryCooldowns() {
    document.querySelectorAll("[data-inventory-cooldown]").forEach((el) => {
      let sec = parseInt(el.dataset.cooldownSeconds, 10) || 0;
      const card = el.closest("[data-inventory-container]");
      if (sec <= 0) {
        el.textContent = t("inv_basic_cooldown_ready", "Jetzt verfügbar");
        if (card && card.dataset.inventoryContainer === "container_basic") {
          const amountEl = card.querySelector('[data-inventory-amount="container_basic"]');
          const amount = amountEl ? parseInt(amountEl.textContent, 10) || 0 : 0;
          const hint = card.querySelector(".inventory-loot-card-hint");
          const openBtn = card.querySelector('[data-inventory-open][data-open-amount="1"]');
          if (amount <= 0) {
            card.classList.add("inventory-loot-card--free-ready");
            card.classList.remove("inventory-loot-card--empty");
            if (hint) hint.textContent = t("inv_basic_free_ready", "Gratis-Öffnung verfügbar");
            if (openBtn) openBtn.disabled = false;
          }
        }
        return;
      }
      sec = Math.max(0, sec - 1);
      el.dataset.cooldownSeconds = String(sec);
      el.textContent = `${t("inv_basic_cooldown_timer", "Gratis-Öffnung in")} ${formatCountdownRemain(sec)}`;
    });
  }

  function initInventory() {
    bindInventoryOnce();
    syncTradingSubnav("inventory");
    const page = document.getElementById("inventory-page");
    if (!page || page.dataset.ready !== "1") return;
    _inventoryLastState = parseInventoryPageState();
    patchInventoryDom(_inventoryLastState);
    GC.setSafeInterval(tickInventoryCooldowns, 1000);
    GC.registerCleanup(() => {
      closeLootModal();
      const panel = document.getElementById("inventory-rewards-panel");
      if (panel) panel.hidden = true;
    });
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

      const urlMission = page.dataset.fleetUrlMission || "";
      if (
        isExpoSlot &&
        missionSel &&
        missionSel.value !== "expedition" &&
        !urlMission
      ) {
        missionSel.value = "expedition";
        const colonizeRow = page.querySelector("[data-fleet-colonize-row]");
        if (colonizeRow) colonizeRow.hidden = true;
        if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(missionSel);
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

    const setColonizeRowVisible = (page, mission) => {
      const colonizeRow = page.querySelector("[data-fleet-colonize-row]");
      if (colonizeRow) colonizeRow.hidden = mission !== "colonize";
    };

    const syncMissionAllowlistFromTarget = (page, target) => {
      const sel = page.querySelector("[data-fleet-mission]");
      if (!sel || !target) return;
      const allowed = new Set(target.allowed_missions || []);
      const urlMission = String(page.dataset.fleetUrlMission || "").trim().toLowerCase();
      const prevValue = sel.value;
      let currentOk = true;
      Array.from(sel.options).forEach((opt) => {
        const ok = allowed.size === 0 || allowed.has(opt.value);
        opt.disabled = !ok;
        if (opt.value === sel.value) currentOk = ok;
      });
      if (!currentOk) {
        if (urlMission && allowed.has(urlMission)) {
          sel.value = urlMission;
        } else {
          if (urlMission && !allowed.has(urlMission)) {
            delete page.dataset.fleetUrlMission;
          }
          const first = Array.from(sel.options).find((o) => !o.disabled);
          if (first) sel.value = first.value;
        }
      }
      if (typeof GC.rebuildHudSelect === "function") GC.rebuildHudSelect(sel);
      else if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(sel);
      if (sel.value !== prevValue) {
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      }
    };

    const formatDebrisPreview = (debris) => {
      const metal = Math.max(0, parseInt(debris?.metal || 0, 10));
      const crystal = Math.max(0, parseInt(debris?.crystal || 0, 10));
      if (!metal && !crystal) {
        return tt("fleet_preview_no_debris", "No debris at target");
      }
      return tt(
        "fleet_preview_debris_amounts",
        "Metal %(metal)s · Crystal %(crystal)s",
        { metal: fmtNumber(metal), crystal: fmtNumber(crystal) }
      );
    };

    const updateFleetFormMode = (page) => {
      const form = getForm(page);
      if (!form) return;
      const mission = form.querySelector("[data-fleet-mission]")?.value || "transport";
      const resFieldset = page.querySelector("[data-fleet-resources-fieldset]");
      const showResources = ["transport", "deploy", "colonize", "collect"].includes(mission);
      if (resFieldset) resFieldset.hidden = !showResources;
      setColonizeRowVisible(page, mission);
      page.querySelectorAll(".fleet-ship-row[data-ship-role='recycle']").forEach((row) => {
        row.classList.toggle("fleet-ship-row--mission-focus", mission === "recycle");
      });
      const debrisRow = page.querySelector("[data-preview-debris-row]");
      if (debrisRow) debrisRow.hidden = mission !== "recycle";
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

      if (mission === "recycle") {
        const reclaimers = countShipsByRole(page, ships, "recycle");
        const debris = target.debris || {};
        const dm = Math.max(0, parseInt(debris.metal || 0, 10));
        const dc = Math.max(0, parseInt(debris.crystal || 0, 10));
        if (dm + dc <= 0) {
          hints.push({ tone: "warn", text: formatMissionHint("fleet_mission_hint_recycle_no_debris") });
        } else if (reclaimers <= 0) {
          hints.push({ tone: "warn", text: formatMissionHint("fleet_mission_hint_recycle_no_ship") });
        } else {
          hints.push({
            tone: "ok",
            text: formatMissionHint("fleet_mission_hint_recycle_ready", {
              metal: fmtNumber(dm),
              crystal: fmtNumber(dc),
              ships: reclaimers,
            }),
          });
        }
        hints.push({ tone: "info", text: formatMissionHint("fleet_mission_hint_recycle") });
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

    const fleetLegKey = (mv, phase) => mv.status_label || mv.leg_label_key || (
      phase === "returning"
        ? "fleet_leg_returning"
        : phase === "holding"
          ? "fleet_leg_holding"
          : "fleet_leg_outbound"
    );

    const fleetCountdownHtml = (mv) => {
      const countdownAt = Number(mv.countdown_at || 0);
      const phase = mv.phase || mv.leg_phase || mv.status || "";
      const legLabel = tt(fleetLegKey(mv, phase), fleetLegKey(mv, phase));
      const countdownKey = `${mv.id}:${phase}:${countdownAt}`;
      const srvRem = Number(mv.remaining_seconds);
      const srvAttr = Number.isFinite(srvRem) && srvRem >= 0 ? ` data-server-remaining="${Math.ceil(srvRem)}"` : "";
      if (!countdownAt) return "";
      return `<span class="fleet-active-leg">${legLabel}: <time class="fleet-active-countdown gc-mono" data-timer-target="${countdownAt}" data-timer-kind="fleet" data-refresh-on-zero="fleet" data-countdown-at="${countdownAt}" data-countdown-scope="fleet" data-countdown-key="${countdownKey}"${srvAttr}>–</time></span>`;
    };

    const patchActiveFleetCards = (page, list) => {
      list.forEach((mv) => {
        const card = page.querySelector(`[data-fleet-id="${mv.id}"]`);
        if (!card) return;
        const phase = mv.phase || mv.leg_phase || mv.status || "";
        const mission = String(mv.mission_type || "custom");
        card.dataset.status = String(mv.status || "");
        card.dataset.leg = phase;
        card.dataset.mission = mission;
        card.className = `fleet-active-card fleet-active-card--${mission}`;
        const statusEl = card.querySelector(".fleet-active-status");
        if (statusEl) _setIfChanged(statusEl, tt(`fleet_status_${mv.status}`, mv.status));
        const missionEl = card.querySelector(".fleet-active-mission");
        if (missionEl) {
          missionEl.className = `fleet-active-mission fleet-active-mission--${mission}`;
          _setIfChanged(missionEl, tt(`fleet_mission_${mv.mission_type}`, mv.mission_type));
        }
        const timesEl = card.querySelector(".fleet-active-times");
        if (!timesEl) return;
        const countdownAt = Number(mv.countdown_at || 0);
        const cdEl = timesEl.querySelector("[data-countdown-at]");
        const legKey = fleetLegKey(mv, phase);
        const legChanged = !cdEl
          || card.dataset.leg !== phase
          || Number(cdEl.dataset.countdownAt || 0) !== countdownAt
          || String(cdEl.dataset.countdownKey || "") !== `${mv.id}:${phase}:${countdownAt}`;
        if (legChanged) {
          timesEl.innerHTML = fleetCountdownHtml(mv);
        } else if (cdEl) {
          const srvRem = Number(mv.remaining_seconds);
          if (Number.isFinite(srvRem) && srvRem >= 0) {
            assignMonotonicServerRemaining(cdEl, Math.ceil(srvRem), countdownAt);
          } else {
            delete cdEl.dataset.serverRemaining;
          }
          _setIfChanged(
            cdEl,
            formatCountdownRemain(movementRemainingSeconds(countdownAt, getTimerServerNow(), mv.remaining_seconds))
          );
        }
      });
    };

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

      const signature = list.map((mv) => (
        `${mv.id}:${mv.status}:${mv.phase || mv.leg_phase || ""}:${mv.countdown_at || 0}`
      )).join("|");
      const sigChanged = activeListEl.dataset.fleetSig !== signature;
      if (sigChanged) {
        activeListEl.dataset.fleetSig = signature;
        _clearMovementCountdownExpiryState();
        activeListEl.innerHTML = list.map((mv) => {
        const countdownAt = Number(mv.countdown_at || 0);
        const phase = mv.phase || mv.leg_phase || mv.status || "";
        const mission = String(mv.mission_type || "custom");
        const countdown = fleetCountdownHtml(mv);
        const cargo = [];
        if (mv.resources?.metal) cargo.push(`${tt("resource_metal")}: ${Number(mv.resources.metal).toLocaleString()}`);
        if (mv.resources?.crystal) cargo.push(`${tt("resource_crystal")}: ${Number(mv.resources.crystal).toLocaleString()}`);
        if (mv.resources?.fuel_cells) cargo.push(`${tt("resource_fuel_cells")}: ${Number(mv.resources.fuel_cells).toLocaleString()}`);
        return `<article class="fleet-active-card fleet-active-card--${mission}" data-fleet-id="${mv.id}" data-status="${mv.status}" data-mission="${mission}" data-leg="${phase}">
          <div class="fleet-active-row">
            <span class="fleet-active-mission fleet-active-mission--${mission}">${tt(`fleet_mission_${mv.mission_type}`, mv.mission_type)}</span>
            <span class="fleet-active-status">${tt(`fleet_status_${mv.status}`, mv.status)}</span>
          </div>
          <div class="fleet-active-coords gc-mono">${GC.coordRouteHtml(mv.origin_coords, mv.target_coords)}</div>
          <div class="fleet-active-ships">${renderShipChips(mv.ships)}</div>
          ${cargo.length ? `<div class="fleet-active-cargo">${cargo.map((c) => `<span>${c}</span>`).join(" ")}</div>` : ""}
          <div class="fleet-active-times gc-mono">${countdown}</div>
        </article>`;
        }).join("");
      } else {
        patchActiveFleetCards(page, list);
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

    const syncColonyChipsFromCoords = (page) => {
      const form = getForm(page);
      if (!form) return;
      const g = parseInt(form.querySelector('[name="target_galaxy"]')?.value || "0", 10);
      const s = parseInt(form.querySelector('[name="target_system"]')?.value || "0", 10);
      const p = parseInt(form.querySelector('[name="target_position"]')?.value || "0", 10);
      const mission = form.querySelector("[data-fleet-mission]")?.value || "";
      page.querySelectorAll(".fleet-colony-chip").forEach((chip) => {
        const cg = parseInt(chip.getAttribute("data-galaxy") || chip.dataset.galaxy || "0", 10);
        const cs = parseInt(chip.getAttribute("data-system") || chip.dataset.system || "0", 10);
        const cp = parseInt(chip.getAttribute("data-position") || chip.dataset.position || "0", 10);
        const chipMission = chip.getAttribute("data-mission") || chip.dataset.mission || "";
        const coordMatch = cg === g && cs === s && cp === p;
        const missionMatch = !chipMission || !mission || chipMission === mission;
        chip.classList.toggle("is-selected", coordMatch && missionMatch);
      });
    };

    const applyLiveState = (page, state, opts) => {
      const rt = getFleetRuntime(page);
      if (!state || typeof state !== "object") return;
      const seq = Number(opts?.seq || 0);
      if (seq > 0) {
        const last = Number(page._fleetApplySeq || 0);
        if (seq < last) return;
        page._fleetApplySeq = seq;
      }
      const st = Number(state.server_time || 0);
      if (st) {
        const lastSt = Number(page._fleetLiveServerTime || 0);
        if (lastSt && st < lastSt - 1) return;
        page._fleetLiveServerTime = Math.max(lastSt, st);
      }
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
      if (Array.isArray(state.active_fleets)) {
        rt.data.active_fleets = state.active_fleets;
        renderActiveFleets(page, state.active_fleets);
      }
      if (state.presets) {
        rt.data.presets = state.presets;
        renderPresetList(page, state.presets);
        renderPresetSelect(page, state.presets);
      }
    };

    const refreshFleetState = async (page) => {
      const seq = ++_fleetRefreshSeq;
      try {
        const rt = getFleetRuntime(page);
        let planetId = parseInt(page.dataset.planetId || rt.data?.planet_id || "0", 10);
        if (!planetId) {
          planetId = Number(GC.lastState?.active_planet_id || 0);
        }
        const q = planetId ? `?planet_id=${planetId}` : "";
        const res = await GC.fetchJSON(`/api/fleet/state${q}`, { cache: "no-store" });
        if (res?.ok) applyLiveState(page, fleetPayload(res), { seq });
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
          const debrisRow = page.querySelector("[data-preview-debris-row]");
          const previewDebris = page.querySelector("[data-preview-debris]");
          if (debrisRow && previewDebris) {
            const showDebris = missionType === "recycle";
            debrisRow.hidden = !showDebris;
            if (showDebris) previewDebris.textContent = formatDebrisPreview(target.debris);
          }
          syncMissionAllowlistFromTarget(page, target);
          updateFleetFormMode(page);
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
            const arrivalAt = Number(p.countdown_at || p.arrival_at || 0);
            if (arrivalAt > 0) {
              previewArrival.dataset.countdownAt = String(arrivalAt);
              const nowSec = getApproxServerNow();
              previewArrival.textContent = formatCountdownRemain(Math.max(0, Math.ceil(arrivalAt - nowSec)));
              GC.startProgressTicker();
            } else {
              delete previewArrival.dataset.countdownAt;
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

    const pickDefaultFleetTargetIfNeeded = (page) => {
      const params = new URLSearchParams(window.location.search);
      if (
        params.has("target_galaxy")
        && params.has("target_system")
        && params.has("target_position")
      ) {
        return;
      }
      const rt = getFleetRuntime(page);
      const origin = rt.data?.coordinates || {};
      const target = getTargetCoords(page);
      const og = parseInt(origin.galaxy, 10);
      const os = parseInt(origin.system, 10);
      const op = parseInt(origin.position, 10);
      if (
        og !== target.target_galaxy
        || os !== target.target_system
        || op !== target.target_position
      ) {
        return;
      }
      const altColony = page.querySelector(
        ".fleet-colony-chip:not(.fleet-colony-chip--expedition):not(.is-active)"
      );
      if (altColony) {
        applyQuickTarget(page, altColony);
        return;
      }
      const expo = page.querySelector(".fleet-colony-chip--expedition");
      if (expo) applyQuickTarget(page, expo);
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
        setColonizeRowVisible(page, mission);
      } else if (ms && ms.value === "expedition") {
        ms.value = "transport";
        GC.syncHudSelect(ms);
        setColonizeRowVisible(page, "transport");
      }
      delete page.dataset.fleetUrlMission;
      page.querySelectorAll(".fleet-colony-chip").forEach((c) => c.classList.remove("is-selected"));
      chip.classList.add("is-selected");
      syncExpeditionMissionTarget(page);
      schedulePreview(page);
    };

    GC.scheduleFleetPreview = schedulePreview;
    GC.syncColonyChipsFromCoords = syncColonyChipsFromCoords;
    GC.syncExpeditionMissionTarget = syncExpeditionMissionTarget;
    GC.updateFleetFormMode = updateFleetFormMode;
    GC.refreshFleetState = refreshFleetState;
    GC.runFleetPreview = runPreview;
    GC.applyFleetUrlPrefill = applyFleetUrlPrefill;
    GC.pickDefaultFleetTargetIfNeeded = pickDefaultFleetTargetIfNeeded;

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
        delete page.dataset.fleetUrlMission;
        setColonizeRowVisible(page, e.target.value);
        if (e.target.value === "expedition") applyExpeditionTarget(page);
        syncExpeditionMissionTarget(page);
        updateFleetFormMode(page);
        schedulePreview(page);
      }
      if (e.target.matches('[name="target_galaxy"], [name="target_system"], [name="target_position"]')) {
        delete page.dataset.fleetUrlMission;
        syncExpeditionMissionTarget(page);
      }
      if (e.target.closest("#fleet-send-form")) schedulePreview(page);
    });

    document.addEventListener("input", (e) => {
      const page = getPage();
      if (!page) return;
      if (e.target.matches('[name="target_galaxy"], [name="target_system"], [name="target_position"]')) {
        delete page.dataset.fleetUrlMission;
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
          await runPreview(page);
        }
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

  let _logisticsBound = false;
  const _logisticsPreviewTimers = new WeakMap();

  const tt = (key, fallback) => t(key, fallback);
  const apiError = (res) => (res && (res.error || res.reason)) || "generic";

  const logisticsPayload = (res) =>
    (res && res.data && typeof res.data === "object" ? res.data : res) || {};

  const logisticsReasonText = (reason) => {
    if (!reason) return tt("fleet_error_generic");
    const key = String(reason);
    const prefixed = tt(`fleet_error_${key}`, "");
    if (prefixed && prefixed !== `fleet_error_${key}`) return prefixed;
    const direct = tt(key, "");
    if (direct && direct !== key) return direct;
    return tt("fleet_error_generic");
  };

  function notifyLogisticsFailure(page, mode, message) {
    showLogisticsError(page, mode, message);
    showNotify(message, "error");
  }

  function clampLogisticsShipInput(inp) {
    if (!inp) return;
    const max = parseInt(inp.max || "0", 10);
    let v = parseInt(inp.value || "0", 10);
    if (!Number.isFinite(v) || v < 0) v = 0;
    if (Number.isFinite(max) && max >= 0 && v > max) v = max;
    inp.value = String(v);
  }

  function logisticsSubmitEnabled(page, mode) {
    if (!logisticsFormReady(page, mode)) return false;
    const preview = page._logisticsLastPreview;
    if (!preview || preview.mode !== mode) return false;
    return !!preview.can_launch;
  }

  function syncLogisticsColonyLaunchHints(page, preview) {
    const launchIds = new Set(
      (preview?.legs || []).map((leg) => parseInt(leg.planet_id, 10)).filter(Boolean)
    );
    page.querySelectorAll(".logistics-colony-card").forEach((card) => {
      if (card.hidden) {
        card.classList.remove("is-slots-skipped");
        return;
      }
      const cb = card.querySelector("[data-logistics-colony-cb]");
      const pid = parseInt(card.getAttribute("data-colony-planet-id"), 10);
      const checked = !!(cb && cb.checked);
      card.classList.toggle("is-slots-skipped", checked && launchIds.size > 0 && !launchIds.has(pid));
    });
  }

  async function refreshLogisticsLiveState(page) {
    if (!page || page.dataset.ready !== "1") return;
    try {
      const originId = getLogisticsOriginId(page);
      const q = originId ? `?planet_id=${originId}` : "";
      const res = await GC.fetchJSON(`/api/fleet/state${q}`, { cache: "no-store" });
      if (!res?.ok) return;
      const payload = logisticsPayload(res);
      const slots = payload.active_slots || payload.fleet_slots;
      if (slots) updateLogisticsFleetSlotsBadge(page, slots);
      const data = parseLogisticsPageData(page);
      if (data && payload.planet_id && payload.ships) {
        const hubId = parseInt(payload.planet_id, 10);
        const hub = getLogisticsColonyById(data, hubId);
        if (hub) hub.ships = payload.ships;
        data.ships = payload.ships;
        const stateEl = page.querySelector("#logistics-page-state");
        if (stateEl) stateEl.textContent = JSON.stringify(data);
        updateLogisticsOriginShips(page, data);
      } else {
        scheduleLogisticsPreview(page);
      }
    } catch (_) {}
  }

  function scheduleLogisticsRefreshFromState() {
    const page = document.getElementById("logistics-page");
    if (!page || page.dataset.ready !== "1") return;
    if (page._logisticsLivePending) return;
    page._logisticsLivePending = true;
    queueMicrotask(async () => {
      page._logisticsLivePending = false;
      await refreshLogisticsLiveState(page);
    });
  }

  GC.scheduleLogisticsRefreshFromState = scheduleLogisticsRefreshFromState;

  function parseLogisticsPageData(page) {
    const el = page.querySelector("#logistics-page-state");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || "{}");
    } catch (_) {
      return null;
    }
  }

  function getLogisticsColonyById(data, planetId) {
    const id = parseInt(planetId, 10);
    if (!data?.colonies || !id) return null;
    return data.colonies.find((c) => parseInt(c.planet_id, 10) === id) || null;
  }

  function getLogisticsMode(page) {
    return String(page?.dataset?.logisticsMode || "collect").toLowerCase();
  }

  function setLogisticsMode(page, mode) {
    const m = mode === "distribute" ? "distribute" : "collect";
    page.dataset.logisticsMode = m;
    page.querySelectorAll("[data-logistics-tab]").forEach((btn) => {
      const active = btn.getAttribute("data-logistics-tab") === m;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    page.querySelectorAll("[data-logistics-panel]").forEach((panel) => {
      const show = panel.getAttribute("data-logistics-panel") === m;
      panel.hidden = !show;
    });
    clearLogisticsError(page);
    scheduleLogisticsPreview(page);
  }

  function getLogisticsOriginId(page) {
    const sel = page.querySelector("[data-logistics-origin]");
    return sel ? parseInt(sel.value, 10) : 0;
  }

  function getLogisticsShipsSelection(page, mode) {
    const ships = {};
    const grid = page.querySelector(`[data-logistics-ships-grid="${mode}"]`);
    if (!grid) return ships;
    grid.querySelectorAll("[data-logistics-ship-input]").forEach((inp) => {
      const key = inp.getAttribute("data-logistics-ship-input");
      const qty = parseInt(inp.value || "0", 10);
      if (key && qty > 0) ships[key] = qty;
    });
    return ships;
  }

  function getLogisticsResourcesSelection(page) {
    const resources = { metal: 0, crystal: 0, fuel_cells: 0 };
    page.querySelectorAll("[data-logistics-resource]").forEach((inp) => {
      const key = inp.getAttribute("data-logistics-resource");
      if (!key) return;
      resources[key] = Math.max(0, parseInt(inp.value || "0", 10) || 0);
    });
    return resources;
  }

  function getLogisticsSelectedColonyIds(page, mode) {
    const ids = [];
    page.querySelectorAll(`[data-logistics-colony-cb="${mode}"]:checked`).forEach((cb) => {
      const card = cb.closest("[data-colony-planet-id]");
      if (card && !card.hidden) ids.push(parseInt(cb.value, 10));
    });
    return ids;
  }

  function updateLogisticsOriginShips(page, data) {
    const originId = getLogisticsOriginId(page);
    const colony = getLogisticsColonyById(data, originId);
    const stock = colony?.ships || {};
    page.querySelectorAll("[data-logistics-ships-grid]").forEach((grid) => {
      grid.querySelectorAll("[data-ship-key]").forEach((row) => {
        const key = row.getAttribute("data-ship-key");
        const have = parseInt(stock[key] || "0", 10) || 0;
        row.dataset.shipHave = String(have);
        row.classList.toggle("is-empty", have <= 0);
        const stockEl = row.querySelector("[data-logistics-ship-stock]");
        if (stockEl) stockEl.textContent = `×${fmtNumber(have)}`;
        const inp = row.querySelector("[data-logistics-ship-input]");
        if (inp) {
          inp.max = String(have);
          if (parseInt(inp.value || "0", 10) > have) inp.value = String(have);
        }
      });
    });
    syncLogisticsColonyVisibility(page, originId);
    syncLogisticsColonySelected(page);
    scheduleLogisticsPreview(page);
  }

  function syncLogisticsColonyVisibility(page, originId) {
    const hub = parseInt(originId, 10);
    page.querySelectorAll("[data-colony-planet-id]").forEach((li) => {
      const pid = parseInt(li.getAttribute("data-colony-planet-id"), 10);
      const isHub = pid === hub;
      li.hidden = isHub;
      if (isHub) {
        const cb = li.querySelector("[data-logistics-colony-cb]");
        if (cb) cb.checked = false;
        li.classList.remove("is-selected");
      }
    });
  }

  function syncLogisticsColonySelected(page) {
    page.querySelectorAll(".logistics-colony-card").forEach((card) => {
      const cb = card.querySelector("[data-logistics-colony-cb]");
      card.classList.toggle("is-selected", !!(cb && cb.checked && !card.hidden));
    });
  }

  function updateLogisticsFleetSlotsBadge(page, slots) {
    if (!slots) return;
    const el = page.querySelector("[data-logistics-fleet-slots]");
    if (el) {
      el.textContent = `${parseInt(slots.active, 10) || 0} / ${parseInt(slots.max, 10) || 0}`;
    }
    const freeEl = page.querySelector(".logistics-slots-free");
    if (freeEl && slots.free !== undefined) {
      const freeLabel = tt("logistics_slots_free");
      freeEl.textContent = `${freeLabel}: ${fmtNumber(parseInt(slots.free, 10) || 0)}`;
    }
    const data = parseLogisticsPageData(page);
    if (data) data.fleet_slots = slots;
  }

  function clearLogisticsError(page, mode) {
    const m = mode || getLogisticsMode(page);
    const errorEl = page.querySelector(`[data-logistics-error="${m}"]`);
    if (errorEl) {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }
  }

  function showLogisticsError(page, mode, message) {
    const errorEl = page.querySelector(`[data-logistics-error="${mode}"]`);
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.hidden = false;
    }
  }

  function logisticsFormReady(page, mode) {
    const m = mode || getLogisticsMode(page);
    const originId = getLogisticsOriginId(page);
    const colonyIds = getLogisticsSelectedColonyIds(page, m);
    const ships = getLogisticsShipsSelection(page, m);
    const shipTotal = Object.values(ships).reduce((a, b) => a + b, 0);
    if (!originId || !colonyIds.length || !shipTotal) return false;
    if (m === "distribute") {
      const res = getLogisticsResourcesSelection(page);
      if ((res.metal || 0) + (res.crystal || 0) + (res.fuel_cells || 0) <= 0) return false;
    }
    return true;
  }

  function updateLogisticsSubmitButtons(page) {
    const mode = getLogisticsMode(page);
    page.querySelectorAll("[data-logistics-submit]").forEach((btn) => {
      const btnMode = btn.getAttribute("data-logistics-submit");
      btn.disabled = btnMode !== mode || !logisticsSubmitEnabled(page, btnMode);
    });
  }

  function resetLogisticsPreview(page, hintKey) {
    page._logisticsLastPreview = null;
    const hud = page.querySelector("[data-logistics-preview]");
    if (hud) {
      hud.classList.remove("is-ready", "is-blocked");
    }
    const statusEl = page.querySelector("[data-logistics-preview-status]");
    if (statusEl) {
      statusEl.textContent = hintKey ? tt(hintKey) : "–";
      statusEl.classList.remove("is-ok", "is-blocked");
      if (hintKey) statusEl.classList.add("is-blocked");
    }
    ["flight", "cargo", "slots", "fuel"].forEach((key) => {
      const el = page.querySelector(`[data-logistics-preview-${key}]`);
      if (el) el.textContent = "–";
    });
    const targetsWrap = page.querySelector("[data-logistics-preview-targets]");
    const targetsList = page.querySelector("[data-logistics-preview-targets-list]");
    if (targetsWrap) targetsWrap.hidden = true;
    if (targetsList) targetsList.innerHTML = "";
    syncLogisticsColonyLaunchHints(page, null);
    updateLogisticsSubmitButtons(page);
  }

  function renderLogisticsPreview(page, preview) {
    const hud = page.querySelector("[data-logistics-preview]");
    const statusEl = page.querySelector("[data-logistics-preview-status]");
    const flightEl = page.querySelector("[data-logistics-preview-flight]");
    const cargoEl = page.querySelector("[data-logistics-preview-cargo]");
    const slotsEl = page.querySelector("[data-logistics-preview-slots]");
    const fuelEl = page.querySelector("[data-logistics-preview-fuel]");
    const targetsWrap = page.querySelector("[data-logistics-preview-targets]");
    const targetsList = page.querySelector("[data-logistics-preview-targets-list]");

    if (!preview || !Object.keys(preview).length) {
      resetLogisticsPreview(page);
      return;
    }

    page._logisticsLastPreview = { ...preview, mode: getLogisticsMode(page) };

    const canLaunch = !!preview.can_launch;
    const blockReason = preview.block_reason || "";
    clearLogisticsError(page, getLogisticsMode(page));
    if (hud) {
      hud.classList.toggle("is-ready", canLaunch);
      hud.classList.toggle("is-blocked", !canLaunch);
    }
    if (statusEl) {
      statusEl.classList.remove("is-ok", "is-blocked");
      const skipped = parseInt(preview.targets_skipped || "0", 10) || 0;
      if (canLaunch) {
        if (skipped > 0) {
          statusEl.textContent = tt("logistics_preview_slots_capped", "")
            .replace("%(launching)s", String(preview.targets_launching || (preview.legs || []).length))
            .replace("%(selected)s", String(preview.targets_selected || 0))
            .replace("%(skipped)s", String(skipped));
        } else {
          statusEl.textContent = tt("logistics_preview_ready");
        }
        statusEl.classList.add("is-ok");
      } else {
        statusEl.textContent = blockReason
          ? logisticsReasonText(blockReason)
          : tt("logistics_preview_incomplete");
        statusEl.classList.add("is-blocked");
      }
    }
    if (flightEl) {
      flightEl.textContent = formatCountdownRemain(preview.max_flight_seconds || 0);
    }
    if (cargoEl) {
      cargoEl.textContent = `${preview.cargo_used || 0} / ${preview.cargo_total || 0}`;
    }
    if (slotsEl) {
      const fs = preview.fleet_slots || {};
      slotsEl.textContent = `${preview.slots_needed || 0} ${tt("logistics_preview_slots_of")} ${fs.free ?? 0} ${tt("logistics_slots_free")}`;
    }
    if (fuelEl) {
      fuelEl.textContent = String(preview.total_fuel_cost || 0);
    }
    if (targetsWrap && targetsList) {
      const legs = preview.legs || [];
      if (legs.length) {
        targetsWrap.hidden = false;
        targetsList.innerHTML = legs
          .map((leg) => {
            const res = leg.resources;
            const cargoTxt = res
              ? ` — ${(res.metal || 0)}/${(res.crystal || 0)}/${(res.fuel_cells || 0)}`
              : "";
            return `<li class="logistics-preview-target-item"><span class="logistics-preview-target-name">${escapeHtml(leg.name || "")}</span> <span class="gc-mono logistics-preview-target-coords">${escapeHtml(leg.coordinates || "")}</span><span class="logistics-preview-target-meta gc-mono">${formatCountdownRemain(leg.flight_seconds || 0)}${cargoTxt}</span></li>`;
          })
          .join("");
      } else {
        targetsWrap.hidden = true;
        targetsList.innerHTML = "";
      }
    }
    syncLogisticsColonyLaunchHints(page, preview);
    updateLogisticsSubmitButtons(page);
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function buildLogisticsPreviewBody(page) {
    const mode = getLogisticsMode(page);
    const originId = getLogisticsOriginId(page);
    const ships = getLogisticsShipsSelection(page, mode);
    const body = {
      mode,
      origin_planet_id: originId,
      target_planet_id: originId,
      ships,
      speed_percent: 100,
      ships_selection_mode: "manual",
    };
    if (mode === "collect") {
      body.source_planet_ids = getLogisticsSelectedColonyIds(page, "collect");
      body.resources_mode = "all";
    } else {
      body.target_planet_ids = getLogisticsSelectedColonyIds(page, "distribute");
      body.resources = getLogisticsResourcesSelection(page);
      body.resources_mode = "equal";
    }
    return body;
  }

  async function refreshLogisticsPreview(page) {
    const mode = getLogisticsMode(page);
    const originId = getLogisticsOriginId(page);
    const ships = getLogisticsShipsSelection(page, mode);
    const colonyIds = getLogisticsSelectedColonyIds(page, mode);
    const shipTotal = Object.values(ships).reduce((a, b) => a + b, 0);

    if (!originId || !colonyIds.length || !shipTotal) {
      if (!colonyIds.length && originId && shipTotal) {
        resetLogisticsPreview(page, "logistics_preview_select_colonies");
      } else if (!shipTotal && originId && colonyIds.length) {
        resetLogisticsPreview(page, "logistics_preview_select_ships");
      } else {
        resetLogisticsPreview(page);
      }
      return;
    }
    if (mode === "distribute") {
      const res = getLogisticsResourcesSelection(page);
      if ((res.metal || 0) + (res.crystal || 0) + (res.fuel_cells || 0) <= 0) {
        resetLogisticsPreview(page, "logistics_distribute_no_resources");
        return;
      }
    }

    try {
      const res = await GC.fetchJSON("/api/fleet/logistics/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify(buildLogisticsPreviewBody(page)),
      });
      const preview = logisticsPayload(res).preview || res?.preview;
      if (res?.ok && preview) {
        renderLogisticsPreview(page, preview);
      } else {
        resetLogisticsPreview(page);
        if (!res?.ok) {
          notifyLogisticsFailure(page, mode, logisticsReasonText(apiError(res)));
        }
      }
    } catch (_) {
      resetLogisticsPreview(page);
      notifyLogisticsFailure(page, mode, logisticsReasonText("generic"));
    }
  }

  function scheduleLogisticsPreview(page) {
    if (!page) return;
    const prev = _logisticsPreviewTimers.get(page);
    if (prev) clearTimeout(prev);
    _logisticsPreviewTimers.set(
      page,
      setTimeout(() => {
        refreshLogisticsPreview(page);
      }, 320)
    );
  }

  function applyLogisticsActionState(page, res) {
    applyActionState(res, "logistics_action");
    const slots =
      res?.state?.fleet_slots ||
      res?.data?.active_slots ||
      logisticsPayload(res).active_slots;
    if (slots) updateLogisticsFleetSlotsBadge(page, slots);
    if (res?.state?.active_planet_id) {
      syncScopedPlanetIds(res.state.active_planet_id);
    }
  }

  function bindLogisticsOnce() {
    if (_logisticsBound) return;
    _logisticsBound = true;

    GC.registerCleanup(() => {
      _logisticsBound = false;
    });

    document.addEventListener("click", (e) => {
      const tabBtn = e.target.closest("[data-logistics-tab]");
      if (tabBtn && !tabBtn.disabled) {
        const page = document.getElementById("logistics-page");
        if (page && page.contains(tabBtn)) {
          setLogisticsMode(page, tabBtn.getAttribute("data-logistics-tab"));
        }
        return;
      }

      const maxBtn = e.target.closest("[data-logistics-ship-max]");
      if (!maxBtn) return;
      const page = document.getElementById("logistics-page");
      if (!page || !page.contains(maxBtn)) return;
      const mode = getLogisticsMode(page);
      const grid = page.querySelector(`[data-logistics-ships-grid="${mode}"]`);
      const key = maxBtn.getAttribute("data-logistics-ship-max");
      const row = grid?.querySelector(`[data-ship-key="${key}"]`);
      const inp = row?.querySelector("[data-logistics-ship-input]");
      if (inp) {
        inp.value = String(parseInt(row.dataset.shipHave || inp.max || "0", 10) || 0);
        clampLogisticsShipInput(inp);
        syncLogisticsColonySelected(page);
        updateLogisticsSubmitButtons(page);
        scheduleLogisticsPreview(page);
      }
    });

    document.addEventListener("change", (e) => {
      const page = document.getElementById("logistics-page");
      if (!page || page.dataset.ready !== "1") return;
      if (
        e.target.matches("[data-logistics-origin]") ||
        e.target.matches("[data-logistics-colony-cb]") ||
        e.target.matches("[data-logistics-ship-input]") ||
        e.target.matches("[data-logistics-resource]")
      ) {
        const data = parseLogisticsPageData(page);
        if (e.target.matches("[data-logistics-origin]")) {
          updateLogisticsOriginShips(page, data);
        } else {
          if (e.target.matches("[data-logistics-ship-input]")) {
            clampLogisticsShipInput(e.target);
          }
          syncLogisticsColonySelected(page);
          updateLogisticsSubmitButtons(page);
          scheduleLogisticsPreview(page);
        }
      }
    });

    document.addEventListener("input", (e) => {
      const page = document.getElementById("logistics-page");
      if (!page || page.dataset.ready !== "1") return;
      if (e.target.matches("[data-logistics-ship-input]")) {
        clampLogisticsShipInput(e.target);
        updateLogisticsSubmitButtons(page);
        scheduleLogisticsPreview(page);
      } else if (e.target.matches("[data-logistics-resource]")) {
        updateLogisticsSubmitButtons(page);
        scheduleLogisticsPreview(page);
      }
    });

    document.addEventListener("submit", async (e) => {
      const collectForm = e.target.closest("#logistics-collect-form");
      const distributeForm = e.target.closest("#logistics-distribute-form");
      const form = collectForm || distributeForm;
      if (!form) return;
      const page = document.getElementById("logistics-page");
      if (!page || !page.contains(form)) return;
      e.preventDefault();
      if (form.dataset.submitting === "1") return;

      const mode = collectForm ? "collect" : "distribute";
      clearLogisticsError(page, mode);

      const originId = getLogisticsOriginId(page);
      const colonyIds = getLogisticsSelectedColonyIds(page, mode);
      const ships = getLogisticsShipsSelection(page, mode);

      if (!originId || !colonyIds.length || !Object.keys(ships).length) {
        notifyLogisticsFailure(
          page,
          mode,
          mode === "collect"
            ? tt("logistics_collect_incomplete")
            : tt("logistics_distribute_incomplete")
        );
        return;
      }

      const submitBtn = form.querySelector(`[data-logistics-submit="${mode}"]`);
      form.dataset.submitting = "1";
      if (submitBtn) submitBtn.disabled = true;
      try {
        await refreshLogisticsPreview(page);
        if (!logisticsSubmitEnabled(page, mode)) {
          const blockReason = page._logisticsLastPreview?.block_reason || "";
          notifyLogisticsFailure(
            page,
            mode,
            blockReason
              ? logisticsReasonText(blockReason)
              : mode === "collect"
                ? tt("logistics_collect_incomplete")
                : tt("logistics_distribute_incomplete")
          );
          return;
        }
        let res;
        if (mode === "collect") {
          res = await GC.fetchGameAction("/api/fleet/logistics/collect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              target_planet_id: originId,
              source_planet_ids: colonyIds,
              ships,
              resources_mode: "all",
              ships_selection_mode: "manual",
            }),
          });
        } else {
          const resources = getLogisticsResourcesSelection(page);
          if ((resources.metal || 0) + (resources.crystal || 0) + (resources.fuel_cells || 0) <= 0) {
            notifyLogisticsFailure(page, mode, tt("logistics_distribute_no_resources"));
            return;
          }
          res = await GC.fetchGameAction("/api/fleet/logistics/distribute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              origin_planet_id: originId,
              target_planet_ids: colonyIds,
              ships,
              resources,
              resources_mode: "equal",
              ships_selection_mode: "manual",
            }),
          });
        }
        if (res?.ok) {
          const okKey =
            mode === "collect" ? "logistics_collect_success" : "logistics_distribute_success";
          showNotify(
            tt(okKey),
            "success"
          );
          applyLogisticsActionState(page, res);
          await refreshLogisticsLiveState(page);
          if (typeof GC.reloadCurrentPage === "function") {
            await GC.reloadCurrentPage({ force: true });
          }
        } else {
          notifyLogisticsFailure(page, mode, logisticsReasonText(apiError(res)));
          applyLogisticsActionState(page, res);
        }
      } catch (_) {
        notifyLogisticsFailure(page, mode, logisticsReasonText("generic"));
      } finally {
        form.dataset.submitting = "0";
        updateLogisticsSubmitButtons(page);
        scheduleLogisticsPreview(page);
      }
    });
  }

  function initLogistics() {
    bindLogisticsOnce();
    const page = document.getElementById("logistics-page");
    if (!page || page.dataset.ready !== "1") return;

    const data = parseLogisticsPageData(page);
    if (data?.planet_id) {
      page.dataset.planetId = String(data.planet_id);
      syncScopedPlanetIds(data.planet_id);
    }
    if (typeof GC.initHudSelects === "function") GC.initHudSelects(page);
    setLogisticsMode(page, getLogisticsMode(page));
    updateLogisticsOriginShips(page, data);
    resetLogisticsPreview(page);
    refreshLogisticsLiveState(page);
    GC.registerCleanup(() => {
      page._logisticsLivePending = false;
    });
  }

  function initFleet() {
    bindFleetOnce();
    const page = document.getElementById("fleet-page");
    if (!page || page.dataset.ready !== "1") return;

    page._fleetApplySeq = 0;
    page._fleetLiveServerTime = 0;
    const initParams = new URLSearchParams(window.location.search);
    if (!(initParams.get("mission") || "").trim()) {
      delete page.dataset.fleetUrlMission;
    }

    const rt = getFleetRuntime(page);
    rt.data = parseFleetPageData(page);
    rt.lastPreview = null;
    if (rt.data?.planet_id) page.dataset.planetId = String(rt.data.planet_id);

    const fuelResource = rt.data.fuel_resource || page.dataset.fuelResource || "fuel_cells";
    const fuelLabelEl = page.querySelector("[data-fuel-resource-label]");
    if (fuelLabelEl) {
      fuelLabelEl.textContent = fleetFuelLabel((k, f) => t(k, f), fuelResource);
    }

    if (typeof GC.initHudSelects === "function") GC.initHudSelects(page);
    applyFleetUrlPrefill(page);
    if (typeof GC.pickDefaultFleetTargetIfNeeded === "function") {
      GC.pickDefaultFleetTargetIfNeeded(page);
    }

    const tickFleetCountdowns = () => {
      const p = document.getElementById("fleet-page");
      if (!p || p.dataset.ready !== "1") return;
      updateMovementCountdowns(getTimerServerNow());
    };
    tickFleetCountdowns();
    GC.startProgressTicker();
    if (typeof GC.refreshFleetState === "function") GC.refreshFleetState(page);
  }

  function applyFleetUrlPrefill(page) {
    const params = new URLSearchParams(window.location.search);
    const form = page.querySelector("#fleet-send-form");
    if (!form) return;

    const readExpeditionPosition = () => {
      const fromPage = parseInt(page.dataset.expeditionPosition || "", 10);
      if (fromPage > 0) return fromPage;
      try {
        const st = JSON.parse(page.querySelector("#fleet-page-state")?.textContent || "{}");
        return parseInt(st.expedition_position || "16", 10) || 16;
      } catch (_) {
        return 16;
      }
    };

    const missionRaw = (params.get("mission") || "").trim().toLowerCase();
    const gRaw = params.get("target_galaxy");
    const sRaw = params.get("target_system");
    const pRaw = params.get("target_position");
    const hasCoords = gRaw != null && sRaw != null && pRaw != null;
    const gInp = form.querySelector('[name="target_galaxy"]');
    const sInp = form.querySelector('[name="target_system"]');
    const pInp = form.querySelector('[name="target_position"]');
    const ms = form.querySelector("[data-fleet-mission]");
    const missionKnown =
      missionRaw && ms && Array.from(ms.options).some((opt) => opt.value === missionRaw);

    if (hasCoords) {
      if (gInp) gInp.value = String(parseInt(gRaw, 10) || gRaw);
      if (sInp) sInp.value = String(parseInt(sRaw, 10) || sRaw);
      if (pInp) pInp.value = String(parseInt(pRaw, 10) || pRaw);
    }

    if (missionKnown) {
      if (missionRaw === "expedition") {
        const expPos = readExpeditionPosition();
        if (pInp) pInp.value = String(expPos);
      }
      page.dataset.fleetUrlMission = missionRaw;
      ms.value = missionRaw;
      if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(ms);
      setColonizeRowVisible(page, missionRaw);
      updateFleetFormMode(page);
    } else {
      delete page.dataset.fleetUrlMission;
    }

    const colonyName = params.get("colony_name");
    if (colonyName) {
      const inp = form.querySelector("[data-fleet-colony-name]");
      if (inp) inp.value = colonyName;
    }

    if (typeof GC.syncColonyChipsFromCoords === "function") {
      GC.syncColonyChipsFromCoords(page);
    }
    if (typeof GC.syncExpeditionMissionTarget === "function") {
      GC.syncExpeditionMissionTarget(page);
    }
    const urlMission = page.dataset.fleetUrlMission || "";
    if (urlMission && ms && ms.value !== urlMission) {
      ms.value = urlMission;
      if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(ms);
      setColonizeRowVisible(page, urlMission);
      updateFleetFormMode(page);
    }
    if (typeof GC.runFleetPreview === "function") {
      GC.runFleetPreview(page);
    }
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
    const delay = immediate ? 0 : 150;
    _shipyardRefreshTimer = GC.setSafeTimeout(() => {
      _shipyardRefreshTimer = null;
      if (page.dataset.queueRefreshBusy === "1") return;
      page.dataset.queueRefreshBusy = "1";
      refreshShipyardStateCoalesced(page)
        .then((data) => {
          if (data?.current_ships) updateShipyardStockBadges(page, data.current_ships);
          _shipyardUnitFinishKey = "";
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
    const page = document.getElementById("shipyard-page");
    if (!page || page.dataset.ready !== "1") return;
    GC.startProgressTicker();
  }

  function _shipyardQueueSignature(queueList, summary) {
    try {
      const count = summary?.count ?? (queueList?.length ?? 0);
      const items = (queueList || [])
        .map(
          (j, idx) =>
            `${j.id}:${j.queue_position ?? idx + 1}:${j.units_delivered ?? 0}:${j.amount_remaining ?? j.amount}:${j.next_finish_at || j.finish_at || 0}`
        )
        .join("|");
      return `${count}|${items}`;
    } catch (_) {
      return "";
    }
  }

  function _updateShipyardQueueCompact(count) {
    const labelEl = document.getElementById("shipyard-queue-compact-label");
    if (!labelEl) return;

    const n = Math.max(0, Math.floor(Number(count || 0)));
    if (!n) {
      _setIfChanged(labelEl, t("shipyard_queue_compact_idle", "Keine Werftaufträge"));
      return;
    }
    _setIfChanged(
      labelEl,
      tf("shipyard_queue_compact_active", { count: n }, `${n} Werftaufträge aktiv`)
    );
  }

  function patchShipyardCardQueues(page, queueData) {
    if (!page) return;
    const byOwner = queueData?.card_jobs_by_owner;
    if (!byOwner || typeof byOwner !== "object") return;
    patchCardQueuesFromOwnerMap(
      page,
      byOwner,
      (root) => root.querySelectorAll("[data-ship-card][data-unlocked='1']"),
      (card) => card.getAttribute("data-ship-key") || "",
      (root, shipKey) => root.querySelector(`[data-ship-key="${shipKey}"][data-unlocked="1"]`)
    );
  }

  function shipyardIconUrl(shipKey) {
    const sk = String(shipKey || "").trim();
    return `/static/img/ships/${sk}.png`;
  }
  GC.shipyardIconUrl = shipyardIconUrl;

  function _syncShipyardQueueLiveState(queueList) {
    const first = queueList && queueList.length ? queueList[0] : null;
    if (first) {
      const finishTime = resolveQueueJobFinishTime(first);
      const isActiveHead = Boolean(first.is_active !== false);
      if (isActiveHead && finishTime) {
        const now = getTimerServerNow();
        const remaining = queueJobRemainingSeconds(finishTime, now, resolveQueueJobRemaining(first));
        const totalRaw = Number(first.order_total_seconds || first.total_seconds || 0);
        const total = totalRaw > 0 ? Math.floor(totalRaw) : Math.max(1, remaining + 1);
        SHIPYARDQ.active.finishTime = finishTime;
        SHIPYARDQ.active.totalSeconds = total;
      } else {
        SHIPYARDQ.active.finishTime = 0;
        SHIPYARDQ.active.totalSeconds = 0;
      }
    } else {
      SHIPYARDQ.active.finishTime = 0;
      SHIPYARDQ.active.totalSeconds = 0;
    }
  }

  function renderShipyardQueue(page, queueData) {
    const compact = document.getElementById("shipyard-queue-compact");
    if (!compact) return;

    const qd = queueData || { queue: [], summary: { count: 0, limit: 3, refund_percent: 60 } };
    const jobs = qd.queue || [];
    const summary = qd.summary || {};
    const count = summary.count ?? jobs.length;
    const first = jobs.length ? jobs[0] : null;

    _syncShipyardQueueLiveState(jobs);

    const sig = _shipyardQueueSignature(jobs, summary);

    if (!jobs.length) {
      _lastShipyardQueueSignature = sig;
      _productionZeroHandled.shipyard = "";
      _finishRefreshArmed.shipyard = false;
      _updateShipyardQueueCompact(0);
      patchShipyardCardQueues(page, qd);
      GC.startProgressTicker();
      return;
    }

    if (sig === _lastShipyardQueueSignature) {
      const finishTime = first ? resolveQueueJobFinishTime(first) : 0;
      const nextUnitFinish = first
        ? parseTimerTarget(first.next_countdown_at ?? first.next_finish_at ?? 0)
        : 0;
      const now = getTimerServerNow();
      const overdue =
        (finishTime > 0 && finishTime <= now) ||
        (nextUnitFinish > 0 && nextUnitFinish <= now);
      if (!overdue) {
        _updateShipyardQueueCompact(count);
        patchShipyardCardQueues(page, qd);
        GC.startProgressTicker();
        return;
      }
    }
    _lastShipyardQueueSignature = sig;
    _productionZeroHandled.shipyard = "";

    _updateShipyardQueueCompact(count);
    if (!jobs.length) _finishRefreshArmed.shipyard = false;
    else clearFinishRefreshArmed("shipyard", jobs);

    patchShipyardCardQueues(page, qd);

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

  function updateShipyardStockBadges(page, ships) {
    if (!page) return;
    const stock = ships || {};
    page.querySelectorAll("[data-shipyard-stock]").forEach((el) => {
      const key = el.getAttribute("data-shipyard-stock");
      if (!key) return;
      const qty = Number(stock[key]) || 0;
      const text = fmtNumber(qty);
      if (el.textContent !== text) el.textContent = text;
    });
  }

  function renderShipyardInventory(page, ships) {
    updateShipyardStockBadges(page, ships);
  }

  function shipyardResourceIconHtml(resKey) {
    const icons = {
      metal: { file: "ferronit", mod: "gc-res-metal" },
      crystal: { file: "crytite", mod: "gc-res-crystal" },
      fuel_cells: { file: "fuel_cells", mod: "gc-res-fuel-cells" },
    };
    const cfg = icons[resKey];
    if (!cfg) return "";
    return (
      `<img src="/static/icons/${cfg.file}.png" alt="" ` +
      `class="gc-res-icon gc-res-icon--sm ${cfg.mod}" loading="lazy" aria-hidden="true">`
    );
  }

  function shipyardResourceLabel(resKey, tt) {
    const map = {
      metal: tt("resource_metal", "Metal"),
      crystal: tt("resource_crystal", "Crystal"),
      fuel_cells: tt("resource_fuel_cells", "Fuel cells"),
    };
    return map[resKey] || resKey;
  }

  function renderShipyardCostChips(ship, resources, tt) {
    const specs = [
      ["metal", "cost_metal"],
      ["crystal", "cost_crystal"],
      ["fuel_cells", "cost_fuel_cells"],
    ];
    return specs
      .map(([resKey, costKey]) => {
        const need = Number(ship[costKey]) || 0;
        if (need <= 0) return "";
        const have = Number(resources[resKey]) || 0;
        const unmet = have < need;
        return (
          `<span class="gc-cost-chip gc-cost-${resKey}${unmet ? " is-unmet" : ""}">` +
          `${shipyardResourceIconHtml(resKey)}` +
          `<span class="gc-cost-val">${fmtNumber(need)}</span></span>`
        );
      })
      .filter(Boolean)
      .join("");
  }

  function shipyardReqItemVisible(item) {
    if (!item || item.met) return false;
    if (item.type === "building" && (item.key === "orbital_shipyard" || item.key === "shipyard")) {
      return false;
    }
    return true;
  }

  function renderShipyardReqBlocker(item, tt) {
    const label =
      item.type === "building"
        ? tt("building_" + item.key, item.key)
        : tt(item.key, item.key);
    const met = Boolean(item.met);
    const cls = met ? " is-met" : " is-unmet";
    const typeCls = item.type === "research" ? " shipyard-blocker-research" : " shipyard-blocker-building";
    const icon = met ? "✓" : "🔒";
    const cur = fmtNumber(Number(item.current) || 0);
    const req = fmtNumber(Number(item.required) || 0);
    return (
      `<span class="shipyard-blocker shipyard-blocker-req${typeCls}${cls}"` +
      ` title="${gcEscHtml(label)} L${req} (${cur}/${req})">` +
      `<span class="shipyard-blocker-icon" aria-hidden="true">${icon}</span>` +
      `<span class="shipyard-blocker-text">${gcEscHtml(label)}</span>` +
      `<span class="shipyard-blocker-progress gc-mono">L${cur}/${req}</span></span>`
    );
  }

  function renderShipyardLevelBlocker(required, current, tt) {
    const req = Number(required) || 0;
    const cur = Number(current) || 0;
    const met = cur >= req;
    const cls = met ? " is-met" : " is-unmet";
    const icon = met ? "✓" : "🔒";
    const label = tt("building_orbital_shipyard", "Orbital Shipyard");
    const title = tt("shipyard_locked_level", "Requires Orbital Shipyard level %(level)s")
      .replace("%(level)s", fmtNumber(req))
      .replace("{{level}}", fmtNumber(req));
    return (
      `<span class="shipyard-blocker shipyard-blocker-shipyard${cls}"` +
      ` title="${gcEscHtml(title)} (${fmtNumber(cur)}/${fmtNumber(req)})">` +
      `<span class="shipyard-blocker-icon" aria-hidden="true">${icon}</span>` +
      `<span class="shipyard-blocker-text">${gcEscHtml(label)}</span>` +
      `<span class="shipyard-blocker-progress gc-mono">L${fmtNumber(cur)}/${fmtNumber(req)}</span></span>`
    );
  }

  function renderShipyardResourceBlocker(resKey, need, have, tt) {
    const req = Number(need) || 0;
    const cur = Number(have) || 0;
    const met = cur >= req;
    const cls = met ? " is-met" : " is-unmet";
    const label = shipyardResourceLabel(resKey, tt);
    return (
      `<span class="shipyard-blocker shipyard-blocker-resource${cls}"` +
      ` title="${gcEscHtml(label)}: ${fmtNumber(cur)} / ${fmtNumber(req)}">` +
      `${shipyardResourceIconHtml(resKey)}` +
      `<span class="shipyard-blocker-text">${gcEscHtml(label)}</span>` +
      `<span class="shipyard-blocker-progress gc-mono">${fmtNumber(cur)}/${fmtNumber(req)}</span></span>`
    );
  }

  function renderShipyardBlockersHtml(ship, resources, syLevel, unlocked, tt) {
    const parts = [];
    if (!unlocked) {
      const reqSy = Number(ship.required_shipyard_level) || 0;
      const curSy = Number(syLevel) || 0;
      if (curSy < reqSy) {
        parts.push(renderShipyardLevelBlocker(reqSy, curSy, tt));
      }
      (ship.requirements?.items || [])
        .filter((item) => shipyardReqItemVisible(item))
        .forEach((item) => parts.push(renderShipyardReqBlocker(item, tt)));
      return parts.join("");
    }
    if (ship.can_build) return "";
    [
      ["metal", "cost_metal"],
      ["crystal", "cost_crystal"],
      ["fuel_cells", "cost_fuel_cells"],
    ].forEach(([resKey, costKey]) => {
      const need = Number(ship[costKey]) || 0;
      const have = Number(resources[resKey]) || 0;
      if (need > 0 && have < need) {
        parts.push(renderShipyardResourceBlocker(resKey, need, have, tt));
      }
    });
    return parts.join("");
  }

  function applyShipyardShipCard(card, ship, resources, syLevel, tt) {
    if (!card || !ship) return;
    const unlocked = card.dataset.unlocked === "1";
    card.classList.toggle("shipyard-ship-card--blocked", unlocked && !ship.can_build);
    card.classList.toggle("gc-prog-unaffordable", unlocked && !ship.can_build && ship.block_reason !== "queue_full");
    card.classList.toggle("gc-prog-affordable", unlocked && ship.can_build);

    const costEl = card.querySelector("[data-shipyard-cost]");
    if (costEl) {
      const html = renderShipyardCostChips(ship, resources, tt);
      if (html && costEl.innerHTML !== html) costEl.innerHTML = html;
    }

    let blockersEl = card.querySelector("[data-shipyard-blockers]");
    const blockersHtml = renderShipyardBlockersHtml(ship, resources, syLevel, unlocked, tt);
    if (blockersHtml) {
      if (!blockersEl) {
        blockersEl = document.createElement("div");
        blockersEl.className = "shipyard-blockers";
        blockersEl.dataset.shipyardBlockers = "1";
        blockersEl.setAttribute("aria-live", "polite");
        card.appendChild(blockersEl);
      }
      if (blockersEl.innerHTML !== blockersHtml) blockersEl.innerHTML = blockersHtml;
      blockersEl.hidden = false;
    } else if (blockersEl) {
      blockersEl.replaceChildren();
      blockersEl.hidden = true;
    }

    if (!unlocked) return;
    const btn = card.querySelector("[data-shipyard-build]");
    const maxBtn = card.querySelector("[data-shipyard-max]");
    if (btn) {
      btn.disabled = !ship.can_build;
      btn.dataset.canBuild = ship.can_build ? "1" : "0";
      if (btn.dataset.building !== "1") btn.classList.remove("is-loading");
      const queueFull = ship.block_reason === "queue_full";
      const buildLabel = tt("shipyard_build_btn", "Bauen");
      const fullLabel = tt("shipyard_btn_queue_full", "Werftwarteschlange voll");
      if (queueFull) {
        btn.textContent = fullLabel;
        btn.title = fullLabel;
      } else {
        btn.textContent = buildLabel;
        btn.removeAttribute("title");
      }
    }
    if (maxBtn) maxBtn.dataset.maxQty = String(ship.max_build || 0);
    const buildTimeEl = card.querySelector(".shipyard-ship-build-time");
    if (buildTimeEl && ship.build_seconds != null) {
      const tpl = tt("shipyard_build_time_per_unit", "Build time: %(seconds)s s per ship");
      buildTimeEl.textContent = tpl.replace("%(seconds)s", fmtNumber(Number(ship.build_seconds) || 0));
    }

    const stockEl = card.querySelector("[data-shipyard-stock]");
    if (stockEl && ship.owned_count != null) {
      const text = fmtNumber(Number(ship.owned_count) || 0);
      if (stockEl.textContent !== text) stockEl.textContent = text;
    }
  }

  function applyShipyardState(page, data) {
    if (!page || !data) return;
    const statePlanet = Number(data.planet_id || 0);
    const activePlanet = Number(GC.lastState?.active_planet_id || page.dataset.planetId || 0);
    if (activePlanet > 0 && statePlanet > 0 && activePlanet !== statePlanet) {
      return;
    }
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
          coordsEl.innerHTML = `(${GC.coordLinkHtml(data.planet_coords, { label: data.planet_coords })})`;
        } else if (coordsEl) {
          coordsEl.remove();
        }
      }
    }

    const resources = data.resources || {};
    page.querySelectorAll("[data-sy-res]").forEach((node) => {
      const key = node.getAttribute("data-sy-res");
      if (key && resources[key] != null) node.textContent = fmtNumber(Number(resources[key]) || 0);
    });

    if (data.current_ships) updateShipyardStockBadges(page, data.current_ships);
    if (data.shipyard_queue) renderShipyardQueue(page, data.shipyard_queue);

    const syLevel = data.orbital_shipyard_level != null ? data.orbital_shipyard_level : page.dataset.shipyardLevel;

    (data.buildable_ships || []).forEach((ship) => {
      const card = page.querySelector(`[data-ship-key="${ship.ship_key}"][data-unlocked="1"]`);
      applyShipyardShipCard(card, ship, resources, syLevel, tt);
    });

    (data.locked_ships || []).forEach((ship) => {
      const card = page.querySelector(`[data-ship-key="${ship.ship_key}"][data-unlocked="0"]`);
      applyShipyardShipCard(card, ship, resources, syLevel, tt);
    });
  }

  async function refreshShipyardState(page) {
    let planetId = parseInt(page.dataset.planetId || "0", 10);
    const activePlanet = Number(GC.lastState?.active_planet_id || 0);
    if (activePlanet > 0) {
      if (planetId > 0 && planetId !== activePlanet) return null;
      planetId = activePlanet;
      page.dataset.planetId = String(activePlanet);
    }
    const q = planetId ? `?planet_id=${planetId}` : "";
    const res = await GC.fetchGameAction(`/api/shipyard${q}`, { method: "GET" });
    if (res?.ok && res.data) {
      applyShipyardState(page, res.data);
      return res.data;
    }
    return null;
  }

  function refreshShipyardStateCoalesced(page) {
    if (!page) return Promise.resolve(null);
    if (_shipyardApiInFlight) return _shipyardApiInFlight;
    _shipyardApiInFlight = Promise.resolve(refreshShipyardState(page)).finally(() => {
      _shipyardApiInFlight = null;
    });
    return _shipyardApiInFlight;
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
            _lastShipyardQueueSignature = "";
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
            _lastShipyardQueueSignature = "";
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
          _lastShipyardQueueSignature = "";
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

  let _defenseRefreshTimer = null;
  let _defenseUnitFinishKey = "";
  let _defenseBound = false;
  let _defensePollIntervalId = null;
  let _lastDefenseQueueSignature = "";

  function defenseIconUrl(defenseKey) {
    return `/static/img/defense/${String(defenseKey || "").trim()}.png`;
  }
  GC.defenseIconUrl = defenseIconUrl;

  function defenseLabel(defenseKey) {
    const k = String(defenseKey || "").trim();
    return t(`defense_${k}`, k);
  }

  function normalizeDefenseApiPayload(res) {
    if (!res) return null;
    if (res.data && typeof res.data === "object") return res.data;
    if (res.defenses && typeof res.defenses === "object") {
      return {
        ...res.defenses,
        defense_queue: res.queue || res.defenses.defense_queue,
      };
    }
    return null;
  }

  function updateDefenseStockBadges(page, stock) {
    if (!page) return;
    const inv = stock || {};
    page.querySelectorAll("[data-defense-stock]").forEach((el) => {
      const key = el.getAttribute("data-defense-stock");
      if (!key) return;
      const qty = Number(inv[key]) || 0;
      const text = fmtNumber(qty);
      if (el.textContent !== text) el.textContent = text;
    });
  }

  function renderDefenseInventory(page, stock) {
    updateDefenseStockBadges(page, stock);
  }

  function parseDefensePageData(page) {
    const el = document.getElementById("defense-page-state");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || "{}");
    } catch (_) {
      return null;
    }
  }

  function _defenseQueueSignature(queueList, summary) {
    try {
      const count = summary?.count ?? (queueList?.length ?? 0);
      const items = (queueList || [])
        .map(
          (j, idx) =>
            `${j.id}:${j.queue_position ?? idx + 1}:${j.units_delivered ?? 0}:${j.amount_remaining ?? j.amount}:${j.next_finish_at || j.finish_at || 0}`
        )
        .join("|");
      return `${count}|${items}`;
    } catch (_) {
      return "";
    }
  }

  function _updateDefenseQueueCompact(count) {
    const labelEl = document.getElementById("defense-queue-compact-label");
    if (!labelEl) return;
    const n = Math.max(0, Math.floor(Number(count || 0)));
    if (!n) {
      _setIfChanged(labelEl, t("defense_queue_compact_idle", "Keine Verteidigungsaufträge"));
      return;
    }
    _setIfChanged(
      labelEl,
      tf("defense_queue_compact_active", { count: n }, `${n} Verteidigungsaufträge aktiv`)
    );
  }

  function patchDefenseCardQueues(page, queueData) {
    if (!page) return;
    const byOwner = queueData?.card_jobs_by_owner;
    if (!byOwner || typeof byOwner !== "object") return;
    patchCardQueuesFromOwnerMap(
      page,
      byOwner,
      (root) => root.querySelectorAll("[data-defense-card][data-unlocked='1']"),
      (card) => card.getAttribute("data-defense-card") || "",
      (root, defenseKey) => root.querySelector(`[data-defense-card="${defenseKey}"][data-unlocked="1"]`)
    );
  }

  function _syncDefenseQueueLiveState(queueList) {
    const first = queueList && queueList.length ? queueList[0] : null;
    if (first) {
      const finishTime = resolveQueueJobFinishTime(first);
      const isActiveHead = Boolean(first.is_active !== false);
      if (isActiveHead && finishTime) {
        const now = getTimerServerNow();
        const remaining = queueJobRemainingSeconds(finishTime, now, resolveQueueJobRemaining(first));
        const totalRaw = Number(first.order_total_seconds || first.total_seconds || 0);
        const total = totalRaw > 0 ? Math.floor(totalRaw) : Math.max(1, remaining + 1);
        DEFENSEQ.active.finishTime = finishTime;
        DEFENSEQ.active.totalSeconds = total;
      } else {
        DEFENSEQ.active.finishTime = 0;
        DEFENSEQ.active.totalSeconds = 0;
      }
    } else {
      DEFENSEQ.active.finishTime = 0;
      DEFENSEQ.active.totalSeconds = 0;
    }
  }

  function renderDefenseQueue(page, queuePayload) {
    const compact = document.getElementById("defense-queue-compact");
    if (!compact) return;

    const qd = queuePayload || { queue: [], summary: { count: 0, limit: 3, refund_percent: 60 } };
    const jobs = qd.queue || [];
    const summary = qd.summary || {};
    const count = summary.count ?? jobs.length;
    const first = jobs.length ? jobs[0] : null;

    _syncDefenseQueueLiveState(jobs);

    const sig = _defenseQueueSignature(jobs, summary);

    if (!jobs.length) {
      _lastDefenseQueueSignature = sig;
      _productionZeroHandled.defense = "";
      _finishRefreshArmed.defense = false;
      _updateDefenseQueueCompact(0);
      patchDefenseCardQueues(page, qd);
      GC.startProgressTicker();
      return;
    }

    if (sig === _lastDefenseQueueSignature) {
      const finishTime = first ? resolveQueueJobFinishTime(first) : 0;
      const nextUnitFinish = first
        ? parseTimerTarget(first.next_countdown_at ?? first.next_finish_at ?? 0)
        : 0;
      const now = getTimerServerNow();
      const overdue =
        (finishTime > 0 && finishTime <= now) ||
        (nextUnitFinish > 0 && nextUnitFinish <= now);
      if (!overdue) {
        _updateDefenseQueueCompact(count);
        patchDefenseCardQueues(page, qd);
        GC.startProgressTicker();
        return;
      }
    }
    _lastDefenseQueueSignature = sig;
    _productionZeroHandled.defense = "";

    _updateDefenseQueueCompact(count);
    if (!jobs.length) _finishRefreshArmed.defense = false;
    else clearFinishRefreshArmed("defense", jobs);

    patchDefenseCardQueues(page, qd);
    GC.startProgressTicker();
  }

  function applyDefenseState(page, data) {
    if (!page || !data) return;
    const tt = (key, fallback) => t(key, fallback);
    if (data.planet_id != null) page.dataset.planetId = String(data.planet_id);
    if (data.defense_factory_level != null) {
      page.dataset.factoryLevel = String(data.defense_factory_level);
      const lvlEl = page.querySelector("[data-defense-factory-label]");
      if (lvlEl) {
        lvlEl.textContent = tt("defense_factory_level", "Level %(level)s").replace(
          "%(level)s",
          fmtNumber(data.defense_factory_level)
        );
      }
    }
    if (data.planet_name) {
      const scopeEl = page.querySelector("[data-defense-planet-scope]");
      if (scopeEl) {
        const label = tt("defense_planet_scope", "Active planet: %(name)s").replace(
          "%(name)s",
          String(data.planet_name)
        );
        scopeEl.textContent = label;
        let coordsEl = scopeEl.querySelector("[data-defense-planet-coords]");
        if (data.planet_coords) {
          if (!coordsEl) {
            coordsEl = document.createElement("span");
            coordsEl.className = "defense-planet-coords";
            coordsEl.dataset.defensePlanetCoords = "1";
            scopeEl.appendChild(document.createTextNode(" "));
            scopeEl.appendChild(coordsEl);
          }
          coordsEl.innerHTML = `(${GC.coordLinkHtml(data.planet_coords, { label: data.planet_coords })})`;
        } else if (coordsEl) {
          coordsEl.remove();
        }
      }
    }
    if (data.resources) {
      Object.entries(data.resources).forEach(([key, val]) => {
        const el = page.querySelector(`[data-df-res="${key}"]`);
        if (el) el.textContent = fmtNumber(val);
      });
    }
    if (data.current_defense) updateDefenseStockBadges(page, data.current_defense);
    if (data.defense_queue) renderDefenseQueue(page, data.defense_queue);
    (data.buildable_defense || []).forEach((unit) => {
      applyDefenseUnitCard(page, unit, data.resources || {}, tt);
    });
    (data.locked_defense || []).forEach((unit) => {
      applyDefenseUnitCard(page, unit, data.resources || {}, tt, { locked: true });
    });
  }

  function applyDefenseUnitCard(page, unit, resources, tt, opts = {}) {
    const card = page.querySelector(`[data-defense-card="${unit.defense_key}"]`);
    if (!card) return;

    if (unit.stock != null) {
      const stockEl = card.querySelector(`[data-defense-stock="${unit.defense_key}"]`);
      if (stockEl) {
        const text = fmtNumber(Number(unit.stock) || 0);
        if (stockEl.textContent !== text) stockEl.textContent = text;
      }
    }

    if (opts.locked) return;

    card.classList.toggle("shipyard-ship-card--blocked", !unit.can_build);
    card.classList.toggle("gc-prog-unaffordable", !unit.can_build && unit.block_reason !== "queue_full");
    card.classList.toggle("gc-prog-affordable", !!unit.can_build);

    const costEl = card.querySelector("[data-defense-cost]");
    if (costEl) {
      const html = renderShipyardCostChips(
        {
          cost_metal: unit.cost_metal,
          cost_crystal: unit.cost_crystal,
        },
        resources,
        tt
      );
      if (html && costEl.innerHTML.trim() !== html.trim()) costEl.innerHTML = html;
    }

    const maxBtn = card.querySelector(`[data-defense-max="${unit.defense_key}"]`);
    if (maxBtn) maxBtn.dataset.maxQty = String(unit.max_build || 0);
    const btn = card.querySelector(`[data-defense-build="${unit.defense_key}"]`);
    if (btn) {
      btn.dataset.canBuild = unit.can_build ? "1" : "0";
      btn.disabled = !unit.can_build;
      const queueFull = unit.block_reason === "queue_full";
      const buildLabel = tt("defense_build_btn", "Bauen");
      const fullLabel = tt("defense_btn_queue_full", "Warteschlange voll");
      if (queueFull) {
        btn.textContent = fullLabel;
        btn.title = fullLabel;
      } else {
        btn.textContent = buildLabel;
        btn.removeAttribute("title");
      }
    }
    const buildTimeEl = card.querySelector(".shipyard-ship-build-time");
    if (buildTimeEl && unit.build_seconds != null) {
      buildTimeEl.textContent = tt("defense_build_time_per_unit", "Build time: %(seconds)s s per unit").replace(
        "%(seconds)s",
        fmtNumber(unit.build_seconds)
      );
    }
  }

  async function refreshDefenseState(page) {
    const planetId = parseInt(page.dataset.planetId || "0", 10);
    const q = planetId ? `?planet_id=${planetId}` : "";
    const res = await GC.fetchGameAction(`/api/defense${q}`, { method: "GET" });
    const payload = normalizeDefenseApiPayload(res);
    if (res?.ok && payload) {
      applyDefenseState(page, payload);
      return payload;
    }
    return null;
  }

  function refreshDefenseStateCoalesced(page) {
    if (!page) return Promise.resolve(null);
    if (_defenseApiInFlight) return _defenseApiInFlight;
    _defenseApiInFlight = Promise.resolve(refreshDefenseState(page)).finally(() => {
      _defenseApiInFlight = null;
    });
    return _defenseApiInFlight;
  }

  function scheduleDefenseRefreshFromState(immediate) {
    const page = document.getElementById("defense-page");
    if (!page || page.dataset.ready !== "1") return;
    if (_defenseRefreshTimer != null) {
      clearTimeout(_defenseRefreshTimer);
      _defenseRefreshTimer = null;
    }
    const delay = immediate ? 0 : 150;
    _defenseRefreshTimer = GC.setSafeTimeout(() => {
      _defenseRefreshTimer = null;
      if (page.dataset.queueRefreshBusy === "1") return;
      page.dataset.queueRefreshBusy = "1";
      refreshDefenseStateCoalesced(page)
        .finally(() => {
          delete page.dataset.queueRefreshBusy;
          _defenseUnitFinishKey = "";
        });
    }, delay);
  }

  function stopDefenseTimers() {
    if (_defensePollIntervalId != null) {
      clearInterval(_defensePollIntervalId);
      _defensePollIntervalId = null;
    }
  }

  function startDefenseTimers() {
    stopDefenseTimers();
    const page = document.getElementById("defense-page");
    if (!page || page.dataset.ready !== "1") return;
    GC.startProgressTicker();
  }

  function bindDefenseOnce() {
    if (_defenseBound) return;
    _defenseBound = true;
    const tt = (key, fallback) => t(key, fallback);
    const apiError = (res) => (res && (res.error || res.reason)) || "generic";
    const reasonText = (reason) =>
      tt(`defense_error_${reason}`, tt(`fleet_error_${reason}`, reason || "Error"));

    document.addEventListener("click", async (e) => {
      const page = document.getElementById("defense-page");
      if (!page || page.dataset.ready !== "1") return;

      const maxBtn = e.target.closest("[data-defense-max]");
      if (maxBtn && page.contains(maxBtn)) {
        e.preventDefault();
        const dk = maxBtn.getAttribute("data-defense-max");
        const qtyInp = page.querySelector(`[data-defense-qty="${dk}"]`);
        const maxQty = parseInt(maxBtn.dataset.maxQty || "0", 10);
        if (qtyInp && maxQty > 0) qtyInp.value = String(maxQty);
        return;
      }

      const cancelBtn = e.target.closest("[data-defense-queue-cancel]");
      if (cancelBtn && page.contains(cancelBtn)) {
        e.preventDefault();
        const jobId = parseInt(cancelBtn.getAttribute("data-defense-queue-cancel") || "0", 10);
        const planetId = parseInt(page.dataset.planetId || "0", 10);
        if (!jobId) return;
        cancelBtn.disabled = true;
        try {
          const res = await GC.fetchGameAction("/api/defense/cancel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job_id: jobId, planet_id: planetId || undefined }),
          });
          if (res?.ok) {
            if (res.state) applyActionState(res, "defense_cancel");
            const payload = normalizeDefenseApiPayload(res);
            if (payload) applyDefenseState(page, payload);
            else await refreshDefenseState(page);
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

      const buildBtn = e.target.closest("[data-defense-build]");
      if (!buildBtn || !page.contains(buildBtn) || buildBtn.disabled) return;
      if (buildBtn.dataset.building === "1" || buildBtn.dataset.canBuild === "0") return;
      e.preventDefault();
      const defenseKey = buildBtn.getAttribute("data-defense-build");
      const qtyInp = page.querySelector(`[data-defense-qty="${defenseKey}"]`);
      const amount = parseInt(qtyInp?.value || "1", 10) || 1;
      const planetId = parseInt(page.dataset.planetId || "0", 10);
      buildBtn.dataset.building = "1";
      buildBtn.disabled = true;
      buildBtn.classList.add("is-loading");
      try {
        const res = await GC.fetchGameAction("/api/defense/build", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ defense_key: defenseKey, amount, planet_id: planetId || undefined }),
        });
        if (res?.ok) {
          _lastDefenseQueueSignature = "";
          if (res.state) applyActionState(res, "defense_build");
          const payload = normalizeDefenseApiPayload(res);
          if (payload) applyDefenseState(page, payload);
          else if (!res.state) await refreshDefenseState(page);
        } else {
          showNotify(reasonText(res?.error || apiError(res)), "error");
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

  function initDefense() {
    bindDefenseOnce();
    const page = document.getElementById("defense-page");
    if (!page || page.dataset.ready !== "1") return;
    const data = parseDefensePageData(page);
    if (!data) return;
    applyDefenseState(page, data);
    startDefenseTimers();
    GC.registerCleanup(stopDefenseTimers);
    GC.startProgressTicker();
  }

  GC.refreshDefenseState = refreshDefenseState;

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
    const RECEIVE_FOR_GIVE = {
      metal: ["crystal", "fuel_cells"],
      crystal: ["metal", "fuel_cells"],
      fuel_cells: ["metal", "crystal"],
    };

    const readRates = () => ({
      m2c: parseFloat(panel.dataset.rateM2c || "0.8"),
      c2m: parseFloat(panel.dataset.rateC2m || "0.8"),
      fuelMetalPer: parseFloat(panel.dataset.fuelMetalPer || "45"),
      fuelCrystalPer: parseFloat(panel.dataset.fuelCrystalPer || "28"),
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
      if (give === "fuel_cells") return currentReceive === "metal" ? "crystal" : "metal";
      return "crystal";
    };

    const alternateGive = (receive, currentGive) => {
      if (receive === "metal") return currentGive === "crystal" ? "fuel_cells" : "crystal";
      if (receive === "crystal") return currentGive === "metal" ? "fuel_cells" : "metal";
      if (receive === "fuel_cells") return currentGive === "metal" ? "crystal" : "metal";
      return "metal";
    };

    const updateTileStates = (give, receive) => {
      giveTiles.forEach((btn) => {
        const res = btn.getAttribute("data-exchange-give") || "";
        const active = res === give;
        const canGive = (RECEIVE_FOR_GIVE[res] || []).length > 0;
        btn.classList.toggle("is-active", active);
        btn.classList.toggle("is-disabled", !canGive);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
        btn.disabled = !canGive;
        btn.removeAttribute("title");
      });
      receiveTiles.forEach((btn) => {
        const res = btn.getAttribute("data-exchange-receive") || "";
        const active = res === receive;
        const enabled = (RECEIVE_FOR_GIVE[give] || []).includes(res);
        btn.classList.toggle("is-active", active);
        btn.classList.toggle("is-disabled", !enabled);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
        btn.disabled = !enabled;
      });
    };

    const minForRoute = (dir) => {
      const cfg = readRates();
      const { from, to } = routeParts(dir);
      if (from === "fuel_cells") return cfg.fuelMin;
      if (to === "fuel_cells") {
        const per = from === "metal" ? cfg.fuelMetalPer : cfg.fuelCrystalPer;
        return Math.max(cfg.minAmount, Math.ceil(Math.max(0.001, per)));
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
      if (from === "metal" && to === "fuel_cells") return Math.floor(raw / Math.max(0.001, cfg.fuelMetalPer));
      if (from === "crystal" && to === "fuel_cells") return Math.floor(raw / Math.max(0.001, cfg.fuelCrystalPer));
      if (from === "fuel_cells" && to === "metal") return Math.floor(raw * Math.max(0.001, cfg.fuelMetalPer));
      if (from === "fuel_cells" && to === "crystal") return Math.floor(raw * Math.max(0.001, cfg.fuelCrystalPer));
      return 0;
    };

    const displayRate = (dir) => {
      const cfg = readRates();
      const { from, to } = routeParts(dir);
      if (from === "metal" && to === "crystal") return cfg.m2c;
      if (from === "crystal" && to === "metal") return cfg.c2m;
      if (from === "metal" && to === "fuel_cells") return 1 / Math.max(0.001, cfg.fuelMetalPer);
      if (from === "crystal" && to === "fuel_cells") return 1 / Math.max(0.001, cfg.fuelCrystalPer);
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
          if (btn.disabled || btn.classList.contains("is-disabled")) return;
          const give = btn.getAttribute("data-exchange-give") || "metal";
          const { to } = routeParts(selectedDirection());
          setResourcePair(give, to);
        });
      });
      receiveTiles.forEach((btn) => {
        btn.addEventListener("click", () => {
          if (btn.disabled || btn.classList.contains("is-disabled")) return;
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
        <article class="gc-scrapyard-row fleet-ship-row gc-trader-scrap-row" data-scrap-ship="${key}" data-scrap-max="${amount}">
          <div class="fleet-ship-row-main gc-trader-scrap-main">
            <div class="gc-trader-scrap-icon-wrap">
              <img src="${icon}" alt="" class="gc-scrapyard-ship-icon" width="40" height="40" loading="lazy">
            </div>
            <div class="gc-trader-scrap-body">
              <span class="gc-scrapyard-ship-name fleet-ship-name">${shipName}</span>
              <span class="gc-scrapyard-have fleet-ship-stock gc-mono">${haveLabel}</span>
              <span class="gc-trader-scrap-refund hint gc-mono">
                ${tt("scrapyard_refund_estimate", "Refund (approx.)")}:
                ${minM.toLocaleString()}–${maxM.toLocaleString()} ${metalLabel},
                ${minC.toLocaleString()}–${maxC.toLocaleString()} ${crystalLabel}
              </span>
            </div>
          </div>
          <div class="fleet-ship-row-controls gc-trader-scrap-actions">
            <input type="number" class="gc-trader-input fleet-ship-input gc-scrapyard-qty" min="1" max="${amount}" value="1"
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

  function patchTraderHubBalance(metal, crystal, storageMetal, storageCrystal, fuelCells, storageFuelCells) {
    const page = document.getElementById("trader-hub-page");
    if (!page) return;
    const metalVal = page.querySelector('[data-res="metal"]');
    const crystalVal = page.querySelector('[data-res="crystal"]');
    const fuelVal = page.querySelector('[data-res="fuel_cells"]');
    const metalCap = page.querySelector('[data-cap="metal"]');
    const crystalCap = page.querySelector('[data-cap="crystal"]');
    const fuelCap = page.querySelector('[data-cap="fuel_cells"]');
    const metalBar = page.querySelector('[data-res-bar="metal"]');
    const crystalBar = page.querySelector('[data-res-bar="crystal"]');
    const fuelBar = page.querySelector('[data-res-bar="fuel_cells"]');
    if (metalVal) _setIfChanged(metalVal, fmtNumber(metal));
    if (crystalVal) _setIfChanged(crystalVal, fmtNumber(crystal));
    if (fuelVal && typeof fuelCells === "number") _setIfChanged(fuelVal, fmtNumber(fuelCells));
    if (metalCap && storageMetal > 0) _setIfChanged(metalCap, `/ ${fmtNumber(storageMetal)}`);
    if (crystalCap && storageCrystal > 0) _setIfChanged(crystalCap, `/ ${fmtNumber(storageCrystal)}`);
    if (fuelCap && storageFuelCells > 0) _setIfChanged(fuelCap, `/ ${fmtNumber(storageFuelCells)}`);
    if (metalBar && storageMetal > 0) {
      const pct = Math.min(100, Math.floor((Number(metal) / storageMetal) * 100));
      metalBar.style.width = `${pct}%`;
    }
    if (crystalBar && storageCrystal > 0) {
      const pct = Math.min(100, Math.floor((Number(crystal) / storageCrystal) * 100));
      crystalBar.style.width = `${pct}%`;
    }
    if (fuelBar && storageFuelCells > 0) {
      const pct = Math.min(100, Math.floor((Number(fuelCells) / storageFuelCells) * 100));
      fuelBar.style.width = `${pct}%`;
    }
  }

  function initResearch() {
    GC.startProgressTicker();
  }

  function syncPlanetEvolutionResearchTicker() {
    const page = document.querySelector(".planet-evolution-page");
    if (!page) return;
    const hasCardQueues = page.querySelector(".gc-card-queue-block[data-gc-card-queue='1']");
    if (!hasCardQueues) return;
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
      closeAllHudSelects(wrap);
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
      document.addEventListener("click", (e) => {
        if (e.target.closest(".gc-hud-select")) return;
        closeAllHudSelects();
      });
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
      coordEl.hidden = !coord;
      coordEl.innerHTML = coord ? GC.coordLinkHtml(coord, { label: coord }) : "";
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
      metaSpan.innerHTML = coord
        ? `${GC.coordLinkHtml(coord, { label: coord })} · ${gcEscHtml(suffix)}`
        : gcEscHtml(suffix);

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
          coordEl.hidden = !coord;
          coordEl.innerHTML = coord ? GC.coordLinkHtml(coord, { label: coord }) : "";
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
        if (e.target.closest("a.gc-galaxy-coord-link")) return;
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
      if (e.target.closest("a.gc-galaxy-coord-link")) return;
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
          const anyActive = applyActionState(res, "planet_switch");
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
          await GC.reloadCurrentPage({ force: true, skipHydrate: true, skipGameState: true });
          syncScopedPlanetIds(planetId);
          if (typeof GC.refreshGameState === "function") {
            await GC.refreshGameState("planet_switch");
          }
          const fleetPage = document.getElementById("fleet-page");
          if (
            fleetPage &&
            fleetPage.dataset.ready === "1" &&
            typeof GC.refreshFleetState === "function"
          ) {
            await GC.refreshFleetState(fleetPage);
          }
          GC.startPolling(anyActive || lastHadActiveJob || lastHadActiveResearch || lastHadActiveShipyard);
          GC.startProgressTicker();
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
          if (res?.ok) {
            _lastPePlanetTechQueueSignature = "";
            if (typeof GC.reloadCurrentPage === "function") {
              await GC.reloadCurrentPage({ force: true });
            }
            if (typeof GC.refreshGameState === "function") {
              await GC.refreshGameState("planet_research_start");
            }
          } else showNotify(reasonText(res?.reason), "error");
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

  function normalizePopoverTriggers(root = document) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(".gc-popover-trigger[title]").forEach((el) => {
      el.removeAttribute("title");
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
      const text = (trigger.dataset.popover || "").trim();
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
      if (e.key === "Escape") {
        closePopover();
        return;
      }
      if (e.key !== "Enter" && e.key !== " ") return;
      const trigger = e.target.closest(".gc-popover-trigger");
      if (!trigger) return;
      e.preventDefault();
      if (activeTrigger === trigger) closePopover();
      else openPopover(trigger);
    });

    window.addEventListener("resize", closePopover);
    window.addEventListener("scroll", closePopover, true);

    normalizePopoverTriggers();
  }

  function initPlanetEvolution() {
    if (!document.querySelector(".planet-evolution-page")) return;
    bindPlanetEvolutionOnce();
    syncPlanetEvolutionResearchTicker();
    document.querySelectorAll("[data-pe-reload]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (typeof GC.reloadCurrentPage === "function") {
          GC.reloadCurrentPage({ force: true });
        }
      });
    });
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
    return parseIntNumber(row[tab.scoreKey]);
  }

  function rankingVisibleTabs(payload) {
    const cur = payload?.current_player || {};
    const top = Array.isArray(payload?.top_players) ? payload.top_players : [];
    return RANKING_TABS.filter((tab) => {
      if (tab.id === "total" || tab.id === "building" || tab.id === "research" || tab.id === "fleet" || tab.id === "defense" || tab.id === "evolution") return true;
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
    return parseIntNumber(cur[tab.scoreKey]);
  }

  function rankingAvatarFallbackHtml(initial, theme) {
    const letter = rankingEscapeHtml(initial || "?");
    const th = rankingEscapeHtml(theme || "cyan");
    return `<span class="gc-ranking-avatar-fallback gc-ranking-avatar-fallback--${th}" aria-hidden="true">${letter}</span>`;
  }

  GC.fallbackRankingAvatar = function fallbackRankingAvatar(img) {
    if (!img || img.dataset.fallbackApplied === "1") return;
    img.dataset.fallbackApplied = "1";
    const initial = img.getAttribute("data-avatar-initial") || "?";
    const theme = img.getAttribute("data-avatar-theme") || "cyan";
    const wrap = img.closest(".gc-ranking-avatar");
    if (wrap) {
      wrap.innerHTML = rankingAvatarFallbackHtml(initial, theme);
      return;
    }
    img.replaceWith(
      (() => {
        const span = document.createElement("span");
        span.innerHTML = rankingAvatarFallbackHtml(initial, theme);
        return span.firstElementChild || span;
      })()
    );
  };

  function rankingAvatarInner(row) {
    const initial = rankingEscapeHtml(row.avatar_initial || "?");
    const theme = rankingEscapeHtml(row.theme || "cyan");
    if (row.show_avatar && row.avatar_url) {
      const src = rankingEscapeHtml(row.avatar_url);
      return (
        `<img class="gc-ranking-avatar-img" src="${src}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" ` +
        `data-avatar-initial="${initial}" data-avatar-theme="${theme}" ` +
        `onerror="GC.fallbackRankingAvatar(this)">`
      );
    }
    return rankingAvatarFallbackHtml(initial, theme);
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
          `<img class="gc-ranking-avatar-img" src="${rankingEscapeHtml(busted)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" ` +
          `data-avatar-initial="${rankingEscapeHtml(initial)}" data-avatar-theme="${rankingEscapeHtml(theme)}" ` +
          `onerror="GC.fallbackRankingAvatar(this)">`;
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
    const badgeImgFallback = "/static/img/badges/default.png";
    const chips = badges
      .map((badge) => {
        const label = rankingEscapeHtml(rankingT(badge.name_key, badge.badge_key || "Badge"));
        const imgSrc = rankingEscapeHtml(badge.image_url || "");
        const rarity = rankingEscapeHtml(badge.rarity || "common");
        const img = imgSrc
          ? `<img class="gc-ranking-badge-img" src="${imgSrc}" alt="" width="20" height="20" loading="lazy" onerror="this.onerror=null;this.src='${badgeImgFallback}';">`
          : "";
        return (
          `<span class="gc-ranking-badge gc-ranking-badge--${rarity}" title="${label}" aria-label="${label}">` +
          img +
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
      `<span class="gc-ranking-my-value gc-mono">${renderMonoCompact(score)}</span>` +
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
          `<td class="gc-ranking-score gc-ranking-score--active">${renderMonoCompact(row.display_score)}</td>` +
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
          `<span class="gc-ranking-mobile-score-inline gc-mono">${renderMonoCompact(row.display_score)}</span>` +
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
    try {
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
    } catch (err) {
      console.error("[GC] ranking render failed", err);
      const tableEl = document.getElementById("ranking-table-content");
      if (tableEl) {
        const errMsg = rankingT("ranking_error", "Could not load ranking.");
        tableEl.innerHTML = `<div class="ranking-state ranking-state-error">${rankingEscapeHtml(errMsg)}</div>`;
      }
    }
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
      } catch (err) {
        console.warn("[GC] ranking initial JSON parse failed", err);
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
        if (loadId !== _rankingLifecycle.loadId) return;
        if (err && err.name === "AbortError") return;
        renderRankingPayload(null);
      });
  }

  GC.initRanking = function initRanking() {
    if (!document.getElementById("ranking-page")) return;
    bindRankingTabsOnce();
    loadRankingData();
  };

  const EMPIRE_MATRIX_STORAGE_KEY = "gc_empire_matrix_collapsed";

  function loadEmpireMatrixCollapsed() {
    try {
      const raw = localStorage.getItem(EMPIRE_MATRIX_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed?.collapsed) ? parsed.collapsed.filter(Boolean) : [];
    } catch (_) {
      return [];
    }
  }

  function saveEmpireMatrixCollapsed(collapsedKeys) {
    try {
      localStorage.setItem(
        EMPIRE_MATRIX_STORAGE_KEY,
        JSON.stringify({ collapsed: collapsedKeys.filter(Boolean) })
      );
    } catch (_) {}
  }

  function applyEmpireSectionCollapse(matrix, sectionKey, collapsed) {
    if (!matrix || !sectionKey) return;
    const sectionRow = matrix.querySelector(
      `.empire-matrix-section-row[data-empire-section="${sectionKey}"]`
    );
    const toggle = sectionRow?.querySelector("[data-empire-section-toggle]");
    const dataRows = matrix.querySelectorAll(
      `.empire-matrix-data-row[data-empire-section="${sectionKey}"]`
    );
    sectionRow?.classList.toggle("is-collapsed", collapsed);
    if (toggle) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.setAttribute(
        "aria-label",
        collapsed
          ? t("empire_matrix_section_expand", "Abschnitt aufklappen")
          : t("empire_matrix_section_collapse", "Abschnitt einklappen")
      );
    }
    dataRows.forEach((row) => row.classList.toggle("is-section-collapsed", collapsed));
  }

  function bindEmpireMatrixOnce() {
    if (GC._empireMatrixBound) return;
    GC._empireMatrixBound = true;

    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-empire-section-toggle]");
      if (!btn) return;
      const matrix = document.querySelector("#empire-page .empire-matrix");
      if (!matrix || !matrix.contains(btn)) return;
      e.preventDefault();

      const sectionKey = btn.dataset.empireSectionToggle;
      if (!sectionKey) return;

      const sectionRow = matrix.querySelector(
        `.empire-matrix-section-row[data-empire-section="${sectionKey}"]`
      );
      const willCollapse = !sectionRow?.classList.contains("is-collapsed");
      applyEmpireSectionCollapse(matrix, sectionKey, willCollapse);

      const collapsed = [];
      matrix.querySelectorAll(".empire-matrix-section-row.is-collapsed").forEach((row) => {
        const key = row.dataset.empireSection;
        if (key) collapsed.push(key);
      });
      saveEmpireMatrixCollapsed(collapsed);
    });
  }

  function initEmpire() {
    const root = document.getElementById("empire-page");
    if (!root) return;
    const matrix = root.querySelector(".empire-matrix");
    if (!matrix) return;

    bindEmpireMatrixOnce();

    const collapsed = new Set(loadEmpireMatrixCollapsed());
    matrix.querySelectorAll("[data-empire-section-toggle]").forEach((btn) => {
      const key = btn.dataset.empireSectionToggle;
      if (key) applyEmpireSectionCollapse(matrix, key, collapsed.has(key));
    });
  }

  GC.modules.overview = initOverview;
  GC.modules.inventory = initInventory;
  GC.modules.trader_hub = initTraderHub;
  GC.modules.fleet = initFleet;
  GC.modules.logistics = initLogistics;
  GC.modules.shipyard = initShipyard;
  GC.modules.defense = initDefense;
  GC.modules.buildings = initBuildings;
  GC.modules.research = initResearch;
  GC.modules.planet_evolution = initPlanetEvolution;
  GC.modules.empire = initEmpire;
  GC.modules.galaxy = initGalaxy;
  GC.modules.ranking = function initRankingPage() {
    GC.initRanking();
  };
  const TECHTREE_STORAGE_KEY = "gc_techtree_collapsed";
  let techtreeMediaZoomOpen = false;

  function closeTechtreeMediaZoom() {
    const zoom = document.querySelector("[data-techtree-media-zoom-root]");
    if (!zoom || zoom.hidden) {
      techtreeMediaZoomOpen = false;
      document.body.classList.remove("gc-techtree-media-zoom-open");
      return;
    }
    zoom.hidden = true;
    zoom.setAttribute("aria-hidden", "true");
    const img = zoom.querySelector(".gc-techtree-media-zoom-img");
    const titleEl = zoom.querySelector("[data-techtree-media-zoom-title]");
    if (img) {
      img.removeAttribute("src");
      img.alt = "";
    }
    if (titleEl) titleEl.textContent = "";
    techtreeMediaZoomOpen = false;
    document.body.classList.remove("gc-techtree-media-zoom-open");
  }

  function openTechtreeMediaZoom({ src, title }) {
    const zoom = document.querySelector("[data-techtree-media-zoom-root]");
    const url = String(src || "").trim();
    if (!zoom || !url) return;
    const img = zoom.querySelector(".gc-techtree-media-zoom-img");
    const titleEl = zoom.querySelector("[data-techtree-media-zoom-title]");
    const label = String(title || "").trim();
    if (img) {
      img.src = url;
      img.alt = label;
    }
    if (titleEl) titleEl.textContent = label;
    zoom.hidden = false;
    zoom.setAttribute("aria-hidden", "false");
    techtreeMediaZoomOpen = true;
    document.body.classList.add("gc-techtree-media-zoom-open");
  }

  function loadTechtreeCollapsed(defaultCollapsedKeys) {
    try {
      const raw = localStorage.getItem(TECHTREE_STORAGE_KEY);
      if (!raw) return new Set(defaultCollapsedKeys || []);
      const parsed = JSON.parse(raw);
      return new Set(Array.isArray(parsed?.collapsed) ? parsed.collapsed.filter(Boolean) : []);
    } catch (_) {
      return new Set(defaultCollapsedKeys || []);
    }
  }

  function saveTechtreeCollapsed(collapsedKeys) {
    try {
      localStorage.setItem(
        TECHTREE_STORAGE_KEY,
        JSON.stringify({ collapsed: collapsedKeys.filter(Boolean) })
      );
    } catch (_) {}
  }

  function applyTechtreeSectionCollapse(root, sectionKey, collapsed) {
    if (!root || !sectionKey) return;
    const section = root.querySelector(`[data-techtree-section="${sectionKey}"]`);
    if (!section) return;
    const toggle = section.querySelector("[data-techtree-section-toggle]");
    const body = section.querySelector(".techtree-section-body");
    section.classList.toggle("is-collapsed", collapsed);
    if (toggle) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
    if (body) {
      if (collapsed) body.setAttribute("hidden", "");
      else body.removeAttribute("hidden");
    }
  }

  function bindTechtreeOnce() {
    if (GC._techtreeBound) return;
    GC._techtreeBound = true;

    document.addEventListener("click", (e) => {
      const closeBtn = e.target.closest("[data-techtree-media-zoom-close]");
      if (closeBtn) {
        const page = document.getElementById("techtree-page");
        if (!page || !page.contains(closeBtn)) return;
        e.preventDefault();
        closeTechtreeMediaZoom();
        return;
      }

      const imgBtn = e.target.closest("[data-techtree-img-zoom]");
      if (imgBtn) {
        const page = document.getElementById("techtree-page");
        if (!page || !page.contains(imgBtn)) return;
        e.preventDefault();
        e.stopPropagation();
        const img = imgBtn.querySelector("img");
        openTechtreeMediaZoom({
          src: imgBtn.getAttribute("data-img-src") || img?.currentSrc || img?.src || "",
          title: imgBtn.getAttribute("data-img-title") || img?.alt || "",
        });
        return;
      }

      const btn = e.target.closest("[data-techtree-section-toggle]");
      if (!btn) return;
      const root = document.getElementById("techtree-page");
      if (!root || !root.contains(btn)) return;
      e.preventDefault();

      const sectionKey = btn.dataset.techtreeSectionToggle;
      if (!sectionKey) return;

      const section = root.querySelector(`[data-techtree-section="${sectionKey}"]`);
      const willCollapse = !section?.classList.contains("is-collapsed");
      applyTechtreeSectionCollapse(root, sectionKey, willCollapse);

      const collapsed = [];
      root.querySelectorAll(".techtree-section.is-collapsed").forEach((el) => {
        const key = el.dataset.techtreeSection;
        if (key) collapsed.push(key);
      });
      saveTechtreeCollapsed(collapsed);
    });

    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-techtree-filter]");
      if (!btn) return;
      const root = document.getElementById("techtree-page");
      if (!root || !root.contains(btn)) return;
      e.preventDefault();
      root.querySelectorAll(".techtree-filter-btn").forEach((el) => {
        el.classList.toggle("is-active", el === btn);
      });
      applyTechtreeFilters(root);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !techtreeMediaZoomOpen) return;
      closeTechtreeMediaZoom();
    });
  }

  function applyTechtreeFilters(root) {
    if (!root) return;
    const query = (root.querySelector("#techtree-search")?.value || "").trim().toLowerCase();
    const activeFilter =
      root.querySelector(".techtree-filter-btn.is-active")?.dataset?.techtreeFilter || "all";

    root.querySelectorAll("[data-techtree-section]").forEach((section) => {
      let visibleCount = 0;
      section.querySelectorAll("[data-techtree-item]").forEach((card) => {
        const status = card.dataset.status || "locked";
        const searchText = card.dataset.searchText || "";
        const matchesFilter = activeFilter === "all" || status === activeFilter;
        const matchesSearch = !query || searchText.includes(query);
        const visible = matchesFilter && matchesSearch;
        card.classList.toggle("is-filter-hidden", !visible);
        if (visible) visibleCount += 1;
      });
      section.classList.toggle("is-filter-empty", visibleCount === 0);
    });
  }

  function initTechtree() {
    const root = document.getElementById("techtree-page");
    if (!root) return;

    bindTechtreeOnce();

    const defaultCollapsed = [];
    root.querySelectorAll("[data-techtree-section]").forEach((section) => {
      if (section.dataset.defaultCollapsed === "1") {
        const key = section.dataset.techtreeSection;
        if (key) defaultCollapsed.push(key);
      }
    });

    const collapsed = loadTechtreeCollapsed(defaultCollapsed);
    root.querySelectorAll("[data-techtree-section-toggle]").forEach((btn) => {
      const key = btn.dataset.techtreeSectionToggle;
      if (key) applyTechtreeSectionCollapse(root, key, collapsed.has(key));
    });

    const searchInput = root.querySelector("#techtree-search");
    if (searchInput && !searchInput.dataset.bound) {
      searchInput.dataset.bound = "1";
      searchInput.addEventListener("input", () => applyTechtreeFilters(root));
    }

    applyTechtreeFilters(root);
    GC.registerCleanup(() => {
      closeTechtreeMediaZoom();
      if (searchInput) searchInput.dataset.bound = "";
    });
  }

  GC.modules.techtree = initTechtree;

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
    "a.gc-nav-link, a.gc-bottom-nav-item, a.gc-nav-drawer-link, a.gc-hud-panel-messages, #gc-nav-trading-sub a.gc-nav-sub-link, #gc-nav-military-sub a.gc-nav-sub-link";

  function _tradingPageFromPath(path) {
    const p = String(path || "").replace(/\/$/, "") || "/";
    if (p.endsWith("/trader-hub")) return "trader_hub";
    if (p.endsWith("/logistics")) return "logistics";
    if (p.endsWith("/inventory")) return "inventory";
    if (p.endsWith("/auction-house")) return "auction_house";
    if (p.endsWith("/galactic-politics")) return "galactic_politics";
    if (p.endsWith("/skilltree")) return "skilltree";
    if (p.endsWith("/premium")) return "premium";
    return "";
  }

  function _militaryPageFromPath(path) {
    const p = String(path || "").replace(/\/$/, "") || "/";
    if (p.endsWith("/shipyard")) return "shipyard";
    if (p.endsWith("/defense")) return "defense";
    return "";
  }

  function _syncTradingNavFromPath(path) {
    const tradingPage = _tradingPageFromPath(path);
    const parent = document.getElementById("gc-nav-trading-parent");
    const sub = document.getElementById("gc-nav-trading-sub");
    if (!parent || !sub) return;

    parent.classList.toggle("active", !!tradingPage);
    sub.querySelectorAll("[data-trading-nav]").forEach((el) => {
      el.classList.toggle("active", el.dataset.tradingNav === tradingPage);
    });
    if (tradingPage) showTradingSubnav();
    else hideTradingSubnav();
  }

  function _syncMilitaryNavFromPath(path) {
    const militaryPage = _militaryPageFromPath(path);
    const parent = document.getElementById("gc-nav-military-parent");
    const sub = document.getElementById("gc-nav-military-sub");
    if (!parent || !sub) return;

    parent.classList.toggle("active", !!militaryPage);
    sub.querySelectorAll("[data-military-nav]").forEach((el) => {
      el.classList.toggle("active", el.dataset.militaryNav === militaryPage);
    });
    if (militaryPage) showMilitarySubnav();
    else hideMilitarySubnav();
  }

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
      const isTradingParent = link.id === "gc-nav-trading-parent";
      const isMilitaryParent = link.id === "gc-nav-military-parent";
      if (isTradingParent || isMilitaryParent) return;
      link.classList.toggle("active", linkPath === path);
    });
    _syncTradingNavFromPath(path);
    _syncMilitaryNavFromPath(path);
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
        if (fetchedBody?.dataset?.serverTime) {
          document.body.dataset.serverTime = fetchedBody.dataset.serverTime;
          resyncServerTimeFromDom(true);
        }
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

        await GC.initPage({
          force: true,
          skipHydrate: Boolean(opts.skipHydrate),
          skipGameState: Boolean(opts.skipGameState),
        });
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
          GC.startPolling(lastHadActiveJob || lastHadActiveResearch || lastHadActiveShipyard);
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
      syncPerfBodyClasses();
      if (document.hidden) {
        GC.stopPolling();
        pauseVisualLoops();
        return;
      }
      if (!shouldRunGameLoop() || _authLoopAborted) return;
      _authLoopAborted = false;
      resumeVisualLoops();
      GC.refreshGameState("tab_visible");
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
    avatarZoomOpen: false,
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

  function closePlayerCardMediaZoom() {
    const openZoom = document.querySelector("[data-pc-media-zoom-root]:not([hidden])");
    if (!openZoom) {
      PLAYER_CARD.avatarZoomOpen = false;
      document.body.classList.remove("gc-player-card-avatar-zoom-open");
      return;
    }
    openZoom.hidden = true;
    openZoom.setAttribute("aria-hidden", "true");
    const img = openZoom.querySelector(".gc-player-card-avatar-zoom-img");
    const panel = openZoom.querySelector(".gc-player-card-avatar-zoom-panel");
    const caption = openZoom.querySelector("[data-pc-media-zoom-caption]");
    const titleEl = openZoom.querySelector("[data-pc-media-zoom-title]");
    const descEl = openZoom.querySelector("[data-pc-media-zoom-desc]");
    if (img) {
      img.removeAttribute("src");
      img.classList.remove("gc-player-card-avatar-zoom-img--badge");
      img.alt = "";
    }
    panel?.classList.remove("gc-player-card-avatar-zoom-panel--badge");
    if (caption) caption.hidden = true;
    if (titleEl) titleEl.textContent = "";
    if (descEl) descEl.textContent = "";
    PLAYER_CARD.avatarZoomOpen = false;
    document.body.classList.remove("gc-player-card-avatar-zoom-open");
  }

  function closePlayerCardAvatarZoom() {
    closePlayerCardMediaZoom();
  }

  function openPlayerCardMediaZoom({ src, shell, kind, title, desc, alt }) {
    const zoom = shell?.querySelector("[data-pc-media-zoom-root]");
    const url = String(src || "").trim();
    if (!zoom || !url) return;
    const img = zoom.querySelector(".gc-player-card-avatar-zoom-img");
    const panel = zoom.querySelector(".gc-player-card-avatar-zoom-panel");
    const caption = zoom.querySelector("[data-pc-media-zoom-caption]");
    const titleEl = zoom.querySelector("[data-pc-media-zoom-title]");
    const descEl = zoom.querySelector("[data-pc-media-zoom-desc]");
    const isBadge = kind === "badge";
    if (img) {
      img.src = url;
      img.alt = String(alt || title || "").trim();
      img.classList.toggle("gc-player-card-avatar-zoom-img--badge", isBadge);
    }
    panel?.classList.toggle("gc-player-card-avatar-zoom-panel--badge", isBadge);
    if (caption) {
      if (isBadge) {
        caption.hidden = false;
        if (titleEl) titleEl.textContent = String(title || "").trim();
        if (descEl) descEl.textContent = String(desc || "").trim();
      } else {
        caption.hidden = true;
        if (titleEl) titleEl.textContent = "";
        if (descEl) descEl.textContent = "";
      }
    }
    zoom.hidden = false;
    zoom.setAttribute("aria-hidden", "false");
    PLAYER_CARD.avatarZoomOpen = true;
    document.body.classList.add("gc-player-card-avatar-zoom-open");
  }

  function openPlayerCardAvatarZoom(src, shell) {
    openPlayerCardMediaZoom({ src, shell, kind: "avatar" });
  }

  function closePlayerCardModal() {
    const root = cachePlayerCardElements();
    if (!root) return;
    closePlayerCardMediaZoom();
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
      const badgeImgFallback = "/static/img/badges/default.png";
      const checked = form.querySelectorAll('input[name="badge_slot"]:checked');
      let n = 0;
      checked.forEach((inp) => {
        if (n >= 3) return;
        const imgSrc = inp.getAttribute("data-pc-badge-image") || "";
        const name = inp.getAttribute("data-pc-badge-name") || "";
        const rarity = inp.getAttribute("data-pc-badge-rarity") || "";
        const desc = inp.getAttribute("data-pc-badge-desc") || "";
        const tip = [name, rarity, desc].filter(Boolean).join("\n\n");
        const tile = document.createElement("div");
        tile.className = "gc-player-card-badge-tile";
        if (tip) tile.title = tip;
        if (imgSrc) {
          const img = document.createElement("img");
          img.className = "gc-badge-icon gc-player-card-badge-img";
          img.src = imgSrc;
          img.alt = "";
          img.width = 40;
          img.height = 40;
          img.loading = "lazy";
          img.onerror = function () {
            this.onerror = null;
            this.src = badgeImgFallback;
          };
          tile.appendChild(img);
        }
        const nameEl = document.createElement("span");
        nameEl.className = "gc-player-card-badge-name";
        nameEl.textContent = name;
        tile.appendChild(nameEl);
        host.appendChild(tile);
        n += 1;
      });
    }

    function avatarPreviewSrc() {
      const raw = (form.querySelector('[data-pc-field="avatar_url"]')?.value || "").trim();
      if (!raw) return "";
      const ver = String(form.getAttribute("data-avatar-version") || "").trim();
      if (!ver || ver === "0") return raw;
      const sep = raw.includes("?") ? "&" : "?";
      return `${raw}${sep}v=${ver}`;
    }

    function syncPreview() {
      const avatarUrl = avatarPreviewSrc();
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

    const avatarFileInput = form.querySelector('[data-pc-field="avatar_file"]');
    if (avatarFileInput && avatarFileInput.dataset.pcAvatarBound !== "1") {
      avatarFileInput.dataset.pcAvatarBound = "1";
      avatarFileInput.addEventListener("change", () => {
        const file = avatarFileInput.files && avatarFileInput.files[0];
        if (file) uploadPlayerCardAvatar(form, file, avatarFileInput);
      });
    }

    syncPreview();
  }

  async function uploadPlayerCardAvatar(form, file, fileInput) {
    const msgEl = form.querySelector("[data-pc-form-msg]");
    const fd = new FormData();
    fd.append("avatar", file);

    if (msgEl) { msgEl.hidden = true; msgEl.textContent = ""; }
    pcSetLoading(true);

    try {
      const res = await fetch("/api/player-card/me/avatar", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: fd,
      });
      const data = await res.json();
      pcSetLoading(false);
      if (!data.ok) {
        const key = data.reason || "playercard_avatar_upload_error";
        const txt = t(key, t("playercard_avatar_upload_error", "Avatar-Upload fehlgeschlagen."));
        if (msgEl) { msgEl.textContent = txt; msgEl.hidden = false; }
        showNotify(txt, "error");
        return;
      }
      const hidden = form.querySelector('[data-pc-field="avatar_url"]');
      const card = data.card || {};
      if (hidden && card.avatar_url) {
        const busted = String(card.avatar_url);
        const base = busted.split("?")[0].split("&")[0];
        hidden.value = base;
        const ver = String(card.avatar_version || "");
        if (ver) form.setAttribute("data-avatar-version", ver);
      }
      const preview = form.querySelector("#gc-player-card-preview");
      const avatarImg = form.querySelector("#pc-preview-avatar");
      const avatarPh = form.querySelector("#pc-preview-avatar-ph");
      if (card.avatar_url && avatarImg && avatarPh) {
        avatarImg.src = card.avatar_url;
        avatarImg.hidden = false;
        avatarPh.hidden = true;
      }
      if (typeof GC.syncPlayerAvatarVisuals === "function") {
        GC.syncPlayerAvatarVisuals(card);
      }
      showNotify(t("playercard_avatar_upload_success", "Avatar gespeichert."), "success");
    } catch (_) {
      pcSetLoading(false);
      const txt = t("playercard_avatar_upload_error", "Avatar-Upload fehlgeschlagen.");
      if (msgEl) { msgEl.textContent = txt; msgEl.hidden = false; }
      showNotify(txt, "error");
    } finally {
      if (fileInput) fileInput.value = "";
    }
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
    const shell = wrap.querySelector(".gc-ship-detail-shell, .gc-defense-detail-shell, .gc-player-card-shell");
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

  async function fetchDefenseDetailHtml(defenseKey, reqToken) {
    sdAbortFetch();
    const ctrl = new AbortController();
    SHIP_DETAIL.abort = ctrl;
    const key = encodeURIComponent(String(defenseKey || "").trim());
    try {
      const res = await fetch(`/api/defense-units/${key}`, {
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

  async function loadDefenseDetail(defenseKey) {
    if (!sdPrepareOpen(defenseKey)) return;
    if (SHIP_DETAIL.titleEl) {
      SHIP_DETAIL.titleEl.textContent = t("defense_detail_title", "Defense specifications");
    }
    const reqToken = SHIP_DETAIL.reqId;
    try {
      const result = await fetchDefenseDetailHtml(defenseKey, reqToken);
      if (result.aborted || reqToken !== SHIP_DETAIL.reqId) return;
      if (!result.ok) {
        if (result.html && result.html.includes("gc-ship-detail-shell")) {
          mountShipDetailHtml(result.html);
        } else {
          sdSetError(t("defense_detail_not_found", t("defense_detail_load_error", "Could not load defense data.")));
        }
        return;
      }
      mountShipDetailHtml(result.html);
    } catch (_) {
      if (reqToken !== SHIP_DETAIL.reqId) return;
      sdSetError(t("defense_detail_load_error", "Could not load defense data."));
    }
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

      const defTrigger = e.target.closest("[data-defense-detail]");
      if (defTrigger) {
        const defenseKey = defTrigger.getAttribute("data-defense-detail");
        if (!defenseKey) return;
        e.preventDefault();
        e.stopPropagation();
        loadDefenseDetail(defenseKey);
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
      const defTrigger = e.target.closest("[data-defense-detail]");
      if (defTrigger && document.activeElement === defTrigger) {
        e.preventDefault();
        loadDefenseDetail(defTrigger.getAttribute("data-defense-detail"));
        return;
      }
      const trigger = e.target.closest("[data-ship-detail]");
      if (!trigger || document.activeElement !== trigger) return;
      e.preventDefault();
      loadShipDetail(trigger.getAttribute("data-ship-detail"));
    });
  }

  GC.openShipDetail = loadShipDetail;
  GC.openDefenseDetail = loadDefenseDetail;
  GC.closeShipDetail = closeShipDetailModal;

  function initPlayerCardOnce() {
    if (GC._playerCardBound) return;
    GC._playerCardBound = true;

    document.addEventListener("click", (e) => {
      const zoomClose = e.target.closest("[data-pc-media-zoom-close], [data-pc-avatar-zoom-close]");
      if (zoomClose) {
        e.preventDefault();
        e.stopPropagation();
        closePlayerCardMediaZoom();
        return;
      }

      const badgeZoomOpen = e.target.closest("[data-pc-badge-zoom]");
      if (badgeZoomOpen) {
        e.preventDefault();
        e.stopPropagation();
        const shell = badgeZoomOpen.closest(".gc-player-card-shell");
        const src =
          badgeZoomOpen.getAttribute("data-badge-src") ||
          badgeZoomOpen.querySelector("img")?.currentSrc ||
          badgeZoomOpen.querySelector("img")?.src;
        if (shell && src) {
          openPlayerCardMediaZoom({
            src,
            shell,
            kind: "badge",
            title: badgeZoomOpen.getAttribute("data-badge-name") || "",
            desc: badgeZoomOpen.getAttribute("data-badge-desc") || "",
            alt: badgeZoomOpen.getAttribute("data-badge-name") || "",
          });
        }
        return;
      }

      const zoomOpen = e.target.closest("[data-pc-avatar-zoom]");
      if (zoomOpen) {
        e.preventDefault();
        e.stopPropagation();
        const shell = zoomOpen.closest(".gc-player-card-shell");
        const img = zoomOpen.querySelector("img");
        const src = zoomOpen.getAttribute("data-avatar-src") || img?.currentSrc || img?.src;
        if (shell && src) openPlayerCardAvatarZoom(src, shell);
        return;
      }

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
      if (PLAYER_CARD.avatarZoomOpen) {
        closePlayerCardMediaZoom();
        return;
      }
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
    initMotionPreferenceListener();
    bootstrapPlanetLandscapeFromBoot();
    syncPerfBodyClasses();
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
