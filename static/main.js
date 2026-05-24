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
        state.raf = requestAnimationFrame(tick);
        _numAnim.set(el, state);
      } else {
        el.textContent = fmt(state.target);
        _numAnim.delete(el);
      }
    }

    state.raf = requestAnimationFrame(tick);
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
      _deltaTimerOv = setTimeout(() => deltaEl.classList.remove("show"), 1200);
    } else {
      if (_deltaTimerHud) clearTimeout(_deltaTimerHud);
      _deltaTimerHud = setTimeout(() => deltaEl.classList.remove("show"), 1200);
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
    // set by renderBuildQueue() when there is an active job
    active: {
      finishTime: 0,   // epoch seconds
      totalSeconds: 0, // seconds
    },
  };

  // =========================
  // Build-Queue panel render
  // - minimal re-render via signature
  // - BUT live progress runs independently
  // =========================
  let _lastQueueSignature = "";

  function _queueSignature(queueList, summary) {
    try {
      const first = queueList && queueList[0] ? queueList[0] : null;
      const a = summary?.count ?? (queueList?.length ?? 0);
      // IMPORTANT: do NOT include "remaining" here, otherwise we re-render every poll second
      const b = first ? `${first.building_type}:${first.target_level}:${first.finish_time || 0}` : "none";
      return `${a}|${b}`;
    } catch (_) {
      return "";
    }
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
    if (sig === _lastQueueSignature) return;
    _lastQueueSignature = sig;

    const title = t("build_queue_title", "Bauschleife");

    // empty state
    if (!queueList || queueList.length === 0) {
      const none =
        t("build_queue_none", null) ||
        t("build_queue_empty", null) ||
        t("build_queue_no_active", null) ||
        "Keine Bauaufträge aktiv.";

      root.innerHTML = `
        <div class="build-queue-panel">
          <div class="build-queue-header">
            <h3 class="section-subtitle">${title}</h3>
          </div>
          <div class="build-queue-empty">${none}</div>
        </div>
      `;
      return;
    }

    const count = summary?.count ?? queueList.length;

    const firstEta =
      typeof summary?.first_finish_in !== "undefined"
        ? formatEta(summary.first_finish_in)
        : formatEta(first?.remaining ?? 0);

    const hint = tf(
      "build_queue_hint",
      { count, eta: firstEta },
      `${count} · Nächste Fertigstellung in: ${firstEta}`
    );

    let html = `
      <div class="build-queue-panel">
        <div class="build-queue-header">
          <h3 class="section-subtitle">${title}</h3>
          <div class="build-queue-meta" id="build-queue-hint-live">${hint}</div>
        </div>
    `;

    queueList.forEach((job, index) => {
      const bType = job.building_type;
      const i18nKey = "building_" + bType;
      const fallbackName = bType || i18nKey;

      const name =
        BUILDING_LABELS[bType] ||
        (job.label_key ? t(job.label_key, fallbackName) : t(i18nKey, fallbackName));

      const remaining = parseInt(job.remaining, 10) || 0;

      // total: prefer API's total; otherwise use remaining+1 as safe fallback
      const totalRaw = job.total || job.total_seconds || 0;
      const total = Math.max(1, parseInt(totalRaw, 10) || (remaining + 1));
      const pct = Math.max(0, Math.min(100, 100 * (1 - remaining / total)));

      if (index === 0) {
        const finishTime = Number(job.finish_time || 0);

        html += `
          <div class="build-job build-job-active"
               data-finish-time="${finishTime}"
               data-total="${total}">
            <div class="job-header">
              <span class="job-name">${name} → ${t("label_level_short", "L")} ${job.target_level}</span>
              <span class="job-time" id="build-eta-live">${formatEta(remaining)}</span>
            </div>
            <div class="build-bar build-bar-large">
              <div class="build-bar-fill" id="build-bar-fill-live" style="width:${pct}%"
                   role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
            </div>
          </div>`;
      } else {
        html += `
          <div class="build-job">
            <div class="job-header">
              <span class="job-name">${name} → ${t("label_level_short", "L")} ${job.target_level}</span>
              <span class="job-time">${t("status_in_queue", "In Warteschlange")}</span>
            </div>
            <div class="build-bar build-bar-large">
              <div class="build-bar-fill" style="width:0%" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
            </div>
          </div>`;
      }
    });

    html += `</div>`;
    root.innerHTML = html;
  }

  // LIVE ticker for build queue (runs every second via schedulePolling tick)
  function updateBuildQueueLive() {
    const active = document.querySelector(".build-job.build-job-active");
    if (!active) return;

    const finishTime = Number(active.getAttribute("data-finish-time") || 0);
    const total = Math.max(1, Number(active.getAttribute("data-total") || 1));

    if (!finishTime) return;

    const serverNow = getApproxServerNow();
    if (!serverNow) return;

    const remaining = Math.max(0, Math.ceil(finishTime - serverNow));
    const pct = Math.max(0, Math.min(100, 100 * (1 - remaining / total)));

    const etaEl = document.getElementById("build-eta-live");
    const fillEl = document.getElementById("build-bar-fill-live");

    if (etaEl) _setIfChanged(etaEl, formatEta(remaining));
    if (fillEl) {
      fillEl.style.width = `${pct}%`;
      fillEl.setAttribute("aria-valuenow", String(Math.round(pct)));
    }

    // optional: keep header hint in sync when serverNow ticks
    const hintEl = document.getElementById("build-queue-hint-live");
    if (hintEl) {
      // We only rewrite ETA part safely using tf on the fly, but we don't know count here.
      // If you want fully correct, rely on polling data; for now keep it stable.
      // (No-op.)
    }
  }

  // =========================
  // Polling control
  // =========================
  const POLL = {
    timer: 0,
    intervalActive: 1000,
    intervalIdle: 4000,
    intervalHidden: 12000,
    lastInterval: 0,
    backoff: 0,
    inFlight: false,
    abort: null,
  };

  let lastHadActiveJob = false;
  let lastHadActiveResearch = false;
  let reloadTriggered = false;
  let researchReloadTriggered = false;

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
  // Research progressbar updater (drift-safe)
  // =========================
  function updateResearchProgressBar() {
    const outer = document.querySelector(".research-progress-outer");
    const fill = document.getElementById("research-progress-fill");
    const countdown = document.getElementById("research-countdown");
    if (!outer || !fill || !countdown) return;

    const total = parseInt(outer.dataset.totalSeconds || "0", 10);
    if (!total || total <= 0) return;

    const finishAt = parseInt(outer.dataset.finishAt || "0", 10);
    if (finishAt > 0) {
      const serverNow = getApproxServerNow();
      if (serverNow > 0) {
        const remaining = Math.max(0, Math.floor(finishAt - serverNow));
        _setIfChanged(countdown, formatEta(remaining));
        const done = Math.max(0, Math.min(1, 1 - remaining / total));
        fill.style.width = `${Math.round(done * 100)}%`;
        return;
      }
    }

    // fallback: parse existing text
    const remaining = parseDurationToSeconds(countdown.textContent);
    if (!Number.isFinite(remaining)) return;

    const done = Math.max(0, Math.min(1, 1 - remaining / total));
    fill.style.width = `${Math.round(done * 100)}%`;
  }

  // =========================
  // Status polling
  // =========================
  async function fetchStatusAndUpdate() {
    if (POLL.inFlight) return;

    const path = window.location.pathname || "";
    const isBuildingsPage = path.endsWith("/buildings");
    const isResearchPage = path.endsWith("/research");
    const isOverviewPage = path.endsWith("/overview") || path === "/" || path === "";

    POLL.inFlight = true;

    try {
      if (POLL.abort) POLL.abort.abort();
    } catch (_) {}

    const ctrl = new AbortController();
    POLL.abort = ctrl;

    try {
      const res = await fetch("/api/status", { cache: "no-store", signal: ctrl.signal });
      if (!res.ok) throw new Error(`status ${res.status}`);

      const data = await res.json();
      POLL.backoff = 0;

      if (data.server_time) setServerTime(data.server_time);

      const p = data.player || {};
      const buildings = data.buildings || {};
      const buildQueueRaw = data.build_queue || null;
      const prod = data.production_per_hour || {};
      const research = data.research || {};
      const activeResearch = research.active || null;
      const storage = data.storage || {};

      const storageMetal = Math.floor(Number(storage.metal || 0));
      const storageCrystal = Math.floor(Number(storage.crystal || 0));

      const metal = Math.floor(Number(p.metal || 0));
      const crystal = Math.floor(Number(p.crystal || 0));
      const used = Math.floor(Number(p.energy_used || 0));
      const total = Math.floor(Number(p.energy_total || 0));

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

      // Effizienz
      const ovEff = document.getElementById("overview-efficiency");
      if (ovEff) {
        let ratio = 1.0;
        if (total <= 0) ratio = 0.0;
        else if (used > total) ratio = total / Math.max(1, used);
        const pct = Math.round(ratio * 100);
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
        let statusText = t("status_ready", "Bereit");
        let btnLabel = queueActive ? t("action_queue_upgrade", "Upgrade (anreihen)") : t("action_upgrade", "Upgrade");

        if (queueActive && activeJob && activeJob.building_type === key) {
          statusText = `${t("status_building", "Im Bau")} (${formatEta(activeJob.remaining)})`;
        }

        if (cfg.statusId) setText(cfg.statusId, statusText);

        const btn = document.getElementById(cfg.btnId);
        if (btn && btn.textContent !== btnLabel) btn.textContent = btnLabel;
      });

      renderBuildQueue(buildQueueRaw);

      // Soft-Reload Buildings
      const hasActiveBuild = !!activeJob;
      if (!reloadTriggered && isBuildingsPage && lastHadActiveJob && !hasActiveBuild) {
        reloadTriggered = true;
        setTimeout(() => window.location.reload(), 250);
      }
      lastHadActiveJob = hasActiveBuild;

      // --- Live-Update Forschung (from API) ---
      if (activeResearch) {
        const remaining = Math.max(0, parseInt(activeResearch.remaining, 10) || 0);
        const totalSec = Math.max(
          1,
          parseInt(activeResearch.total_seconds, 10) ||
            parseInt(activeResearch.total, 10) ||
            remaining + 1
        );

        const cdEl = document.getElementById("research-countdown");
        const barEl = document.getElementById("research-progress-fill");

        const ovCdEl = document.getElementById("research-remaining");
        const ovBarEl = document.getElementById("research-bar-fill");
        const totalLabel = document.getElementById("research-total");

        if (cdEl) _setIfChanged(cdEl, formatEta(remaining));
        if (ovCdEl) _setIfChanged(ovCdEl, `${remaining}s`);
        if (totalLabel) _setIfChanged(totalLabel, `${totalSec}s`);

        const pct = Math.max(0, Math.min(100, 100 * (1 - remaining / totalSec)));
        if (barEl) barEl.style.width = `${pct}%`;
        if (ovBarEl) ovBarEl.style.width = `${pct}%`;
      }

      // Soft-Reload Research/Overview
      const hasActiveResearchNow = !!activeResearch;
      if (!researchReloadTriggered && (isResearchPage || isOverviewPage) && lastHadActiveResearch && !hasActiveResearchNow) {
        researchReloadTriggered = true;
        setTimeout(() => window.location.reload(), 250);
      }
      lastHadActiveResearch = hasActiveResearchNow;

      schedulePolling(hasActiveBuild || hasActiveResearchNow);

    } catch (err) {
      if (err?.name !== "AbortError") console.error("Status-Update fehlgeschlagen:", err);
      POLL.backoff = Math.min(60000, (POLL.backoff || 2000) * 1.6);
      schedulePolling(lastHadActiveJob || lastHadActiveResearch, true);
    } finally {
      POLL.inFlight = false;
    }
  }

  // =========================
  // Poll loop (setTimeout) – no overlap, adaptive interval
  // =========================
  function schedulePolling(anyActive, isError = false) {
    const hidden = document.hidden === true;

    let next = POLL.intervalIdle;
    if (anyActive) next = POLL.intervalActive;
    if (hidden) next = POLL.intervalHidden;
    if (isError && POLL.backoff) next = Math.max(next, POLL.backoff);

    if (next === POLL.lastInterval && POLL.timer) return;

    POLL.lastInterval = next;
    if (POLL.timer) clearTimeout(POLL.timer);

    const tick = () => {
      // fetch (may be intervalActive = 1s, but fine)
      fetchStatusAndUpdate();

      // live UI tick (every second)
      updateResearchProgressBar();
      updateBuildQueueLive();

      POLL.timer = setTimeout(tick, POLL.lastInterval);
    };

    POLL.timer = setTimeout(tick, next);
  }

  // =========================
  // Tabs (Buildings) + keyboard nav
  // =========================
  function initTabs() {
    const tablist = document.querySelector(".building-tabs");
    if (!tablist) return;

    const tabBtns = Array.from(tablist.querySelectorAll(".tab-btn"));
    const tabContents = Array.from(document.querySelectorAll(".tab-content[data-tab]"));
    if (!tabBtns.length || !tabContents.length) return;

    function activateTab(btn, focus = true) {
      const targetTab = btn.dataset.tab;

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

    tabBtns.forEach((btn) => {
      btn.addEventListener("click", (e) => {
        if (btn.tagName === "A") e.preventDefault();
        activateTab(btn, true);
      });
    });

    if (tablist.getAttribute("role") === "tablist") {
      tablist.addEventListener("keydown", (e) => {
        const current = document.activeElement;
        if (!current || !current.classList.contains("tab-btn")) return;

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
          activateTab(current, true);
          e.preventDefault();
          return;
        } else return;

        tabBtns[nextIdx].focus();
      });
    }

    const activeBtn = tabBtns.find((b) => b.classList.contains("active")) || tabBtns[0];
    activateTab(activeBtn, false);
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
  // Upgrade debounce
  // =========================
  function initUpgradeDebounce() {
    document.addEventListener("click", (e) => {
      const el = e.target.closest("a.btn-upgrade, button.btn-upgrade");
      if (!el) return;

      if (el.dataset.debouncing === "1") {
        e.preventDefault();
        return;
      }

      el.dataset.debouncing = "1";
      setTimeout(() => { el.dataset.debouncing = "0"; }, 450);
    });
  }

  // =========================
  // Flash autohide
  // =========================
  function initFlashAutohide() {
    setTimeout(() => {
      const box = document.getElementById("messages");
      if (!box) return;
      box.style.transition = "opacity 0.4s ease";
      box.style.opacity = "0";
      setTimeout(() => box.remove(), 450);
    }, 4000);
  }

  // =========================
  // Visibility listener
  // =========================
  function initVisibilityPolling() {
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        fetchStatusAndUpdate();
        updateResearchProgressBar();
        updateBuildQueueLive();
      }
      schedulePolling(lastHadActiveJob || lastHadActiveResearch);
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
  // Boot
  // =========================
  document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initForms();
    initSkipLink();
    initUpgradeDebounce();
    initFlashAutohide();
    initVisibilityPolling();
    initMobileNav();
    initStickyResourceBar();

    fetchStatusAndUpdate();
    updateResearchProgressBar();
    updateBuildQueueLive();
    schedulePolling(false);
  });
})();
