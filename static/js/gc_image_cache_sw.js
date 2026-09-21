/* GC-PERF-IMG-001 — persistent cache-first layer for bundled Genesis art. */
"use strict";

const GC_IMAGE_CACHE_PREFIX = "gc-static-images-";
const GC_IMAGE_VERSION = new URL(self.location.href).searchParams.get("v") || "dev";
const GC_IMAGE_CACHE = GC_IMAGE_CACHE_PREFIX + GC_IMAGE_VERSION;

function isBundledGameImage(url) {
  return url.origin === self.location.origin && url.pathname.startsWith("/static/img/");
}

function canonicalImageCacheKey(url) {
  // Query params are cache-busters only for bundled static files. The cache
  // namespace already carries the asset version, so one file is stored once.
  return new Request(url.origin + url.pathname, {
    method: "GET",
    credentials: "same-origin",
  });
}

self.addEventListener("install", function (event) {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names
          .filter(function (name) {
            return name.startsWith(GC_IMAGE_CACHE_PREFIX) && name !== GC_IMAGE_CACHE;
          })
          .map(function (name) {
            return caches.delete(name);
          })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (!request || request.method !== "GET") return;
  if (request.headers && request.headers.has("range")) return;

  const url = new URL(request.url);
  if (!isBundledGameImage(url)) return;

  event.respondWith((async function () {
    const cache = await caches.open(GC_IMAGE_CACHE);
    const key = canonicalImageCacheKey(url);
    const cached = await cache.match(key);
    if (cached) return cached;

    const response = await fetch(request);
    if (response && response.ok && (response.type === "basic" || response.type === "cors")) {
      event.waitUntil(cache.put(key, response.clone()).catch(function () {}));
    }
    return response;
  })());
});
