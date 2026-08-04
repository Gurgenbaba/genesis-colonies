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

  function applyTroopsPayload(panel, troops) {
    if (!panel || !troops) return;
    var totalEl = panel.querySelector("[data-barracks-troops-total]");
    var capEl = panel.querySelector("[data-barracks-troops-capacity]");
    if (totalEl) totalEl.textContent = String(troops.total || 0);
    if (capEl) capEl.textContent = String(troops.capacity || 0);
    (troops.units || []).forEach(function (u) {
      var stock = panel.querySelector('[data-troop-stock="' + u.key + '"]');
      if (stock) stock.textContent = "×" + String(u.amount || 0);
    });
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
      var trainBtn = e.target.closest("[data-troop-train]");
      var cancelBtn = e.target.closest("[data-troop-cancel]");
      if (!trainBtn && !cancelBtn) return;
      e.preventDefault();

      if (trainBtn) {
        var key = trainBtn.getAttribute("data-troop-train");
        var amountInp = panel.querySelector('[data-troop-amount="' + key + '"]');
        var amount = Math.max(1, parseIntNumber(amountInp && amountInp.value) || 1);
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
              var row = cancelBtn.closest("[data-troop-job-id]");
              if (row) row.remove();
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
        var maxQty = parseIntNumber(
          maxBtn.dataset.maxQty || maxBtn.getAttribute("data-max-qty") || "0"
        );
        if (qtyInp && maxQty > 0) {
          qtyInp.dataset.inputMax = String(maxQty);
          setNumberInputValue(qtyInp, maxQty);
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
      var amount = readNumberInput(qtyInpBuild) || 1;
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
