/**
 * GC-PERF-JS-001 — Buildings page module scaffold.
 * Loaded only on /buildings via templates/buildings.html extra_scripts.
 */
(function (global) {
  "use strict";
  var GC = global.GC || (global.GC = {});
  GC.pages = GC.pages || {};
  GC.pages.buildings = {
    init: function () {
      if (typeof GC.registerCleanup === "function") {
        GC.registerCleanup(function () {});
      }
    },
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      GC.pages.buildings.init();
    });
  } else {
    GC.pages.buildings.init();
  }
})(typeof window !== "undefined" ? window : globalThis);
