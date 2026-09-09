/* GC-MANDO-RELAY-002 — shipless collect/distribute with per-planet cooldown UX. */
(() => {
  "use strict";

  const GC = window.GC || (window.GC = {});
  if (GC.EmpireRelayCooldownBound) return;
  GC.EmpireRelayCooldownBound = true;

  const state = {
    root: null,
    loaded: false,
    serverOffsetSec: 0,
    collect: {},
    distribute: {},
    timer: null,
  };

  const t = (key, fallback) =>
    typeof GC.t === "function" ? GC.t(key, fallback || key) : (fallback || key);

  const root = () => document.getElementById("logistics-page");
  const intString = (value) =>
    typeof GC.normalizeGameplayInteger === "function"
      ? GC.normalizeGameplayInteger(value)
      : String(value ?? "0").replace(/[^0-9-]/g, "") || "0";
  const big = (value) => {
    try {
      return BigInt(intString(value));
    } catch (_) {
      return 0n;
    }
  };
  const fmt = (value) =>
    typeof GC.fmtGameplayInteger === "function"
      ? GC.fmtGameplayInteger(value)
      : intString(value);

  function nowSec() {
    return Math.floor(Date.now() / 1000 + state.serverOffsetSec);
  }

  function formatCountdown(seconds) {
    const total = Math.max(0, Math.ceil(Number(seconds) || 0));
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    return String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
  }

  function hubId(page) {
    return parseInt(page?.querySelector("[data-logistics-hub]")?.value || "0", 10) || 0;
  }

  function cooldownMap(direction) {
    return direction === "distribute" ? state.distribute : state.collect;
  }

  function readyAt(direction, planetId) {
    return Math.max(0, Number(cooldownMap(direction)?.[String(planetId)] || 0));
  }

  function isReady(direction, planetId) {
    return state.loaded && readyAt(direction, planetId) <= nowSec();
  }

  function checkbox(page, direction, planetId) {
    return page?.querySelector(
      `[data-logistics-colony-cb="${direction}"][value="${CSS.escape(String(planetId))}"]`
    );
  }

  function syncHubPresentation(page) {
    if (!page) return;
    const hub = hubId(page);
    page.querySelectorAll("[data-colony-planet-id]").forEach((card) => {
      const pid = parseInt(card.getAttribute("data-colony-planet-id") || "0", 10) || 0;
      card.classList.toggle("is-hub", pid === hub);
    });

    ["collect", "distribute"].forEach((direction) => {
      page.querySelectorAll(`[data-logistics-colony-cb="${direction}"]`).forEach((input) => {
        const pid = parseInt(input.value || "0", 10) || 0;
        if (pid === hub) input.checked = false;
      });
    });

    const hubCard = page.querySelector(
      `[data-colony-planet-id="${CSS.escape(String(hub))}"]`
    );
    if (hubCard) {
      ["metal", "crystal", "fuel_cells"].forEach((key) => {
        const source = hubCard.querySelector(`[data-logistics-colony-res="${key}"]`);
        const target = page.querySelector(`[data-logistics-hub-res="${key}"]`);
        if (source && target) {
          target.textContent = source.textContent;
          target.setAttribute("title", source.getAttribute("title") || source.textContent || "");
        }
      });
    }
  }

  function syncCooldownUi(page) {
    if (!page) return;
    const hub = hubId(page);
    const current = nowSec();

    page.querySelectorAll("[data-resource-relay-cooldown]").forEach((node) => {
      const direction = node.getAttribute("data-resource-relay-cooldown") || "collect";
      const pid = parseInt(node.getAttribute("data-relay-planet-id") || "0", 10) || 0;
      const input = checkbox(page, direction, pid);
      const at = readyAt(direction, pid);
      const remaining = Math.max(0, at - current);
      const isHub = pid === hub;
      const ready = state.loaded && remaining <= 0 && !isHub;

      node.classList.toggle("is-ready", ready);
      node.classList.toggle("is-cooldown", state.loaded && remaining > 0);
      node.classList.toggle("is-hub", isHub);

      if (!state.loaded) {
        node.textContent = t("logistics_relay_loading", "…");
      } else if (isHub) {
        node.textContent = t("logistics_hub_colony_tag", "Hub");
      } else if (remaining > 0) {
        node.textContent =
          t("logistics_relay_cooldown", "CD") + " " + formatCountdown(remaining);
      } else {
        node.textContent = t("logistics_relay_ready", "BEREIT");
      }

      if (input) {
        // Cooldown blocks execution, not selection. Players can preselect a
        // colony while it cools down; the selection stays armed and becomes
        // executable automatically when the countdown reaches zero.
        input.disabled = isHub || !state.loaded;
        input.dataset.relayReady = ready ? "1" : "0";
        const card = input.closest?.("[data-colony-planet-id]");
        if (card) {
          card.classList.toggle("is-relay-ready", ready);
          card.classList.toggle(
            "is-relay-cooldown",
            state.loaded && remaining > 0 && !isHub
          );
        }
      }
    });

    syncButtons(page);
  }

  function selectedIds(page, direction, options = {}) {
    const readyOnly = Boolean(options.readyOnly);
    return Array.from(
      page?.querySelectorAll(`[data-logistics-colony-cb="${direction}"]:checked`) || []
    )
      .filter((input) => {
        if (input.disabled) return false;
        return !readyOnly || input.dataset.relayReady === "1";
      })
      .map((input) => parseInt(input.value || "0", 10))
      .filter((pid) => pid > 0);
  }

  function resourceInputs(page) {
    const out = {};
    ["metal", "crystal", "fuel_cells"].forEach((key) => {
      const input = page?.querySelector(`[data-logistics-resource="${key}"]`);
      out[key] = intString(input?.value || "0");
    });
    return out;
  }

  function hasDistributionResources(page) {
    const values = resourceInputs(page);
    return Object.values(values).some((value) => big(value) > 0n);
  }

  function syncSelectionPresentation(page) {
    if (!page) return;
    page.querySelectorAll("[data-logistics-colony-cb]").forEach((input) => {
      const card = input.closest?.("[data-colony-planet-id]");
      if (card) card.classList.toggle("is-selected", Boolean(input.checked));
    });
    page.querySelectorAll(".logistics-colony-card.is-slots-skipped").forEach((card) => {
      card.classList.remove("is-slots-skipped");
    });
  }

  function syncButtons(page) {
    if (!page) return;
    syncSelectionPresentation(page);
    const hub = hubId(page);
    const collect = page.querySelector('[data-resource-relay-submit="collect"]');
    const distribute = page.querySelector('[data-resource-relay-submit="distribute"]');
    if (collect && collect.getAttribute("aria-busy") !== "true") {
      const selected = selectedIds(page, "collect").length;
      const ready = selectedIds(page, "collect", { readyOnly: true }).length;
      collect.dataset.selectedCount = String(selected);
      collect.dataset.readyCount = String(ready);
      collect.disabled = !state.loaded || !hub || ready === 0;
    }
    if (distribute && distribute.getAttribute("aria-busy") !== "true") {
      const selected = selectedIds(page, "distribute").length;
      const ready = selectedIds(page, "distribute", { readyOnly: true }).length;
      distribute.dataset.selectedCount = String(selected);
      distribute.dataset.readyCount = String(ready);
      distribute.disabled =
        !state.loaded ||
        !hub ||
        selected === 0 ||
        ready !== selected ||
        !hasDistributionResources(page);
    }
  }

  function setBusy(button, busy) {
    if (!button) return;
    button.setAttribute("aria-busy", busy ? "true" : "false");
    button.disabled = Boolean(busy);
  }

  function showResult(page, direction, message, kind) {
    const host = page?.querySelector(`[data-resource-relay-result="${direction}"]`);
    if (host) {
      host.hidden = false;
      host.dataset.kind = kind || "info";
      host.textContent = message;
    }
    if (typeof GC.showNotify === "function") GC.showNotify(message, kind || "info");
  }

  function requestId(direction) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return `relay-${direction}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  }

  function applyCooldownState(payload) {
    const source = payload?.cooldowns || payload || {};
    if (source.server_now !== undefined) {
      state.serverOffsetSec = Number(source.server_now || 0) - Date.now() / 1000;
    }
    state.collect = source.collect && typeof source.collect === "object" ? source.collect : {};
    state.distribute =
      source.distribute && typeof source.distribute === "object" ? source.distribute : {};
    state.loaded = true;
  }

  function patchResources(page, payload) {
    const colonies = payload?.colony_resources || {};
    Object.entries(colonies).forEach(([planetId, resources]) => {
      page.querySelectorAll(
        `[data-colony-planet-id="${CSS.escape(String(planetId))}"]`
      ).forEach((card) => {
        ["metal", "crystal", "fuel_cells"].forEach((key) => {
          const node = card.querySelector(`[data-logistics-colony-res="${key}"]`);
          if (!node) return;
          const value = resources?.[key] ?? "0";
          node.textContent = fmt(value);
          node.setAttribute("title", fmt(value));
        });
      });
    });

    const hub = payload?.hub_resources || {};
    ["metal", "crystal", "fuel_cells"].forEach((key) => {
      const node = page.querySelector(`[data-logistics-hub-res="${key}"]`);
      if (!node || hub[key] === undefined) return;
      node.textContent = fmt(hub[key]);
      node.setAttribute("title", fmt(hub[key]));
    });
  }

  async function loadState(page) {
    if (!page || typeof GC.fetchGameAction !== "function") return;
    state.loaded = false;
    syncCooldownUi(page);
    try {
      const response = await GC.fetchGameAction("/api/logistics/relay/state", {
        method: "GET",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response?.ok) throw new Error("relay_state_failed");
      applyCooldownState(response.data || {});
      syncHubPresentation(page);
      syncCooldownUi(page);
    } catch (_) {
      state.loaded = false;
      syncCooldownUi(page);
    }
  }

  function errorText(reason) {
    const key = {
      relay_cooldown: "logistics_relay_error_cooldown",
      no_resources: "logistics_relay_error_no_resources",
      not_enough_resources: "logistics_relay_error_not_enough",
      foreign_planet: "logistics_relay_error_foreign",
      vacation_mode: "logistics_relay_error_vacation",
    }[String(reason || "")];
    return key ? t(key) : t("fleet_error_generic", "Aktion fehlgeschlagen.");
  }

  async function run(page, direction, button) {
    if (!page || typeof GC.fetchGameAction !== "function") return;
    const hub = hubId(page);
    const selected = selectedIds(page, direction);
    const readyIds = selectedIds(page, direction, { readyOnly: true });
    if (!hub || !selected.length) {
      showResult(page, direction, t("logistics_collect_incomplete"), "error");
      return;
    }
    if (!readyIds.length || (direction === "distribute" && readyIds.length !== selected.length)) {
      showResult(
        page,
        direction,
        errorText("relay_cooldown"),
        "error"
      );
      return;
    }

    // Collect may execute the ready subset and retain cooling selections for
    // later. Distribute waits for the whole selected set so the entered total
    // is never silently re-split across fewer planets.
    const ids = direction === "collect" ? readyIds : selected;
    const body =
      direction === "collect"
        ? {
            target_planet_id: hub,
            source_planet_ids: ids,
            request_id: requestId(direction),
          }
        : {
            origin_planet_id: hub,
            target_planet_ids: ids,
            resources: resourceInputs(page),
            request_id: requestId(direction),
          };

    setBusy(button, true);
    try {
      const response = await GC.fetchGameAction(`/api/logistics/relay/${direction}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-GC-Dom-Planet-Id": String(hub),
        },
        body: JSON.stringify(body),
      });

      if (!response?.ok) {
        const payload = response?.data && typeof response.data === "object" ? response.data : {};
        if (payload.cooldowns) applyCooldownState(payload);
        syncCooldownUi(page);
        showResult(
          page,
          direction,
          errorText(response?.reason || response?.error || "generic"),
          "error"
        );
        return;
      }

      const payload = response.data || {};
      patchResources(page, payload);
      if (payload.cooldowns) applyCooldownState(payload.cooldowns);
      ids.forEach((pid) => {
        const input = checkbox(page, direction, pid);
        if (input) input.checked = false;
      });
      syncCooldownUi(page);

      const done = Math.max(0, Number(payload.processed_count || 0));
      const summary =
        t(
          direction === "collect"
            ? "logistics_relay_collect_success"
            : "logistics_relay_distribute_success"
        ) +
        " · " +
        t("logistics_relay_processed", "Verarbeitet") +
        " " +
        done +
        "/" +
        ids.length;
      showResult(page, direction, summary, "success");

      if (typeof GC.refreshGameState === "function") {
        Promise.resolve(GC.refreshGameState()).catch(() => {});
      }
    } catch (_) {
      showResult(page, direction, errorText("generic"), "error");
    } finally {
      setBusy(button, false);
      syncButtons(page);
    }
  }

  function selectAll(page, direction, checked) {
    page.querySelectorAll(`[data-logistics-colony-cb="${direction}"]`).forEach((input) => {
      // "Alle markieren" really means all non-hub colonies. Cooldown entries
      // stay selected as pending and become actionable automatically on expiry.
      input.checked = Boolean(checked && !input.disabled);
    });
    syncButtons(page);
  }

  function setMax(page, key) {
    const source = page.querySelector(`[data-logistics-hub-res="${key}"]`);
    const input = page.querySelector(`[data-logistics-resource="${key}"]`);
    if (!source || !input) return;
    input.value = intString(source.getAttribute("title") || source.textContent || "0");
    syncButtons(page);
  }

  function setRelayMode(page, direction) {
    if (!page || (direction !== "collect" && direction !== "distribute")) return;
    page.dataset.logisticsMode = direction;
    page.querySelectorAll("[data-logistics-tab]").forEach((tab) => {
      const active = tab.getAttribute("data-logistics-tab") === direction;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    page.querySelectorAll("[data-logistics-panel]").forEach((panel) => {
      panel.hidden = panel.getAttribute("data-logistics-panel") !== direction;
    });
    syncButtons(page);
  }

  function activate(page) {
    if (!page) return;

    // The visible Collect/Distribute UI is Empire Relay-owned. Keep the legacy
    // Fleet logistics live-state poller asleep; otherwise it periodically
    // re-arms the obsolete freighter preview path behind this Relay screen.
    page._logisticsLivePending = true;

    if (state.root !== page) {
      state.root = page;
      state.loaded = false;
      state.collect = {};
      state.distribute = {};
      syncHubPresentation(page);
      syncCooldownUi(page);
      loadState(page);
    } else {
      syncCooldownUi(page);
    }
  }

  document.addEventListener(
    "click",
    (event) => {
      const page = root();
      if (!page) return;

      const relayTab = event.target.closest?.("[data-logistics-tab]");
      if (relayTab && page.contains(relayTab)) {
        const direction = relayTab.getAttribute("data-logistics-tab");
        if (direction === "collect" || direction === "distribute") {
          event.preventDefault();
          event.stopImmediatePropagation();
          setRelayMode(page, direction);
          return;
        }
      }

      const select = event.target.closest?.("[data-logistics-select-all]");
      if (select && page.contains(select)) {
        const direction = select.getAttribute("data-logistics-select-all");
        if (direction === "collect" || direction === "distribute") {
          event.preventDefault();
          event.stopImmediatePropagation();
          selectAll(
            page,
            direction,
            select.getAttribute("data-logistics-select-all-action") === "all"
          );
          return;
        }
      }

      const max = event.target.closest?.("[data-logistics-res-max]");
      if (max && page.contains(max)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        setMax(page, max.getAttribute("data-logistics-res-max") || "");
        return;
      }

      const button = event.target.closest?.("[data-resource-relay-submit]");
      if (button && page.contains(button)) {
        const direction = button.getAttribute("data-resource-relay-submit");
        if (direction === "collect" || direction === "distribute") {
          event.preventDefault();
          event.stopImmediatePropagation();
          run(page, direction, button);
        }
      }
    },
    true
  );

  document.addEventListener(
    "change",
    (event) => {
      const page = root();
      if (!page || !page.contains(event.target)) return;
      if (event.target.matches?.("[data-logistics-hub]")) {
        event.stopImmediatePropagation();
        syncHubPresentation(page);
        syncCooldownUi(page);
        return;
      }
      if (event.target.matches?.("[data-logistics-colony-cb]")) {
        event.stopImmediatePropagation();
        syncButtons(page);
      }
    },
    true
  );

  document.addEventListener(
    "input",
    (event) => {
      const page = root();
      if (!page || !page.contains(event.target)) return;
      if (event.target.matches?.("[data-logistics-resource]")) {
        event.stopImmediatePropagation();
        syncButtons(page);
      }
    },
    true
  );

  document.addEventListener(
    "submit",
    (event) => {
      const page = root();
      if (!page || !page.contains(event.target)) return;
      if (
        event.target.matches?.("#logistics-collect-form") ||
        event.target.matches?.("#logistics-distribute-form")
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    true
  );

  function stopTicker() {
    if (!state.timer) return;
    window.clearInterval(state.timer);
    state.timer = null;
  }

  function ensureTicker() {
    if (state.timer) return;
    state.timer = window.setInterval(() => {
      const page = root();
      if (!page) {
        stopTicker();
        state.root = null;
        state.loaded = false;
        return;
      }
      activate(page);
    }, 1000);
  }

  function syncMountedPage() {
    const page = root();
    if (!page) {
      state.root = null;
      state.loaded = false;
      stopTicker();
      return;
    }
    activate(page);
    ensureTicker();
  }

  const shell = document.getElementById("main-content") || document.body;
  const observer = new MutationObserver(syncMountedPage);
  // Watch only direct #main-content replacements. Internal relay UI updates
  // (countdown text/classes/disabled state) must never re-trigger mount sync,
  // otherwise the observer can feed its own DOM writes into an endless loop.
  observer.observe(shell, { childList: true });

  syncMountedPage();

  window.addEventListener(
    "pagehide",
    () => {
      observer.disconnect();
      stopTicker();
    },
    { once: true }
  );
})();
