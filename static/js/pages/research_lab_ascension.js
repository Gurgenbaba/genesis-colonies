(function () {
  "use strict";

  var GC = window.GC = window.GC || {};
  if (GC._researchLabAscensionPersistentBound) {
    if (typeof GC.normalizeBuildingAscensionCards === "function") {
      GC.normalizeBuildingAscensionCards();
    }
    return;
  }
  GC._researchLabAscensionPersistentBound = true;

  var activeTrigger = null;
  var normalizeQueued = false;

  function byId(id) {
    return document.getElementById(id);
  }

  function requestId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    return "research-lab-asc-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  function messageFor(res) {
    var reason = String((res && (res.reason || res.error)) || "research_ascension_failed");
    if (typeof GC.t === "function") {
      return GC.t("research_network_error_" + reason, GC.t("research_network_error_generic", ""));
    }
    return reason;
  }

  function t(key, fallback) {
    return typeof GC.t === "function" ? GC.t(key, fallback || key) : (fallback || key);
  }

  function romanFromText(value) {
    var match = String(value || "").toUpperCase().match(/\b(IV|III|II|V|I)\b/);
    return match ? match[1] : "";
  }

  function previousRoman(nextRoman) {
    var prev = { II: "I", III: "II", IV: "III", V: "IV" };
    return prev[String(nextRoman || "").toUpperCase()] || "";
  }

  function ensureLeftStack(card) {
    if (!card) return null;
    var hero = card.querySelector(".gc-bld-card-hero");
    if (!hero) return null;
    var stack = hero.querySelector(".gc-bld-hero-left-stack");
    if (stack) return stack;
    stack = document.createElement("div");
    stack.className = "gc-bld-hero-left-stack";
    var right = hero.querySelector(".gc-bld-hero-right-stack");
    if (right) hero.insertBefore(stack, right);
    else hero.appendChild(stack);
    return stack;
  }

  function ensureResearchRankBadge(card, roman) {
    if (!card || !roman) return null;
    var stack = ensureLeftStack(card);
    if (!stack) return null;
    var badge = stack.querySelector("[data-research-lab-evo-badge]");
    if (!badge) {
      badge = document.createElement("span");
      badge.setAttribute("data-research-lab-evo-badge", "1");
      stack.insertBefore(badge, stack.firstChild || null);
    }
    badge.className = "gc-hero-stat-badge gc-bld-evo-badge";
    badge.title = t("research_network_title", "Research Network Ascension");
    badge.setAttribute("aria-label", badge.title);
    badge.textContent = t("buildings_mine_evo_short", "EVO") + " " + roman;
    card.classList.add("gc-building-card--evolved");
    card.dataset.gcResearchAscRoman = roman;
    return badge;
  }

  function researchRankFromCard(card, block, trigger) {
    if (!card) return "";
    var cached = romanFromText(card.dataset.gcResearchAscRoman || "");
    if (cached) return cached;

    var bonus = block && block.querySelector ? block.querySelector(".gc-bld-evo-bonus") : null;
    var fromBonus = romanFromText(bonus && bonus.textContent);
    if (fromBonus) return fromBonus;

    var nextRoman = romanFromText(
      (trigger && (trigger.dataset.ascRankLabel || trigger.dataset.ascActionLabel || trigger.textContent)) || ""
    );
    return previousRoman(nextRoman);
  }

  function normalizeResearchCard() {
    var card = document.querySelector('[data-building-row="research_lab"]');
    if (!card) return;
    var block = card.querySelector("[data-research-lab-ascension]");
    var trigger = block && block.querySelector ? block.querySelector("[data-research-lab-ascend]") : null;
    var roman = researchRankFromCard(card, block, trigger);
    if (roman) ensureResearchRankBadge(card, roman);

    // At an Ascension gate the normal next-level price is not actionable. Match
    // Mine/Forge UX: the ready state has one clear Ascension CTA, not a stale
    // building-cost footer competing with it.
    if (trigger) {
      var costs = card.querySelector(".gc-bld-card-meta--costs-only");
      if (costs) costs.remove();
    }

    // The research lab used to render a one-off network/progress panel that made
    // its Ascension surface look different from Mine/Forge cards. Keep only the
    // real CTA; the rank itself lives in the shared EVO badge on the hero.
    if (block) {
      if (trigger && block.parentNode) {
        trigger.classList.add("gc-bld-evo-btn");
        block.parentNode.insertBefore(trigger, block);
      }
      block.remove();
    }
  }

  function normalizeForgeCard() {
    document.querySelectorAll(".gc-bld-forge-badge").forEach(function (badge) {
      badge.classList.add("gc-bld-evo-badge");
    });
    document.querySelectorAll("[data-stellar-forge-open]").forEach(function (button) {
      button.classList.add("gc-bld-evo-btn");
      button.classList.remove("gc-btn-ghost");
    });
  }

  function normalizeBuildingAscensionCards() {
    normalizeResearchCard();
    normalizeForgeCard();
  }

  function queueNormalize() {
    if (normalizeQueued) return;
    normalizeQueued = true;
    var run = function () {
      normalizeQueued = false;
      normalizeBuildingAscensionCards();
      if (!byId("gc-research-lab-ascension-confirm-modal")) {
        document.body.classList.remove("gc-modal-open");
        activeTrigger = null;
      }
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(run);
    else setTimeout(run, 0);
  }

  function modalParts() {
    return {
      modal: byId("gc-research-lab-ascension-confirm-modal"),
      submit: byId("gc-research-lab-ascension-confirm-submit"),
      lead: byId("gc-research-lab-ascension-confirm-lead"),
      rank: byId("gc-research-lab-ascension-confirm-rank"),
      benefit: byId("gc-research-lab-ascension-benefit"),
      metal: byId("gc-research-lab-ascension-tribute-metal"),
      crystal: byId("gc-research-lab-ascension-tribute-crystal"),
    };
  }

  function openModal(btn) {
    var parts = modalParts();
    if (!parts.modal || !btn) return;
    activeTrigger = btn;
    if (parts.lead) parts.lead.textContent = btn.dataset.ascLead || "";
    if (parts.rank) parts.rank.textContent = btn.dataset.ascRankLabel || "";
    if (parts.benefit) parts.benefit.textContent = btn.dataset.ascBenefit || "";
    if (parts.metal) parts.metal.textContent = btn.dataset.ascTributeMetalLabel || "";
    if (parts.crystal) parts.crystal.textContent = btn.dataset.ascTributeCrystalLabel || "";
    if (parts.submit) parts.submit.textContent = btn.dataset.ascActionLabel || "";
    parts.modal.hidden = false;
    parts.modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-modal-open");
    if (parts.submit) parts.submit.focus();
  }

  function closeModal() {
    var parts = modalParts();
    if (parts.modal) {
      parts.modal.hidden = true;
      parts.modal.setAttribute("aria-hidden", "true");
    }
    document.body.classList.remove("gc-modal-open");
    var focusTarget = activeTrigger;
    activeTrigger = null;
    if (focusTarget && document.contains(focusTarget)) focusTarget.focus();
  }

  function retireAscendTrigger(trigger) {
    if (!trigger || !document.contains(trigger)) return;
    trigger.disabled = true;
    trigger.setAttribute("aria-disabled", "true");
    trigger.removeAttribute("data-research-lab-ascend");
    trigger.dataset.gcAwaitingReconcile = "1";
  }

  function reconcileBuildingsPanel() {
    if (typeof GC.forceCanonicalGameStateRefresh !== "function") {
      queueNormalize();
      return;
    }
    try {
      var pending = GC.forceCanonicalGameStateRefresh("research_lab_ascension");
      if (pending && typeof pending.then === "function") {
        pending.then(queueNormalize).catch(function () {});
      } else {
        queueNormalize();
      }
    } catch (_) {
      // Response-first acceleration is fail-open. The next canonical page/state
      // refresh still owns the final server-authoritative representation.
      queueNormalize();
    }
  }

  async function ascend(submit) {
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

      var completedTrigger = activeTrigger;
      var completedRoman = romanFromText(
        completedTrigger && (completedTrigger.dataset.ascRankLabel || completedTrigger.dataset.ascActionLabel || completedTrigger.textContent)
      );
      var completedCard = completedTrigger && completedTrigger.closest
        ? completedTrigger.closest('[data-building-row="research_lab"]')
        : null;
      closeModal();
      if (completedCard && completedRoman) ensureResearchRankBadge(completedCard, completedRoman);
      retireAscendTrigger(completedTrigger);
      if (typeof GC.applyActionState === "function") GC.applyActionState(res, "research_lab_ascension");
      reconcileBuildingsPanel();
    } catch (err) {
      if (typeof GC.toast === "function") GC.toast(messageFor(null), "error");
      else if (window.console && console.error) console.error(err);
    } finally {
      submit.dataset.busy = "0";
      submit.disabled = false;
    }
  }

  function onDocumentClick(event) {
    var target = event.target && event.target.closest ? event.target : null;
    if (!target) return;

    var trigger = target.closest("[data-research-lab-ascend]");
    if (trigger) {
      event.preventDefault();
      openModal(trigger);
      return;
    }

    var submit = target.closest("#gc-research-lab-ascension-confirm-submit");
    if (submit) {
      event.preventDefault();
      ascend(submit);
      return;
    }

    if (target.closest("[data-research-lab-ascension-cancel]")) {
      event.preventDefault();
      closeModal();
    }
  }

  function onKeydown(event) {
    var modal = byId("gc-research-lab-ascension-confirm-modal");
    if (event.key === "Escape" && modal && !modal.hidden) closeModal();
  }

  // Persistent delegated handlers are deliberate: Buildings uses light PJAX tab
  // swaps. Page cleanup must not tear these down because the external script is
  // de-duplicated and may not execute again after the next partial DOM swap.
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", onKeydown);

  var main = byId("main-content");
  if (main && typeof MutationObserver !== "undefined") {
    var observer = new MutationObserver(queueNormalize);
    observer.observe(main, { childList: true, subtree: true });
    GC._researchLabAscensionObserver = observer;
  }

  GC.normalizeBuildingAscensionCards = normalizeBuildingAscensionCards;
  normalizeBuildingAscensionCards();
}());
