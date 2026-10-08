/**
 * GC-LIVE-BUILD-AFFORD-001 — refresh server-authoritative building actions
 * when live HUD balances cross a cost threshold.
 *
 * No second game-state poller and no client-side building decisions:
 * this only asks the existing refresh pipeline to reconcile the panel.
 */
(function (global) {
  "use strict";
  var GC = global.GC || (global.GC = {});
  GC.pages = GC.pages || {};
  var cleanupCurrent = null;

  function integerText(node) {
    if (!node) return null;
    var raw = String(node.getAttribute("title") || node.textContent || "");
    var digits = raw.replace(/[^0-9]/g, "");
    return digits ? Number(digits) : null;
  }

  function balance(key) {
    return integerText(document.querySelector("#resource-bar .res-value." + key));
  }

  function cost(card, key) {
    return integerText(card.querySelector(".gc-bld-card-costs .gc-cost-" + key + " .gc-cost-val"));
  }

  function watchAffordability() {
    var page = document.querySelector(".buildings-tab-panels");
    if (!page || typeof GC.refreshGameState !== "function") return function () {};

    var previous = new Map();
    var lastRequested = new Map();
    var refreshing = false;
    var stopped = false;

    function tick() {
      if (stopped || refreshing || !page.isConnected || document.hidden) return;
      var metal = balance("metal");
      var crystal = balance("crystal");
      if (metal === null || crystal === null) return;

      var cards = page.querySelectorAll("[data-building-row]");
      for (var i = 0; i < cards.length; i += 1) {
        var card = cards[i];
        var key = card.getAttribute("data-building-row");
        var warn = card.querySelector('.btn-upgrade[data-action-state="warn"]');
        var needMetal = cost(card, "metal");
        var needCrystal = cost(card, "crystal");
        if (!key || !warn || needMetal === null || needCrystal === null) {
          if (key) previous.delete(key);
          continue;
        }
        var signature = needMetal + ":" + needCrystal;
        var affordable = metal >= needMetal && crystal >= needCrystal;
        var old = previous.get(key);
        previous.set(key, { signature: signature, affordable: affordable });
        if (!affordable) continue;

        // Initial stale SSR state is also eligible. Do not repeatedly hit the
        // server while requirements or a full queue legitimately block build.
        var now = Date.now();
        var recent = lastRequested.get(key);
        if (recent && recent.signature === signature && now - recent.at < 30000) continue;
        if (old && old.signature === signature && old.affordable && recent) continue;
        lastRequested.set(key, { signature: signature, at: now });
        refreshing = true;
        try {
          Promise.resolve(GC.refreshGameState("queue_timer_zero"))
            .catch(function () {})
            .finally(function () { refreshing = false; });
        } catch (_) {
          refreshing = false;
        }
        return;
      }
    }

    tick();
    var interval = global.setInterval(tick, 1500);
    return function () {
      stopped = true;
      global.clearInterval(interval);
      previous.clear();
      lastRequested.clear();
    };
  }

  GC.pages.buildings = {
    init: function () {
      if (cleanupCurrent) cleanupCurrent();
      cleanupCurrent = watchAffordability();
      if (typeof GC.registerCleanup === "function") {
        GC.registerCleanup(function () {
          if (cleanupCurrent) cleanupCurrent();
          cleanupCurrent = null;
        });
      }
    },
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      GC.pages.buildings.init();
    });
  } else {
    GC.pages.buildings.init();
  }
})(typeof window !== "undefined" ? window : globalThis);
