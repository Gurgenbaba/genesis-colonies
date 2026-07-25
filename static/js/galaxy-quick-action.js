/* GC-980 — shared Galaxy quick-action layer (spy, attack presets, debris recycle). */
(() => {
  "use strict";

  const BUSY_CLASS = "galaxy-quick-action--busy";
  const SUBMIT_COOLDOWN_MS = 600;
  const RECYCLE_ARRIVAL_RELOAD_DEBOUNCE_MS = 400;

  function deps() {
    const GC = window.GC || {};
    return {
      t: typeof GC.t === "function" ? GC.t.bind(GC) : (key, fb) => fb || key,
      showNotify: typeof GC.showNotify === "function" ? GC.showNotify.bind(GC) : () => {},
      applyActionState: typeof GC.applyActionState === "function" ? GC.applyActionState.bind(GC) : () => {},
      mapActionError: typeof GC.mapActionError === "function" ? GC.mapActionError.bind(GC) : null,
      fetchGameAction: typeof GC.fetchGameAction === "function" ? GC.fetchGameAction.bind(GC) : null,
      getDomPlanetId: typeof GC.getDomPlanetId === "function" ? GC.getDomPlanetId.bind(GC) : () => 0,
      formatNumber: typeof GC.formatNumber === "function" ? GC.formatNumber.bind(GC) : (n) => String(n),
    };
  }

  const GalaxyQuickAction = {
    _attackMenu: null,
    _attackTrigger: null,
    _attackPresetsCache: null,
    _attackPresetsLoading: false,
    _recycleFleetStatuses: null,
    _recycleArrivalReloadTimer: null,
    _unwatchRecycleArrivals: null,
    _asteroidHelpHome: null,

    escapeHtml(value) {
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    },

    makeRequestId(prefix) {
      if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
      }
      return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    },

    getOriginPlanetId(root) {
      // PJAX galaxy SSR skips HEADER_ACTIVE_PLANET — prefer explicit page attrs,
      // then shell switcher / lastState, then getDomPlanetId.
      const pageRoot = document.getElementById("galaxy-page-root");
      const switcher = document.getElementById("gc-planet-switcher");
      const candidates = [
        root?.dataset?.activePlanetId,
        pageRoot?.dataset?.activePlanetId,
        switcher?.dataset?.activePlanetId,
        window.GC?.lastState?.active_planet_id,
      ];
      for (const raw of candidates) {
        const id = parseInt(raw || "0", 10);
        if (id > 0) return id;
      }
      const { getDomPlanetId } = deps();
      return parseInt(getDomPlanetId() || "0", 10) || 0;
    },

    getAvailableReclaimers(root) {
      const pageRoot = document.getElementById("galaxy-page-root");
      const fromRoot = Math.max(0, parseInt(root?.dataset?.availableReclaimers || "0", 10) || 0);
      if (fromRoot > 0) return fromRoot;
      return Math.max(0, parseInt(pageRoot?.dataset?.availableReclaimers || "0", 10) || 0);
    },

    resolveRecycleSendCount(root, needed) {
      const need = Math.max(0, parseInt(needed || "0", 10) || 0);
      return Math.min(this.getAvailableReclaimers(root), need);
    },

    coordsLabel(galaxy, system, position) {
      return `[${galaxy}:${system}:${position}]`;
    },

    async reloadGalaxyAfterRecycle() {
      if (typeof window.GC?.invalidateGalaxyPjaxCache === "function") {
        window.GC.invalidateGalaxyPjaxCache();
      }
      if (typeof window.GC?.reloadCurrentPage === "function") {
        await window.GC.reloadCurrentPage({ force: true });
      }
    },

    scheduleGalaxyReloadAfterRecycleArrival() {
      if (this._recycleArrivalReloadTimer) {
        window.clearTimeout(this._recycleArrivalReloadTimer);
      }
      this._recycleArrivalReloadTimer = window.setTimeout(() => {
        this._recycleArrivalReloadTimer = null;
        this.reloadGalaxyAfterRecycle();
      }, RECYCLE_ARRIVAL_RELOAD_DEBOUNCE_MS);
    },

    recycleFleetStatusMap(fleetsRaw) {
      const GC = window.GC || {};
      const normalize =
        typeof GC.normalizeActiveFleetsPayload === "function"
          ? GC.normalizeActiveFleetsPayload.bind(GC)
          : null;
      const items = normalize
        ? normalize(fleetsRaw).items || []
        : Array.isArray(fleetsRaw?.items)
          ? fleetsRaw.items
          : Array.isArray(fleetsRaw)
            ? fleetsRaw
            : [];
      const map = new Map();
      for (const it of items) {
        if (!it || typeof it !== "object") continue;
        const mission = String(it.mission || it.mission_type || "").trim().toLowerCase();
        if (mission !== "recycle") continue;
        const id = Number(it.movement_id || it.id || 0);
        if (!id) continue;
        map.set(id, String(it.status || "").trim().toLowerCase());
      }
      return map;
    },

    onActiveFleetsForRecycleSync(fleetsRaw) {
      const next = this.recycleFleetStatusMap(fleetsRaw);
      const prev = this._recycleFleetStatuses;
      this._recycleFleetStatuses = next;
      if (!prev) return;
      let arrived = false;
      for (const [id, status] of prev.entries()) {
        if (status !== "outbound") continue;
        const nextStatus = next.get(id);
        // Harvest runs on outbound→returning; item may also drop from the list briefly.
        if (!nextStatus || nextStatus === "returning" || nextStatus === "completed") {
          arrived = true;
          break;
        }
      }
      if (arrived) this.scheduleGalaxyReloadAfterRecycleArrival();
    },

    watchRecycleArrivals() {
      this.stopWatchRecycleArrivals();
      const GC = window.GC || {};
      this._recycleFleetStatuses = this.recycleFleetStatusMap(GC.lastState?.active_fleets);
      if (typeof GC.registerActiveFleetsListener !== "function") return;
      this._unwatchRecycleArrivals = GC.registerActiveFleetsListener((fleetsRaw) => {
        this.onActiveFleetsForRecycleSync(fleetsRaw);
      });
    },

    stopWatchRecycleArrivals() {
      if (typeof this._unwatchRecycleArrivals === "function") {
        this._unwatchRecycleArrivals();
        this._unwatchRecycleArrivals = null;
      }
      if (this._recycleArrivalReloadTimer) {
        window.clearTimeout(this._recycleArrivalReloadTimer);
        this._recycleArrivalReloadTimer = null;
      }
      this._recycleFleetStatuses = null;
    },

    async handleStaleRecycleTargetError(reason) {
      const { t, showNotify } = deps();
      const key = String(reason || "");
      if (key === "no_debris_at_target") {
        showNotify(
          t(
            "galaxy_debris_gone_reload",
            "Debris field is gone or already harvested — refreshing galaxy."
          ),
          "error"
        );
        await this.reloadGalaxyAfterRecycle();
        return true;
      }
      if (key === "no_asteroid_at_target") {
        showNotify(
          t(
            "galaxy_asteroid_gone_reload",
            "Asteroid is gone or already claimed — refreshing galaxy."
          ),
          "error"
        );
        await this.reloadGalaxyAfterRecycle();
        return true;
      }
      return false;
    },

    parseTargetCoords(el) {
      return {
        targetGalaxy: parseInt(el?.dataset?.targetGalaxy || "0", 10),
        targetSystem: parseInt(el?.dataset?.targetSystem || "0", 10),
        targetPosition: parseInt(el?.dataset?.targetPosition || "0", 10),
      };
    },

    notifyFleetError(reason, res, reasonMap) {
      const { t, showNotify, mapActionError } = deps();
      const key = String(reason || "generic");
      let msg;
      if (reasonMap && Object.prototype.hasOwnProperty.call(reasonMap, key)) {
        const entry = reasonMap[key];
        msg = typeof entry === "function" ? entry(res) : entry;
      } else if (mapActionError) {
        msg = mapActionError(key, res?.payload || res);
      } else {
        msg = t(`fleet_error_${key}`, t("fleet_error_generic", "Fleet action failed."));
      }
      showNotify(msg, "error");
    },

    async runGuarded(trigger, fn, { cooldownMs = SUBMIT_COOLDOWN_MS } = {}) {
      if (!trigger || trigger.disabled || trigger.dataset.submitting === "1") return;
      trigger.disabled = true;
      trigger.dataset.submitting = "1";
      trigger.classList.add(BUSY_CLASS);
      const started = Date.now();
      try {
        await fn();
      } finally {
        const wait = Math.max(0, cooldownMs - (Date.now() - started));
        window.setTimeout(() => {
          trigger.disabled = false;
          delete trigger.dataset.submitting;
          trigger.classList.remove(BUSY_CLASS);
        }, wait);
      }
    },

    async postFleetSend(root, trigger, {
      body,
      applyReason = "fleet_send_success",
      onSuccess,
      onError,
      skipGuard = false,
    }) {
      const { fetchGameAction, applyActionState } = deps();
      if (!fetchGameAction) return null;

      const originPlanetId = this.getOriginPlanetId(root);
      const targetGalaxy = parseInt(body.target_galaxy || "0", 10);
      const targetSystem = parseInt(body.target_system || "0", 10);
      const targetPosition = parseInt(body.target_position || "0", 10);
      if (!originPlanetId || !targetGalaxy || !targetSystem || !targetPosition) {
        if (typeof onError === "function") onError("no_origin");
        return null;
      }

      const domPlanetId = deps().getDomPlanetId() || originPlanetId;
      const payload = {
        ...body,
        origin_planet_id: originPlanetId,
        request_id: body.request_id || this.makeRequestId("galaxy-fleet"),
      };

      const exec = async () => {
        const res = await fetchGameAction("/api/fleet/send", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            ...(domPlanetId ? { "X-GC-Dom-Planet-Id": String(domPlanetId) } : {}),
          },
          body: JSON.stringify(payload),
        });
        if (res?.ok) {
          applyActionState(res, applyReason);
          if (typeof onSuccess === "function") onSuccess(res);
        } else if (typeof onError === "function") {
          onError(res?.error || res?.reason || "generic", res);
        }
        return res;
      };

      if (skipGuard) return exec();
      let result = null;
      await this.runGuarded(trigger, async () => {
        result = await exec();
      });
      return result;
    },

    closeAttackMenu() {
      if (this._attackMenu) {
        this._attackMenu.remove();
        this._attackMenu = null;
      }
      if (this._attackTrigger) {
        this._attackTrigger.setAttribute("aria-expanded", "false");
        this._attackTrigger = null;
      }
    },

    positionAttackMenu(menu, trigger) {
      const rect = trigger.getBoundingClientRect();
      const margin = 8;
      menu.style.visibility = "hidden";
      menu.style.display = "block";
      const menuRect = menu.getBoundingClientRect();
      let left = rect.right - menuRect.width;
      left = Math.max(margin, Math.min(left, window.innerWidth - menuRect.width - margin));
      let top = rect.bottom + 4;
      if (top + menuRect.height > window.innerHeight - margin) {
        top = Math.max(margin, rect.top - menuRect.height - 4);
      }
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
      menu.style.visibility = "visible";
    },

    renderAttackMenu(menu, presets, trigger) {
      const { t, formatNumber } = deps();
      const fleetHref = (trigger.dataset.fleetHref || "").trim();
      const menuLabel = t("galaxy_quick_attack_menu_label", "Raid templates");
      const emptyText = t("galaxy_quick_attack_empty", "No raid template available.");
      const fleetLinkText = t("galaxy_quick_attack_open_fleet", "Open fleet page");
      const moreTpl = t("galaxy_quick_attack_more_ships", "+%(count)s more");
      let bodyHtml;

      if (!presets.length) {
        bodyHtml = `
          <p class="galaxy-quick-attack-empty">${this.escapeHtml(emptyText)}</p>
          ${fleetHref ? `<a href="${this.escapeHtml(fleetHref)}" class="galaxy-quick-attack-fleet-link">${this.escapeHtml(fleetLinkText)}</a>` : ""}
        `;
      } else {
        const buildPreview = (preset) => {
          const ships = preset.ships && typeof preset.ships === "object" ? preset.ships : {};
          const entries = Object.keys(ships)
            .map((key) => [key, parseInt(ships[key], 10) || 0])
            .filter(([, qty]) => qty > 0)
            .sort((a, b) => b[1] - a[1]);
          const shown = entries.slice(0, 3);
          const parts = shown.map(([key, qty]) => {
            const shipName = typeof GC !== "undefined" && typeof GC.shipDisplayName === "function"
              ? GC.shipDisplayName(key)
              : t(`fleet_ship_${key}`, key);
            return `${formatNumber(qty)} ${this.escapeHtml(shipName)}`;
          });
          const remaining = entries.length - shown.length;
          if (remaining > 0) {
            parts.push(this.escapeHtml(moreTpl.replace("%(count)s", String(remaining))));
          }
          const speed = parseInt(preset.speed_percent, 10);
          if (Number.isFinite(speed) && speed > 0) parts.push(`${speed}%`);
          const resources = preset.resources && typeof preset.resources === "object" ? preset.resources : null;
          if (resources) {
            const cargoTotal = Object.keys(resources)
              .reduce((sum, rk) => sum + (parseInt(resources[rk], 10) || 0), 0);
            if (cargoTotal > 0) {
              const cargoLabel = t("galaxy_quick_attack_cargo", "Cargo %(amount)s");
              parts.push(this.escapeHtml(cargoLabel.replace("%(amount)s", formatNumber(cargoTotal))));
            }
          }
          return parts.join(" · ");
        };

        const items = presets
          .map((preset) => {
            const typeKey = `fleet_preset_type_${preset.preset_type || "custom"}`;
            const typeLabel = t(typeKey, preset.preset_type || "custom");
            const name = this.escapeHtml(preset.name || "");
            const type = this.escapeHtml(typeLabel);
            const preview = buildPreview(preset);
            const previewHtml = preview
              ? `<span class="galaxy-quick-attack-item-preview">${preview}</span>`
              : "";
            return `<button type="button" class="galaxy-quick-attack-item" data-preset-id="${this.escapeHtml(preset.id)}">
              <span class="galaxy-quick-attack-item-head">
                <span class="galaxy-quick-attack-item-name">${name}</span>
                <span class="galaxy-quick-attack-item-type">${type}</span>
              </span>
              ${previewHtml}
            </button>`;
          })
          .join("");
        bodyHtml = `<div class="galaxy-quick-attack-list" role="menu">${items}</div>`;
      }

      menu.innerHTML = `
        <div class="galaxy-quick-attack-menu-inner" role="menu" aria-label="${this.escapeHtml(menuLabel)}">
          ${bodyHtml}
        </div>
      `;
      this.positionAttackMenu(menu, trigger);
    },

    async loadAttackPresets() {
      if (this._attackPresetsCache) return this._attackPresetsCache;
      if (this._attackPresetsLoading) {
        await new Promise((resolve) => {
          const wait = () => {
            if (!this._attackPresetsLoading) resolve();
            else window.setTimeout(wait, 40);
          };
          wait();
        });
        return this._attackPresetsCache || [];
      }
      this._attackPresetsLoading = true;
      try {
        const res = await fetch("/api/fleet/presets?galaxy_attack=1", {
          headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        const body = await res.json().catch(() => ({}));
        const presets = body?.ok && body?.data?.presets ? body.data.presets : [];
        this._attackPresetsCache = Array.isArray(presets) ? presets : [];
        return this._attackPresetsCache;
      } catch (_err) {
        this._attackPresetsCache = [];
        return [];
      } finally {
        this._attackPresetsLoading = false;
      }
    },

    async sendAttackPreset(root, trigger, presetId) {
      const { t, showNotify } = deps();
      const { targetGalaxy, targetSystem, targetPosition } = this.parseTargetCoords(trigger);
      const coords = this.coordsLabel(targetGalaxy, targetSystem, targetPosition);
      this.closeAttackMenu();

      await this.postFleetSend(root, trigger, {
        body: {
          mission_type: "attack",
          galaxy_quick_attack: true,
          preset_id: parseInt(presetId, 10),
          target_galaxy: targetGalaxy,
          target_system: targetSystem,
          target_position: targetPosition,
        },
        onSuccess: (res) => {
          const payload = res.data && typeof res.data === "object" ? res.data : res;
          const atkMeta = payload.galaxy_quick_attack || {};
          const presetName = String(atkMeta.preset_name || "").trim() || `#${presetId}`;
          const tpl = t("galaxy_quick_attack_success", "Attack \"%(preset)s\" launched to %(coords)s.");
          showNotify(tpl.replace("%(preset)s", presetName).replace("%(coords)s", coords), "success");
        },
        onError: (reason, res) => {
          this.notifyFleetError(reason, res, {
            no_origin: t("galaxy_quick_attack_no_origin", "No active colony to launch an attack from."),
            not_enough_ships: t("fleet_error_not_enough_ships", "Not enough ships available."),
            preset_no_ships: t("fleet_error_not_enough_ships", "Not enough ships available."),
            fleet_slots_full: t("fleet_error_fleet_slots_full", "No free fleet slots."),
          });
        },
      });
    },

    async handleSpyClick(ev, root) {
      const btn = ev.target.closest("[data-galaxy-quick-spy]");
      if (!btn || !root.contains(btn)) return;
      ev.preventDefault();
      ev.stopPropagation();

      const { t, showNotify } = deps();
      const { targetGalaxy, targetSystem, targetPosition } = this.parseTargetCoords(btn);
      const coords = this.coordsLabel(targetGalaxy, targetSystem, targetPosition);

      await this.runGuarded(btn, async () => {
        await this.postFleetSend(root, btn, {
          skipGuard: true,
          body: {
            mission_type: "spy",
            galaxy_quick_spy: true,
            target_galaxy: targetGalaxy,
            target_system: targetSystem,
            target_position: targetPosition,
            resources: {},
            speed_percent: 100,
          },
          onSuccess: (res) => {
            const payload = res.data && typeof res.data === "object" ? res.data : res;
            const spyMeta = payload.galaxy_quick_spy || {};
            const sentCount = parseInt(spyMeta.sent_count, 10) || 0;
            const availableCount = parseInt(spyMeta.available_count, 10);
            const reduced = Boolean(spyMeta.reduced) && sentCount > 0;
            let tpl;
            if (reduced && Number.isFinite(availableCount)) {
              tpl = t(
                "galaxy_quick_spy_success_partial",
                "Only %(available)s Phantom Probes available — %(count)s sent to %(coords)s."
              );
              showNotify(
                tpl
                  .replace("%(available)s", String(availableCount))
                  .replace("%(count)s", String(sentCount))
                  .replace("%(coords)s", coords),
                "success"
              );
            } else {
              tpl = t("galaxy_quick_spy_success", "%(count)s Phantom Probes sent to %(coords)s.");
              showNotify(tpl.replace("%(count)s", String(sentCount)).replace("%(coords)s", coords), "success");
            }
          },
          onError: (reason, res) => {
            this.notifyFleetError(reason, res, {
              no_origin: t("galaxy_quick_spy_no_origin", "No active colony to launch probes from."),
              no_spy_probes_available: t("galaxy_quick_spy_no_probes", "No Phantom Probes available."),
              not_enough_ships: t("galaxy_quick_spy_no_probes", "No Phantom Probes available."),
              fleet_slots_full: t("fleet_error_fleet_slots_full", "No free fleet slots."),
            });
          },
        });
      });
    },

    async handleAttackClick(ev, root) {
      const trigger = ev.target.closest("[data-galaxy-quick-attack]");
      if (!trigger || !root.contains(trigger)) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (trigger.disabled || trigger.dataset.submitting === "1") return;

      if (this._attackTrigger === trigger && this._attackMenu) {
        this.closeAttackMenu();
        return;
      }
      this.closeAttackMenu();

      const { t } = deps();
      const menu = document.createElement("div");
      menu.className = "galaxy-quick-attack-menu gc-popover-layer";
      menu.hidden = false;
      menu.innerHTML = `<div class="galaxy-quick-attack-menu-inner"><p class="galaxy-quick-attack-loading">${t("galaxy_quick_attack_loading", "Loading templates…")}</p></div>`;
      document.body.appendChild(menu);
      this._attackMenu = menu;
      this._attackTrigger = trigger;
      trigger.setAttribute("aria-expanded", "true");
      this.positionAttackMenu(menu, trigger);

      const presets = await this.loadAttackPresets();
      if (this._attackMenu !== menu) return;
      this.renderAttackMenu(menu, presets, trigger);
    },

    async handleAttackMenuClick(ev) {
      if (!this._attackMenu) return;
      const item = ev.target.closest("[data-preset-id]");
      if (!item || !this._attackMenu.contains(item)) return;
      ev.preventDefault();
      ev.stopPropagation();
      const presetId = item.getAttribute("data-preset-id");
      const trigger = this._attackTrigger;
      const root = document.querySelector("[data-galaxy-ring-view]");
      if (!presetId || !trigger || !root) return;

      await this.runGuarded(trigger, async () => {
        await this.sendAttackPreset(root, trigger, presetId);
      });
    },

    handleAttackOutsideClick(ev) {
      if (!this._attackMenu) return;
      if (ev.target.closest("[data-galaxy-quick-attack]") || this._attackMenu.contains(ev.target)) return;
      this.closeAttackMenu();
    },

    async handleDebrisRecycleClick(ev, root) {
      const btn = ev.target.closest("[data-galaxy-ring-debris-recycle]");
      if (!btn || !root.contains(btn)) return;
      ev.preventDefault();
      ev.stopPropagation();
      const wrap = btn.closest("[data-galaxy-ring-debris-wrap]");
      if (!wrap) return;

      const { t, showNotify } = deps();
      const targetGalaxy = parseInt(wrap.dataset.targetGalaxy || "0", 10);
      const targetSystem = parseInt(wrap.dataset.targetSystem || "0", 10);
      const targetPosition = parseInt(wrap.dataset.targetPosition || "0", 10);
      const needed = parseInt(wrap.dataset.recyclerSlots || "0", 10);
      const sendCount = this.resolveRecycleSendCount(root, needed);
      const originPlanetId = this.getOriginPlanetId(root);

      if (!originPlanetId) {
        showNotify(t("galaxy_debris_recycle_no_origin", "No active colony for recycler launch."), "error");
        return;
      }
      if (!targetGalaxy || !targetSystem || !targetPosition) {
        showNotify(t("galaxy_debris_recycle_bad_target", "Invalid debris coordinates."), "error");
        return;
      }
      if (needed < 1) {
        showNotify(t("galaxy_debris_recycle_empty", "No harvestable debris."), "error");
        return;
      }
      if (sendCount < 1) {
        showNotify(
          t(
            "galaxy_debris_recycle_no_ships",
            "No Harvest Reclaimers free — wait for return or build more."
          ),
          "error"
        );
        return;
      }

      await this.runGuarded(btn, async () => {
        await this.postFleetSend(root, btn, {
          skipGuard: true,
          body: {
            mission_type: "recycle",
            target_galaxy: targetGalaxy,
            target_system: targetSystem,
            target_position: targetPosition,
            ships: { harvest_reclaimer: sendCount },
            resources: {},
            speed_percent: 100,
          },
          onSuccess: async () => {
            if (sendCount < needed) {
              showNotify(
                t(
                  "galaxy_debris_recycle_partial",
                  "Fleet dispatched with available reclaimers (partial harvest)."
                ),
                "success"
              );
            } else {
              showNotify(t("fleet_send_success", "Fleet dispatched."), "success");
            }
            // Arrival watcher reloads Galaxy after harvest (avoid caching pre-harvest HTML).
          },
          onError: async (reason, res) => {
            if (await this.handleStaleRecycleTargetError(reason)) return;
            this.notifyFleetError(reason, res, null);
          },
        });
      });
    },

    async handleAsteroidRecycleClick(ev, root) {
      const btn = ev.target.closest("[data-galaxy-ring-asteroid-recycle]");
      if (!btn || !root.contains(btn)) return;
      ev.preventDefault();
      ev.stopPropagation();
      const wrap = btn.closest("[data-galaxy-ring-asteroid-wrap]");
      if (!wrap) return;
      if (wrap.dataset.harvestLocked === "1" || btn.disabled) {
        const { t, showNotify } = deps();
        showNotify(
          t("galaxy_asteroid_en_route_title", "Harvest fleet already en route."),
          "info"
        );
        return;
      }

      const { t, showNotify } = deps();
      const targetGalaxy = parseInt(wrap.dataset.targetGalaxy || "0", 10);
      const targetSystem = parseInt(wrap.dataset.targetSystem || "0", 10);
      const targetPosition = parseInt(wrap.dataset.targetPosition || "0", 10);
      const needed = parseInt(wrap.dataset.recyclerSlots || "0", 10);
      const sendCount = this.resolveRecycleSendCount(root, needed);
      const originPlanetId = this.getOriginPlanetId(root);

      if (!originPlanetId) {
        showNotify(t("galaxy_asteroid_harvest_no_origin", "No active colony for asteroid harvest."), "error");
        return;
      }
      if (!targetGalaxy || !targetSystem || !targetPosition) {
        showNotify(t("galaxy_asteroid_harvest_bad_target", "Invalid asteroid coordinates."), "error");
        return;
      }
      if (needed < 1) {
        showNotify(t("galaxy_asteroid_harvest_empty", "No harvestable asteroid."), "error");
        return;
      }
      if (sendCount < 1) {
        showNotify(
          t(
            "galaxy_asteroid_harvest_no_ships",
            "No Harvest Reclaimers free — wait for return or build more."
          ),
          "error"
        );
        return;
      }

      await this.runGuarded(btn, async () => {
        await this.postFleetSend(root, btn, {
          skipGuard: true,
          body: {
            mission_type: "recycle",
            target_galaxy: targetGalaxy,
            target_system: targetSystem,
            target_position: targetPosition,
            ships: { harvest_reclaimer: sendCount },
            resources: {},
            speed_percent: 100,
          },
          onSuccess: async () => {
            if (sendCount < needed) {
              showNotify(
                t(
                  "galaxy_asteroid_harvest_partial",
                  "Fleet dispatched with available reclaimers (partial harvest)."
                ),
                "success"
              );
            } else {
              showNotify(t("fleet_send_success", "Fleet dispatched."), "success");
            }
            await this.reloadGalaxyAfterRecycle();
          },
          onError: async (reason, res) => {
            if (await this.handleStaleRecycleTargetError(reason)) return;
            this.notifyFleetError(reason, res, null);
          },
        });
      });
    },

    handleEscape() {
      if (this._attackMenu) this.closeAttackMenu();
      this.closeAsteroidHelp();
    },

    openAsteroidHelp() {
      const modal = document.getElementById("galaxy-asteroid-help-modal");
      if (!modal) return;
      // Portal to body so fixed overlay is not trapped by galaxy stacking contexts.
      if (modal.parentElement !== document.body) {
        this._asteroidHelpHome = modal.parentElement;
        document.body.appendChild(modal);
      }
      modal.hidden = false;
      modal.setAttribute("aria-hidden", "false");
      modal.querySelector("[data-galaxy-asteroid-help-close].gc-player-card-close")?.focus();
    },

    closeAsteroidHelp() {
      const modal = document.getElementById("galaxy-asteroid-help-modal");
      if (!modal || modal.hidden) return;
      modal.hidden = true;
      modal.setAttribute("aria-hidden", "true");
      if (this._asteroidHelpHome && modal.parentElement === document.body) {
        this._asteroidHelpHome.appendChild(modal);
        this._asteroidHelpHome = null;
      }
      document.querySelector("[data-galaxy-asteroid-help-open]")?.focus();
    },

    handleAsteroidHelpClick(ev) {
      const openBtn = ev.target.closest("[data-galaxy-asteroid-help-open]");
      if (openBtn) {
        ev.preventDefault();
        this.openAsteroidHelp();
        return;
      }
      const closeEl = ev.target.closest("[data-galaxy-asteroid-help-close]");
      if (closeEl) {
        ev.preventDefault();
        this.closeAsteroidHelp();
      }
    },

    setAsteroidBoardExpanded(board, expanded) {
      if (!board) return;
      const panel = board.querySelector("[data-galaxy-asteroid-board-panel]");
      const toggle = board.querySelector("[data-galaxy-asteroid-board-toggle]");
      const open = Boolean(expanded);
      board.classList.toggle("is-collapsed", !open);
      if (panel) panel.hidden = !open;
      if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
      try {
        localStorage.setItem("gc_galaxy_asteroid_board_open", open ? "1" : "0");
      } catch (_) {}
    },

    initAsteroidBoardToggle(root) {
      const board = root?.querySelector?.("[data-galaxy-asteroid-board]");
      if (!board) return;
      let preferOpen = false;
      try {
        preferOpen = localStorage.getItem("gc_galaxy_asteroid_board_open") === "1";
      } catch (_) {}
      this.setAsteroidBoardExpanded(board, preferOpen);
    },

    handleAsteroidBoardToggle(ev, root) {
      const btn = ev.target.closest("[data-galaxy-asteroid-board-toggle]");
      if (!btn || !root.contains(btn)) return;
      ev.preventDefault();
      const board = btn.closest("[data-galaxy-asteroid-board]");
      if (!board) return;
      const open = board.classList.contains("is-collapsed");
      this.setAsteroidBoardExpanded(board, open);
    },

    async handleRelocationClick(ev, root) {
      const btn = ev.target.closest("[data-galaxy-relocation-start]");
      if (!btn || !root.contains(btn)) return;
      ev.preventDefault();
      ev.stopPropagation();

      const { t, showNotify, fetchGameAction, applyActionState } = deps();
      const { targetGalaxy, targetSystem, targetPosition } = this.parseTargetCoords(btn);
      const coords = this.coordsLabel(targetGalaxy, targetSystem, targetPosition);

      if (!targetGalaxy || !targetSystem || !targetPosition || !fetchGameAction) return;

      await this.runGuarded(btn, async () => {
        const res = await fetchGameAction("/api/planet/relocation/start", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
          },
          body: JSON.stringify({
            galaxy: targetGalaxy,
            system: targetSystem,
            position: targetPosition,
            request_id: this.makeRequestId("galaxy-reloc"),
          }),
        });
        if (res?.ok) {
          applyActionState(res, "planet_relocation_start");
          const tpl = t("galaxy_relocation_success", "Evacuation to %(coords)s started.");
          showNotify(tpl.replace("%(coords)s", coords), "success");
          if (typeof window.GC?.reloadCurrentPage === "function") {
            await window.GC.reloadCurrentPage({ force: true });
          }
        } else {
          const reason = res?.reason || res?.error || "planet_relocation_failed";
          showNotify(t(reason, t("planet_relocation_failed", "Relocation failed.")), "error");
        }
      });
    },

    resetAttackPresetCache() {
      this._attackPresetsCache = null;
    },

    bindRingView(root) {
      const onSpy = (ev) => this.handleSpyClick(ev, root);
      const onAttack = (ev) => this.handleAttackClick(ev, root);
      const onAttackMenu = (ev) => this.handleAttackMenuClick(ev);
      const onAttackOutside = (ev) => this.handleAttackOutsideClick(ev);
      const onDebris = (ev) => this.handleDebrisRecycleClick(ev, root);
      const onAsteroid = (ev) => this.handleAsteroidRecycleClick(ev, root);
      const onAsteroidHelp = (ev) => this.handleAsteroidHelpClick(ev);
      const onBoardToggle = (ev) => this.handleAsteroidBoardToggle(ev, root);
      const onRelocate = (ev) => this.handleRelocationClick(ev, root);
      const onEscape = (ev) => {
        if (ev.key === "Escape") this.handleEscape();
      };

      root.addEventListener("click", onSpy);
      root.addEventListener("click", onAttack);
      document.addEventListener("click", onAttackMenu);
      document.addEventListener("click", onAttackOutside);
      root.addEventListener("click", onDebris);
      root.addEventListener("click", onAsteroid);
      root.addEventListener("click", onAsteroidHelp);
      document.addEventListener("click", onAsteroidHelp);
      root.addEventListener("click", onBoardToggle);
      root.addEventListener("click", onRelocate);
      document.addEventListener("keydown", onEscape);
      this.watchRecycleArrivals();
      this.initAsteroidBoardToggle(root);

      return () => {
        root.removeEventListener("click", onSpy);
        root.removeEventListener("click", onAttack);
        document.removeEventListener("click", onAttackMenu);
        document.removeEventListener("click", onAttackOutside);
        root.removeEventListener("click", onDebris);
        root.removeEventListener("click", onAsteroid);
        root.removeEventListener("click", onAsteroidHelp);
        document.removeEventListener("click", onAsteroidHelp);
        root.removeEventListener("click", onBoardToggle);
        root.removeEventListener("click", onRelocate);
        document.removeEventListener("keydown", onEscape);
        this.stopWatchRecycleArrivals();
        this.closeAttackMenu();
        this.closeAsteroidHelp();
        this.resetAttackPresetCache();
      };
    },
  };

  window.GC = window.GC || {};
  window.GC.GalaxyQuickAction = GalaxyQuickAction;
})();
