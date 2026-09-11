(function () {
  "use strict";

  var GC = window.GC = window.GC || {};
  var bound = false;
  var pendingButton = null;

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

  function formatInt(value) {
    var number = Number(value || 0);
    if (!Number.isFinite(number)) number = 0;
    try {
      return new Intl.NumberFormat(document.documentElement.lang || undefined, { maximumFractionDigits: 0 }).format(number);
    } catch (_) {
      return String(Math.trunc(number));
    }
  }

  function modal() {
    return document.getElementById("gc-research-network-confirm-modal");
  }

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value || "";
  }

  function closeModal() {
    var root = modal();
    if (!root) return;
    root.hidden = true;
    root.setAttribute("aria-hidden", "true");
    document.body.classList.remove("gc-modal-open");
    var restore = pendingButton;
    pendingButton = null;
    if (restore && typeof restore.focus === "function") restore.focus();
  }

  function openModal(btn) {
    var root = modal();
    if (!root || !btn) return;
    pendingButton = btn;

    var rank = String(btn.dataset.researchAscendRank || "");
    var benefit = String(btn.dataset.researchAscendBenefit || "");
    var ready = String(btn.dataset.researchAscendReady || "");
    var metal = btn.dataset.researchAscendMetal || "0";
    var crystal = btn.dataset.researchAscendCrystal || "0";

    setText("gc-research-network-confirm-lead", ready);
    setText("gc-research-network-confirm-rank-chip", rank ? "ASCENSION " + rank : "ASCENSION");
    setText("gc-research-network-confirm-benefit", benefit);
    setText("gc-research-network-confirm-tribute-metal", "Ferronit: " + formatInt(metal));
    setText("gc-research-network-confirm-tribute-crystal", "Crytite: " + formatInt(crystal));

    root.hidden = false;
    root.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-modal-open");
    var submit = document.getElementById("gc-research-network-confirm-submit");
    if (submit && typeof submit.focus === "function") submit.focus();
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
      closeModal();
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
      var target = event.target;
      var btn = target && target.closest ? target.closest("[data-research-network-ascend]") : null;
      if (btn) {
        event.preventDefault();
        openModal(btn);
        return;
      }
      if (target && target.closest && target.closest("[data-research-network-confirm-cancel]")) {
        event.preventDefault();
        closeModal();
        return;
      }
      var submit = target && target.closest ? target.closest("#gc-research-network-confirm-submit") : null;
      if (submit && pendingButton) {
        event.preventDefault();
        ascend(pendingButton);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeModal();
    });
  }

  bind();
}());
