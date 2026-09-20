(function () {
  "use strict";

  var GC = window.GC = window.GC || {};
  if (GC._nodebusterMinePersistentBound) return;
  GC._nodebusterMinePersistentBound = true;

  var activeAscend = null;

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
    var completed = false;
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

      completed = true;
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
      if (!completed && document.contains(btn)) btn.disabled = false;
    }
  }

  function onDocumentClick(event) {
    var target = event.target && event.target.closest ? event.target : null;
    if (!target) return;

    var skill = target.closest("[data-nodebuster-skill]");
    if (skill) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      buySkill(skill, event);
      return;
    }

    var ascend = target.closest("[data-nodebuster-mine] [data-mine-evolve]");
    if (ascend) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      openAscend(ascend);
      return;
    }

    if (activeAscend && target.closest("#gc-mine-evo-confirm-submit")) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      submitAscend(event);
      return;
    }

    if (activeAscend && target.closest("[data-mine-evo-confirm-cancel]")) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      closeAscend();
    }
  }

  function onDocumentKeydown(event) {
    var modal = byId("gc-mine-evo-confirm-modal");
    if (activeAscend && event.key === "Escape" && modal && !modal.hidden) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      closeAscend();
    }
  }

  // Capture phase is deliberate: legacy Mine-Evolution handlers may still exist
  // during a rolling DEV deployment. Nodebuster owns only buttons inside its
  // own surface and prevents an older bubbling handler from double-submitting.
  // The listeners stay persistent across Buildings light-PJAX replacements.
  document.addEventListener("click", onDocumentClick, true);
  document.addEventListener("keydown", onDocumentKeydown, true);
}());
