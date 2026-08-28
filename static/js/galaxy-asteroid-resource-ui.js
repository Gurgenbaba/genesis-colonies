(() => {
  "use strict";

  const quickAction = window.GC?.GalaxyQuickAction;
  if (!quickAction || typeof quickAction.renderAsteroidFlightPreview !== "function") return;

  const originalRender = quickAction.renderAsteroidFlightPreview.bind(quickAction);
  const legacyFuelGlyph = String.fromCodePoint(0x26fd);

  quickAction.renderAsteroidFlightPreview = function renderAsteroidFlightPreviewWithResourceIcon(
    wrap,
    preview,
    sendCount
  ) {
    originalRender(wrap, preview, sendCount);

    if (!wrap || wrap.classList.contains("galaxy-ring-asteroid-wrap")) return;
    const line = wrap.querySelector("[data-galaxy-asteroid-flight-preview]");
    if (!line) return;

    const value = String(line.textContent || "");
    line.textContent = value.startsWith(`${legacyFuelGlyph} `)
      ? value.slice(legacyFuelGlyph.length + 1)
      : value;
  };
})();
