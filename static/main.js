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
    if (arguments.length > 1) return fallback == null ? "" : String(fallback);
    return String(key || "");
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
  const _deIntFormatter = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

  function parseIntNumber(n) {
    if (typeof n === "number" && Number.isFinite(n)) return Math.trunc(n);
    const raw = String(n ?? "").trim();
    if (!raw) return 0;
    if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
    let cleaned = raw.replace(/\s/g, "");
    // de-DE grouped integers: 999.999 / 1.000 / 10.000.000
    if (/^-?\d{1,3}(\.\d{3})+$/.test(cleaned)) {
      return parseInt(cleaned.replace(/\./g, ""), 10);
    }
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

  function formatNumber(n) {
    return _deIntFormatter.format(parseIntNumber(n));
  }

  const COMPACT_THRESHOLD = 10_000_000;
  const COMPACT_INFINITY = 1e18;

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

  /** Compact German display for large scores: 12,3 Mio. / 149,5 Mrd. */
  function formatNumberCompact(n) {
    const num = parseIntNumber(n);
    const abs = Math.abs(num);
    if (abs < COMPACT_THRESHOLD) return formatNumber(num);
    if (abs >= COMPACT_INFINITY) return "∞";

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
    return `${sign}${body} ${suffix}`;
  }

  function formatScore(n) {
    return formatNumberCompact(n);
  }

  function fmtNumber(n) {
    return formatNumber(n);
  }

  function fmtIntFull(n) {
    return formatNumber(n);
  }

  function fmtIntParts(n) {
    const full = formatNumber(n);
    const display = formatNumberCompact(n);
    return { display, full };
  }

  const GC_NUM_INPUT_SELECTOR = [
    ".gc-num-input",
    "[data-shipyard-qty]",
    "[data-defense-qty]",
    "[data-ship-input]",
    "[data-logistics-ship-input]",
    "[data-fleet-res-metal]",
    "[data-fleet-res-crystal]",
    "[data-fleet-res-fuel-cells]",
    "#gc-exchange-amount",
    "#gc-fuel-exchange-units",
    ".gc-scrapyard-qty",
    "[data-auction-bid-input]",
    "[data-scrap-qty]",
    "[data-logistics-resource]",
  ].join(",");

  let _numInputDelegationBound = false;

  function isFormattedNumberInput(el) {
    return !!(el && el.matches && el.matches(GC_NUM_INPUT_SELECTOR));
  }

  function getNumberInputCap(inp) {
    if (!inp) return null;
    const dataMax = inp.getAttribute("data-input-max");
    if (dataMax != null && dataMax !== "") {
      const n = parseIntNumber(dataMax);
      return Number.isFinite(n) && n >= 0 ? n : null;
    }
    if (
      inp.matches(
        "[data-ship-input],[data-logistics-ship-input],[data-scrap-qty],.gc-scrapyard-qty,[data-logistics-resource]"
      )
    ) {
      const maxAttr = inp.getAttribute("max");
      if (maxAttr != null && maxAttr !== "") {
        const n = parseIntNumber(maxAttr);
        return Number.isFinite(n) && n >= 0 ? n : null;
      }
    }
    return null;
  }

  function clampToNumberInputCap(inp, num) {
    const cap = getNumberInputCap(inp);
    if (cap != null && num > cap) return cap;
    return num;
  }

  function readNumberInput(el) {
    return parseIntNumber(el?.value ?? "0");
  }

  function setNumberInputValue(el, n) {
    if (!el) return;
    let num = Math.max(0, parseIntNumber(n));
    num = clampToNumberInputCap(el, num);
    el.value = formatNumber(num);
  }

  function formatNumberInputOnInput(inp) {
    if (!inp) return;
    const digits = String(inp.value ?? "").replace(/[^\d]/g, "");
    if (!digits) {
      inp.value = "";
      return;
    }
    let num = clampToNumberInputCap(inp, parseInt(digits, 10));
    const formatted = formatNumber(num);
    inp.value = formatted;
    try {
      inp.setSelectionRange(formatted.length, formatted.length);
    } catch (_) {}
  }

  function ensureFormattedNumberInput(inp) {
    if (!inp || inp.dataset.gcNumFmt === "1") return;
    inp.dataset.gcNumFmt = "1";
    if (inp.type === "number") {
      inp.type = "text";
      inp.inputMode = "numeric";
      inp.autocomplete = "off";
    }
    if (!inp.getAttribute("maxlength")) inp.maxLength = 20;
    if (inp.matches("[data-shipyard-qty],[data-defense-qty]")) {
      inp.removeAttribute("max");
    }
    const raw = String(inp.value ?? "").trim();
    if (raw && /\d/.test(raw)) {
      inp.value = formatNumber(parseIntNumber(raw));
    }
  }

  function bindFormattedNumberInputs(root) {
    const scope = root || document;
    scope.querySelectorAll(GC_NUM_INPUT_SELECTOR).forEach(ensureFormattedNumberInput);
  }

  function initFormattedNumberInputDelegation() {
    if (_numInputDelegationBound) return;
    _numInputDelegationBound = true;
    document.addEventListener("input", (e) => {
      if (!isFormattedNumberInput(e.target)) return;
      formatNumberInputOnInput(e.target);
    });
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
    return `<span class="gc-cost-val gc-num-compact">${formatNumber(n)}</span>`;
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

  function serverNow() {
    if (TIME.serverNow && TIME.clientPerfAt) {
      const dt = (performance.now() - TIME.clientPerfAt) / 1000;
      return TIME.serverNow + dt;
    }
    return Math.floor(Date.now() / 1000);
  }

  function syncServerClockFromState(data) {
    const st = Number(data?.server_now ?? data?.server_time ?? 0);
    if (st > 0) setServerTime(st);
  }

  function getApproxServerNow() {
    return serverNow();
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

  /** GC-553 — patch only DOM for the active page module (queue tracking always runs). */
  const _GAME_STATE_PATCH_PAGES = {
    overview: new Set(["overview"]),
    buildings: new Set(["buildings"]),
    research: new Set(["research"]),
    shipyard: new Set(["shipyard"]),
    defense: new Set(["defense"]),
    trader: new Set(["trader_hub", "auction_house"]),
    fleet: new Set(["fleet"]),
    empire: new Set(["empire"]),
  };

  function shouldPatchGameStateModule(module) {
    const page = GC.currentPage || (typeof GC.detectPage === "function" ? GC.detectPage() : "");
    const allowed = _GAME_STATE_PATCH_PAGES[module];
    if (!allowed) return true;
    return allowed.has(page);
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

  const AMBIENCE_STORAGE_KEY = "gc_ambience_time";
  const AMBIENCE_VOLUME = 0.15;
  const AMBIENCE_ENDPOINTS = new Set(["landing", "login", "register"]);
  let _ambiencePersistTimer = null;

  function isAmbiencePage() {
    const ep = document.body && document.body.dataset.endpoint;
    return AMBIENCE_ENDPOINTS.has(ep);
  }

  function persistAmbienceTime() {
    const audio = document.getElementById("gc-ambience");
    if (!audio || !Number.isFinite(audio.currentTime)) return;
    try {
      sessionStorage.setItem(AMBIENCE_STORAGE_KEY, String(audio.currentTime));
    } catch (_) {}
  }

  function restoreAmbienceTime(audio) {
    let saved = null;
    try {
      saved = sessionStorage.getItem(AMBIENCE_STORAGE_KEY);
    } catch (_) {}
    if (saved == null) return;
    const t = parseFloat(saved);
    if (!Number.isFinite(t) || t < 0) return;

    const apply = () => {
      if (audio.duration && t >= audio.duration - 0.05) return;
      audio.currentTime = t;
    };

    if (audio.readyState >= 1) apply();
    else audio.addEventListener("loadedmetadata", apply, { once: true });
  }

  function initSimplePageAmbience() {
    if (!isAmbiencePage()) return;
    const audio = document.getElementById("gc-ambience");
    if (!audio) return;

    audio.volume = AMBIENCE_VOLUME;
    restoreAmbienceTime(audio);

    const tryPlay = () => {
      const p = audio.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    };

    tryPlay();
    document.addEventListener("pointerdown", tryPlay, { once: true, passive: true });
    document.addEventListener("keydown", tryPlay, { once: true });

    if (!window.__gcAmbiencePersistBound) {
      window.__gcAmbiencePersistBound = true;
      window.addEventListener("pagehide", persistAmbienceTime);
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") persistAmbienceTime();
      });
      _ambiencePersistTimer = window.setInterval(persistAmbienceTime, 4000);
    }
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

  function landscapeWebpUrlFromRaster(url) {
    const raw = String(url || "").trim();
    if (!raw) return "";
    return raw.replace(/\.(png|jpe?g)(\?.*)?$/i, ".webp$2");
  }

  function applyPlanetLandscapeFromState(data) {
    const ap = data?.active_planet;
    const url = String(ap?.landscape_url || "").trim();
    if (!url) {
      document.body.classList.remove("gc-has-planet-landscape");
      document.body.style.removeProperty("--planet-landscape");
      document.body.style.removeProperty("--planet-landscape-webp");
      return;
    }
    const webp = String(ap?.landscape_webp_url || landscapeWebpUrlFromRaster(url) || "").trim();
    document.body.classList.add("gc-has-planet-landscape");
    document.body.style.setProperty("--planet-landscape", `url("${url}")`);
    if (webp) {
      document.body.style.setProperty("--planet-landscape-webp", `url("${webp}")`);
    } else {
      document.body.style.removeProperty("--planet-landscape-webp");
    }
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
      document.querySelector(".buildings-wrapper[data-planet-id]"),
      document.querySelector(".research-page[data-planet-id]"),
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
    document.querySelectorAll(".buildings-wrapper[data-planet-id], .research-page[data-planet-id]").forEach((el) => {
      el.dataset.planetId = String(pid);
    });
    const fleetPage = document.getElementById("fleet-page");
    if (fleetPage && fleetPage._fleetRt?.data) {
      fleetPage._fleetRt.data.planet_id = pid;
    }
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
      _resetQueueLiveStates();
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

  window.GC = GC;

  GC.parseIntNumber = parseIntNumber;
  GC.readNumberInput = readNumberInput;
  GC.setNumberInputValue = setNumberInputValue;
  GC.formatNumber = formatNumber;
  GC.formatNumberCompact = formatNumberCompact;
  GC.formatScore = formatScore;
  GC.setScoreDisplayInstant = setScoreDisplayInstant;
  GC.fmtIntParts = fmtIntParts;
  GC.fmtNumber = fmtNumber;
  GC.fmtIntFull = fmtIntFull;
  GC.readNumberInput = readNumberInput;
  GC.setNumberInputValue = setNumberInputValue;
  GC.bindFormattedNumberInputs = bindFormattedNumberInputs;
  initFormattedNumberInputDelegation();
  GC.t = t;
  GC.tf = tf;

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
    _resetQueueLiveStates();
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
    if (path.endsWith("/vote-center")) return "vote_center";
    if (path.endsWith("/referrals")) return "referrals";
    if (path.endsWith("/galactic-politics")) return "galactic_politics";
    if (path.endsWith("/skilltree")) return "skilltree";
    if (path.endsWith("/premium")) return "premium";
    if (path.endsWith("/alliance")) return "alliance";
    if (path.endsWith("/shipyard")) return "shipyard";
    if (path.endsWith("/defense")) return "defense";
    if (path.endsWith("/empire")) return "empire";
    if (path.endsWith("/overview") || path === "/") return "overview";
    if (path.endsWith("/ranking")) return "ranking";
    if (path.endsWith("/hall-of-fame")) return "hall_of_fame";
    if (path.endsWith("/records")) return "records";
    if (path.endsWith("/messages")) return "messages";
    if (path.endsWith("/options")) return "options";
    if (path.endsWith("/galaxy")) return "galaxy";
    if (path.endsWith("/techtree")) return "techtree";
    if (path.endsWith("/admin")) return "admin";
    return "other";
  };

  GC.getServerNow = getTimerServerNow;
  GC.serverNow = getTimerServerNow;
  GC.syncServerClockFromState = syncServerClockFromState;

  GC.reloadCurrentPage = function reloadCurrentPage(opts) {
    if (opts && opts.fullDocument) {
      window.location.reload();
      return Promise.resolve();
    }
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
      if (p.lastInterval !== next) {
        p.lastInterval = next;
        scheduleGameStatePoll(next);
        console.debug("[GC] polling interval adjusted", next, "ms");
      } else {
        console.debug("[GC] polling already active", next, "ms");
      }
      return;
    }

    GC.stopPolling();

    p.running = true;
    p.started = true;
    p.lastInterval = next;
    console.debug("[GC] polling started", next, "ms");
    scheduleGameStatePoll(next);
  };

  function scheduleMessagesInboxBoot() {
    if (GC.detectPage() !== "messages") return;
    const repairInboxIfNeeded = () => {
      if (GC.detectPage() !== "messages") return;
      if (typeof GC.bootMessagesInbox !== "function") return;
      GC.bootMessagesInbox({ force: false, pjax: true });
    };
    const defer =
      typeof requestAnimationFrame === "function"
        ? (fn) => requestAnimationFrame(() => requestAnimationFrame(fn))
        : (fn) => queueMicrotask(fn);
    defer(repairInboxIfNeeded);
  }

  function runMessagesPageModule(retry = 0) {
    const mod = GC.modules?.messages;
    if (typeof mod !== "function" && typeof GC.initMessagesPage !== "function") {
      if (retry < 60) {
        const next =
          typeof requestAnimationFrame === "function" ? requestAnimationFrame : (fn) => setTimeout(fn, 16);
        next(() => runMessagesPageModule(retry + 1));
        return;
      }
      console.warn("[GC] messages module not loaded yet");
      return;
    }
    if (typeof mod === "function") {
      try {
        mod({ pjax: true });
      } catch (err) {
        console.error("[GC] page module error", "messages", err);
      }
    } else if (typeof GC.initMessagesPage === "function") {
      try {
        GC.initMessagesPage({ pjax: true });
      } catch (err) {
        console.error("[GC] messages init fallback error", err);
      }
    }
    scheduleMessagesInboxBoot();
  }

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
    syncFleetSubnav(page);

    if (typeof normalizePopoverTriggers === "function") {
      normalizePopoverTriggers(document.getElementById("main-content") || document);
    }

    const mod = GC.modules[page];
    if (page === "messages") {
      if (force) {
        const defer =
          typeof requestAnimationFrame === "function"
            ? (fn) => requestAnimationFrame(() => requestAnimationFrame(fn))
            : (fn) => queueMicrotask(fn);
        defer(runMessagesPageModule);
      } else {
        runMessagesPageModule();
      }
    } else if (typeof mod === "function") {
      try {
        mod();
      } catch (err) {
        console.error("[GC] page module error", page, err);
      }
    }

    initFlashAutohide();
    initMotdBanner();
    bootstrapScoreStateFromDom();
    bindFormattedNumberInputs(document.getElementById("main-content") || document);

    if (shouldRunGameLoop() && !skipHydrate) {
      hydratePageFromLastState({ skipMessagesUnread: page === "messages" });
    }

    if (!shouldRunGameLoop()) {
      console.debug("[GC] game loop skipped (auth/simple page)");
      initSimplePageAmbience();
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
      if (GC.detectPage() === "messages" && typeof GC.bootMessagesInbox === "function") {
        const st = GC.messagesPageState;
        if (!st || !st.listLoaded) {
          GC.bootMessagesInbox({ force: false, pjax: true });
        }
      }
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

  function getResearchActionState(tech, queueFull) {
    if (!tech.requirements_met) return "warn";
    if (queueFull) return "locked";
    if (tech.can_afford === false) return "afford";
    return "go";
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
    const state = getResearchActionState(tech, queueFull);

    if (state === "warn") {
      let lockTitle = t("research_requirements_not_met", "Voraussetzungen nicht erfüllt.");
      const reqHint = formatResearchReqTooltip(tech.requirements_items);
      if (reqHint) lockTitle += " · " + reqHint;
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--warn btn-research status-pill-icon-btn" type="button" disabled` +
        ` data-action-state="warn" title="${lockTitle}" aria-label="${lockTitle}"><span class="gc-bld-head-action-icon">⚠</span></button>`
      );
    }
    if (state === "locked") {
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--locked btn-research" type="button" disabled` +
        ` data-action-state="locked" aria-disabled="true" title="${fullLabel}" aria-label="${fullLabel}"><span class="gc-bld-head-action-icon">🔒</span></button>`
      );
    }
    if (state === "afford") {
      const shortMsg = t("research_not_enough_resources", "Nicht genug Ressourcen.");
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--afford btn-research" type="button" disabled` +
        ` data-action-state="afford" title="${shortMsg}" aria-label="${shortMsg}"><span class="gc-bld-head-action-icon">+</span></button>`
      );
    }
    const href = `/research_start/${encodeURIComponent(key)}`;
    return (
      `<a href="${href}" class="gc-bld-head-action-btn gc-bld-head-action-btn--go btn-research"` +
      ` data-action-state="go" title="${actionLabel}" aria-label="${actionLabel}"><span class="gc-bld-head-action-icon">+</span></a>`
    );
  }

  function syncResearchHeadAction(cell, tech, summary) {
    if (!cell || !tech) return;
    const count = summary?.count ?? 0;
    const limit = summary?.limit ?? 3;
    const queueFull = count >= limit;
    const state = getResearchActionState(tech, queueFull);
    const btn = cell.querySelector(".gc-bld-head-action-btn");
    const prevState = btn?.dataset?.actionState || "";
    const queueActive = count > 0;
    const actionLabel = queueActive
      ? t("research_btn_queue", "Anreihen")
      : t("research_btn_start", "Forschung starten");

    if (btn && prevState === state) {
      if (state === "go") {
        btn.title = actionLabel;
        btn.setAttribute("aria-label", actionLabel);
        const href = `/research_start/${encodeURIComponent(tech.key)}`;
        if (btn.getAttribute("href") !== href) btn.setAttribute("href", href);
      }
      return;
    }

    const html = renderResearchActionCell(tech, summary);
    if (cell.innerHTML.trim() !== html.trim()) cell.innerHTML = html;
  }

  function getBuildingActionState(b, bqQueueFull) {
    const isMax = (b.level >= b.max_level) || b.at_queue_max;
    if (isMax) return "max";
    if (!b.requirements_met) return "warn";
    if (bqQueueFull) return "locked";
    if (!b.can_afford) return "afford";
    return "go";
  }

  function renderBuildingActionCell(b, bqSummary, bqQueueFull) {
    const key = b.key;
    const btnUpgrade = t("buildings_btn_upgrade", "Ausbau starten");
    const btnMax = t("buildings_btn_max_level", "Max. Level");
    const fullLabel = t("buildings_btn_queue_full", "Warteschlange voll");
    const btnQueue = t("research_btn_queue", "Anreihen");
    const queueActive = (bqSummary?.count || 0) > 0;
    const actionLabel = queueActive ? btnQueue : btnUpgrade;
    const state = getBuildingActionState(b, bqQueueFull);

    if (state === "max") {
      return (
        `<span class="gc-bld-head-action-btn gc-bld-head-action-btn--max" data-action-state="max" title="${btnMax}"` +
        ` aria-label="${btnMax}"><span class="gc-bld-head-action-icon">✓</span></span>`
      );
    }
    if (state === "warn") {
      const lockTitle = t("msg_build_requirements", "Voraussetzungen nicht erfüllt.");
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--warn btn-upgrade status-pill-icon-btn" type="button" disabled` +
        ` data-action-state="warn" title="${lockTitle}" aria-label="${lockTitle}"><span class="gc-bld-head-action-icon">⚠</span></button>`
      );
    }
    if (state === "locked") {
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--locked btn-upgrade" type="button" disabled` +
        ` data-action-state="locked" aria-disabled="true" title="${fullLabel}" aria-label="${fullLabel}"><span class="gc-bld-head-action-icon">🔒</span></button>`
      );
    }
    if (state === "afford") {
      const shortMsg = t("msg_build_not_enough_resources", "Nicht genug Ressourcen.");
      return (
        `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--afford btn-upgrade" type="button" disabled` +
        ` data-action-state="afford" title="${shortMsg}" aria-label="${shortMsg}"><span class="gc-bld-head-action-icon">+</span></button>`
      );
    }
    const tab = b.tab || _getActiveBuildingTab();
    const href = `/upgrade/${encodeURIComponent(key)}?src=buildings&tab=${encodeURIComponent(tab)}`;
    return (
      `<a id="btn-${key}" data-building="${key}" data-action-state="go" href="${href}"` +
      ` class="gc-bld-head-action-btn gc-bld-head-action-btn--go btn-upgrade"` +
      ` title="${actionLabel}" aria-label="${actionLabel}"><span class="gc-bld-head-action-icon">+</span></a>`
    );
  }

  function syncBuildingHeadAction(cell, b, bqSummary, bqQueueFull) {
    if (!cell || !b) return;
    const state = getBuildingActionState(b, bqQueueFull);
    const btn = cell.querySelector(".gc-bld-head-action-btn");
    const prevState = btn?.dataset?.actionState || "";
    const queueActive = (bqSummary?.count || 0) > 0;
    const actionLabel = queueActive
      ? t("research_btn_queue", "Anreihen")
      : t("buildings_btn_upgrade", "Ausbau starten");

    if (btn && prevState === state) {
      if (state === "go") {
        btn.title = actionLabel;
        btn.setAttribute("aria-label", actionLabel);
        const tab = b.tab || _getActiveBuildingTab();
        const href = `/upgrade/${encodeURIComponent(b.key)}?src=buildings&tab=${encodeURIComponent(tab)}`;
        if (btn.getAttribute("href") !== href) btn.setAttribute("href", href);
      }
      return;
    }

    const html = renderBuildingActionCell(b, bqSummary, bqQueueFull);
    if (cell.innerHTML.trim() !== html.trim()) cell.innerHTML = html;
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
          syncBuildingHeadAction(actionCell, b, summary, bqQueueFull);
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
        _setIfChanged(levelEl, fmtNumber(tech.level || 0));
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
        syncResearchHeadAction(actionCell, tech, summary);
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
              : queueJobRemainingSeconds(endAt, getTimerServerNow(), act.remaining);
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
              : queueJobRemainingSeconds(endAt, getTimerServerNow(), act.remaining);
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

  function setScoreDisplayInstant(el, value) {
    if (!el) return;
    const v = Math.max(0, parseIntNumber(value));
    const st = _numAnim.get(el);
    if (st?.raf) cancelAnimationFrame(st.raf);
    _numAnim.delete(el);
    el.textContent = formatScore(v);
    el.title = formatNumber(v);
    el.dataset.numValue = String(v);
    _lastNum.set(el, v);
  }

  function animateNumber(el, target, opts = {}) {
    if (!el) return;

    const tgt = Math.max(0, Math.floor(Number(target || 0)));
    const displayFmt = opts.fmt || fmtNumber;
    // Compact score labels must not tween (9.999.999 ↔ 10 Mio. flickers the HUD).
    const tweenFmt = displayFmt === formatScore ? formatNumber : displayFmt;
    const syncTitle = (val) => {
      if (displayFmt === formatScore) el.title = formatNumber(val);
    };
    if (_prefersReducedMotion || !shouldRunVisualLoops()) {
      el.textContent = displayFmt(tgt);
      el.dataset.numValue = String(tgt);
      syncTitle(tgt);
      _lastNum.set(el, tgt);
      return;
    }
    const last = _lastNum.get(el);
    if (last === tgt) return;
    _lastNum.set(el, tgt);

    const { duration = 650, minStep = 1 } = opts;
    const now = performance.now();

    let cur = Number(el.dataset.numValue);
    if (!Number.isFinite(cur)) cur = parseIntNumber(el.getAttribute("title") || el.textContent);
    cur = Math.max(0, Math.floor(cur));

    const st = _numAnim.get(el);
    if (st && st.target === tgt) return;

    if (Math.abs(tgt - cur) <= minStep) {
      el.textContent = displayFmt(tgt);
      el.dataset.numValue = String(tgt);
      syncTitle(tgt);
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
      el.textContent = p < 1 ? tweenFmt(v) : displayFmt(v);
      el.dataset.numValue = String(v);

      if (p < 1) {
        state.raf = GC.requestFrame(tick);
        _numAnim.set(el, state);
      } else {
        el.textContent = displayFmt(state.target);
        el.dataset.numValue = String(state.target);
        syncTitle(state.target);
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

  function bootstrapScoreStateFromDom() {
    const hud = document.getElementById("hud-score-total");
    if (!hud) return;
    let domTotal = Number(hud.dataset.numValue);
    if (!Number.isFinite(domTotal)) {
      domTotal = parseIntNumber(hud.getAttribute("title") || hud.textContent);
    }
    if (!Number.isFinite(domTotal) || domTotal < 0) return;
    if (_scoreState.lastServerTotal === null) _scoreState.lastServerTotal = domTotal;
    if (_scoreState.lastAnimatedTotal === null) _scoreState.lastAnimatedTotal = domTotal;
  }

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
    deltaEl.textContent = `${sign}${formatScore(d)}`;
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

  function _setSubnavGroupExpanded(groupEl, parentEl, expanded) {
    if (groupEl) groupEl.classList.toggle("is-expanded", expanded);
    if (parentEl) parentEl.setAttribute("aria-expanded", expanded ? "true" : "false");
  }

  function syncBuildingsSubnavFromState() {
    const group = document.querySelector(".gc-nav-buildings-group");
    if (!group) return;
    const state = readNavSectionState();
    setNavGroupExpanded(group, resolveNavGroupExpanded(group, state), false);
  }

  function hideBuildingsSubnav() {
    syncBuildingsSubnavFromState();
  }

  function showBuildingsSubnav() {
    syncBuildingsSubnavFromState();
  }

  function syncBuildingSidebarTab(tab) {
    const sub = document.getElementById("gc-nav-buildings-sub");
    if (!sub) return;
    if (tab == null || tab === "") {
      sub.querySelectorAll("[data-building-tab]").forEach((el) => el.classList.remove("active"));
      return;
    }
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
        e.preventDefault();
        const tab = subBtn.dataset.buildingTab || "resources";
        if (GC.detectPage() !== "buildings") {
          GC.navigateTo(`/buildings?tab=${encodeURIComponent(tab)}`);
          return;
        }
        activateBuildingTabByName(tab, subBtn);
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
    initBuildingTechnicalData();
    syncBuildingsSubnavFromState();
    const pageRoot = document.querySelector("[data-buildings-page]");
    if (!pageRoot) return;
    const initialTab = pageRoot.dataset.activeBuildingTab || "resources";
    activateBuildingTabByName(initialTab, null);
    GC.startProgressTicker();
    GC.registerCleanup(hideBuildingsSubnav);
  }

  const BUILDING_TECH = {
    root: null,
    titleEl: null,
    descEl: null,
    tableWrap: null,
    tbody: null,
    loadingEl: null,
    errorEl: null,
    colTime: null,
    colEnergy: null,
    abort: null,
    open: false,
    reqId: 0,
  };

  function cacheBuildingTechElements() {
    if (BUILDING_TECH.root && BUILDING_TECH.tbody) return BUILDING_TECH.root;
    BUILDING_TECH.root = document.getElementById("gc-building-tech-root");
    if (!BUILDING_TECH.root) return null;
    BUILDING_TECH.titleEl = document.getElementById("gc-building-tech-title");
    BUILDING_TECH.descEl = BUILDING_TECH.root.querySelector("[data-bt-desc]");
    BUILDING_TECH.tableWrap = BUILDING_TECH.root.querySelector("[data-bt-table-wrap]");
    BUILDING_TECH.tbody = BUILDING_TECH.root.querySelector("[data-bt-tbody]");
    BUILDING_TECH.loadingEl = BUILDING_TECH.root.querySelector("[data-bt-loading]");
    BUILDING_TECH.errorEl = BUILDING_TECH.root.querySelector("[data-bt-error]");
    BUILDING_TECH.colTime = BUILDING_TECH.root.querySelector("[data-bt-col-time]");
    BUILDING_TECH.colEnergy = BUILDING_TECH.root.querySelector("[data-bt-col-energy]");
    return BUILDING_TECH.root;
  }

  function formatTechnicalOutputPart(row) {
    if (!row || typeof row !== "object") return "";
    const kind = String(row.effect_kind || "level");
    const val = row.effect_value;
    if (val == null || val === "") return "";
    const unit = row.effect_unit || "";
    const metricKey = row.effect_metric_key ? t(row.effect_metric_key, "") : "";
    const metricPrefix = metricKey ? `${metricKey}: ` : "";
    if (kind === "production") {
      const res = row.effect_resource ? t("resource_" + row.effect_resource, row.effect_resource) : "";
      return `${metricPrefix}+${fmtNumber(val)}${unit}${res ? " " + res : ""}`;
    }
    if (kind === "energy") {
      return `${metricPrefix}${fmtNumber(val)} ${t("energy", "Energie")}`;
    }
    if (kind === "energy_use") {
      return `${metricPrefix}-${fmtNumber(val)} ${t("buildings_technical_energy_use", "Verbrauch")}`;
    }
    if (kind === "storage") {
      const res = row.effect_resource ? t("resource_" + row.effect_resource, row.effect_resource) : "";
      return `${metricPrefix}${fmtNumber(val)}${res ? " " + res : ""}`;
    }
    if (kind === "bonus_percent") {
      return `${metricPrefix}+${fmtNumber(val)}${unit || "%"}`;
    }
    if (kind === "reduction_percent") {
      return `${metricPrefix}-${fmtNumber(val)}${unit || "%"}`;
    }
    if (kind === "max_level" || kind === "scan" || kind === "level") {
      return `${metricPrefix}${fmtNumber(val)}`;
    }
    if (kind === "yard_production") {
      const capCompact = formatNumberCompact(val);
      const reduction = Number(row.build_time_reduction_percent || 0);
      if (reduction > 0) {
        return tf(
          "buildings_technical_yard_compact_with_reduction",
          { capacity: capCompact, percent: fmtNumber(reduction) },
          `${capCompact} · -${fmtNumber(reduction)}%`
        );
      }
      return tf(
        "buildings_technical_yard_capacity_compact",
        { capacity: capCompact },
        capCompact
      );
    }
    if (kind === "defense_unlock") {
      return "";
    }
    if (kind === "yard_reference") {
      return tf(
        "buildings_technical_yard_ref_compact",
        { capacity: formatNumberCompact(val) },
        formatNumberCompact(val)
      );
    }
    return `${metricPrefix}${fmtNumber(val)}`;
  }

  function formatTechnicalOutputTitle(row) {
    if (!row || typeof row !== "object") return "";
    const kind = String(row.effect_kind || "");
    if (kind === "yard_production") {
      const capFull = fmtNumber(row.effect_value ?? row.yard_batch_capacity ?? 0);
      const parts = [
        tf("buildings_technical_yard_capacity_row", { capacity: capFull }, `Werftkapazität ${capFull}`),
      ];
      const reduction = Number(row.build_time_reduction_percent || 0);
      if (reduction > 0) {
        parts.push(
          tf(
            "buildings_technical_build_time_reduction",
            { percent: fmtNumber(reduction) },
            `-${fmtNumber(reduction)}% Zyklus`
          )
        );
      }
      const light = row.parallel_light;
      const medium = row.parallel_medium;
      const heavy = row.parallel_heavy;
      if (light != null && medium != null && heavy != null) {
        parts.push(
          tf(
            "buildings_technical_parallel_examples",
            {
              light: fmtNumber(light),
              medium: fmtNumber(medium),
              heavy: fmtNumber(heavy),
            },
            `Parallel z. B. ${fmtNumber(light)} / ${fmtNumber(medium)} / ${fmtNumber(heavy)}`
          )
        );
      }
      return parts.join(" · ");
    }
    if (kind === "defense_unlock") {
      const parts = [
        tf(
          "buildings_technical_defense_unlock_row",
          { level: fmtNumber(row.effect_value ?? 0) },
          `Freischaltung Stufe ${fmtNumber(row.effect_value ?? 0)}`
        ),
      ];
      if (row.secondary_effect) {
        const secTitle = formatTechnicalOutputTitle(row.secondary_effect);
        if (secTitle) parts.push(secTitle);
      }
      return parts.join(" · ");
    }
    if (kind === "yard_reference") {
      const yardLevel = row.yard_level != null ? fmtNumber(row.yard_level) : "";
      const capFull = fmtNumber(row.effect_value ?? 0);
      if (yardLevel) {
        return tf(
          "buildings_technical_yard_reference",
          { level: yardLevel, capacity: capFull },
          `Orbitalwerft Stufe ${yardLevel}: Kapazität ${capFull}`
        );
      }
      return tf(
        "buildings_technical_yard_capacity_row",
        { capacity: capFull },
        `Werftkapazität ${capFull}`
      );
    }
    return "";
  }

  function formatTechnicalOutput(row) {
    const primary = formatTechnicalOutputPart(row);
    const sec = row?.secondary_effect;
    const secondary = sec ? formatTechnicalOutputPart(sec) : "";
    if (primary && secondary) return `${primary} · ${secondary}`;
    return primary || secondary || "—";
  }

  function formatTechnicalEnergy(row) {
    if (row?.energy_use != null) return `-${fmtNumber(row.energy_use)}`;
    if (row?.energy_total != null) return fmtNumber(row.energy_total);
    return "—";
  }

  function setTechnicalModalMode(kind) {
    if (!cacheBuildingTechElements()) return;
    const isResearch = kind === "research";
    if (BUILDING_TECH.colTime) {
      BUILDING_TECH.colTime.textContent = isResearch
        ? t("research_technical_col_time", "Forschungszeit")
        : t("buildings_technical_col_time", "Bauzeit");
    }
    if (BUILDING_TECH.colEnergy) {
      BUILDING_TECH.colEnergy.hidden = isResearch;
    }
    BUILDING_TECH.root?.classList.toggle("gc-building-tech-modal--research", isResearch);
  }

  function setTechnicalModalDescription(data) {
    if (!BUILDING_TECH.descEl) return;
    const descKey = String(data?.description_key || "").trim();
    let desc = descKey ? t(descKey, "") : "";
    if (!desc || desc === descKey || desc.startsWith("desc_")) {
      desc = "";
    }
    if (desc) {
      BUILDING_TECH.descEl.textContent = desc;
      BUILDING_TECH.descEl.hidden = false;
    } else {
      BUILDING_TECH.descEl.textContent = "";
      BUILDING_TECH.descEl.hidden = true;
    }
  }

  function renderBuildingTechnicalTable(data) {
    if (!BUILDING_TECH.tbody || !BUILDING_TECH.tableWrap) return;
    const kind = data?.kind === "research" ? "research" : "building";
    setTechnicalModalMode(kind);
    setTechnicalModalDescription(data);
    const levels = Array.isArray(data?.levels) ? data.levels : [];
    const currentLabel = t("buildings_technical_current_level", "Aktuell");
    const showEnergy = kind !== "research";
    BUILDING_TECH.tbody.innerHTML = levels
      .map((row) => {
        const cls = row.is_current ? "gc-building-tech-row gc-building-tech-row--current" : "gc-building-tech-row";
        const levelNum = fmtNumber(row.level);
        const levelCell = row.is_current
          ? `<span class="gc-building-tech-level">` +
            `<span class="gc-building-tech-current-badge">${currentLabel}</span>` +
            `<span class="gc-building-tech-level-num">${levelNum}</span></span>`
          : `<span class="gc-building-tech-level"><span class="gc-building-tech-level-num">${levelNum}</span></span>`;
        const energyCell = showEnergy
          ? `<td class="gc-mono">${escapeHtml(formatTechnicalEnergy(row))}</td>`
          : "";
        const outputText = formatTechnicalOutput(row);
        const outputTitle = formatTechnicalOutputTitle(row);
        const outputCell = outputTitle
          ? `<td class="gc-mono gc-num-compact gc-building-tech-col-output" title="${escapeHtml(outputTitle)}">${escapeHtml(outputText)}</td>`
          : `<td class="gc-mono gc-num-compact gc-building-tech-col-output">${escapeHtml(outputText)}</td>`;
        return (
          `<tr class="${cls}">` +
          `<td class="gc-mono gc-building-tech-col-level">${levelCell}</td>` +
          outputCell +
          `<td class="gc-mono">${fmtNumber(row.cost_metal || 0)}</td>` +
          `<td class="gc-mono">${fmtNumber(row.cost_crystal || 0)}</td>` +
          `<td class="gc-mono">${escapeHtml(formatDuration(row.time_seconds || 0))}</td>` +
          energyCell +
          `</tr>`
        );
      })
      .join("");
    BUILDING_TECH.tableWrap.hidden = levels.length === 0;
  }

  function setBuildingTechLoading(on) {
    if (BUILDING_TECH.loadingEl) BUILDING_TECH.loadingEl.hidden = !on;
    if (BUILDING_TECH.root) BUILDING_TECH.root.classList.toggle("is-loading", !!on);
  }

  function setBuildingTechError(msg) {
    if (!BUILDING_TECH.errorEl) return;
    if (msg) {
      BUILDING_TECH.errorEl.hidden = false;
      BUILDING_TECH.errorEl.textContent = msg;
    } else {
      BUILDING_TECH.errorEl.hidden = true;
      BUILDING_TECH.errorEl.textContent = "";
    }
  }

  function openBuildingTechnicalModal(focusClose) {
    if (!cacheBuildingTechElements()) return;
    BUILDING_TECH.open = true;
    BUILDING_TECH.root.hidden = false;
    BUILDING_TECH.root.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-building-tech-open");
    const closeBtn = BUILDING_TECH.root.querySelector("[data-bt-close].gc-player-card-close");
    if (focusClose && closeBtn) closeBtn.focus();
  }

  function closeBuildingTechnicalModal() {
    if (BUILDING_TECH.abort) {
      BUILDING_TECH.abort.abort();
      BUILDING_TECH.abort = null;
    }
    if (!BUILDING_TECH.root) return;
    BUILDING_TECH.open = false;
    BUILDING_TECH.root.hidden = true;
    BUILDING_TECH.root.setAttribute("aria-hidden", "true");
    document.body.classList.remove("gc-building-tech-open");
    setBuildingTechLoading(false);
    setBuildingTechError("");
    if (BUILDING_TECH.tableWrap) BUILDING_TECH.tableWrap.hidden = true;
    if (BUILDING_TECH.tbody) BUILDING_TECH.tbody.innerHTML = "";
    if (BUILDING_TECH.descEl) {
      BUILDING_TECH.descEl.textContent = "";
      BUILDING_TECH.descEl.hidden = true;
    }
    setTechnicalModalMode("building");
  }

  async function loadBuildingTechnicalData(buildingType) {
    if (!cacheBuildingTechElements()) return;
    const key = String(buildingType || "").trim();
    if (!key) return;

    if (BUILDING_TECH.abort) BUILDING_TECH.abort.abort();
    BUILDING_TECH.abort = new AbortController();
    const reqId = ++BUILDING_TECH.reqId;

    setBuildingTechError("");
    setBuildingTechLoading(true);
    if (BUILDING_TECH.tableWrap) BUILDING_TECH.tableWrap.hidden = true;
    openBuildingTechnicalModal(true);

    try {
      const res = await GC.fetchJSON(`/api/buildings/${encodeURIComponent(key)}/technical-data`, {
        cache: "no-store",
        signal: BUILDING_TECH.abort.signal,
      });
      if (reqId !== BUILDING_TECH.reqId) return;
      if (!res?.ok || !res.data) {
        setBuildingTechError(t("buildings_technical_load_error", "Technische Daten konnten nicht geladen werden."));
        return;
      }
      const labelKey = res.data.label_key || key;
      if (BUILDING_TECH.titleEl) {
        BUILDING_TECH.titleEl.textContent =
          `${t(labelKey, key)} · ${t("buildings_technical_modal_title", "Technische Daten")}`;
      }
      renderBuildingTechnicalTable(res.data);
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (reqId !== BUILDING_TECH.reqId) return;
      setBuildingTechError(t("buildings_technical_load_error", "Technische Daten konnten nicht geladen werden."));
    } finally {
      if (reqId === BUILDING_TECH.reqId) setBuildingTechLoading(false);
    }
  }

  async function loadResearchTechnicalData(techKey) {
    if (!cacheBuildingTechElements()) return;
    const key = String(techKey || "").trim();
    if (!key) return;

    if (BUILDING_TECH.abort) BUILDING_TECH.abort.abort();
    BUILDING_TECH.abort = new AbortController();
    const reqId = ++BUILDING_TECH.reqId;

    setBuildingTechError("");
    setBuildingTechLoading(true);
    if (BUILDING_TECH.tableWrap) BUILDING_TECH.tableWrap.hidden = true;
    openBuildingTechnicalModal(true);

    try {
      const res = await GC.fetchJSON(`/api/research/${encodeURIComponent(key)}/technical-data`, {
        cache: "no-store",
        signal: BUILDING_TECH.abort.signal,
      });
      if (reqId !== BUILDING_TECH.reqId) return;
      if (!res?.ok || !res.data) {
        setBuildingTechError(t("buildings_technical_load_error", "Technische Daten konnten nicht geladen werden."));
        return;
      }
      const labelKey = res.data.label_key || key;
      if (BUILDING_TECH.titleEl) {
        BUILDING_TECH.titleEl.textContent =
          `${t(labelKey, key)} · ${t("buildings_technical_modal_title", "Technische Daten")}`;
      }
      renderBuildingTechnicalTable(res.data);
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (reqId !== BUILDING_TECH.reqId) return;
      setBuildingTechError(t("buildings_technical_load_error", "Technische Daten konnten nicht geladen werden."));
    } finally {
      if (reqId === BUILDING_TECH.reqId) setBuildingTechLoading(false);
    }
  }

  function onBuildingTechnicalClick(e) {
    const closeEl = e.target.closest("[data-bt-close]");
    if (closeEl && BUILDING_TECH.root && !BUILDING_TECH.root.hidden) {
      e.preventDefault();
      closeBuildingTechnicalModal();
      return;
    }
    const buildingTrigger = e.target.closest("[data-building-tech-data]");
    if (buildingTrigger) {
      e.preventDefault();
      loadBuildingTechnicalData(buildingTrigger.getAttribute("data-building-tech-data"));
      return;
    }
    const researchTrigger = e.target.closest("[data-research-tech-data]");
    if (researchTrigger) {
      e.preventDefault();
      loadResearchTechnicalData(researchTrigger.getAttribute("data-research-tech-data"));
    }
  }

  function onBuildingTechnicalKeydown(e) {
    if (e.key === "Escape" && BUILDING_TECH.open) {
      e.preventDefault();
      closeBuildingTechnicalModal();
    }
  }

  function initBuildingTechnicalDataOnce() {
    if (GC._buildingTechBound) return;
    GC._buildingTechBound = true;
    document.addEventListener("click", onBuildingTechnicalClick);
    document.addEventListener("keydown", onBuildingTechnicalKeydown);
    GC.registerCleanup(() => {
      closeBuildingTechnicalModal();
    });
  }

  function initBuildingTechnicalData() {
    initBuildingTechnicalDataOnce();
  }

  GC.openBuildingTechnicalData = loadBuildingTechnicalData;
  GC.openResearchTechnicalData = loadResearchTechnicalData;

  const TRADING_NAV_PAGES = new Set([
    "trader_hub",
    "inventory",
    "auction_house",
    "vote_center",
    "galactic_politics",
    "skilltree",
    "premium",
  ]);
  const MILITARY_NAV_PAGES = new Set(["shipyard", "defense"]);
  const FLEET_NAV_PAGES = new Set(["fleet", "logistics"]);
  const BUILDINGS_NAV_PAGES = new Set(["buildings"]);

  function isTradingNavPage(page) {
    return TRADING_NAV_PAGES.has(String(page || ""));
  }

  function isMilitaryNavPage(page) {
    return MILITARY_NAV_PAGES.has(String(page || ""));
  }

  function isFleetNavPage(page) {
    return FLEET_NAV_PAGES.has(String(page || ""));
  }

  function isBuildingsNavPage(page) {
    return BUILDINGS_NAV_PAGES.has(String(page || ""));
  }

  function hideTradingSubnav() {
    const sub = document.getElementById("gc-nav-trading-sub");
    if (!sub) return;
    sub.hidden = true;
    sub.classList.add("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "true");
    _setSubnavGroupExpanded(
      document.querySelector(".gc-nav-trading-group"),
      document.getElementById("gc-nav-trading-parent"),
      false
    );
  }

  function showTradingSubnav() {
    const sub = document.getElementById("gc-nav-trading-sub");
    if (!sub) return;
    sub.hidden = false;
    sub.classList.remove("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "false");
    _setSubnavGroupExpanded(
      document.querySelector(".gc-nav-trading-group"),
      document.getElementById("gc-nav-trading-parent"),
      true
    );
  }

  function syncTradingSubnav(page) {
    const sub = document.getElementById("gc-nav-trading-sub");
    const parent = document.getElementById("gc-nav-trading-parent");
    if (!sub || !parent) return;

    const activePage = page || GC.detectPage();
    const onTradingPage = isTradingNavPage(activePage);

    parent.classList.remove("active");
    sub.querySelectorAll("[data-trading-nav]").forEach((el) => {
      el.classList.toggle("active", onTradingPage && el.dataset.tradingNav === activePage);
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
    _setSubnavGroupExpanded(
      document.querySelector(".gc-nav-military-group"),
      document.getElementById("gc-nav-military-parent"),
      false
    );
  }

  function showMilitarySubnav() {
    const sub = document.getElementById("gc-nav-military-sub");
    if (!sub) return;
    sub.hidden = false;
    sub.classList.remove("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "false");
    _setSubnavGroupExpanded(
      document.querySelector(".gc-nav-military-group"),
      document.getElementById("gc-nav-military-parent"),
      true
    );
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

  function hideFleetSubnav() {
    const sub = document.getElementById("gc-nav-fleet-sub");
    if (!sub) return;
    sub.hidden = true;
    sub.classList.add("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "true");
    _setSubnavGroupExpanded(
      document.querySelector(".gc-nav-fleet-group"),
      document.getElementById("gc-nav-fleet-parent"),
      false
    );
  }

  function showFleetSubnav() {
    const sub = document.getElementById("gc-nav-fleet-sub");
    if (!sub) return;
    sub.hidden = false;
    sub.classList.remove("gc-nav-sub--collapsed");
    sub.setAttribute("aria-hidden", "false");
    _setSubnavGroupExpanded(
      document.querySelector(".gc-nav-fleet-group"),
      document.getElementById("gc-nav-fleet-parent"),
      true
    );
  }

  function syncFleetSubnav(page) {
    const sub = document.getElementById("gc-nav-fleet-sub");
    const parent = document.getElementById("gc-nav-fleet-parent");
    if (!sub || !parent) return;

    const activePage = page || GC.detectPage();
    const onFleetPage = isFleetNavPage(activePage);

    parent.classList.toggle("active", onFleetPage);
    sub.querySelectorAll("[data-fleet-nav]").forEach((el) => {
      el.classList.toggle("active", el.dataset.fleetNav === activePage);
    });

    if (onFleetPage) {
      showFleetSubnav();
      return;
    }
    hideFleetSubnav();
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
      const btn = cell.querySelector(".gc-bld-head-action-btn");
      const state = btn?.dataset?.actionState || "";

      if (queueFull && state === "go") {
        cell.innerHTML =
          `<button class="gc-bld-head-action-btn gc-bld-head-action-btn--locked btn-upgrade" type="button" disabled` +
          ` data-action-state="locked" aria-disabled="true" title="${fullLabel}" aria-label="${fullLabel}"><span class="gc-bld-head-action-icon">🔒</span></button>`;
        return;
      }

      if (!queueFull && state === "locked") {
        const href = `/upgrade/${encodeURIComponent(bType)}?src=buildings&tab=${encodeURIComponent(tab)}`;
        cell.innerHTML =
          `<a id="btn-${bType}" data-building="${bType}" data-action-state="go" href="${href}"` +
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
    if (!chip || chip.querySelector(".gc-card-queue-timer")) return;
    const label = formatDuration(seconds);
    chip.title = title || chip.title || "";
    let textEl = chip.querySelector(".gc-hero-time-text");
    if (!textEl) {
      chip.innerHTML = `<span class="gc-hero-time-text">${label}</span>`;
      return;
    }
    _setIfChanged(textEl, label);
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
    const st = Number(GC.lastState?.server_now ?? GC.lastState?.server_time ?? 0);
    if (st) {
      const approx = serverNow();
      if (!TIME.serverNow || st > approx - 0.5) setServerTime(st);
    }
    return serverNow();
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
    const now = getTimerServerNow();
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
          getTimerServerNow(),
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

  /** GC-557 — drop cached queue timer state (planet switch / PJAX cleanup). */
  function _resetQueueLiveStates() {
    BUILDQ.active.finishTime = 0;
    BUILDQ.active.totalSeconds = 0;
    RESEARCHQ.active.finishTime = 0;
    RESEARCHQ.active.totalSeconds = 0;
    SHIPYARDQ.active.finishTime = 0;
    SHIPYARDQ.active.totalSeconds = 0;
    DEFENSEQ.active.finishTime = 0;
    DEFENSEQ.active.totalSeconds = 0;
    _buildZeroHandled = "";
    _productionZeroHandled.shipyard = "";
    _productionZeroHandled.defense = "";
  }

  function updateAllProgressBars(serverNow) {
    const serverNowTs = Number.isFinite(serverNow) ? serverNow : getTimerServerNow();

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
            requestProductionCompletionSync({ gameState: true, defense: true });
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

  function updateNavBadges(navBadges) {
    const badges = navBadges && typeof navBadges === "object" ? navBadges : {};
    document.querySelectorAll("[data-nav-badge]").forEach((el) => {
      const key = el.getAttribute("data-nav-badge");
      if (!key) return;
      const entry = badges[key];
      if (!entry || !entry.active) {
        el.textContent = "";
        el.hidden = true;
        el.classList.add("hidden");
        el.setAttribute("aria-hidden", "true");
        el.removeAttribute("aria-label");
        return;
      }
      const count = Math.max(0, Number(entry.count) || 0);
      const label = entry.label != null && String(entry.label) !== ""
        ? String(entry.label)
        : (count > 0 ? String(count > 99 ? "99+" : count) : "!");
      el.textContent = label;
      el.hidden = false;
      el.classList.remove("hidden");
      el.setAttribute("aria-hidden", "false");
      const ariaKey = key === "vote_center"
        ? "nav_badge_vote_center_aria"
        : key === "government"
          ? "nav_badge_government_aria"
          : key === "referrals"
            ? "nav_badge_referrals_aria"
            : key === "community"
              ? "nav_badge_community_aria"
              : "";
      if (ariaKey) {
        el.setAttribute(
          "aria-label",
          t(ariaKey, key === "vote_center"
            ? "Vote verfügbar"
            : key === "referrals"
              ? "Referral-Belohnung verfügbar"
              : "Abstimmung offen")
        );
      }
    });
  }
  GC.updateNavBadges = updateNavBadges;

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
          setScoreDisplayInstant(hudScoreEl, serverTotal);
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

    if (data.nav_badges) {
      updateNavBadges(data.nav_badges);
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
      setScoreDisplayInstant(ovScoreVal, serverTotal);
    }
    if (ovScoreRank) {
      ovScoreRank.textContent = (rank >= 1 && totalPlayers > 0) ? `#${rank}/${totalPlayers}` : "#–/–";
    }
    if (ovScoreBuild) animateNumber(ovScoreBuild, scoreBuildings, { duration: 650, fmt: formatScore });
    if (ovScoreRes) animateNumber(ovScoreRes, scoreResearch, { duration: 650, fmt: formatScore });
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
    const slice = data?.shipyard;
    if (slice && typeof slice === "object") {
      const inner = slice.ships && typeof slice.ships === "object" ? slice.ships : null;
      if (inner && inner.ready !== false) {
        applyShipyardState(page, {
          ...inner,
          shipyard_queue: slice.queue || inner.shipyard_queue,
        });
        return;
      }
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
    if (onShipyard && completionReason && !data?.shipyard && !data?.shipyard_queue) {
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

      syncServerClockFromState(data);

      const activePlanetId = Number(data.active_planet_id || data.build_queue?.planet_id || 0);
      if (!hudOnly) {
        if (
          _last.activePlanetId !== null &&
          activePlanetId > 0 &&
          _last.activePlanetId !== activePlanetId
        ) {
          // Build queue is per active colony — never reuse the previous planet's panel state.
          _lastQueueSignature = "";
          _lastResearchQueueSignature = "";
          _lastShipyardQueueSignature = "";
          _lastDefenseQueueSignature = "";
          _resetQueueLiveStates();
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

        if (typeof GC.syncRoleBasedSidebar === "function") {
          GC.syncRoleBasedSidebar(data);
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

      // --- Queue tracking (always — ticker intervals / polling cadence) ---
      let queueList = [];
      if (Array.isArray(buildQueueRaw)) queueList = buildQueueRaw;
      else if (buildQueueRaw && Array.isArray(buildQueueRaw.queue)) queueList = buildQueueRaw.queue;

      const activeJob = queueList.length > 0 ? queueList[0] : null;
      _syncBuildQueueLiveState(queueList);

      const researchQueue = Array.isArray(research.queue) ? research.queue : (activeResearch ? [activeResearch] : []);
      _syncResearchQueueLiveState(researchQueue);

      if (data.shipyard?.queue) {
        const syJobs = Array.isArray(data.shipyard.queue.queue) ? data.shipyard.queue.queue : [];
        _syncShipyardQueueLiveState(syJobs);
      } else if (data.shipyard_queue) {
        const syJobs = Array.isArray(data.shipyard_queue.queue) ? data.shipyard_queue.queue : [];
        _syncShipyardQueueLiveState(syJobs);
      }
      if (data.defense) {
        const defSlice = data.defense.queue || data.defense.defense_queue;
        const defQ = defSlice?.queue ?? defSlice;
        if (Array.isArray(defQ)) _syncDefenseQueueLiveState(defQ);
      }

      const hasActiveBuild = !!activeJob;
      const bqLimitFinal = buildQueueRaw?.summary?.limit ?? 3;
      const bqCountFinal = buildQueueRaw?.summary?.count ?? queueList.length;
      lastBuildQueueCount = bqCountFinal;
      lastBuildQueueFull = bqCountFinal >= bqLimitFinal;
      lastHadActiveJob = hasActiveBuild;

      const hasActiveResearchNow = researchQueue.length > 0;
      const rqLimitFinal = research?.summary?.limit ?? 3;
      const rqCountFinal = research?.summary?.count ?? researchQueue.length;
      lastResearchQueueCount = rqCountFinal;
      lastResearchQueueFull = rqCountFinal >= rqLimitFinal;
      lastHadActiveResearch = hasActiveResearchNow;
      lastHadActiveShipyard = SHIPYARDQ.active.finishTime > getTimerServerNow();

      if (shouldPatchGameStateModule("overview")) {
        patchOverviewScoreFromState(data);

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

        const ovEff = document.getElementById("overview-efficiency");
        if (ovEff) {
          const pct = Number.isFinite(Number(data.energy_efficiency_pct))
            ? Math.round(Number(data.energy_efficiency_pct))
            : 100;
          _setIfChanged(ovEff, pct);
        }

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
        }

        patchOverviewResearch(research);
        patchOverviewStatus(data.overview, data, buildings, prod);
        if (data.planet_teaser) patchPlanetTeaser(data.planet_teaser);
      }

      if (shouldPatchGameStateModule("buildings")) {
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

      if (data.buildings_panel) {
        patchBuildingPanel(data.buildings_panel, buildQueueRaw);
      }
      }

      if (shouldPatchGameStateModule("research")) {
        patchResearchPanelFromState(data);
        updateResearchQueueActions(research);

        if (activeResearch) {
          const totalSec = Math.max(
            1,
            parseInt(activeResearch.total_seconds, 10) ||
              parseInt(activeResearch.total, 10) ||
              (resolveQueueJobRemaining(activeResearch) || 0) + 1
          );
          const totalLabel = document.getElementById("research-total");
          if (totalLabel) _setIfChanged(totalLabel, `${totalSec}s`);
        }
      }

      if (shouldPatchGameStateModule("trader")) {
        if (data.exchange) patchExchangePanel(data.exchange);
        if (data.scrapyard) patchScrapyardPanel(data.scrapyard);
        if (data.auction_house) patchAuctionHousePanel(data.auction_house);
        patchTraderHubBalance(metal, crystal, storageMetal, storageCrystal, fuelCells, storageFuelCells);
      }

      if (shouldPatchGameStateModule("shipyard")) {
        patchShipyardPanelFromState(data, activePlanetId);
      }

      if (shouldPatchGameStateModule("research") && research.techs) {
        patchResearchPanel(research.techs, research);
      }

      const stApplied = Number(data.server_time || 0);
      if (stApplied) _lastAppliedServerTime = Math.max(_lastAppliedServerTime, stApplied);

      GC.lastState = coercePollUnreadForHud(data, reason);
      GC.startProgressTicker();
      _maybeRefreshStaleMovementCountdowns();
      if (shouldPatchGameStateModule("shipyard") || shouldPatchGameStateModule("defense")) {
        syncProductionPanelsAfterGameState(data, reason, activePlanetId);
      }
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
        syncServerClockFromState(data);

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
          amount: formatNumber(params.amount || effect.amount || 0),
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

    if (effect.kind === "exchange") {
      const inName = t(`inv_${params.input_key}`, params.input_key || "");
      const outName = t(`inv_${params.output_key}`, params.output_key || "");
      const key = effect.message_key || "inv_effect_exchange";
      return tf(
        key,
        {
          ...params,
          input_name: inName,
          output_name: outName,
        },
        "%(input_amount)s× %(input_name)s zu %(output_amount)s× %(output_name)s verbessert."
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
      no_research_queue: t("inv_error_no_research_queue", "Keine Forschung in der Warteschlange."),
      no_shipyard_queue: t("inv_error_no_shipyard_queue", "Keine Schiffsbauaufträge in der Warteschlange."),
      no_effect_target: t("inv_error_no_effect_target", "Kein gültiges Ziel für dieses Item."),
      no_matching_research: t("inv_error_no_matching_research", "Keine passende aktive Forschung für diesen Datenkern."),
      insufficient_items: t("inv_error_insufficient_items", "Nicht genug Items im Inventar."),
      insufficient_materials: t("inv_error_insufficient_materials", "Nicht genug Material im Inventar."),
      invalid_recipe: t("inv_error_invalid_recipe", "Unbekanntes Rezept."),
      item_not_usable: t("inv_error_item_not_usable", "Dieses Item kann nicht benutzt werden."),
      invalid_item: t("inv_error_invalid_item", "Unbekanntes Item."),
      inventory_unavailable: t("inv_unavailable", "Inventar ist derzeit nicht verfügbar."),
      inventory_action_failed: t("inv_error_action_failed", "Inventar-Aktion ist fehlgeschlagen."),
    };
    return map[reason] || t("msg_generic_error", "Aktion fehlgeschlagen.");
  }

  const INVENTORY_ACTION_TIMEOUT_MS = 15000;

  async function runInventoryAction(buttons, url, payload, onSuccess) {
    const btnList = (Array.isArray(buttons) ? buttons : [buttons]).filter(Boolean);
    if (!btnList.length) return;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), INVENTORY_ACTION_TIMEOUT_MS);
    btnList.forEach((btn) => lockInventoryActionBtn(btn));

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify(payload),
        credentials: "same-origin",
        redirect: "manual",
        signal: controller.signal,
      });
      const ct = (res.headers.get("content-type") || "").toLowerCase();
      let json = {};
      if (ct.includes("application/json")) {
        try {
          json = await res.json();
        } catch (_) {}
      }
      if (res.status === 401 || res.status === 403 || json.error === "not_logged_in") {
        if (typeof handleAuthFailure === "function") handleAuthFailure(`inventory-action-http-${res.status}`);
        if (typeof throwAuthError === "function") throwAuthError();
      }
      if (!json || json.ok !== true) {
        const reason = json?.reason || (res.status >= 500 ? "inventory_action_failed" : "generic");
        const msg =
          json?.message ||
          (res.status >= 500
            ? t("inv_error_action_retry", "Inventar-Aktion fehlgeschlagen. Bitte erneut versuchen.")
            : inventoryUseReasonText(reason));
        console.warn("[GC] inventory action failed:", reason, res.status, json);
        showNotify(msg, "error");
        scrollInventoryToFeedback();
        patchInventoryDom(_inventoryLastState || parseInventoryPageState());
        return;
      }
      if (typeof onSuccess === "function") {
        await onSuccess(json);
      }
    } catch (err) {
      if (err?.name === "AbortError") {
        showNotify(t("inv_error_action_timeout", "Inventar-Aktion hat zu lange gedauert."), "error");
      } else if (!err?.gcAuth) {
        console.warn("[GC] inventory action error", err);
        showNotify(t("inv_error_action_failed", "Inventar-Aktion ist fehlgeschlagen."), "error");
      }
      scrollInventoryToFeedback();
      patchInventoryDom(_inventoryLastState || parseInventoryPageState());
    } finally {
      clearTimeout(timeout);
      btnList.forEach((btn) => releaseInventoryActionBtn(btn));
    }
  }

  function scrollInventoryToFeedback() {
    const panel = document.getElementById("inventory-rewards-panel");
    const page = document.getElementById("inventory-page");
    const scrollTarget = panel && !panel.hidden ? panel : page;
    if (scrollTarget) {
      try {
        scrollTarget.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (_) {
        scrollTarget.scrollIntoView(true);
      }
    }
    try {
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (_) {
      window.scrollTo(0, 0);
    }
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
      exchange: "🧬",
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
    if (text) {
      panel.hidden = false;
      scrollInventoryToFeedback();
    }
  }

  function releaseInventoryActionBtn(btn) {
    if (!btn) return;
    btn.disabled = false;
    btn.classList.remove("is-loading", "is-busy");
  }

  function lockInventoryActionBtn(btn) {
    if (!btn) return;
    btn.disabled = true;
    btn.classList.add("is-loading", "is-busy");
  }

  function buildInventoryItemRowHtml(item) {
    const rarity = item.rarity || "common";
    const name = t(item.name_key || `inv_item_${item.item_key}`, item.item_key);
    const amount = parseInt(item.amount, 10) || 0;
    const craftProgress = (item.craft_progress || [])
      .map(
        (cp) =>
          `<span class="inventory-craft-progress gc-mono">${formatNumber(amount)} / ${formatNumber(cp.required || 0)} ${escapeHtml(t(cp.name_key, cp.output_key))}</span>`
      )
      .join("");
    const exchangeProgress = (item.exchange_progress || [])
      .map((ep) => {
        const inputName = t(`inv_${ep.input_key}`, ep.input_key);
        const outputName = t(`inv_${ep.output_key}`, ep.output_key);
        return `<span class="inventory-exchange-progress gc-mono">${escapeHtml(
          tf(
            "inv_exchange_upgrade_hint",
            {
              input_amount: ep.required,
              output_amount: ep.output_amount || 1,
              input_name: inputName,
              output_name: outputName,
            },
            "Upgrade möglich: %(input_amount)s %(input_name)s → %(output_amount)s %(output_name)s"
          )
        )}</span>`;
      })
      .join("");
    const endgameHint = item.exchange_endgame
      ? `<span class="inventory-endgame-hint">${escapeHtml(t("inv_dna_core_epic_hint", "Endgame-Material — später nutzbar"))}</span>`
      : "";
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
    const exchangeBtns = (item.exchange_progress || [])
      .filter((ep) => ep.can_exchange)
      .map(
        (ep) =>
          `<button type="button" class="gc-btn gc-btn-secondary gc-btn-xs inventory-exchange-btn" data-inventory-exchange="${escapeHtml(ep.recipe_key)}">${escapeHtml(t("inv_upgrade_btn", "Upgrade"))}</button>`
      )
      .join("");
    return `<span class="inventory-item-icon" aria-hidden="true">${item.icon || "📦"}</span><div class="inventory-item-body"><span class="inventory-item-name">${escapeHtml(name)}</span>${craftProgress}${exchangeProgress}${endgameHint}</div><span class="inventory-rarity-badge inventory-rarity-badge--${escapeHtml(rarity)}">${escapeHtml(t(`inv_rarity_${rarity}`, rarity))}</span>${collectibleBadge}<span class="inventory-item-amount gc-mono" data-inventory-item-amount="${escapeHtml(item.item_key)}">×${formatNumber(amount)}</span>${useBtn}${craftBtns}${exchangeBtns}`;
  }

  let _lootModalState = null;

  function playLootboxOpenSound() {
    if (window.GC?.settings?.sound === false) return;
    try {
      const audio = new Audio("/static/sounds/lootboxes/lootbox_sound.mp3");
      audio.volume = 0.2;
      audio.play().catch(() => {});
    } catch (_) {}
  }

  function lootTileAmountLabel(tile) {
    const amt = parseInt(tile.amount, 10) || 0;
    const type = String(tile.type || "");
    if (type === "resource") return `+${formatNumber(amt)}`;
    if (type === "booster" && String(tile.key || "").includes("booster")) {
      const sec = parseInt(tile.booster_seconds, 10) || 0;
      if (sec >= 3600) return `${Math.round(sec / 3600)} h`;
      if (sec >= 60) return `${Math.round(sec / 60)} Min`;
    }
    return `×${formatNumber(amt)}`;
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
          <span class="gc-loot-result-amount gc-mono">+${formatNumber(amt)}</span>
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
        <span class="gc-loot-result-amount gc-mono">×${formatNumber(amt)}</span>
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

  function lootContainerImageUrl(payload) {
    const fallback = "/static/img/lootboxes/Generic_Supply_Container.png";
    const raw = String(payload.container_image || "").trim();
    if (!raw) return fallback;
    if (raw.startsWith("http://") || raw.startsWith("https://") || raw.startsWith("/")) return raw;
    const rel = raw.replace(/^static\//, "");
    return `/static/${rel}`;
  }

  function showLootOpeningModal(payload) {
    closeLootModal();
    const containerKey = payload.container_key || payload.item_key || "container_basic";
    const containerName = t(
      payload.container_name_key || `inv_${containerKey}`,
      containerKey
    );
    const containerRarity = payload.container_rarity || "common";
    const crateImg = lootContainerImageUrl(payload);
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
        <div class="gc-loot-crate rarity-${escapeHtml(containerRarity)}">
          <div class="gc-loot-crate-glow inventory-loot-card-glow inventory-loot-card-glow--${escapeHtml(containerRarity)}" aria-hidden="true"></div>
          <img class="gc-loot-crate-img"
               src="${escapeHtml(crateImg)}"
               alt="${escapeHtml(containerName)}"
               decoding="async"
               onerror="this.onerror=null;this.src='/static/img/lootboxes/Generic_Supply_Container.png';">
        </div>
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
          return `<li class="inventory-reward-row inventory-reward-row--resource"><span class="inventory-reward-label">${escapeHtml(label)}</span><span class="inventory-reward-amount gc-mono">+${formatNumber(amt)}</span></li>`;
        }
        if (r.reward_type === "ship" || r.reward_type === "defense") {
          const name = t(r.name_key || `${r.reward_type}_${r.reward_key}`, r.reward_key);
          const icon = r.reward_type === "ship" ? "🛰️" : "🛡️";
          return `<li class="inventory-reward-row inventory-reward-row--${escapeHtml(r.reward_type)}"><span class="inventory-reward-icon" aria-hidden="true">${icon}</span><span class="inventory-reward-label">${escapeHtml(name)}</span><span class="inventory-reward-amount gc-mono">+${formatNumber(amt)}</span></li>`;
        }
        const name = t(r.name_key || `inv_item_${r.reward_key}`, r.reward_key);
        const rarity = t(`inv_rarity_${r.rarity || "common"}`, r.rarity || "common");
        const icon = r.icon || "📦";
        return `<li class="inventory-reward-row inventory-reward-row--item" data-rarity="${escapeHtml(r.rarity || "common")}"><span class="inventory-reward-icon" aria-hidden="true">${icon}</span><span class="inventory-reward-label">${escapeHtml(name)}</span><span class="inventory-rarity-badge inventory-rarity-badge--${escapeHtml(r.rarity || "common")}">${escapeHtml(rarity)}</span><span class="inventory-reward-amount gc-mono">×${formatNumber(amt)}</span></li>`;
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
        void runInventoryAction(
          useBtn,
          "/api/inventory/use-item",
          {
            item_key: itemKey,
            amount: 1,
            request_id: `inv-use-${itemKey}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          },
          (res) => {
            applyActionState(res, "inventory_use");
            renderInventoryEffect(res.effect || {});
            applyInventoryActionResult(res);
            void refreshInventoryFromServer();
          }
        );
        return;
      }

      const craftBtn = ev.target.closest("[data-inventory-craft]");
      if (craftBtn && !craftBtn.disabled) {
        const page = document.getElementById("inventory-page");
        if (!page || page.dataset.ready !== "1") return;
        const recipeKey = craftBtn.dataset.inventoryCraft;
        if (!recipeKey) return;
        void runInventoryAction(
          craftBtn,
          "/api/inventory/craft",
          {
            recipe_key: recipeKey,
            amount: 1,
            request_id: `inv-craft-${recipeKey}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          },
          (res) => {
            applyActionState(res, "inventory_craft");
            renderInventoryEffect(res.effect || {});
            applyInventoryActionResult(res);
            void refreshInventoryFromServer();
          }
        );
        return;
      }

      const exchangeBtn = ev.target.closest("[data-inventory-exchange]");
      if (exchangeBtn && !exchangeBtn.disabled) {
        const page = document.getElementById("inventory-page");
        if (!page || page.dataset.ready !== "1") return;
        const recipeKey = exchangeBtn.dataset.inventoryExchange;
        if (!recipeKey) return;
        void runInventoryAction(
          exchangeBtn,
          "/api/inventory/exchange",
          {
            recipe_key: recipeKey,
            amount: 1,
            request_id: `inv-exchange-${recipeKey}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          },
          (res) => {
            applyActionState(res, "inventory_exchange");
            renderInventoryEffect(res.effect || {});
            applyInventoryActionResult(res);
            void refreshInventoryFromServer();
          }
        );
        return;
      }

      const openBtn = ev.target.closest("[data-inventory-open]");
      if (!openBtn || openBtn.disabled) return;
      const page = document.getElementById("inventory-page");
      if (!page || page.dataset.ready !== "1") return;

      const itemKey = openBtn.dataset.inventoryOpen;
      const amount = parseInt(openBtn.dataset.openAmount, 10) || 1;
      if (!itemKey) return;

      const openButtons = Array.from(page.querySelectorAll("[data-inventory-open]"));
      void runInventoryAction(
        openButtons,
        "/api/inventory/open-container",
        {
          item_key: itemKey,
          amount,
          request_id: `inv-open-${itemKey}-${amount}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        },
        (res) => {
          showLootOpeningModal({
            ...res,
            item_key: itemKey,
            consumed: res.opened || amount,
            _deferredState: res.state,
            _deferredInventory: res.inventory,
          });
        }
      );
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

  function parseAuctionHousePageState() {
    const el = document.getElementById("auction-house-page-state");
    if (el && el.textContent) {
      try { return JSON.parse(el.textContent); } catch (_) {}
    }
    return null;
  }

  function patchAuctionHouseStats(stats) {
    const page = document.getElementById("auction-house-page");
    if (!page || !stats) return;
    const map = {
      active: stats.active_auctions,
      my_bids: stats.my_bids,
      won: stats.won_auctions,
    };
    Object.entries(map).forEach(([key, val]) => {
      const el = page.querySelector(`[data-auction-stat="${key}"]`);
      if (el && val !== undefined) _setIfChanged(el, String(val));
    });
  }

  function renderAuctionRecentBids(listingId, bids) {
    const page = document.getElementById("auction-house-page");
    if (!page) return;
    const section = page.querySelector(`[data-auction-recent="${listingId}"]`);
    if (!section) return;
    const rows = Array.isArray(bids) ? bids : [];
    let list = section.querySelector(`[data-auction-recent-list="${listingId}"]`);
    let empty = section.querySelector(`[data-auction-recent-empty="${listingId}"]`);
    if (!rows.length) {
      if (list) list.remove();
      if (!empty) {
        empty = document.createElement("p");
        empty.className = "auction-house-recent-empty";
        empty.dataset.auctionRecentEmpty = String(listingId);
        section.appendChild(empty);
      }
      empty.textContent = t("auction_house_recent_empty", "Noch keine Gebotshistorie.");
      empty.hidden = false;
      return;
    }
    if (empty) empty.remove();
    if (!list) {
      list = document.createElement("ul");
      list.className = "auction-house-recent-list";
      list.dataset.auctionRecentList = String(listingId);
      section.appendChild(list);
    }
    list.innerHTML = rows.map((bid) => (
      `<li class="auction-house-recent-row">`
      + `<span class="auction-house-recent-name">${escapeHtml(String(bid.player_name || "—"))}</span>`
      + `<span class="auction-house-recent-amount gc-mono">${escapeHtml(fmtNumber(bid.amount || 0))}</span>`
      + `</li>`
    )).join("");
  }

  function toggleAuctionHouseExpand(listingId, forceOpen) {
    const page = document.getElementById("auction-house-page");
    if (!page || !listingId) return;
    const id = String(listingId);
    const currentlyOpen = page.dataset.expandedAuction === id;
    const open = forceOpen === true ? true : forceOpen === false ? false : !currentlyOpen;

    page.querySelectorAll("[data-auction-expand]").forEach((expand) => {
      expand.hidden = true;
    });
    page.querySelectorAll("[data-auction-row]").forEach((row) => {
      row.classList.remove("is-expanded", "is-selected");
      row.setAttribute("aria-expanded", "false");
    });

    if (!open) {
      delete page.dataset.expandedAuction;
      return;
    }

    const row = page.querySelector(`[data-auction-row="${id}"]`);
    const expand = page.querySelector(`[data-auction-expand="${id}"]`);
    if (row) {
      row.classList.add("is-expanded", "is-selected");
      row.setAttribute("aria-expanded", "true");
    }
    if (expand) expand.hidden = false;
    page.dataset.expandedAuction = id;
  }

  function patchAuctionHousePanel(ah) {
    const page = document.getElementById("auction-house-page");
    if (!page || !ah || typeof ah !== "object") return;
    const tt = (key, fallback) => t(key, fallback);
    if (ah.stats) patchAuctionHouseStats(ah.stats);
    const auctions = Array.isArray(ah.auctions) ? ah.auctions : [];
    auctions.forEach((a) => {
      const id = a.id;
      if (!id) return;
      const hasBids = Boolean(a.has_bids || (a.current_bid > 0 && a.current_bidder_id));
      const displayBid = hasBids ? (a.current_bid || 0) : (a.display_bid || a.start_price || 0);
      const bidTxt = fmtNumber(displayBid);
      const currencyTxt = a.currency ? tt(`resource_${a.currency}`, a.currency) : "";

      const bidLabelEl = page.querySelector(`[data-auction-bid-label="${id}"]`);
      if (bidLabelEl) {
        const label = hasBids
          ? tt("auction_house_current_bid_upper", "AKTUELLES GEBOT")
          : tt("auction_house_start_bid_upper", "STARTGEBOT");
        _setIfChanged(bidLabelEl, label);
      }

      const bidEl = page.querySelector(`[data-auction-current-bid="${id}"]`);
      if (bidEl) _setIfChanged(bidEl, bidTxt);

      const currencyWrap = page.querySelector(`[data-auction-currency-label="${id}"]`);
      if (currencyWrap && currencyTxt) {
        const labelSpan = currencyWrap.querySelector("span:not(.gc-res-icon):not([class*='gc-res-icon'])");
        if (labelSpan) _setIfChanged(labelSpan, currencyTxt);
      }

      const rowBidderEl = page.querySelector(`[data-auction-row-bidder="${id}"]`);
      if (rowBidderEl) {
        const rowTxt = hasBids
          ? (a.is_leading
            ? tt("auction_house_you_lead_short", "Du (Führst)")
            : String(a.current_bidder_name || "—"))
          : "—";
        _setIfChanged(rowBidderEl, rowTxt);
      }

      const leaderBadge = page.querySelector(`[data-auction-leader="${id}"]`);
      const noBidsEl = page.querySelector(`[data-auction-no-bids="${id}"]`);
      const bidderEl = page.querySelector(`[data-auction-bidder="${id}"]`);
      if (hasBids && leaderBadge) {
        leaderBadge.hidden = false;
        leaderBadge.classList.toggle("auction-house-leader-badge--you", Boolean(a.is_leading));
        leaderBadge.classList.remove("auction-house-leader-badge--empty");
        if (bidderEl) {
          const txt = a.is_leading
            ? tt("auction_house_you_lead", "Du führst aktuell")
            : String(a.current_bidder_name || "—");
          _setIfChanged(bidderEl, txt);
        }
        if (noBidsEl) noBidsEl.hidden = true;
      } else if (leaderBadge) {
        leaderBadge.hidden = true;
        if (noBidsEl) noBidsEl.hidden = false;
      }

      const minEl = page.querySelector(`[data-auction-min-label="${id}"]`);
      if (minEl && a.min_next_bid) {
        const label = `(${tt("auction_house_min_bid", "min.")} ${fmtNumber(a.min_next_bid)})`;
        _setIfChanged(minEl, label);
      }
      const input = page.querySelector(`[data-auction-bid-input="${id}"]`);
      if (input) {
        const minVal = String(a.min_next_bid || 1);
        input.min = minVal;
        input.placeholder = fmtNumber(a.min_next_bid || 1);
        if (!input.matches(":focus") && (!input.value || readNumberInput(input) < parseIntNumber(minVal))) {
          setNumberInputValue(input, minVal);
        }
      }
      const card = page.querySelector(`[data-auction-card="${id}"]`);
      if (card) {
        card.dataset.minBid = String(a.min_next_bid || 1);
        card.dataset.currentBid = String(a.current_bid || 0);
        card.dataset.endsAt = String(a.ends_at || 0);
        card.dataset.currency = String(a.currency || "");
        card.dataset.hasBids = hasBids ? "1" : "0";
        card.dataset.isLeading = a.is_leading ? "1" : "0";
        card.classList.toggle("auction-house-row--leading", Boolean(a.is_leading));
      }
      const submitBtn = page.querySelector(`[data-auction-bid-submit="${id}"]`);
      if (submitBtn) {
        const label = a.is_leading
          ? tt("auction_house_raise_bid", "Gebot erhöhen")
          : tt("auction_house_place_bid", "Gebot abgeben");
        _setIfChanged(submitBtn, label);
      }
      renderAuctionRecentBids(id, a.recent_bids || []);
    });
    const expanded = page.dataset.expandedAuction;
    if (expanded && page.querySelector(`[data-auction-expand="${expanded}"]`)) {
      toggleAuctionHouseExpand(expanded, true);
    }
    patchAuctionHouseRotation(ah);
  }

  function formatAuctionRotationRemain(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const secR = s % 60;
    if (h > 0) return `${h}h ${m}m ${secR}s`;
    if (m > 0) return `${m}m ${secR}s`;
    return `${secR}s`;
  }

  async function refreshAuctionHouseState() {
    if (GC._auctionHouseRefreshInFlight) return;
    GC._auctionHouseRefreshInFlight = true;
    try {
      const res = await GC.fetchJSON("/api/auction-house/state");
      const ah = res?.auction_house;
      if (ah) patchAuctionHousePanel(ah);
    } catch (err) {
      console.warn("[GC] auction house state refresh failed", err);
    } finally {
      GC._auctionHouseRefreshInFlight = false;
    }
  }

  function patchAuctionHouseRotation(ah) {
    const page = document.getElementById("auction-house-page");
    if (!page || !ah) return;
    const nextAt = parseInt(String(ah.next_rotation_at || page.dataset.nextRotationAt || "0"), 10);
    if (nextAt > 0) page.dataset.nextRotationAt = String(nextAt);
    const timer = page.querySelector("[data-auction-rotation-timer]");
    if (timer && nextAt > 0) timer.dataset.nextRotationAt = String(nextAt);
    patchAuctionHouseUpcoming(ah.upcoming || []);
  }

  function patchAuctionHouseUpcoming(upcoming) {
    const page = document.getElementById("auction-house-page");
    if (!page || !Array.isArray(upcoming)) return;
    upcoming.forEach((u) => {
      const id = u.preview_index ?? u.id;
      if (id === undefined || id === null) return;
      const wrap = page.querySelector(`[data-auction-upcoming-available="${id}"]`);
      if (!wrap) return;
      const availableAt = u.available_at ?? u.starts_at;
      if (availableAt) wrap.dataset.availableAt = String(availableAt);
    });
  }

  function tickAuctionHouseCountdowns() {
    const page = document.getElementById("auction-house-page");
    if (!page) return;
    const now = Math.floor(getTimerServerNow());
    page.querySelectorAll("[data-auction-remaining]").forEach((wrap) => {
      const endsAt = parseInt(
        wrap.dataset.endsAt || wrap.closest("[data-auction-card]")?.dataset.endsAt || "0",
        10
      );
      if (!endsAt) return;
      const rem = Math.max(0, endsAt - now);
      const valEl = wrap.querySelector(".auction-house-time-value");
      if (valEl) _setIfChanged(valEl, formatCountdownRemain(rem));
    });
    page.querySelectorAll("[data-auction-upcoming-available]").forEach((wrap) => {
      const availableAt = parseInt(wrap.dataset.availableAt || "0", 10);
      if (!availableAt) return;
      const rem = Math.max(0, availableAt - now);
      const valEl = wrap.querySelector(".auction-house-upcoming-available-value");
      if (valEl) _setIfChanged(valEl, formatCountdownRemain(rem));
    });
    const rotWrap = page.querySelector("[data-auction-rotation-timer]");
    if (rotWrap) {
      const nextAt = parseInt(rotWrap.dataset.nextRotationAt || page.dataset.nextRotationAt || "0", 10);
      if (nextAt > 0) {
        const rem = Math.max(0, nextAt - now);
        const valEl = rotWrap.querySelector(".auction-rotation-timer-value");
        if (valEl) _setIfChanged(valEl, formatAuctionRotationRemain(rem));
        if (rem <= 0 && !GC._auctionHouseRotationRefreshDone) {
          GC._auctionHouseRotationRefreshDone = true;
          refreshAuctionHouseState().finally(() => {
            GC._auctionHouseRotationRefreshDone = false;
          });
        }
      }
    }
  }

  function bindAuctionHouseOnce() {
    if (GC._auctionHouseEventsBound) return;
    GC._auctionHouseEventsBound = true;

    document.addEventListener("click", (ev) => {
      const row = ev.target?.closest?.("[data-auction-row]");
      if (row && !ev.target?.closest?.("[data-auction-expand], [data-auction-bid-form], button, a, input, label")) {
        toggleAuctionHouseExpand(row.dataset.auctionRow);
        return;
      }

      const btn = ev.target?.closest?.("[data-auction-loot-toggle]");
      if (!btn) return;
      const id = btn.getAttribute("data-auction-loot-toggle");
      const panel = document.getElementById(`auction-loot-panel-${id}`);
      if (!panel) return;
      const open = panel.hidden;
      document.querySelectorAll(".auction-house-loot-preview-panel").forEach((p) => { p.hidden = true; });
      document.querySelectorAll("[data-auction-loot-toggle]").forEach((b) => {
        b.setAttribute("aria-expanded", "false");
      });
      if (open) {
        panel.hidden = false;
        btn.setAttribute("aria-expanded", "true");
      }
    });

    document.addEventListener("keydown", (ev) => {
      const row = ev.target?.closest?.("[data-auction-row]");
      if (!row) return;
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        toggleAuctionHouseExpand(row.dataset.auctionRow);
      }
    });

  }

  function bindAuctionHouseBidForms(root) {
    const page = root || document.querySelector("[data-auction-house]");
    if (!page) return;

    const tt = (key, fallback) => t(key, fallback);
    const auctionBidSucceeded = (res) => {
      if (!res || typeof res !== "object") return false;
      if (res.ok === true || res.reason === "bid_placed") return true;
      if (res.bid && res.bid.listing_id) return true;
      return false;
    };
    const auctionReasonText = (res) => {
      const reason = String((res && res.reason) || "generic");
      if (reason === "bid_must_raise") {
        return tt("auction_error_bid_must_raise", "Your bid must be higher than your current high bid.");
      }
      if (reason === "bid_too_low") {
        const minBid = Number(res?.min_bid || 0);
        if (minBid > 0) {
          return tt(
            "auction_error_bid_too_low_min",
            tt("auction_error_bid_too_low", "Bid is too low.") + ` (${tt("auction_house_min_bid", "min.")} ${fmtNumber(minBid)})`
          ).replace("%(min)s", fmtNumber(minBid));
        }
      }
      return tt(`auction_error_${reason}`, tt("auction_error_generic", "Bid failed."));
    };
    const setAuctionFormError = (listingId, message) => {
      const el = page.querySelector(`[data-auction-form-error="${listingId}"]`);
      if (!el) return;
      const msg = String(message || "").trim();
      el.textContent = msg;
      el.hidden = !msg;
    };

    page.querySelectorAll("[data-auction-bid-form]").forEach((form) => {
      if (form.dataset.bound === "1") return;
      form.dataset.bound = "1";

      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        ev.stopImmediatePropagation();

        const listingId = parseInt(
          form.querySelector("[name='listing_id']")?.value
          || form.getAttribute("data-auction-bid-form")
          || "0",
          10
        );
        const card = page.querySelector(`[data-auction-card="${listingId}"]`);
        const currency = String(
          form.querySelector("[name='currency']")?.value
          || card?.dataset.currency
          || ""
        ).trim();
        const input = form.querySelector("[data-auction-bid-input], [name='amount']");
        const btn = form.querySelector("[data-auction-bid-submit], [type='submit']");
        const amount = readNumberInput(input);
        const minBid = parseInt(String(card?.dataset.minBid || input?.min || "0"), 10);

        setAuctionFormError(listingId, "");
        if (!listingId || !currency || !amount) {
          const msg = tt("auction_error_invalid_amount", "Enter a valid bid.");
          setAuctionFormError(listingId, msg);
          showNotify(msg, "error");
          return;
        }
        if (minBid > 0 && amount < minBid) {
          const msg = auctionReasonText({ reason: "bid_too_low", min_bid: minBid });
          setAuctionFormError(listingId, msg);
          showNotify(msg, "error");
          return;
        }
        const isLeading = card?.dataset.isLeading === "1";
        const currentBid = parseInt(String(card?.dataset.currentBid || "0"), 10);
        if (isLeading && currentBid > 0 && amount <= currentBid) {
          const msg = auctionReasonText({ reason: "bid_must_raise", min_bid: minBid });
          setAuctionFormError(listingId, msg);
          showNotify(msg, "error");
          return;
        }
        if (form.dataset.submitting === "1") return;
        form.dataset.submitting = "1";
        if (btn) {
          btn.disabled = true;
          btn.classList.add("is-loading");
        }

        const requestId = newRequestId();
        let res = null;
        try {
          res = await GC.fetchGameAction("/api/auction-house/bid", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Request-Id": requestId,
            },
            body: JSON.stringify({
              listing_id: listingId,
              amount,
              currency,
              request_id: requestId,
            }),
          });
        } catch (err) {
          if (err?.name === "AbortError") return;
          const msg = tt("auction_error_generic", "Bid failed.");
          setAuctionFormError(listingId, msg);
          showNotify(msg, "error");
          console.warn("[GC] auction bid request failed", err);
        } finally {
          form.dataset.submitting = "0";
          if (btn) {
            btn.disabled = false;
            btn.classList.remove("is-loading");
          }
        }

        if (!res) return;

        const succeeded = auctionBidSucceeded(res);
        const ahPayload = res?.auction_house || res?.state?.auction_house;
        try {
          if (ahPayload) patchAuctionHousePanel(ahPayload);
        } catch (patchErr) {
          console.warn("[GC] auction panel patch failed", patchErr);
        }

        if (succeeded) {
          try {
            if (res?.state) applyActionState(res, "auction_bid");
          } catch (stateErr) {
            console.warn("[GC] auction bid state apply failed", stateErr);
          }
          setAuctionFormError(listingId, "");
          showNotify(tt("auction_bid_ok", "Bid placed."), "success");
          if (input && ahPayload?.auctions) {
            const row = ahPayload.auctions.find((a) => Number(a.id) === listingId);
            if (row?.min_next_bid) setNumberInputValue(input, row.min_next_bid);
            else input.value = "";
          } else if (input) {
            input.value = "";
          }
        } else {
          try {
            if (res?.state) applyActionState(res, "auction_bid_error");
          } catch (_) {}
          const msg = auctionReasonText(res || { reason: "generic" });
          setAuctionFormError(listingId, msg);
          showNotify(msg, "error");
        }
      }, true);
    });
  }

  function initAuctionHouse() {
    bindAuctionHouseOnce();
    syncTradingSubnav("auction_house");
    const page = document.getElementById("auction-house-page");
    bindAuctionHouseBidForms(page);
    if (!page || page.dataset.ready !== "1") return;
    const state = parseAuctionHousePageState();
    if (state) patchAuctionHousePanel(state);
    tickAuctionHouseCountdowns();
    GC.setSafeInterval(tickAuctionHouseCountdowns, 1000);
    GC.registerCleanup(() => {});
  }

  function parseVoteCenterPageState() {
    const el = document.getElementById("vote-center-page-state");
    if (el && el.textContent) {
      try { return JSON.parse(el.textContent); } catch (_) {}
    }
    return null;
  }

  function _voteRewardTypeLabel(r) {
    const key = String(r?.reward_type_label_key || "");
    if (key) return t(key, String(r?.reward_type || "lootbox"));
    const map = {
      lootbox: t("vote_reward_type_lootbox", "Lootbox"),
      resources: t("vote_reward_type_resources", "Ressourcen"),
      ships: t("vote_reward_type_ships", "Schiffe"),
      defense: t("vote_reward_type_defense", "Verteidigung"),
    };
    return map[String(r?.reward_type || "lootbox")] || map.lootbox;
  }

  const VOTE_REWARD_IMG_FALLBACK = "/static/img/lootboxes/Generic_Supply_Container.png";

  function _voteRewardDisplayHtml(r) {
    const items = Array.isArray(r?.display_items) ? r.display_items : [];
    if (!items.length) return "";
    return `<div class="vote-center-reward-visual">${items.map((item) => {
      const kind = String(item?.kind || "");
      const resKey = String(item?.resource_key || "");
      const name = t(item?.name_key || "", item?.name_fallback || "");
      const img = escapeHtml(String(item?.image || VOTE_REWARD_IMG_FALLBACK));
      const amount = fmtNumber(Number(item?.amount) || 0);
      const mods = [
        "vote-center-reward-item",
        kind ? `vote-center-reward-item--${escapeHtml(kind)}` : "",
        resKey ? `vote-center-reward-item--${escapeHtml(resKey)}` : "",
      ].filter(Boolean).join(" ");
      return `<div class="${mods}">
        <img class="vote-center-reward-item-img"
             src="${img}"
             alt="${escapeHtml(name)}"
             loading="lazy"
             decoding="async"
             onerror="this.onerror=null;this.src='${VOTE_REWARD_IMG_FALLBACK}';">
        <div class="vote-center-reward-item-meta">
          <span class="vote-center-reward-item-name">${escapeHtml(name)}</span>
          <span class="vote-center-reward-item-amount gc-mono">× ${escapeHtml(amount)}</span>
        </div>
      </div>`;
    }).join("")}</div>`;
  }

  function voteProviderCooldownRemaining(p, nowSec) {
    const remSec = Number(p.cooldown_remaining_sec);
    if (Number.isFinite(remSec) && remSec > 0) return Math.floor(remSec);
    const nextAt = Number(p.next_vote_at);
    if (!Number.isFinite(nextAt) || nextAt <= 0) return 0;
    return Math.max(0, Math.floor(nextAt - nowSec));
  }

  function formatVoteProviderStatus(p, nowSec) {
    const canVote = p.can_vote_now === true || p.can_vote_hint === true;
    if (canVote) {
      return t("vote_center_ready_to_vote", "Bereit zum Voten");
    }
    const rem = voteProviderCooldownRemaining(p, nowSec);
    if (rem <= 0) {
      return t("vote_center_now", "Jetzt");
    }
    return formatCountdownRemain(rem);
  }

  function patchVoteCenterDom(vc) {
    if (!vc) return;
    const rewards = Array.isArray(vc.pending_rewards) ? vc.pending_rewards : [];
    const pendingCount = Number(vc.pending_count) || rewards.length;
    const now = Math.floor(getApproxServerNow());

    document.querySelectorAll("[data-vote-pending-count]").forEach((el) => {
      el.textContent = String(pendingCount);
    });
    document.querySelectorAll("[data-vote-pending-count-inline]").forEach((el) => {
      el.textContent = String(pendingCount);
    });
    const claimAllBtn = document.querySelector("[data-vote-claim-all]");
    if (claimAllBtn) claimAllBtn.disabled = pendingCount <= 0;

    const providers = Array.isArray(vc.providers) ? vc.providers : [];
    providers.forEach((p) => {
      const key = String(p.provider_key || "");
      if (!key) return;
      const lastEl = document.querySelector(`[data-vote-provider-last="${key}"]`);
      const nextEl = document.querySelector(`[data-vote-provider-next="${key}"]`);
      const subtitleEl = document.querySelector(`[data-vote-provider-subtitle="${key}"]`);
      const rewardStatusEl = document.querySelector(`[data-vote-provider-reward-status="${key}"]`);
      const hintEl = document.querySelector(`[data-vote-provider-hint="${key}"]`);
      const voteCountEl = document.querySelector(`[data-vote-provider-count="${key}"]`);
      const linkEl = document.querySelector(`[data-vote-provider-link="${key}"]`);
      if (subtitleEl && p.subtitle_key) {
        subtitleEl.textContent = t(p.subtitle_key, subtitleEl.textContent || "");
      }
      if (rewardStatusEl && p.reward_status_key) {
        rewardStatusEl.textContent = t(p.reward_status_key, rewardStatusEl.textContent || "");
      }
      if (lastEl) {
        lastEl.textContent = p.last_vote_at
          ? formatLocaleDateTime(p.last_vote_at)
          : t("vote_center_never", "Noch nie");
      }
      if (nextEl) {
        const rem = voteProviderCooldownRemaining(p, now);
        if (p.can_vote_hint) {
          nextEl.textContent = t("vote_center_now", "Jetzt");
        } else if (rem > 0) {
          nextEl.textContent = formatCountdownRemain(rem);
        } else {
          nextEl.textContent = t("vote_center_now", "Jetzt");
        }
      }
      if (hintEl) {
        const rem = voteProviderCooldownRemaining(p, now);
        const postbackEnabled = !!p.postback_enabled;
        if (!postbackEnabled) {
          hintEl.hidden = false;
          const noRewardKey = String(p.no_auto_reward_key || "").trim();
          hintEl.textContent = noRewardKey
            ? t(noRewardKey, hintEl.textContent || "")
            : t(
                "vote_provider_gametoor_no_auto_reward",
                "GameToor-Votes werden aktuell noch nicht automatisch belohnt."
              );
          hintEl.classList.add("vote-center-hint-wait");
          hintEl.classList.remove("vote-center-hint-ready");
        } else if (p.can_vote_hint) {
          hintEl.hidden = false;
          hintEl.textContent = t("vote_center_can_vote", "Du kannst jetzt voten.");
          hintEl.classList.add("vote-center-hint-ready");
          hintEl.classList.remove("vote-center-hint-wait");
        } else if (rem > 0) {
          hintEl.hidden = true;
        } else {
          hintEl.hidden = false;
          hintEl.textContent = t("vote_center_wait_vote", "Bitte warte, bis der Cooldown abgelaufen ist.");
          hintEl.classList.add("vote-center-hint-wait");
          hintEl.classList.remove("vote-center-hint-ready");
        }
      }
      if (voteCountEl) voteCountEl.textContent = fmtNumber(Number(p.vote_count) || 0);
      if (linkEl && p.vote_url) linkEl.href = p.vote_url;
    });

    const list = document.querySelector("[data-vote-rewards-list]");
    if (!list) return;
    if (!rewards.length) {
      list.innerHTML = `<p class="vote-center-empty" data-vote-rewards-empty>${escapeHtml(t("vote_center_no_rewards", "Keine offenen Belohnungen."))}</p>`;
      return;
    }
    list.innerHTML = rewards.map((r) => `
      <article class="vote-center-reward-card" data-vote-reward-id="${Number(r.id)}">
        ${_voteRewardDisplayHtml(r)}
        <div class="vote-center-reward-info">
          <span class="vote-center-reward-title">${escapeHtml(t("vote_reward_title", "Vote Belohnung"))}</span>
          <span class="vote-center-reward-provider">${escapeHtml(String(r.provider_name || r.provider || ""))}</span>
          <span class="vote-center-reward-type">${escapeHtml(_voteRewardTypeLabel(r))}</span>
        </div>
        <button type="button" class="gc-btn gc-btn-ghost gc-btn-sm vote-center-claim-btn" data-vote-claim="${Number(r.id)}">
          ${escapeHtml(t("vote_center_claim_btn", "Belohnung abholen"))}
        </button>
      </article>
    `).join("");
  }

  async function _submitVoteClaim(endpoint, body, successKey, failKey, reasonKey) {
    const res = await GC.fetchGameAction(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res?.state) applyActionState(res, res.ok ? reasonKey : `${reasonKey}_error`);
    if (res?.vote_center) patchVoteCenterDom(res.vote_center);
    if (res?.ok) {
      showNotify(t(successKey, "Belohnung ins Inventar gutgeschrieben."), "success");
    } else {
      showNotify(t(failKey, "Belohnung konnte nicht abgeholt werden."), "error");
    }
    return res;
  }

  let _voteCenterBound = false;
  let _voteCenterPollTimer = null;

  function stopVoteCenterPoll() {
    if (_voteCenterPollTimer) {
      clearInterval(_voteCenterPollTimer);
      _voteCenterPollTimer = null;
    }
  }

  async function refreshVoteCenterState() {
    const page = document.getElementById("vote-center-page");
    if (!page || page.dataset.ready !== "1") return null;
    try {
      const res = await GC.fetchGameAction("/api/vote/center-state");
      if (res?.vote_center) patchVoteCenterDom(res.vote_center);
      return res;
    } catch (_) {
      return null;
    }
  }

  function startVoteCenterPoll(maxAttempts = 24, intervalMs = 5000) {
    stopVoteCenterPoll();
    let attempts = 0;
    _voteCenterPollTimer = GC.setSafeInterval(async () => {
      if (document.hidden || !shouldRunVisualLoops()) return;
      attempts += 1;
      const page = document.getElementById("vote-center-page");
      if (!page || page.dataset.ready !== "1" || attempts > maxAttempts) {
        stopVoteCenterPoll();
        return;
      }
      await refreshVoteCenterState();
    }, intervalMs);
  }

  function bindVoteCenterOnce() {
    if (_voteCenterBound) return;
    _voteCenterBound = true;
    document.addEventListener("click", async (ev) => {
      const page = document.getElementById("vote-center-page");
      if (!page || page.dataset.ready !== "1") return;

      const voteLink = ev.target.closest("[data-vote-provider-link]");
      if (voteLink && voteLink.href) {
        ev.preventDefault();
        const providerKey = String(voteLink.dataset.voteProviderLink || "").trim();
        const href = voteLink.href;
        if (providerKey) {
          try {
            const res = await GC.fetchGameAction("/api/vote/visit", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                provider_key: providerKey,
                request_id: newRequestId(),
              }),
            });
            if (res?.vote_center) patchVoteCenterDom(res.vote_center);
            if (res?.ok && res?.created) {
              showNotify(
                t("vote_center_visit_reward_pending", "Vote registriert — Belohnung wartet im Vote Center."),
                "success"
              );
              window.open(href, "_blank", "noopener,noreferrer");
              startVoteCenterPoll();
            } else if (res?.ok && res?.reason === "cooldown_active") {
              const rem = Math.max(0, Number(res.cooldown_remaining_sec) || 0);
              showNotify(
                `${t("vote_center_next_in", "Nächster Vote möglich in")} ${formatCountdownRemain(rem)}`,
                "info"
              );
            }
          } catch (_) {
            showNotify(t("vote_center_visit_fail", "Vote konnte nicht registriert werden."), "error");
          }
        } else {
          window.open(href, "_blank", "noopener,noreferrer");
        }
        return;
      }

      const claimAllBtn = ev.target.closest("[data-vote-claim-all]");
      if (claimAllBtn && !claimAllBtn.disabled) {
        ev.preventDefault();
        claimAllBtn.disabled = true;
        try {
          await _submitVoteClaim(
            "/api/vote/rewards/claim-all",
            { request_id: newRequestId() },
            "vote_center_claim_all_ok",
            "vote_center_claim_all_fail",
            "vote_reward_claim_all"
          );
        } catch (_) {
          showNotify(t("vote_center_claim_all_fail", "Belohnungen konnten nicht abgeholt werden."), "error");
        } finally {
          claimAllBtn.disabled = false;
        }
        return;
      }

      const btn = ev.target.closest("[data-vote-claim]");
      if (!btn || btn.disabled) return;
      ev.preventDefault();
      const rewardId = parseInt(btn.dataset.voteClaim, 10) || 0;
      if (!rewardId) return;
      btn.disabled = true;
      try {
        await _submitVoteClaim(
          "/api/vote/rewards/claim",
          { reward_id: rewardId, request_id: newRequestId() },
          "vote_center_claim_ok",
          "vote_center_claim_fail",
          "vote_reward_claim"
        );
      } catch (_) {
        showNotify(t("vote_center_claim_fail", "Belohnung konnte nicht abgeholt werden."), "error");
      } finally {
        btn.disabled = false;
      }
    }, true);
  }

  function initVoteCenter() {
    bindVoteCenterOnce();
    syncTradingSubnav("vote_center");
    const page = document.getElementById("vote-center-page");
    if (!page || page.dataset.ready !== "1") return;
    const state = parseVoteCenterPageState();
    if (state) patchVoteCenterDom(state);
    GC.registerCleanup(stopVoteCenterPoll);
    if (!page._voteFocusBound) {
      page._voteFocusBound = true;
      const onFocus = () => {
        if (document.visibilityState && document.visibilityState !== "visible") return;
        refreshVoteCenterState();
      };
      window.addEventListener("focus", onFocus);
      document.addEventListener("visibilitychange", onFocus);
      GC.registerCleanup(() => {
        window.removeEventListener("focus", onFocus);
        document.removeEventListener("visibilitychange", onFocus);
        page._voteFocusBound = false;
      });
    }
  }

  function parseReferralsPageState() {
    const el = document.getElementById("referrals-page-state");
    if (el && el.textContent) {
      try { return JSON.parse(el.textContent); } catch (_) {}
    }
    return null;
  }

  function _referralTierCardHtml(tier, scope) {
    const display = tier.display || {};
    const img = escapeHtml(String(display.image || "/static/img/lootboxes/Generic_Supply_Container.png"));
    const title = escapeHtml(t(tier.label_key, tier.reward_key || ""));
    const desc = tier.desc_key ? escapeHtml(t(tier.desc_key, "")) : "";
    const progress = escapeHtml(String(tier.progress_label || ""));
    const claimable = Boolean(tier.claimable);
    const claimed = Boolean(tier.claimed);
    const unlocked = tier.unlocked !== false;
    let stateClass = "";
    if (claimable) stateClass = "referral-tier-card--claimable";
    else if (claimed) stateClass = "referral-tier-card--claimed";
    else if (!unlocked) stateClass = "referral-tier-card--locked";
    const action = claimable
      ? `<button type="button" class="gc-btn gc-btn-ghost gc-btn-sm" data-referral-claim>${escapeHtml(t("referral_claim_btn", "Abholen"))}</button>`
      : claimed
        ? `<span class="referral-tier-claimed">${escapeHtml(t("referral_claimed_badge", "Abgeholt"))}</span>`
        : scope === "referrer"
          ? `<span class="referral-tier-locked gc-mono" aria-hidden="true"></span>`
          : "";
    const progressLine = scope === "referrer"
      ? `<p class="referral-tier-progress gc-mono">${progress} ${escapeHtml(t("referral_tier_progress_suffix", "erfolgreiche Empfehlungen"))}</p>`
      : "";
    return `
      <article class="referral-tier-card ${stateClass}"
               data-referral-tier
               data-reward-scope="${escapeHtml(scope)}"
               data-reward-key="${escapeHtml(String(tier.reward_key || ""))}"
               data-required="${Number(tier.required_count) || 0}">
        <div class="referral-tier-visual">
          <img src="${img}" alt="" width="64" height="64" loading="lazy">
        </div>
        <div class="referral-tier-info">
          <h3 class="referral-tier-title">${title}</h3>
          ${desc ? `<p class="referral-tier-desc">${desc}</p>` : ""}
          ${progressLine}
        </div>
        ${action}
      </article>
    `;
  }

  function patchReferralsDom(state) {
    if (!state || typeof state !== "object") return;
    const page = document.getElementById("referrals-page");
    if (!page) return;

    const codeEl = page.querySelector("[data-referral-code]");
    if (codeEl && state.code) codeEl.textContent = String(state.code);

    const urlInput = page.querySelector("[data-referral-url-input]");
    if (urlInput && state.referral_url) urlInput.value = String(state.referral_url);

    const progressEl = page.querySelector("[data-referral-progress]");
    if (progressEl) {
      const pending = Math.max(0, Number(state.pending_count) || 0);
      const successful = Math.max(0, Number(state.successful_count) || 0);
      let html = `${escapeHtml(t("referral_progress", "Erfolgreiche Empfehlungen"))}: <strong>${fmtNumber(successful)}</strong>`;
      if (pending > 0) {
        html += ` <span class="referral-progress-pending">(${pending} ${escapeHtml(t("referral_pending_short", "ausstehend"))})</span>`;
      }
      progressEl.innerHTML = html;
    }

    const tierList = page.querySelector("[data-referral-tier-list]");
    if (tierList && Array.isArray(state.referrer_tiers)) {
      tierList.innerHTML = state.referrer_tiers.map((tier) => _referralTierCardHtml(tier, "referrer")).join("");
    }

    const referredList = page.querySelector("[data-referral-referred-list]");
    if (referredList) {
      if (state.referred_reward) {
        referredList.innerHTML = _referralTierCardHtml(state.referred_reward, "referred");
      } else {
        referredList.innerHTML = "";
      }
    }
  }

  let _referralsBound = false;

  function bindReferralsOnce() {
    if (_referralsBound) return;
    _referralsBound = true;

    document.addEventListener("click", async (ev) => {
      const copyBtn = ev.target.closest("[data-referral-copy]");
      if (copyBtn) {
        const page = document.getElementById("referrals-page");
        if (!page) return;
        const mode = String(copyBtn.dataset.referralCopy || "");
        let text = "";
        if (mode === "code") {
          text = page.querySelector("[data-referral-code]")?.textContent?.trim() || "";
        } else if (mode === "link") {
          text = page.querySelector("[data-referral-url-input]")?.value?.trim() || "";
        }
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
          showNotify(t("referral_copy_ok", "In Zwischenablage kopiert."), "success");
        } catch (_) {
          showNotify(t("referral_copy_fail", "Kopieren fehlgeschlagen."), "error");
        }
        return;
      }

      const claimBtn = ev.target.closest("[data-referral-claim]");
      if (claimBtn) {
        const card = claimBtn.closest("[data-referral-tier]");
        if (!card) return;
        const scope = String(card.dataset.rewardScope || "").trim();
        const rewardKey = String(card.dataset.rewardKey || "").trim();
        if (!scope || !rewardKey) return;
        const res = await GC.fetchGameAction("/api/referrals/claim", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            reward_scope: scope,
            reward_key: rewardKey,
            request_id: newRequestId(),
          }),
        });
        if (res?.state) applyActionState(res, "referral_claim");
        if (res?.referrals) patchReferralsDom(res.referrals);
        if (res?.ok) {
          showNotify(t("referral_claim_ok", "Belohnung ins Inventar gutgeschrieben."), "success");
        } else {
          showNotify(t("referral_claim_fail", "Belohnung konnte nicht abgeholt werden."), "error");
        }
      }
    });

    document.addEventListener("submit", async (ev) => {
      const form = ev.target.closest("[data-referral-apply-form]");
      if (!form) return;
      ev.preventDefault();
      const input = form.querySelector("[data-referral-apply-input]");
      const code = String(input?.value || "").trim();
      if (!code) {
        showNotify(t("referral_apply_missing", "Bitte einen Code eingeben."), "error");
        return;
      }
      const res = await GC.fetchGameAction("/api/referrals/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ referral_code: code, request_id: newRequestId() }),
      });
      if (res?.state) applyActionState(res, "referral_apply");
      if (res?.referrals) patchReferralsDom(res.referrals);
      if (res?.ok) {
        showNotify(t("referral_apply_ok", "Referral-Code verknüpft."), "success");
        const applyPanel = document.querySelector(".referral-apply-panel");
        if (applyPanel) applyPanel.remove();
      } else {
        const reason = String(res?.reason || "");
        const msg = reason === "referral_self_not_allowed"
          ? t("referral_err_self", "Du kannst deinen eigenen Code nicht verwenden.")
          : reason === "referral_already_linked"
            ? t("referral_err_already_linked", "Du hast bereits einen Referrer.")
            : reason === "referral_code_not_found"
              ? t("referral_err_not_found", "Code nicht gefunden.")
              : t("referral_apply_fail", "Code konnte nicht eingelöst werden.");
        showNotify(msg, "error");
      }
    });
  }

  function initReferrals() {
    bindReferralsOnce();
    const page = document.getElementById("referrals-page");
    if (!page || page.dataset.ready !== "1") return;
    const state = parseReferralsPageState();
    if (state) patchReferralsDom(state);
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

  /** GC-557 — fleet send/preview origin must match active/context planet. */
  function resolveFleetOriginPlanetId(page) {
    if (!page) return 0;
    const rt = getFleetRuntime(page);
    const fromDom = parseInt(page.dataset.planetId || "0", 10);
    const fromState = Number(GC.lastState?.active_planet_id || 0);
    const fromRt = parseInt(rt.data?.planet_id || "0", 10);
    const pid = fromDom || fromState || fromRt;
    if (pid > 0) {
      page.dataset.planetId = String(pid);
      if (rt.data) rt.data.planet_id = pid;
    }
    return pid > 0 ? pid : 0;
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
        const val = readNumberInput(inp);
        if (key && val > 0) ships[key] = val;
      });
      return ships;
    };

    const getResourcesSelection = (page) => ({
      metal: readNumberInput(page.querySelector("[data-fleet-res-metal]")),
      crystal: readNumberInput(page.querySelector("[data-fleet-res-crystal]")),
      fuel_cells: readNumberInput(page.querySelector("[data-fleet-res-fuel-cells]")),
    });

    const getTargetCoords = (page) => {
      const form = getForm(page);
      return {
        target_galaxy: parseInt(form?.querySelector('[name="target_galaxy"]')?.value || "1", 10),
        target_system: parseInt(form?.querySelector('[name="target_system"]')?.value || "1", 10),
        target_position: parseInt(form?.querySelector('[name="target_position"]')?.value || "1", 10),
      };
    };

    const getFleetUrlParams = () => new URLSearchParams(window.location.search);

    const getFleetUrlMissionPrefill = () => {
      const mission = (getFleetUrlParams().get("mission") || "").trim().toLowerCase();
      return mission || "";
    };

    const hasFleetWorldKeyPrefill = () => !!(getFleetUrlParams().get("world_key") || "").trim();

    const refreshFleetUrlMissionLock = (page) => {
      if (!page) return "";
      const params = getFleetUrlParams();
      const missionRaw = (params.get("mission") || "").trim().toLowerCase();
      const worldKeyRaw = (params.get("world_key") || "").trim();
      if (missionRaw) {
        page.dataset.fleetUrlMission = missionRaw;
      } else if (worldKeyRaw) {
        page.dataset.fleetUrlMission = "colonize";
      }
      if (worldKeyRaw) {
        page.dataset.fleetWorldKey = worldKeyRaw;
      }
      return String(page.dataset.fleetUrlMission || "").trim().toLowerCase();
    };

    const isFleetUrlPrefillLocked = (page) => {
      const locked = String(page?.dataset?.fleetUrlMission || "").trim().toLowerCase();
      if (locked) return true;
      return hasFleetWorldKeyPrefill() || !!getFleetUrlMissionPrefill();
    };

    const enforceFleetUrlMissionLock = (page) => {
      const form = getForm(page);
      const ms = form?.querySelector("[data-fleet-mission]");
      if (!ms) return "";
      const locked = String(page.dataset.fleetUrlMission || refreshFleetUrlMissionLock(page) || "").trim().toLowerCase();
      if (!locked) return "";
      const known = Array.from(ms.options).some((opt) => opt.value === locked);
      if (!known) return locked;
      if (ms.value !== locked) {
        ms.value = locked;
        if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(ms);
        if (typeof GC.updateFleetFormMode === "function") GC.updateFleetFormMode(page);
      }
      syncFleetMissionLockUi(page);
      return locked;
    };

    const getFleetWorldKey = (page) => {
      const fromDataset = String(page?.dataset?.fleetWorldKey || "").trim();
      if (fromDataset) return fromDataset;
      return (getFleetUrlParams().get("world_key") || "").trim();
    };
    const getFleetTargetType = (page) => {
      const fromPreview = String(page?.dataset?.fleetNativeTargetType || "").trim().toLowerCase();
      if (fromPreview) return fromPreview;
      const fromUrl = String(getFleetUrlParams().get("target_type") || "").trim().toLowerCase();
      if (fromUrl) return fromUrl;
      return String(page?.dataset?.fleetTargetType || "").trim().toLowerCase();
    };

    const buildFleetTargetPayload = (page) => {
      const wk = getFleetWorldKey(page);
      if (!wk) return {};
      const payload = { world_key: wk };
      const targetType = getFleetTargetType(page);
      if (targetType) payload.target_type = targetType;
      return payload;
    };

    const syncFleetMissionLockUi = (page) => {
      const form = getForm(page);
      const ms = form?.querySelector("[data-fleet-mission]");
      const row = page?.querySelector(".fleet-mission-speed-row");
      if (!ms || !row) return;
      const locked = isFleetUrlPrefillLocked(page);
      ms.disabled = locked;
      row.classList.toggle("is-mission-locked", locked);
      if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(ms);
    };

    const resolveFleetWorldTargetPresentation = (target) => {
      if (!target || typeof target !== "object") return null;
      const sw = target.strategic_world;
      if (sw?.world_key) return { ...sw };
      const wt = target.world_target;
      const worldKey = String(wt?.target_world_key || target.world_key || "").trim();
      if (!worldKey) return null;
      return {
        world_key: worldKey,
        name_key: wt?.target_name_key || sw?.name_key || null,
        display_name: wt?.target_name || null,
        type_key: sw?.type_key || null,
        native_type: wt?.target_type || null,
        role_icon: sw?.role_icon || "✦",
        promise_key: sw?.promise_key || null,
        risk_key: sw?.risk_key || null,
        risk_level: sw?.risk_level || "low",
        reward_hint_key: sw?.reward_hint_key || null,
      };
    };

    const _fleetEsc = (text) => String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

    const formatFleetNamedTarget = (worldTarget, target, fallbackCoords) => {
      const wt = worldTarget || target?.world_target || null;
      const coords = String(fallbackCoords || target?.coords || "").trim();
      if (!wt) {
        const legacyType = String(target?.target_type || "").trim();
        let name = String(target?.target_owner_name || "").trim();
        if (!name && legacyType === "expedition_slot") {
          name = tt("fleet_target_expedition_label", "Deep space");
        }
        if (!name && legacyType === "empty_slot") {
          name = tt("fleet_target_empty_label", "—");
        }
        if (!name) name = coords || "–";
        return {
          name,
          typeLabel: legacyType ? tt(`fleet_target_${legacyType}`, legacyType) : "",
          coords,
        };
      }
      let name = wt.target_name_key
        ? tt(wt.target_name_key, wt.target_name_key)
        : String(wt.target_name || "").trim();
      if (!name && wt.target_type === "expedition_world") {
        name = tt("fleet_target_expedition_label", "Deep space");
      }
      if (!name) name = coords || "–";
      const typeLabel = wt.target_type
        ? tt(`fleet_target_${wt.target_type}`, wt.target_type)
        : "";
      const legacyCoords = wt.legacy_coords;
      const coordsText = legacyCoords
        ? `[${legacyCoords.galaxy}:${legacyCoords.system}:${legacyCoords.position}]`
        : coords;
      return { name, typeLabel, coords: coordsText };
    };

    const renderFleetActiveTargetBlock = (mv) => {
      const named = formatFleetNamedTarget(mv.world_target, null, mv.target_coords);
      const routeHtml = GC.coordRouteHtml(mv.origin_coords, mv.target_coords);
      if (!mv.world_target) {
        return `<div class="fleet-active-coords gc-mono">${routeHtml}</div>`;
      }
      const originName = String(mv.origin_name || "").trim();
      const originPrefix = originName
        ? `<span class="fleet-active-origin-name">${_fleetEsc(originName)}</span><span class="fleet-active-route-arrow" aria-hidden="true">→</span>`
        : "";
      return `<div class="fleet-active-target">
          <div class="fleet-active-target-primary">${originPrefix}<span class="fleet-active-target-name">${_fleetEsc(named.name)}</span></div>
          ${named.typeLabel ? `<span class="fleet-active-target-type">${_fleetEsc(named.typeLabel)}</span>` : ""}
          <div class="fleet-active-coords-secondary gc-mono hint">${routeHtml}</div>
        </div>`;
    };

    const applyFleetPreviewNamedTarget = (page, target, fallbackCoords) => {
      const named = formatFleetNamedTarget(target?.world_target, target, fallbackCoords);
      const previewTargetName = page.querySelector("[data-preview-target-name]");
      const previewTargetNativeType = page.querySelector("[data-preview-target-native-type]");
      const previewTargetCoords = page.querySelector("[data-preview-target-coords]");
      const previewTargetHero = page.querySelector("[data-preview-target-hero]");
      if (previewTargetName) previewTargetName.textContent = named.name || "–";
      if (previewTargetNativeType) previewTargetNativeType.textContent = named.typeLabel || "–";
      if (previewTargetCoords) {
        if (named.coords) {
          previewTargetCoords.textContent = named.coords;
          previewTargetCoords.hidden = false;
        } else {
          previewTargetCoords.textContent = "";
          previewTargetCoords.hidden = true;
        }
      }
      if (previewTargetHero) {
        previewTargetHero.classList.toggle("is-empty", !named.name || named.name === "–");
      }
      return named;
    };

    const clearFleetWorldKey = (page) => {
      if (!page) return;
      delete page.dataset.fleetWorldKey;
      delete page.dataset.fleetTargetType;
      delete page.dataset.fleetNativeTargetType;
      page.querySelector("[data-fleet-coords-row]")?.removeAttribute("hidden");
      page.querySelector("[data-fleet-target-block]")?.classList.remove("is-world-target");
      page.querySelector(".fleet-send-panel")?.classList.remove("is-world-target-mode");
      page.querySelector("[data-fleet-coords-strip]")?.classList.remove("is-world-target");
      const hint = page.querySelector("[data-fleet-coords-hint]");
      if (hint?.dataset.worldTargetHint === "1") {
        hint.textContent = "";
        hint.hidden = true;
        delete hint.dataset.worldTargetHint;
      }
      hideFleetWorldTargetPanel(page);
    };
    const syncFleetWorldTargetUi = (page) => {
      const wk = getFleetWorldKey(page);
      const targetBlock = page.querySelector("[data-fleet-target-block]");
      const coordsRow = page.querySelector("[data-fleet-coords-row]");
      const strip = page.querySelector("[data-fleet-coords-strip]");
      const sendPanel = page.querySelector(".fleet-send-panel");
      const hint = page.querySelector("[data-fleet-coords-hint]");
      if (targetBlock) targetBlock.classList.toggle("is-world-target", !!wk);
      if (coordsRow) coordsRow.hidden = !!wk;
      if (strip) strip.classList.toggle("is-world-target", !!wk);
      if (sendPanel) sendPanel.classList.toggle("is-world-target-mode", !!wk);
      if (!hint) return;
      if (wk) {
        hint.hidden = true;
        delete hint.dataset.worldTargetHint;
      } else if (hint.dataset.worldTargetHint === "1") {
        hint.textContent = "";
        hint.hidden = true;
        delete hint.dataset.worldTargetHint;
      }
    };
    const renderFleetWorldTargetPanel = (page, presentation, extras = {}) => {
      const panel = page.querySelector("[data-fleet-world-target]");
      if (!panel) return;
      const sw = presentation && typeof presentation === "object" ? presentation : null;
      if (!sw?.world_key) {
        panel.hidden = true;
        return;
      }
      panel.hidden = false;
      syncFleetWorldTargetUi(page);
      const iconEl = panel.querySelector("[data-fleet-world-target-icon]");
      const nameEl = panel.querySelector("[data-fleet-world-target-name]");
      const typeEl = panel.querySelector("[data-fleet-world-target-type]");
      const promiseEl = panel.querySelector("[data-fleet-world-target-promise]");
      const riskEl = panel.querySelector("[data-fleet-world-target-risk]");
      const rewardEl = panel.querySelector("[data-fleet-world-target-reward]");
      const missionEl = panel.querySelector("[data-fleet-world-target-mission]");
      const flightEl = panel.querySelector("[data-fleet-world-target-flight]");
      if (iconEl) iconEl.textContent = sw.role_icon || "✦";
      if (nameEl) {
        nameEl.textContent = sw.display_name
          || (sw.name_key ? tt(sw.name_key, sw.name_key) : "–");
      }
      if (typeEl) {
        typeEl.textContent = sw.type_key
          ? tt(sw.type_key, sw.type_key)
          : sw.native_type
            ? tt(`fleet_target_${sw.native_type}`, sw.native_type)
            : "–";
      }
      const setMetaRow = (el, text) => {
        const row = el?.closest("div");
        if (!el || !row) return;
        const label = String(text || "").trim();
        if (!label || label === "–") {
          row.hidden = true;
          el.textContent = "–";
          return;
        }
        row.hidden = false;
        el.textContent = label;
      };
      setMetaRow(promiseEl, sw.promise_key ? tt(sw.promise_key, "") : "");
      if (riskEl) {
        const riskText = sw.risk_key ? tt(sw.risk_key, "") : "";
        setMetaRow(riskEl, riskText);
        if (riskText) {
          riskEl.className = `fleet-world-target-risk fleet-world-target-risk--${sw.risk_level || "low"}`;
        }
      }
      setMetaRow(rewardEl, sw.reward_hint_key ? tt(sw.reward_hint_key, "") : "");
      if (missionEl) {
        const mission = String(extras.mission || "").trim().toLowerCase();
        missionEl.textContent = mission ? tt(`fleet_mission_${mission}`, mission) : "–";
      }
      if (flightEl) {
        flightEl.textContent = extras.flightLabel || "–";
      }
    };
    const hideFleetWorldTargetPanel = (page) => renderFleetWorldTargetPanel(page, null);
    const loadFleetWorldTargetPreview = async (page, worldKey) => {
      const wk = String(worldKey || "").trim();
      if (!wk) {
        hideFleetWorldTargetPanel(page);
        return;
      }
      const mission = getForm(page)?.querySelector("[data-fleet-mission]")?.value || "colonize";
      const previewPath = mission === "expedition"
        ? "/api/worlds/expedition-preview"
        : "/api/worlds/colonize-preview";
      try {
        let res = await GC.fetchJSON(
          `${previewPath}?world_key=${encodeURIComponent(wk)}`,
          { cache: "no-store" }
        );
        if (
          mission === "expedition"
          && (!res?.ok || !res.data?.can_expedition)
        ) {
          res = await GC.fetchJSON(
            `/api/worlds/salvage-preview?world_key=${encodeURIComponent(wk)}`,
            { cache: "no-store" }
          );
        }
        if (res?.ok && res.data?.presentation) {
          const mission = enforceFleetUrlMissionLock(page)
            || getForm(page)?.querySelector("[data-fleet-mission]")?.value
            || "";
          renderFleetWorldTargetPanel(page, res.data.presentation, { mission });
          syncFleetMissionLockUi(page);
        } else {
          hideFleetWorldTargetPanel(page);
        }
      } catch (_) {
        hideFleetWorldTargetPanel(page);
      }
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
      const wk = getFleetWorldKey(page);
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

      if (wk) {
        if (strip) {
          strip.classList.remove("is-expedition");
          strip.classList.add("is-world-target");
        }
        if (sendPanel) sendPanel.classList.toggle("is-expedition-mode", mission === "expedition");
        if (previewHud) previewHud.classList.toggle("is-expedition", mission === "expedition");
        syncFleetWorldTargetUi(page);
        updateFleetFormMode(page);
        if (missionSel) GC.syncHudSelect(missionSel);
        return;
      }

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
      const urlMission = String(page.dataset.fleetUrlMission || refreshFleetUrlMissionLock(page) || "").trim().toLowerCase();
      const locked = isFleetUrlPrefillLocked(page);
      const prevValue = sel.value;
      const allowed = new Set(target.allowed_missions || []);
      Array.from(sel.options).forEach((opt) => {
        if (urlMission && opt.value === urlMission) {
          opt.disabled = false;
          return;
        }
        const ok = allowed.size === 0 || allowed.has(opt.value);
        opt.disabled = !ok;
      });
      if (urlMission && Array.from(sel.options).some((opt) => opt.value === urlMission)) {
        sel.value = urlMission;
      } else if (!locked && allowed.size > 0 && !allowed.has(sel.value)) {
        const first = Array.from(sel.options).find((o) => !o.disabled);
        if (first) sel.value = first.value;
      }
      if (typeof GC.rebuildHudSelect === "function") GC.rebuildHudSelect(sel);
      else if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(sel);
      if (locked) {
        enforceFleetUrlMissionLock(page);
        return;
      }
      if (sel.value !== prevValue && !urlMission) {
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
        const validTarget = target.target_type === "expedition_slot"
          || target.target_type === "strategic_world";
        if (target.target_type && !validTarget) {
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
      .map(([key, qty]) => `<span class="fleet-ship-chip">${tt(`fleet_ship_${key}`, key)} × ${formatNumber(qty)}</span>`)
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
        if (mv.resources?.metal) cargo.push(`${tt("resource_metal")}: ${formatNumber(mv.resources.metal)}`);
        if (mv.resources?.crystal) cargo.push(`${tt("resource_crystal")}: ${formatNumber(mv.resources.crystal)}`);
        if (mv.resources?.fuel_cells) cargo.push(`${tt("resource_fuel_cells")}: ${formatNumber(mv.resources.fuel_cells)}`);
        return `<article class="fleet-active-card fleet-active-card--${mission}" data-fleet-id="${mv.id}" data-status="${mv.status}" data-mission="${mission}" data-leg="${phase}">
          <div class="fleet-active-row">
            <span class="fleet-active-mission fleet-active-mission--${mission}">${tt(`fleet_mission_${mv.mission_type}`, mv.mission_type)}</span>
            <span class="fleet-active-status">${tt(`fleet_status_${mv.status}`, mv.status)}</span>
          </div>
          ${renderFleetActiveTargetBlock(mv)}
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
            el.textContent = formatNumber(state.resources[res] || 0);
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
              if (readNumberInput(inp) > have) setNumberInputValue(inp, have);
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
      const previewTargetName = page.querySelector("[data-preview-target-name]");
      const previewTargetNativeType = page.querySelector("[data-preview-target-native-type]");
      const previewTargetCoords = page.querySelector("[data-preview-target-coords]");
      const previewTargetHero = page.querySelector("[data-preview-target-hero]");
      const previewMissionStatus = page.querySelector("[data-preview-mission-status]");
      const previewMissionBadge = page.querySelector("[data-preview-mission-badge]");
      const previewArrival = page.querySelector("[data-preview-arrival]");
      const missionFeedback = page.querySelector("[data-fleet-mission-feedback]");
      const sendBtn = page.querySelector("[data-fleet-send-btn]");
      const ships = getShipsSelection(page);
      enforceFleetUrlMissionLock(page);
      const missionType = form.querySelector("[data-fleet-mission]")?.value || "transport";
      const resetPreview = () => {
        rt.lastPreview = null;
        if (previewTargetType) previewTargetType.textContent = "–";
        if (previewTargetOwner) previewTargetOwner.textContent = "–";
        if (previewTargetName) previewTargetName.textContent = "–";
        if (previewTargetNativeType) previewTargetNativeType.textContent = "–";
        if (previewTargetCoords) {
          previewTargetCoords.textContent = "–";
          previewTargetCoords.hidden = true;
        }
        if (previewTargetHero) previewTargetHero.classList.add("is-empty");
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
        const originId = resolveFleetOriginPlanetId(page);
        const domPlanetId = getDomPlanetId();
        const res = await GC.fetchJSON("/api/fleet/preview", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            ...(domPlanetId ? { "X-GC-Dom-Planet-Id": String(domPlanetId) } : {}),
          },
          body: JSON.stringify({
            origin_planet_id: originId,
            ships,
            resources: getResourcesSelection(page),
            speed_percent: parseInt(form.querySelector("[data-fleet-speed]")?.value || "100", 10),
            mission_type: missionType,
            ...getTargetCoords(page),
            ...buildFleetTargetPayload(page),
          }),
        });
        const p = fleetPayload(res).preview || res.preview;
        if (res?.ok && p) {
          rt.lastPreview = p;
          const target = p.target || {};
          const named = applyFleetPreviewNamedTarget(page, target, target.coords);
          if (previewTargetType) {
            previewTargetType.textContent = named.typeLabel
              || (target.target_type ? tt(`fleet_target_${target.target_type}`, target.target_type) : "–");
          }
          if (previewTargetOwner) {
            previewTargetOwner.textContent = named.name || "–";
          }
          const debrisRow = page.querySelector("[data-preview-debris-row]");
          const previewDebris = page.querySelector("[data-preview-debris]");
          if (debrisRow && previewDebris) {
            const showDebris = missionType === "recycle";
            debrisRow.hidden = !showDebris;
            if (showDebris) previewDebris.textContent = formatDebrisPreview(target.debris);
          }
          syncMissionAllowlistFromTarget(page, target);
          const lockedMission = enforceFleetUrlMissionLock(page) || missionType;
          const wk = getFleetWorldKey(page);
          if (wk) {
            if (target.world_target?.target_type) {
              page.dataset.fleetNativeTargetType = String(target.world_target.target_type);
            }
            const presentation = resolveFleetWorldTargetPresentation(target);
            if (presentation) {
              renderFleetWorldTargetPanel(page, presentation, {
                mission: lockedMission,
                flightLabel: formatFleetDuration(p.duration_seconds ?? p.flight_seconds ?? 0),
              });
            }
            syncFleetWorldTargetUi(page);
          } else if (target.strategic_world) {
            renderFleetWorldTargetPanel(page, target.strategic_world, { mission: lockedMission });
          } else {
            hideFleetWorldTargetPanel(page);
          }
          updateFleetFormMode(page);
          if (previewMissionBadge) {
            previewMissionBadge.textContent = tt(`fleet_mission_${lockedMission}`, lockedMission);
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
              lockedMission === "expedition"
                && (target.target_type === "expedition_slot" || target.target_type === "strategic_world")
            );
            previewHud.classList.toggle("is-ready", !!p.can_send);
            previewHud.classList.toggle("is-blocked", !p.can_send);
          }
          updateMissionFeedback(page, p, lockedMission, ships);
          if (previewCargo) previewCargo.textContent = `${p.cargo_used || 0} / ${p.cargo_total || 0}`;
          if (previewCargoFree) previewCargoFree.textContent = String(p.cargo_free || 0);
          if (previewFuel) previewFuel.textContent = String(p.fuel_cost || 0);
          if (previewFuelAvail) previewFuelAvail.textContent = String(p.fuel_available ?? rt.data.resources?.fuel_cells ?? "–");
          if (previewFlight) {
            previewFlight.textContent = formatCountdownRemain(p.duration_seconds ?? p.flight_seconds ?? 0);
          }
          if (previewArrival) {
            const arrivalAt = parseTimerTarget(p.countdown_at || p.arrival_at || 0);
            if (arrivalAt > 0) {
              previewArrival.dataset.timerTarget = String(arrivalAt);
              previewArrival.dataset.countdownAt = String(arrivalAt);
              previewArrival.dataset.timerKind = "fleet";
              const nowSec = getTimerServerNow();
              const rem = queueJobRemainingSeconds(arrivalAt, nowSec);
              previewArrival.textContent = formatCountdownRemain(rem);
              GC.startProgressTicker();
            } else {
              delete previewArrival.dataset.timerTarget;
              delete previewArrival.dataset.countdownAt;
              delete previewArrival.dataset.timerKind;
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
      enforceFleetUrlMissionLock(page);
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
      const params = getFleetUrlParams();
      if (params.has("world_key") || params.get("mission")) {
        return;
      }
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
      if (mission && ms && !isFleetUrlPrefillLocked(page)) {
        ms.value = mission;
        GC.syncHudSelect(ms);
        setColonizeRowVisible(page, mission);
      } else if (ms && ms.value === "expedition" && !isFleetUrlPrefillLocked(page)) {
        ms.value = "transport";
        GC.syncHudSelect(ms);
        setColonizeRowVisible(page, "transport");
      }
      if (!isFleetUrlPrefillLocked(page)) {
        delete page.dataset.fleetUrlMission;
        clearFleetWorldKey(page);
      }
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
    GC.getFleetWorldKey = getFleetWorldKey;
    GC.clearFleetWorldKey = clearFleetWorldKey;
    GC.syncFleetWorldTargetUi = syncFleetWorldTargetUi;
    GC.renderFleetWorldTargetPanel = renderFleetWorldTargetPanel;
    GC.loadFleetWorldTargetPreview = loadFleetWorldTargetPreview;
    GC.enforceFleetUrlMissionLock = enforceFleetUrlMissionLock;
    GC.buildFleetTargetPayload = buildFleetTargetPayload;
    GC.syncFleetMissionLockUi = syncFleetMissionLockUi;
    GC.resolveFleetWorldTargetPresentation = resolveFleetWorldTargetPresentation;

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
        if (inp) setNumberInputValue(inp, have);
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
        if (inp) setNumberInputValue(inp, Math.max(0, val));
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
        if (e.target.value === "expedition" && !getFleetWorldKey(page)) applyExpeditionTarget(page);
        syncExpeditionMissionTarget(page);
        updateFleetFormMode(page);
        const wk = getFleetWorldKey(page);
        if (wk) loadFleetWorldTargetPreview(page, wk);
        schedulePreview(page);
      }
      if (e.target.matches('[name="target_galaxy"], [name="target_system"], [name="target_position"]')) {
        if (!isFleetUrlPrefillLocked(page)) {
          delete page.dataset.fleetUrlMission;
          clearFleetWorldKey(page);
        }
        syncExpeditionMissionTarget(page);
      }
      if (e.target.closest("#fleet-send-form")) schedulePreview(page);
    });

    document.addEventListener("input", (e) => {
      const page = getPage();
      if (!page) return;
      if (e.target.matches('[name="target_galaxy"], [name="target_system"], [name="target_position"]')) {
        if (!isFleetUrlPrefillLocked(page)) {
          delete page.dataset.fleetUrlMission;
          clearFleetWorldKey(page);
        }
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
          enforceFleetUrlMissionLock(page);
          const originId = resolveFleetOriginPlanetId(page);
          const domPlanetId = getDomPlanetId();
          const res = await GC.fetchGameAction("/api/fleet/send", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(domPlanetId ? { "X-GC-Dom-Planet-Id": String(domPlanetId) } : {}),
            },
            body: JSON.stringify({
              origin_planet_id: originId,
              ships: getShipsSelection(page),
              resources: getResourcesSelection(page),
              speed_percent: parseInt(form.querySelector("[data-fleet-speed]")?.value || "100", 10),
              mission_type: form.querySelector("[data-fleet-mission]")?.value,
              colony_name: form.querySelector("[data-fleet-colony-name]")?.value || undefined,
              ...getTargetCoords(page),
              ...buildFleetTargetPayload(page),
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
            }
            await refreshFleetState(page);
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
          const originId = resolveFleetOriginPlanetId(page);
          const res = await GC.fetchGameAction("/api/fleet/mass-expedition", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              origin_planet_id: originId,
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
    const max = parseIntNumber(inp.getAttribute("max") || "0");
    let v = readNumberInput(inp);
    if (!Number.isFinite(v) || v < 0) v = 0;
    if (Number.isFinite(max) && max >= 0 && v > max) v = max;
    setNumberInputValue(inp, v);
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
      const qty = readNumberInput(inp);
      if (key && qty > 0) ships[key] = qty;
    });
    return ships;
  }

  function getLogisticsResourcesSelection(page) {
    const resources = { metal: 0, crystal: 0, fuel_cells: 0 };
    page.querySelectorAll("[data-logistics-resource]").forEach((inp) => {
      const key = inp.getAttribute("data-logistics-resource");
      if (!key) return;
      resources[key] = Math.max(0, readNumberInput(inp));
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
          if (readNumberInput(inp) > have) setNumberInputValue(inp, have);
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
        inp.value = formatNumber(parseInt(row.dataset.shipHave || inp.getAttribute("max") || "0", 10) || 0);
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
    const initMission = (initParams.get("mission") || "").trim();
    const initWorldKey = (initParams.get("world_key") || "").trim();
    if (!initMission && !initWorldKey) {
      delete page.dataset.fleetUrlMission;
    }
    if (!initWorldKey) {
      delete page.dataset.fleetWorldKey;
      delete page.dataset.fleetTargetType;
      delete page.dataset.fleetNativeTargetType;
    }

    const rt = getFleetRuntime(page);
    rt.data = parseFleetPageData(page);
    rt.lastPreview = null;
    resolveFleetOriginPlanetId(page);

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
    if (typeof GC.syncFleetMissionLockUi === "function") GC.syncFleetMissionLockUi(page);
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
      if (typeof GC.updateFleetFormMode === "function") GC.updateFleetFormMode(page);
    } else {
      delete page.dataset.fleetUrlMission;
    }

    const worldKeyRaw = (params.get("world_key") || "").trim();
    const targetTypeRaw = (params.get("target_type") || "").trim().toLowerCase();
    if (worldKeyRaw) {
      page.dataset.fleetWorldKey = worldKeyRaw;
      if (targetTypeRaw) {
        page.dataset.fleetTargetType = targetTypeRaw;
      }
      if (!missionKnown && ms) {
        page.dataset.fleetUrlMission = "colonize";
        ms.value = "colonize";
        if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(ms);
        if (typeof GC.updateFleetFormMode === "function") GC.updateFleetFormMode(page);
      }
      if (typeof GC.syncFleetWorldTargetUi === "function") GC.syncFleetWorldTargetUi(page);
      if (typeof GC.loadFleetWorldTargetPreview === "function") {
        GC.loadFleetWorldTargetPreview(page, worldKeyRaw);
      }
    } else if (typeof GC.clearFleetWorldKey === "function") {
      GC.clearFleetWorldKey(page);
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
      if (typeof GC.updateFleetFormMode === "function") GC.updateFleetFormMode(page);
    }
    if (typeof GC.syncFleetWorldTargetUi === "function") GC.syncFleetWorldTargetUi(page);
    if (typeof GC.enforceFleetUrlMissionLock === "function") GC.enforceFleetUrlMissionLock(page);
    if (typeof GC.syncFleetMissionLockUi === "function") GC.syncFleetMissionLockUi(page);
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

  function clearAllProductionCardQueues(page) {
    if (!page) return;
    page.querySelectorAll("[data-ship-card], [data-defense-card]").forEach((card) => {
      clearProductionCardQueueState(card);
    });
  }

  function clearProductionCardQueueState(card) {
    if (!card) return;
    delete card.dataset.queueHeadJobId;
    delete card.dataset.queuePending;
    GC.clearCardQueueBlock(card);
    card.classList.remove(
      "gc-ship-card--in-queue",
      "gc-ship-card--queue-active",
      "gc-ship-card--queue-pending"
    );
  }

  function patchShipyardCardQueues(page, queueData) {
    if (!page) return;
    const byOwner =
      queueData?.card_jobs_by_owner && typeof queueData.card_jobs_by_owner === "object"
        ? queueData.card_jobs_by_owner
        : {};
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
      _shipyardUnitFinishKey = "";
      SHIPYARDQ.active.finishTime = 0;
      SHIPYARDQ.active.totalSeconds = 0;
      _updateShipyardQueueCompact(0);
      clearAllProductionCardQueues(page);
      patchShipyardCardQueues(page, { queue: [], summary: { count: 0 }, card_jobs_by_owner: {} });
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

  function patchProductionStatChips(card, cycleSeconds, batchCapacity, tt) {
    const grid = card?.querySelector("[data-production-stats]");
    if (!grid) return;
    const sec = Math.max(0, Math.round(Number(cycleSeconds) || 0));
    const cap = Math.max(1, Math.round(Number(batchCapacity) || 1));
    const cycleEl = grid.querySelector("[data-prod-cycle-seconds]");
    if (cycleEl) {
      const cycleText = `${fmtNumber(sec)}s`;
      if (cycleEl.textContent !== cycleText) cycleEl.textContent = cycleText;
    }
    const capEl = grid.querySelector("[data-prod-batch-capacity]");
    if (capEl) {
      const capParts = fmtIntParts(cap);
      if (capEl.textContent !== capParts.display) capEl.textContent = capParts.display;
      if (capParts.display !== capParts.full) capEl.title = capParts.full;
      else capEl.removeAttribute("title");
    }
    if (tt) {
      const ariaTpl = tt("prod_stat_aria", "Zyklus %(cycle)s Sekunden, parallel %(capacity)s");
      const aria = ariaTpl
        .replace("%(cycle)s", fmtNumber(sec))
        .replace("%(capacity)s", fmtIntParts(cap).full);
      if (grid.getAttribute("aria-label") !== aria) grid.setAttribute("aria-label", aria);
    }
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

    if (ship.build_seconds != null) {
      const page = card.closest("#shipyard-page");
      const unitCap =
        Number(ship.effective_batch_capacity) > 0
          ? Number(ship.effective_batch_capacity)
          : Number(page?.dataset.shipyardBatchCapacity || 1) || 1;
      patchProductionStatChips(card, ship.build_seconds, unitCap, tt);
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
    const qtyInp = card.querySelector(`[data-shipyard-qty="${ship.ship_key}"]`);
    if (qtyInp) {
      const cap = Number(ship.max_build) || 0;
      if (cap > 0) qtyInp.dataset.inputMax = String(cap);
      else qtyInp.removeAttribute("data-input-max");
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
    if (data.production_batch_capacity != null) {
      page.dataset.shipyardBatchCapacity = String(data.production_batch_capacity);
      const capEl = page.querySelector("[data-shipyard-batch-capacity]");
      if (capEl) {
        capEl.textContent = tt(
          "shipyard_parallel_capacity",
          "Parallel production: %(capacity)s units per cycle"
        ).replace("%(capacity)s", fmtNumber(data.production_batch_capacity));
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
      if (card && !ship.queue_job) clearProductionCardQueueState(card);
    });

    (data.locked_ships || []).forEach((ship) => {
      const card = page.querySelector(`[data-ship-key="${ship.ship_key}"][data-unlocked="0"]`);
      applyShipyardShipCard(card, ship, resources, syLevel, tt);
      if (card && !ship.queue_job) clearProductionCardQueueState(card);
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
        const maxQty = parseIntNumber(maxBtn.dataset.maxQty || "0");
        if (qtyInp && maxQty > 0) setNumberInputValue(qtyInp, maxQty);
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
      const amount = readNumberInput(qtyInp) || 1;
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
    const byOwner =
      queueData?.card_jobs_by_owner && typeof queueData.card_jobs_by_owner === "object"
        ? queueData.card_jobs_by_owner
        : {};
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
      _defenseUnitFinishKey = "";
      DEFENSEQ.active.finishTime = 0;
      DEFENSEQ.active.totalSeconds = 0;
      _updateDefenseQueueCompact(0);
      clearAllProductionCardQueues(page);
      patchDefenseCardQueues(page, { queue: [], summary: { count: 0 }, card_jobs_by_owner: {} });
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
    if (data.production_batch_capacity != null) {
      page.dataset.defenseBatchCapacity = String(data.production_batch_capacity);
      const capEl = page.querySelector("[data-defense-batch-capacity]");
      if (capEl) {
        capEl.textContent = tt(
          "defense_production_capacity",
          "Production via orbital shipyard capacity: %(capacity)s per cycle"
        ).replace("%(capacity)s", fmtNumber(data.production_batch_capacity));
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
      const card = page.querySelector(`[data-defense-card="${unit.defense_key}"]`);
      applyDefenseUnitCard(page, unit, data.resources || {}, tt);
      if (card && !unit.queue_job) clearProductionCardQueueState(card);
    });
    (data.locked_defense || []).forEach((unit) => {
      const card = page.querySelector(`[data-defense-card="${unit.defense_key}"]`);
      applyDefenseUnitCard(page, unit, data.resources || {}, tt, { locked: true });
      if (card && !unit.queue_job) clearProductionCardQueueState(card);
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
    const qtyInp = card.querySelector(`[data-defense-qty="${unit.defense_key}"]`);
    if (qtyInp) {
      const cap = Number(unit.max_build) || 0;
      if (cap > 0) qtyInp.dataset.inputMax = String(cap);
      else qtyInp.removeAttribute("data-input-max");
    }
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
    if (unit.build_seconds != null) {
      const unitCap =
        Number(unit.effective_batch_capacity) > 0
          ? Number(unit.effective_batch_capacity)
          : Number(page?.dataset.defenseBatchCapacity || 1) || 1;
      patchProductionStatChips(card, unit.build_seconds, unitCap, tt);
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
        const maxQty = parseIntNumber(maxBtn.dataset.maxQty || "0");
        if (qtyInp && maxQty > 0) setNumberInputValue(qtyInp, maxQty);
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
      const amount = readNumberInput(qtyInp) || 1;
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
    const dailyUsedEl = page?.querySelector("[data-exchange-daily-used]");
    const dailyLimitEl = page?.querySelector("[data-exchange-daily-limit]");
    const dailyLimitDisplayEl = page?.querySelector("[data-exchange-daily-limit-display]");
    const empireDayEl = page?.querySelector("[data-exchange-empire-day]");
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
      if (!amountInput.value || readNumberInput(amountInput) < minNow) {
        setNumberInputValue(amountInput, minNow);
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
      const raw = readNumberInput(amountInput);
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
      previewEl.textContent = formatNumber(receive);
      if (receiveSummaryEl) {
        receiveSummaryEl.textContent = `${formatNumber(receive)} ${receiveLabel}`;
      }
    };

    const patchExchangeFromState = (exchange) => {
      if (!exchange) return;
      if (typeof exchange.daily_used === "number" && dailyUsedEl) {
        dailyUsedEl.textContent = fmtNumber(exchange.daily_used);
      }
      if (typeof exchange.daily_remaining === "number" && remainingEl) {
        remainingEl.textContent = fmtNumber(exchange.daily_remaining);
      }
      if (typeof exchange.daily_limit === "number" && dailyLimitEl) {
        dailyLimitEl.textContent = fmtNumber(exchange.daily_limit);
      }
      if (typeof exchange.daily_limit === "number" && dailyLimitDisplayEl) {
        dailyLimitDisplayEl.textContent = fmtNumber(exchange.daily_limit);
      }
      if (typeof exchange.empire_production_day_total === "number" && empireDayEl) {
        empireDayEl.textContent = tf(
          "trader_hub_empire_production_day",
          { total: fmtNumber(exchange.empire_production_day_total) },
          `Empire / Tag: ${fmtNumber(exchange.empire_production_day_total)}`
        );
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

        const amount = readNumberInput(amountInput);
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
          .replace("%(amount)s", formatNumber(amount))
          .replace("%(give)s", resourceLabels[from]())
          .replace("%(receive)s", formatNumber(receive))
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
      const haveLabel = tt("scrapyard_have", "Available: %(count)s").replace("%(count)s", formatNumber(amount));
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
                ${formatNumber(minM)}–${formatNumber(maxM)} ${metalLabel},
                ${formatNumber(minC)}–${formatNumber(maxC)} ${crystalLabel}
              </span>
            </div>
          </div>
          <div class="fleet-ship-row-controls gc-trader-scrap-actions">
            <input type="text" inputmode="numeric" class="gc-trader-input fleet-ship-input gc-scrapyard-qty gc-num-input" min="1" max="${amount}" value="1"
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
    bindFormattedNumberInputs(panel);

    const tt = (key, fallback) => t(key, fallback);
    const errorEl = panel.querySelector("[data-scrapyard-error]");
    const reasonText = (reason) => tt(`scrapyard_error_${reason}`, tt("scrapyard_error_generic", "Recycle failed."));

    panel.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-scrap-recycle]");
      if (!btn) return;
      const shipKey = btn.getAttribute("data-scrap-recycle");
      const row = btn.closest("[data-scrap-ship]");
      const qtyInp = row?.querySelector(`[data-scrap-qty="${shipKey}"]`);
      const amount = readNumberInput(qtyInp);
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
    bindFormattedNumberInputs(list);
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
    initBuildingTechnicalData();
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

  function empireIdentityLabelKey(planet) {
    if (!planet) return "";
    return (
      planet.identity_title_key ||
      planet.empire_subtitle_key ||
      planet.empire_role_label_key ||
      ""
    );
  }

  function rebuildHeaderPlanetSwitcher(planets) {
    const root = document.getElementById("gc-planet-switcher");
    if (!root || !Array.isArray(planets) || !planets.length) return;

    const active = planets.find((p) => p.is_active) || planets[0];
    const multi = planets.length > 1;

    root.dataset.multi = multi ? "1" : "0";
    root.dataset.activePlanetId = String(active.planet_id || "");

    const trigger = document.getElementById("gc-planet-switcher-trigger");
    const nameEl = root.querySelector("[data-planet-switcher-name]");
    const roleEl = root.querySelector("[data-planet-switcher-role]");
    const iconEl = root.querySelector("[data-planet-switcher-icon]");
    const coordEl = root.querySelector("[data-planet-switcher-coord]");
    if (nameEl) nameEl.textContent = active.name || "";
    if (iconEl) {
      iconEl.textContent = active.empire_role_icon || "";
      iconEl.hidden = !active.empire_role_icon;
    }
    if (roleEl) {
      const roleKey = empireIdentityLabelKey(active);
      const roleText = roleKey ? t(roleKey, roleKey) : "";
      roleEl.textContent = roleText;
      roleEl.hidden = !roleText;
    }
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
      btn.dataset.planetRoleKey = p.empire_role_key || "";
      btn.dataset.planetRoleLabelKey = p.empire_role_label_key || "";
      btn.dataset.planetRoleIcon = p.empire_role_icon || "";
      btn.dataset.planetIdentityKey = empireIdentityLabelKey(p);

      const nameRow = document.createElement("span");
      nameRow.className = "gc-planet-switcher-item-name-row";
      if (p.empire_role_icon) {
        const iconSpan = document.createElement("span");
        iconSpan.className = "gc-planet-switcher-item-icon";
        iconSpan.setAttribute("aria-hidden", "true");
        iconSpan.textContent = p.empire_role_icon;
        nameRow.appendChild(iconSpan);
      }
      const nameSpan = document.createElement("span");
      nameSpan.className = "gc-planet-switcher-item-name";
      nameSpan.textContent = p.name || "";
      nameRow.appendChild(nameSpan);

      const metaSpan = document.createElement("span");
      metaSpan.className = "gc-planet-switcher-item-meta";
      const identityKey = empireIdentityLabelKey(p);
      if (identityKey) {
        const roleSpan = document.createElement("span");
        roleSpan.className = "gc-planet-switcher-item-role";
        roleSpan.textContent = t(identityKey, identityKey);
        metaSpan.appendChild(roleSpan);
      }
      const coord = p.coordinates_formatted || "";
      if (coord) {
        const coordSpan = document.createElement("span");
        coordSpan.className = "gc-planet-switcher-item-coord gc-mono";
        coordSpan.innerHTML = GC.coordLinkHtml(coord, { label: coord });
        metaSpan.appendChild(coordSpan);
      }

      btn.appendChild(nameRow);
      btn.appendChild(metaSpan);
      menu.appendChild(btn);
    });
  }

  function updateHeaderPlanetSwitcherFromPlanets(planets) {
    rebuildHeaderPlanetSwitcher(planets);
  }

  function buildSidebarNavFromRole(empireRoleKey, isHomeworld) {
    const cfg = window.GC_SIDEBAR_NAV_CONFIG || {};
    const allModules = Array.isArray(cfg.all_modules) ? cfg.all_modules : [];
    const homeworldRoles = new Set(Array.isArray(cfg.homeworld_roles) ? cfg.homeworld_roles : ["homeworld"]);
    const role = String(empireRoleKey || "general").trim().toLowerCase();
    if (isHomeworld || homeworldRoles.has(role)) {
      const modules = {};
      allModules.forEach((key) => { modules[key] = "prominent"; });
      return {
        empire_role_key: "homeworld",
        is_homeworld: true,
        full_nav: true,
        show_more_section: false,
        modules,
      };
    }
    const prominent = cfg.prominent_by_role && cfg.prominent_by_role[role];
    if (!Array.isArray(prominent) || !prominent.length) {
      const modules = {};
      allModules.forEach((key) => { modules[key] = "prominent"; });
      return {
        empire_role_key: role,
        is_homeworld: false,
        full_nav: true,
        show_more_section: false,
        modules,
      };
    }
    const prominentSet = new Set(prominent);
    const modules = {};
    allModules.forEach((key) => {
      modules[key] = prominentSet.has(key) ? "prominent" : "secondary";
    });
    return {
      empire_role_key: role,
      is_homeworld: false,
      full_nav: false,
      show_more_section: true,
      modules,
    };
  }

  function resolveSidebarNavFromState(data) {
    if (!data || typeof data !== "object") return null;
    if (data.active_planet && data.active_planet.sidebar_nav) {
      return data.active_planet.sidebar_nav;
    }
    const activeId = Number(data.active_planet_id || data.active_planet?.planet_id || 0);
    if (!activeId) return null;
    let roleKey = "general";
    let isHomeworld = false;
    const ap = data.active_planet;
    if (ap && Number(ap.planet_id) === activeId) {
      roleKey = ap.empire_role_key || roleKey;
      isHomeworld = !!ap.is_homeworld;
    } else if (Array.isArray(data.planets)) {
      const row = data.planets.find((p) => Number(p.planet_id) === activeId);
      if (row) {
        roleKey = row.empire_role_key || roleKey;
        isHomeworld = !!row.is_homeworld;
      }
    }
    return buildSidebarNavFromRole(roleKey, isHomeworld);
  }

  const MOBILE_BOTTOM_PRIORITY = (() => {
    const cfg = window.GC_SIDEBAR_NAV_CONFIG || {};
    return Array.isArray(cfg.mobile_bottom_priority) && cfg.mobile_bottom_priority.length
      ? cfg.mobile_bottom_priority
      : [
        "overview",
        "buildings",
        "research",
        "defense",
        "logistics",
        "fleet",
        "galaxy",
        "planet_evolution",
        "trading",
        "ranking",
      ];
  })();
  const MOBILE_BOTTOM_MAX = Number((window.GC_SIDEBAR_NAV_CONFIG || {}).mobile_bottom_max) || 4;

  function navTierForModule(nav, module) {
    const fullNav = !!nav.full_nav;
    const modules = nav.modules && typeof nav.modules === "object" ? nav.modules : {};
    return fullNav ? "prominent" : (modules[module] || "prominent");
  }

  function applyRoleNavTiers(root, nav) {
    if (!root || !nav) return;
    const fullNav = !!nav.full_nav;
    const modules = nav.modules && typeof nav.modules === "object" ? nav.modules : {};
    root.dataset.navRole = String(nav.empire_role_key || "general");
    root.dataset.navFull = fullNav ? "1" : "0";

    root.querySelectorAll("[data-nav-module]").forEach((el) => {
      const key = String(el.dataset.navModule || "");
      const tier = fullNav ? "prominent" : (modules[key] || "prominent");
      el.dataset.navTier = tier;
      el.classList.remove("gc-nav-module--prominent", "gc-nav-module--secondary");
      el.classList.add(`gc-nav-module--${tier}`);
    });

    root.querySelectorAll("[data-nav-group]").forEach((group) => {
      const keys = String(group.dataset.navGroupModules || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const tiers = keys.map((key) => (fullNav ? "prominent" : (modules[key] || "prominent")));
      const anyProminent = tiers.some((tier) => tier === "prominent");
      const allSecondary = tiers.length > 0 && tiers.every((tier) => tier === "secondary");
      group.classList.toggle("gc-nav-group--prominent", anyProminent);
      group.classList.toggle("gc-nav-group--secondary", allSecondary);
    });
  }

  function moduleDisplaySection(nav, module) {
    const cfg = window.GC_SIDEBAR_NAV_CONFIG || {};
    const standalone = new Set(
      Array.isArray(cfg.standalone_modules) ? cfg.standalone_modules : ["messages"]
    );
    if (standalone.has(module)) return module;
    const primaryMap = cfg.module_primary_section || {};
    if (module === "support") return null;
    const utility = new Set(
      Array.isArray(cfg.utility_modules)
        ? cfg.utility_modules
        : (cfg.administration_modules || [])
    );
    if (utility.has(module)) return "administration";
    return primaryMap[module] || null;
  }

  function shouldShowSidebarNavLink(nav, el) {
    const module = String(el.dataset.navModule || "");
    if (!module) return false;
    const display = moduleDisplaySection(nav, module);
    if (!display) return false;
    const section = String(el.closest("[data-nav-section]")?.dataset.navSection || "");
    return display === section;
  }

  function navLinkShows(nav, module, placement) {
    const display = moduleDisplaySection(nav, module);
    if (!display) return false;
    if (placement === "administration") return display === "administration";
    return display === (window.GC_SIDEBAR_NAV_CONFIG?.module_primary_section || {})[module];
  }

  const NAV_SECTION_STORAGE_KEY = "gc_sidebar_state";

  function readNavSectionState() {
    try {
      return JSON.parse(localStorage.getItem(NAV_SECTION_STORAGE_KEY) || "{}");
    } catch (_) {
      return {};
    }
  }

  function writeNavSectionState(state) {
    try {
      localStorage.setItem(NAV_SECTION_STORAGE_KEY, JSON.stringify(state));
    } catch (_) {}
  }

  function resolveNavSectionExpanded(section, state) {
    const key = String(section.dataset.navSection || "");
    if (key && Object.prototype.hasOwnProperty.call(state, key)) {
      return !!state[key];
    }
    return section.classList.contains("is-expanded");
  }

  function resolveNavGroupExpanded(group, state) {
    const key = String(group.dataset.navGroupKey || "");
    if (key && Object.prototype.hasOwnProperty.call(state, key)) {
      return !!state[key];
    }
    if (key === "buildings") {
      return typeof GC.detectPage === "function" && GC.detectPage() === "buildings";
    }
    return false;
  }

  function setNavSectionExpanded(section, expanded, persist) {
    if (!section) return;
    const toggle = section.querySelector(".gc-nav-section-toggle");
    const body = section.querySelector(".gc-nav-section-body");
    if (!toggle || !body) return;
    section.classList.toggle("is-expanded", expanded);
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    if (persist) {
      const key = String(section.dataset.navSection || "");
      if (!key) return;
      const state = readNavSectionState();
      state[key] = expanded;
      writeNavSectionState(state);
    }
  }

  function setNavGroupExpanded(group, expanded, persist) {
    if (!group) return;
    const toggle = group.querySelector(".gc-nav-group-toggle");
    const body = group.querySelector(".gc-nav-group-body");
    if (!toggle || !body) return;
    group.classList.toggle("is-expanded", expanded);
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    if (persist) {
      const key = String(group.dataset.navGroupKey || "");
      if (!key) return;
      const state = readNavSectionState();
      state[key] = expanded;
      writeNavSectionState(state);
    }
  }

  function syncNavGroupAccordionState(sidebar, state) {
    if (!sidebar) return;
    const stored = state || readNavSectionState();
    sidebar.querySelectorAll("[data-nav-group-key]").forEach((group) => {
      if (group.hidden) return;
      setNavGroupExpanded(group, resolveNavGroupExpanded(group, stored), false);
    });
  }

  function syncNavSectionAccordionState(sidebar) {
    if (!sidebar) return;
    const state = readNavSectionState();
    sidebar.querySelectorAll("[data-nav-section]").forEach((section) => {
      if (section.hidden) return;
      setNavSectionExpanded(section, resolveNavSectionExpanded(section, state), false);
    });
    syncNavGroupAccordionState(sidebar, state);
  }

  function applyDesktopSidebarNav(sidebar, nav) {
    if (!sidebar || !nav) return;
    applyRoleNavTiers(sidebar, nav);
    const fullNav = !!nav.full_nav;
    sidebar.classList.toggle("gc-sidebar--full-nav", fullNav);
    sidebar.classList.toggle("gc-sidebar--role-nav", !fullNav);

    sidebar.querySelectorAll("[data-nav-module]").forEach((el) => {
      el.hidden = true;
    });
    sidebar.querySelectorAll("[data-nav-module]").forEach((el) => {
      if (shouldShowSidebarNavLink(nav, el)) {
        el.hidden = false;
      }
    });

    sidebar.querySelectorAll("[data-nav-section]").forEach((section) => {
      const anyVisible = !!section.querySelector("[data-nav-module]:not([hidden])");
      section.hidden = !anyVisible;
    });

    syncNavSectionAccordionState(sidebar);
  }

  function applyMobileBottomNav(bottomNav, nav) {
    if (!bottomNav || !nav) return new Set(["overview", "buildings", "research", "messages"]);
    applyRoleNavTiers(bottomNav, nav);
    const fullNav = !!nav.full_nav;
    bottomNav.classList.toggle("gc-bottom-nav--full-nav", fullNav);
    bottomNav.classList.toggle("gc-bottom-nav--role-nav", !fullNav);

    const cfg = window.GC_SIDEBAR_NAV_CONFIG || {};
    const alwaysBottom = Array.isArray(cfg.mobile_always_bottom) ? cfg.mobile_always_bottom : ["messages"];
    const slotMax = Math.max(0, MOBILE_BOTTOM_MAX - alwaysBottom.length);
    const prominent = MOBILE_BOTTOM_PRIORITY.filter(
      (key) => !alwaysBottom.includes(key) && navTierForModule(nav, key) === "prominent"
    );
    const visible = fullNav
      ? ["overview", "buildings", "research"].slice(0, slotMax)
      : prominent.slice(0, slotMax);
    const visibleSet = new Set([...visible, ...alwaysBottom]);

    bottomNav.querySelectorAll("a.gc-bottom-nav-item[data-nav-module]").forEach((el) => {
      const key = String(el.dataset.navModule || "");
      const show = visibleSet.has(key) || el.dataset.navAlwaysVisible === "1";
      el.hidden = !show;
      el.classList.toggle("gc-nav-bottom-slot", show);
    });

    return visibleSet;
  }

  function applyMobileDrawerNav(drawer, nav, bottomModules) {
    if (!drawer || !nav) return;
    applyRoleNavTiers(drawer, nav);
    const fullNav = !!nav.full_nav;
    const bottomSet = bottomModules instanceof Set ? bottomModules : new Set(bottomModules || []);
    drawer.classList.toggle("gc-nav-drawer--full-nav", fullNav);
    drawer.classList.toggle("gc-nav-drawer--role-nav", !fullNav);

    drawer.querySelectorAll("[data-nav-module]").forEach((el) => {
      el.hidden = true;
    });
    drawer.querySelectorAll("[data-nav-module]").forEach((el) => {
      const module = String(el.dataset.navModule || "");
      if (bottomSet.has(module)) return;
      if (fullNav) {
        el.hidden = false;
        return;
      }
      el.hidden = !mobileDrawerShowsModule(nav, module, bottomSet);
    });

    drawer.querySelectorAll("[data-nav-group]").forEach((group) => {
      const links = group.querySelectorAll("[data-nav-module]");
      let anyVisible = false;
      links.forEach((el) => {
        if (!el.hidden) anyVisible = true;
      });
      group.hidden = !anyVisible;
    });
  }

  function mobileDrawerShowsModule(nav, module, bottomSet) {
    if (bottomSet.has(module)) return false;
    const utility = new Set(
      Array.isArray(window.GC_SIDEBAR_NAV_CONFIG?.utility_modules)
        ? window.GC_SIDEBAR_NAV_CONFIG.utility_modules
        : (window.GC_SIDEBAR_NAV_CONFIG?.administration_modules || [])
    );
    if (utility.has(module)) return true;
    const display = moduleDisplaySection(nav, module);
    if (display === "administration") {
      return navTierForModule(nav, module) === "secondary";
    }
    return display === (window.GC_SIDEBAR_NAV_CONFIG?.module_primary_section || {})[module]
      && navTierForModule(nav, module) === "prominent";
  }

  GC.syncRoleBasedSidebar = function syncRoleBasedSidebar(data) {
    const nav = resolveSidebarNavFromState(data);
    if (!nav) return;

    const sidebar = document.getElementById("gc-sidebar-nav");
    if (sidebar) applyDesktopSidebarNav(sidebar, nav);

    const bottomNav = document.getElementById("gc-bottom-nav");
    const drawer = document.getElementById("gc-nav-drawer");
    if (bottomNav || drawer) {
      const bottomModules = bottomNav
        ? applyMobileBottomNav(bottomNav, nav)
        : new Set();
      if (drawer) applyMobileDrawerNav(drawer, nav, bottomModules);
    }
  };

  function initRoleBasedSidebar() {
    if (GC._roleBasedSidebarBound) return;
    GC._roleBasedSidebarBound = true;

    initSidebarSectionAccordion();

    if (GC.lastState && GC.lastState.ok !== false) {
      GC.syncRoleBasedSidebar(GC.lastState);
    }
  }

  function initSidebarSectionAccordion() {
    if (GC._sidebarSectionAccordionBound) return;
    GC._sidebarSectionAccordionBound = true;

    const sidebar = document.getElementById("gc-sidebar-nav");
    if (!sidebar) return;

    sidebar.addEventListener("click", (e) => {
      const groupToggle = e.target.closest(".gc-nav-group-toggle");
      if (groupToggle && sidebar.contains(groupToggle)) {
        e.preventDefault();
        const group = groupToggle.closest("[data-nav-group-key]");
        if (!group || group.hidden) return;
        setNavGroupExpanded(group, !group.classList.contains("is-expanded"), true);
        return;
      }

      const toggle = e.target.closest(".gc-nav-section-toggle");
      if (!toggle || !sidebar.contains(toggle)) return;
      e.preventDefault();
      const section = toggle.closest("[data-nav-section]");
      if (!section || section.hidden) return;
      setNavSectionExpanded(section, !section.classList.contains("is-expanded"), true);
    });

    syncNavSectionAccordionState(sidebar);
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
          is_homeworld: ap.is_homeworld,
          empire_role_key: ap.empire_role_key,
          empire_role_label_key: ap.empire_role_label_key,
          empire_role_icon: ap.empire_role_icon,
          empire_subtitle_key: ap.empire_subtitle_key,
          identity_title_key: ap.identity_title_key,
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
        const roleEl = root.querySelector("[data-planet-switcher-role]");
        if (roleEl) {
          const identityKey = btn.dataset.planetIdentityKey || "";
          const roleText = identityKey ? t(identityKey, identityKey) : "";
          roleEl.textContent = roleText;
          roleEl.hidden = !roleText;
        }
        const iconEl = root.querySelector("[data-planet-switcher-icon]");
        if (iconEl) {
          iconEl.textContent = btn.dataset.planetRoleIcon || "";
          iconEl.hidden = !btn.dataset.planetRoleIcon;
        }
        const coordEl = root.querySelector("[data-planet-switcher-coord]");
        if (coordEl) {
          const coord = btn.dataset.planetCoord || "";
          coordEl.hidden = !coord;
          coordEl.innerHTML = coord ? GC.coordLinkHtml(coord, { label: coord }) : "";
        }
      }
    });
  };

  function initLanguageSwitcher() {
    const root = document.getElementById("gc-language-switcher");
    if (!root || root.dataset.gcBound === "1") return;
    root.dataset.gcBound = "1";

    const apiUrl = root.dataset.api || "/api/locale";
    let busy = false;

    root.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-locale]");
      if (!btn || busy) return;
      const loc = String(btn.dataset.locale || "").trim().toLowerCase();
      if (!loc || loc === root.dataset.locale) return;

      busy = true;
      root.classList.add("is-busy");
      root.querySelectorAll(".gc-lang-btn").forEach((b) => {
        b.disabled = true;
      });
      try {
        const res = await fetch(apiUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ locale: loc }),
          credentials: "same-origin",
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || data.ok !== true) {
          console.warn("[GC] locale switch rejected", data && data.error);
          return;
        }
        // Locale affects header, sidebar, nav and GC_LOCALE — PJAX main-content swap is not enough.
        if (typeof GC.reloadCurrentPage === "function") {
          await GC.reloadCurrentPage({ force: true, fullDocument: true });
        } else {
          window.location.reload();
        }
        return;
      } catch (err) {
        console.error("[GC] locale switch failed", err);
      } finally {
        busy = false;
        root.classList.remove("is-busy");
        root.querySelectorAll(".gc-lang-btn").forEach((b) => {
          b.disabled = false;
        });
      }
    });
  }

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

  function bindGalaxyCommandMapSwitchOnce() {
    if (GC._galaxyCommandMapSwitchBound) return;
    GC._galaxyCommandMapSwitchBound = true;

    document.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-empire-identity-switch]");
      if (!btn) return;
      const root = document.getElementById("galaxy-page-root");
      if (!root || !root.contains(btn)) return;
      const graph = document.getElementById("galaxy-command-map-graph");
      if (graph?.dataset.wasDragging === "1") {
        graph.dataset.wasDragging = "0";
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      if (btn.classList.contains("is-active")) {
        e.preventDefault();
        if (typeof GC.showCommandMapColonyPanel === "function") {
          GC.showCommandMapColonyPanel(btn);
        }
        return;
      }

      const planetId = parseInt(btn.dataset.empireIdentitySwitch || btn.dataset.planetId || "0", 10);
      if (!planetId) return;

      e.preventDefault();
      btn.disabled = true;
      root.classList.add("is-busy");

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
          root.querySelectorAll("[data-empire-identity-switch]").forEach((item) => {
            const pid = parseInt(item.dataset.empireIdentitySwitch || item.dataset.planetId || "0", 10);
            const on = pid === planetId;
            item.classList.toggle("is-active", on);
            item.setAttribute("aria-pressed", on ? "true" : "false");
          });
          if (typeof GC.showCommandMapColonyPanel === "function") {
            GC.showCommandMapColonyPanel(btn);
          }
        }
      } finally {
        btn.disabled = false;
        root.classList.remove("is-busy");
      }
    });
  }

  const COMMAND_MAP_VIEWPORT_STORAGE_KEY = "gc_command_map_viewport_v6";
  const COMMAND_MAP_SCALE_MIN = 0.35;
  const COMMAND_MAP_SCALE_MAX = 2.2;
  const COMMAND_MAP_DEFAULT_SCALE = 0.62;
  const COMMAND_MAP_DRAG_THRESHOLD_PX = 4;
  const COMMAND_MAP_CLICK_SUPPRESS_MS = 220;

  function clampCommandMapScale(value) {
    return Math.min(COMMAND_MAP_SCALE_MAX, Math.max(COMMAND_MAP_SCALE_MIN, value));
  }

  function isCommandMapInteractiveTarget(target) {
    if (!(target instanceof Element)) return false;
    return !!target.closest(
      "button, a, input, select, textarea, [data-map-node], .galaxy-command-map-node, [data-command-map-reset], .galaxy-command-map-controls, [data-fleet-route]"
    );
  }

  function isCommandMapPanSurface(target) {
    if (!(target instanceof Element)) return false;
    if (isCommandMapInteractiveTarget(target)) return false;
    return !!target.closest(
      "[data-command-map-viewport], [data-command-map-canvas], [data-command-map-bg], .galaxy-command-map-bg, [data-command-map-ambient-glow], .galaxy-command-map-ambient-glow, [data-command-map-sector-layer], .galaxy-command-map-svg-layer, .galaxy-command-map-edges, .galaxy-command-map-fleet-routes, .galaxy-command-map-influence, .galaxy-command-map-nodes"
    );
  }

  function syncCommandMapBackgroundExtent(canvas) {
    if (!canvas) return;
    const worldWidth = parseFloat(canvas.dataset.worldWidth || "4000") || 4000;
    const worldHeight = parseFloat(canvas.dataset.worldHeight || "4000") || 4000;
    const canvasW = parseFloat(canvas.style.width) || worldWidth;
    const canvasH = parseFloat(canvas.style.height) || worldHeight;
    const mapBg = canvas.querySelector("[data-command-map-bg]");
    const mapAmbient = canvas.querySelector("[data-command-map-ambient-glow]");
    const bgPad = 8000;
    const glowPad = 6000;
    if (mapBg) {
      mapBg.style.left = `${-bgPad}px`;
      mapBg.style.top = `${-bgPad}px`;
      mapBg.style.width = `${canvasW + bgPad * 2}px`;
      mapBg.style.height = `${canvasH + bgPad * 2}px`;
    }
    if (mapAmbient) {
      mapAmbient.style.left = `${-glowPad}px`;
      mapAmbient.style.top = `${-glowPad}px`;
      mapAmbient.style.width = `${canvasW + glowPad * 2}px`;
      mapAmbient.style.height = `${canvasH + glowPad * 2}px`;
    }
  }

  function initCommandMapSectorLoader(opts) {
    const { canvas, getState, viewportSizeFn } = opts || {};
    const layer = canvas?.querySelector("[data-command-map-sector-layer]");
    const root = layer?.querySelector("[data-command-map-sector-root]");
    if (!layer || !root) return null;

    const seed = parseInt(layer.dataset.sectorSeed || "1", 10) || 1;
    const sectorPad = parseFloat(layer.dataset.sectorPad || "2000") || 2000;
    const sectorSize = parseFloat(layer.dataset.sectorSize || "2000") || 2000;
    const worldWidth = parseFloat(canvas.dataset.worldWidth || "4000") || 4000;
    const worldHeight = parseFloat(canvas.dataset.worldHeight || "4000") || 4000;
    const prunePad = sectorPad * 3;
    const loaded = new Map();
    let loadTimer = null;
    let loadAbort = null;
    let loadGen = 0;

    function sectorLabel(chunk) {
      const key = chunk?.label_key || "";
      if (key) return t(key, chunk?.type || "");
      return chunk?.type || "";
    }

    function visibleBounds() {
      const state = getState();
      const { width, height } = viewportSizeFn();
      const z = Math.max(state.zoom, 0.001);
      return {
        minWx: (0 - state.x) / z - sectorPad,
        minWy: (0 - state.y) / z - sectorPad,
        maxWx: (width - state.x) / z + sectorPad,
        maxWy: (height - state.y) / z + sectorPad,
      };
    }

    function syncSectorLayerLayout(bounds) {
      let minX = Math.min(0, bounds.minWx - sectorPad);
      let minY = Math.min(0, bounds.minWy - sectorPad);
      let maxX = worldWidth;
      let maxY = worldHeight;
      const half = sectorSize * 0.55;
      loaded.forEach((el) => {
        const cx = parseFloat(el.dataset.centerX || "0");
        const cy = parseFloat(el.dataset.centerY || "0");
        if (!Number.isFinite(cx) || !Number.isFinite(cy)) return;
        minX = Math.min(minX, cx - half);
        minY = Math.min(minY, cy - half);
        maxX = Math.max(maxX, cx + half);
        maxY = Math.max(maxY, cy + half);
      });
      const width = Math.max(Math.ceil(maxX - minX), 1);
      const height = Math.max(Math.ceil(maxY - minY), 1);
      layer.style.left = `${minX}px`;
      layer.style.top = `${minY}px`;
      layer.style.width = `${width}px`;
      layer.style.height = `${height}px`;
      layer.setAttribute("viewBox", `${minX} ${minY} ${width} ${height}`);
      const canvasW = Math.max(Math.ceil(maxX), worldWidth) - Math.min(0, Math.floor(minX));
      const canvasH = Math.max(Math.ceil(maxY), worldHeight) - Math.min(0, Math.floor(minY));
      canvas.style.width = `${Math.max(canvasW, 1)}px`;
      canvas.style.height = `${Math.max(canvasH, 1)}px`;
      syncCommandMapBackgroundExtent(canvas);
    }

    function appendChunk(chunk) {
      const id = String(chunk?.id || "");
      if (!id || loaded.has(id)) return;
      const ns = "http://www.w3.org/2000/svg";
      const g = document.createElementNS(ns, "g");
      g.setAttribute("class", `galaxy-command-map-sector galaxy-command-map-sector--${chunk.tone || "rim"}`);
      g.setAttribute("data-sector-id", id);
      g.setAttribute("data-sector-type", chunk.type || "");
      g.dataset.centerX = String(chunk.center_x ?? "");
      g.dataset.centerY = String(chunk.center_y ?? "");
      const path = document.createElementNS(ns, "path");
      path.setAttribute("class", "galaxy-command-map-sector-fill");
      path.setAttribute("d", chunk.path || "");
      const text = document.createElementNS(ns, "text");
      text.setAttribute("class", "galaxy-command-map-sector-label");
      text.setAttribute("x", String(chunk.center_x ?? 0));
      text.setAttribute("y", String(chunk.center_y ?? 0));
      text.setAttribute("text-anchor", "middle");
      text.textContent = sectorLabel(chunk);
      g.appendChild(path);
      g.appendChild(text);
      root.appendChild(g);
      loaded.set(id, g);
    }

    function pruneDistant(bounds) {
      loaded.forEach((el, id) => {
        const cx = parseFloat(el.dataset.centerX || "0");
        const cy = parseFloat(el.dataset.centerY || "0");
        if (
          cx < bounds.minWx - prunePad ||
          cx > bounds.maxWx + prunePad ||
          cy < bounds.minWy - prunePad ||
          cy > bounds.maxWy + prunePad
        ) {
          el.remove();
          loaded.delete(id);
        }
      });
    }

    async function loadNow() {
      const bounds = visibleBounds();
      const gen = ++loadGen;
      if (loadAbort) {
        try {
          loadAbort.abort();
        } catch (_) {}
      }
      loadAbort = new AbortController();
      const params = new URLSearchParams({
        min_wx: String(bounds.minWx),
        min_wy: String(bounds.minWy),
        max_wx: String(bounds.maxWx),
        max_wy: String(bounds.maxWy),
        seed: String(seed),
      });
      try {
        const res = await GC.fetchJSON(`/api/command-map/sectors?${params.toString()}`, {
          cache: "no-store",
          signal: loadAbort.signal,
        });
        if (gen !== loadGen || !res?.ok) return;
        (res.sector_chunks || []).forEach(appendChunk);
        pruneDistant(bounds);
        syncSectorLayerLayout(bounds);
      } catch (err) {
        if (err && err.name === "AbortError") return;
      }
    }

    function scheduleLoad() {
      if (loadTimer) clearTimeout(loadTimer);
      loadTimer = setTimeout(() => {
        loadTimer = null;
        loadNow();
      }, 120);
    }

    function destroy() {
      if (loadTimer) clearTimeout(loadTimer);
      if (loadAbort) {
        try {
          loadAbort.abort();
        } catch (_) {}
      }
      loaded.clear();
      root.replaceChildren();
      layer.style.left = "0";
      layer.style.top = "0";
      layer.style.width = `${worldWidth}px`;
      layer.style.height = `${worldHeight}px`;
      layer.setAttribute("viewBox", `0 0 ${worldWidth} ${worldHeight}`);
    }

    return { scheduleLoad, loadNow, destroy };
  }

  function initCommandMapViewport() {
    const graph = document.querySelector("[data-command-map-graph]");
    if (!graph) return;

    const viewport = graph.querySelector("[data-command-map-viewport]");
    const canvas = graph.querySelector("[data-command-map-canvas]");
    const resetBtn = graph.querySelector("[data-command-map-reset]");
    if (!viewport || !canvas) return;

    const worldWidth = parseFloat(canvas.dataset.worldWidth || "4000") || 4000;
    const worldHeight = parseFloat(canvas.dataset.worldHeight || "4000") || 4000;
    const hubWorldX = parseFloat(canvas.dataset.hubWorldX || String(worldWidth / 2));
    const hubWorldY = parseFloat(canvas.dataset.hubWorldY || String(worldHeight / 2));
    if (!Number.isFinite(hubWorldX) || !Number.isFinite(hubWorldY)) {
      console.warn("[command-map] invalid hub world coords — viewport init aborted");
      if (resetBtn) resetBtn.disabled = true;
      return;
    }
    const defaultScale = clampCommandMapScale(
      parseFloat(canvas.dataset.defaultScale || String(COMMAND_MAP_DEFAULT_SCALE)) || COMMAND_MAP_DEFAULT_SCALE
    );

    canvas.style.width = `${worldWidth}px`;
    canvas.style.height = `${worldHeight}px`;

    const state = {
      zoom: defaultScale,
      x: 0,
      y: 0,
    };

    let dragging = false;
    let dragMoved = false;
    let startX = 0;
    let startY = 0;
    let startPanX = 0;
    let startPanY = 0;
    let pinchStartDist = 0;
    let pinchStartScale = defaultScale;
    let pinchMidX = 0;
    let pinchMidY = 0;
    let saveTimer = null;
    let suppressClickUntil = 0;

    const sectorLoader = initCommandMapSectorLoader({
      canvas,
      getState: () => state,
      viewportSizeFn: viewportSize,
    });
    syncCommandMapBackgroundExtent(canvas);

    function applyTransform() {
      canvas.style.transformOrigin = "0 0";
      canvas.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.zoom})`;
      if (sectorLoader) sectorLoader.scheduleLoad();
    }

    function viewportSize() {
      const rect = viewport.getBoundingClientRect();
      return { width: rect.width || 1, height: rect.height || 1 };
    }

    function clearViewportStorage() {
      try {
        sessionStorage.removeItem(COMMAND_MAP_VIEWPORT_STORAGE_KEY);
      } catch (_) {}
    }

    function persistViewport() {
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        saveTimer = null;
        try {
          sessionStorage.setItem(
            COMMAND_MAP_VIEWPORT_STORAGE_KEY,
            JSON.stringify({ scale: state.zoom, panX: state.x, panY: state.y })
          );
        } catch (_) {}
      }, 120);
    }

    function isViewportStateValid() {
      if (!Number.isFinite(state.zoom) || !Number.isFinite(state.x) || !Number.isFinite(state.y)) {
        return false;
      }
      const { width, height } = viewportSize();
      const hubScreenX = state.x + hubWorldX * state.zoom;
      const hubScreenY = state.y + hubWorldY * state.zoom;
      const margin = Math.max(width, height) * 0.75;
      if (hubScreenX < -margin || hubScreenX > width + margin) return false;
      if (hubScreenY < -margin || hubScreenY > height + margin) return false;
      return true;
    }

    function loadViewport() {
      try {
        const raw = sessionStorage.getItem(COMMAND_MAP_VIEWPORT_STORAGE_KEY);
        if (!raw) return false;
        const saved = JSON.parse(raw);
        const nextZoom = clampCommandMapScale(Number(saved.scale));
        const nextX = Number(saved.panX);
        const nextY = Number(saved.panY);
        if (!Number.isFinite(nextZoom) || !Number.isFinite(nextX) || !Number.isFinite(nextY)) {
          return false;
        }
        state.zoom = nextZoom;
        state.x = nextX;
        state.y = nextY;
        return isViewportStateValid();
      } catch (_) {
        return false;
      }
    }

    function centerOnHub(targetScale) {
      const { width, height } = viewportSize();
      state.zoom = clampCommandMapScale(
        typeof targetScale === "number" ? targetScale : defaultScale
      );
      state.x = width / 2 - hubWorldX * state.zoom;
      state.y = height / 2 - hubWorldY * state.zoom;
      applyTransform();
      persistViewport();
    }

    function suppressClickAfterDrag(e) {
      if (graph.dataset.wasDragging !== "1" && Date.now() >= suppressClickUntil) return;
      e.preventDefault();
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === "function") {
        e.stopImmediatePropagation();
      }
      graph.dataset.wasDragging = "0";
      suppressClickUntil = 0;
    }

    function zoomAt(clientX, clientY, factor) {
      const rect = viewport.getBoundingClientRect();
      const mouseX = clientX - rect.left;
      const mouseY = clientY - rect.top;
      const beforeX = (mouseX - state.x) / state.zoom;
      const beforeY = (mouseY - state.y) / state.zoom;
      const nextZoom = clampCommandMapScale(state.zoom * factor);
      if (nextZoom === state.zoom) return;
      state.x = mouseX - beforeX * nextZoom;
      state.y = mouseY - beforeY * nextZoom;
      state.zoom = nextZoom;
      applyTransform();
      persistViewport();
    }

    function touchDistance(touches) {
      const dx = touches[0].clientX - touches[1].clientX;
      const dy = touches[0].clientY - touches[1].clientY;
      return Math.hypot(dx, dy);
    }

    function touchMidpoint(touches, rect) {
      return {
        x: (touches[0].clientX + touches[1].clientX) / 2 - rect.left,
        y: (touches[0].clientY + touches[1].clientY) / 2 - rect.top,
      };
    }

    function onPointerDown(e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      if (!isCommandMapPanSurface(e.target)) return;
      dragging = true;
      dragMoved = false;
      startX = e.clientX;
      startY = e.clientY;
      startPanX = state.x;
      startPanY = state.y;
      viewport.classList.add("is-dragging");
      if (typeof viewport.setPointerCapture === "function") {
        viewport.setPointerCapture(e.pointerId);
      }
    }

    function onPointerMove(e) {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (Math.abs(dx) + Math.abs(dy) > COMMAND_MAP_DRAG_THRESHOLD_PX) dragMoved = true;
      state.x = startPanX + dx;
      state.y = startPanY + dy;
      applyTransform();
    }

    function onPointerUp(e) {
      if (!dragging) return;
      dragging = false;
      viewport.classList.remove("is-dragging");
      if (typeof viewport.releasePointerCapture === "function") {
        try {
          viewport.releasePointerCapture(e.pointerId);
        } catch (_) {}
      }
      if (dragMoved) {
        graph.dataset.wasDragging = "1";
        suppressClickUntil = Date.now() + COMMAND_MAP_CLICK_SUPPRESS_MS;
        persistViewport();
      }
    }

    function onWheel(e) {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 0.9;
      zoomAt(e.clientX, e.clientY, factor);
    }

    function onTouchStart(e) {
      if (e.touches.length === 2) {
        pinchStartDist = touchDistance(e.touches);
        pinchStartScale = state.zoom;
        const rect = viewport.getBoundingClientRect();
        const mid = touchMidpoint(e.touches, rect);
        pinchMidX = mid.x;
        pinchMidY = mid.y;
      }
    }

    function onTouchMove(e) {
      if (e.touches.length !== 2 || pinchStartDist <= 0) return;
      e.preventDefault();
      const dist = touchDistance(e.touches);
      const factor = dist / pinchStartDist;
      const nextZoom = clampCommandMapScale(pinchStartScale * factor);
      const beforeX = (pinchMidX - state.x) / state.zoom;
      const beforeY = (pinchMidY - state.y) / state.zoom;
      state.x = pinchMidX - beforeX * nextZoom;
      state.y = pinchMidY - beforeY * nextZoom;
      state.zoom = nextZoom;
      applyTransform();
    }

    function onTouchEnd() {
      if (pinchStartDist > 0) {
        pinchStartDist = 0;
        persistViewport();
      }
    }

    function onResetClick(e) {
      e.preventDefault();
      e.stopPropagation();
      centerOnHub(defaultScale);
    }

    function initViewportPosition() {
      if (loadViewport()) {
        applyTransform();
      } else {
        clearViewportStorage();
        centerOnHub(defaultScale);
      }
    }

    initViewportPosition();
    requestAnimationFrame(() => {
      if (!isViewportStateValid()) {
        clearViewportStorage();
        centerOnHub(defaultScale);
      }
      if (sectorLoader) sectorLoader.loadNow();
    });

    let focusAnimFrame = null;

    function prefersReducedMotion() {
      try {
        return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      } catch (_) {
        return false;
      }
    }

    function focusOnWorld(worldX, worldY, opts) {
      const options = opts && typeof opts === "object" ? opts : {};
      const wx = parseFloat(worldX);
      const wy = parseFloat(worldY);
      if (!Number.isFinite(wx) || !Number.isFinite(wy)) return;
      const { width, height } = viewportSize();
      const isMobile = width < 768;
      const zoomBoost = isMobile ? 1.08 : 1.15;
      const maxScale = isMobile ? 0.85 : 1.05;
      const requestedScale = typeof options.scale === "number" ? options.scale : state.zoom * zoomBoost;
      const targetScale = clampCommandMapScale(Math.min(requestedScale, maxScale));
      const targetX = width / 2 - wx * targetScale;
      const targetY = height / 2 - wy * targetScale;
      if (focusAnimFrame) {
        cancelAnimationFrame(focusAnimFrame);
        focusAnimFrame = null;
      }
      if (options.animate === false || prefersReducedMotion()) {
        state.zoom = targetScale;
        state.x = targetX;
        state.y = targetY;
        applyTransform();
        persistViewport();
        return;
      }
      const start = { zoom: state.zoom, x: state.x, y: state.y };
      const startTime = performance.now();
      const duration = 650;
      const tick = (now) => {
        const t = Math.min(1, (now - startTime) / duration);
        const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        state.zoom = start.zoom + (targetScale - start.zoom) * ease;
        state.x = start.x + (targetX - start.x) * ease;
        state.y = start.y + (targetY - start.y) * ease;
        applyTransform();
        if (t < 1) {
          focusAnimFrame = requestAnimationFrame(tick);
        } else {
          focusAnimFrame = null;
          persistViewport();
        }
      };
      focusAnimFrame = requestAnimationFrame(tick);
    }

    GC.focusCommandMapWorld = focusOnWorld;

    graph.addEventListener("click", suppressClickAfterDrag, true);

    viewport.addEventListener("pointerdown", onPointerDown);
    viewport.addEventListener("pointermove", onPointerMove);
    viewport.addEventListener("pointerup", onPointerUp);
    viewport.addEventListener("pointercancel", onPointerUp);
    viewport.addEventListener("wheel", onWheel, { passive: false });
    viewport.addEventListener("touchstart", onTouchStart, { passive: true });
    viewport.addEventListener("touchmove", onTouchMove, { passive: false });
    viewport.addEventListener("touchend", onTouchEnd);
    viewport.addEventListener("touchcancel", onTouchEnd);
    resetBtn?.addEventListener("click", onResetClick);

    GC.registerCleanup(() => {
      if (saveTimer) clearTimeout(saveTimer);
      if (focusAnimFrame) cancelAnimationFrame(focusAnimFrame);
      delete GC.focusCommandMapWorld;
      if (sectorLoader) sectorLoader.destroy();
      viewport.removeEventListener("pointerdown", onPointerDown);
      viewport.removeEventListener("pointermove", onPointerMove);
      viewport.removeEventListener("pointerup", onPointerUp);
      viewport.removeEventListener("pointercancel", onPointerUp);
      viewport.removeEventListener("wheel", onWheel);
      viewport.removeEventListener("touchstart", onTouchStart);
      viewport.removeEventListener("touchmove", onTouchMove);
      viewport.removeEventListener("touchend", onTouchEnd);
      viewport.removeEventListener("touchcancel", onTouchEnd);
      resetBtn?.removeEventListener("click", onResetClick);
      graph.removeEventListener("click", suppressClickAfterDrag, true);
    });
  }

  function setCommandMapSidePanelState(panel, emptyPanel, detailPanel, mode) {
    if (!panel) return;
    const showDetail = mode === "detail";
    const showEmpty = mode === "empty";
    panel.hidden = !(showDetail || showEmpty);
    if (emptyPanel) emptyPanel.hidden = !showEmpty;
    if (detailPanel) detailPanel.hidden = !showDetail;
    panel.classList.toggle("is-active", showDetail);
  }

  function resetCommandMapSidePanels(graph) {
    const siteInspector = document.querySelector("[data-command-map-site-inspector]");
    if (!siteInspector || siteInspector.hidden || siteInspector.closest("[hidden]")) return;
    setCommandMapSidePanelState(
      siteInspector,
      siteInspector.querySelector("[data-command-map-empty-panel]"),
      siteInspector.querySelector("[data-command-map-detail-panel]"),
      "empty"
    );
  }

  function initCommandMapSiteInspector() {
    const graph = document.querySelector("[data-command-map-graph]");
    const inspector = document.querySelector("[data-command-map-site-inspector]");
    if (!graph || !inspector || inspector.hidden) return;

    const emptyState = inspector.querySelector("[data-command-map-empty-panel]");
    const body = inspector.querySelector("[data-command-map-detail-panel]");
    const iconEl = inspector.querySelector("[data-command-map-site-inspector-icon]");
    const typeEl = inspector.querySelector("[data-command-map-site-inspector-type]");
    const nameEl = inspector.querySelector("[data-command-map-site-inspector-name]");
    const statusEl = inspector.querySelector("[data-command-map-site-inspector-status]");
    const regionEl = inspector.querySelector("[data-command-map-site-inspector-region]");
    const levelEl = inspector.querySelector("[data-command-map-site-inspector-level]");
    const riskEl = inspector.querySelector("[data-command-map-site-inspector-risk]");
    const promiseEl = inspector.querySelector("[data-command-map-site-inspector-promise]");
    const rewardEl = inspector.querySelector("[data-command-map-site-inspector-reward]");
    const futureEl = inspector.querySelector("[data-command-map-site-inspector-future]");
    const expansionMeta = inspector.querySelector("[data-command-map-inspector-expansion-meta]");
    const landmarkMeta = inspector.querySelector("[data-command-map-inspector-landmark-meta]");
    const landmarkRegionEl = inspector.querySelector("[data-command-map-inspector-landmark-region]");
    const landmarkFlavorEl = inspector.querySelector("[data-command-map-inspector-landmark-flavor]");
    const expansionSections = inspector.querySelectorAll("[data-command-map-inspector-expansion-section]");
    const landmarkSection = inspector.querySelector("[data-command-map-inspector-landmark-section]");
    const foreignSection = inspector.querySelector("[data-command-map-inspector-foreign-section]");
    const foreignPlayerEl = inspector.querySelector("[data-command-map-inspector-foreign-player]");
    const foreignCoordsEl = inspector.querySelector("[data-command-map-inspector-foreign-coords]");
    const foreignColoniesEl = inspector.querySelector("[data-command-map-inspector-foreign-colonies]");
    const foreignWorldSection = inspector.querySelector("[data-command-map-inspector-foreign-world-section]");
    const foreignWorldOwnerEl = inspector.querySelector("[data-command-map-inspector-foreign-world-owner]");
    const foreignWorldRoleEl = inspector.querySelector("[data-command-map-inspector-foreign-world-role]");
    const expeditionActivitySection = inspector.querySelector("[data-command-map-inspector-expedition-activity]");
    const expeditionStatusEl = inspector.querySelector("[data-command-map-inspector-expedition-status]");
    const expeditionEtaEl = inspector.querySelector("[data-command-map-inspector-expedition-eta]");
    const expeditionReportEl = inspector.querySelector("[data-command-map-inspector-expedition-report]");
    const worldFieldSection = inspector.querySelector("[data-command-map-inspector-world-field-section]");
    const strategicOwnerEl = inspector.querySelector("[data-command-map-inspector-strategic-owner]");
    const strategicRiskEl = inspector.querySelector("[data-command-map-inspector-strategic-risk]");
    const strategicPromiseEl = inspector.querySelector("[data-command-map-inspector-strategic-promise]");
    const strategicRewardEl = inspector.querySelector("[data-command-map-inspector-strategic-reward]");
    const strategicFutureEl = inspector.querySelector("[data-command-map-inspector-strategic-future]");
    const colonizeActions = inspector.querySelector("[data-command-map-inspector-colonize-actions]");
    const colonizeBtn = inspector.querySelector("[data-command-map-colonize-world]");
    const colonizeBlocked = inspector.querySelector("[data-command-map-inspector-colonize-blocked]");
    const colonizeLimit = inspector.querySelector("[data-command-map-inspector-colony-limit]");
    const expeditionActions = inspector.querySelector("[data-command-map-inspector-expedition-actions]");
    const expeditionBtn = inspector.querySelector("[data-command-map-expedition-world]");
    const salvageActions = inspector.querySelector("[data-command-map-inspector-salvage-actions]");
    const salvageBtn = inspector.querySelector("[data-command-map-salvage-world]");
    const salvagePrepare = inspector.querySelector("[data-command-map-inspector-salvage-prepare]");
    const salvageBlocked = inspector.querySelector("[data-command-map-inspector-salvage-blocked]");
    const worldProgressSection = inspector.querySelector("[data-command-map-inspector-world-progress]");
    const familiarityStatusEl = inspector.querySelector("[data-command-map-inspector-familiarity-status]");
    const familiarityProgressEl = inspector.querySelector("[data-command-map-inspector-familiarity-progress]");
    const outpostPreparedHint = inspector.querySelector("[data-command-map-inspector-outpost-prepared]");
    const strategicClaimedHint = inspector.querySelector("[data-command-map-inspector-strategic-claimed]");
    const strategicNoncolonizableHint = inspector.querySelector("[data-command-map-inspector-strategic-noncolonizable]");
    const siteButtons = graph.querySelectorAll("[data-expansion-site-inspect]");
    const landmarkButtons = graph.querySelectorAll("[data-landmark-inspect]");
    const foreignButtons = graph.querySelectorAll("[data-foreign-empire-inspect]");
    const foreignWorldColonyButtons = graph.querySelectorAll("[data-foreign-world-colony-inspect]");
    const worldFieldButtons = graph.querySelectorAll("[data-world-field-inspect]");
    if (!body || (!siteButtons.length && !landmarkButtons.length && !foreignButtons.length && !foreignWorldColonyButtons.length && !worldFieldButtons.length)) return;

    let activeBtn = null;
    let selectedWorldKey = "";
    let selectedWorldName = "";

    function formatInspectorHint(key, vars = {}) {
      return tf(key, vars, key);
    }

    function readPlanetLimitBlock() {
      const block = GC.lastState?.planet_limit || {};
      let current = Number(block.current);
      let max = Number(block.max);
      if (!Number.isFinite(current)) current = 0;
      if (!Number.isFinite(max) || max < 1) max = 9;
      return { current: Math.floor(current), max: Math.floor(max) };
    }

    function clearSelection() {
      if (activeBtn) {
        activeBtn.classList.remove("is-selected");
        activeBtn.setAttribute("aria-pressed", "false");
        activeBtn = null;
      }
    }

    function hideInspectorModes() {
      if (foreignSection) foreignSection.hidden = true;
      if (foreignWorldSection) foreignWorldSection.hidden = true;
      if (expeditionActivitySection) expeditionActivitySection.hidden = true;
      if (worldFieldSection) worldFieldSection.hidden = true;
      if (worldProgressSection) worldProgressSection.hidden = true;
    }

    function updateWorldProgressInspector(ds) {
      const isExpedition = ds?.strategicExpedition === "1";
      if (worldProgressSection) worldProgressSection.hidden = !isExpedition;
      if (!isExpedition) return;
      const famKey = String(ds.familiarityLabelKey || "world_familiarity_unknown");
      if (familiarityStatusEl) familiarityStatusEl.textContent = tf(famKey, {}, famKey);
      const count = parseInt(ds.expeditionCount || "0", 10) || 0;
      const nextMilestone = parseInt(ds.nextMilestone || "0", 10) || 0;
      const isOutpost = String(ds.familiarityStatus || "") === "outpost_prepared";
      if (outpostPreparedHint) outpostPreparedHint.hidden = !isOutpost;
      if (familiarityProgressEl) {
        if (isOutpost || nextMilestone <= 0) {
          familiarityProgressEl.hidden = true;
          familiarityProgressEl.textContent = "";
        } else {
          familiarityProgressEl.hidden = false;
          familiarityProgressEl.textContent = formatInspectorHint("world_progress_inspector_next", {
            current: count,
            target: nextMilestone,
            milestone: nextMilestone,
          });
        }
      }
    }

    function setExpansionMode(visible) {
      if (expansionMeta) expansionMeta.hidden = !visible;
      expansionSections.forEach((section) => {
        section.hidden = !visible;
      });
      if (landmarkMeta) landmarkMeta.hidden = visible;
      if (landmarkSection) landmarkSection.hidden = visible;
      hideInspectorModes();
    }

    function setForeignMode(visible) {
      if (expansionMeta) expansionMeta.hidden = true;
      expansionSections.forEach((section) => {
        section.hidden = true;
      });
      if (landmarkMeta) landmarkMeta.hidden = true;
      if (landmarkSection) landmarkSection.hidden = true;
      hideInspectorModes();
      if (foreignSection) foreignSection.hidden = !visible;
    }

    function setForeignWorldColonyMode(visible) {
      if (expansionMeta) expansionMeta.hidden = true;
      expansionSections.forEach((section) => {
        section.hidden = true;
      });
      if (landmarkMeta) landmarkMeta.hidden = true;
      if (landmarkSection) landmarkSection.hidden = true;
      hideInspectorModes();
      if (foreignWorldSection) foreignWorldSection.hidden = !visible;
    }

    function setWorldFieldMode(visible) {
      if (expansionMeta) expansionMeta.hidden = true;
      expansionSections.forEach((section) => {
        section.hidden = true;
      });
      if (landmarkMeta) landmarkMeta.hidden = true;
      if (landmarkSection) landmarkSection.hidden = true;
      hideInspectorModes();
      if (worldFieldSection) worldFieldSection.hidden = !visible;
    }

    function formatExpeditionEta(etaAt) {
      const ts = parseTimerTarget(etaAt);
      if (!ts) return "";
      const rem = movementRemainingSeconds(ts, getTimerServerNow());
      if (typeof GC.formatCountdownRemain === "function") {
        return GC.formatCountdownRemain(rem);
      }
      return String(Math.max(0, Math.floor(rem)));
    }

    function updateExpeditionActivityInspector(ds) {
      const status = String(ds.expeditionStatus || "idle");
      const showActivity = status !== "idle";
      if (expeditionActivitySection) expeditionActivitySection.hidden = !showActivity;
      if (!showActivity) {
        if (expeditionEtaEl) expeditionEtaEl.hidden = true;
        if (expeditionReportEl) expeditionReportEl.hidden = true;
        return;
      }
      let statusText = GC.t?.("world_expedition_status_idle", "No active expedition") || "No active expedition";
      const isSalvage = ds.strategicSalvage === "1";
      if (status === "expedition_active") {
        statusText = isSalvage
          ? (GC.t?.("world_salvage_status_active", "Salvage in progress") || "Salvage in progress")
          : (GC.t?.("world_expedition_status_active", "Expedition in progress") || "Expedition in progress");
      } else if (status === "expedition_returning") {
        statusText = isSalvage
          ? (GC.t?.("world_salvage_status_returning", "Fleet returning with salvage") || "Fleet returning with salvage")
          : (GC.t?.("world_expedition_status_returning", "Fleet returning") || "Fleet returning");
      } else if (status === "recently_reported") {
        const eventKey = ds.expeditionEventLabelKey || "";
        const eventLabel = eventKey ? (GC.t?.(eventKey, eventKey) || eventKey) : "";
        statusText = isSalvage
          ? (GC.t?.("world_salvage_status_report", "Latest salvage report") || "Latest salvage report")
          : (GC.t?.("world_expedition_status_report", "Latest expedition report") || "Latest expedition report");
        if (expeditionReportEl) {
          expeditionReportEl.hidden = false;
          expeditionReportEl.textContent = eventLabel
            ? formatInspectorHint(
                isSalvage ? "world_salvage_inspector_report_hint" : "world_expedition_inspector_report_hint",
                { event: eventLabel }
              )
            : (GC.t?.("world_expedition_inspector_report_open", "Open your inbox for the full report.") || "");
        }
      }
      if (expeditionStatusEl) expeditionStatusEl.textContent = statusText;
      const etaAt = Number(ds.expeditionEtaAt || 0);
      if (expeditionEtaEl) {
        if (status === "expedition_active" || status === "expedition_returning") {
          expeditionEtaEl.hidden = false;
          expeditionEtaEl.textContent = formatInspectorHint("world_expedition_inspector_eta", {
            eta: formatExpeditionEta(etaAt),
          });
        } else {
          expeditionEtaEl.hidden = true;
          expeditionEtaEl.textContent = "";
        }
      }
      if (status !== "recently_reported" && expeditionReportEl) {
        expeditionReportEl.hidden = true;
        expeditionReportEl.textContent = "";
      }
    }

    function hideColonyPanel() {
      /* GC-597: colony HUD stays visible; only clear map selection if needed */
      graph.querySelectorAll("[data-colony-location-inspect].is-selected").forEach((btn) => {
        btn.classList.remove("is-selected");
        btn.setAttribute("aria-pressed", "false");
      });
    }

    function showInspectorDetail() {
      setCommandMapSidePanelState(inspector, emptyState, body, "detail");
    }

    function showSite(btn) {
      if (!btn) return;
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      hideColonyPanel();
      if (activeBtn && activeBtn !== btn) {
        activeBtn.classList.remove("is-selected");
        activeBtn.setAttribute("aria-pressed", "false");
      }
      activeBtn = btn;
      btn.classList.add("is-selected");
      btn.setAttribute("aria-pressed", "true");

      const ds = btn.dataset;
      const status = ds.siteStatus || "locked";
      showInspectorDetail();
      setExpansionMode(true);

      if (iconEl) iconEl.textContent = ds.siteIcon || "🌌";
      if (typeEl) typeEl.textContent = ds.siteType || "";
      if (nameEl) nameEl.textContent = ds.siteName || "";
      if (statusEl) {
        statusEl.textContent = ds.siteStatusLabel || "";
        statusEl.className = `galaxy-command-map-site-inspector-status galaxy-command-map-site-inspector-status--${status}`;
      }
      if (regionEl) regionEl.textContent = ds.siteRegion || "";
      if (levelEl) levelEl.textContent = ds.siteLevel || "—";
      if (riskEl) {
        riskEl.textContent = ds.siteRisk || "";
        riskEl.className = `galaxy-command-map-site-inspector-risk galaxy-command-map-site-inspector-risk--${ds.siteRiskLevel || "low"}`;
      }
      if (promiseEl) promiseEl.textContent = ds.sitePromise || "";
      if (rewardEl) rewardEl.textContent = ds.siteReward || "";
      if (futureEl) futureEl.textContent = ds.siteFuture || "";
    }

    function showLandmark(btn) {
      if (!btn) return;
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      hideColonyPanel();
      if (activeBtn && activeBtn !== btn) {
        activeBtn.classList.remove("is-selected");
        activeBtn.setAttribute("aria-pressed", "false");
      }
      activeBtn = btn;
      btn.classList.add("is-selected");
      btn.setAttribute("aria-pressed", "true");

      const ds = btn.dataset;
      showInspectorDetail();
      setExpansionMode(false);

      if (iconEl) iconEl.textContent = ds.landmarkIcon || "✦";
      if (typeEl) typeEl.textContent = ds.landmarkType || "Landmark";
      if (nameEl) nameEl.textContent = ds.landmarkName || "";
      if (statusEl) {
        statusEl.textContent = ds.landmarkStatusLabel || "";
        statusEl.className = "galaxy-command-map-site-inspector-status galaxy-command-map-site-inspector-status--landmark";
      }
      if (landmarkRegionEl) landmarkRegionEl.textContent = ds.landmarkRegion || "";
      if (landmarkFlavorEl) landmarkFlavorEl.textContent = ds.landmarkFlavor || "";
    }

    function showForeignEmpire(btn) {
      if (!btn) return;
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      hideColonyPanel();
      if (activeBtn && activeBtn !== btn) {
        activeBtn.classList.remove("is-selected");
        activeBtn.setAttribute("aria-pressed", "false");
      }
      activeBtn = btn;
      btn.classList.add("is-selected");
      btn.setAttribute("aria-pressed", "true");

      const ds = btn.dataset;
      showInspectorDetail();
      setForeignMode(true);

      if (iconEl) iconEl.textContent = ds.empireIcon || "🏛";
      if (typeEl) typeEl.textContent = GC.t?.("world_map_foreign_empire", "Foreign empire") || "Foreign empire";
      if (nameEl) nameEl.textContent = ds.homeworldName || ds.empireName || ds.ownerUsername || "";
      if (statusEl) {
        statusEl.textContent = ds.empireRole || GC.t?.("empire_homeworld_subtitle", "Founder World") || "Founder World";
        statusEl.className = "galaxy-command-map-site-inspector-status galaxy-command-map-site-inspector-status--foreign";
      }
      if (foreignPlayerEl) foreignPlayerEl.textContent = ds.ownerUsername || "—";
      if (foreignCoordsEl) foreignCoordsEl.textContent = ds.empireCoords || "—";
      if (foreignColoniesEl) foreignColoniesEl.textContent = String(ds.empireColonyCount || "0");
    }

    function showForeignWorldColony(btn) {
      if (!btn) return;
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      hideColonyPanel();
      if (activeBtn && activeBtn !== btn) {
        activeBtn.classList.remove("is-selected");
        activeBtn.setAttribute("aria-pressed", "false");
      }
      activeBtn = btn;
      btn.classList.add("is-selected");
      btn.setAttribute("aria-pressed", "true");

      const ds = btn.dataset;
      showInspectorDetail();
      setForeignWorldColonyMode(true);

      if (iconEl) iconEl.textContent = ds.foreignColonyIcon || "🌍";
      if (typeEl) typeEl.textContent = ds.foreignColonyType || GC.t?.("strategic_world_inspector_kicker", "Strategic world") || "Strategic world";
      if (nameEl) nameEl.textContent = ds.foreignColonyName || "";
      if (statusEl) {
        statusEl.textContent = GC.t?.("foreign_world_colony_status_settled", "Settled") || "Settled";
        statusEl.className = "galaxy-command-map-site-inspector-status galaxy-command-map-site-inspector-status--foreign";
      }
      if (foreignWorldOwnerEl) foreignWorldOwnerEl.textContent = ds.ownerUsername || "—";
      if (foreignWorldRoleEl) foreignWorldRoleEl.textContent = ds.foreignColonyRole || "—";
    }

    function showWorldField(btn) {
      if (!btn) return;
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      hideColonyPanel();
      if (activeBtn && activeBtn !== btn) {
        activeBtn.classList.remove("is-selected");
        activeBtn.setAttribute("aria-pressed", "false");
      }
      activeBtn = btn;
      btn.classList.add("is-selected");
      btn.setAttribute("aria-pressed", "true");

      const ds = btn.dataset;
      showInspectorDetail();
      setWorldFieldMode(true);

      if (iconEl) iconEl.textContent = ds.strategicIcon || "✦";
      if (typeEl) typeEl.textContent = ds.strategicType || GC.t?.("strategic_world_inspector_kicker", "Strategic world") || "Strategic world";
      if (nameEl) nameEl.textContent = ds.strategicName || "";
      const colonizable = ds.strategicColonizable === "1";
      const claimed = ds.strategicClaimed === "1";
      const isExpedition = ds.strategicExpedition === "1";
      const isExpeditionPrepared = ds.strategicExpeditionPrepared === "1";
      const isSalvage = ds.strategicSalvage === "1";
      if (statusEl) {
        if (claimed) {
          statusEl.textContent =
            GC.t?.("strategic_world_inspector_status_settled", "Already settled") || "Already settled";
        } else if (isExpedition) {
          const famKey = ds.familiarityLabelKey || "world_familiarity_unknown";
          statusEl.textContent = tf(famKey, {}, famKey);
        } else if (isSalvage) {
          statusEl.textContent =
            GC.t?.("strategic_world_inspector_status_salvage", "Salvage target") || "Salvage target";
        } else if (isExpeditionPrepared) {
          statusEl.textContent =
            GC.t?.("strategic_world_inspector_status_prepared", "Coming soon") || "Coming soon";
        } else if (!colonizable) {
          statusEl.textContent =
            GC.t?.("strategic_world_inspector_status_not_colonizable", "Not colonizable") || "Not colonizable";
        } else {
          statusEl.textContent = GC.t?.("strategic_world_inspector_status", "Unclaimed") || "Unclaimed";
        }
        statusEl.className = "galaxy-command-map-site-inspector-status galaxy-command-map-site-inspector-status--field";
      }
      if (strategicOwnerEl) strategicOwnerEl.textContent = ds.strategicOwner || "";
      if (strategicRiskEl) {
        strategicRiskEl.textContent = ds.strategicRisk || "";
        strategicRiskEl.className = `galaxy-command-map-site-inspector-risk galaxy-command-map-site-inspector-risk--${ds.strategicRiskLevel || "low"}`;
      }
      if (strategicPromiseEl) strategicPromiseEl.textContent = ds.strategicPromise || "";
      if (strategicRewardEl) strategicRewardEl.textContent = ds.strategicReward || "";
      if (strategicFutureEl) strategicFutureEl.textContent = ds.strategicFuture || "";

      selectedWorldKey = String(ds.strategicWorldKey || "").trim();
      selectedWorldName = String(ds.strategicName || "").trim();

      const limit = readPlanetLimitBlock();
      const atLimit = limit.current >= limit.max;

      if (strategicClaimedHint) strategicClaimedHint.hidden = !claimed;
      if (strategicNoncolonizableHint) {
        strategicNoncolonizableHint.hidden = colonizable || claimed || isExpedition || isExpeditionPrepared || isSalvage;
      }
      if (salvageActions) salvageActions.hidden = !isSalvage || claimed;
      if (colonizeActions) colonizeActions.hidden = !colonizable || claimed;
      if (expeditionActions) expeditionActions.hidden = !isExpedition || claimed;
      if (expeditionBtn) expeditionBtn.hidden = !isExpedition || claimed;
      if (salvageBtn) salvageBtn.hidden = !isSalvage || claimed;
      if (salvagePrepare) salvagePrepare.hidden = true;
      if (salvageBlocked) {
        salvageBlocked.hidden = true;
        salvageBlocked.textContent = "";
      }

      if (isSalvage && !claimed && selectedWorldKey) {
        void refreshSalvageInspectorState();
      } else if (salvageBtn) {
        salvageBtn.disabled = false;
      }

      if (colonizeLimit) {
        if (colonizable && !claimed) {
          colonizeLimit.hidden = false;
          colonizeLimit.textContent = formatInspectorHint("strategic_world_colony_limit", limit);
        } else {
          colonizeLimit.hidden = true;
          colonizeLimit.textContent = "";
        }
      }

      if (colonizeBtn) {
        colonizeBtn.hidden = !colonizable || claimed;
        colonizeBtn.disabled = atLimit;
      }

      if (colonizeBlocked) {
        if (colonizable && !claimed && atLimit) {
          colonizeBlocked.hidden = false;
          colonizeBlocked.textContent =
            GC.t?.("fleet_error_colony_limit_reached", "Colony limit reached.") || "Colony limit reached.";
        } else {
          colonizeBlocked.hidden = true;
          colonizeBlocked.textContent = "";
        }
      }

      updateExpeditionActivityInspector(ds);
      updateWorldProgressInspector(ds);
    }

    async function refreshSalvageInspectorState() {
      if (!selectedWorldKey || !salvageActions || salvageActions.hidden) return;
      try {
        const res = await GC.fetchJSON(
          `/api/worlds/salvage-preview?world_key=${encodeURIComponent(selectedWorldKey)}`,
          { cache: "no-store" }
        );
        const data = res?.data || {};
        const canStart = Boolean(data.can_start_salvage);
        const hasShips = Boolean(data.has_salvage_ships);
        if (salvageBtn) {
          salvageBtn.hidden = false;
          salvageBtn.disabled = !canStart;
          salvageBtn.textContent = canStart
            ? (GC.t?.("strategic_world_btn_salvage", "Start salvage") || "Start salvage")
            : (GC.t?.("strategic_world_btn_salvage_prepare", "Prepare salvage") || "Prepare salvage");
        }
        if (salvagePrepare) {
          salvagePrepare.hidden = hasShips;
        }
        if (salvageBlocked) {
          if (data.block_reason === "no_expedition_ships" && !hasShips) {
            salvageBlocked.hidden = false;
            salvageBlocked.textContent =
              GC.t?.("strategic_world_salvage_no_ships", "Build expedition ships on your active planet first.") || "";
          } else {
            salvageBlocked.hidden = true;
            salvageBlocked.textContent = "";
          }
        }
      } catch (_) {
        if (salvageBtn) salvageBtn.disabled = true;
      }
    }

    function onSalvageWorldClick(e) {
      e.preventDefault();
      e.stopPropagation();
      if (!selectedWorldKey) return;
      const params = new URLSearchParams();
      params.set("mission", "expedition");
      params.set("world_key", selectedWorldKey);
      if (typeof GC.navigateTo === "function") {
        GC.navigateTo(`/fleet?${params.toString()}`, { push: true });
      }
    }

    function onExpeditionWorldClick(e) {
      e.preventDefault();
      e.stopPropagation();
      if (!selectedWorldKey) return;
      const params = new URLSearchParams();
      params.set("mission", "expedition");
      params.set("world_key", selectedWorldKey);
      if (typeof GC.navigateTo === "function") {
        GC.navigateTo(`/fleet?${params.toString()}`, { push: true });
      }
    }

    function onColonizeWorldClick(e) {
      e.preventDefault();
      e.stopPropagation();
      if (!selectedWorldKey) return;
      const params = new URLSearchParams();
      params.set("mission", "colonize");
      params.set("world_key", selectedWorldKey);
      if (selectedWorldName) params.set("colony_name", selectedWorldName);
      if (typeof GC.navigateTo === "function") {
        GC.navigateTo(`/fleet?${params.toString()}`, { push: true });
      }
    }

    function onSiteClick(e) {
      const btn = e.currentTarget;
      if (!(btn instanceof HTMLElement)) return;
      e.stopPropagation();
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      if (typeof GC.openWorldInspectorFromNode === "function" && GC.openWorldInspectorFromNode(btn)) {
        hideColonyPanel();
        return;
      }
      showSite(btn);
    }

    function onLandmarkClick(e) {
      const btn = e.currentTarget;
      if (!(btn instanceof HTMLElement)) return;
      e.stopPropagation();
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      if (typeof GC.openWorldInspectorFromNode === "function" && GC.openWorldInspectorFromNode(btn)) {
        hideColonyPanel();
        return;
      }
      showLandmark(btn);
    }

    function onForeignClick(e) {
      const btn = e.currentTarget;
      if (!(btn instanceof HTMLElement)) return;
      e.stopPropagation();
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      if (typeof GC.openWorldInspectorFromNode === "function" && GC.openWorldInspectorFromNode(btn)) {
        return;
      }
      if (typeof GC.showCommandMapForeignColonyPanel === "function") {
        GC.showCommandMapForeignColonyPanel(btn);
        return;
      }
      showForeignEmpire(btn);
    }

    function onForeignWorldColonyClick(e) {
      const btn = e.currentTarget;
      if (!(btn instanceof HTMLElement)) return;
      e.stopPropagation();
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      if (typeof GC.openWorldInspectorFromNode === "function" && GC.openWorldInspectorFromNode(btn)) {
        return;
      }
      if (typeof GC.showCommandMapForeignColonyPanel === "function") {
        GC.showCommandMapForeignColonyPanel(btn);
        return;
      }
      showForeignWorldColony(btn);
    }

    function onWorldFieldClick(e) {
      const btn = e.currentTarget;
      if (!(btn instanceof HTMLElement)) return;
      e.stopPropagation();
      if (graph.dataset.wasDragging === "1") {
        delete graph.dataset.wasDragging;
        return;
      }
      if (typeof GC.openWorldInspectorFromNode === "function" && GC.openWorldInspectorFromNode(btn)) {
        return;
      }
      if (typeof GC.showCommandMapStrategicWorldPanel === "function") {
        GC.showCommandMapStrategicWorldPanel(btn);
        return;
      }
      showWorldField(btn);
    }

    siteButtons.forEach((btn) => {
      btn.addEventListener("click", onSiteClick);
    });
    landmarkButtons.forEach((btn) => {
      btn.addEventListener("click", onLandmarkClick);
    });
    foreignButtons.forEach((btn) => {
      btn.addEventListener("click", onForeignClick);
    });
    foreignWorldColonyButtons.forEach((btn) => {
      btn.addEventListener("click", onForeignWorldColonyClick);
    });
    worldFieldButtons.forEach((btn) => {
      btn.addEventListener("click", onWorldFieldClick);
    });
    colonizeBtn?.addEventListener("click", onColonizeWorldClick);
    expeditionBtn?.addEventListener("click", onExpeditionWorldClick);
    salvageBtn?.addEventListener("click", onSalvageWorldClick);

    resetCommandMapSidePanels(graph);

    GC.registerCleanup(() => {
      clearSelection();
      resetCommandMapSidePanels(graph);
      siteButtons.forEach((btn) => {
        btn.removeEventListener("click", onSiteClick);
      });
      landmarkButtons.forEach((btn) => {
        btn.removeEventListener("click", onLandmarkClick);
      });
      foreignButtons.forEach((btn) => {
        btn.removeEventListener("click", onForeignClick);
      });
      foreignWorldColonyButtons.forEach((btn) => {
        btn.removeEventListener("click", onForeignWorldColonyClick);
      });
      worldFieldButtons.forEach((btn) => {
        btn.removeEventListener("click", onWorldFieldClick);
      });
      colonizeBtn?.removeEventListener("click", onColonizeWorldClick);
      expeditionBtn?.removeEventListener("click", onExpeditionWorldClick);
      salvageBtn?.removeEventListener("click", onSalvageWorldClick);
    });
  }

  function initWorldInspectorModal() {
    const root = document.getElementById("gc-world-inspector-root");
    if (!root) return;

    const graph = document.querySelector("[data-command-map-graph]");
    const titleEl = root.querySelector("#gc-world-inspector-title");
    const contentEl = root.querySelector("[data-world-inspector-content]");
    const actionsEl = root.querySelector("[data-world-inspector-actions]");
    if (!titleEl || !contentEl || !actionsEl) return;

    let lastFocus = null;
    const _wiDebug = {
      modalFound: true,
      mapRootFound: !!graph,
      nodeCount: 0,
      lastClickedNode: null,
      lastPayload: null,
    };

    const INSPECT_NODE_SELECTOR = [
      "[data-colony-location-inspect]",
      "[data-world-field-inspect]",
      "[data-expansion-site-inspect]",
      "[data-landmark-inspect]",
      "[data-foreign-world-colony-inspect]",
      "[data-foreign-empire-inspect]",
    ].join(", ");

    function refreshInspectorNodeCount() {
      _wiDebug.nodeCount = graph ? graph.querySelectorAll(INSPECT_NODE_SELECTOR).length : 0;
    }
    refreshInspectorNodeCount();

    function parseCommandCenterFromSource(source) {
      if (!source) return {};
      const raw = source.getAttribute("data-command-center") || source.dataset.commandCenter || "{}";
      try {
        return JSON.parse(raw);
      } catch (_) {
        return {};
      }
    }

    function detailText(row) {
      if (!row || typeof row !== "object") return "";
      if (row.value_text) return String(row.value_text);
      if (row.value_key) return tf(row.value_key, row.value_key);
      return "";
    }

    function mergeColonyPayload(btn, cc) {
      const base = cc && typeof cc === "object" ? { ...cc } : {};
      const planetId = parseInt(
        String(btn?.dataset.planetId || btn?.dataset.empireIdentitySwitch || base.planet_id || "0"),
        10
      );
      base.panel_kind = "colony";
      if (planetId) base.planet_id = planetId;
      if (!base.name) base.name = btn?.dataset.colonyName || "";
      if (!base.role_label_key && btn?.dataset.colonyRole) {
        base._roleText = btn.dataset.colonyRole;
      }
      if (!base.role_icon && btn?.dataset.colonyIcon) base.role_icon = btn.dataset.colonyIcon;
      const action = base.primary_action && typeof base.primary_action === "object" ? base.primary_action : {};
      if (planetId && String(action.action_key || "") !== "open_colony") {
        base.primary_action = { action_key: "open_colony", enabled: true, planet_id: planetId };
      }
      return base;
    }

    function mergeWorldFieldPayload(btn, cc) {
      const base = cc && typeof cc === "object" ? { ...cc } : {};
      const ds = btn?.dataset || {};
      const worldKey = String(ds.strategicWorldKey || base.world_key || "").trim();
      base.panel_kind = base.panel_kind || "expedition_site";
      if (worldKey) base.world_key = worldKey;
      if (!base.name_key && ds.strategicName) base._nameText = ds.strategicName;
      if (!base.type_key && ds.strategicType) base._typeText = ds.strategicType;
      const details = Array.isArray(base.details) ? [...base.details] : [];
      const hasRisk = details.some((row) => String(row.label_key || "").includes("risk"));
      const hasReward = details.some((row) => String(row.label_key || "").includes("reward"));
      const hasPromise = details.some((row) => String(row.label_key || "").includes("promise"));
      if (!hasRisk && ds.strategicRisk) {
        details.push({ label_key: "expansion_site_inspector_risk", value_text: ds.strategicRisk });
      }
      if (!hasReward && ds.strategicReward) {
        details.push({ label_key: "strategic_world_inspector_bonus", value_text: ds.strategicReward });
      }
      if (!hasPromise && ds.strategicPromise) base._promiseText = ds.strategicPromise;
      base.details = details;
      if (ds.expeditionStatus && ds.expeditionStatus !== "idle") {
        base.status_key = base.status_key || `world_expedition_status_${ds.expeditionStatus.replace("expedition_", "")}`;
      }
      const action = base.primary_action && typeof base.primary_action === "object" ? base.primary_action : {};
      if (worldKey && !action.action_key) {
        let actionKey = "expedition";
        if (ds.strategicColonizable === "1") actionKey = "colonize";
        else if (ds.strategicSalvage === "1") actionKey = "salvage";
        base.primary_action = {
          action_key: actionKey,
          world_key: worldKey,
          enabled: true,
          label_key: actionKey === "colonize" ? "strategic_world_btn_colonize" : "world_inspector_explore",
        };
      }
      return base;
    }

    function mergeExpansionSitePayload(btn) {
      const ds = btn?.dataset || {};
      return {
        panel_kind: "expedition_site",
        _nameText: ds.siteName || "",
        _typeText: ds.siteType || "",
        _promiseText: ds.sitePromise || "",
        details: [
          ds.siteRegion ? { label_key: "expansion_site_inspector_region", value_text: ds.siteRegion } : null,
          ds.siteRisk ? { label_key: "expansion_site_inspector_risk", value_text: ds.siteRisk } : null,
          ds.siteReward ? { label_key: "strategic_world_inspector_bonus", value_text: ds.siteReward } : null,
        ].filter(Boolean),
        primary_action: { action_key: "none", enabled: false },
      };
    }

    function mergeLandmarkPayload(btn) {
      const ds = btn?.dataset || {};
      return {
        panel_kind: "expedition_site",
        _nameText: ds.landmarkName || "",
        _typeText: ds.landmarkType || "",
        _promiseText: ds.landmarkFlavor || "",
        details: [
          ds.landmarkRegion ? { label_key: "expansion_site_inspector_region", value_text: ds.landmarkRegion } : null,
          ds.landmarkStatusLabel ? { label_key: "world_inspector_status", value_text: ds.landmarkStatusLabel } : null,
        ].filter(Boolean),
        primary_action: { action_key: "none", enabled: false },
      };
    }

    function mergeForeignPayload(btn, cc) {
      const base = cc && typeof cc === "object" ? { ...cc } : {};
      const ds = btn?.dataset || {};
      const isEmpire = btn?.matches?.("[data-foreign-empire-inspect]");
      base.panel_kind = isEmpire ? "foreign_empire" : "foreign_colony";
      if (!base.name) {
        base.name = ds.homeworldName || ds.foreignColonyName || ds.empireName || ds.ownerUsername || "";
      }
      if (!base.empire_display_name) {
        base.empire_display_name = ds.empireName || ds.ownerUsername || "";
      }
      if (!base.homeworld_name) {
        base.homeworld_name = ds.homeworldName || ds.empireName || "";
      }
      if (!base.influence_pct && ds.empireInfluence) {
        base.influence_pct = parseInt(ds.empireInfluence, 10) || 0;
      }
      if (!base.colony_count && ds.empireColonyCount) {
        base.colony_count = parseInt(ds.empireColonyCount, 10) || 0;
      }
      if (!base._typeText) {
        base._typeText = isEmpire
          ? (ds.empireRole || tf("empire_homeworld_subtitle", "Founder World"))
          : ds.foreignColonyType || ds.foreignColonyRole || "";
      }
      if (!Array.isArray(base.details) || !base.details.length) {
        base.details = [
          ds.ownerUsername ? { label_key: "world_map_inspector_player", value_text: ds.ownerUsername } : null,
          ds.empireCoords ? { label_key: "world_map_inspector_coords", value_text: ds.empireCoords } : null,
          isEmpire && ds.empireColonyCount
            ? { label_key: "world_map_inspector_colonies", value_text: String(ds.empireColonyCount) }
            : null,
        ].filter(Boolean);
      }
      return base;
    }

    function isForeignInspectorNode(kind, cc, btn) {
      if (kind === "foreign_colony" || kind === "foreign_empire") return true;
      const panelKind = String(cc?.panel_kind || "");
      if (panelKind === "foreign_colony" || panelKind === "foreign_empire") return true;
      return Boolean(
        btn?.matches?.("[data-foreign-world-colony-inspect], [data-foreign-empire-inspect]")
      );
    }

    function hasForeignMissionPayload(cc) {
      const actions = Array.isArray(cc?.mission_actions) ? cc.mission_actions : [];
      if (actions.some((row) => row && row.enabled !== false && String(row.action_key || row.mission || ""))) {
        return true;
      }
      const actionKey = String(cc?.primary_action?.action_key || "");
      return ["attack", "spy", "transport", "station", "deploy", "collect", "recycle", "expedition", "colonize", "salvage", "hold"].includes(actionKey)
        && cc.primary_action.enabled !== false;
    }

    function navigateMissionAction(action) {
      const row = action && typeof action === "object" ? action : {};
      if (row.enabled === false) return;
      const href = String(row.href || "").trim();
      if (!href) return;
      closeModal();
      if (typeof GC.navigateTo === "function") {
        GC.navigateTo(href, { push: true });
      }
    }

    function resetInspectorActions() {
      actionsEl.innerHTML = "";
      actionsEl.className = "gc-world-inspector-actions";
    }

    function appendMissionActions(cc) {
      const rows = Array.isArray(cc?.mission_actions) ? cc.mission_actions : [];
      if (!rows.length) return false;
      if (!actionsEl.children.length) {
        actionsEl.className = "gc-world-inspector-actions gc-world-inspector-actions--missions";
      } else {
        actionsEl.classList.add("gc-world-inspector-actions--missions");
      }
      rows.forEach((row) => {
        if (!row || typeof row !== "object") return;
        const missionKey = String(row.action_key || row.mission || "").trim();
        if (!missionKey) return;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `gc-btn gc-world-inspector-cta gc-world-inspector-mission-btn gc-world-inspector-mission-btn--${missionKey}`;
        btn.textContent = tf(row.label_key, row.label_key || missionKey);
        if (row.enabled === false) {
          btn.disabled = true;
          btn.classList.add("gc-world-inspector-mission-btn--blocked");
          const blockedKey = String(row.blocked_reason_key || "").trim();
          if (blockedKey) {
            btn.title = tf(blockedKey, blockedKey);
          }
        } else {
          btn.classList.add(missionKey === "attack" ? "gc-btn-primary" : "gc-btn-outline");
        }
        btn.addEventListener("click", () => navigateMissionAction(row));
        actionsEl.appendChild(btn);
      });
      return actionsEl.children.length > 0;
    }

    function shouldShowForeignDevPreview(kind, cc, btn) {
      if (!isForeignInspectorNode(kind, cc, btn)) return false;
      return !hasForeignMissionPayload(cc);
    }

    function resolveForeignClassicHref(btn) {
      const ds = btn?.dataset || {};
      const raw = String(ds.empireCoords || ds.coordinatesFormatted || "").trim();
      if (!raw) return "/galaxy?view=system";
      return `/galaxy?view=system&q=${encodeURIComponent(raw)}`;
    }

    function appendForeignDevActions(btn) {
      actionsEl.innerHTML = "";
      actionsEl.className = "gc-world-inspector-actions gc-world-inspector-actions--stacked";
      const classicHref = resolveForeignClassicHref(btn);
      const classic = document.createElement("button");
      classic.type = "button";
      classic.className = "gc-btn gc-btn-primary gc-world-inspector-cta";
      classic.textContent = tf("world_inspector_foreign_dev_classic_cta", "Klassische Ansicht öffnen");
      classic.addEventListener("click", () => {
        closeModal();
        if (typeof GC.navigateTo === "function") {
          GC.navigateTo(classicHref, { push: true });
        }
      });
      actionsEl.appendChild(classic);

      const fleet = document.createElement("button");
      fleet.type = "button";
      fleet.className = "gc-btn gc-btn-outline gc-world-inspector-cta";
      fleet.textContent = tf(
        "world_inspector_foreign_dev_fleet_cta",
        "Flotte über klassische Ansicht senden"
      );
      fleet.addEventListener("click", () => {
        closeModal();
        if (typeof GC.navigateTo === "function") {
          GC.navigateTo(classicHref, { push: true });
        }
      });
      actionsEl.appendChild(fleet);
    }

    function renderForeignEmpirePresenceModal(cc, btn) {
      const ds = btn?.dataset || {};
      const empireName =
        cc.empire_display_name
        || ds.empireName
        || ds.ownerUsername
        || tf("world_map_foreign_empire", "Fremdes Reich");
      const homeworldName = cc.homeworld_name || ds.homeworldName || cc.name || ds.empireName || "";
      const roleLabel = ds.empireRole || tf(cc.role_label_key || "empire_homeworld_subtitle", "Founder World");
      const owner = cc.owner_username || ds.ownerUsername || "";
      const coords =
        ds.empireCoords
        || (Array.isArray(cc.details)
          ? cc.details.find((row) => row.label_key === "world_map_inspector_coords")?.value_text
          : "")
        || "";
      const colonyCount = parseInt(
        String(cc.colony_count ?? ds.empireColonyCount ?? "0"),
        10
      ) || 0;
      const influencePct = parseInt(
        String(cc.influence_pct ?? ds.empireInfluence ?? "0"),
        10
      ) || 0;

      titleEl.textContent = homeworldName || empireName;
      contentEl.innerHTML = `
        <div class="gc-player-card-shell gc-world-inspector-shell gc-world-inspector-shell--foreign-presence">
          <span class="gc-dev-preview-badge gc-dev-preview-badge--banner">${tf("command_map_dev_badge", "DEV")} ${tf("command_map_dev_preview_label", "PREVIEW")}</span>
          <p class="gc-world-inspector-empire-kicker">${empireName}</p>
          <h3 class="gc-world-inspector-place-name"></h3>
          <p class="gc-world-inspector-foreign-presence-lead hint"></p>
          <dl class="gc-world-inspector-stats"></dl>
        </div>`;
      const shell = contentEl.querySelector(".gc-world-inspector-shell--foreign-presence");
      const placeName = shell?.querySelector(".gc-world-inspector-place-name");
      const lead = shell?.querySelector(".gc-world-inspector-foreign-presence-lead");
      const stats = shell?.querySelector(".gc-world-inspector-stats");
      if (placeName) placeName.textContent = homeworldName || empireName;
      if (lead) {
        lead.textContent = tf(
          "world_inspector_foreign_presence_lead",
          "Hier lebt jemand — Missionen auf der Karte folgen in Kürze."
        );
      }
      if (stats) {
        const rows = [
          roleLabel
            ? `<div class="gc-world-inspector-stat"><dt>${tf("world_inspector_type", "Typ")}</dt><dd></dd></div>`
            : "",
          owner
            ? `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_player", "Spieler")}</dt><dd></dd></div>`
            : "",
          colonyCount >= 0
            ? `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_colonies", "Kolonien")}</dt><dd></dd></div>`
            : "",
          influencePct > 0
            ? `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_influence", "Einfluss")}</dt><dd></dd></div>`
            : "",
          coords
            ? `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_coords", "Koordinate")}</dt><dd class="gc-mono"></dd></div>`
            : "",
        ].filter(Boolean);
        stats.innerHTML = rows.join("");
        const dds = stats.querySelectorAll("dd");
        let idx = 0;
        if (roleLabel && dds[idx]) dds[idx++].textContent = roleLabel;
        if (owner && dds[idx]) dds[idx++].textContent = owner;
        if (colonyCount >= 0 && dds[idx]) dds[idx++].textContent = String(colonyCount);
        if (influencePct > 0 && dds[idx]) dds[idx++].textContent = `${influencePct}%`;
        if (coords && dds[idx]) dds[idx].textContent = coords;
      }
      appendForeignDevActions(btn);
    }

    function renderForeignMissionModal(cc, btn) {
      const ds = btn?.dataset || {};
      const isEmpire = cc.panel_kind === "foreign_empire" || btn?.matches?.("[data-foreign-empire-inspect]");
      const empireName =
        cc.empire_display_name
        || ds.empireName
        || ds.ownerUsername
        || tf("world_map_foreign_empire", "Fremdes Reich");
      const homeworldName = cc.homeworld_name || ds.homeworldName || cc.name || ds.empireName || "";
      const name =
        cc.name
        || homeworldName
        || ds.foreignColonyName
        || ds.empireName
        || ds.ownerUsername
        || empireName;
      const typeLabel =
        cc._typeText
        || (cc.type_label_key ? tf(cc.type_label_key, cc.type_label_key) : "")
        || (cc.role_label_key ? tf(cc.role_label_key, cc.role_label_key) : "")
        || ds.foreignColonyType
        || ds.foreignColonyRole
        || ds.empireRole
        || "";
      const details = Array.isArray(cc.details) ? cc.details : [];
      const coords =
        ds.empireCoords
        || details.find((row) => row.label_key === "world_map_inspector_coords")?.value_text
        || "";
      const owner =
        cc.owner_username
        || ds.ownerUsername
        || details.find((row) => row.label_key === "world_map_inspector_player")?.value_text
        || "";

      titleEl.textContent = isEmpire ? (homeworldName || empireName) : name;
      contentEl.innerHTML = `
        <div class="gc-player-card-shell gc-world-inspector-shell gc-world-inspector-shell--foreign-mission">
          ${isEmpire ? `<p class="gc-world-inspector-empire-kicker">${empireName}</p>` : ""}
          <h3 class="gc-world-inspector-place-name"></h3>
          ${typeLabel ? `<p class="gc-world-inspector-kicker">${typeLabel}</p>` : ""}
          <dl class="gc-world-inspector-stats"></dl>
        </div>`;
      const shell = contentEl.querySelector(".gc-world-inspector-shell--foreign-mission");
      const placeName = shell?.querySelector(".gc-world-inspector-place-name");
      const stats = shell?.querySelector(".gc-world-inspector-stats");
      if (placeName) placeName.textContent = isEmpire ? (homeworldName || empireName) : name;
      if (stats) {
        const rows = [];
        if (owner) {
          rows.push(
            `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_player", "Spieler")}</dt><dd></dd></div>`
          );
        }
        if (coords) {
          rows.push(
            `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_coords", "Koordinate")}</dt><dd class="gc-mono"></dd></div>`
          );
        }
        if (isEmpire && cc.colony_count != null) {
          rows.push(
            `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_colonies", "Kolonien")}</dt><dd></dd></div>`
          );
        }
        stats.innerHTML = rows.join("");
        const dds = stats.querySelectorAll("dd");
        let idx = 0;
        if (owner && dds[idx]) dds[idx++].textContent = owner;
        if (coords && dds[idx]) dds[idx++].textContent = coords;
        if (isEmpire && cc.colony_count != null && dds[idx]) dds[idx++].textContent = String(cc.colony_count);
      }
      appendPrimaryAction(cc, btn);
    }

    function renderForeignDevPreviewModal(cc, btn) {
      const ds = btn?.dataset || {};
      const name =
        cc.name
        || ds.foreignColonyName
        || ds.empireName
        || ds.ownerUsername
        || tf("world_map_foreign_empire", "Fremdes Reich");
      const typeLabel =
        cc._typeText || ds.foreignColonyType || ds.foreignColonyRole || "";
      const coords =
        ds.empireCoords
        || (Array.isArray(cc.details)
          ? cc.details.find((row) => row.label_key === "world_map_inspector_coords")?.value_text
          : "")
        || "";
      const owner =
        ds.ownerUsername
        || (Array.isArray(cc.details)
          ? cc.details.find((row) => row.label_key === "world_map_inspector_player")?.value_text
          : "")
        || "";

      titleEl.textContent = name;
      contentEl.innerHTML = `
        <div class="gc-player-card-shell gc-world-inspector-shell gc-world-inspector-shell--foreign-dev">
          <span class="gc-dev-preview-badge gc-dev-preview-badge--banner">${tf("command_map_dev_badge", "DEV")} ${tf("command_map_dev_preview_label", "PREVIEW")}</span>
          <h3 class="gc-world-inspector-place-name"></h3>
          <p class="gc-world-inspector-foreign-dev-lead hint"></p>
          <dl class="gc-world-inspector-stats"></dl>
        </div>`;
      const shell = contentEl.querySelector(".gc-world-inspector-shell--foreign-dev");
      const placeName = shell?.querySelector(".gc-world-inspector-place-name");
      const lead = shell?.querySelector(".gc-world-inspector-foreign-dev-lead");
      const stats = shell?.querySelector(".gc-world-inspector-stats");
      if (placeName) placeName.textContent = name;
      if (lead) {
        lead.textContent = tf(
          "world_inspector_foreign_dev_body",
          "Fremde Welten sind sichtbar, Missionen werden noch vorbereitet."
        );
      }
      if (stats) {
        const rows = [];
        if (typeLabel) {
          rows.push(
            `<div class="gc-world-inspector-stat"><dt>${tf("world_inspector_type", "Typ")}</dt><dd></dd></div>`
          );
        }
        if (coords) {
          rows.push(
            `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_coords", "Koordinate")}</dt><dd class="gc-mono"></dd></div>`
          );
        }
        if (owner) {
          rows.push(
            `<div class="gc-world-inspector-stat"><dt>${tf("world_map_inspector_player", "Spieler")}</dt><dd></dd></div>`
          );
        }
        stats.innerHTML = rows.join("");
        const dds = stats.querySelectorAll("dd");
        let idx = 0;
        if (typeLabel && dds[idx]) dds[idx++].textContent = typeLabel;
        if (coords && dds[idx]) dds[idx++].textContent = coords;
        if (owner && dds[idx]) dds[idx].textContent = owner;
      }
      appendForeignDevActions(btn);
    }

    function resolveInspectorContext(btn) {
      if (!(btn instanceof HTMLElement)) return null;
      if (btn.matches("[data-colony-location-inspect]")) {
        const planetId = String(btn.dataset.planetId || btn.dataset.empireIdentitySwitch || "");
        const source = graph?.querySelector(`[data-colony-actions-source="${planetId}"]`);
        return {
          cc: mergeColonyPayload(btn, parseCommandCenterFromSource(source)),
          btn,
          kind: "colony",
          discovery: false,
        };
      }
      if (btn.matches("[data-world-field-inspect]")) {
        const worldKey = String(btn.dataset.strategicWorldKey || "").trim();
        const source = worldKey ? graph?.querySelector(`[data-world-field-source="${worldKey}"]`) : null;
        return {
          cc: mergeWorldFieldPayload(btn, parseCommandCenterFromSource(source)),
          btn,
          kind: "expedition_site",
          discovery: btn.dataset.expeditionStatus === "recently_reported",
        };
      }
      if (btn.matches("[data-expansion-site-inspect]")) {
        return { cc: mergeExpansionSitePayload(btn), btn, kind: "expedition_site", discovery: false };
      }
      if (btn.matches("[data-landmark-inspect]")) {
        return { cc: mergeLandmarkPayload(btn), btn, kind: "expedition_site", discovery: false };
      }
      if (btn.matches("[data-foreign-world-colony-inspect], [data-foreign-empire-inspect]")) {
        const sourceKey = String(btn.dataset.foreignColonySource || "").trim();
        const source = sourceKey ? graph?.querySelector(`[data-foreign-colony-source="${sourceKey}"]`) : null;
        const isEmpire = btn.matches("[data-foreign-empire-inspect]");
        return {
          cc: mergeForeignPayload(btn, parseCommandCenterFromSource(source)),
          btn,
          kind: isEmpire ? "foreign_empire" : "foreign_colony",
          discovery: false,
        };
      }
      return null;
    }

    function inspectorHasContent(cc) {
      if (!cc || typeof cc !== "object") return false;
      if (cc.planet_id || cc.name || cc._nameText || cc.name_key || cc.world_key) return true;
      return false;
    }

    function markInspectorNodeSelected(btn) {
      if (!graph || !btn) return;
      graph.querySelectorAll(`${INSPECT_NODE_SELECTOR}.is-selected`).forEach((el) => {
        el.classList.remove("is-selected");
        el.setAttribute("aria-pressed", "false");
      });
      btn.classList.add("is-selected");
      btn.setAttribute("aria-pressed", "true");
    }

    function formatFleetLabel(labelKey) {
      const raw = String(labelKey || "");
      const pipe = raw.indexOf("|");
      if (pipe >= 0) {
        const missionKey = raw.slice(0, pipe);
        const targetName = raw.slice(pipe + 1).trim();
        const mission = tf(missionKey, missionKey);
        return targetName ? `${mission} · ${targetName}` : mission;
      }
      return tf(raw, raw);
    }

    function queueLine(cc, key, labelKey) {
      const rows = Array.isArray(cc.queues) ? cc.queues : [];
      const row = rows.find((item) => String(item.key || "") === key);
      const active = row && String(row.state || "") === "active";
      const statusKey = active ? "command_map_hover_queue_active" : "command_map_hover_queue_free";
      return `<div class="gc-world-inspector-stat"><dt>${tf(labelKey, labelKey)}</dt><dd class="${active ? "is-active" : ""}">${tf(statusKey, active ? "Active" : "Idle")}</dd></div>`;
    }

    function closeModal() {
      root.hidden = true;
      root.setAttribute("aria-hidden", "true");
      root.classList.remove("is-open");
      root.classList.remove("gc-world-inspector-modal--discovery");
      document.body.classList.remove("gc-player-card-open");
      contentEl.innerHTML = "";
      actionsEl.innerHTML = "";
      if (lastFocus && typeof lastFocus.focus === "function") {
        try {
          lastFocus.focus();
        } catch (_) {}
      }
      lastFocus = null;
    }

    function appendPrimaryAction(cc, btn) {
      resetInspectorActions();
      const action = cc.primary_action && typeof cc.primary_action === "object" ? cc.primary_action : {};
      const actionKey = String(action.action_key || "");
      if (cc.panel_kind === "colony") {
        const planetId = parseInt(
          String(cc.planet_id || btn?.dataset.planetId || btn?.dataset.empireIdentitySwitch || "0"),
          10
        );
        if (!planetId) {
          appendMissionActions(cc);
          return;
        }
        const cta = document.createElement("button");
        cta.type = "button";
        cta.className = "gc-btn gc-btn-primary gc-world-inspector-cta";
        cta.textContent = tf("world_inspector_open_colony", "Kolonie öffnen");
        cta.addEventListener("click", async () => {
          const pid = parseInt(String(cc.planet_id || btn?.dataset.planetId || "0"), 10);
          if (!pid) return;
          try {
            const res = await GC.fetchGameAction("/api/planets/active", {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
              body: JSON.stringify({ planet_id: pid }),
            });
            if (res?.ok) {
              applyActionState(res, "planet_switch");
              closeModal();
              if (typeof GC.navigateTo === "function") {
                GC.navigateTo("/overview", { push: true });
              }
            }
          } catch (_) {}
        });
        actionsEl.appendChild(cta);
        appendMissionActions(cc);
        return;
      }
      if (appendMissionActions(cc)) return;
      if (!actionKey || actionKey === "none" || action.enabled === false) return;
      const cta = document.createElement("button");
      cta.type = "button";
      cta.className = "gc-btn gc-btn-primary gc-world-inspector-cta";
      cta.textContent = tf(action.label_key || "world_inspector_explore", action.label_key || "Erkunden");
      cta.disabled = action.enabled === false;
      cta.addEventListener("click", () => {
        const wk = String(action.world_key || cc.world_key || btn?.dataset.strategicWorldKey || "").trim();
        if (!wk) return;
        const params = new URLSearchParams();
        if (actionKey === "colonize") {
          params.set("mission", "colonize");
          params.set("world_key", wk);
          params.set("target_type", "strategic_world");
        } else if (actionKey === "salvage") {
          params.set("mission", "expedition");
          params.set("world_key", wk);
          params.set("target_type", "wreckage");
        } else if (actionKey === "expedition") {
          params.set("mission", "expedition");
          params.set("world_key", wk);
          params.set("target_type", "expedition_world");
        } else {
          params.set("mission", "expedition");
          params.set("world_key", wk);
        }
        closeModal();
        if (typeof GC.navigateTo === "function") {
          GC.navigateTo(`/fleet?${params.toString()}`, { push: true });
        }
      });
      actionsEl.appendChild(cta);
    }

    function renderColonyModal(cc, btn) {
      const name = cc.name || btn?.dataset.colonyName || "";
      const roleKey = String(cc.role_label_key || "").trim();
      const role = roleKey ? tf(roleKey, roleKey) : (cc._roleText || btn?.dataset.colonyRole || "");
      const coord = String(cc.coordinates_formatted || "").trim();
      const progress = cc.progress && typeof cc.progress === "object" ? cc.progress : {};
      const resources = Array.isArray(cc.resources) ? cc.resources : [];
      const metal = resources.find((row) => row.key === "metal");
      const fleetCount = (Array.isArray(cc.fleets) ? cc.fleets : []).filter(
        (row) => String(row.label_key || "") !== "command_center_fleet_ready"
      ).length;

      titleEl.textContent = name;
      contentEl.innerHTML = `
        <div class="gc-player-card-shell gc-world-inspector-shell">
          <p class="gc-world-inspector-kicker">${role}${coord ? ` · <span class="gc-mono hint">${coord}</span>` : ""}</p>
          <dl class="gc-world-inspector-stats">
            ${progress.level ? `<div class="gc-world-inspector-stat"><dt>${tf("world_inspector_level", "Level")}</dt><dd>${progress.level}</dd></div>` : ""}
            ${metal?.rate ? `<div class="gc-world-inspector-stat"><dt>${tf("world_inspector_production", "Produktion")}</dt><dd>${metal.rate}</dd></div>` : ""}
            ${queueLine(cc, "build", "command_map_hover_queue_build")}
            ${queueLine(cc, "research", "command_map_hover_queue_research")}
            ${queueLine(cc, "shipyard", "command_map_hover_queue_shipyard")}
            ${fleetCount > 0 ? `<div class="gc-world-inspector-stat"><dt>${tf("world_inspector_fleets", "Flotten")}</dt><dd>${tf("command_map_hover_fleets", { count: fleetCount })}</dd></div>` : ""}
          </dl>
        </div>`;
      appendPrimaryAction(cc, btn);
    }

    function renderWorldModal(cc, btn, discovery) {
      const name = cc._nameText
        || cc.name
        || (cc.name_key ? tf(cc.name_key, cc.name_key) : "")
        || btn?.dataset.strategicName
        || btn?.dataset.siteName
        || btn?.dataset.landmarkName
        || btn?.dataset.foreignColonyName
        || btn?.dataset.empireName
        || "";
      const typeKey = cc.type_key || "";
      const typeLabel = cc._typeText
        || (typeKey ? tf(typeKey, typeKey) : "")
        || btn?.dataset.strategicType
        || btn?.dataset.siteType
        || btn?.dataset.landmarkType
        || "";
      const details = Array.isArray(cc.details) ? cc.details : [];
      const detailRow = (needle) => details.find((row) => String(row.label_key || "").includes(needle));
      const promise = detailRow("promise");
      const risk = detailRow("risk") || (cc.risk_key ? { value_key: cc.risk_key } : null);
      const reward = detailRow("reward");
      const region = detailRow("region");
      const activity = cc.expedition_activity && typeof cc.expedition_activity === "object"
        ? cc.expedition_activity
        : null;
      const statusKey = activity?.status_key || cc.status_key || "";
      const statusText = details.find((row) => row.label_key === "world_inspector_status")?.value_text || "";
      const riskText = detailText(risk) || btn?.dataset.strategicRisk || btn?.dataset.siteRisk || "";
      const rewardText = detailText(reward) || btn?.dataset.strategicReward || btn?.dataset.siteReward || "";
      const regionText = detailText(region) || btn?.dataset.siteRegion || btn?.dataset.landmarkRegion || "";
      const promiseText = cc._promiseText
        || (promise?.value_key ? tf(promise.value_key, promise.value_key) : detailText(promise))
        || btn?.dataset.strategicPromise
        || btn?.dataset.sitePromise
        || btn?.dataset.landmarkFlavor
        || "";

      titleEl.textContent = discovery
        ? tf("command_map_discovery_feed_title", "Neuer Kontakt entdeckt")
        : name;
      contentEl.innerHTML = `
        <div class="gc-player-card-shell gc-world-inspector-shell${discovery ? " gc-world-inspector-shell--discovery" : ""}">
          ${discovery ? `<p class="gc-world-inspector-discovery-sub">${tf("command_map_discovery_feed_subtitle", "Ein unbekannter Ort wurde im Sektor bestätigt.")}</p>` : ""}
          <h3 class="gc-world-inspector-place-name">${name}</h3>
          ${typeLabel ? `<p class="gc-world-inspector-kicker">${typeLabel}</p>` : ""}
          <dl class="gc-world-inspector-stats">
            ${regionText ? `<div class="gc-world-inspector-stat"><dt>${tf("expansion_site_inspector_region", "Region")}</dt><dd>${regionText}</dd></div>` : ""}
            ${riskText ? `<div class="gc-world-inspector-stat"><dt>${tf("expansion_site_inspector_risk", "Gefahr")}</dt><dd>${riskText}</dd></div>` : ""}
            ${rewardText ? `<div class="gc-world-inspector-stat"><dt>${tf("strategic_world_inspector_bonus", "Belohnung")}</dt><dd>${rewardText}</dd></div>` : ""}
            ${statusText ? `<div class="gc-world-inspector-stat"><dt>${tf("world_inspector_status", "Status")}</dt><dd>${statusText}</dd></div>` : ""}
            ${!statusText && statusKey ? `<div class="gc-world-inspector-stat"><dt>${tf("world_inspector_status", "Status")}</dt><dd>${tf(statusKey, statusKey)}</dd></div>` : ""}
          </dl>
          ${promiseText ? `<blockquote class="gc-world-inspector-flavor">${promiseText}</blockquote>` : ""}
        </div>`;
      appendPrimaryAction(cc, btn);
    }

    function openModal(opts) {
      const cc = opts?.cc && typeof opts.cc === "object" ? opts.cc : {};
      const btn = opts?.btn || null;
      const discovery = Boolean(opts?.discovery);
      const kind = String(opts?.kind || cc.panel_kind || "colony");

      logCommandMapTelemetry("inspector_open", { node_kind: kind });

      lastFocus = document.activeElement;
      root.hidden = false;
      root.setAttribute("aria-hidden", "false");
      root.classList.add("is-open");
      root.classList.toggle("gc-world-inspector-modal--discovery", discovery);
      document.body.classList.add("gc-player-card-open");

      if (isForeignInspectorNode(kind, cc, btn) && hasForeignMissionPayload(cc)) {
        renderForeignMissionModal(cc, btn);
      } else if (kind === "foreign_empire") {
        renderForeignEmpirePresenceModal(cc, btn);
      } else if (shouldShowForeignDevPreview(kind, cc, btn)) {
        renderForeignDevPreviewModal(cc, btn);
      } else if (kind === "colony" || cc.panel_kind === "colony") {
        renderColonyModal(cc, btn);
      } else {
        renderWorldModal(cc, btn, discovery);
      }

      const closeBtn = root.querySelector("[data-world-inspector-close].gc-player-card-close");
      closeBtn?.focus();
    }

    function onKeyDown(ev) {
      if (ev.key === "Escape" && !root.hidden) {
        ev.preventDefault();
        closeModal();
      }
    }

    root.querySelectorAll("[data-world-inspector-close]").forEach((el) => {
      el.addEventListener("click", closeModal);
    });
    document.addEventListener("keydown", onKeyDown);

    function openFromNode(btn) {
      const ctx = resolveInspectorContext(btn);
      if (!ctx || !inspectorHasContent(ctx.cc)) return false;
      _wiDebug.lastClickedNode = btn;
      _wiDebug.lastPayload = ctx.cc;
      markInspectorNodeSelected(btn);
      logCommandMapTelemetry("node_click", {
        node_kind: String(btn.dataset.panelKind || btn.dataset.nodeKind || btn.dataset.mapNodeKind || ""),
      });
      openModal(ctx);
      return true;
    }

    function onInspectorNodeClick(e) {
      if (!graph || !graph.contains(e.target)) return;
      if (graph.dataset.wasDragging === "1") {
        graph.dataset.wasDragging = "0";
        return;
      }
      const btn = e.target.closest(INSPECT_NODE_SELECTOR);
      if (!btn || !graph.contains(btn)) return;
      if (btn.matches("[data-colony-location-inspect]") && !btn.classList.contains("is-active")) {
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      openFromNode(btn);
    }

    GC.openWorldInspectorModal = openModal;
    GC.closeWorldInspectorModal = closeModal;
    GC.openWorldInspectorFromNode = openFromNode;
    GC.debugWorldInspector = function debugWorldInspector() {
      refreshInspectorNodeCount();
      return {
        ..._wiDebug,
        modalOpen: root.classList.contains("is-open") && !root.hidden,
      };
    };

    if (graph) {
      graph.addEventListener("click", onInspectorNodeClick);
    }

    GC.registerCleanup(() => {
      if (graph) graph.removeEventListener("click", onInspectorNodeClick);
      root.querySelectorAll("[data-world-inspector-close]").forEach((el) => {
        el.removeEventListener("click", closeModal);
      });
      document.removeEventListener("keydown", onKeyDown);
      delete GC.openWorldInspectorModal;
      delete GC.closeWorldInspectorModal;
      delete GC.openWorldInspectorFromNode;
      delete GC.debugWorldInspector;
      closeModal();
    });
  }

  function initCommandMapLocationActions() {
    const graph = document.querySelector("[data-command-map-graph]");
    if (!graph) return;

    const mapRoot = document.querySelector(".galaxy-command-map-panel");
    const colonyPanel = mapRoot?.querySelector("[data-command-map-colony-panel]");
    const hudBody = colonyPanel?.querySelector("[data-command-map-hud-body]");
    const iconEl = colonyPanel?.querySelector("[data-command-center-icon]");
    const nameEl = colonyPanel?.querySelector("[data-command-center-name]");
    const roleEl = colonyPanel?.querySelector("[data-command-center-role]");
    const coordEl = colonyPanel?.querySelector("[data-command-center-coord]");
    const statusEl = colonyPanel?.querySelector("[data-command-center-status]");
    const riskEl = colonyPanel?.querySelector("[data-command-center-risk]");
    const resourcesEl = colonyPanel?.querySelector("[data-command-center-resources]");
    const fleetsEl = colonyPanel?.querySelector("[data-command-center-fleets]");
    const hudStatusEl = colonyPanel?.querySelector("[data-command-center-hud-status]");
    const actionsEl = colonyPanel?.querySelector("[data-command-center-actions]");
    const newsEl = colonyPanel?.querySelector("[data-command-center-activity-feed]")
      || colonyPanel?.querySelector("[data-command-center-news]");
    const openColonyBtn = colonyPanel?.querySelector("[data-command-map-open-colony]");
    const primaryBtn = colonyPanel?.querySelector("[data-command-center-primary]");
    const blockedEl = colonyPanel?.querySelector("[data-command-center-blocked]");
    const siteInspector = document.querySelector("[data-command-map-site-inspector]");

    let ccWorldKey = "";
    let ccWorldName = "";

    resetCommandMapSidePanels(graph);

    function parseColonyCommandCenter(planetId) {
      const source = graph.querySelector(`[data-colony-actions-source="${planetId}"]`);
      if (!source) return {};
      try {
        return JSON.parse(source.dataset.commandCenter || "{}");
      } catch (_) {
        return {};
      }
    }

    function findHudColonyButton() {
      return graph.querySelector("[data-colony-location-inspect].is-active")
        || graph.querySelector(".galaxy-command-map-node--colony.galaxy-command-map-node--hub[data-colony-location-inspect]")
        || graph.querySelector("[data-colony-location-inspect]");
    }

    function renderSidebarHud(cc) {
      if (!cc || cc.panel_kind !== "colony") return;
      if (iconEl) iconEl.textContent = cc.role_icon || "🌍";
      if (nameEl) nameEl.textContent = cc.name || "";
      if (roleEl) {
        const roleKey = String(cc.role_label_key || "").trim();
        roleEl.textContent = roleKey ? tf(roleKey, roleKey) : "";
        roleEl.hidden = !roleEl.textContent;
      }
      if (hudStatusEl) {
        hudStatusEl.innerHTML = "";
        const progress = cc.progress && typeof cc.progress === "object" ? cc.progress : {};
        if (progress.level != null) {
          const li = document.createElement("li");
          li.textContent = tf("command_center_colony_level", { level: progress.level }, `Level ${progress.level}`);
          hudStatusEl.appendChild(li);
        }
        const fleetCount = (Array.isArray(cc.fleets) ? cc.fleets : []).filter(
          (row) => String(row.label_key || "") !== "command_center_fleet_ready"
        ).length;
        if (fleetCount > 0) {
          const li = document.createElement("li");
          li.textContent = tf("command_map_hover_fleets", { count: fleetCount });
          hudStatusEl.appendChild(li);
        }
        const queues = Array.isArray(cc.queues) ? cc.queues : [];
        const activeQueues = queues.filter((row) => String(row.state || "") === "active");
        if (activeQueues.length) {
          const li = document.createElement("li");
          li.textContent = activeQueues
            .map((row) => tf(row.label_key, row.label_key || row.key || ""))
            .join(" · ");
          hudStatusEl.appendChild(li);
        } else {
          const li = document.createElement("li");
          li.className = "hint";
          li.textContent = tf("command_center_hud_idle", "Keine aktiven Queues");
          hudStatusEl.appendChild(li);
        }
      }
      if (actionsEl) {
        actionsEl.innerHTML = "";
        (Array.isArray(cc.quick_actions) ? cc.quick_actions : []).slice(0, 4).forEach((row) => {
          actionsEl.appendChild(renderColonyActionCard(row));
        });
        GC.startProgressTicker();
      }
      if (newsEl) {
        const feed = Array.isArray(cc.activity_feed) ? cc.activity_feed : (Array.isArray(cc.news) ? cc.news : []);
        renderActivityFeed(feed, newsEl, { maxItems: 3 });
      }
    }

    function bootstrapSidebarHud() {
      const btn = findHudColonyButton();
      const planetId = String(btn?.dataset.planetId || btn?.dataset.empireIdentitySwitch || "");
      if (!planetId) return;
      renderSidebarHud(parseColonyCommandCenter(planetId));
    }

    function setCommandCenterSectionTitles() {
      /* GC-597: section titles live in modal / compact HUD only */
    }

    const progressSection = null;

    function formatCcFleetLabel(labelKey) {
      const raw = String(labelKey || "");
      const pipe = raw.indexOf("|");
      if (pipe >= 0) {
        const missionKey = raw.slice(0, pipe);
        const targetName = raw.slice(pipe + 1).trim();
        const mission = tf(missionKey, missionKey);
        return targetName ? `${mission} ${targetName}` : mission;
      }
      return tf(raw, raw);
    }

    function formatCcExpeditionEta(etaAt) {
      const ts = parseTimerTarget(etaAt);
      if (!ts) return "";
      const rem = movementRemainingSeconds(ts, getTimerServerNow());
      if (typeof GC.formatCountdownRemain === "function") {
        return GC.formatCountdownRemain(rem);
      }
      return String(Math.max(0, Math.floor(rem)));
    }

    function renderCcDetailList(cc) {
      if (!resourcesEl) return;
      resourcesEl.innerHTML = "";
      resourcesEl.className = "gc-command-center-detail-list";
      (Array.isArray(cc.details) ? cc.details : []).forEach((row) => {
        const wrap = document.createElement("div");
        wrap.className = "gc-command-center-detail-row";
        const dt = document.createElement("dt");
        dt.textContent = tf(row.label_key, row.label_key || "");
        const dd = document.createElement("dd");
        if (row.value_text) {
          dd.textContent = row.value_text;
        } else {
          dd.textContent = tf(row.value_key, row.value_key || "");
        }
        if (row.tone) dd.classList.add(`gc-command-center-detail-tone--${row.tone}`);
        wrap.appendChild(dt);
        wrap.appendChild(dd);
        resourcesEl.appendChild(wrap);
      });
    }

    function renderCcExpeditionProgress(cc, { showExpeditionCount = false } = {}) {
      if (!fleetsEl) return;
      fleetsEl.innerHTML = "";
      fleetsEl.className = "gc-command-center-progress-list";
      const fam = cc.familiarity && typeof cc.familiarity === "object" ? cc.familiarity : null;
      if (fam) {
        const li = document.createElement("li");
        li.className = "gc-command-center-progress-row";
        const title = tf(fam.title_key || "world_progress_inspector_title", "Bekanntheit");
        const status = tf(fam.label_key, fam.label_key || "");
        li.innerHTML = `<span class="gc-command-center-progress-label">${title}</span><span class="gc-command-center-progress-value">${status}</span>`;
        fleetsEl.appendChild(li);
        const nextMs = parseInt(fam.next_milestone, 10) || 0;
        const count = parseInt(fam.expedition_count, 10) || 0;
        if (showExpeditionCount) {
          const countLi = document.createElement("li");
          countLi.className = "gc-command-center-progress-row hint";
          countLi.textContent = tf("command_center_expedition_count", {
            current: count,
            target: nextMs > 0 ? nextMs : count,
          });
          fleetsEl.appendChild(countLi);
        }
        if (!fam.outpost_prepared && nextMs > 0) {
          const prog = document.createElement("li");
          prog.className = "gc-command-center-progress-row hint";
          prog.textContent = tf("world_progress_inspector_next", {
            current: count,
            target: nextMs,
            milestone: nextMs,
          });
          fleetsEl.appendChild(prog);
        }
        if (fam.outpost_prepared) {
          const hint = document.createElement("li");
          hint.className = "gc-command-center-progress-row hint";
          hint.textContent = tf("world_progress_outpost_prepared_hint", "Außenposten vorbereitet.");
          fleetsEl.appendChild(hint);
        }
      }
      const activity = cc.expedition_activity && typeof cc.expedition_activity === "object"
        ? cc.expedition_activity
        : null;
      if (activity) {
        const li = document.createElement("li");
        li.className = "gc-command-center-progress-row";
        const statusText = tf(activity.status_key || "", activity.status_key || "");
        li.innerHTML = `<span class="gc-command-center-progress-label">${tf("world_expedition_inspector_activity", "Expedition")}</span><span class="gc-command-center-progress-value">${statusText}</span>`;
        fleetsEl.appendChild(li);
        if (activity.status === "expedition_active" || activity.status === "expedition_returning") {
          const eta = document.createElement("li");
          eta.className = "gc-command-center-progress-row hint gc-mono";
          eta.textContent = tf("world_expedition_inspector_eta", {
            eta: formatCcExpeditionEta(activity.eta_at),
          });
          fleetsEl.appendChild(eta);
        }
        if (activity.status === "recently_reported" && activity.report_event_key) {
          const report = document.createElement("li");
          report.className = "gc-command-center-progress-row hint";
          const eventLabel = tf(activity.report_event_key, activity.report_event_key);
          const hintKey = activity.is_salvage
            ? "world_salvage_inspector_report_hint"
            : "world_expedition_inspector_report_hint";
          report.textContent = tf(hintKey, { event: eventLabel });
          fleetsEl.appendChild(report);
        }
      }
      if (!fleetsEl.children.length) {
        const empty = document.createElement("li");
        empty.className = "hint";
        empty.textContent = tf("command_center_progress_empty", "Noch keine Aktivität.");
        fleetsEl.appendChild(empty);
      }
    }

    function ccOpenColonyAction(cc) {
      const payload = cc && typeof cc === "object" ? cc : {};
      if (String(payload.panel_kind || "") !== "colony") return null;
      if (payload.is_own === false) return null;
      const action = payload.primary_action && typeof payload.primary_action === "object"
        ? payload.primary_action
        : null;
      if (!action || String(action.action_key || "") !== "open_colony") return null;
      const planetId = parseInt(action.planet_id || payload.planet_id || "0", 10);
      if (!planetId) return null;
      if (action.enabled === false) return null;
      return { planetId };
    }

    function syncOpenColonyButton(cc) {
      if (!openColonyBtn) return;
      const open = ccOpenColonyAction(cc);
      if (!open) {
        openColonyBtn.hidden = true;
        delete openColonyBtn.dataset.planetId;
        return;
      }
      openColonyBtn.hidden = false;
      openColonyBtn.dataset.planetId = String(open.planetId);
    }

    function renderCcPrimaryAndHints(cc) {
      const action = cc.primary_action && typeof cc.primary_action === "object" ? cc.primary_action : {};
      ccWorldKey = String(action.world_key || cc.world_key || "").trim();
      if (primaryBtn) {
        const actionKey = String(action.action_key || "none");
        if (actionKey === "none" || !action.label_key) {
          primaryBtn.hidden = true;
          primaryBtn.disabled = true;
        } else {
          primaryBtn.hidden = false;
          primaryBtn.disabled = !action.enabled;
          primaryBtn.textContent = tf(action.label_key, action.label_key);
          primaryBtn.dataset.actionKey = actionKey;
          primaryBtn.dataset.worldKey = ccWorldKey;
        }
      }
      if (blockedEl) {
        const blockedKey = String(action.blocked_reason_key || "").trim();
        if (blockedKey && !action.enabled) {
          blockedEl.hidden = false;
          blockedEl.textContent = tf(blockedKey, blockedKey);
        } else {
          blockedEl.hidden = true;
          blockedEl.textContent = "";
        }
      }
      if (action.action_key === "salvage" && ccWorldKey) {
        void refreshCcSalvageState(ccWorldKey);
      }

      if (newsEl) {
        newsEl.className = "gc-command-center-news-list";
        newsEl.innerHTML = "";
        const hints = Array.isArray(cc.hints) ? cc.hints : [];
        if (!hints.length) {
          const li = document.createElement("li");
          li.className = "hint gc-command-center-news-empty";
          li.textContent = tf("command_center_hints_empty", "Keine Hinweise.");
          newsEl.appendChild(li);
        } else {
          hints.forEach((row) => {
            if (row.salvage_prepare) return;
            const li = document.createElement("li");
            li.className = "gc-command-center-hint-row hint";
            li.textContent = tf(row.label_key, row.vars || {}, row.label_key || "");
            newsEl.appendChild(li);
          });
        }
      }
    }

    function applyCommandCenterHeader(cc) {
      if (nameEl && cc.name_key) nameEl.textContent = tf(cc.name_key, cc.name_key);
      else if (nameEl && cc.name) nameEl.textContent = cc.name;
      if (roleEl) {
        const roleKey = String(cc.role_label_key || cc.type_key || "").trim();
        if (roleKey) {
          roleEl.hidden = false;
          roleEl.textContent = tf(roleKey, roleKey);
        } else if (cc.type_key) {
          roleEl.hidden = false;
          roleEl.textContent = tf(cc.type_key, cc.type_key);
        } else {
          roleEl.textContent = "";
          roleEl.hidden = true;
        }
      }
      if (iconEl && cc.role_icon) {
        iconEl.textContent = cc.role_icon;
        iconEl.hidden = false;
      }
      if (coordEl) {
        const coord = String(cc.coordinates_formatted || "").trim();
        if (coord) {
          coordEl.hidden = false;
          coordEl.innerHTML = GC.coordLinkHtml(coord, { label: coord });
        } else {
          coordEl.hidden = true;
          coordEl.textContent = "";
        }
      }
      if (riskEl) {
        const riskKey = String(cc.risk_key || "");
        if (riskKey && String(cc.panel_kind || "") === "expedition_site") {
          riskEl.hidden = false;
          riskEl.textContent = tf(riskKey, riskKey);
          riskEl.className = `gc-command-center-risk gc-command-center-detail-tone--${cc.risk_level || "low"}`;
        } else {
          riskEl.hidden = true;
          riskEl.textContent = "";
          riskEl.className = "gc-command-center-risk";
        }
      }
    }

    function renderExpeditionSiteCommandCenter(cc) {
      renderCcDetailList(cc);
      renderCcExpeditionProgress(cc, { showExpeditionCount: true });
      renderCcPrimaryAndHints(cc);
    }

    function renderStrategicCommandCenter(cc) {
      setCommandCenterSectionTitles("strategic_world");
      if (actionsEl) actionsEl.hidden = true;
      if (progressSection) progressSection.hidden = true;
      renderCcDetailList(cc);
      renderCcPrimaryAndHints(cc);
    }

    function navigateForeignFleetAction(action) {
      const row = action && typeof action === "object" ? action : {};
      const actionKey = String(row.action_key || "");
      if (!actionKey || actionKey === "observe" || row.enabled === false) return;
      const wk = String(row.world_key || ccWorldKey || "").trim();
      const planetId = parseInt(row.planet_id || "0", 10) || 0;
      if (!wk && !planetId) return;
      const params = new URLSearchParams();
      params.set("mission", actionKey === "spy" ? "spy" : "attack");
      params.set("target_type", String(row.target_type || "enemy_colony"));
      if (wk) params.set("world_key", wk);
      if (planetId) params.set("target_planet_id", String(planetId));
      if (typeof GC.navigateTo === "function") {
        GC.navigateTo(`/fleet?${params.toString()}`, { push: true });
      }
    }

    function renderForeignCommandCenter(cc) {
      setCommandCenterSectionTitles("foreign_colony");
      if (progressSection) progressSection.hidden = false;
      if (primaryBtn) {
        primaryBtn.hidden = true;
        primaryBtn.disabled = true;
      }
      if (blockedEl) {
        blockedEl.hidden = true;
        blockedEl.textContent = "";
      }

      ccWorldKey = String(cc.world_key || "").trim();

      if (resourcesEl) {
        resourcesEl.innerHTML = "";
        resourcesEl.className = "gc-command-center-detail-list";
        (Array.isArray(cc.details) ? cc.details : []).forEach((row) => {
          const wrap = document.createElement("div");
          wrap.className = "gc-command-center-detail-row";
          const dt = document.createElement("dt");
          dt.textContent = tf(row.label_key, row.label_key || "");
          const dd = document.createElement("dd");
          if (row.value_text) {
            dd.textContent = row.value_text;
          } else {
            dd.textContent = tf(row.value_key, row.value_key || "");
          }
          wrap.appendChild(dt);
          wrap.appendChild(dd);
          resourcesEl.appendChild(wrap);
        });
      }

      if (fleetsEl) {
        fleetsEl.innerHTML = "";
        fleetsEl.className = "gc-command-center-progress-list";
        const statusKey = String(cc.status_key || "");
        if (statusKey) {
          const li = document.createElement("li");
          li.className = "gc-command-center-progress-row";
          li.innerHTML = `<span class="gc-command-center-progress-label">${tf("command_center_foreign_status_label", "Status")}</span><span class="gc-command-center-progress-value">${tf(statusKey, statusKey)}</span>`;
          fleetsEl.appendChild(li);
        } else {
          const empty = document.createElement("li");
          empty.className = "hint";
          empty.textContent = tf("command_center_intel_empty", "Keine weiteren öffentlichen Daten.");
          fleetsEl.appendChild(empty);
        }
      }

      if (actionsEl) {
        actionsEl.hidden = false;
        actionsEl.innerHTML = "";
        (Array.isArray(cc.actions) ? cc.actions : []).forEach((row) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "gc-command-center-action-btn";
          if (row.enabled === false) btn.disabled = true;
          btn.textContent = tf(row.label_key, row.label_key || row.action_key || "");
          btn.dataset.actionKey = row.action_key || "";
          btn.dataset.targetType = row.target_type || "enemy_colony";
          btn.dataset.worldKey = row.world_key || ccWorldKey || "";
          if (row.planet_id) btn.dataset.planetId = String(row.planet_id);
          btn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            navigateForeignFleetAction(row);
          });
          actionsEl.appendChild(btn);
        });
      }

      if (newsEl) {
        newsEl.className = "gc-command-center-news-list";
        newsEl.innerHTML = "";
        const hints = Array.isArray(cc.hints) ? cc.hints : [];
        if (!hints.length) {
          const li = document.createElement("li");
          li.className = "hint gc-command-center-news-empty";
          li.textContent = tf("command_center_hints_empty", "Keine Hinweise.");
          newsEl.appendChild(li);
        } else {
          hints.forEach((row) => {
            const li = document.createElement("li");
            li.className = "gc-command-center-hint-row hint";
            li.textContent = tf(row.label_key, row.vars || {}, row.label_key || "");
            newsEl.appendChild(li);
          });
        }
      }
    }

    function activityFeedId(row) {
      if (row && row.feed_id) return String(row.feed_id);
      return [
        row?.kind || "",
        row?.label_key || "",
        row?.detail_key || "",
        row?.text || "",
        row?.countdown_at || "",
      ].join("|");
    }

    function renderActivityFeed(feedRows, targetEl, opts) {
      if (!targetEl) return;
      const options = opts && typeof opts === "object" ? opts : {};
      const maxItems = parseInt(options.maxItems, 10) || 0;
      let rows = Array.isArray(feedRows) ? feedRows : [];
      if (maxItems > 0) rows = rows.slice(0, maxItems);
      const seen = GC._activityFeedSeenIds || (GC._activityFeedSeenIds = new Set());
      const seedOnly = !GC._activityFeedSeenInitialized;
      GC._activityFeedSeenInitialized = true;
      targetEl.className = "gc-command-center-activity-feed gc-command-center-news-list";
      targetEl.innerHTML = "";
      if (!rows.length) {
        const li = document.createElement("li");
        li.className = "gc-command-center-activity-empty hint";
        li.textContent = tf("command_center_feed_empty", "Keine aktuellen Ereignisse.");
        targetEl.appendChild(li);
        return;
      }
      rows.forEach((row) => {
        const feedId = activityFeedId(row);
        const isNew = !seedOnly && feedId && !seen.has(feedId);
        if (feedId) seen.add(feedId);
        const presentation = String(row.presentation || "").trim();
        const forceHighlight = presentation === "discovery"
          && !GC._discoveryFeedSeenIds?.has(feedId);
        if (forceHighlight) {
          (GC._discoveryFeedSeenIds || (GC._discoveryFeedSeenIds = new Set())).add(feedId);
        }
        const li = document.createElement("li");
        li.className = `gc-command-center-activity-item gc-command-center-activity-item--${row.kind || "system"}${(isNew || forceHighlight) ? " is-new" : ""}${presentation === "expedition_launch" ? " is-expedition" : ""}${presentation === "discovery" ? " is-discovery" : ""}`;
        if (isNew || forceHighlight) {
          li.dataset.activityFeedId = feedId;
        }
        const link = document.createElement("a");
        link.className = "gc-nav-link gc-command-center-activity-link gc-command-center-news-link";
        link.href = row.href || "/overview";
        link.dataset.gcNav = "1";

        const icon = String(row.icon || "•");
        let title = row.text || tf(row.label_key, row.label_key || "");
        let subtitleHtml = "";
        if (presentation === "discovery") {
          title = tf("command_map_discovery_feed_title", "Neuer Kontakt entdeckt");
          subtitleHtml = `<span class="gc-command-center-activity-subtitle">${tf("command_map_discovery_feed_subtitle", "Ein unbekannter Ort wurde im Sektor bestätigt.")}</span>`;
        } else if (presentation === "expedition_launch") {
          title = tf("command_map_expedition_feed_title", "Expedition unterwegs…");
          if (row.detail_key) {
            const detail = formatCcFleetLabel(row.detail_key);
            if (detail) subtitleHtml = `<span class="gc-command-center-activity-subtitle">${detail}</span>`;
          }
        } else if (row.detail_key) {
          const detail = String(row.detail_key).includes("|")
            ? formatCcFleetLabel(row.detail_key)
            : tf(row.detail_key, row.detail_key);
          title = detail ? `${title} · ${detail}` : title;
        }

        let timerHtml = "";
        if (row.countdown_at) {
          const rem = queueJobRemainingSeconds(
            row.countdown_at,
            getTimerServerNow(),
            row.remaining
          );
          timerHtml = `<time class="gc-command-center-activity-timer gc-mono" data-timer-target="${row.countdown_at}" data-timer-kind="queue"${row.remaining != null ? ` data-server-remaining="${Math.max(0, Math.floor(Number(row.remaining) || 0))}"` : ""}>${GC.formatCountdownRemain(rem)}</time>`;
        }

        link.innerHTML = `<span class="gc-command-center-activity-icon" aria-hidden="true">${icon}</span><span class="gc-command-center-activity-body"><span class="gc-command-center-activity-title">${title}</span>${subtitleHtml}${timerHtml}</span>`;
        li.appendChild(link);
        targetEl.appendChild(li);
      });
      GC.startProgressTicker();
    }

    function renderColonyActionCard(row) {
      const status = String(row.status || "free");
      const card = document.createElement("a");
      card.className = `gc-nav-link gc-command-center-action-card gc-command-center-action-btn gc-command-center-action-card--${status}`;
      card.href = row.href || "/overview";
      card.dataset.gcNav = "1";
      card.dataset.actionStatus = status;

      const icon = String(row.icon || "").trim();
      const label = tf(row.label_key, row.label_key || row.action_key || "");
      let statusText = tf(row.status_key, row.status_key || "");
      if (row.detail_key && status === "queue_active") {
        const detail = tf(row.detail_key, row.detail_key);
        statusText = detail ? `${statusText} · ${detail}` : statusText;
      }

      let timerHtml = "";
      if (status === "queue_active" && row.countdown_at) {
        const rem = queueJobRemainingSeconds(
          row.countdown_at,
          getTimerServerNow(),
          row.remaining
        );
        timerHtml = `<time class="gc-command-center-action-timer gc-mono" data-timer-target="${row.countdown_at}" data-timer-kind="queue"${row.remaining != null ? ` data-server-remaining="${Math.max(0, Math.floor(Number(row.remaining) || 0))}"` : ""}>${GC.formatCountdownRemain(rem)}</time>`;
      }

      card.innerHTML = `${icon ? `<span class="gc-command-center-action-icon" aria-hidden="true">${icon}</span>` : ""}<span class="gc-command-center-action-body"><span class="gc-command-center-action-label">${label}</span><span class="gc-command-center-action-status">${statusText}</span>${timerHtml}</span>`;
      return card;
    }

    function renderColonyQueueRow(row) {
      const li = document.createElement("li");
      li.className = "gc-command-center-progress-row";
      const label = tf(row.label_key, row.label_key || row.key || "");
      const summary = String(row.summary || "").trim();
      const labelText = summary ? `${label} ${summary}` : label;
      if (row.state === "active" && row.countdown_at) {
        const rem = queueJobRemainingSeconds(
          row.countdown_at,
          getTimerServerNow(),
          row.remaining
        );
        li.innerHTML = `<span class="gc-command-center-progress-label">${labelText}</span><time class="gc-command-center-progress-value gc-mono" data-timer-target="${row.countdown_at}" data-timer-kind="queue"${row.remaining != null ? ` data-server-remaining="${Math.max(0, Math.floor(Number(row.remaining) || 0))}"` : ""}>${GC.formatCountdownRemain(rem)}</time>`;
      } else {
        li.innerHTML = `<span class="gc-command-center-progress-label">${labelText}</span><span class="gc-command-center-progress-value hint">${tf("command_center_queue_idle", "Idle")}</span>`;
      }
      return li;
    }

    function renderColonyCommandCenter(cc) {
      setCommandCenterSectionTitles("colony");
      if (progressSection) progressSection.hidden = false;
      if (actionsEl) actionsEl.hidden = false;
      if (primaryBtn) {
        primaryBtn.hidden = true;
        primaryBtn.disabled = true;
      }
      if (blockedEl) {
        blockedEl.hidden = true;
        blockedEl.textContent = "";
      }
      if (resourcesEl) {
        resourcesEl.className = "gc-command-center-resource-list";
        resourcesEl.innerHTML = "";
        (Array.isArray(cc.resources) ? cc.resources : []).forEach((row) => {
          const li = document.createElement("li");
          li.className = "gc-command-center-resource-row";
          li.innerHTML = `<span class="gc-command-center-resource-short">${row.short || ""}</span><span class="gc-command-center-resource-amount gc-mono">${row.amount || "0"}</span><span class="gc-command-center-resource-rate gc-mono">${row.rate || ""}</span>`;
          resourcesEl.appendChild(li);
        });
      }
      if (fleetsEl) {
        fleetsEl.className = "gc-command-center-progress-list";
        fleetsEl.innerHTML = "";
        const progress = cc.progress && typeof cc.progress === "object" ? cc.progress : null;
        if (progress && progress.level != null) {
          const li = document.createElement("li");
          li.className = "gc-command-center-progress-row gc-command-center-progress-row--level";
          const levelLabel = tf("command_center_colony_level", { level: progress.level }, `Level ${progress.level}`);
          const xpHint = progress.xp_remaining > 0
            ? tf("command_center_colony_xp_remaining", { xp: progress.xp_remaining }, `${progress.xp_remaining} XP`)
            : "";
          li.innerHTML = `<span class="gc-command-center-progress-label">${levelLabel}</span><span class="gc-command-center-progress-value gc-mono hint">${xpHint}</span>`;
          fleetsEl.appendChild(li);
        }
        (Array.isArray(cc.queues) ? cc.queues : []).forEach((row) => {
          fleetsEl.appendChild(renderColonyQueueRow(row));
        });
        (Array.isArray(cc.fleets) ? cc.fleets : []).forEach((row) => {
          const li = document.createElement("li");
          const link = document.createElement("a");
          link.className = "gc-nav-link gc-command-center-fleet-link";
          link.href = row.href || "/fleet";
          link.dataset.gcNav = "1";
          link.textContent = `${row.icon || "▶"} ${formatCcFleetLabel(row.label_key)}`;
          li.appendChild(link);
          fleetsEl.appendChild(li);
        });
      }
      if (actionsEl) {
        actionsEl.innerHTML = "";
        (Array.isArray(cc.quick_actions) ? cc.quick_actions : []).forEach((row) => {
          actionsEl.appendChild(renderColonyActionCard(row));
        });
        GC.startProgressTicker();
      }
      if (newsEl) {
        const feed = Array.isArray(cc.activity_feed) ? cc.activity_feed : (Array.isArray(cc.news) ? cc.news : []);
        renderActivityFeed(feed, newsEl);
      }
    }

    async function refreshCcSalvageState(worldKey) {
      if (!primaryBtn || primaryBtn.hidden || primaryBtn.dataset.actionKey !== "salvage") return;
      try {
        const res = await GC.fetchJSON(
          `/api/worlds/salvage-preview?world_key=${encodeURIComponent(worldKey)}`,
          { cache: "no-store" }
        );
        const data = res?.data || {};
        const canStart = Boolean(data.can_start_salvage);
        const hasShips = Boolean(data.has_salvage_ships);
        primaryBtn.disabled = !canStart;
        primaryBtn.textContent = canStart
          ? tf("strategic_world_btn_salvage", "Bergung starten")
          : tf("strategic_world_btn_salvage_prepare", "Bergung vorbereiten");
        if (blockedEl) {
          if (data.block_reason === "no_expedition_ships" && !hasShips) {
            blockedEl.hidden = false;
            blockedEl.textContent = tf(
              "strategic_world_salvage_no_ships",
              "Expeditionsschiffe auf dem aktiven Planeten benötigt."
            );
          } else if (canStart || hasShips) {
            blockedEl.hidden = true;
            blockedEl.textContent = "";
          }
        }
      } catch (_) {
        if (primaryBtn) primaryBtn.disabled = true;
      }
    }

    function renderCommandCenterPanel(data) {
      const cc = data && typeof data === "object" ? data : {};
      const panelKind = String(cc.panel_kind || "");
      if (panelKind === "strategic_world") {
        renderStrategicCommandCenter(cc);
      } else if (panelKind === "expedition_site") {
        renderExpeditionSiteCommandCenter(cc);
      } else if (panelKind === "foreign_colony") {
        renderForeignCommandCenter(cc);
      } else if (panelKind === "colony") {
        renderColonyCommandCenter(cc);
      } else if (openColonyBtn) {
        openColonyBtn.hidden = true;
        delete openColonyBtn.dataset.planetId;
      }
      syncOpenColonyButton(cc);
      applyCommandCenterHeader(cc);
      if (statusEl) {
        const statusKey = String(cc.status_key || "");
        if (statusKey) {
          statusEl.hidden = false;
          statusEl.textContent = tf(statusKey, statusKey);
        } else {
          statusEl.hidden = true;
          statusEl.textContent = "";
        }
      }
    }

    function hideSiteInspector() {
      graph.querySelectorAll("[data-expansion-site-inspect].is-selected, [data-landmark-inspect].is-selected, [data-foreign-empire-inspect].is-selected, [data-foreign-world-colony-inspect].is-selected, [data-world-field-inspect].is-selected").forEach((btn) => {
        btn.classList.remove("is-selected");
        btn.setAttribute("aria-pressed", "false");
      });
    }

    GC.showCommandMapColonyPanel = function showCommandMapColonyPanel(btn) {
      if (!btn) return;
      const planetId = String(btn.dataset.planetId || btn.dataset.empireIdentitySwitch || "");
      hideSiteInspector();
      if (typeof GC.openWorldInspectorFromNode === "function") {
        GC.openWorldInspectorFromNode(btn);
      } else if (typeof GC.openWorldInspectorModal === "function") {
        const cc = mergeColonyPayloadFallback(btn, parseColonyCommandCenter(planetId));
        GC.openWorldInspectorModal({ cc, btn, kind: "colony" });
      }

      graph.querySelectorAll("[data-world-field-inspect]").forEach((item) => {
        item.classList.remove("is-selected");
        item.setAttribute("aria-pressed", "false");
      });
      graph.querySelectorAll("[data-foreign-empire-inspect], [data-foreign-world-colony-inspect]").forEach((item) => {
        item.classList.remove("is-selected");
        item.setAttribute("aria-pressed", "false");
      });
      graph.querySelectorAll("[data-colony-location-inspect]").forEach((item) => {
        const selected = item === btn;
        item.classList.toggle("is-selected", selected);
        item.setAttribute("aria-pressed", selected ? "true" : "false");
      });
    };

    function mergeColonyPayloadFallback(btn, cc) {
      const base = cc && typeof cc === "object" ? { ...cc } : {};
      const pid = parseInt(String(btn?.dataset.planetId || btn?.dataset.empireIdentitySwitch || base.planet_id || "0"), 10);
      base.panel_kind = "colony";
      if (pid) base.planet_id = pid;
      if (!base.name) base.name = btn?.dataset.colonyName || "";
      if (!base.primary_action && pid) {
        base.primary_action = { action_key: "open_colony", enabled: true, planet_id: pid };
      }
      return base;
    }

    GC.showCommandMapStrategicWorldPanel = function showCommandMapStrategicWorldPanel(btn) {
      if (!btn) return;
      hideSiteInspector();
      if (typeof GC.openWorldInspectorFromNode === "function") {
        GC.openWorldInspectorFromNode(btn);
      } else if (typeof GC.openWorldInspectorModal === "function") {
        const worldKey = String(btn.dataset.strategicWorldKey || "").trim();
        const source = worldKey ? graph.querySelector(`[data-world-field-source="${worldKey}"]`) : null;
        let cc = {};
        try {
          cc = JSON.parse(source?.getAttribute("data-command-center") || source?.dataset.commandCenter || "{}");
        } catch (_) {
          cc = {};
        }
        const discovery = btn.dataset.expeditionStatus === "recently_reported";
        GC.openWorldInspectorModal({ cc, btn, kind: cc.panel_kind || "expedition_site", discovery });
      }

      graph.querySelectorAll("[data-colony-location-inspect]").forEach((item) => {
        item.classList.remove("is-selected");
        item.setAttribute("aria-pressed", "false");
      });
      graph.querySelectorAll("[data-foreign-empire-inspect], [data-foreign-world-colony-inspect]").forEach((item) => {
        item.classList.remove("is-selected");
        item.setAttribute("aria-pressed", "false");
      });
      graph.querySelectorAll("[data-world-field-inspect]").forEach((item) => {
        const selected = item === btn;
        item.classList.toggle("is-selected", selected);
        item.setAttribute("aria-pressed", selected ? "true" : "false");
      });
    };

    GC.showCommandMapForeignColonyPanel = function showCommandMapForeignColonyPanel(btn) {
      if (!btn) return;
      hideSiteInspector();
      if (typeof GC.openWorldInspectorFromNode === "function") {
        GC.openWorldInspectorFromNode(btn);
      } else if (typeof GC.openWorldInspectorModal === "function") {
        const sourceKey = String(btn.dataset.foreignColonySource || "").trim();
        const source = sourceKey ? graph.querySelector(`[data-foreign-colony-source="${sourceKey}"]`) : null;
        let cc = {};
        try {
          cc = JSON.parse(source?.getAttribute("data-command-center") || source?.dataset.commandCenter || "{}");
        } catch (_) {
          cc = {};
        }
        GC.openWorldInspectorModal({ cc, btn, kind: cc.panel_kind || "foreign_colony" });
      }

      graph.querySelectorAll("[data-colony-location-inspect], [data-world-field-inspect]").forEach((item) => {
        item.classList.remove("is-selected");
        item.setAttribute("aria-pressed", "false");
      });
      graph.querySelectorAll("[data-foreign-empire-inspect], [data-foreign-world-colony-inspect]").forEach((item) => {
        const selected = item === btn;
        item.classList.toggle("is-selected", selected);
        item.setAttribute("aria-pressed", selected ? "true" : "false");
      });
    };

    function onPrimaryActionClick(e) {
      e.preventDefault();
      e.stopPropagation();
      const actionKey = String(primaryBtn?.dataset.actionKey || "");
      const wk = String(primaryBtn?.dataset.worldKey || ccWorldKey || "").trim();
      if (!wk || !actionKey || actionKey === "none") return;
      const params = new URLSearchParams();
      if (actionKey === "colonize") {
        params.set("mission", "colonize");
        params.set("world_key", wk);
        if (ccWorldName) params.set("colony_name", ccWorldName);
      } else {
        params.set("mission", "expedition");
        params.set("world_key", wk);
      }
      if (typeof GC.navigateTo === "function") {
        GC.navigateTo(`/fleet?${params.toString()}`, { push: true });
      }
    }

    async function onOpenColonyClick(e) {
      e.preventDefault();
      e.stopPropagation();
      if (!openColonyBtn || openColonyBtn.hidden) return;
      const planetId = parseInt(openColonyBtn.dataset.planetId || "0", 10);
      if (!planetId) return;
      try {
        const res = await GC.fetchGameAction("/api/planets/active", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          body: JSON.stringify({ planet_id: planetId }),
        });
        if (res?.ok) {
          applyActionState(res, "planet_switch");
          if (typeof GC.navigateTo === "function") {
            GC.navigateTo("/overview", { push: true });
          }
        }
      } catch (_) {
        /* ignore */
      }
    }

    openColonyBtn?.addEventListener("click", onOpenColonyClick);
    primaryBtn?.addEventListener("click", onPrimaryActionClick);

    GC.registerCleanup(() => {
      delete GC.showCommandMapColonyPanel;
      delete GC.showCommandMapStrategicWorldPanel;
      delete GC.showCommandMapForeignColonyPanel;
      openColonyBtn?.removeEventListener("click", onOpenColonyClick);
      primaryBtn?.removeEventListener("click", onPrimaryActionClick);
      resetCommandMapSidePanels(graph);
    });
  }

  function initCommandMapFleetRoutes() {
    const graph = document.querySelector("[data-command-map-graph]");
    const layer = graph?.querySelector("[data-command-map-fleet-routes]");
    if (!graph || !layer) return;

    let tooltip = graph.querySelector("[data-fleet-route-tooltip]");
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.className = "galaxy-command-map-fleet-route-tooltip";
      tooltip.setAttribute("data-fleet-route-tooltip", "");
      tooltip.hidden = true;
      graph.appendChild(tooltip);
    }

    const nodeIndex = [];
    graph.querySelectorAll(".galaxy-command-map-node").forEach((el) => {
      const wx = parseFloat(el.style.getPropertyValue("--world-x") || "0");
      const wy = parseFloat(el.style.getPropertyValue("--world-y") || "0");
      if (!Number.isFinite(wx) || !Number.isFinite(wy)) return;
      const name = (
        el.dataset.colonyName
        || el.dataset.strategicName
        || el.dataset.siteName
        || el.dataset.foreignColonyName
        || el.dataset.empireName
        || el.querySelector(".galaxy-command-map-node-name")?.textContent
        || ""
      ).trim();
      if (!name) return;
      nodeIndex.push({
        wx,
        wy,
        name,
        worldKey: el.dataset.strategicWorldKey || el.dataset.worldKey || "",
      });
    });

    const resolveRouteLabel = (x, y, worldKey, preferWorldKey) => {
      const wk = String(worldKey || "").trim();
      if (preferWorldKey && wk) {
        const hit = nodeIndex.find((n) => n.worldKey === wk);
        if (hit) return hit.name;
      }
      let best = null;
      let bestDist = 140;
      nodeIndex.forEach((n) => {
        const d = Math.hypot(n.wx - x, n.wy - y);
        if (d < bestDist) {
          bestDist = d;
          best = n;
        }
      });
      return best?.name || "–";
    };

    const legLabel = (phase) => {
      const key = {
        outbound: "fleet_leg_outbound",
        returning: "fleet_leg_returning",
        holding: "fleet_leg_holding",
      }[String(phase || "").toLowerCase()] || "fleet_leg_outbound";
      return tt(key, phase);
    };

    const formatRouteEta = (routeEl) => {
      const etaAt = parseInt(routeEl.dataset.fleetRouteEtaAt || "0", 10);
      const remaining = parseInt(routeEl.dataset.fleetRouteRemaining || "0", 10);
      if (remaining > 0) return formatCountdownRemain(remaining);
      if (etaAt > 0) {
        const nowSec = getApproxServerNow();
        return formatCountdownRemain(Math.max(0, Math.ceil(etaAt - nowSec)));
      }
      return "–";
    };

    const hideTooltip = () => {
      tooltip.hidden = true;
      layer.querySelectorAll(".galaxy-command-map-fleet-route-group.is-hovered").forEach((g) => {
        g.classList.remove("is-hovered");
      });
    };

    const showTooltip = (routeEl, clientX, clientY) => {
      const mission = String(routeEl.dataset.fleetRouteMission || "transport");
      const phase = String(routeEl.dataset.fleetRoutePhase || "outbound");
      const fromX = parseFloat(routeEl.dataset.fleetRouteFromX || "0");
      const fromY = parseFloat(routeEl.dataset.fleetRouteFromY || "0");
      const toX = parseFloat(routeEl.dataset.fleetRouteToX || "0");
      const toY = parseFloat(routeEl.dataset.fleetRouteToY || "0");
      const worldKey = routeEl.dataset.fleetRouteWorldKey || "";
      const missionLabel = tt(`fleet_mission_${mission}`, mission);
      const fromLabel = resolveRouteLabel(fromX, fromY, worldKey, false);
      const toLabel = resolveRouteLabel(toX, toY, worldKey, true);
      const statusLabel = legLabel(phase);
      const etaLabel = formatRouteEta(routeEl);

      tooltip.innerHTML = `<strong>${missionLabel}</strong><dl>
        <dt>${tt("fleet_route_tooltip_from", "From")}</dt><dd>${fromLabel}</dd>
        <dt>${tt("fleet_route_tooltip_to", "To")}</dt><dd>${toLabel}</dd>
        <dt>${tt("fleet_route_tooltip_status", "Status")}</dt><dd>${statusLabel}</dd>
        <dt>${tt("fleet_route_tooltip_eta", "ETA")}</dt><dd class="gc-mono">${etaLabel}</dd>
      </dl>`;
      tooltip.hidden = false;
      const pad = 12;
      const rect = tooltip.getBoundingClientRect();
      let left = clientX + pad;
      let top = clientY + pad;
      if (left + rect.width > window.innerWidth - 8) left = clientX - rect.width - pad;
      if (top + rect.height > window.innerHeight - 8) top = clientY - rect.height - pad;
      tooltip.style.left = `${Math.max(8, left)}px`;
      tooltip.style.top = `${Math.max(8, top)}px`;
    };

    const onRouteEnter = (e) => {
      const routeEl = e.target.closest("[data-fleet-route]");
      if (!routeEl || !layer.contains(routeEl)) return;
      routeEl.classList.add("is-hovered");
      showTooltip(routeEl, e.clientX, e.clientY);
    };

    const onRouteMove = (e) => {
      const routeEl = e.target.closest("[data-fleet-route]");
      if (!routeEl || tooltip.hidden) return;
      showTooltip(routeEl, e.clientX, e.clientY);
    };

    const onRouteLeave = (e) => {
      const routeEl = e.target.closest("[data-fleet-route]");
      if (!routeEl) return;
      const related = e.relatedTarget;
      if (related && routeEl.contains(related)) return;
      hideTooltip();
    };

    const onViewportDragStart = () => hideTooltip();

    layer.addEventListener("pointerenter", onRouteEnter, true);
    layer.addEventListener("pointermove", onRouteMove, true);
    layer.addEventListener("pointerleave", onRouteLeave, true);
    graph.querySelector("[data-command-map-viewport]")?.addEventListener("pointerdown", onViewportDragStart);

    GC.registerCleanup(() => {
      layer.removeEventListener("pointerenter", onRouteEnter, true);
      layer.removeEventListener("pointermove", onRouteMove, true);
      layer.removeEventListener("pointerleave", onRouteLeave, true);
      graph.querySelector("[data-command-map-viewport]")?.removeEventListener("pointerdown", onViewportDragStart);
      hideTooltip();
    });
  }

  function initCommandMapVisualPolish() {
    const graph = document.querySelector("[data-command-map-graph]");
    if (!graph) return;

    const ACTIVITY_CLASS = [
      "has-activity-build",
      "has-activity-research",
      "has-activity-shipyard",
      "has-activity-fleet",
    ];

    function parseCommandCenter(sourceEl) {
      if (!sourceEl) return {};
      try {
        return JSON.parse(sourceEl.dataset.commandCenter || "{}");
      } catch (_) {
        return {};
      }
    }

    function queueActive(cc, key) {
      const rows = Array.isArray(cc.queues) ? cc.queues : [];
      return rows.some((row) => String(row.key || "") === key && String(row.state || "") === "active");
    }

    function fleetActive(cc) {
      const rows = Array.isArray(cc.fleets) ? cc.fleets : [];
      return rows.some((row) => String(row.label_key || "") !== "command_center_fleet_ready");
    }

    function applyColonyNodeActivity() {
      graph.querySelectorAll("[data-colony-actions-source]").forEach((source) => {
        const planetId = String(source.dataset.colonyActionsSource || "");
        const btn = graph.querySelector(`[data-colony-location-inspect][data-planet-id="${planetId}"]`);
        if (!btn) return;
        const cc = parseCommandCenter(source);
        ACTIVITY_CLASS.forEach((cls) => btn.classList.remove(cls));
        if (fleetActive(cc)) {
          btn.classList.add("has-activity-fleet");
        } else if (queueActive(cc, "shipyard")) {
          btn.classList.add("has-activity-shipyard");
        } else if (queueActive(cc, "research")) {
          btn.classList.add("has-activity-research");
        } else if (queueActive(cc, "build")) {
          btn.classList.add("has-activity-build");
        }
      });
    }

    function edgeEndpointsMatch(edgeEl, x1, y1, x2, y2, eps = 36) {
      const ex1 = parseFloat(edgeEl.dataset.edgeX1 || "0");
      const ey1 = parseFloat(edgeEl.dataset.edgeY1 || "0");
      const ex2 = parseFloat(edgeEl.dataset.edgeX2 || "0");
      const ey2 = parseFloat(edgeEl.dataset.edgeY2 || "0");
      const direct = Math.hypot(ex1 - x1, ey1 - y1) + Math.hypot(ex2 - x2, ey2 - y2);
      const flipped = Math.hypot(ex1 - x2, ey1 - y2) + Math.hypot(ex2 - x1, ey2 - y2);
      return Math.min(direct, flipped) <= eps * 2;
    }

    function applyEdgeRouteGlow() {
      const edges = graph.querySelectorAll("[data-command-map-edge]");
      const routes = graph.querySelectorAll("[data-fleet-route]");
      edges.forEach((edgeEl) => {
        edgeEl.classList.remove("is-route-active");
        const edgeType = String(edgeEl.dataset.edgeType || "");
        if (!["hub_link", "trade_route"].includes(edgeType)) return;
        let active = false;
        routes.forEach((routeEl) => {
          const rx1 = parseFloat(routeEl.dataset.fleetRouteFromX || "0");
          const ry1 = parseFloat(routeEl.dataset.fleetRouteFromY || "0");
          const rx2 = parseFloat(routeEl.dataset.fleetRouteToX || "0");
          const ry2 = parseFloat(routeEl.dataset.fleetRouteToY || "0");
          if (edgeEndpointsMatch(edgeEl, rx1, ry1, rx2, ry2)) {
            active = true;
          }
        });
        if (active) edgeEl.classList.add("is-route-active");
      });
      routes.forEach((routeEl) => {
        if (String(routeEl.dataset.fleetRouteMission || "") === "expedition") {
          routeEl.classList.add("is-expedition-route");
        }
      });
    }

    let hoverTooltip = graph.querySelector("[data-colony-hover-tooltip]");
    if (!hoverTooltip) {
      hoverTooltip = document.createElement("div");
      hoverTooltip.className = "galaxy-command-map-colony-hover-tooltip";
      hoverTooltip.setAttribute("data-colony-hover-tooltip", "");
      hoverTooltip.hidden = true;
      graph.appendChild(hoverTooltip);
    }

    function queueStatusLabel(cc, key, labelKey) {
      const active = queueActive(cc, key);
      const statusKey = active ? "command_map_hover_queue_active" : "command_map_hover_queue_free";
      return `<dt>${tf(labelKey, labelKey)}</dt><dd class="${active ? "is-active" : "is-idle"}">${tf(statusKey, active ? "Active" : "Idle")}</dd>`;
    }

    function buildColonyHoverHtml(cc, btn) {
      const name = cc.name || btn?.dataset.colonyName || "";
      const roleKey = String(cc.role_label_key || "").trim();
      const role = roleKey ? tf(roleKey, roleKey) : (btn?.dataset.colonyRole || "");
      const progress = cc.progress && typeof cc.progress === "object" ? cc.progress : {};
      const level = parseInt(progress.level, 10) || 0;
      const resources = Array.isArray(cc.resources) ? cc.resources : [];
      const metal = resources.find((row) => row.key === "metal");
      const prodLine = metal?.rate
        ? tf("command_map_hover_production", { rate: metal.rate }, metal.rate)
        : "";
      const fleetCount = (Array.isArray(cc.fleets) ? cc.fleets : []).filter(
        (row) => String(row.label_key || "") !== "command_center_fleet_ready"
      ).length;
      const fleetLine = fleetCount > 0
        ? tf("command_map_hover_fleets", { count: fleetCount }, `${fleetCount} fleets`)
        : "";
      const levelLine = level > 0
        ? tf("command_map_hover_level", { level }, `Level ${level}`)
        : "";
      return `<strong class="galaxy-command-map-colony-hover-name">${name}</strong>
        ${role ? `<span class="galaxy-command-map-colony-hover-role">${role}</span>` : ""}
        ${levelLine ? `<p class="galaxy-command-map-colony-hover-level">${levelLine}</p>` : ""}
        ${prodLine ? `<p class="galaxy-command-map-colony-hover-prod">${prodLine}</p>` : ""}
        <dl class="galaxy-command-map-colony-hover-queues">
          ${queueStatusLabel(cc, "build", "command_map_hover_queue_build")}
          ${queueStatusLabel(cc, "shipyard", "command_map_hover_queue_shipyard")}
          ${queueStatusLabel(cc, "research", "command_map_hover_queue_research")}
        </dl>
        ${fleetLine ? `<p class="galaxy-command-map-colony-hover-fleets">${fleetLine}</p>` : ""}`;
    }

    function buildForeignHoverHtml(ds) {
      const empireName = ds.empireName || ds.ownerUsername || "";
      const homeworldName = ds.homeworldName || "";
      const role = ds.empireRole || "";
      const owner = ds.ownerUsername || "";
      const colonies = ds.empireColonyCount || "";
      const influence = ds.empireInfluence || "";
      const colonyName = ds.foreignColonyName || "";
      const colonyRole = ds.foreignColonyRole || "";
      if (colonyName) {
        return `<strong class="galaxy-command-map-colony-hover-name">${colonyName}</strong>
          ${colonyRole ? `<span class="galaxy-command-map-colony-hover-role">${colonyRole}</span>` : ""}
          ${owner ? `<p class="galaxy-command-map-colony-hover-level">${owner}</p>` : ""}`;
      }
      return `<strong class="galaxy-command-map-colony-hover-name">${homeworldName || empireName}</strong>
        ${role ? `<span class="galaxy-command-map-colony-hover-role">${role}</span>` : ""}
        ${empireName && homeworldName ? `<p class="galaxy-command-map-colony-hover-level">${empireName}</p>` : ""}
        ${owner ? `<p class="galaxy-command-map-colony-hover-prod">${tf("world_map_inspector_player", "Spieler")}: ${owner}</p>` : ""}
        ${colonies !== "" ? `<p class="galaxy-command-map-colony-hover-fleets">${tf("world_map_inspector_colonies", "Kolonien")}: ${colonies}</p>` : ""}
        ${influence ? `<p class="galaxy-command-map-colony-hover-fleets">${tf("world_map_inspector_influence", "Einfluss")}: ${influence}%</p>` : ""}`;
    }

    const hideColonyHover = () => {
      hoverTooltip.hidden = true;
      hoverTooltip.classList.remove("galaxy-command-map-colony-hover-tooltip--foreign");
      graph.querySelectorAll("[data-colony-location-inspect].is-hover-summary, [data-foreign-empire-inspect].is-hover-summary, [data-foreign-colony-hover].is-hover-summary").forEach((btn) => {
        btn.classList.remove("is-hover-summary");
      });
    };

    const showForeignHover = (el, clientX, clientY) => {
      if (!el?.dataset) return;
      hoverTooltip.innerHTML = buildForeignHoverHtml(el.dataset);
      hoverTooltip.hidden = false;
      hoverTooltip.classList.add("galaxy-command-map-colony-hover-tooltip--foreign");
      graph.querySelectorAll("[data-foreign-empire-inspect], [data-foreign-colony-hover]").forEach((node) => {
        node.classList.toggle("is-hover-summary", node === el);
      });
      const pad = 12;
      const rect = hoverTooltip.getBoundingClientRect();
      let left = clientX + pad;
      let top = clientY + pad;
      if (left + rect.width > window.innerWidth - 8) left = clientX - rect.width - pad;
      if (top + rect.height > window.innerHeight - 8) top = clientY - rect.height - pad;
      hoverTooltip.style.left = `${Math.max(8, left)}px`;
      hoverTooltip.style.top = `${Math.max(8, top)}px`;
    };

    const showColonyHover = (btn, clientX, clientY) => {
      hoverTooltip.classList.remove("galaxy-command-map-colony-hover-tooltip--foreign");
      const planetId = String(btn.dataset.planetId || "");
      const source = graph.querySelector(`[data-colony-actions-source="${planetId}"]`);
      const cc = parseCommandCenter(source);
      if (!cc || !cc.panel_kind) return;
      hoverTooltip.innerHTML = buildColonyHoverHtml(cc, btn);
      hoverTooltip.hidden = false;
      graph.querySelectorAll("[data-colony-location-inspect].is-hover-summary").forEach((el) => {
        el.classList.remove("is-hover-summary");
      });
      btn.classList.add("is-hover-summary");
      const pad = 12;
      const rect = hoverTooltip.getBoundingClientRect();
      let left = clientX + pad;
      let top = clientY + pad;
      if (left + rect.width > window.innerWidth - 8) left = clientX - rect.width - pad;
      if (top + rect.height > window.innerHeight - 8) top = clientY - rect.height - pad;
      hoverTooltip.style.left = `${Math.max(8, left)}px`;
      hoverTooltip.style.top = `${Math.max(8, top)}px`;
    };

    const onColonyEnter = (e) => {
      const foreignEl = e.target.closest("[data-foreign-empire-inspect], [data-foreign-colony-hover]");
      if (foreignEl && graph.contains(foreignEl)) {
        showForeignHover(foreignEl, e.clientX, e.clientY);
        return;
      }
      const btn = e.target.closest("[data-colony-location-inspect]");
      if (!btn || !graph.contains(btn)) return;
      showColonyHover(btn, e.clientX, e.clientY);
    };

    const onColonyMove = (e) => {
      const foreignEl = e.target.closest("[data-foreign-empire-inspect], [data-foreign-colony-hover]");
      if (foreignEl && !hoverTooltip.hidden) {
        showForeignHover(foreignEl, e.clientX, e.clientY);
        return;
      }
      const btn = e.target.closest("[data-colony-location-inspect]");
      if (!btn || hoverTooltip.hidden) return;
      showColonyHover(btn, e.clientX, e.clientY);
    };

    const onColonyLeave = (e) => {
      const foreignEl = e.target.closest("[data-foreign-empire-inspect], [data-foreign-colony-hover]");
      if (foreignEl) {
        const related = e.relatedTarget;
        if (related && foreignEl.contains(related)) return;
        hideColonyHover();
        return;
      }
      const btn = e.target.closest("[data-colony-location-inspect]");
      if (!btn) return;
      const related = e.relatedTarget;
      if (related && btn.contains(related)) return;
      hideColonyHover();
    };

    applyColonyNodeActivity();
    applyEdgeRouteGlow();

    graph.addEventListener("pointerenter", onColonyEnter, true);
    graph.addEventListener("pointermove", onColonyMove, true);
    graph.addEventListener("pointerleave", onColonyLeave, true);
    graph.querySelector("[data-command-map-viewport]")?.addEventListener("pointerdown", hideColonyHover);

    GC.registerCleanup(() => {
      graph.removeEventListener("pointerenter", onColonyEnter, true);
      graph.removeEventListener("pointermove", onColonyMove, true);
      graph.removeEventListener("pointerleave", onColonyLeave, true);
      graph.querySelector("[data-command-map-viewport]")?.removeEventListener("pointerdown", hideColonyHover);
      hideColonyHover();
      graph.querySelectorAll("[data-colony-location-inspect]").forEach((btn) => {
        ACTIVITY_CLASS.forEach((cls) => btn.classList.remove(cls));
      });
      graph.querySelectorAll("[data-command-map-edge].is-route-active").forEach((edgeEl) => {
        edgeEl.classList.remove("is-route-active");
      });
    });
  }

  function initFirstDiscoveryMoment() {
    const graph = document.querySelector("[data-command-map-graph]");
    if (!graph) return;

    const LAUNCH_KEY_PREFIX = "gc_discovery_launch:";
    const REVEAL_KEY_PREFIX = "gc_discovery_reveal:";
    const BANNER_KEY = "gc_discovery_banner_shown";

    function sessionFlag(key) {
      try {
        return sessionStorage.getItem(key) === "1";
      } catch (_) {
        return false;
      }
    }

    function setSessionFlag(key) {
      try {
        sessionStorage.setItem(key, "1");
      } catch (_) {}
    }

    function nodeWorldCoords(btn) {
      const wx = parseFloat(btn.style.getPropertyValue("--world-x") || "0");
      const wy = parseFloat(btn.style.getPropertyValue("--world-y") || "0");
      return { wx, wy };
    }

    function focusNode(btn, scale, animate) {
      if (typeof GC.focusCommandMapWorld !== "function") return;
      const { wx, wy } = nodeWorldCoords(btn);
      if (!Number.isFinite(wx) || !Number.isFinite(wy)) return;
      GC.focusCommandMapWorld(wx, wy, { scale, animate });
    }

    const banner = graph.querySelector("[data-command-map-discovery-banner]");
    let revealNode = null;

    graph.querySelectorAll("[data-world-field-inspect]").forEach((btn) => {
      const status = String(btn.dataset.expeditionStatus || "idle");
      const worldKey = String(btn.dataset.strategicWorldKey || "").trim();
      if (!worldKey) return;

      if (status === "expedition_active" || status === "expedition_returning") {
        const launchKey = `${LAUNCH_KEY_PREFIX}${worldKey}`;
        if (!sessionFlag(launchKey)) {
          focusNode(btn, null, true);
          setSessionFlag(launchKey);
        }
      }

      if (status === "recently_reported") {
        btn.classList.add("is-discovery-reveal");
        revealNode = btn;
        const revealKey = `${REVEAL_KEY_PREFIX}${worldKey}`;
        if (!sessionFlag(revealKey)) {
          focusNode(btn, null, true);
          setSessionFlag(revealKey);
        }
        const autoModalKey = `gc_discovery_modal_auto:${worldKey}`;
        if (!sessionFlag(autoModalKey)) {
          const reducedMotion = (() => {
            try {
              return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            } catch (_) {
              return false;
            }
          })();
          const openDiscovery = () => {
            if (typeof GC.openWorldInspectorFromNode === "function") {
              GC.openWorldInspectorFromNode(btn);
            } else if (typeof GC.openWorldInspectorModal === "function") {
              const source = graph.querySelector(`[data-world-field-source="${worldKey}"]`);
              let cc = {};
              try {
                cc = JSON.parse(source?.getAttribute("data-command-center") || source?.dataset.commandCenter || "{}");
              } catch (_) {
                cc = {};
              }
              GC.openWorldInspectorModal({
                cc,
                btn,
                kind: cc.panel_kind || "expedition_site",
                discovery: true,
              });
            }
          };
          if (reducedMotion) openDiscovery();
          else requestAnimationFrame(openDiscovery);
          setSessionFlag(autoModalKey);
        }
      }
    });

    if (banner && revealNode && !sessionFlag(BANNER_KEY)) {
      banner.hidden = false;
      banner.className = "galaxy-command-map-discovery-banner is-visible";
      banner.innerHTML = `<strong>${tf("command_map_discovery_feed_title", "Neuer Kontakt entdeckt")}</strong><span>${tf("command_map_discovery_feed_subtitle", "Ein unbekannter Ort wurde im Sektor bestätigt.")}</span>`;
      setSessionFlag(BANNER_KEY);
      const bannerTimer = setTimeout(() => {
        banner.classList.remove("is-visible");
      }, 4200);
      GC.registerCleanup(() => {
        clearTimeout(bannerTimer);
        banner.hidden = true;
        banner.classList.remove("is-visible");
        graph.querySelectorAll("[data-world-field-inspect].is-discovery-reveal").forEach((btn) => {
          btn.classList.remove("is-discovery-reveal");
        });
      });
      return;
    }

    GC.registerCleanup(() => {
      graph.querySelectorAll("[data-world-field-inspect].is-discovery-reveal").forEach((btn) => {
        btn.classList.remove("is-discovery-reveal");
      });
    });
  }

  function logCommandMapTelemetry(event, detail = {}) {
    const cfg = window.GC_CLIENT_CONFIG || {};
    if (!cfg.command_map_dev_mode) return;
    const ev = String(event || "").trim().toLowerCase();
    if (!ev) return;
    const body = { event: ev, ...(detail && typeof detail === "object" ? detail : {}) };
    fetch("/api/command-map/telemetry", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(body),
    }).catch(() => {});
  }
  GC.logCommandMapTelemetry = logCommandMapTelemetry;

  function initGalaxy() {
    if (!document.querySelector(".galaxy-page")) return;
    const galaxyRoot = document.getElementById("galaxy-page-root");
    if (galaxyRoot?.dataset?.galaxyView === "command_map") {
      logCommandMapTelemetry("map_open");
    }
    bindGalaxyCommandMapSwitchOnce();
    initCommandMapViewport();
    initCommandMapFleetRoutes();
    initWorldInspectorModal();
    initCommandMapVisualPolish();
    initCommandMapLocationActions();
    initFirstDiscoveryMoment();
    initCommandMapSiteInspector();
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
    const seen = new Set();
    const top = (Array.isArray(payload?.top_players) ? payload.top_players : []).filter((row) => {
      const pid = Number(row.player_id) || 0;
      if (!pid || seen.has(pid)) return false;
      seen.add(pid);
      return true;
    });
    top.sort((a, b) => {
      const diff = rankingScoreValue(b, tabId) - rankingScoreValue(a, tabId);
      if (diff !== 0) return diff;
      return (Number(a.player_id) || 0) - (Number(b.player_id) || 0);
    });
    return top.map((row, idx) => ({
      ...row,
      display_rank: idx + 1,
      display_score: rankingScoreValue(row, tabId),
    }));
  }

  function rankingCurrentPlayerId(payload) {
    const pageEl = document.getElementById("ranking-page");
    const fromPage = Number(pageEl?.dataset?.playerId || 0);
    if (Number.isFinite(fromPage) && fromPage > 0) return fromPage;
    const fromPayload = Number(payload?.current_player?.player_id || 0);
    return Number.isFinite(fromPayload) && fromPayload > 0 ? fromPayload : 0;
  }

  function rankingCurrentRank(payload, tabId) {
    const pid = rankingCurrentPlayerId(payload);
    if (pid > 0) {
      const inTop = rankingSortedRows(payload, tabId).find((row) => Number(row.player_id) === pid);
      if (inTop) return Number(inTop.display_rank);
    }
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
  GC.modules.auction_house = initAuctionHouse;
  GC.modules.vote_center = initVoteCenter;
  GC.modules.referrals = initReferrals;
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
  GC.modules.hall_of_fame = function initHallOfFamePage() {
    const root = document.getElementById("hall-of-fame-page");
    if (!root) return;
    root.querySelectorAll("[data-hof-report]").forEach((btn) => {
      if (btn.dataset.hofBound === "1") return;
      btn.dataset.hofBound = "1";
      btn.addEventListener("click", () => {
        let meta = {};
        try {
          meta = JSON.parse(btn.getAttribute("data-hof-report") || "{}");
        } catch (_err) {
          meta = {};
        }
        if (!meta || typeof meta !== "object") return;
        if (typeof GC.openCombatReportModal !== "function") return;
        GC.openCombatReportModal({ category: "combat", metadata: meta });
      });
    });
  };
  GC.modules.records = function initRecordsPage() {
    const root = document.getElementById("records-page");
    if (!root) return;
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
    "a.gc-nav-link, a.gc-nav-sub-link, a.gc-bottom-nav-item, a.gc-nav-drawer-link, a.gc-hud-panel-messages, " +
    "a.gc-hud-panel-score, a.galaxy-view-tab, a.galaxy-nav-step, a.galaxy-range-item, " +
    "a.gc-command-center-action-btn, a.gc-command-center-fleet-link, a.gc-command-center-news-link, a.gc-command-center-activity-link, " +
    "a[data-gc-nav], a[data-command-action], " +
    "#gc-sidebar-nav a[href], " +
    "#gc-nav-trading-sub a.gc-nav-sub-link, #gc-nav-military-sub a.gc-nav-sub-link, #gc-nav-fleet-sub a.gc-nav-sub-link";

  function _tradingPageFromPath(path) {
    const p = String(path || "").replace(/\/$/, "") || "/";
    if (p.endsWith("/trader-hub")) return "trader_hub";
    if (p.endsWith("/inventory")) return "inventory";
    if (p.endsWith("/auction-house")) return "auction_house";
    if (p.endsWith("/vote-center")) return "vote_center";
    if (p.endsWith("/galactic-politics")) return "galactic_politics";
    if (p.endsWith("/skilltree")) return "skilltree";
    if (p.endsWith("/premium")) return "premium";
    return "";
  }

  function _fleetPageFromPath(path) {
    const p = String(path || "").replace(/\/$/, "") || "/";
    if (p.endsWith("/fleet")) return "fleet";
    if (p.endsWith("/logistics")) return "logistics";
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

    parent.classList.remove("active");
    sub.querySelectorAll("[data-trading-nav]").forEach((el) => {
      el.classList.toggle("active", !!tradingPage && el.dataset.tradingNav === tradingPage);
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

  function _syncFleetNavFromPath(path) {
    const fleetPage = _fleetPageFromPath(path);
    const parent = document.getElementById("gc-nav-fleet-parent");
    const sub = document.getElementById("gc-nav-fleet-sub");
    if (!parent || !sub) return;

    parent.classList.toggle("active", !!fleetPage);
    sub.querySelectorAll("[data-fleet-nav]").forEach((el) => {
      el.classList.toggle("active", el.dataset.fleetNav === fleetPage);
    });
    if (fleetPage) showFleetSubnav();
    else hideFleetSubnav();
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

  function _clearSidebarNavActive() {
    const sidebar = document.getElementById("gc-sidebar-nav");
    if (!sidebar) return;
    sidebar.querySelectorAll(".active").forEach((el) => el.classList.remove("active"));
  }

  function _pickSidebarHrefActive(path) {
    let best = null;
    let bestDepth = -1;
    document.querySelectorAll("#gc-sidebar-nav a.gc-nav-sub-link[href]").forEach((link) => {
      if (link.id === "gc-nav-trading-parent") return;
      const href = link.getAttribute("href");
      if (!href) return;
      let linkPath;
      try {
        linkPath = new URL(href, window.location.origin).pathname.replace(/\/$/, "") || "/";
      } catch (_) {
        return;
      }
      if (linkPath !== path) return;
      const depth = link.classList.contains("gc-nav-sub-link--nested") ? 2 : 1;
      if (depth > bestDepth) {
        bestDepth = depth;
        best = link;
      }
    });
    return best;
  }

  function _syncNavActive(url) {
    let urlObj;
    try {
      urlObj = new URL(url, window.location.origin);
    } catch (_) {
      return;
    }
    const path = urlObj.pathname.replace(/\/$/, "") || "/";
    const onBuildings = path.endsWith("/buildings");
    const tradingPage = _tradingPageFromPath(path);

    _clearSidebarNavActive();

    if (onBuildings) {
      const tab = urlObj.searchParams.get("tab") || "resources";
      syncBuildingSidebarTab(tab);
      const buildingsGroup = document.querySelector(".gc-nav-buildings-group");
      if (buildingsGroup) setNavGroupExpanded(buildingsGroup, true, false);
    } else {
      syncBuildingSidebarTab(null);
    }

    _syncTradingNavFromPath(path);

    if (!onBuildings && !tradingPage) {
      const activeLink = _pickSidebarHrefActive(path);
      if (activeLink) activeLink.classList.add("active");
    }

    syncBuildingsSubnavFromState();

    document.querySelectorAll(
      ".gc-bottom-nav-item, .gc-nav-drawer-link, a.gc-hud-panel-messages"
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

  const SUBNAV_PARENT_TOGGLE = {
    "gc-nav-trading-parent": {
      subId: "gc-nav-trading-sub",
      pages: TRADING_NAV_PAGES,
      show: showTradingSubnav,
      hide: hideTradingSubnav,
    },
  };

  function _subnavExpanded(sub) {
    return !!(sub && !sub.hidden && !sub.classList.contains("gc-nav-sub--collapsed"));
  }

  function tryHandleSubnavParentClick(link, e) {
    const cfg = SUBNAV_PARENT_TOGGLE[link.id];
    if (!cfg) return false;
    const page = GC.detectPage();
    if (!cfg.pages.has(page)) return false;
    e.preventDefault();
    const sub = document.getElementById(cfg.subId);
    if (_subnavExpanded(sub)) cfg.hide();
    else cfg.show();
    return true;
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
        const landscapeWebp = fetchedBody?.style?.getPropertyValue("--planet-landscape-webp");
        if (landscape && landscape.trim()) {
          document.body.classList.add("gc-has-planet-landscape");
          document.body.style.setProperty("--planet-landscape", landscape.trim());
          if (landscapeWebp && landscapeWebp.trim()) {
            document.body.style.setProperty("--planet-landscape-webp", landscapeWebp.trim());
          } else {
            document.body.style.removeProperty("--planet-landscape-webp");
          }
        } else {
          document.body.classList.remove("gc-has-planet-landscape");
          document.body.style.removeProperty("--planet-landscape");
          document.body.style.removeProperty("--planet-landscape-webp");
        }

        _syncNavActive(url);
        if (typeof GC.syncSidebarSticky === "function") GC.syncSidebarSticky();
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
      if (!link) return;
      if (tryHandleSubnavParentClick(link, e)) return;
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

  const GC_COMMANDER_NAME_MAX = 40;

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
    if (u.length > GC_COMMANDER_NAME_MAX) {
      markInvalid(username, true);
      setClientError(form, t("err_username_long", "Benutzername ist zu lang (max. 40 Zeichen)."));
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
    if (u.length > GC_COMMANDER_NAME_MAX) {
      markInvalid(username, true);
      setClientError(form, t("err_username_long", "Commander-Name ist zu lang (max. 40 Zeichen)."));
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

  function initMotdBanner() {
    const banner = document.querySelector("[data-motd-banner]");
    if (!banner) return;

    const toggle = banner.querySelector("[data-motd-toggle]");
    const dismiss = banner.querySelector("[data-motd-dismiss]");
    const textEl = banner.querySelector(".motd-banner-text");
    if (!toggle || !textEl) return;

    const syncExpandable = () => {
      const raw = (textEl.textContent || "").trim();
      const truncated = textEl.scrollWidth > textEl.clientWidth + 1;
      const expandable = truncated || raw.includes("\n") || raw.length > 72;
      banner.classList.toggle("motd-banner--expandable", expandable);
      if (!expandable) {
        banner.classList.remove("motd-banner--expanded");
        banner.classList.add("motd-banner--collapsed");
        toggle.setAttribute("aria-expanded", "false");
      }
    };

    const setExpanded = (expanded) => {
      banner.classList.toggle("motd-banner--expanded", expanded);
      banner.classList.toggle("motd-banner--collapsed", !expanded);
      toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    };

    const onToggle = () => {
      if (!banner.classList.contains("motd-banner--expandable")) return;
      setExpanded(!banner.classList.contains("motd-banner--expanded"));
    };

    const onDismiss = (event) => {
      event.stopPropagation();
      banner.hidden = true;
    };

    const onResize = () => syncExpandable();

    toggle.addEventListener("click", onToggle);
    if (dismiss) dismiss.addEventListener("click", onDismiss);
    window.addEventListener("resize", onResize);
    requestAnimationFrame(syncExpandable);

    GC.registerCleanup(() => {
      toggle.removeEventListener("click", onToggle);
      if (dismiss) dismiss.removeEventListener("click", onDismiss);
      window.removeEventListener("resize", onResize);
    });
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
        pauseVisualLoops();
        if (shouldRunGameLoop() && !_authLoopAborted) {
          GC.startPolling(lastHadActiveJob || lastHadActiveResearch || lastHadActiveShipyard);
        }
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
    if (!root || !target) return;
    const btn = root.querySelector(`[data-special-open-window="${target}"]`);
    if (btn) {
      btn.click();
      return;
    }

    const windows = root.querySelectorAll("[data-special-window]");
    const barButtons = root.querySelectorAll(".gc-special-bar [data-special-open-window]");
    let found = false;
    windows.forEach((win) => {
      const active = (win.dataset.specialWindow || "") === target;
      win.hidden = !active;
      if (active) found = true;
    });
    if (!found) return;
    root.classList.add("is-open");
    barButtons.forEach((b) => b.classList.remove("is-active"));
  }
  GC.openSpecialWindow = openSpecialWindow;

  function initCommunityHub() {
    const hub = document.querySelector("[data-community-hub]");
    if (!hub || hub.dataset.bound === "1") return;
    hub.dataset.bound = "1";

    const menu = hub.querySelector("[data-community-menu]");
    const toggle = hub.querySelector("[data-community-menu-toggle]");
    const discordLink = hub.querySelector("[data-community-discord-link]");
    const openItems = hub.querySelectorAll("[data-community-open]");

    const closeMenu = () => {
      if (!menu || !toggle) return;
      menu.hidden = true;
      hub.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    };

    const openMenu = () => {
      if (!menu || !toggle) return;
      menu.hidden = false;
      hub.classList.add("is-open");
      toggle.setAttribute("aria-expanded", "true");
    };

    if (toggle && menu) {
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        if (menu.hidden) openMenu();
        else closeMenu();
      });
    }

    if (discordLink) {
      discordLink.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        openMenu();
      });
    }

    openItems.forEach((item) => {
      item.addEventListener("click", () => {
        const target = item.dataset.communityOpen || "";
        closeMenu();
        if (!target) return;
        openSpecialWindow(target);
      });
    });

    document.addEventListener("click", (e) => {
      if (!hub.contains(e.target)) closeMenu();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMenu();
    });
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

  function syncSidebarSticky() {
    const header = document.querySelector(".gc-header-cmd");
    if (!header) return;
    const headerH = Math.ceil(header.getBoundingClientRect().height);
    document.documentElement.style.setProperty("--gc-sidebar-top", `${headerH + 8}px`);
    document.documentElement.style.setProperty("--gc-header-h", `${headerH}px`);
  }

  function initSidebarSticky() {
    if (!document.querySelector(".gc-sidebar-desktop")) return;
    let raf = 0;
    const schedule = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        syncSidebarSticky();
      });
    };
    syncSidebarSticky();
    window.addEventListener("resize", schedule, { passive: true });
    const header = document.querySelector(".gc-header-cmd");
    if (header && typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(schedule);
      ro.observe(header);
      GC.registerCleanup(() => ro.disconnect());
    }
    GC.syncSidebarSticky = syncSidebarSticky;
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

  /** GC-553 — DevTools snapshot: polling, loops, lifecycle counters. */
  GC.debugPerf = function debugPerf() {
    const lc = GC.pageLifecycle;
    const pol = GC.polling;
    return {
      page: typeof GC.detectPage === "function" ? GC.detectPage() : null,
      currentPage: GC.currentPage,
      gameLoop: shouldRunGameLoop(),
      visualLoops: shouldRunVisualLoops(),
      perfIdle: isPerfIdle(),
      tabHidden: document.hidden,
      authAborted: _authLoopAborted,
      polling: {
        running: pol.running,
        started: pol.started,
        inFlight: pol.inFlight,
        lastInterval: pol.lastInterval,
        intervalActive: pol.intervalActive,
        intervalIdle: pol.intervalIdle,
        intervalHidden: pol.intervalHidden,
        backoff: pol.backoff,
      },
      queues: {
        buildActive: lastHadActiveJob,
        researchActive: lastHadActiveResearch,
        shipyardActive: lastHadActiveShipyard,
        progressJobs: _hasActiveProgressJobs(),
      },
      loops: {
        resourceTicker: _resourceTickerId != null,
        progressTicker: _pageTimerLoopRunning,
        progressTickerScheduled: _progressTickerTimerId != null,
        voteCenterPoll: _voteCenterPollTimer != null,
        ambiencePersist: _ambiencePersistTimer != null,
      },
      timers: {
        movementCountdownRefresh: _movementCountdownRefreshTimer != null,
        productionCompletion: _productionCompletionTimer != null,
        queueTimerZero: _queueTimerZeroRefreshTimer != null,
        queueZeroRefreshKeys: _queueTimerZeroRefreshKeys.size,
        movementExpiryStateEntries: _movementCountdownExpiryState.size,
      },
      scope: {
        domPlanetId: getDomPlanetId(),
        activePlanetId: Number(GC.lastState?.active_planet_id || 0) || null,
        buildQueuePlanetId: Number(GC.lastState?.build_queue?.planet_id || 0) || null,
      },
      lifecycle: {
        rafIds: lc.rafIds.length,
        intervals: lc.intervals.length,
        timeouts: lc.timeouts.length,
        abortControllers: lc.abortControllers.length,
        cleanupFns: lc.cleanupFns.length,
        pjaxInFlight: !!GC.pjaxInFlight,
      },
      bodyClasses: {
        perfIdle: document.body?.classList.contains("gc-perf-idle"),
        tabHidden: document.body?.classList.contains("gc-tab-hidden"),
        reducedMotion: document.body?.classList.contains("gc-reduced-motion"),
      },
    };
  };
  GC.isPerfIdle = isPerfIdle;
  GC.shouldPatchGameStateModule = shouldPatchGameStateModule;
  GC.resolveFleetOriginPlanetId = resolveFleetOriginPlanetId;
  GC.resetQueueLiveStates = _resetQueueLiveStates;

  GC.debugTimers = function debugTimers() {
    const now = getTimerServerNow();
    const clientWall = Math.floor(Date.now() / 1000);
    const driftSec = Math.round((now - clientWall) * 10) / 10;
    const activePid = Number(GC.lastState?.active_planet_id || 0);
    const domPid = getDomPlanetId();
    const scopeOk = !activePid || !domPid || activePid === domPid;
    const lines = [
      `SERVER NOW (auth)  ${Math.floor(now)}`,
      `CLIENT WALL        ${clientWall}`,
      `DRIFT (s)          ${driftSec}`,
      "",
      `ACTIVE PLANET      ${activePid || "—"}`,
      `DOM PLANET         ${domPid || "—"}`,
      `SCOPE OK           ${scopeOk ? "yes" : "NO — mismatch"}`,
      `BUILD QUEUE PID    ${Number(GC.lastState?.build_queue?.planet_id || 0) || "—"}`,
      "",
    ];

    const bq = GC.lastState?.build_queue?.queue?.[0] || GC.lastState?.build_queue?.[0];
    if (bq) {
      const fin = resolveQueueJobFinishTime(bq);
      lines.push(
        "BUILDQ",
        `  job ${bq.id || bq.building_type || "?"}`,
        `  finish_at ${fin || "—"}`,
        `  remaining ${fin ? queueJobRemainingSeconds(fin, now, resolveQueueJobRemaining(bq)) : "—"}`,
        ""
      );
    }

    const rq = GC.lastState?.research?.active || GC.lastState?.research_queue?.[0];
    if (rq) {
      const fin = resolveQueueJobFinishTime(rq);
      lines.push(
        "RESEARCH",
        `  job ${rq.tech_key || rq.id || "?"}`,
        `  finish_at ${fin || "—"}`,
        `  remaining ${fin ? queueJobRemainingSeconds(fin, now, resolveQueueJobRemaining(rq)) : "—"}`,
        ""
      );
    }

    const fleetPage = document.getElementById("fleet-page");
    const fleets = fleetPage?._fleetRt?.data?.active_fleets || [];
    if (fleets.length) {
      lines.push("FLEET");
      fleets.slice(0, 6).forEach((mv) => {
        const endAt = parseTimerTarget(mv.countdown_at || mv.arrival_at || mv.return_at || 0);
        const rem = endAt ? movementRemainingSeconds(endAt, now, mv.remaining_seconds) : "—";
        lines.push(
          `  movement ${mv.id || mv.fleet_id || "?"}`,
          `  ${mv.phase || mv.status || "?"}`,
          `  arrival_at ${endAt || "—"}`,
          `  remaining ${rem}`
        );
      });
      lines.push("");
    }

    const perf = typeof GC.debugPerf === "function" ? GC.debugPerf() : {};
    lines.push(
      `rAF                ${perf.lifecycle?.rafIds ?? "?"}`,
      `Intervals          ${perf.lifecycle?.intervals ?? "?"}`,
      `Timeouts           ${perf.lifecycle?.timeouts ?? "?"}`,
      `Poll active        ${perf.polling?.running ?? "?"}`,
      `Progress ticker    ${perf.loops?.progressTicker ?? "?"}`
    );

    const report = lines.join("\n");
    console.info("[GC] debugTimers\n" + report);
    return { now, clientWall, driftSec, lines, perf };
  };

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
    initLanguageSwitcher();
    initRoleBasedSidebar();
    initGcPopoversOnce();
    initVisibilityPolling();
    initMotionPreferenceListener();
    initSimplePageAmbience();
    bootstrapPlanetLandscapeFromBoot();
    syncPerfBodyClasses();
    initMobileNav();
    initSpecialPanel();
    initCommunityHub();
    initSupportModule();
    initStickyResourceBar();
    initSidebarSticky();
    initPjax();
    initShipDetailOnce();
    initBuildingTechnicalDataOnce();
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
