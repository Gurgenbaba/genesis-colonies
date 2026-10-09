/** Live resource requirements for research cards. Presentation only; server authorizes actions. */
(function (window) {
  "use strict";
  var GC = window.GC || (window.GC = {});
  GC.pages = GC.pages || {};
  var cleanup = null;
  function value(key) {
    var node = document.querySelector("#resource-bar .res-value." + key);
    if (!node) return null;
    var raw = String(node.textContent || "").replace(/[^0-9]/g, "");
    return raw ? Number(raw) : null;
  }
  function init() {
    if (cleanup) cleanup();
    var root = document.querySelector(".research-prog-list, [data-research-card]");
    var hud = document.querySelector("#resource-bar");
    if (!root || !hud) return;
    var stopped = false, scheduled = false, inFlight = false;
    var retried = new Map();
    function sync() {
      if (stopped || !root.isConnected) return;
      var amounts = { metal: value("metal"), crystal: value("crystal") };
      if (amounts.metal === null || amounts.crystal === null) return;
      var needsRefresh = false;
      document.querySelectorAll('[data-research-card] .btn-research[data-action-state="warn"][data-req-items]').forEach(function (button) {
        var items;
        try { items = JSON.parse(button.getAttribute("data-req-items") || "[]"); } catch (_) { return; }
        if (!Array.isArray(items)) return;
        var resourceItems = items.filter(function (item) { return item && item.kind === "resource" && Object.prototype.hasOwnProperty.call(amounts, item.key); });
        if (!resourceItems.length) return;
        var allMet = true;
        var touched = false;
        items.forEach(function (item) {
          if (!item || item.kind !== "resource" || !Object.prototype.hasOwnProperty.call(amounts, item.key)) return;
          var have = amounts[item.key], need = Number(item.need);
          if (!Number.isFinite(need)) return;
          item.have = have;
          item.met = have >= need;
          if (!item.met) allMet = false;
          touched = true;
        });
        if (touched) button.setAttribute("data-req-items", JSON.stringify(items));
        if (allMet) {
          var card = button.closest("[data-research-card]");
          var signature = (card && card.getAttribute("data-tech-key") || "") + ":" + resourceItems.map(function (item) { return item.key + ":" + item.need; }).join(",");
          var last = retried.get(signature) || 0;
          if (Date.now() - last > 15000) { retried.set(signature, Date.now()); needsRefresh = true; }
        }
      });
      if (needsRefresh && !inFlight && typeof GC.reloadCurrentPage === "function") {
        inFlight = true;
        Promise.resolve(GC.reloadCurrentPage({ force: true })).catch(function () {}).finally(function () { inFlight = false; });
      }
    }
    function schedule() {
      if (stopped || scheduled) return;
      scheduled = true;
      window.requestAnimationFrame(function () { scheduled = false; sync(); });
    }
    var observer = new MutationObserver(schedule);
    observer.observe(hud, { subtree: true, childList: true, characterData: true });
    sync();
    var timer = window.setInterval(sync, 1000);
    cleanup = function () { stopped = true; observer.disconnect(); window.clearInterval(timer); };
    if (typeof GC.registerCleanup === "function") GC.registerCleanup(cleanup);
  }
  GC.pages.researchLiveRequirements = { init: init };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
