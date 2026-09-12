(function () {
  "use strict";

  var GC = (window.GC = window.GC || {});
  if (GC._planetScopeInstantHotfixBootstrapRegistered) return;
  GC._planetScopeInstantHotfixBootstrapRegistered = true;

  function requestPath(input) {
    var raw = typeof input === "string" ? input : input && typeof input.url === "string" ? input.url : "";
    if (!raw) return "";
    try {
      return new URL(raw, window.location.href).pathname;
    } catch (_) {
      return raw.split("?", 1)[0];
    }
  }

  function requestedPlanetId(options) {
    if (!options || !options.body) return 0;
    var body = options.body;
    if (typeof body === "string") {
      try {
        body = JSON.parse(body);
      } catch (_) {
        return 0;
      }
    }
    if (!body || typeof body !== "object") return 0;
    return Number(body.planet_id || 0);
  }

  function actionState(response) {
    if (!response || typeof response !== "object") return null;
    return response.state || (response.data && response.data.state) || null;
  }

  function statePlanetId(state) {
    if (!state || typeof state !== "object") return 0;
    if (state.active_planet_id != null) return Number(state.active_planet_id || 0);
    var active = state.active_planet;
    if (active && typeof active === "object") {
      return Number(active.planet_id || active.id || 0);
    }
    return 0;
  }

  function syncMountedPlanetScope(planetId) {
    if (!(planetId > 0)) return;
    [
      "#buildings-page",
      "#shipyard-page",
      "#defense-page",
      "#fleet-page",
      "#trader-hub-page",
      "#overview-wrapper",
      ".planet-evolution-page[data-planet-id]",
    ].forEach(function (selector) {
      var node = document.querySelector(selector);
      if (node) node.setAttribute("data-planet-id", String(planetId));
    });
  }

  /**
   * Never leave a previous colony's stock visible below the newly selected
   * planet identity. The canonical scoped panel/fleet refresh replaces these
   * placeholders with the new planet's authoritative values immediately after
   * the switch action. This intentionally performs no gameplay calculation.
   */
  function maskPreviousPlanetStock() {
    document.querySelectorAll("[data-shipyard-stock]").forEach(function (node) {
      node.textContent = "✦ …";
    });
    document.querySelectorAll("[data-defense-stock]").forEach(function (node) {
      node.textContent = "…";
    });
    document.querySelectorAll("[data-fleet-ship-stock]").forEach(function (node) {
      node.textContent = "×…";
    });
  }

  function applyPlanetScopeImmediately(response, requestedId) {
    var state = actionState(response);
    if (!state || typeof state !== "object") return false;

    var planetId = statePlanetId(state);
    if (!(planetId > 0)) return false;
    if (requestedId > 0 && requestedId !== planetId) return false;

    // The switch response already contains authoritative projected resources,
    // energy/storage and the active-planet identity. Paint the shell before the
    // normal planet-switch caller gets the response back.
    if (typeof GC.patchShellHudFromState === "function") {
      GC.patchShellHudFromState(state, {
        forceResourceBar: true,
        reason: "planet_switch_scope_hotfix",
      });
    }

    // Building levels are also part of the deliberately slim switch state.
    if (
      GC.instantFeedback &&
      typeof GC.instantFeedback.patchPlanetBuildingLevels === "function"
    ) {
      GC.instantFeedback.patchPlanetBuildingLevels(state);
    }

    syncMountedPlanetScope(planetId);
    maskPreviousPlanetStock();

    // Account research is empire-wide by design and must NOT be rewritten per
    // planet. Planet-Evolution research is planet-scoped; that page is reloaded
    // by the canonical planet-switch flow, so it never gets client-side math.
    return true;
  }

  function install() {
    GC = window.GC = window.GC || {};
    if (GC._planetScopeInstantHotfixInstalled || typeof GC.fetchGameAction !== "function") return;

    var previousFetchGameAction = GC.fetchGameAction;
    GC.fetchGameAction = async function planetScopeInstantFetchGameAction(url, options) {
      var isPlanetSwitch = requestPath(url) === "/api/planets/active";
      var requestedId = isPlanetSwitch ? requestedPlanetId(options) : 0;
      var response = await previousFetchGameAction.call(this, url, options);

      if (isPlanetSwitch && response && response.ok !== false) {
        try {
          applyPlanetScopeImmediately(response, requestedId);
        } catch (_) {
          // Acceleration is fail-open. Existing canonical switch/reconcile flow
          // remains the source of truth and will repair the UI on any failure.
        }
      }
      return response;
    };

    GC._planetScopeInstantHotfixInstalled = true;
    GC.planetScopeInstantHotfix = {
      applyPlanetScopeImmediately: applyPlanetScopeImmediately,
      maskPreviousPlanetStock: maskPreviousPlanetStock,
      syncMountedPlanetScope: syncMountedPlanetScope,
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
