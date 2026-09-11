(function () {
  "use strict";

  var GC = (window.GC = window.GC || {});
  if (GC._timekeeperBuildingInstantBootstrapRegistered) return;
  GC._timekeeperBuildingInstantBootstrapRegistered = true;

  function requestUrl(input) {
    if (typeof input === "string") return input;
    if (input && typeof input.url === "string") return input.url;
    return "";
  }

  function parsedUrl(input) {
    var raw = requestUrl(input);
    if (!raw) return null;
    try {
      return new URL(raw, window.location.href);
    } catch (_) {
      return null;
    }
  }

  function parseJsonBody(options) {
    if (!options || typeof options.body !== "string" || !options.body) return {};
    try {
      var parsed = JSON.parse(options.body);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function fmtInt(value) {
    if (typeof GC.fmtGameplayInteger === "function") return GC.fmtGameplayInteger(value);
    var raw = String(value == null ? "0" : value).trim();
    try {
      return BigInt(raw).toLocaleString(document.documentElement.lang || "de-DE");
    } catch (_) {
      return raw;
    }
  }

  function formatTranslation(key, fallback, values) {
    var text = typeof GC.t === "function" ? GC.t(key, fallback) : fallback;
    text = String(text || fallback || key);
    Object.keys(values || {}).forEach(function (name) {
      var value = String(values[name]);
      text = text.split("%(" + name + ")s").join(value);
      text = text.split("{" + name + "}").join(value);
    });
    return text;
  }

  function buildingKeysOnPage() {
    var seen = Object.create(null);
    var keys = [];
    document.querySelectorAll("[data-building-row]").forEach(function (card) {
      var key = String(card.getAttribute("data-building-row") || "").trim();
      if (!key || seen[key]) return;
      seen[key] = true;
      keys.push(key);
    });
    return keys;
  }

  function flattenBuildingRows(data) {
    var panel = data && (data.buildings_panel_delta || data.buildings_panel);
    var rows = [];
    if (!panel || typeof panel !== "object") return rows;
    Object.keys(panel).forEach(function (tab) {
      var tabRows = panel[tab];
      if (!Array.isArray(tabRows)) return;
      tabRows.forEach(function (row) {
        if (row && typeof row === "object") rows.push(row);
      });
    });
    return rows;
  }

  function patchLevelNow(row) {
    if (!row || row.level == null) return;
    var key = String(row.key || row.building_type || "").trim();
    if (!key) return;
    var card = document.querySelector('[data-building-row="' + key + '"]');
    if (card) {
      card.setAttribute("data-level", String(row.level));
      var badge = card.querySelector(".gc-bld-hero-level");
      if (badge) badge.textContent = fmtInt(row.level);
    }
    document.querySelectorAll('[data-bld-stage-prop="' + key + '"]').forEach(function (prop) {
      prop.setAttribute("data-level", String(row.level));
      var stageLevel = prop.querySelector("[data-bld-stage-level]");
      if (stageLevel) stageLevel.textContent = fmtInt(row.level);
    });
  }

  function ensureResearchAscensionButton(row) {
    if (!row || String(row.key || row.building_type || "") !== "research_lab") return false;
    patchLevelNow(row);

    var card = document.querySelector('[data-building-row="research_lab"]');
    if (!card) return false;

    var ready = Boolean(row.research_lab_ascension_ready);
    var nextRank = Number(row.research_lab_next_rank || 0);
    var roman = String(row.research_lab_next_roman || "").trim();
    if (!ready || nextRank <= 0 || !roman) return false;

    var button = card.querySelector("[data-research-lab-ascend]");
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "gc-btn gc-bld-evo-btn";
      button.setAttribute("data-research-lab-ascend", "");
      button.setAttribute("data-gc-timekeeper-ascension-live", "1");
      var costs = card.querySelector(".gc-bld-card-meta--costs-only");
      if (costs && costs.parentNode) costs.parentNode.insertBefore(button, costs);
      else card.appendChild(button);
    }

    var requiredLevel = Number(row.research_lab_ascension_required_level || row.level || 0);
    var speedPct = Number(row.research_lab_ascension_speed_bonus_pct || 0) + 2;
    var slots = Number(row.research_queue_capacity || 0) + 1;
    var lead = formatTranslation(
      "research_network_requires",
      "Ascension %(rank)s benötigt Forschungslabor %(level)s",
      { rank: roman, level: fmtInt(requiredLevel) }
    );
    var readyLabel = formatTranslation(
      "research_network_ready",
      "Ascension %(rank)s bereit",
      { rank: roman }
    );
    var actionLabel = formatTranslation(
      "research_network_ascend",
      "Ascension %(rank)s aktivieren",
      { rank: roman }
    );
    var benefit = formatTranslation(
      "research_network_rank_speed",
      "Ascension %(rank)s · Forschung +%(pct)s%%",
      { rank: roman, pct: speedPct }
    ) + " · " + formatTranslation(
      "research_network_capacity",
      "%(slots)s Forschungsplätze",
      { slots: slots }
    );
    var metalName = typeof GC.t === "function" ? GC.t("resource_metal", "Ferronit") : "Ferronit";
    var crystalName = typeof GC.t === "function" ? GC.t("resource_crystal", "Crytite") : "Crytite";

    button.hidden = false;
    button.disabled = false;
    button.removeAttribute("aria-disabled");
    button.dataset.ascLead = lead;
    button.dataset.ascRankLabel = readyLabel;
    button.dataset.ascActionLabel = actionLabel;
    button.dataset.ascTributeMetalLabel = metalName + " · " + fmtInt(row.research_lab_ascension_tribute_metal || 0);
    button.dataset.ascTributeCrystalLabel = crystalName + " · " + fmtInt(row.research_lab_ascension_tribute_crystal || 0);
    button.dataset.ascBenefit = benefit;
    button.textContent = actionLabel;

    card.dataset.gcResearchAscensionReady = "1";
    return true;
  }

  function applyBuildingDelta(data) {
    if (!data || typeof data !== "object" || data.ok === false) return false;
    var rows = flattenBuildingRows(data);
    rows.forEach(patchLevelNow);

    if (typeof GC.applyActionState === "function") {
      GC.applyActionState(data, "timekeeper_build_instant_delta");
    }

    rows.forEach(ensureResearchAscensionButton);
    if (typeof GC.normalizeBuildingAscensionCards === "function") {
      GC.normalizeBuildingAscensionCards();
    }
    return rows.length > 0;
  }

  function refreshVisibleBuildingDelta() {
    var keys = buildingKeysOnPage();
    if (!keys.length || typeof window.fetch !== "function") return Promise.resolve(false);

    var url = "/api/game-state?panel_delta_buildings=" + encodeURIComponent(keys.join(","));
    return window.fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
      cache: "no-store",
    }).then(function (response) {
      if (!response || !response.ok) throw new Error("building_delta_failed");
      return response.json();
    }).then(applyBuildingDelta).catch(function () {
      // Acceleration only. Existing canonical game-state polling remains fallback.
      return false;
    });
  }

  function isSuccessfulBuildTimekeeperApply(url, options, response) {
    if (!response || typeof response !== "object" || response.ok === false) return false;
    var parsed = parsedUrl(url);
    var path = parsed ? parsed.pathname : requestUrl(url);
    if (path !== "/api/timekeeper/apply") return false;
    var body = parseJsonBody(options);
    var domain = String(body.domain || response.domain || "").trim().toLowerCase();
    if (domain !== "build" && domain !== "building" && domain !== "buildings") return false;
    return Number(response.seconds_applied || (response.state && response.state.seconds_applied) || 0) > 0;
  }

  function install() {
    GC = window.GC = window.GC || {};
    if (GC._timekeeperBuildingInstantInstalled) return true;
    if (typeof GC.fetchGameAction !== "function") return false;

    var originalFetchGameAction = GC.fetchGameAction;
    GC.fetchGameAction = async function timekeeperBuildingInstantFetchGameAction(url, options) {
      var response = await originalFetchGameAction.call(this, url, options);
      try {
        if (isSuccessfulBuildTimekeeperApply(url, options, response)) {
          // Do not make the mutation wait for a fat panel rebuild. The committed
          // Timekeeper response returns first; then one tiny selected-card delta
          // repaints level/queue/action state and can surface Research Ascension.
          void refreshVisibleBuildingDelta();
        }
      } catch (_) {
        // Response-first acceleration is fail-open.
      }
      return response;
    };

    GC._timekeeperBuildingInstantInstalled = true;
    GC.refreshVisibleBuildingDeltaAfterTimekeeper = refreshVisibleBuildingDelta;
    GC.patchResearchLabAscensionFromPanelRow = ensureResearchAscensionButton;
    return true;
  }

  function installWhenReady() {
    if (install()) return;
    var attempts = 0;
    var timer = window.setInterval(function () {
      attempts += 1;
      if (install() || attempts >= 100) window.clearInterval(timer);
    }, 50);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installWhenReady, { once: true });
  } else {
    installWhenReady();
  }
})();
