/**
 * GC-700C/D — Combat Simulator player UI (renders server display payload only).
 */
(function () {
  "use strict";

  function initCombatSimulatorPage() {
    const root = document.getElementById("combat-simulator-page");
    if (!root || root.dataset.ready !== "1") return;

    let state = {};
    try {
      const raw = document.getElementById("combat-simulator-state");
      state = raw ? JSON.parse(raw.textContent || "{}") : {};
    } catch (_) {
      state = {};
    }

    const isAdmin = root.dataset.isAdmin === "1";
    const presets = state.presets || {};
    const defaults = state.defaults || presets;
    const ownFleetStock = () => defaults.attacker_ships || presets.attacker_ships || {};
    let lastResult = null;
    const showAllUnits = { attacker: false, defender: false };
    let showAllCombatValues = false;
    let lastCombatValues = null;
    let showResultDetails = false;

    function tr(key, fallback, vars) {
      const fn = window.GC && typeof GC.t === "function" ? GC.t : null;
      let out = fn ? fn(key, fallback) : fallback || key;
      if (vars && typeof out === "string") {
        Object.keys(vars).forEach((k) => {
          out = out.replace(new RegExp(`%\\(${k}\\)s`, "g"), String(vars[k]));
          out = out.replace(new RegExp(`\\{${k}\\}`, "g"), String(vars[k]));
        });
      }
      return out;
    }

    function sideRoot(side) {
      return root.querySelector(`[data-sim-side="${side}"]`);
    }

    function parseQty(val) {
      return window.GC && GC.parseIntNumber ? GC.parseIntNumber(val) : parseInt(val, 10) || 0;
    }

    function readShips(side) {
      const panel = sideRoot(side)?.querySelector('[data-sim-panel="ships"]');
      if (!panel) return {};
      const out = {};
      panel.querySelectorAll("[data-unit-input]").forEach((inp) => {
        if (inp.dataset.fieldKnown === "0") return;
        const qty = parseQty(inp.value);
        if (qty > 0) out[inp.dataset.unitInput] = qty;
      });
      return out;
    }

    function readDefense() {
      const panel = sideRoot("defender")?.querySelector('[data-sim-panel="defense"]');
      if (!panel) return {};
      const out = {};
      panel.querySelectorAll("[data-unit-input]").forEach((inp) => {
        const qty = parseQty(inp.value);
        if (qty > 0) out[inp.dataset.unitInput] = qty;
      });
      return out;
    }

    function readTech(side) {
      const panel = sideRoot(side)?.querySelector('[data-sim-panel="research"]');
      const out = { weapon_tech: 0, armor_tech: 0, shield_tech: 0 };
      if (!panel) return out;
      panel.querySelectorAll("[data-tech]").forEach((inp) => {
        if (inp.dataset.fieldKnown === "0") return;
        out[inp.dataset.tech] = Math.max(0, parseInt(inp.value, 10) || 0);
      });
      return out;
    }

    function readResources() {
      const panel = sideRoot("defender")?.querySelector('[data-sim-panel="resources"]');
      const out = { metal: 0, crystal: 0, fuel_cells: 0 };
      if (!panel) return out;
      panel.querySelectorAll("[data-resource]").forEach((inp) => {
        if (inp.dataset.fieldKnown === "0") return;
        out[inp.dataset.resource] = parseQty(inp.value);
      });
      return out;
    }

    function markUnknownInput(inp) {
      inp.dataset.fieldKnown = "0";
      inp.value = "";
      inp.placeholder = tr("combat_simulator_unknown", "unbekannt");
      inp.disabled = true;
      inp.classList.add("combat-sim-unknown");
    }

    function clearUnknownInput(inp) {
      inp.dataset.fieldKnown = "1";
      inp.disabled = false;
      inp.placeholder = "";
      inp.classList.remove("combat-sim-unknown");
    }

    function setShips(side, stock) {
      const panel = sideRoot(side)?.querySelector('[data-sim-panel="ships"]');
      if (!panel) return;
      panel.querySelectorAll("[data-unit-input]").forEach((inp) => {
        clearUnknownInput(inp);
        inp.value = String(Math.max(0, parseInt(stock[inp.dataset.unitInput] || 0, 10)));
      });
      applyUnitFilters(sideRoot(side));
    }

    function setDefense(stock) {
      const panel = sideRoot("defender")?.querySelector('[data-sim-panel="defense"]');
      if (!panel) return;
      panel.querySelectorAll("[data-unit-input]").forEach((inp) => {
        clearUnknownInput(inp);
        inp.value = String(Math.max(0, parseInt(stock[inp.dataset.unitInput] || 0, 10)));
      });
      applyUnitFilters(sideRoot("defender"));
    }

    function setTech(side, tech, fieldKnown) {
      const panel = sideRoot(side)?.querySelector('[data-sim-panel="research"]');
      if (!panel) return;
      const known = fieldKnown || {};
      panel.querySelectorAll("[data-tech]").forEach((inp) => {
        const key = inp.dataset.tech;
        if (known[key] === false) {
          markUnknownInput(inp);
          return;
        }
        clearUnknownInput(inp);
        inp.value = String(Math.max(0, parseInt((tech || {})[key] || 0, 10)));
      });
    }

    function setResources(stock, fieldKnown) {
      const panel = sideRoot("defender")?.querySelector('[data-sim-panel="resources"]');
      if (!panel) return;
      const known = fieldKnown || {};
      panel.querySelectorAll("[data-resource]").forEach((inp) => {
        const key = inp.dataset.resource;
        if (known[key] === false) {
          markUnknownInput(inp);
          return;
        }
        clearUnknownInput(inp);
        inp.value = String(Math.max(0, parseInt((stock || {})[key] || 0, 10)));
      });
    }

    function formatAge(seconds) {
      const s = Math.max(0, parseInt(seconds, 10) || 0);
      if (s < 3600) return tr("combat_simulator_age_minutes", "%(n)s min", { n: Math.max(1, Math.round(s / 60)) });
      if (s < 86400) return tr("combat_simulator_age_hours", "%(n)s h", { n: Math.round(s / 3600) });
      return tr("combat_simulator_age_days", "%(n)s d", { n: Math.round(s / 86400) });
    }

    function formatIntelTiers(keys) {
      if (!Array.isArray(keys) || !keys.length) return tr("combat_simulator_intel_none", "kein Intel");
      return keys.map((k) => tr(`combat_sim_field_${k}`, k)).join(", ");
    }

    function localizedFieldList(keys) {
      return (keys || []).map((k) => tr(k, k.replace(/^combat_sim_field_/, ""))).join(", ");
    }

    function formatDefenderRoute(target) {
      const owner = String(target?.owner || "").trim();
      const planet = String(target?.planet || "").trim();
      const coords = String(target?.coords || "").trim();
      const parts = [];
      if (owner) parts.push(owner);
      if (planet) parts.push(planet);
      if (coords) parts.push(`[${coords}]`);
      return parts.join(" · ");
    }

    function updateRouteLabels(labels) {
      const atkEl = root.querySelector("[data-sim-attacker-route]");
      const defEl = root.querySelector("[data-sim-defender-route]");
      const spySrc = root.querySelector("[data-sim-spy-source]");
      const routes = labels || state.route_labels || {};
      const ctx = defaults.context_planet || {};
      if (atkEl) {
        atkEl.textContent =
          routes.attacker ||
          (ctx.name && ctx.coords ? `${ctx.name} [${ctx.coords}]` : ctx.name || ctx.coords || "—");
      }
      if (defEl) {
        defEl.textContent = routes.defender || tr("combat_simulator_manual_target", "manuell");
      }
      if (spySrc) spySrc.hidden = !routes.from_spy;
    }

    function updateDefenderUnscanned(unscanned, target, unknownLabelKeys) {
      const el = root.querySelector("[data-sim-defender-unscanned]");
      if (!el) return;
      const unknownFields =
        unknownLabelKeys && unknownLabelKeys.length
          ? localizedFieldList(unknownLabelKeys)
          : Array.isArray(unscanned)
            ? unscanned.join(", ")
            : "";
      if (unknownFields) {
        el.textContent = tr("combat_simulator_unscanned", "Nicht gescannt: %(fields)s", { fields: unknownFields });
        el.hidden = false;
      } else {
        el.hidden = true;
        el.textContent = "";
      }
    }

    function applyAttackerDefaults(source) {
      const src = source || defaults || {};
      setShips("attacker", src.attacker_ships || {});
      setTech("attacker", src.attacker_tech || {});
      updateRouteLabels(state.route_labels);
    }

    function applyDefenderPreset() {
      setShips("defender", presets.defender_ships || {});
      setDefense(presets.defender_defense || {});
      setResources(presets.defender_resources || {}, presets.defender_field_known || {});
      setTech("defender", presets.defender_tech || {}, presets.defender_field_known || {});
      const meta = presets.defender_meta || {};
      updateDefenderUnscanned(meta.unscanned_fields, meta.target, meta.unknown_label_keys);
      if (meta.target && Object.keys(meta.target).length) {
        const route = formatDefenderRoute(meta.target);
        if (route) {
          state.route_labels = { ...(state.route_labels || {}), defender: route, from_spy: Boolean(state.spy_report_id) };
          updateRouteLabels(state.route_labels);
        }
      }
    }

    function applyDefenderImport(defender) {
      if (!defender) return;
      const fk = defender.field_known || {};
      if (defender.defender_ships) setShips("defender", defender.defender_ships);
      if (defender.defender_defense) setDefense(defender.defender_defense);
      if (!fk.fleet && (defender.unscanned_fields || []).includes("fleet")) setShips("defender", {});
      if (!fk.defense && (defender.unscanned_fields || []).includes("defense")) setDefense({});
      setResources(defender.defender_resources || {}, fk);
      setTech("defender", defender.defender_tech || {}, fk);
      updateDefenderUnscanned(defender.unscanned_fields || [], defender.target || {}, defender.unknown_label_keys || []);
      const route = formatDefenderRoute(defender.target || {});
      if (route) {
        state.route_labels = { ...(state.route_labels || {}), defender: route, from_spy: true };
        updateRouteLabels(state.route_labels);
      }
      const statusEl = root.querySelector("[data-sim-spy-status]");
      if (statusEl) {
        const known = localizedFieldList(defender.known_label_keys || []);
        const unknown = localizedFieldList(defender.unknown_label_keys || []);
        statusEl.textContent = tr(
          "combat_simulator_spy_import_detail",
          "Spionagebericht geladen: %(known)s bekannt, %(unknown)s unbekannt.",
          {
            known: known || tr("combat_simulator_nothing", "—"),
            unknown: unknown || tr("combat_simulator_nothing", "—"),
          }
        );
        statusEl.hidden = false;
      }
    }

    async function refreshAttackerDefaults() {
      try {
        const res = await GC.fetchGameAction("/api/combat-simulator/defaults");
        if (res && res.ok && res.defaults) {
          Object.assign(defaults, res.defaults);
          applyAttackerDefaults(res.defaults);
          return res.defaults;
        }
      } catch (_) {}
      applyAttackerDefaults(defaults);
      return defaults;
    }

    function renderSpyReportOptions(reports) {
      const sel = root.querySelector("[data-sim-spy-report-select]");
      if (!sel) return;
      const current = sel.value || String(state.spy_report_id || "");
      sel.innerHTML = `<option value="">${tr("combat_simulator_spy_report_pick", "Bericht wählen…")}</option>`;
      const nowSec = Math.floor(Date.now() / 1000);
      (reports || []).forEach((row) => {
        const opt = document.createElement("option");
        opt.value = String(row.id);
        const age = formatAge(Math.max(0, nowSec - (row.created_at || 0)));
        const target = [row.target_coords, row.target_planet || row.target_owner].filter(Boolean).join(" · ");
        opt.textContent = [target || row.subject, age, formatIntelTiers(row.intel_tier_keys || [])].filter(Boolean).join(" — ");
        sel.appendChild(opt);
      });
      if (current) sel.value = current;
      if (typeof GC.initHudSelects === "function") GC.initHudSelects(root);
    }

    async function loadSpyReports() {
      try {
        const res = await GC.fetchGameAction("/api/combat-simulator/spy-reports");
        if (res && res.ok) renderSpyReportOptions(res.reports || []);
      } catch (_) {}
    }

    async function importSpyReport() {
      const sel = root.querySelector("[data-sim-spy-report-select]");
      const messageId = parseInt(sel?.value || "0", 10);
      if (!messageId) {
        if (GC.showFlash) GC.showFlash(tr("combat_simulator_spy_pick_required", "Bitte Spionagebericht wählen."), "error");
        return;
      }
      const btn = root.querySelector("[data-sim-import-spy]");
      if (btn) btn.disabled = true;
      try {
        const res = await GC.fetchGameAction("/api/combat-simulator/import-spy-report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_id: messageId }),
        });
        if (res && res.ok && res.import && res.import.defender) {
          state.spy_report_id = messageId;
          applyDefenderImport(res.import.defender);
        } else if (GC.showFlash) {
          GC.showFlash(res?.error || tr("combat_simulator_spy_import_failed", "Import fehlgeschlagen"), "error");
        }
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function fmt(n) {
      return GC.formatNumber ? GC.formatNumber(n) : String(n);
    }

    function fmtCompact(n) {
      return GC.formatNumberCompact ? GC.formatNumberCompact(n) : fmt(n);
    }

    function fmtResourceTriple(obj) {
      const o = obj || {};
      return `${fmt(o.metal || 0)} / ${fmt(o.crystal || 0)} / ${fmt(o.fuel_cells || 0)}`;
    }

    function fmtResourcePair(obj) {
      const o = obj || {};
      return `${fmt(o.metal || 0)} / ${fmt(o.crystal || 0)}`;
    }

    function unitLabel(nameKey, unitKey) {
      return tr(nameKey, unitKey);
    }

    function fmtPct(n) {
      const v = Number(n);
      if (!Number.isFinite(v)) return "0 %";
      const s = v.toFixed(1).replace(".", ",");
      return `${s} %`;
    }

    const RESOURCE_ICON = {
      metal: "/static/img/res/Ferronit.webp",
      crystal: "/static/img/res/Crytite.webp",
      fuel_cells: "/static/img/res/Brennzellen.webp",
    };

    const WHY_CHIP_META = {
      combat_values_why_more_attack: { icon: "⚔", labelKey: "battle_lab_why_chip_attack" },
      combat_values_why_defender_no_tank: { icon: "⚔", labelKey: "battle_lab_why_chip_soft_def" },
      combat_values_why_defender_tougher: { icon: "🛡", labelKey: "battle_lab_why_chip_tough" },
      combat_values_why_defender_low_attack: { icon: "⚔", labelKey: "battle_lab_why_chip_low_atk" },
      combat_values_why_cargo_role: { icon: "🚛", labelKey: "battle_lab_why_chip_cargo" },
      combat_values_why_shield_hull_order: { icon: "🛡", labelKey: "battle_lab_why_chip_shield" },
      combat_values_why_rapid_fire: { icon: "⚡", labelKey: "battle_lab_why_chip_rapid" },
    };

    function resourceIconHtml(resKey) {
      const src = RESOURCE_ICON[resKey] || "";
      if (!src) return "";
      return `<img class="gbl-res-icon" src="${src}" alt="" width="22" height="22" loading="lazy">`;
    }

    function unitIconUrl(unitKey, unitType) {
      const folder = unitType === "defense" ? "defense" : "ships";
      return `/static/img/${folder}/${unitKey}.png`;
    }

    function unitIconHtml(unitKey, unitType) {
      const src = unitIconUrl(unitKey, unitType);
      const fallback = unitType === "defense"
        ? "/static/img/defense/sentinel_turret.png"
        : "/static/img/ships/seed_ark.png";
      return `<img class="gbl-unit-icon" src="${src}" alt="" width="28" height="28" loading="lazy" onerror="this.onerror=null;this.src='${fallback}'">`;
    }

    function renderResourceStripHtml(values, keys) {
      return keys
        .map((key) => {
          const val = Number(values[key === "fuel_cells" ? "fuel_cells" : key] ?? values[key] ?? 0);
          const resKey = key === "fuel" ? "fuel_cells" : key;
          return `<div class="gbl-res-cell"><span class="gbl-res-cell-icon">${resourceIconHtml(resKey)}</span><span class="gbl-res-cell-val">${fmt(val)}</span></div>`;
        })
        .join("");
    }

    function renderLossChipsHtml(rows) {
      const lost = (rows || []).filter((row) => Number(row.quantity) > 0);
      if (!lost.length) {
        return `<span class="gbl-unit-empty">${tr("battle_lab_bar_none", "Keine")}</span>`;
      }
      return lost
        .map((row) => {
          const name = unitLabel(row.name_key, row.unit_key);
          return `<span class="gbl-unit-chip" title="${escapeHtml(name)}">${unitIconHtml(row.unit_key, row.unit_type || "ship")}<span class="gbl-unit-chip-qty">×${fmt(row.quantity)}</span></span>`;
        })
        .join("");
    }

    function signalDot(status) {
      if (status === "good") return "🟢";
      if (status === "bad") return "🔴";
      return "🟡";
    }

    function buildAnalysisSignals(headline, narrative) {
      const analysis = narrative.analysis || [];
      const net = Number(headline.expected_profit ?? 0);
      const pct = Number(headline.attacker_win_pct ?? 0);
      const hasShield = analysis.some((row) => row.key === "battle_lab_bullet_shield_wall");
      const cargoWarn = analysis.some(
        (row) => row.key === "battle_lab_bullet_loot_partial" || row.key === "battle_lab_bullet_no_cargo"
      );
      return [
        {
          label: tr("battle_lab_signal_profit", "Profit"),
          status: net > 0 ? "good" : net < 0 ? "bad" : "warn",
        },
        {
          label: tr("battle_lab_signal_win", "Sieg"),
          status: pct >= 70 ? "good" : pct >= 40 ? "warn" : "bad",
        },
        {
          label: tr("battle_lab_signal_shield", "Schildwall"),
          status: hasShield ? "warn" : "good",
        },
        {
          label: tr("battle_lab_signal_cargo", "Cargo"),
          status: cargoWarn ? "warn" : "good",
        },
      ];
    }

    function renderAnalysisSignals(el, headline, narrative) {
      if (!el) return;
      el.innerHTML = buildAnalysisSignals(headline, narrative)
        .map(
          (sig) =>
            `<span class="gbl-signal-chip gbl-signal-chip--${sig.status}"><span class="gbl-signal-dot" aria-hidden="true">${signalDot(sig.status)}</span><span>${sig.label}</span></span>`
        )
        .join("");
    }

    function renderAdviceChips(el, items) {
      if (!el) return;
      el.innerHTML = (items || [])
        .map((item) => {
          const tip = renderNarrativeLine(item);
          return `<span class="gbl-advice-chip" title="${escapeHtml(tip)}">💡 ${tip}</span>`;
        })
        .join("");
    }

    function renderWhyChips(el, whyItems) {
      if (!el) return;
      el.innerHTML = (whyItems || [])
        .map((item) => {
          const meta = WHY_CHIP_META[item.key] || { icon: "•", labelKey: item.key };
          const short = tr(meta.labelKey, meta.labelKey);
          const tip = renderNarrativeLine(item);
          return `<span class="gbl-why-chip" title="${escapeHtml(tip)}"><span class="gbl-why-chip-ico" aria-hidden="true">${meta.icon}</span><span>${short}</span></span>`;
        })
        .join("");
    }

    function renderNarrativeLine(item) {
      const params = { ...(item.params || {}) };
      if (params.unit_name_key) {
        params.unit = unitLabel(params.unit_name_key, params.unit_key || params.unit);
        delete params.unit_name_key;
        delete params.unit_key;
      }
      return tr(item.key, item.key, params);
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/"/g, "&quot;");
    }

    function chipById(compact, chipId) {
      return ((compact && compact.chips) || []).find((chip) => chip.id === chipId);
    }

    function renderLossTile(chip, tone, icon) {
      if (chip && chip.mode === "single") {
        const name = unitLabel(chip.name_key, chip.unit_key);
        return `<div class="gbl-result-tile gbl-result-tile--${tone}"><span class="gbl-result-tile-ico" aria-hidden="true">${icon}</span><span class="gbl-result-tile-visual">${unitIconHtml(chip.unit_key, chip.unit_type || "ship")}<span class="gbl-result-tile-qty">×${fmt(chip.quantity)}</span></span></div>`;
      }
      if (chip && chip.mode === "multi") {
        const tip = (chip.units || [])
          .map((unit) => `${fmt(unit.quantity)} ${unitLabel(unit.name_key, unit.unit_key)}`)
          .join(" · ");
        const icons = (chip.units || [])
          .slice(0, 3)
          .map((unit) => unitIconHtml(unit.unit_key, unit.unit_type || "ship"))
          .join("");
        return `<div class="gbl-result-tile gbl-result-tile--${tone}" title="${escapeHtml(tip)}"><span class="gbl-result-tile-ico" aria-hidden="true">${icon}</span><span class="gbl-result-tile-visual gbl-result-tile-visual--multi">${icons}<span class="gbl-result-tile-qty">${tr("battle_lab_bar_multi_types", "%(count)s Einheitentypen", { count: chip.count })}</span></span></div>`;
      }
      return `<div class="gbl-result-tile gbl-result-tile--${tone}"><span class="gbl-result-tile-ico" aria-hidden="true">${icon}</span><span class="gbl-result-tile-val">${tr("battle_lab_bar_none", "Keine")}</span></div>`;
    }

    function renderLootTile(loot) {
      if (!loot || loot.mode !== "values") {
        return `<div class="gbl-result-tile gbl-result-tile--loot"><span class="gbl-result-tile-ico" aria-hidden="true">💰</span><span class="gbl-result-tile-val">${tr("battle_lab_bar_none", "Keine")}</span></div>`;
      }
      const icons = [
        resourceIconHtml("metal"),
        resourceIconHtml("crystal"),
        resourceIconHtml("fuel_cells"),
      ].join("");
      return `<div class="gbl-result-tile gbl-result-tile--loot"><span class="gbl-result-tile-ico" aria-hidden="true">💰</span><span class="gbl-result-tile-visual gbl-result-tile-visual--res">${icons}</span><span class="gbl-result-tile-val gbl-result-tile-val--compact">${fmtCompact(loot.metal)} / ${fmtCompact(loot.crystal)} / ${fmtCompact(loot.fuel)}</span></div>`;
    }

    function renderDebrisTile(debris) {
      if (!debris || debris.mode !== "values") {
        return `<div class="gbl-result-tile gbl-result-tile--debris"><span class="gbl-result-tile-ico" aria-hidden="true">✦</span><span class="gbl-result-tile-val">${tr("battle_lab_bar_none", "Keine")}</span></div>`;
      }
      const icons = [resourceIconHtml("metal"), resourceIconHtml("crystal")].join("");
      return `<div class="gbl-result-tile gbl-result-tile--debris"><span class="gbl-result-tile-ico" aria-hidden="true">✦</span><span class="gbl-result-tile-visual gbl-result-tile-visual--res">${icons}</span><span class="gbl-result-tile-val gbl-result-tile-val--compact">${fmtCompact(debris.metal)} / ${fmtCompact(debris.crystal)}</span></div>`;
    }

    function renderResultBar(banner, headline, compact) {
      const wrap = root.querySelector("[data-sim-result]");
      const bannerEl = root.querySelector("[data-sim-result-banner]");
      const pctEl = root.querySelector("[data-sim-result-pct]");
      const tilesEl = root.querySelector("[data-sim-result-tiles]");
      const detailsBtn = root.querySelector("[data-sim-details-toggle]");
      if (!wrap || !tilesEl) return;

      if (bannerEl && banner.banner_key) {
        bannerEl.textContent = tr(banner.banner_key, banner.banner_key);
        bannerEl.hidden = false;
      } else if (bannerEl) {
        bannerEl.hidden = true;
      }

      if (pctEl) {
        const pct = banner.primary_win_pct ?? headline.attacker_win_pct ?? 0;
        pctEl.textContent = tr("battle_lab_win_chance_line", "%(pct)s Siegchance", {
          pct: fmtPct(pct).replace(" %", " %"),
        });
        pctEl.hidden = false;
      }

      const own = chipById(compact, "own");
      const enemy = chipById(compact, "enemy");
      const loot = chipById(compact, "loot");
      const debris = chipById(compact, "debris");
      const net = chipById(compact, "net");
      const netRaw = Number(net?.raw ?? compact?.net_value ?? 0);
      const netTone = netRaw > 0 ? "positive" : netRaw < 0 ? "negative" : "neutral";
      const netIcon = netRaw >= 0 ? "📈" : "📉";
      const netText = netRaw > 0
        ? `+${fmtCompact(netRaw)}`
        : netRaw < 0
          ? `-${fmtCompact(Math.abs(netRaw))}`
          : fmtCompact(0);

      let lootText = tr("battle_lab_bar_none", "Keine");
      if (loot && loot.mode === "values") {
        lootText = `${fmtCompact(loot.metal)} / ${fmtCompact(loot.crystal)} / ${fmtCompact(loot.fuel)}`;
      }

      let debrisText = tr("battle_lab_bar_none", "Keine");
      if (debris && debris.mode === "values") {
        debrisText = `${fmtCompact(debris.metal)} / ${fmtCompact(debris.crystal)}`;
      }

      tilesEl.innerHTML = [
        renderLossTile(own, "own", "🛡"),
        renderLossTile(enemy, "enemy", "☠"),
        renderLootTile(loot),
        renderDebrisTile(debris),
        `<div class="gbl-result-tile gbl-result-tile--net gbl-result-tile--${netTone}"><span class="gbl-result-tile-ico" aria-hidden="true">${netIcon}</span><span class="gbl-result-tile-val">${netText}</span></div>`,
      ].join("");

      wrap.hidden = false;
      if (detailsBtn) detailsBtn.hidden = false;
    }

    function syncResultDetailsVisibility() {
      const panel = root.querySelector("[data-sim-details]");
      const btn = root.querySelector("[data-sim-details-toggle]");
      if (panel) panel.hidden = !showResultDetails;
      if (btn) {
        const chevron = showResultDetails ? "▲" : "▼";
        btn.innerHTML = `${tr("battle_lab_bar_details", "Details")} <span class="gbl-result-details-chevron" aria-hidden="true">${chevron}</span>`;
        btn.setAttribute("aria-expanded", showResultDetails ? "true" : "false");
      }
    }

    function renderCombatValueCard(row) {
      const name = unitLabel(row.name_key, row.unit_key);
      const atk = fmt(row.attack_effective ?? row.attack_base ?? 0);
      const sh = fmt(row.shield_effective ?? row.shield_base ?? 0);
      const hull = fmt(row.hull_effective ?? row.hull_base ?? 0);
      const zeroClass = Number(row.count) <= 0 ? " is-zero" : "";
      return `<article class="gbl-stat-card${zeroClass}">
        <div class="gbl-stat-card-head">${unitIconHtml(row.unit_key, row.unit_type || "ship")}<span>${name}</span></div>
        <div class="gbl-stat-row"><span class="gbl-stat-ico" aria-hidden="true">⚔</span><span>${atk}</span></div>
        <div class="gbl-stat-row"><span class="gbl-stat-ico" aria-hidden="true">🛡</span><span>${sh}</span></div>
        <div class="gbl-stat-row"><span class="gbl-stat-ico" aria-hidden="true">❤</span><span>${hull}</span></div>
      </article>`;
    }

    function renderCombatValues(combatValues) {
      lastCombatValues = combatValues || null;
      const section = root.querySelector("[data-sim-combat-values]");
      if (!section) return;
      if (!combatValues) {
        section.hidden = true;
        return;
      }
      section.hidden = false;
      ["attacker", "defender"].forEach((side) => {
        const el = section.querySelector(`[data-sim-combat-cards="${side}"]`);
        if (!el) return;
        const rows = showAllCombatValues
          ? combatValues[`${side}_all`] || combatValues[side] || []
          : combatValues[side] || [];
        const visible = showAllCombatValues ? rows : rows.filter((r) => Number(r.count) > 0);
        if (!visible.length) {
          el.innerHTML = `<p class="gbl-stat-empty">${tr("battle_lab_bar_none", "Keine")}</p>`;
          return;
        }
        el.innerHTML = visible.map((row) => renderCombatValueCard(row)).join("");
      });
      renderWhyChips(section.querySelector("[data-sim-combat-why]"), combatValues.why || []);
      const toggleBtn = section.querySelector("[data-sim-combat-values-toggle]");
      if (toggleBtn) {
        toggleBtn.textContent = showAllCombatValues
          ? tr("combat_values_show_deployed", "Nur eingesetzte Einheiten")
          : tr("combat_values_show_all", "Alle Werte anzeigen");
      }
    }

    function renderLossList(el, rows) {
      if (!el) return;
      if (!rows || !rows.length) {
        el.innerHTML = `<li class="combat-sim-loss-empty">${tr("combat_simulator_no_losses", "Keine")}</li>`;
        return;
      }
      el.innerHTML = rows
        .map((row) => {
          const name = unitLabel(row.name_key, row.unit_key);
          return `<li><span class="combat-sim-loss-name">${name}</span><span class="combat-sim-loss-qty">${fmt(row.quantity)}</span></li>`;
        })
        .join("");
    }

    function renderTimeline(el, timeline) {
      if (!el) return;
      if (!timeline || !timeline.length) {
        el.innerHTML = `<li class="combat-sim-timeline-empty">${tr("combat_simulator_no_rounds", "Keine Runden")}</li>`;
        return;
      }
      el.innerHTML = timeline
        .map((round) => {
          const atk = (round.attacker_losses || [])
            .map((r) => `${unitLabel(r.name_key, r.unit_key)} −${fmt(r.quantity)}`)
            .join(", ");
          const def = (round.defender_losses || [])
            .map((r) => `${unitLabel(r.name_key, r.unit_key)} −${fmt(r.quantity)}`)
            .join(", ");
          return `<li><span class="combat-sim-timeline-round">${tr("combat_simulator_round", "Runde %(n)s", { n: round.round })}</span> — ${tr("combat_simulator_attacker", "Angreifer")}: ${atk || tr("combat_simulator_no_losses", "Keine")}; ${tr("combat_simulator_defender", "Verteidiger")}: ${def || tr("combat_simulator_no_losses", "Keine")}</li>`;
        })
        .join("");
    }

    function isAdminPanelOpen() {
      const panel = root.querySelector("[data-sim-admin-panel]");
      return Boolean(panel && panel.open);
    }

    function updateAdminPanel() {
      if (!isAdmin) return;
      const detailsPre = root.querySelector("[data-sim-details-pre]");
      const samplePre = root.querySelector("[data-sim-sample-pre]");
      const show = isAdminPanelOpen() && lastResult;
      if (detailsPre) {
        detailsPre.hidden = !show;
        if (show) detailsPre.textContent = JSON.stringify(lastResult.summary || {}, null, 2);
      }
      if (samplePre) {
        samplePre.hidden = !show;
        if (show) samplePre.textContent = JSON.stringify(lastResult.sample_battle || {}, null, 2);
      }
    }

    function renderAdminDetails(result, display) {
      const detailsEl = document.getElementById("combat-sim-details");
      if (!isAdmin || !detailsEl) return;

      const iterLabel = detailsEl.querySelector("[data-sim-iterations-label]");
      if (iterLabel) {
        iterLabel.textContent = tr("combat_simulator_iterations_done", "Durchschnitt nach %(n)s Simulationen", {
          n: display.iterations || result.iterations || 1,
        });
        iterLabel.hidden = false;
      }

      const avgLosses = display.average_losses || {};
      renderLossList(detailsEl.querySelector("[data-sim-loss-attacker]"), avgLosses.attacker);
      renderLossList(detailsEl.querySelector("[data-sim-loss-defender-ships]"), avgLosses.defender_ships);
      renderLossList(detailsEl.querySelector("[data-sim-loss-defender-defense]"), avgLosses.defender_defense);

      const sampleWinnerEl = detailsEl.querySelector("[data-sim-sample-winner]");
      if (sampleWinnerEl && display.sample_winner) {
        sampleWinnerEl.textContent = tr("combat_simulator_sample_winner", "Sieger: %(winner)s", {
          winner: tr(`combat_simulator_winner_${display.sample_winner}`, display.sample_winner),
        });
        sampleWinnerEl.hidden = false;
      } else if (sampleWinnerEl) {
        sampleWinnerEl.hidden = true;
      }

      renderTimeline(detailsEl.querySelector("[data-sim-timeline]"), display.sample_timeline);
      updateAdminPanel();
    }

    function renderSummary(result) {
      const resultsEl = document.getElementById("combat-sim-results");
      if (!resultsEl || !result) return;

      const display = result.display || {};
      const headline = display.headline || {};
      const narrative = display.narrative || {};
      const banner = narrative.banner || {};
      const meter = narrative.meter || {};

      resultsEl.hidden = false;
      showResultDetails = false;

      renderResultBar(banner, headline, narrative.compact_summary);
      syncResultDetailsVisibility();

      const atkChips = resultsEl.querySelector("[data-sim-atk-loss-chips]");
      const defChips = resultsEl.querySelector("[data-sim-def-loss-chips]");
      if (atkChips) atkChips.innerHTML = renderLossChipsHtml(narrative.attacker_losses);
      if (defChips) defChips.innerHTML = renderLossChipsHtml(narrative.defender_losses);

      const lootStrip = resultsEl.querySelector("[data-sim-loot-strip]");
      if (lootStrip) lootStrip.innerHTML = renderResourceStripHtml(headline.loot || {}, ["metal", "crystal", "fuel_cells"]);
      const debrisStrip = resultsEl.querySelector("[data-sim-debris-strip]");
      if (debrisStrip) debrisStrip.innerHTML = renderResourceStripHtml(headline.debris || {}, ["metal", "crystal"]);

      const cargoChip = resultsEl.querySelector("[data-sim-cargo-chip]");
      const cargoPct = headline.cargo_fill_pct;
      if (cargoChip) {
        if (cargoPct != null && cargoPct >= 0) {
          cargoChip.hidden = false;
          cargoChip.innerHTML = `<span class="gbl-signal-dot" aria-hidden="true">🚛</span><span>${tr("battle_lab_cargo_load", "Cargo-Auslastung")}: ${fmtPct(cargoPct)}</span>`;
        } else {
          cargoChip.hidden = true;
        }
      }

      renderAnalysisSignals(resultsEl.querySelector("[data-sim-analysis-signals]"), headline, narrative);

      const advice = narrative.advice || [];
      const adviceBlock = resultsEl.querySelector("[data-sim-advice-block]");
      if (adviceBlock) {
        adviceBlock.hidden = !advice.length;
        renderAdviceChips(resultsEl.querySelector("[data-sim-advice-chips]"), advice);
      }

      renderCombatValues(display.combat_values);

      if (!isAdmin) {
        resultsEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
        return;
      }

      renderAdminDetails(result, display);
      resultsEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function syncShowAllButtons() {
      root.querySelectorAll("[data-sim-side]").forEach((sideEl) => {
        const side = sideEl.dataset.simSide;
        const btn = sideEl.querySelector("[data-sim-show-all-units]");
        if (!btn) return;
        btn.textContent = showAllUnits[side]
          ? tr("combat_simulator_show_active_only", "Nur gesetzte anzeigen")
          : tr("combat_simulator_show_all_units", "Alle Einheiten anzeigen");
        btn.classList.toggle("is-active", Boolean(showAllUnits[side]));
      });
    }

    function applyUnitFilters(sideEl) {
      if (!sideEl) return;
      const side = sideEl.dataset.simSide;
      const panel = sideEl.querySelector(".combat-sim-tab-panel.active");
      if (!panel) return;
      const showAll = Boolean(showAllUnits[side]);
      panel.querySelectorAll(".combat-sim-unit-row").forEach((row) => {
        const qty = parseQty(row.querySelector(".combat-sim-qty")?.value);
        row.hidden = !showAll && qty <= 0;
      });
    }

    function syncUnitToolbar(sideEl) {
      if (!sideEl) return;
      const panel = sideEl.querySelector(".combat-sim-tab-panel.active");
      const toolbar = sideEl.querySelector("[data-sim-unit-toolbar]");
      if (!toolbar || !panel) return;
      toolbar.hidden = !(panel.dataset.simPanel === "ships" || panel.dataset.simPanel === "defense");
    }

    async function runSimulation() {
      const defaultIter = parseInt(root.dataset.defaultIterations || "50", 10) || 50;
      const iterInput = root.querySelector("[data-sim-iterations]");
      const iterations = Math.max(
        1,
        Math.min(500, parseInt(iterInput?.value, 10) || defaultIter)
      );
      const calculateLoot = Boolean(root.querySelector("[data-sim-calculate-loot]")?.checked);
      const payload = {
        attacker_ships: readShips("attacker"),
        defender_ships: readShips("defender"),
        defender_defense: readDefense(),
        attacker_tech: readTech("attacker"),
        defender_tech: readTech("defender"),
        defender_resources: readResources(),
        calculate_loot: calculateLoot,
        iterations,
      };
      root.querySelectorAll("[data-sim-run]").forEach((btn) => {
        btn.disabled = true;
      });
      try {
        const res = await GC.fetchGameAction("/api/combat-simulator/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (res && res.ok && res.result) {
          lastResult = res.result;
          renderSummary(res.result);
        } else if (GC.showFlash) {
          GC.showFlash(res?.error || "Simulation failed", "error");
        }
      } finally {
        root.querySelectorAll("[data-sim-run]").forEach((btn) => {
          btn.disabled = false;
        });
      }
    }

    if (!root.dataset.simBound) {
      root.dataset.simBound = "1";

      root.addEventListener("click", (e) => {
        const tab = e.target.closest(".combat-sim-tab");
        if (tab) {
          const sideEl = tab.closest("[data-sim-side]");
          if (!sideEl) return;
          const tabName = tab.dataset.simTab;
          sideEl.querySelectorAll(".combat-sim-tab").forEach((t) => t.classList.toggle("active", t === tab));
          sideEl.querySelectorAll("[data-sim-panel]").forEach((p) => {
            const active = p.dataset.simPanel === tabName;
            p.classList.toggle("active", active);
            p.hidden = !active;
          });
          syncUnitToolbar(sideEl);
          applyUnitFilters(sideEl);
          return;
        }

        const showAllBtn = e.target.closest("[data-sim-show-all-units]");
        if (showAllBtn) {
          const sideEl = showAllBtn.closest("[data-sim-side]");
          const side = sideEl?.dataset?.simSide;
          if (side) {
            showAllUnits[side] = !showAllUnits[side];
            syncShowAllButtons();
            applyUnitFilters(sideEl);
          }
          return;
        }

        const cvToggle = e.target.closest("[data-sim-combat-values-toggle]");
        if (cvToggle) {
          showAllCombatValues = !showAllCombatValues;
          renderCombatValues(lastCombatValues);
          return;
        }

        const detailsToggle = e.target.closest("[data-sim-details-toggle]");
        if (detailsToggle) {
          showResultDetails = !showResultDetails;
          syncResultDetailsVisibility();
          return;
        }

        const maxBtn = e.target.closest("[data-qty-max]");
        if (maxBtn) {
          const row = maxBtn.closest(".combat-sim-unit-row");
          const inp = row?.querySelector(".combat-sim-qty");
          if (!inp || inp.disabled) return;
          const val = Math.max(0, parseInt(ownFleetStock()[inp.dataset.unitInput] || 0, 10));
          inp.value = String(val);
          applyUnitFilters(row.closest("[data-sim-side]"));
          return;
        }

        if (e.target.closest("[data-sim-reload-fleet]")) {
          refreshAttackerDefaults();
          return;
        }
        if (e.target.closest("[data-sim-import-spy]")) {
          importSpyReport();
          return;
        }
        if (e.target.closest("[data-sim-run]")) {
          runSimulation();
          return;
        }

        const copyBtn = e.target.closest("[data-sim-copy]");
        if (copyBtn && lastResult) {
          const fmtKind = copyBtn.dataset.simCopy;
          let text = "";
          if (fmtKind === "csv") {
            const s = lastResult.summary || {};
            text = [
              "metric,value",
              `attacker_win,${s.winner_probabilities?.attacker ?? 0}`,
              `defender_win,${s.winner_probabilities?.defender ?? 0}`,
              `draw,${s.winner_probabilities?.draw ?? 0}`,
              `avg_loot_metal,${s.average_loot?.metal ?? 0}`,
              `avg_loot_crystal,${s.average_loot?.crystal ?? 0}`,
              `avg_debris_metal,${s.average_debris?.metal ?? 0}`,
              `avg_debris_crystal,${s.average_debris?.crystal ?? 0}`,
            ].join("\n");
          } else if (fmtKind === "raw" || fmtKind === "json") {
            text = JSON.stringify(lastResult, null, 2);
          }
          navigator.clipboard?.writeText(text).catch(() => {});
        }
      });

      root.addEventListener("input", (e) => {
        if (e.target.matches(".combat-sim-qty")) {
          applyUnitFilters(e.target.closest("[data-sim-side]"));
        }
      });

      root.addEventListener("toggle", (e) => {
        if (e.target.matches("[data-sim-admin-panel]")) updateAdminPanel();
      }, true);
    }

    if (typeof GC.bindFormattedNumberInputs === "function") GC.bindFormattedNumberInputs(root);
    syncResultDetailsVisibility();
    root.querySelectorAll("[data-sim-side]").forEach((sideEl) => {
      syncUnitToolbar(sideEl);
    });
    syncShowAllButtons();
    updateRouteLabels(state.route_labels);
    if (state.auto_fill_attacker !== false) applyAttackerDefaults(defaults);
    if (presets.defender_ships || presets.defender_defense || state.spy_report_id) {
      applyDefenderPreset();
    }
    loadSpyReports();
  }

  window.GC = window.GC || {};
  window.GC.initCombatSimulatorPage = initCombatSimulatorPage;
})();
