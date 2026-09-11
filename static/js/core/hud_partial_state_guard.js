(function () {
  "use strict";

  function isObject(value) {
    return Boolean(value && typeof value === "object" && !Array.isArray(value));
  }

  function cloneObject(value) {
    return isObject(value) ? Object.assign({}, value) : null;
  }

  function preserveTimekeeperHudSlices(response) {
    var GC = window.GC || {};
    var previous = GC.lastState;
    var state = response && response.state;
    if (!isObject(state) || !isObject(previous)) return response;

    // Timekeeper uses a deliberately narrow action-state projection. Resource amounts
    // are authoritative in that response, while production/storage may be omitted.
    // Never let an omitted slice turn into client-side zeroes and blank the resource HUD.
    if (!isObject(state.production_per_hour)) {
      var previousProduction = cloneObject(previous.production_per_hour);
      if (previousProduction) state.production_per_hour = previousProduction;
    }

    var stateHasStorage = isObject(state.storage)
      || (isObject(state.resources) && isObject(state.resources.storage));
    if (!stateHasStorage) {
      var previousStorage = cloneObject(previous.storage);
      if (previousStorage) state.storage = previousStorage;

      if (isObject(state.resources)
          && isObject(previous.resources)
          && isObject(previous.resources.storage)
          && !isObject(state.resources.storage)) {
        state.resources = Object.assign({}, state.resources, {
          storage: Object.assign({}, previous.resources.storage),
        });
      }
    }

    return response;
  }

  function install() {
    var GC = window.GC = window.GC || {};
    if (GC._timekeeperHudPartialGuardInstalled) return;
    if (typeof GC.fetchGameAction !== "function") return;

    var originalFetchGameAction = GC.fetchGameAction;
    GC.fetchGameAction = async function guardedFetchGameAction(url, options) {
      var response = await originalFetchGameAction.call(this, url, options);
      var path = String(url || "");
      if (path.indexOf("/api/timekeeper/apply") !== -1) {
        preserveTimekeeperHudSlices(response);
      }
      return response;
    };
    GC._timekeeperHudPartialGuardInstalled = true;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
