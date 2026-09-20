(function () {
  "use strict";

  var GC = window.GC = window.GC || {};
  if (GC._nodebusterMinePersistentBound) return;
  GC._nodebusterMinePersistentBound = true;

  var activeAscend = null;
  var observer = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function requestId(prefix) {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return String(prefix || "nodebuster") + "-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  function t(key, fallback) {
    return typeof GC.t === "function" ? GC.t(key, fallback || key) : (fallback || key);
  }

  function reasonKey(res) {
    return String((res && (res.reason || res.error)) || "generic");
  }

  function reasonText(res) {
    var reason = reasonKey(res);
    return t("nodebuster_error_" + reason, t("nodebuster_error_generic", reason));
  }

  function toast(message, kind) {
    if (typeof GC.toast === "function") GC.toast(message, kind || "info");
  }

  function modalParts() {
    var modal = byId("gc-mine-evo-confirm-modal");
    var tributeLabel = byId("gc-mine-evo-confirm-tribute-label");
    return {
      modal: modal,
      submit: byId("gc-mine-evo-confirm-submit"),
      lead: byId("gc-mine-evo-confirm-lead"),
      chip: byId("gc-mine-evo-confirm-rank-chip"),
      benefit: byId("gc-mine-evo-confirm-benefit"),
      reset: byId("gc-mine-evo-confirm-level-kept"),
      best: byId("gc-mine-evo-confirm-rank"),
      tributeSection: tributeLabel && tributeLabel.closest
        ? tributeLabel.closest(".gc-bld-evo-confirm-section")
        : null
    };
  }

  function openAscend(btn) {
    var parts = modalParts();
    if (!parts.modal || !btn) return;
    activeAscend = btn;

    if (parts.lead) parts.lead.textContent = btn.dataset.nodebusterConfirmLead || "";
    if (parts.chip) parts.chip.textContent = "+" + String(btn.dataset.nodebusterPointsGain || "0") + " " + t("nodebuster_ap_short", "AP");
    if (parts.benefit) parts.benefit.textContent = btn.dataset.nodebusterConfirmGain || "";
    if (parts.reset) parts.reset.textContent = btn.dataset.nodebusterConfirmReset || "";
    if (parts.best) parts.best.textContent = btn.dataset.nodebusterConfirmBest || "";
    if (parts.tributeSection) parts.tributeSection.hidden = true;
    if (parts.submit) parts.submit.textContent = btn.dataset.nodebusterConfirmButton || t("nodebuster_confirm_button", "Start Ascension");

    parts.modal.hidden = false;
    parts.modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-modal-open");
    if (parts.submit) parts.submit.focus();
  }

  function closeAscend() {
    var parts = modalParts();
    if (parts.modal) {
      parts.modal.hidden = true;
      parts.modal.setAttribute("aria-hidden", "true");
    }
    if (parts.tributeSection) parts.tributeSection.hidden = false;
    document.body.classList.remove("gc-modal-open");
    var focus = activeAscend;
    activeAscend = null;
    if (focus && document.contains(focus)) focus.focus();
  }

  function reconcile(reason) {
    if (typeof GC.forceCanonicalGameStateRefresh === "function") {
      try {
        var pending = GC.forceCanonicalGameStateRefresh(reason || "nodebuster_mine");
        if (pending && typeof pending.catch === "function") pending.catch(function () {});
        return;
      } catch (_) {}
    }
    if (typeof GC.reloadCurrentPage === "function") {
      try {
        GC.reloadCurrentPage({ reason: reason || "nodebuster_mine" });
      } catch (_) {}
    }
  }

  async function submitAscend(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    var btn = activeAscend;
    var submit = byId("gc-mine-evo-confirm-submit");
    if (!btn || !submit || submit.dataset.busy === "1") return;

    submit.dataset.busy = "1";
    submit.disabled = true;
    try {
      if (typeof GC.fetchGameAction !== "function") throw new Error("fetchGameAction missing");
      var res = await GC.fetchGameAction("/api/buildings/mine-evolve", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          building_type: btn.dataset.mineEvolve || "",
          request_id: requestId("nodebuster-asc")
        })
      });

      if (!res || !res.ok) {
        toast(reasonText(res), "error");
        return;
      }

      closeAscend();
      toast(t("nodebuster_success", "Ascension complete."), "success");
      if (typeof GC.applyActionState === "function") {
        GC.applyActionState(res, "nodebuster_mine_ascension");
      }
      reconcile("nodebuster_mine_ascension");
    } catch (err) {
      toast(t("nodebuster_error_generic", "Ascension action failed."), "error");
      if (window.console && console.error) console.error(err);
    } finally {
      submit.dataset.busy = "0";
      submit.disabled = false;
    }
  }

  async function buySkill(btn, event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (!btn || btn.disabled || btn.dataset.busy === "1") return;

    btn.dataset.busy = "1";
    btn.disabled = true;
    try {
      if (typeof GC.fetchGameAction !== "function") throw new Error("fetchGameAction missing");
      var res = await GC.fetchGameAction("/api/buildings/mine-evolution/skill", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          building_type: btn.dataset.nodebusterBuilding || "",
          skill_key: btn.dataset.nodebusterSkill || "",
          request_id: requestId("nodebuster-skill")
        })
      });

      if (!res || !res.ok) {
        toast(reasonText(res), "error");
        return;
      }

      toast(t("nodebuster_skill_success", "Ascension skill upgraded."), "success");
      if (typeof GC.applyActionState === "function") {
        GC.applyActionState(res, "nodebuster_mine_skill");
      }
      reconcile("nodebuster_mine_skill");
    } catch (err) {
      toast(t("nodebuster_error_generic", "Ascension action failed."), "error");
      if (window.console && console.error) console.error(err);
    } finally {
      btn.dataset.busy = "0";
    }
  }

  function bindNodebuster(root) {
    var host = root && root.querySelectorAll ? root : document;

    host.querySelectorAll("[data-nodebuster-mine] [data-mine-evolve]").forEach(function (btn) {
      if (btn.dataset.nodebusterBound === "1") return;
      btn.dataset.nodebusterBound = "1";
      btn.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        openAscend(btn);
      });
    });

    host.querySelectorAll("[data-nodebuster-skill]").forEach(function (btn) {
      if (btn.dataset.nodebusterBound === "1") return;
      btn.dataset.nodebusterBound = "1";
      btn.addEventListener("click", function (event) {
        buySkill(btn, event);
      });
    });
  }

  var submit = byId("gc-mine-evo-confirm-submit");
  if (submit) {
    submit.addEventListener("click", submitAscend);
  }

  document.querySelectorAll("[data-mine-evo-confirm-cancel]").forEach(function (btn) {
    btn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      closeAscend();
    });
  });

  document.addEventListener("keydown", function (event) {
    var modal = byId("gc-mine-evo-confirm-modal");
    if (event.key === "Escape" && modal && !modal.hidden && activeAscend) {
      event.preventDefault();
      closeAscend();
    }
  });

  bindNodebuster(document);

  var main = byId("main-content");
  if (main && typeof MutationObserver !== "undefined") {
    observer = new MutationObserver(function () {
      bindNodebuster(main);
    });
    observer.observe(main, { childList: true, subtree: true });
    GC._nodebusterMineObserver = observer;
  }
}());
