/**
 * GC-PERF-JS-001 — Core namespace bootstrap.
 * Page modules live under static/js/pages/; main.js remains the monolith owner
 * until split tickets move handlers here. Single GC namespace, one poll, one PJAX lifecycle.
 */
(function (global) {
  "use strict";
  var GC = (global.GC = global.GC || {});
  GC.core = GC.core || {};
  GC.pages = GC.pages || {};
  GC.core.perfJsSplit = { version: 1, ticket: "GC-PERF-JS-001" };
})(typeof window !== "undefined" ? window : globalThis);
