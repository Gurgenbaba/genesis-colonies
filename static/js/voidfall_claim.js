/* VOIDFALL claim enhancement: native POST forms are the no-JS fallback.
 * Delegated submit survives PJAX page swaps without re-binding.
 */
(function () {
  "use strict";
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
        result.classList.add("gc-voidfall__notice--error");
        result.textContent = panel.dataset.voidfallFailed || "Claim unavailable.";
      }
      button.disabled = false;
      form.dataset.pending = "0";
    }
  }, true);
})();
