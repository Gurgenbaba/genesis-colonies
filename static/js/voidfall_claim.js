/* VOIDFALL claim enhancement: native POST forms are the no-JS fallback.
 * Delegated submit survives PJAX page swaps without re-binding.
 */
(function () {
  "use strict";

  // GC-VOIDFALL-008: schedule exactly one PJAX refresh at the UTC day boundary.
  // No additional API polling: only the existing server-rendered view is refreshed.
  var activePanel = null;
  var serverClockOffsetMs = 0;
  var rolloverTimer = null;
  var lastAttemptMs = 0;
  var rolloverBusy = false;

  function scheduleRollover() {
    if (rolloverTimer !== null) {
      window.clearTimeout(rolloverTimer);
      rolloverTimer = null;
    }
    var panel = document.querySelector("[data-voidfall-panel][data-voidfall-next-reset]");
    if (panel !== activePanel) {
      activePanel = panel;
      lastAttemptMs = 0;
      var serverNow = panel && Number(panel.dataset.voidfallServerNow);
      serverClockOffsetMs = Number.isFinite(serverNow) && serverNow > 0
        ? serverNow * 1000 - Date.now() : 0;
    }
    if (!panel || document.hidden) return;
    var nextReset = Number(panel.dataset.voidfallNextReset);
    if (!Number.isFinite(nextReset) || nextReset <= 0) return;
    var remainingMs = nextReset * 1000 - (Date.now() + serverClockOffsetMs);
    if (remainingMs > 0) {
      rolloverTimer = window.setTimeout(scheduleRollover, Math.min(remainingMs + 150, 2147483647));
      return;
    }
    // Avoid a retry storm if the game cannot be reached during rollover.
    var retryInMs = 60000 - (Date.now() - lastAttemptMs);
    if (lastAttemptMs && retryInMs > 0) {
      rolloverTimer = window.setTimeout(scheduleRollover, retryInMs);
      return;
    }
    if (rolloverBusy || !window.GC || typeof window.GC.reloadCurrentPage !== "function") return;
    lastAttemptMs = Date.now();
    rolloverBusy = true;
    Promise.resolve(window.GC.reloadCurrentPage({ force: true })).catch(function () {
      // Keep the existing page; retry no more than once per minute.
    }).finally(function () {
      rolloverBusy = false;
      scheduleRollover();
    });
  }

  function installRolloverWatcher() {
    var main = document.querySelector("#main-content");
    if (!main || !window.MutationObserver) {
      scheduleRollover();
      return;
    }
    var mainObserver = new MutationObserver(scheduleRollover);
    mainObserver.observe(main, { childList: true });
    // Support PJAX swapping the whole #main-content element as well.
    if (main.parentNode) {
      var parentObserver = new MutationObserver(function () {
        var nextMain = document.querySelector("#main-content");
        if (nextMain !== main) {
          mainObserver.disconnect();
          main = nextMain;
          if (main) mainObserver.observe(main, { childList: true });
        }
        scheduleRollover();
      });
      parentObserver.observe(main.parentNode, { childList: true });
    }
    scheduleRollover();
  }

  document.addEventListener("visibilitychange", scheduleRollover);
  window.addEventListener("pageshow", scheduleRollover);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installRolloverWatcher, { once: true });
  } else {
    installRolloverWatcher();
  }

  document.addEventListener("submit", async function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("[data-voidfall-form]")) return;
    if (!window.fetch) return;
    event.preventDefault();
    var button = form.querySelector('button[type="submit"]');
    if (!button || button.disabled || form.dataset.pending === "1") return;
    var token = form.querySelector('input[name="csrf_token"]');
    var key = form.querySelector('input[name="claim_key"]');
    var panel = form.closest("[data-voidfall-panel]");
    var result = panel && panel.querySelector("[data-voidfall-result]");
    if (!token || !key || !token.value) return;
    form.dataset.pending = "1";
    button.disabled = true;
    var granted = false;
    try {
      var response = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": token.value,
          "Accept": "application/json"
        },
        body: JSON.stringify({ claim_key: key.value })
      });
      var payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(String(payload.reason || "claim_failed"));
      granted = true;
      var url = new URL(window.location.href);
      url.pathname = "/login-rewards";
      url.search = "?voidfall_claim=ok";
      var discovery = payload.reward && payload.reward.discovery;
      if (discovery && /^(echo|relic|artifact)$/.test(String(discovery.kind))) {
        url.searchParams.set("voidfall_discovery", discovery.kind);
      }
      var target = url.pathname + url.search + url.hash;
      if (window.GC && typeof window.GC.navigateTo === "function") {
        await window.GC.navigateTo(target, { push: false, force: true });
      } else {
        // Native navigation only when the in-game PJAX shell is unavailable.
        window.location.assign(target);
      }
    } catch (_error) {
      if (result && panel) {
        result.hidden = false;
        result.classList.toggle("gc-voidfall__notice--error", !granted);
        // A successful grant followed by PJAX failure is still successful.
        result.textContent = granted
          ? (panel.dataset.voidfallSuccess || "Reward claimed.")
          : (panel.dataset.voidfallFailed || "Claim unavailable.");
      }
      // Re-enable only when the server did NOT confirm a reward grant.
      if (!granted) {
        button.disabled = false;
        form.dataset.pending = "0";
      }
    }
  }, true);
})();
