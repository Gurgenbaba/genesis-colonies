(function () {
  "use strict";

  var GC = window.GC = window.GC || {};
  var modal = document.getElementById("gc-research-lab-ascension-confirm-modal");
  var submit = document.getElementById("gc-research-lab-ascension-confirm-submit");
  var lead = document.getElementById("gc-research-lab-ascension-confirm-lead");
  var rank = document.getElementById("gc-research-lab-ascension-confirm-rank");
  var benefit = document.getElementById("gc-research-lab-ascension-benefit");
  var metal = document.getElementById("gc-research-lab-ascension-tribute-metal");
  var crystal = document.getElementById("gc-research-lab-ascension-tribute-crystal");
  var activeTrigger = null;

  function requestId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    return "research-lab-asc-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  function messageFor(res) {
    var reason = String((res && (res.reason || res.error)) || "research_ascension_failed");
    if (typeof GC.t === "function") {
      return GC.t("research_network_error_" + reason, GC.t("research_network_error_generic", "Research ascension failed."));
    }
    return reason;
  }

  function openModal(btn) {
    if (!modal || !btn) return;
    activeTrigger = btn;
    var name = btn.dataset.ascName || "";
    var roman = btn.dataset.ascRank || "";
    var required = btn.dataset.ascRequired || "";
    if (lead) lead.textContent = name + (required ? " · Level " + required : "");
    if (rank) rank.textContent = "Ascension " + roman;
    if (benefit) benefit.textContent = btn.dataset.ascBenefit || "";
    if (metal) metal.textContent = "Ferronit · " + (btn.dataset.ascTributeMetal || "0");
    if (crystal) crystal.textContent = "Crytite · " + (btn.dataset.ascTributeCrystal || "0");
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-modal-open");
    if (submit) submit.focus();
  }

  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("gc-modal-open");
    var focusTarget = activeTrigger;
    activeTrigger = null;
    if (focusTarget && document.contains(focusTarget)) focusTarget.focus();
  }

  async function ascend() {
    if (!submit || submit.disabled || submit.dataset.busy === "1") return;
    submit.dataset.busy = "1";
    submit.disabled = true;
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
      closeModal();
      if (typeof GC.applyActionState === "function") GC.applyActionState(res, "research_lab_ascension");
      if (typeof GC.reloadCurrentPage === "function") await GC.reloadCurrentPage({ force: true });
      else window.location.reload();
    } catch (err) {
      if (typeof GC.toast === "function") GC.toast(messageFor(null), "error");
      else if (window.console && console.error) console.error(err);
    } finally {
      submit.dataset.busy = "0";
      submit.disabled = false;
    }
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target && event.target.closest ? event.target.closest("[data-research-lab-ascend]") : null;
    if (trigger) {
      event.preventDefault();
      openModal(trigger);
      return;
    }
    if (event.target && event.target.closest && event.target.closest("[data-research-lab-ascension-cancel]")) {
      event.preventDefault();
      closeModal();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && modal && !modal.hidden) closeModal();
  });
  if (submit) submit.addEventListener("click", ascend);
}());
