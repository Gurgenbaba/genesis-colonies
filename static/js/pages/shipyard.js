/**
 * GC-PERF-JS-002 — Shipyard page binder (extracted from main.js).
 * Mutations are state-first (GC-512D): applyActionState when res.state;
 * applyShipyardState only when res.data is present (stocks / page-local labels).
 * Queue/HUD ownership stays in main.js (applyActionState / patchShipyardPanelFromState).
 */
(function (global) {
  "use strict";

  var GC = global.GC || (global.GC = {});
  GC.pages = GC.pages || {};
  GC.modules = GC.modules || {};

  var _shipyardBound = false;

  function applyActionState(res, reason) {
    if (typeof GC.applyActionState === "function") return GC.applyActionState(res, reason);
    return false;
  }

  function applyShipyardState(page, data) {
    if (typeof GC.applyShipyardState === "function") GC.applyShipyardState(page, data);
  }

  function refreshShipyardState(page) {
    if (typeof GC.refreshShipyardState === "function") return GC.refreshShipyardState(page);
    return Promise.resolve(null);
  }

  function clearShipyardQueueSignature() {
    if (typeof GC.clearShipyardQueueSignature === "function") GC.clearShipyardQueueSignature();
  }

  function reasonText(reason) {
    if (typeof GC.shipyardActionReasonText === "function") return GC.shipyardActionReasonText(reason);
    return String(reason || "error");
  }

  function showNotify(msg, category) {
    if (typeof GC.showNotify === "function") GC.showNotify(msg, category);
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

  function bindShipyardOnce() {
    if (_shipyardBound) return;
    _shipyardBound = true;
    var apiError = function (res) {
      return (res && (res.error || res.reason)) || "cancel_failed";
    };

    document.addEventListener("click", async function (e) {
      var page = document.getElementById("shipyard-page");
      if (!page || page.dataset.ready !== "1") return;

      var maxBtn = e.target.closest("[data-shipyard-max]");
      if (maxBtn && page.contains(maxBtn)) {
        e.preventDefault();
        var shipKeyMax = maxBtn.getAttribute("data-shipyard-max");
        var qtyInpMax = page.querySelector('[data-shipyard-qty="' + shipKeyMax + '"]');
        var maxQty = parseIntNumber(
          maxBtn.dataset.maxQty || maxBtn.getAttribute("data-max-qty") || "0"
        );
        if (qtyInpMax && maxQty > 0) {
          qtyInpMax.dataset.inputMax = String(maxQty);
          setNumberInputValue(qtyInpMax, maxQty);
          var cardMax = maxBtn.closest("[data-ship-card]");
          if (cardMax) syncUnitCardCostPreview(cardMax, militaryPageResources(page));
        }
        return;
      }

      var cancelBtn = e.target.closest("[data-shipyard-queue-cancel]");
      if (cancelBtn && page.contains(cancelBtn)) {
        e.preventDefault();
        e.stopPropagation();
        var jobId = parseInt(cancelBtn.getAttribute("data-shipyard-queue-cancel") || "0", 10);
        var planetIdCancel = parseInt(page.dataset.planetId || "0", 10);
        if (!jobId || cancelBtn.dataset.busy === "1") return;
        cancelBtn.dataset.busy = "1";
        cancelBtn.disabled = true;
        try {
          var resCancel = await GC.fetchGameAction("/api/shipyard/queue/cancel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job_id: jobId, planet_id: planetIdCancel || undefined }),
          });
          if (resCancel && resCancel.ok) {
            clearShipyardQueueSignature();
            // GC-512D — state-first: HUD/queue via applyActionState; optional data for stocks/labels
            if (resCancel.state) {
              applyActionState(resCancel, "shipyard_cancel");
            }
            if (resCancel.data) {
              applyShipyardState(page, resCancel.data);
            } else if (!resCancel.state) {
              await refreshShipyardState(page);
              if (typeof GC.refreshGameState === "function") {
                await GC.refreshGameState("shipyard_cancel");
              }
            }
          } else {
            showNotify(reasonText((resCancel && resCancel.error) || apiError(resCancel)), "error");
          }
        } catch (_) {
          showNotify(reasonText("cancel_failed"), "error");
        } finally {
          delete cancelBtn.dataset.busy;
          cancelBtn.disabled = false;
        }
        return;
      }

      var moveUp = e.target.closest("[data-shipyard-queue-up]");
      var moveDown = e.target.closest("[data-shipyard-queue-down]");
      var moveBtn = moveUp || moveDown;
      if (moveBtn && page.contains(moveBtn)) {
        e.preventDefault();
        var jobIdMove = parseInt(
          moveBtn.getAttribute("data-shipyard-queue-up") ||
            moveBtn.getAttribute("data-shipyard-queue-down") ||
            "0",
          10
        );
        var planetIdMove = parseInt(page.dataset.planetId || "0", 10);
        if (!jobIdMove) return;
        moveBtn.disabled = true;
        try {
          var resMove = await GC.fetchGameAction("/api/shipyard/queue/move", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              job_id: jobIdMove,
              direction: moveUp ? "up" : "down",
              planet_id: planetIdMove || undefined,
            }),
          });
          if (resMove && resMove.ok) {
            clearShipyardQueueSignature();
            if (resMove.data) applyShipyardState(page, resMove.data);
            else await refreshShipyardState(page);
          } else {
            showNotify(reasonText((resMove && resMove.error) || apiError(resMove)), "error");
          }
        } catch (_) {
          showNotify(reasonText("generic"), "error");
        } finally {
          moveBtn.disabled = false;
        }
        return;
      }

      var buildBtn = e.target.closest("[data-shipyard-build]");
      if (!buildBtn || !page.contains(buildBtn) || buildBtn.disabled) return;
      if (buildBtn.dataset.building === "1" || buildBtn.dataset.canBuild === "0") return;
      e.preventDefault();
      var shipKey = buildBtn.getAttribute("data-shipyard-build");
      var qtyInp = page.querySelector('[data-shipyard-qty="' + shipKey + '"]');
      var amount = readNumberInput(qtyInp) || 1;
      var planetId = parseInt(page.dataset.planetId || "0", 10);
      buildBtn.dataset.building = "1";
      buildBtn.disabled = true;
      buildBtn.classList.add("is-loading");
      try {
        var res = await GC.fetchGameAction("/api/shipyard/build", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ship_key: shipKey, amount: amount, planet_id: planetId || undefined }),
        });
        if (res && res.ok) {
          clearShipyardQueueSignature();
          // GC-512D — state-first: applyActionState covers queue via patchShipyardPanelFromState
          if (res.state) {
            applyActionState(res, "shipyard_build");
          }
          // Optional data: page-local stocks / buildable card labels (not redundant queue math)
          if (res.data) {
            applyShipyardState(page, res.data);
          } else if (!res.state) {
            await refreshShipyardState(page);
          }
        } else {
          var errKey = (res && res.error) || apiError(res);
          showNotify(reasonText(errKey), "error");
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

  function initShipyard() {
    bindShipyardOnce();
    var page = document.getElementById("shipyard-page");
    if (!page || page.dataset.ready !== "1") return;
    var data =
      typeof GC.parseShipyardPageData === "function" ? GC.parseShipyardPageData(page) : null;
    if (!data) return;
    applyShipyardState(page, data);
    if (typeof GC.startShipyardTimers === "function") GC.startShipyardTimers();
    if (typeof GC.registerCleanup === "function" && typeof GC.stopShipyardTimers === "function") {
      GC.registerCleanup(GC.stopShipyardTimers);
    }
    if (typeof GC.startProgressTicker === "function") GC.startProgressTicker();
  }

  GC.pages.shipyard = {
    bindOnce: bindShipyardOnce,
    init: initShipyard,
  };
  GC.modules.shipyard = initShipyard;
})(typeof window !== "undefined" ? window : globalThis);
