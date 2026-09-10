(function () {
  "use strict";

  var GC = window.GC = window.GC || {};
  var bound = false;

  function requestId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return "research-asc-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  function messageFor(res) {
    var reason = String((res && (res.reason || res.error)) || "research_ascension_failed");
    if (typeof GC.t === "function") {
      return GC.t("research_network_error_" + reason, GC.t("research_network_error_generic", "Research ascension failed."));
    }
    return reason;
  }

  async function ascend(btn) {
    if (!btn || btn.disabled || btn.dataset.busy === "1") return;
    btn.dataset.busy = "1";
    btn.disabled = true;
    try {
      if (typeof GC.fetchGameAction !== "function") throw new Error("fetchGameAction missing");
      var res = await GC.fetchGameAction("/api/research/ascend-lab", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ request_id: requestId() })
      });
      if (!res || !res.ok) {
        if (typeof GC.toast === "function") GC.toast(messageFor(res), "error");
        return;
      }
      if (typeof GC.applyActionState === "function") {
        GC.applyActionState(res, "research_lab_ascension");
      }
      if (typeof GC.reloadCurrentPage === "function") {
        await GC.reloadCurrentPage({ force: true });
      }
    } catch (err) {
      if (typeof GC.toast === "function") GC.toast(messageFor(null), "error");
      else if (window.console && console.error) console.error(err);
    } finally {
      btn.dataset.busy = "0";
      btn.disabled = false;
    }
  }

  function bind() {
    if (bound) return;
    bound = true;
    document.addEventListener("click", function (event) {
      var btn = event.target && event.target.closest ? event.target.closest("[data-research-network-ascend]") : null;
      if (!btn) return;
      event.preventDefault();
      ascend(btn);
    });
  }

  bind();
}());
