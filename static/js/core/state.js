/**
 * GC-PERF-JS-001 — State extension point (single state source remains main.js).
 * Future: move applyActionState / applyHudOnlyGameState owners here without a second poller.
 */
(function (global) {
  "use strict";
  var GC = global.GC || (global.GC = {});
  GC.core = GC.core || {};
  GC.core.state = {
    /** Prefer GC.applyActionState from main.js — this only documents the contract. */
    applyActionState: function (json, reason) {
      if (typeof GC.applyActionState === "function") {
        return GC.applyActionState(json, reason);
      }
      return null;
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
