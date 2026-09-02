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

  /**
   * GC-PJAX-RESILIENCE-001 — transient gateway protection for read-only live polls.
   *
   * A Railway/container handover can make several independent GET pollers receive
   * 502 at the same time. Retrying each poller immediately creates a thundering herd,
   * so the selected read endpoints share one short backoff window. Mutating requests
   * are intentionally excluded: actions keep their existing idempotency/error flow.
   */
  (function installGatewayBackoff() {
    if (typeof global.fetch !== "function" || global.fetch.__gcGatewayBackoffWrapped) return;

    var nativeFetch = global.fetch.bind(global);
    var targetPaths = {
      "/api/game-state": true,
      "/api/world-boss": true,
      "/api/notifications/summary": true,
      "/api/chat/messages": true,
    };
    var failureStreak = 0;
    var backoffUntil = 0;
    var maxRetries = 2;

    function abortError() {
      try {
        return new DOMException("The operation was aborted.", "AbortError");
      } catch (_) {
        var err = new Error("The operation was aborted.");
        err.name = "AbortError";
        return err;
      }
    }

    function sleep(ms, signal) {
      var waitMs = Math.max(0, Number(ms) || 0);
      if (!waitMs) return Promise.resolve();
      if (signal && signal.aborted) return Promise.reject(abortError());
      return new Promise(function (resolve, reject) {
        var timer = global.setTimeout(done, waitMs);
        function cleanup() {
          if (signal && typeof signal.removeEventListener === "function") {
            signal.removeEventListener("abort", onAbort);
          }
        }
        function done() {
          cleanup();
          resolve();
        }
        function onAbort() {
          global.clearTimeout(timer);
          cleanup();
          reject(abortError());
        }
        if (signal && typeof signal.addEventListener === "function") {
          signal.addEventListener("abort", onAbort, { once: true });
        }
      });
    }

    function requestMeta(input, init) {
      var method = String(
        (init && init.method) || (input && typeof input === "object" && input.method) || "GET"
      ).toUpperCase();
      var rawUrl = typeof input === "string" ? input : input && input.url;
      if (!rawUrl) return null;
      try {
        var base = global.location && global.location.href ? global.location.href : "http://localhost/";
        var url = new URL(rawUrl, base);
        var sameOrigin = !global.location || !global.location.origin || url.origin === global.location.origin;
        return {
          method: method,
          pathname: url.pathname,
          sameOrigin: sameOrigin,
          signal:
            (init && init.signal) ||
            (input && typeof input === "object" && input.signal) ||
            null,
        };
      } catch (_) {
        return null;
      }
    }

    function isProtectedRead(meta) {
      return Boolean(meta && meta.sameOrigin && meta.method === "GET" && targetPaths[meta.pathname]);
    }

    function nextBackoffMs() {
      failureStreak = Math.min(failureStreak + 1, 5);
      var base = Math.min(3000, 450 * Math.pow(2, failureStreak - 1));
      var jitter = Math.floor(Math.random() * 180);
      return Math.round(base + jitter);
    }

    async function gcFetch(input, init) {
      var meta = requestMeta(input, init);
      if (!isProtectedRead(meta)) return nativeFetch(input, init);

      var attempt = 0;
      while (true) {
        var sharedDelay = Math.max(0, backoffUntil - Date.now());
        if (sharedDelay > 0) await sleep(sharedDelay, meta.signal);

        var response = await nativeFetch(input, init);
        if (!response || response.status !== 502) {
          if (failureStreak > 0) failureStreak -= 1;
          return response;
        }

        if (attempt >= maxRetries) return response;
        attempt += 1;
        var delay = nextBackoffMs();
        backoffUntil = Math.max(backoffUntil, Date.now() + delay);
      }
    }

    gcFetch.__gcGatewayBackoffWrapped = true;
    gcFetch.__gcNativeFetch = nativeFetch;
    global.fetch = gcFetch;

    GC.core.gatewayBackoff = {
      protectedPaths: Object.keys(targetPaths),
      snapshot: function snapshot() {
        return {
          failureStreak: failureStreak,
          backoffRemainingMs: Math.max(0, backoffUntil - Date.now()),
          maxRetries: maxRetries,
        };
      },
    };
  })();

  /**
   * GC-PJAX-RESILIENCE-001 — keep preload hints useful.
   *
   * SSR image preloads are already present before this script executes and remain
   * untouched. main.js may create a GC LCP preload only after a PJAX DOM swap; at
   * that point the real <img> request has already started, so Chrome reports the
   * late preload as unused. Suppress only those GC-owned dynamic image hints.
   */
  (function installLatePjaxPreloadGuard() {
    var head = global.document && global.document.head;
    if (!head || head.__gcLatePjaxPreloadGuard) return;
    var nativeAppendChild = head.appendChild.bind(head);

    head.appendChild = function appendChildWithGcPreloadGuard(node) {
      var isLateGcImagePreload = Boolean(
        node &&
          node.nodeType === 1 &&
          String(node.tagName || "").toUpperCase() === "LINK" &&
          String(node.rel || "").toLowerCase() === "preload" &&
          String(node.as || "").toLowerCase() === "image" &&
          node.dataset &&
          (node.dataset.gcLcpPreload === "1" || node.dataset.gcFramePreload === "1")
      );
      if (isLateGcImagePreload) {
        node.dataset.gcPjaxPreloadSuppressed = "1";
        return node;
      }
      return nativeAppendChild(node);
    };

    head.__gcLatePjaxPreloadGuard = true;
  })();

  /**
   * GC-PJAX-RESILIENCE-001 — one Messages init per live #messages-page root.
   *
   * main.js intentionally has a special Messages boot path. During a fast PJAX
   * transition the module runner can be reached more than once; messages.js then
   * resets its state and starts another inbox load. Guard the exported init entry
   * points while preserving a fresh init whenever PJAX swaps in a new root node.
   */
  (function installMessagesInitGuard() {
    GC.modules = GC.modules || {};

    var implementation = null;
    var lastRoot = null;
    var lastNoRootAt = 0;
    var modules = GC.modules;

    function guardedMessagesInit(options) {
      if (typeof implementation !== "function") return undefined;
      var root = global.document && global.document.getElementById("messages-page");
      var force = Boolean(options && options.force === true);

      if (root) {
        if (!force && root === lastRoot) return GC.messagesPageState || undefined;
        lastRoot = root;
      } else if (!force) {
        var now = Date.now();
        if (now - lastNoRootAt < 100) return undefined;
        lastNoRootAt = now;
      }

      return implementation.apply(this, arguments);
    }

    function bindGuardedProperty(owner, key) {
      var existing = owner[key];
      if (typeof existing === "function") implementation = existing;
      try {
        Object.defineProperty(owner, key, {
          configurable: true,
          enumerable: true,
          get: function () {
            return typeof implementation === "function" ? guardedMessagesInit : undefined;
          },
          set: function (fn) {
            if (typeof fn === "function" && fn !== guardedMessagesInit) implementation = fn;
          },
        });
      } catch (_) {
        // Older/embedded browsers: keep the existing behavior instead of breaking boot.
      }
    }

    bindGuardedProperty(modules, "messages");
    bindGuardedProperty(GC, "initMessagesPage");
    GC.core.messagesInitGuard = {
      reset: function reset() {
        lastRoot = null;
        lastNoRootAt = 0;
      },
    };
  })();
})(typeof window !== "undefined" ? window : globalThis);
