/**
 * GC-PERF-JS-002 — Defense page binder (extracted from main.js).
 * Mirror of pages/shipyard.js: state-first mutations; queue/HUD stay in main.js.
 */
(function (global) {
  "use strict";

  var GC = global.GC || (global.GC = {});
  GC.pages = GC.pages || {};
  GC.modules = GC.modules || {};

  var _defenseBound = false;

  function applyActionState(res, reason) {
    if (typeof GC.applyActionState === "function") return GC.applyActionState(res, reason);
    return false;
  }

  function applyDefenseState(page, data, opts) {
    if (typeof GC.applyDefenseState === "function") GC.applyDefenseState(page, data, opts);
  }

  function refreshDefenseState(page) {
    if (typeof GC.refreshDefenseState === "function") return GC.refreshDefenseState(page);
    return Promise.resolve(null);
  }

  function clearDefenseQueueSignature() {
    if (typeof GC.clearDefenseQueueSignature === "function") GC.clearDefenseQueueSignature();
  }

  function normalizeDefenseApiPayload(res) {
    if (typeof GC.normalizeDefenseApiPayload === "function") return GC.normalizeDefenseApiPayload(res);
    return null;
  }

  function showNotify(msg, category) {
    if (typeof GC.showNotify === "function") GC.showNotify(msg, category);
  }

  function t(key, fallback) {
    if (typeof GC.t === "function") return GC.t(key, fallback);
    return fallback != null ? fallback : key;
  }

  function parseIntNumber(v) {
    if (typeof GC.parseIntNumber === "function") return GC.parseIntNumber(v);
    return parseInt(String(v || "0").replace(/[^\d-]/g, ""), 10) || 0;
  }

  function setNumberInputValue(inp, n) {
    if (typeof GC.setNumberInputValue === "function") GC.setNumberInputValue(inp, n);
    else if (inp) inp.value = String(n);
  }

  function readNumberInput(inp) {
    if (typeof GC.readNumberInput === "function") return GC.readNumberInput(inp);
    return parseIntNumber(inp && inp.value);
  }

  function normalizeGameplayInteger(v) {
    if (typeof GC.normalizeGameplayInteger === "function") return GC.normalizeGameplayInteger(v);
    var raw = String(v == null ? "0" : v).replace(/[\s._,'’]/g, "");
    return /^-?\d+$/.test(raw) ? raw : "0";
  }

  function isPositiveGameplayInteger(v) {
    if (typeof GC.isPositiveGameplayInteger === "function") return GC.isPositiveGameplayInteger(v);
    try { return BigInt(normalizeGameplayInteger(v)) > BigInt(0); } catch (_) { return false; }
  }

  function setGameplayIntegerInput(inp, v) {
    if (typeof GC.setGameplayIntegerInput === "function") return GC.setGameplayIntegerInput(inp, v);
    if (inp) {
      var exact = normalizeGameplayInteger(v);
      inp.value = exact;
      inp.dataset.inputMax = exact;
    }
  }

  function readGameplayIntegerInput(inp) {
    if (typeof GC.readGameplayIntegerInput === "function") {
      return GC.readGameplayIntegerInput(inp, "1");
    }
    var exact = normalizeGameplayInteger(inp && inp.value);
    return isPositiveGameplayInteger(exact) ? exact : "1";
  }

  function militaryPageResources(page) {
    if (typeof GC.militaryPageResources === "function") return GC.militaryPageResources(page);
    return (GC.lastState && GC.lastState.resources) || {};
  }

  function syncUnitCardCostPreview(card, resources) {
    if (typeof GC.syncUnitCardCostPreview === "function") {
      GC.syncUnitCardCostPreview(card, resources);
    }
  }

  function reasonText(reason) {
    var r = String(reason || "generic");
    return t("defense_error_" + r, t("troops_error_" + r, t("fleet_error_" + r, r || "Error")));
  }

  function fmtTroopNum(n) {
    if (typeof GC.fmtGameplayInteger === "function") return GC.fmtGameplayInteger(n);
    if (typeof GC.fmtNumber === "function") return GC.fmtNumber(n);
    return normalizeGameplayInteger(n);
  }

  function applyTroopsPayload(panel, troops, resourcesOpt) {
    if (!panel || !troops) return;
    var totalEl = panel.querySelector("[data-barracks-troops-total]");
    var capEl = panel.querySelector("[data-barracks-troops-capacity]");
    if (totalEl) totalEl.textContent = fmtTroopNum(troops.total || 0);
    if (capEl) capEl.textContent = fmtTroopNum(troops.capacity || 0);
    var page = panel.closest("#defense-page") || panel;
    var resources =
      resourcesOpt && typeof resourcesOpt === "object"
        ? resourcesOpt
        : militaryPageResources(page);
    (troops.units || []).forEach(function (u) {
      var stock = panel.querySelector('[data-troop-stock="' + u.key + '"]');
      if (stock) stock.textContent = "×" + fmtTroopNum(u.amount || 0);
      var maxBtn = panel.querySelector('[data-troop-max="' + u.key + '"]');
      if (maxBtn) {
        var maxQty = normalizeGameplayInteger(u.max_train);
        maxBtn.setAttribute("data-max-qty", maxQty);
        maxBtn.dataset.maxQty = maxQty;
      }
      var amountInp = panel.querySelector('[data-troop-amount="' + u.key + '"]');
      if (amountInp && u.max_train != null) {
        amountInp.dataset.inputMax = normalizeGameplayInteger(u.max_train);
      }
      var trainBtn = panel.querySelector('[data-troop-train="' + u.key + '"]');
      if (trainBtn) {
        var can = u.can_train === true || u.can_train === 1 || u.can_train === "1";
        trainBtn.disabled = !can;
        trainBtn.setAttribute("aria-disabled", can ? "false" : "true");
        trainBtn.setAttribute("data-can-train", can ? "1" : "0");
      }
      var card = panel.querySelector('[data-troop-card="' + u.key + '"]');
      if (card) {
        var costWrap = card.querySelector("[data-troop-cost]");
        if (costWrap) {
          var cm = normalizeGameplayInteger(
            u.cost_metal != null ? u.cost_metal : (u.train_cost && u.train_cost.metal)
          );
          var cc = normalizeGameplayInteger(
            u.cost_crystal != null ? u.cost_crystal : (u.train_cost && u.train_cost.crystal)
          );
          costWrap.dataset.unitCostMetal = cm;
          costWrap.dataset.unitCostCrystal = cc;
          costWrap.setAttribute("data-unit-cost-metal", cm);
          costWrap.setAttribute("data-unit-cost-crystal", cc);
        }
        syncUnitCardCostPreview(card, resources);
      }
    });
    renderTroopsQueue(panel, troops);
  }

  GC.applyTroopsPayload = applyTroopsPayload;

  function renderTroopsQueue(panel, troopsOrQueue) {
    var host = panel.querySelector("#troops-mini-queue") || panel.querySelector("[data-mini-queue-host='troops']");
    if (host && typeof GC.renderMiniQueueStrip === "function") {
      var troops =
        troopsOrQueue && !Array.isArray(troopsOrQueue) && typeof troopsOrQueue === "object"
          ? troopsOrQueue
          : { queue: troopsOrQueue, mini_queue_jobs: (troopsOrQueue && troopsOrQueue.mini_queue_jobs) || [] };
      var jobs = Array.isArray(troops.mini_queue_jobs) ? troops.mini_queue_jobs : [];
      if (!jobs.length && Array.isArray(troops.queue) && typeof GC._collectMiniQueueJobs !== "function") {
        // Fallback: pass through queue shaped as mini jobs if server omitted mini_queue_jobs.
        jobs = (troops.queue || []).map(function (job, idx) {
          return {
            job_id: Math.max(0, parseIntNumber(job.id) || 0),
            domain: "troops",
            owner_key: String(job.troop_key || ""),
            label: "troop_" + String(job.troop_key || ""),
            amount: normalizeGameplayInteger(job.amount),
            position: idx + 1,
            is_active: idx === 0,
            remaining_seconds: Math.max(0, parseIntNumber(job.remaining_seconds) || 0),
            finish_at: Math.max(0, parseIntNumber(job.finish_at) || 0),
            start_at: Math.max(0, parseIntNumber(job.started_at) || 0),
            progress_pct: 0,
            duration_seconds: Math.max(1, parseIntNumber(job.order_total_seconds) || 1),
            image_url: "/static/img/troops/" + String(job.troop_key || "") + ".png",
            cancelable: true,
          };
        });
      }
      GC.renderMiniQueueStrip(host, jobs, {
        domain: "troops",
        idleText: t("barracks_troops_queue_idle", "Keine Ausbildung aktiv"),
        limit: Math.max(0, parseIntNumber(troops.queue_limit || (troops.summary && troops.summary.limit)) || 0),
      });
      return;
    }
    // Legacy fallback (should not render if mini-queue host exists).
    var wrap = panel.querySelector("[data-barracks-troops-queue]");
    if (!wrap) return;
    var rows = Array.isArray(troopsOrQueue)
      ? troopsOrQueue
      : (troopsOrQueue && troopsOrQueue.queue) || [];
    if (!rows.length) {
      wrap.innerHTML =
        '<p class="hint" data-barracks-troops-queue-empty>' +
        esc(t("barracks_troops_queue_idle", "Keine Ausbildung aktiv")) +
        "</p>";
      return;
    }
    var html = '<ul class="barracks-troops-queue-list">';
    rows.forEach(function (job) {
      var key = String(job.troop_key || "");
      var amount = normalizeGameplayInteger(job.amount);
      var jobId = Math.max(0, parseIntNumber(job.id) || 0);
      var label = t("troop_" + key, key) + " ×" + fmtTroopNum(amount);
      html +=
        '<li class="barracks-troops-queue-item" data-troop-job-id="' +
        jobId +
        '"><span>' +
        esc(label) +
        '</span><button type="button" class="gc-btn gc-btn-sm gc-btn-ghost" data-troop-cancel="' +
        jobId +
        '">' +
        esc(t("action_cancel", "Abbrechen")) +
        "</button></li>";
    });
    html += "</ul>";
    wrap.innerHTML = html;
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function bindDefenseTabs(page) {
    if (!page || page.getAttribute("data-defense-tabs-bound") === "1") return;
    page.setAttribute("data-defense-tabs-bound", "1");
    page.addEventListener("click", function (e) {
      var tabBtn = e.target.closest("[data-defense-tab]");
      if (!tabBtn || !page.contains(tabBtn)) return;
      e.preventDefault();
      var tab = tabBtn.getAttribute("data-defense-tab") || "structures";
      page.querySelectorAll("[data-defense-tab]").forEach(function (btn) {
        var on = btn.getAttribute("data-defense-tab") === tab;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
      });
      page.querySelectorAll("[data-defense-tab-panel]").forEach(function (panel) {
        panel.hidden = panel.getAttribute("data-defense-tab-panel") !== tab;
      });
    });
  }

  function bindBarracksTroops(page) {
    var panel = page && page.querySelector("[data-barracks-troops-panel]");
    if (!panel || panel.getAttribute("data-bound") === "1") return;
    panel.setAttribute("data-bound", "1");
    var planetId = panel.getAttribute("data-planet-id") || page.getAttribute("data-planet-id") || "";
    var errEl = panel.querySelector("[data-barracks-troops-error]");

    panel.addEventListener("click", function (e) {
      var maxBtn = e.target.closest("[data-troop-max]");
      if (maxBtn && panel.contains(maxBtn)) {
        e.preventDefault();
        var maxKey = maxBtn.getAttribute("data-troop-max");
        var qtyInp = panel.querySelector('[data-troop-amount="' + maxKey + '"]');
        var maxQty = normalizeGameplayInteger(
          maxBtn.dataset.maxQty || maxBtn.getAttribute("data-max-qty") || "0"
        );
        if (qtyInp && isPositiveGameplayInteger(maxQty)) {
          setGameplayIntegerInput(qtyInp, maxQty);
          var card = maxBtn.closest("[data-troop-card], [data-troop-key]");
          if (card) syncUnitCardCostPreview(card, militaryPageResources(page));
        }
        return;
      }

      var trainBtn = e.target.closest("[data-troop-train]");
      var cancelBtn = e.target.closest("[data-troop-cancel]");
      if (!trainBtn && !cancelBtn) return;
      e.preventDefault();

      if (trainBtn) {
        var key = trainBtn.getAttribute("data-troop-train");
        var amountInp = panel.querySelector('[data-troop-amount="' + key + '"]');
        var amount = readGameplayIntegerInput(amountInp);
        trainBtn.disabled = true;
        if (errEl) {
          errEl.hidden = true;
          errEl.textContent = "";
        }
        GC.fetchGameAction("/api/troops/train", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            planet_id: planetId ? Number(planetId) : undefined,
            troop_key: key,
            amount: amount,
          }),
        })
          .then(function (res) {
            if (res && res.ok) {
              if (res.state) applyActionState(res, "troops_train");
              applyTroopsPayload(panel, (res.data && res.data.troops) || res.troops);
              showNotify(t("troops_train_ok", "Ausbildung gestartet."), "success");
            } else {
              var msg = reasonText((res && (res.error || res.reason)) || "generic");
              if (errEl) {
                errEl.textContent = msg;
                errEl.hidden = false;
              }
              if (res) applyActionState(res, "troops_train_error");
            }
          })
          .catch(function () {
            if (errEl) {
              errEl.textContent = reasonText("generic");
              errEl.hidden = false;
            }
          })
          .finally(function () {
            trainBtn.disabled = false;
          });
        return;
      }

      if (cancelBtn) {
        var jobId = Number(cancelBtn.getAttribute("data-troop-cancel") || 0);
        if (!jobId) return;
        cancelBtn.disabled = true;
        GC.fetchGameAction("/api/troops/cancel", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            planet_id: planetId ? Number(planetId) : undefined,
            job_id: jobId,
          }),
        })
          .then(function (res) {
            if (res && res.ok) {
              if (res.state) applyActionState(res, "troops_cancel");
              applyTroopsPayload(panel, (res.data && res.data.troops) || res.troops);
            } else if (errEl) {
              errEl.textContent = reasonText((res && (res.error || res.reason)) || "generic");
              errEl.hidden = false;
            }
          })
          .finally(function () {
            cancelBtn.disabled = false;
          });
      }
    });
  }

  function bindDefenseOnce() {
    if (_defenseBound) return;
    _defenseBound = true;
    var apiError = function (res) {
      return (res && (res.error || res.reason)) || "generic";
    };

    document.addEventListener("click", async function (e) {
      var page = document.getElementById("defense-page");
      if (!page || page.dataset.ready !== "1") return;

      var maxBtn = e.target.closest("[data-defense-max]");
      if (maxBtn && page.contains(maxBtn)) {
        e.preventDefault();
        var dk = maxBtn.getAttribute("data-defense-max");
        var qtyInp = page.querySelector('[data-defense-qty="' + dk + '"]');
        var maxQty = normalizeGameplayInteger(
          maxBtn.dataset.maxQty || maxBtn.getAttribute("data-max-qty") || "0"
        );
        if (qtyInp && isPositiveGameplayInteger(maxQty)) {
          setGameplayIntegerInput(qtyInp, maxQty);
          var card = maxBtn.closest("[data-defense-card]");
          if (card) syncUnitCardCostPreview(card, militaryPageResources(page));
        }
        return;
      }

      var cancelBtn = e.target.closest("[data-defense-queue-cancel]");
      if (cancelBtn && page.contains(cancelBtn)) {
        e.preventDefault();
        var jobId = parseInt(cancelBtn.getAttribute("data-defense-queue-cancel") || "0", 10);
        var planetId = parseInt(page.dataset.planetId || "0", 10);
        if (!jobId) return;
        cancelBtn.disabled = true;
        try {
          var res = await GC.fetchGameAction("/api/defense/cancel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job_id: jobId, planet_id: planetId || undefined }),
          });
          if (res && res.ok) {
            if (res.state) applyActionState(res, "defense_cancel");
            var payload = normalizeDefenseApiPayload(res);
            if (payload) applyDefenseState(page, payload, res.state ? { skipQueue: true } : undefined);
            else await refreshDefenseState(page);
          } else {
            showNotify(reasonText((res && res.error) || apiError(res)), "error");
          }
        } catch (_) {
          showNotify(reasonText("generic"), "error");
        } finally {
          cancelBtn.disabled = false;
        }
        return;
      }

      var buildBtn = e.target.closest("[data-defense-build]");
      if (!buildBtn || !page.contains(buildBtn) || buildBtn.disabled) return;
      if (buildBtn.dataset.building === "1" || buildBtn.dataset.canBuild === "0") return;
      e.preventDefault();
      var defenseKey = buildBtn.getAttribute("data-defense-build");
      var qtyInpBuild = page.querySelector('[data-defense-qty="' + defenseKey + '"]');
      var amount = readGameplayIntegerInput(qtyInpBuild);
      var planetIdBuild = parseInt(page.dataset.planetId || "0", 10);
      buildBtn.dataset.building = "1";
      buildBtn.disabled = true;
      buildBtn.classList.add("is-loading");
      try {
        var buildRes = await GC.fetchGameAction("/api/defense/build", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            defense_key: defenseKey,
            amount: amount,
            planet_id: planetIdBuild || undefined,
          }),
        });
        if (buildRes && buildRes.ok) {
          clearDefenseQueueSignature();
          if (buildRes.state) applyActionState(buildRes, "defense_build");
          var buildPayload = normalizeDefenseApiPayload(buildRes);
          if (buildPayload) {
            applyDefenseState(page, buildPayload, buildRes.state ? { skipQueue: true } : undefined);
          } else if (!buildRes.state) {
            await refreshDefenseState(page);
          }
          if (buildRes.state && typeof GC.finalizeTimekeeperQueueButtons === "function") {
            GC.finalizeTimekeeperQueueButtons(GC.lastState || buildRes.state);
          }
        } else {
          showNotify(reasonText((buildRes && buildRes.error) || apiError(buildRes)), "error");
        }
      } catch (_) {
        showNotify(reasonText("generic"), "error");
      } finally {
        delete buildBtn.dataset.building;
        buildBtn.classList.remove("is-loading");
        buildBtn.disabled = buildBtn.dataset.canBuild !== "1";
      }
    });
  }

  function initDefense() {
    bindDefenseOnce();
    var page = document.getElementById("defense-page");
    if (!page || page.dataset.ready !== "1") return;
    bindDefenseTabs(page);
    bindBarracksTroops(page);
    var data =
      typeof GC.parseDefensePageData === "function" ? GC.parseDefensePageData(page) : null;
    if (!data) return;
    applyDefenseState(page, data);
    if (typeof GC.startDefenseTimers === "function") GC.startDefenseTimers();
    if (typeof GC.registerCleanup === "function" && typeof GC.stopDefenseTimers === "function") {
      GC.registerCleanup(GC.stopDefenseTimers);
    }
    if (typeof GC.startProgressTicker === "function") GC.startProgressTicker();
  }

  GC.pages.defense = {
    bindOnce: bindDefenseOnce,
    init: initDefense,
  };
  GC.modules.defense = initDefense;
})(typeof window !== "undefined" ? window : globalThis);
