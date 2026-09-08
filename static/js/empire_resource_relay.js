/* GC-MANDO-RELAY-001 — instant own-empire resource consolidation, no Fleet movement. */
(() => {
  "use strict";

  const GC = window.GC || (window.GC = {});
  if (GC.EmpireResourceRelayBound) return;
  GC.EmpireResourceRelayBound = true;

  const t = (key) => (typeof GC.t === "function" ? GC.t(key, key) : key);
  const page = () => document.getElementById("logistics-page");

  const selectedSourceIds = (root) =>
    Array.from(root?.querySelectorAll('[data-logistics-colony-cb="collect"]:checked') || [])
      .filter((input) => !input.disabled)
      .map((input) => parseInt(input.value || "0", 10))
      .filter((value) => value > 0);

  const hubId = (root) => {
    const select = root?.querySelector("[data-logistics-hub]");
    return parseInt(select?.value || "0", 10) || 0;
  };

  const relayButton = (root) => root?.querySelector('[data-resource-relay-submit="collect"]');

  const syncButton = (root) => {
    const btn = relayButton(root);
    if (!btn || btn.getAttribute("aria-busy") === "true") return;
    btn.disabled = !hubId(root) || selectedSourceIds(root).length === 0;
  };

  const setBusy = (btn, busy) => {
    if (!btn) return;
    btn.setAttribute("aria-busy", busy ? "true" : "false");
    btn.disabled = Boolean(busy);
  };

  const fmt = (value) =>
    typeof GC.fmtGameplayInteger === "function" ? GC.fmtGameplayInteger(value) : String(value ?? "0");

  const patchResourceNode = (node, value) => {
    if (!node) return;
    node.textContent = fmt(value);
    node.setAttribute("title", fmt(value));
  };

  const patchLogisticsResources = (root, payload) => {
    const hub = payload?.hub_resources || {};
    ["metal", "crystal", "fuel_cells"].forEach((key) => {
      patchResourceNode(root.querySelector(`[data-logistics-hub-res="${key}"]`), hub[key] ?? 0);
    });

    const colonies = payload?.colony_resources || {};
    Object.entries(colonies).forEach(([planetId, resources]) => {
      const card = root.querySelector(`[data-colony-planet-id="${CSS.escape(String(planetId))}"]`);
      if (!card) return;
      ["metal", "crystal", "fuel_cells"].forEach((key) => {
        patchResourceNode(card.querySelector(`[data-logistics-colony-res="${key}"]`), resources?.[key] ?? 0);
      });
    });
  };

  const showResult = (root, message, kind) => {
    const host = root?.querySelector("[data-resource-relay-result]");
    if (host) {
      host.hidden = false;
      host.textContent = message;
      host.dataset.kind = kind || "info";
    }
    if (typeof GC.showNotify === "function") GC.showNotify(message, kind || "info");
  };

  const requestId = () => {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return `relay-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  };

  const runRelay = async (root, btn) => {
    const targetPlanetId = hubId(root);
    const sourcePlanetIds = selectedSourceIds(root);
    if (!targetPlanetId || !sourcePlanetIds.length) {
      showResult(root, t("logistics_collect_incomplete"), "error");
      syncButton(root);
      return;
    }

    setBusy(btn, true);
    try {
      if (typeof GC.fetchGameAction !== "function") throw new Error("relay_fetch_unavailable");
      const response = await GC.fetchGameAction("/api/logistics/relay/collect", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-GC-Dom-Planet-Id": String(targetPlanetId),
        },
        body: JSON.stringify({
          target_planet_id: targetPlanetId,
          source_planet_ids: sourcePlanetIds,
          request_id: requestId(),
        }),
      });

      if (!response?.ok) {
        const reason = String(response?.reason || response?.error || "generic");
        const key = reason === "vacation_mode" ? "fleet_error_vacation_mode" : `fleet_error_${reason}`;
        showResult(root, t(key) === key ? t("fleet_error_generic") : t(key), "error");
        return;
      }

      patchLogisticsResources(root, response.data || {});
      root.querySelectorAll('[data-logistics-colony-cb="collect"]').forEach((input) => {
        input.checked = false;
      });
      showResult(root, t("logistics_collect_success"), "success");

      if (typeof GC.refreshGameState === "function") {
        Promise.resolve(GC.refreshGameState()).catch(() => {});
      }
    } catch (_) {
      showResult(root, t("fleet_error_generic"), "error");
    } finally {
      setBusy(btn, false);
      syncButton(root);
    }
  };

  document.addEventListener("change", (event) => {
    const root = page();
    if (!root) return;
    const target = event.target;
    if (
      target?.matches?.('[data-logistics-colony-cb="collect"]') ||
      target?.matches?.("[data-logistics-hub]") ||
      target?.matches?.('[data-logistics-select-all="collect"]')
    ) {
      queueMicrotask(() => syncButton(root));
    }
  });

  document.addEventListener("click", (event) => {
    const btn = event.target.closest?.('[data-resource-relay-submit="collect"]');
    const root = page();
    if (!btn || !root || !root.contains(btn)) return;
    event.preventDefault();
    runRelay(root, btn);
  });

  const observer = new MutationObserver(() => syncButton(page()));
  const shell = document.getElementById("main-content") || document.body;
  observer.observe(shell, { childList: true, subtree: true });
  syncButton(page());

  window.addEventListener("pagehide", () => observer.disconnect(), { once: true });
})();
