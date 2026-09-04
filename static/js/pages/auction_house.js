/** P0-D — exact Auction bid transport without Number coercion. */
(function (global) {
  "use strict";

  var GC = global.GC || (global.GC = {});
  GC.pages = GC.pages || {};
  GC.modules = GC.modules || {};

  var bound = false;

  function normalizeGameplayInteger(value) {
    if (typeof GC.normalizeGameplayInteger === "function") {
      return GC.normalizeGameplayInteger(value);
    }
    var raw = String(value == null ? "0" : value).trim().replace(/[\s._,'’]/g, "");
    return /^-?\d+$/.test(raw) ? raw : "0";
  }

  function compareGameplayIntegers(a, b) {
    if (typeof GC.compareGameplayIntegers === "function") {
      return GC.compareGameplayIntegers(a, b);
    }
    try {
      var left = BigInt(normalizeGameplayInteger(a));
      var right = BigInt(normalizeGameplayInteger(b));
      return left < right ? -1 : left > right ? 1 : 0;
    } catch (_) {
      return 0;
    }
  }

  function formatGameplayInteger(value) {
    if (typeof GC.fmtGameplayInteger === "function") {
      return GC.fmtGameplayInteger(value);
    }
    return normalizeGameplayInteger(value);
  }

  function notify(message, category) {
    if (typeof GC.showNotify === "function") {
      GC.showNotify(message, category || "error");
    }
  }

  function errorText(reason) {
    if (typeof GC.t === "function") {
      return GC.t("auction_house_error_" + String(reason || "generic"), String(reason || "error"));
    }
    return String(reason || "error");
  }

  function refreshAuctionPage() {
    if (typeof GC.navigateTo === "function") {
      return GC.navigateTo(global.location.pathname + global.location.search, { replace: true });
    }
    global.location.reload();
    return Promise.resolve();
  }

  function bindAuctionHouseOnce() {
    if (bound) return;
    bound = true;

    document.addEventListener(
      "submit",
      function (event) {
        var form = event.target && event.target.closest
          ? event.target.closest("[data-auction-bid-form]")
          : null;
        var page = document.getElementById("auction-house-page");
        if (!form || !page || !page.contains(form)) return;

        event.preventDefault();
        event.stopImmediatePropagation();

        var listingId = form.getAttribute("data-auction-bid-form") ||
          (form.querySelector('[name="listing_id"]') || {}).value ||
          "0";
        var currency = String(
          ((form.querySelector('[name="currency"]') || {}).value || "")
        ).trim();
        var input = form.querySelector("[data-auction-bid-input]");
        var submit = form.querySelector("[data-auction-bid-submit]");
        var errorEl = form.querySelector("[data-auction-form-error]");
        var card = form.closest("[data-auction-card]");
        var minBid = normalizeGameplayInteger(
          (card && card.getAttribute("data-min-bid")) ||
          (input && input.getAttribute("min")) ||
          "0"
        );
        var amount = normalizeGameplayInteger(input && input.value);

        if (compareGameplayIntegers(amount, "0") <= 0) {
          if (errorEl) {
            errorEl.hidden = false;
            errorEl.textContent = errorText("invalid_amount");
          }
          return;
        }
        if (compareGameplayIntegers(amount, minBid) < 0) {
          if (errorEl) {
            errorEl.hidden = false;
            errorEl.textContent = errorText("bid_too_low");
          }
          if (input) input.value = formatGameplayInteger(minBid);
          return;
        }

        if (errorEl) {
          errorEl.hidden = true;
          errorEl.textContent = "";
        }
        if (submit) submit.disabled = true;

        var action = form.getAttribute("action") || "/api/auction-house/bid";
        var doFetch = typeof GC.fetchGameAction === "function"
          ? GC.fetchGameAction(action, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                listing_id: Number(listingId) || 0,
                amount: amount,
                currency: currency,
              }),
            })
          : fetch(action, {
              method: "POST",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                listing_id: Number(listingId) || 0,
                amount: amount,
                currency: currency,
              }),
            }).then(function (response) { return response.json(); });

        Promise.resolve(doFetch)
          .then(function (res) {
            if (!res || !res.ok) {
              var reason = (res && (res.reason || res.error)) || "generic";
              if (errorEl) {
                errorEl.hidden = false;
                errorEl.textContent = errorText(reason);
              }
              notify(errorText(reason), "error");
              return;
            }
            if (res.state && typeof GC.applyActionState === "function") {
              GC.applyActionState(res, "auction_house_bid");
            }
            return refreshAuctionPage();
          })
          .catch(function () {
            if (errorEl) {
              errorEl.hidden = false;
              errorEl.textContent = errorText("generic");
            }
            notify(errorText("generic"), "error");
          })
          .finally(function () {
            if (submit) submit.disabled = false;
          });
      },
      true
    );
  }

  function initAuctionHouse() {
    bindAuctionHouseOnce();
  }

  GC.pages.auctionHouse = {
    bindOnce: bindAuctionHouseOnce,
    init: initAuctionHouse,
  };
  GC.modules.auctionHouse = initAuctionHouse;
  initAuctionHouse();
})(typeof window !== "undefined" ? window : globalThis);
