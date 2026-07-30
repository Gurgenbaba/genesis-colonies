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
  GC.core.perfJsSplit = { version: 2, ticket: "GC-PERF-JS-002" };

  /** GC-PERF-IMG: prefer sibling .webp for static rasters; keep query string. */
  GC.preferWebpStaticUrl = function preferWebpStaticUrl(url) {
    var text = String(url || "").trim();
    if (!text) return text;
    var q = text.indexOf("?");
    var path = q >= 0 ? text.slice(0, q) : text;
    var query = q >= 0 ? text.slice(q) : "";
    if (/\.webp$/i.test(path)) return text;
    if (/\.(png|jpe?g)$/i.test(path)) {
      return path.replace(/\.(png|jpe?g)$/i, ".webp") + query;
    }
    return text;
  };

  /** PNG/JPG fallback when a WebP primary 404s (attach as img.onerror). */
  GC.webpImgOnError = function webpImgOnError(img) {
    if (!img || img.dataset.gcWebpFallback === "1") return;
    var src = String(img.currentSrc || img.src || "");
    var q = src.indexOf("?");
    var path = q >= 0 ? src.slice(0, q) : src;
    var query = q >= 0 ? src.slice(q) : "";
    if (!/\.webp$/i.test(path)) return;
    img.dataset.gcWebpFallback = "1";
    img.src = path.replace(/\.webp$/i, ".png") + query;
  };
})(typeof window !== "undefined" ? window : globalThis);
