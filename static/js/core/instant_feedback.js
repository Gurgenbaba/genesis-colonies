(function () {
  "use strict";

  var GC = (window.GC = window.GC || {});
  if (GC._instantFeedbackBootstrapRegistered) return;
  GC._instantFeedbackBootstrapRegistered = true;

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
    if (typeof GC.fmtGameplayInteger === "function") {
      return GC.fmtGameplayInteger(value);
    }
    var raw = String(value == null ? "0" : value).trim();
    try {
      return BigInt(raw).toLocaleString(document.documentElement.lang || "de-DE");
    } catch (_) {
      return raw;
    }
  }

  function buildingLevels(buildings) {
    var out = Object.create(null);
    if (Array.isArray(buildings)) {
      buildings.forEach(function (row) {
        if (!row || typeof row !== "object") return;
        var key = String(row.key || row.building_type || row.type || "").trim();
        if (!key || row.level == null) return;
        out[key] = row.level;
      });
      return out;
    }
    if (!buildings || typeof buildings !== "object") return out;
    Object.keys(buildings).forEach(function (key) {
      var row = buildings[key];
      var level = row && typeof row === "object" && row.level != null ? row.level : row;
      if (level == null || level === "") return;
      out[String(key)] = level;
    });
    return out;
  }

  /**
   * Planet switch responses already contain the authoritative, deliberately slim
   * building-level map. Paint those levels in the same tick instead of leaving the
   * previous colony visible until include_panel=1 finishes in the background.
   * Costs/requirements stay server-owned and are still reconciled by the canonical
   * panel refresh; this helper performs no gameplay math.
   */
  function patchPlanetBuildingLevels(state) {
    if (!state || typeof state !== "object" || !state.buildings) return 0;
    if (!document.querySelector("[data-building-row], [data-bld-stage-prop]")) return 0;

    var levels = buildingLevels(state.buildings);
    var patched = 0;

    document.querySelectorAll("[data-building-row]").forEach(function (row) {
      var key = String(row.getAttribute("data-building-row") || "");
      if (!Object.prototype.hasOwnProperty.call(levels, key)) return;
      var level = levels[key];
      row.setAttribute("data-level", String(level));
      var badge = row.querySelector(".gc-bld-hero-level");
      if (badge) badge.textContent = fmtInt(level);
      patched += 1;
    });

    document.querySelectorAll("[data-bld-stage-prop]").forEach(function (prop) {
      var key = String(prop.getAttribute("data-bld-stage-prop") || prop.getAttribute("data-building") || "");
      if (!Object.prototype.hasOwnProperty.call(levels, key)) return;
      var level = levels[key];
      prop.setAttribute("data-level", String(level));
      var badge = prop.querySelector("[data-bld-stage-level]");
      if (badge) badge.textContent = fmtInt(level);
      patched += 1;
    });

    var page = document.getElementById("buildings-page");
    if (page && patched) page.dataset.gcInstantPlanetLevels = "1";
    return patched;
  }

  function worldBossCard(eventId) {
    var id = Number(eventId || 0);
    if (id > 0) {
      var cards = document.querySelectorAll("[data-wb-event-id]");
      for (var i = 0; i < cards.length; i += 1) {
        if (Number(cards[i].getAttribute("data-wb-event-id") || 0) === id) return cards[i];
      }
    }
    var activeCards = document.querySelectorAll("#world-boss-page [data-wb-event-id]");
    return activeCards.length === 1 ? activeCards[0] : null;
  }

  function currentCommanderIdentity() {
    var linked = document.querySelector(".gc-user-name a");
    var fallback = linked || document.querySelector(".gc-user-name");
    return {
      node: fallback,
      name: fallback ? String(fallback.textContent || "").trim() : "",
      playerId: Number(document.body && document.body.dataset ? document.body.dataset.playerId || 0 : 0),
    };
  }

  function tr(key) {
    return typeof GC.t === "function" ? GC.t(key, key) : key;
  }

  function ensureParticipantTable(wrapper) {
    if (!wrapper) return null;
    var table = wrapper.querySelector("table.gc-ranking-table");
    if (table) return table;

    var empty = wrapper.querySelector("p.hint");
    if (empty) empty.hidden = true;

    table = document.createElement("table");
    table.className = "gc-ranking-table";
    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    ["wb_col_rank", "wb_col_player", "wb_col_alliance", "wb_col_damage", "wb_col_waves"].forEach(function (key) {
      var th = document.createElement("th");
      th.textContent = tr(key);
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    table.appendChild(document.createElement("tbody"));
    wrapper.appendChild(table);
    return table;
  }

  function rowRank(row) {
    if (!row || !row.children || !row.children.length) return Number.MAX_SAFE_INTEGER;
    var raw = String(row.children[0].textContent || "").replace(/[^0-9]/g, "");
    var rank = Number(raw || 0);
    return rank > 0 ? rank : Number.MAX_SAFE_INTEGER;
  }

  function ensureSelfParticipantRow(tbody, identity, rank) {
    if (!tbody) return null;
    var row = tbody.querySelector("tr[data-gc-live-self-contrib]");
    if (!row && identity.name) {
      Array.prototype.some.call(tbody.querySelectorAll("tr"), function (candidate) {
        var cells = candidate.children || [];
        if (cells.length > 1 && String(cells[1].textContent || "").trim() === identity.name) {
          row = candidate;
          return true;
        }
        return false;
      });
    }

    if (!row) {
      row = document.createElement("tr");
      for (var i = 0; i < 5; i += 1) row.appendChild(document.createElement("td"));
      if (identity.node) row.children[1].appendChild(identity.node.cloneNode(true));
      else row.children[1].textContent = identity.name;
      row.children[2].textContent = "—";
    }
    row.setAttribute("data-gc-live-self-contrib", "1");
    if (identity.playerId > 0) row.setAttribute("data-player-id", String(identity.playerId));

    var before = null;
    Array.prototype.some.call(tbody.querySelectorAll("tr"), function (candidate) {
      if (candidate === row) return false;
      if (rowRank(candidate) > rank) {
        before = candidate;
        return true;
      }
      return false;
    });
    if (before) tbody.insertBefore(row, before);
    else if (row.parentNode !== tbody || row !== tbody.lastElementChild) tbody.appendChild(row);
    return row;
  }

  /**
   * Attack/live payloads already carry the current player's authoritative damage,
   * rank, waves and participant count. Mirror that into the participant board now;
   * do not wait for a later full World-Boss page render.
   */
  function patchWorldBossParticipant(eventId, player) {
    if (!player || typeof player !== "object") return false;
    var contribution = player.contribution && typeof player.contribution === "object" ? player.contribution : {};
    var damage = player.total_damage != null ? player.total_damage : contribution.damage;
    var waves = player.waves != null ? player.waves : contribution.waves;
    var rank = Number(player.rank != null ? player.rank : contribution.rank || 0);
    var totalPlayers = Number(player.total_players != null ? player.total_players : contribution.total_players || 0);
    if (damage == null && waves == null && rank <= 0) return false;

    var card = worldBossCard(eventId);
    if (!card) return false;
    var details = card.querySelector(".gc-world-boss-board-details");
    if (!details) return false;
    var wrapper = details.querySelector(".gc-world-boss-board-panels .ranking-table-wrapper");
    if (!wrapper) return false;
    var table = ensureParticipantTable(wrapper);
    var tbody = table && table.querySelector("tbody");
    if (!tbody) return false;

    var identity = currentCommanderIdentity();
    var row = ensureSelfParticipantRow(tbody, identity, rank > 0 ? rank : Number.MAX_SAFE_INTEGER);
    if (!row || row.children.length < 5) return false;
    row.children[0].textContent = rank > 0 ? "#" + String(rank) : "—";
    if (damage != null) row.children[3].textContent = fmtInt(damage);
    if (waves != null) row.children[4].textContent = fmtInt(waves);
    row.classList.toggle("gc-world-boss-board-more", rank > 3);

    if (totalPlayers > 0) {
      var summary = details.querySelector("summary");
      var count = summary && summary.querySelector(".hint.gc-mono");
      if (!count && summary) {
        count = document.createElement("span");
        count.className = "hint gc-mono";
        summary.appendChild(document.createTextNode(" "));
        summary.appendChild(count);
      }
      if (count) count.textContent = "(" + fmtInt(totalPlayers) + ")";
    }

    card.dataset.gcInstantParticipant = "1";
    return true;
  }

  function patchWorldBossLivePayload(payload) {
    if (!payload || typeof payload !== "object") return;
    if (Array.isArray(payload.events)) {
      payload.events.forEach(function (entry) {
        if (!entry || typeof entry !== "object") return;
        var event = entry.event || entry;
        var player = entry.player || null;
        if (player) patchWorldBossParticipant(event && event.id, player);
      });
      return;
    }
    var event = payload.event || null;
    if (event && payload.player) patchWorldBossParticipant(event.id, payload.player);
  }

  function applyMessageNotificationSummary(data) {
    if (!data || typeof data !== "object" || data.ok === false) return false;
    if (data.unread_messages_count == null) return false;
    var n = Math.max(0, Number(data.unread_messages_count) || 0);
    var localCount = document.getElementById("messages-unread-count");
    if (localCount) localCount.textContent = String(n);
    if (typeof GC.mergeLastState === "function") {
      GC.mergeLastState({ unread_messages_count: n }, "messages_sync");
    }
    if (typeof GC.setMessagesUnreadPollBaseline === "function") {
      GC.setMessagesUnreadPollBaseline(n);
    }
    return true;
  }

  /**
   * Messages only asks for refreshGameState("messages_sync") to reconcile the
   * unread badge. Route that reason through the existing tiny, server-authoritative
   * notification heartbeat instead of rebuilding the complete game-state payload.
   * Any malformed/failed summary falls back to the original canonical refresh.
   */
  function installMessagesSyncFastPath() {
    if (typeof GC.refreshGameState !== "function") return;
    if (GC.refreshGameState.__gcMessagesSyncFastPath) return;
    var originalRefreshGameState = GC.refreshGameState;
    var wrappedRefreshGameState = function instantFeedbackRefreshGameState(reason) {
      if (String(reason || "") !== "messages_sync") {
        return originalRefreshGameState.apply(this, arguments);
      }

      var self = this;
      var args = arguments;
      if (typeof window.fetch !== "function") {
        return originalRefreshGameState.apply(self, args);
      }

      return window.fetch("/api/notifications/summary", {
        method: "GET",
        headers: {
          Accept: "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        credentials: "same-origin",
        cache: "no-store",
      }).then(function (response) {
        if (!response || !response.ok) throw new Error("notification_summary_failed");
        return response.json();
      }).then(function (data) {
        if (!applyMessageNotificationSummary(data)) throw new Error("notification_summary_invalid");
        return data;
      }).catch(function () {
        return originalRefreshGameState.apply(self, args);
      });
    };
    wrappedRefreshGameState.__gcMessagesSyncFastPath = true;
    wrappedRefreshGameState.__gcPreviousRefreshGameState = originalRefreshGameState;
    GC.refreshGameState = wrappedRefreshGameState;
  }

  function applyActionFeedback(url, options, response) {
    if (!response || typeof response !== "object" || response.ok === false) return;
    var parsed = parsedUrl(url);
    var path = parsed ? parsed.pathname : requestUrl(url);

    if (path === "/api/planets/active") {
      patchPlanetBuildingLevels(response.state || (response.data && response.data.state));
      return;
    }

    if (path.indexOf("/api/world-boss/") === 0 && response.player && (response.attack || response.player.contribution)) {
      var body = parseJsonBody(options);
      var eventId = body.event_id || response.event_id || (response.boss && (response.boss.event_id || response.boss.id));
      patchWorldBossParticipant(eventId, response.player);
    }
  }

  function install() {
    GC = window.GC = window.GC || {};
    if (GC._instantFeedbackInstalled || typeof GC.fetchGameAction !== "function") return;

    var originalFetchGameAction = GC.fetchGameAction;
    GC.fetchGameAction = async function instantFeedbackFetchGameAction(url, options) {
      var response = await originalFetchGameAction.call(this, url, options);
      try {
        applyActionFeedback(url, options, response);
      } catch (_) {
        // UI acceleration is fail-open; canonical state remains authoritative.
      }
      return response;
    };

    installMessagesSyncFastPath();

    var originalFetch = typeof window.fetch === "function" ? window.fetch.bind(window) : null;
    if (originalFetch && !window.fetch.__gcInstantFeedbackWrapped) {
      var wrappedFetch = function instantFeedbackFetch(input, init) {
        var parsed = parsedUrl(input);
        var isWorldBossLive = Boolean(
          parsed &&
          parsed.pathname === "/api/world-boss" &&
          parsed.searchParams.get("live") === "1"
        );
        var promise = originalFetch(input, init);
        if (!isWorldBossLive) return promise;
        return promise.then(function (response) {
          if (response && response.ok && typeof response.clone === "function") {
            response
              .clone()
              .json()
              .then(patchWorldBossLivePayload)
              .catch(function () {});
          }
          return response;
        });
      };
      wrappedFetch.__gcInstantFeedbackWrapped = true;
      wrappedFetch.__gcPreviousFetch = originalFetch;
      window.fetch = wrappedFetch;
    }

    GC._instantFeedbackInstalled = true;
    GC.instantFeedback = {
      patchPlanetBuildingLevels: patchPlanetBuildingLevels,
      patchWorldBossParticipant: patchWorldBossParticipant,
      patchWorldBossLivePayload: patchWorldBossLivePayload,
      applyMessageNotificationSummary: applyMessageNotificationSummary,
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
