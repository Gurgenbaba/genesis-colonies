/**
 * GC-PERF-JS-001 — PJAX lifecycle extension point.
 * Canonical cleanup remains GC.cleanupPage / GC.registerCleanup in main.js.
 */
(function (global) {
  "use strict";
  var GC = global.GC || (global.GC = {});
  GC.core = GC.core || {};
  GC.core.lifecycle = {
    cleanupPage: function () {
      if (typeof GC.cleanupPage === "function") {
        return GC.cleanupPage();
      }
    },
    registerCleanup: function (fn) {
      if (typeof GC.registerCleanup === "function") {
        return GC.registerCleanup(fn);
      }
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
