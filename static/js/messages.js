/* Genesis Colonies – player messages inbox (PJAX-safe) */
(() => {
  "use strict";

  const GC = (window.GC = window.GC || {});

  /** Monotonic page init counter – invalidates in-flight loads after re-init. */
  let _messagesInitSeq = 0;

  function msgDebug(...args) {
    try {
      const dev =
        GC.DEBUG === true ||
        window.localStorage?.getItem("gc_debug") === "1" ||
        /localhost|127\.0\.0\.1/.test(window.location.hostname || "");
      if (dev && typeof console !== "undefined" && console.debug) {
        console.debug(...args);
      }
    } catch (_) {}
  }

  function t(key, fallback) {
    try {
      const dict = window.GC_LOCALE || {};
      if (Object.prototype.hasOwnProperty.call(dict, key)) {
        const val = dict[key];
        if (val !== null && val !== undefined && String(val).length > 0) return String(val);
      }
    } catch (_) {}
    return fallback || key;
  }

  function esc(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatInt(n) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "0";
    try {
      return Math.trunc(v).toLocaleString();
    } catch (_) {
      return String(Math.trunc(v));
    }
  }

  function shipLabel(key) {
    return t(`fleet_ship_${key}`, key);
  }

  function defenseLabel(key) {
    return t(`defense_${key}`, key);
  }

  function unitLabel(key, defenseStock) {
    const k = String(key || "");
    if (defenseStock && Object.prototype.hasOwnProperty.call(defenseStock, k)) {
      return defenseLabel(k);
    }
    return shipLabel(k);
  }

  function renderUnitRows(stock, defenseStock) {
    const entries = Object.entries(stock || {}).filter(([, qty]) => Number(qty) > 0);
    if (!entries.length) {
      return `<p class="gc-spy-report-empty">${esc(t("combat_report_fleet_empty", "—"))}</p>`;
    }
    return entries
      .sort(([a], [b]) => a.localeCompare(b))
      .map(
        ([key, qty]) =>
          `<div class="gc-spy-report-kv"><span>${esc(unitLabel(key, defenseStock))}</span><strong>×${esc(formatInt(qty))}</strong></div>`
      )
      .join("");
  }

  const COMBAT_MODAL = {
    root: null,
    dialog: null,
    titleEl: null,
    content: null,
    open: false,
  };

  function isCombatReportMsg(msg) {
    const meta = msg?.metadata || {};
    return (
      msg?.category === "combat" &&
      Number(meta.report_version) >= 2 &&
      Boolean(meta.target_coords)
    );
  }

  function combatResultVisual(resultKey) {
    const key = String(resultKey || "undecided");
    if (key === "attacker") {
      return { theme: "emerald", icon: "⚔", badge: "victory" };
    }
    if (key === "defender") {
      return { theme: "rose", icon: "🛡", badge: "defeat" };
    }
    if (key === "draw") {
      return { theme: "amber", icon: "◇", badge: "draw" };
    }
    return { theme: "cyan", icon: "◈", badge: "open" };
  }

  function unitCountTotal(stock) {
    return Object.values(stock || {}).reduce((sum, qty) => sum + Math.max(0, Number(qty) || 0), 0);
  }

  function renderCombatUnitGrid(stock, defenseStock) {
    const entries = Object.entries(stock || {}).filter(([, qty]) => Number(qty) > 0);
    if (!entries.length) {
      return `<p class="gc-combat-report-empty">${esc(t("combat_report_fleet_empty", "—"))}</p>`;
    }
    return (
      `<div class="gc-combat-unit-grid">` +
      entries
        .sort(([a], [b]) => a.localeCompare(b))
        .map(
          ([key, qty]) =>
            `<div class="gc-combat-unit-chip">` +
            `<span class="gc-combat-unit-chip-name">${esc(unitLabel(key, defenseStock))}</span>` +
            `<strong class="gc-combat-unit-chip-qty">×${esc(formatInt(qty))}</strong>` +
            `</div>`
        )
        .join("") +
      `</div>`
    );
  }

  function renderCombatLootChips(loot) {
    const rows = [];
    if (Number(loot?.metal || 0) > 0) {
      rows.push(
        `<div class="gc-expedition-loot-chip gc-expedition-loot-chip--metal">` +
          `<span class="gc-expedition-loot-label">${esc(t("resource_metal", "Ferronit"))}</span>` +
          `<strong class="gc-expedition-loot-value">${esc(formatInt(loot.metal))}</strong>` +
        `</div>`
      );
    }
    if (Number(loot?.crystal || 0) > 0) {
      rows.push(
        `<div class="gc-expedition-loot-chip gc-expedition-loot-chip--crystal">` +
          `<span class="gc-expedition-loot-label">${esc(t("resource_crystal", "Crytite"))}</span>` +
          `<strong class="gc-expedition-loot-value">${esc(formatInt(loot.crystal))}</strong>` +
        `</div>`
      );
    }
    if (Number(loot?.fuel_cells || 0) > 0) {
      rows.push(
        `<div class="gc-expedition-loot-chip gc-expedition-loot-chip--fuel">` +
          `<span class="gc-expedition-loot-label">${esc(t("resource_fuel_cells", "Fuel Cells"))}</span>` +
          `<strong class="gc-expedition-loot-value">${esc(formatInt(loot.fuel_cells))}</strong>` +
        `</div>`
      );
    }
    if (!rows.length) {
      return `<p class="gc-combat-report-empty">${esc(t("combat_report_loot_none", "No plunder"))}</p>`;
    }
    return `<div class="gc-expedition-loot-grid">${rows.join("")}</div>`;
  }

  function renderCombatPanel(title, bodyHtml, extraClass = "") {
    return (
      `<section class="gc-combat-report-panel${extraClass ? ` ${extraClass}` : ""}">` +
      `<h4 class="gc-combat-report-panel-title">${esc(title)}</h4>` +
      `<div class="gc-combat-report-panel-body">${bodyHtml}</div>` +
      `</section>`
    );
  }

  function renderCombatReportTeaser(meta, opts = {}) {
    const compact = Boolean(opts.compact);
    const messageId = opts.messageId;
    const resultKey = meta.result || meta.winner || "undecided";
    const visual = combatResultVisual(resultKey);
    const resultLabel = t(`combat_report_winner_${resultKey}`, resultKey);
    const rounds = formatInt(meta.rounds_fought || (meta.rounds || []).length || 0);
    const loot = meta.loot || {};
    const lootTotal = expeditionLootTotal(loot);
    const vsLine = t("combat_report_vs", "%(attacker)s vs %(defender)s")
      .replace("%(attacker)s", meta.attacker_name || "—")
      .replace("%(defender)s", meta.defender_name || "—");
    const openAttrs =
      messageId != null && Number.isFinite(Number(messageId))
        ? ` data-open-combat-report="${Number(messageId)}"`
        : "";

    const lootHint =
      lootTotal > 0
        ? `${formatInt(loot.metal || 0)} / ${formatInt(loot.crystal || 0)} / ${formatInt(loot.fuel_cells || 0)}`
        : t("combat_report_loot_none", "No plunder");

    return (
      `<div class="gc-combat-teaser gc-combat-teaser--${esc(visual.badge)}${compact ? " gc-combat-teaser--compact" : ""}" data-result="${esc(resultKey)}">` +
        `<div class="gc-combat-teaser-top">` +
          `<span class="gc-combat-teaser-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-combat-teaser-headings">` +
            `<span class="gc-combat-teaser-coords gc-mono">${esc(meta.target_coords || "—")}</span>` +
            `<span class="gc-combat-teaser-vs">${esc(vsLine)}</span>` +
          `</div>` +
          `<span class="gc-combat-teaser-badge">${esc(resultLabel)}</span>` +
        `</div>` +
        `<p class="gc-combat-teaser-meta gc-mono">${esc(
          t("combat_report_rounds_total", "%(count)s rounds").replace("%(count)s", rounds)
        )} · ${esc(lootHint)}</p>` +
        (!compact ? `<p class="gc-combat-teaser-hint">${esc(t("combat_report_teaser_hint", ""))}</p>` : "") +
        `<span class="gc-btn gc-btn-primary gc-btn-sm gc-combat-teaser-open" role="button" tabindex="0"${openAttrs}>${esc(
          t("combat_report_open_btn", "Open report")
        )}</span>` +
      `</div>`
    );
  }

  function renderCombatReportFull(meta) {
    const resultKey = meta.result || meta.winner || "undecided";
    const visual = combatResultVisual(resultKey);
    const resultLabel = t(`combat_report_winner_${resultKey}`, resultKey);
    const defenseStock = meta.defending_defense || {};
    const roundsCount = meta.rounds_fought || (meta.rounds || []).length || 0;
    const atkLossTotal = unitCountTotal(meta.attacker_losses);
    const defLossTotal = unitCountTotal(meta.defender_losses);
    const loot = meta.loot || {};
    const lootTotal = expeditionLootTotal(loot);

    const sections = [];

    sections.push(
      `<header class="gc-combat-report-hero gc-combat-report-hero--${esc(visual.badge)}">` +
        `<div class="gc-combat-report-hero-top">` +
          `<span class="gc-combat-report-hero-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-combat-report-hero-text">` +
            `<div class="gc-combat-report-coords gc-mono">${esc(meta.target_coords || "—")}</div>` +
            `<div class="gc-combat-report-vs">${esc(
              t("combat_report_vs", "%(attacker)s vs %(defender)s")
                .replace("%(attacker)s", meta.attacker_name || "—")
                .replace("%(defender)s", meta.defender_name || "—")
            )}</div>` +
          `</div>` +
          `<span class="gc-combat-report-result-badge">${esc(resultLabel)}</span>` +
        `</div>` +
      `</header>`
    );

    sections.push(
      `<div class="gc-player-card-stats gc-combat-report-stats">` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("combat_report_stat_rounds", "Rounds"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(roundsCount))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("combat_report_stat_atk_lost", "Attacker losses"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(atkLossTotal))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("combat_report_stat_def_lost", "Defender losses"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(defLossTotal))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("combat_report_stat_loot", "Plunder"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(lootTotal))}</span>` +
        `</div>` +
      `</div>`
    );

    sections.push(
      `<div class="gc-combat-report-columns">` +
        renderCombatPanel(
          t("combat_report_section_attacker", "Attacker"),
          renderCombatUnitGrid(meta.attacking_ships, null),
          "gc-combat-report-panel--attacker"
        ) +
        renderCombatPanel(
          t("combat_report_section_defender", "Defender"),
          renderCombatUnitGrid(meta.defending_ships, null) +
            renderCombatUnitGrid(defenseStock, defenseStock),
          "gc-combat-report-panel--defender"
        ) +
      `</div>`
    );

    const roundList = Array.isArray(meta.rounds) ? meta.rounds : [];
    if (roundList.length) {
      const roundHtml = roundList
        .map((rnd) => {
          const n = rnd.number || 0;
          return (
            `<details class="gc-combat-round">` +
            `<summary class="gc-combat-round-title">${esc(
              t("combat_report_section_round", "Round %(n)s").replace("%(n)s", formatInt(n))
            )}</summary>` +
            `<div class="gc-combat-round-body">` +
            renderCombatUnitGrid(rnd.attacker_losses, null) +
            renderCombatUnitGrid(rnd.defender_losses, defenseStock) +
            `</div>` +
            `</details>`
          );
        })
        .join("");
      sections.push(
        renderCombatPanel(t("combat_report_section_rounds", "Round log"), roundHtml, "gc-combat-report-panel--rounds")
      );
    }

    sections.push(
      renderCombatPanel(
        t("combat_report_section_losses", "Total losses"),
        renderCombatUnitGrid(meta.attacker_losses, null) + renderCombatUnitGrid(meta.defender_losses, defenseStock)
      )
    );

    const ret = meta.return_ships || {};
    if (unitCountTotal(ret) > 0) {
      sections.push(
        renderCombatPanel(
          t("combat_report_section_return", "Returning fleet"),
          renderCombatUnitGrid(ret, null),
          "gc-combat-report-panel--return"
        )
      );
    }

    sections.push(
      renderCombatPanel(
        t("combat_report_section_loot", "Plundered cargo"),
        renderCombatLootChips(loot),
        `gc-combat-report-panel--loot${lootTotal > 0 ? " gc-combat-report-panel--loot-found" : ""}`
      )
    );

    return (
      `<div class="gc-player-card-shell gc-combat-report-shell" data-theme="${esc(visual.theme)}">` +
      sections.join("") +
      `</div>`
    );
  }

  function cacheCombatModalElements() {
    if (COMBAT_MODAL.root && COMBAT_MODAL.content) return COMBAT_MODAL.root;
    COMBAT_MODAL.root = document.getElementById("gc-combat-report-root");
    if (!COMBAT_MODAL.root) return null;
    COMBAT_MODAL.dialog = COMBAT_MODAL.root.querySelector(".gc-combat-report-dialog");
    COMBAT_MODAL.titleEl = document.getElementById("gc-combat-report-title");
    COMBAT_MODAL.content = COMBAT_MODAL.root.querySelector("[data-cr-content]");
    return COMBAT_MODAL.root;
  }

  function openCombatReportModal(msg) {
    if (!msg || !isCombatReportMsg(msg)) return;
    const root = cacheCombatModalElements();
    if (!root || !COMBAT_MODAL.content) return;
    const meta = msg.metadata || {};
    const visual = combatResultVisual(meta.result || meta.winner || "undecided");
    if (COMBAT_MODAL.dialog) {
      COMBAT_MODAL.dialog.setAttribute("data-theme", visual.theme);
    }
    if (COMBAT_MODAL.titleEl) {
      const coords = meta.target_coords || "—";
      COMBAT_MODAL.titleEl.textContent = `${t("combat_report_modal_title", "Combat report")} — ${coords}`;
    }
    COMBAT_MODAL.content.innerHTML = renderCombatReportFull(meta);
    root.hidden = false;
    root.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-combat-report-open");
    COMBAT_MODAL.open = true;
    const closeBtn = root.querySelector("[data-cr-close].gc-player-card-close");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
  }

  function closeCombatReportModal() {
    const root = cacheCombatModalElements();
    if (!root) return;
    if (COMBAT_MODAL.content) COMBAT_MODAL.content.innerHTML = "";
    root.hidden = true;
    root.setAttribute("aria-hidden", "true");
    document.body.classList.remove("gc-combat-report-open");
    COMBAT_MODAL.open = false;
  }

  function resolveCombatMessage(messageId) {
    const id = Number(messageId);
    if (!Number.isFinite(id)) return null;
    const state = GC.messagesPageState;
    const cached = state?.messages?.find((m) => m.id === id);
    if (cached && isCombatReportMsg(cached)) return cached;
    return null;
  }

  async function openCombatReportById(messageId) {
    let msg = resolveCombatMessage(messageId);
    if (!msg) {
      const data = await messagesApi(`/api/messages/${messageId}`);
      if (data?.ok && data.data?.message && isCombatReportMsg(data.data.message)) {
        msg = data.data.message;
      }
    }
    if (msg) openCombatReportModal(msg);
  }

  function buildingLabel(key) {
    return t(`building_${key}`, key);
  }

  function missionLabel(mission) {
    return t(`fleet_mission_${mission}`, mission);
  }

  function renderSpyReport(meta) {
    const tiers = meta.intel_tiers || {};
    const sections = [];

    sections.push(
      `<div class="gc-spy-report-head">` +
        `<div class="gc-spy-report-coords">${esc(meta.target_coords || "—")}</div>` +
        `<div class="gc-spy-report-owner">${esc(meta.target_owner || "—")}</div>` +
        (meta.target_planet
          ? `<div class="gc-spy-report-planet">${esc(meta.target_planet)}</div>`
          : "") +
        `<div class="gc-spy-report-probes">${esc(t("fleet_spy_report_probes", "Probes deployed: %(count)s").replace("%(count)s", formatInt(meta.probe_count || 0)))}</div>` +
      `</div>`
    );

    function section(title, bodyHtml, locked, lockedText) {
      if (locked) {
        return (
          `<section class="gc-spy-report-section gc-spy-report-section--locked">` +
          `<h3 class="gc-spy-report-section-title">${esc(title)}</h3>` +
          `<p class="gc-spy-report-locked">${esc(lockedText)}</p>` +
          `</section>`
        );
      }
      return (
        `<section class="gc-spy-report-section">` +
        `<h3 class="gc-spy-report-section-title">${esc(title)}</h3>` +
        `<div class="gc-spy-report-section-body">${bodyHtml}</div>` +
        `</section>`
      );
    }

    const res = meta.resources || {};
    let resHtml = "";
    if (tiers.resources || tiers.fuel) {
      const rows = [];
      if (tiers.resources) {
        rows.push(
          `<div class="gc-spy-report-kv"><span>${esc(t("resource_metal", "Ferronit"))}</span><strong>${esc(formatInt(res.metal || 0))}</strong></div>`
        );
        rows.push(
          `<div class="gc-spy-report-kv"><span>${esc(t("resource_crystal", "Crytite"))}</span><strong>${esc(formatInt(res.crystal || 0))}</strong></div>`
        );
      }
      if (tiers.fuel) {
        rows.push(
          `<div class="gc-spy-report-kv"><span>${esc(t("resource_fuel_cells", "Fuel Cells"))}</span><strong>${esc(formatInt(res.fuel_cells || 0))}</strong></div>`
        );
      }
      resHtml = rows.join("");
    }
    sections.push(
      section(
        t("fleet_spy_report_section_resources", "Resources"),
        resHtml || `<p class="gc-spy-report-empty">${esc(t("fleet_spy_report_resources_locked", "Resources: insufficient probe data"))}</p>`,
        !tiers.resources && !tiers.fuel,
        t("fleet_spy_report_resources_locked", "Resources: insufficient probe data")
      )
    );

    const ships = meta.ships || {};
    let fleetHtml = "";
    if (tiers.fleet) {
      const entries = Object.entries(ships).filter(([, qty]) => Number(qty) > 0);
      fleetHtml = entries.length
        ? entries
            .sort(([a], [b]) => a.localeCompare(b))
            .map(
              ([key, qty]) =>
                `<div class="gc-spy-report-kv"><span>${esc(shipLabel(key))}</span><strong>×${esc(formatInt(qty))}</strong></div>`
            )
            .join("")
        : `<p class="gc-spy-report-empty">${esc(t("fleet_spy_report_fleet_empty", "No ships detected in orbit"))}</p>`;
    }
    sections.push(
      section(
        t("fleet_spy_report_section_fleet", "Orbital fleet"),
        fleetHtml,
        !tiers.fleet,
        t("fleet_spy_report_fleet_locked", "Orbital fleet: insufficient probe data")
      )
    );

    const defense = meta.defense || {};
    let defenseHtml = "";
    if (tiers.defense) {
      const rows = [
        `<div class="gc-spy-report-kv"><span>${esc(t("fleet_spy_report_defense_total", "Defense units"))}</span><strong>${esc(formatInt(defense.total_units || 0))}</strong></div>`,
        `<div class="gc-spy-report-kv"><span>${esc(t("fleet_spy_report_defense_power", "Defense power"))}</span><strong>${esc(formatInt(defense.defense_power || 0))}</strong></div>`,
        `<div class="gc-spy-report-kv"><span>${esc(t("fleet_spy_report_shield_power", "Shield power"))}</span><strong>${esc(formatInt(defense.shield_power || 0))}</strong></div>`,
      ];
      const units = defense.units || {};
      const unitEntries = Object.entries(units).filter(([, qty]) => Number(qty) > 0);
      if (unitEntries.length) {
        defenseHtml =
          rows.join("") +
          unitEntries
            .sort(([a], [b]) => a.localeCompare(b))
            .map(
              ([key, qty]) =>
                `<div class="gc-spy-report-kv"><span>${esc(t(`defense_${key}`, key))}</span><strong>×${esc(formatInt(qty))}</strong></div>`
            )
            .join("");
      } else {
        defenseHtml =
          rows.join("") +
          `<p class="gc-spy-report-empty">${esc(t("fleet_spy_report_defense_empty", "No defensive structures detected"))}</p>`;
      }
      if (defense.accuracy_pct != null && !defense.exact) {
        defenseHtml += `<div class="gc-spy-report-energy">${esc(
          t("fleet_spy_report_defense_accuracy", "Intel accuracy: ~%(pct)s%% (espionage research)").replace(
            "%(pct)s",
            formatInt(defense.accuracy_pct || 0)
          )
        )}</div>`;
      }
    }
    sections.push(
      section(
        t("fleet_spy_report_section_defense", "Planetary defense"),
        defenseHtml,
        !tiers.defense,
        t("fleet_spy_report_defense_locked", "Planetary defense: insufficient probe data")
      )
    );

    const buildings = meta.buildings || {};
    let buildHtml = "";
    if (tiers.buildings) {
      const entries = Object.entries(buildings).filter(([, lvl]) => Number(lvl) > 0);
      buildHtml = entries.length
        ? entries
            .sort(([a], [b]) => a.localeCompare(b))
            .map(
              ([key, lvl]) =>
                `<div class="gc-spy-report-kv"><span>${esc(buildingLabel(key))}</span><strong>L${esc(formatInt(lvl))}</strong></div>`
            )
            .join("")
        : `<p class="gc-spy-report-empty">${esc(t("fleet_spy_report_buildings_empty", "No surface installations detected"))}</p>`;
      if (meta.energy) {
        buildHtml +=
          `<div class="gc-spy-report-energy">${esc(
            t(
              "fleet_spy_report_energy",
              "Energy balance: %(balance)s (generated %(total)s / used %(used)s)"
            )
              .replace("%(balance)s", formatInt(meta.energy.balance || 0))
              .replace("%(total)s", formatInt(meta.energy.total || 0))
              .replace("%(used)s", formatInt(meta.energy.used || 0))
          )}</div>`;
      }
    }
    sections.push(
      section(
        t("fleet_spy_report_section_buildings", "Surface installations"),
        buildHtml,
        !tiers.buildings,
        t("fleet_spy_report_buildings_locked", "Surface installations: insufficient probe data")
      )
    );

    const activity = Array.isArray(meta.activity) ? meta.activity : [];
    let activityHtml = "";
    if (tiers.activity) {
      activityHtml = activity.length
        ? activity
            .map(
              (row) =>
                `<div class="gc-spy-report-activity-row">${esc(
                  t(
                    "fleet_spy_report_activity_row",
                    "%(mission)s → %(coords)s (%(status)s)"
                  )
                    .replace("%(mission)s", missionLabel(row.mission || ""))
                    .replace("%(coords)s", row.coords || "")
                    .replace("%(status)s", row.status || "")
                )}</div>`
            )
            .join("")
        : `<p class="gc-spy-report-empty">${esc(t("fleet_spy_report_activity_empty", "No outbound fleet activity detected"))}</p>`;
    }
    sections.push(
      section(
        t("fleet_spy_report_section_activity", "Fleet activity"),
        activityHtml,
        !tiers.activity,
        t("fleet_spy_report_activity_locked", "Fleet activity: insufficient probe data")
      )
    );

    return `<div class="gc-spy-report">${sections.join("")}</div>`;
  }

  function expeditionSeverityLabel(severity) {
    const key = `fleet_expedition_report_severity_${severity || "normal"}`;
    return t(key, severity || "normal");
  }

  function expeditionEventVisual(eventKey) {
    const map = {
      void_scan: { theme: "anomaly", icon: "◌" },
      sensor_glitch: { theme: "anomaly", icon: "◌" },
      mineral_deposit: { theme: "fund", icon: "◆" },
      fuel_cache: { theme: "fund", icon: "⚡" },
      debris_salvage: { theme: "fund", icon: "▣" },
      nav_interference: { theme: "disturbance", icon: "⚠" },
      distress_beacon: { theme: "alert", icon: "✦" },
      ancient_stash: { theme: "relic", icon: "✧" },
    };
    return map[eventKey] || { theme: "anomaly", icon: "◎" };
  }

  function expeditionEventBadge(eventKey, severity) {
    const badges = {
      nav_interference: "fleet_expedition_badge_disturbance",
      sensor_glitch: "fleet_expedition_badge_anomaly",
      void_scan: "fleet_expedition_badge_anomaly",
      distress_beacon: "fleet_expedition_badge_alert",
      ancient_stash: "fleet_expedition_badge_relic",
    };
    const key = badges[eventKey] || `fleet_expedition_badge_${severity || "normal"}`;
    return t(key, expeditionSeverityLabel(severity));
  }

  function expeditionRiskLabel(eventKey) {
    const high = new Set(["distress_beacon", "ancient_stash"]);
    const medium = new Set(["nav_interference"]);
    if (high.has(eventKey)) return t("fleet_expedition_report_risk_high", "elevated");
    if (medium.has(eventKey)) return t("fleet_expedition_report_risk_medium", "moderate");
    return t("fleet_expedition_report_risk_low", "low");
  }

  function expeditionFindLabel(rewards, severity, eventKey) {
    const total =
      Number(rewards?.metal || 0) +
      Number(rewards?.crystal || 0) +
      Number(rewards?.fuel_cells || 0);
    if (total <= 0) {
      if (eventKey === "nav_interference" || eventKey === "sensor_glitch") {
        return t("fleet_expedition_report_find_trace", "trace");
      }
      return t("fleet_expedition_report_find_none", "none");
    }
    if (severity === "major" || eventKey === "ancient_stash") {
      return t("fleet_expedition_report_find_major", "major");
    }
    if (severity === "minor" || total < 800) {
      return t("fleet_expedition_report_find_small", "small");
    }
    return t("fleet_expedition_report_find_standard", "standard");
  }

  function expeditionReturnLabel(delayExtra) {
    const delay = Number(delayExtra || 0);
    if (delay > 0) {
      return t("fleet_expedition_report_return_delayed", "Return +%(seconds)s").replace(
        "%(seconds)s",
        formatInt(delay)
      );
    }
    return t("fleet_expedition_report_return_nominal", "Return nominal");
  }

  function expeditionFleetStatus(delayExtra, rewardTotal) {
    if (Number(delayExtra || 0) > 0) {
      return t("fleet_expedition_report_fleet_status_delayed", "Return delayed");
    }
    if (Number(rewardTotal || 0) > 0) {
      return t("fleet_expedition_report_fleet_status_loaded", "Cargo secured");
    }
    return t("fleet_expedition_report_fleet_status_returning", "Returning");
  }

  function expeditionLootTotal(rewards) {
    return (
      Number(rewards?.metal || 0) +
      Number(rewards?.crystal || 0) +
      Number(rewards?.fuel_cells || 0)
    );
  }

  function renderExpeditionReport(meta) {
    const eventKey = meta.event_key || "void_scan";
    const eventLabel = t(
      meta.event_label_key || `expedition_event_${eventKey}`,
      eventKey
    );
    const descKey = meta.event_desc_key || `expedition_event_${eventKey}_desc`;
    const desc = t(descKey, "");
    const severity = meta.event_severity || "normal";
    const visual = expeditionEventVisual(eventKey);
    const rewards = meta.rewards || {};
    const lootTotal = expeditionLootTotal(rewards);
    const cargoTotal = Number(meta.cargo_total || 0);
    const delayExtra = Number(meta.delay_extra || 0);
    const badge = expeditionEventBadge(eventKey, severity);
    const risk = expeditionRiskLabel(eventKey);
    const find = expeditionFindLabel(rewards, severity, eventKey);
    const returnLabel = expeditionReturnLabel(delayExtra);
    const metaLine = t(
      "fleet_expedition_report_meta_line",
      "%(return)s · Risk: %(risk)s · Find: %(find)s"
    )
      .replace("%(return)s", returnLabel)
      .replace("%(risk)s", risk)
      .replace("%(find)s", find);

    const fleet = meta.fleet_ships || {};
    const fleetEntries = Object.entries(fleet).filter(([, qty]) => Number(qty) > 0);
    const fleetShipsText = fleetEntries.length
      ? fleetEntries
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([key, qty]) => `${formatInt(qty)}× ${shipLabel(key)}`)
          .join(" · ")
      : t("fleet_expedition_report_fleet_unknown", "Fleet composition unknown");
    const fleetSummary = t(
      "fleet_expedition_report_fleet_summary",
      "%(ships)s · Cargo %(used)s/%(total)s · Status: %(status)s"
    )
      .replace("%(ships)s", fleetShipsText)
      .replace("%(used)s", formatInt(lootTotal))
      .replace("%(total)s", formatInt(cargoTotal))
      .replace("%(status)s", expeditionFleetStatus(delayExtra, lootTotal));

    const sections = [];

    sections.push(
      `<header class="gc-expedition-card gc-expedition-card--${esc(visual.theme)}" data-event="${esc(eventKey)}">` +
        `<div class="gc-expedition-card-top">` +
          `<span class="gc-expedition-card-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-expedition-card-headings">` +
            `<h3 class="gc-expedition-card-title">${esc(eventLabel)}</h3>` +
            `<span class="gc-expedition-card-badge">${esc(badge)}</span>` +
          `</div>` +
        `</div>` +
        `<p class="gc-expedition-card-meta gc-mono">${esc(metaLine)}</p>` +
        (desc ? `<p class="gc-expedition-card-desc">${esc(desc)}</p>` : "") +
        `<div class="gc-expedition-card-coords gc-mono">${esc(meta.target_coords || "—")}</div>` +
      `</header>`
    );

    sections.push(
      `<section class="gc-expedition-panel gc-expedition-panel--fleet">` +
        `<h4 class="gc-expedition-panel-title">${esc(t("fleet_expedition_report_section_fleet", "Expedition fleet"))}</h4>` +
        `<p class="gc-expedition-fleet-summary">${esc(fleetSummary)}</p>` +
      `</section>`
    );

    const rewardRows = [];
    if (Number(rewards.metal || 0) > 0) {
      rewardRows.push(
        `<div class="gc-expedition-loot-chip gc-expedition-loot-chip--metal">` +
          `<span class="gc-expedition-loot-label">${esc(t("resource_metal", "Ferronit"))}</span>` +
          `<strong class="gc-expedition-loot-value">${esc(formatInt(rewards.metal))}</strong>` +
        `</div>`
      );
    }
    if (Number(rewards.crystal || 0) > 0) {
      rewardRows.push(
        `<div class="gc-expedition-loot-chip gc-expedition-loot-chip--crystal">` +
          `<span class="gc-expedition-loot-label">${esc(t("resource_crystal", "Crytite"))}</span>` +
          `<strong class="gc-expedition-loot-value">${esc(formatInt(rewards.crystal))}</strong>` +
        `</div>`
      );
    }
    if (Number(rewards.fuel_cells || 0) > 0) {
      rewardRows.push(
        `<div class="gc-expedition-loot-chip gc-expedition-loot-chip--fuel">` +
          `<span class="gc-expedition-loot-label">${esc(t("resource_fuel_cells", "Fuel Cells"))}</span>` +
          `<strong class="gc-expedition-loot-value">${esc(formatInt(rewards.fuel_cells))}</strong>` +
        `</div>`
      );
    }

    const lootBody = rewardRows.length
      ? `<div class="gc-expedition-loot-grid">${rewardRows.join("")}</div>`
      : `<div class="gc-expedition-loot-empty">` +
          `<span class="gc-expedition-loot-empty-mark" aria-hidden="true">—</span>` +
          `<span class="gc-expedition-loot-empty-text">${esc(
            t("fleet_expedition_report_loot_empty", "No recoverable find")
          )}</span>` +
        `</div>`;

    sections.push(
      `<section class="gc-expedition-panel gc-expedition-panel--loot gc-expedition-panel--loot-${rewardRows.length ? "found" : "empty"}">` +
        `<h4 class="gc-expedition-panel-title">${esc(t("fleet_expedition_report_section_loot", "Recovered cargo"))}</h4>` +
        lootBody +
      `</section>`
    );

    return `<div class="gc-expedition-report gc-expedition-report--${esc(eventKey)}">${sections.join("")}</div>`;
  }

  function renderMessageBody(msg) {
    const meta = msg.metadata || {};
    if (isCombatReportMsg(msg)) {
      return { html: null, plain: msg.body || "", combatReport: true };
    }
    if (msg.category === "espionage" && meta.report_version >= 2 && meta.intel_tiers) {
      return { html: renderSpyReport(meta), plain: msg.body || "" };
    }
    if (msg.category === "expedition" && meta.report_version >= 2 && meta.event_key) {
      return { html: renderExpeditionReport(meta), plain: msg.body || "" };
    }
    return { html: null, plain: msg.body || "" };
  }

  function categoryLabel(cat) {
    return t(`messages.category.${cat}`, cat);
  }

  function formatTime(ts) {
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return "–";
    try {
      return new Date(n * 1000).toLocaleString();
    } catch (_) {
      return String(n);
    }
  }

  function getMessagesDom() {
    const page = document.getElementById("messages-page");
    if (!page) return null;
    return {
      page,
      list: document.getElementById("messages-list"),
      detail: document.getElementById("messages-detail"),
      detailEmpty: document.getElementById("messages-detail-empty"),
      detailSubject: document.getElementById("messages-detail-subject"),
      detailMeta: document.getElementById("messages-detail-meta"),
      detailBody: document.getElementById("messages-detail-body"),
      detailActions: document.getElementById("messages-detail-actions"),
    };
  }

  /** Inbox fetch – bypass GC.fetchJSON so PJAX cleanup cannot abort list loads. */
  async function messagesApi(url, options = {}) {
    const headers = {
      Accept: "application/json",
      "X-Requested-With": "XMLHttpRequest",
      ...(options.headers || {}),
    };
    const fetchOpts = {
      cache: "no-store",
      credentials: "same-origin",
      redirect: "manual",
      ...options,
      headers,
    };

    try {
      const res = await fetch(url, fetchOpts);
      const ct = (res.headers.get("content-type") || "").toLowerCase();
      if (res.type === "opaqueredirect" || res.status === 401 || res.status === 403) {
        return { ok: false, error: "not_logged_in", status: res.status };
      }
      if (!ct.includes("application/json")) {
        return { ok: false, error: "error_load", status: res.status };
      }
      const data = await res.json();
      if (!res.ok && data && typeof data === "object") {
        return { ...data, ok: false, status: res.status };
      }
      if (!data || typeof data !== "object") {
        return { ok: false, error: "error_load", status: res.status };
      }
      return data;
    } catch (err) {
      if (err?.name === "AbortError") {
        const abortErr = new Error("aborted");
        abortErr.name = "AbortError";
        throw abortErr;
      }
      return { ok: false, error: "error_load", status: err?.status || 0 };
    }
  }

  function syncUnreadFromResponse(data) {
    const n = data?.data?.unread_count;
    if (typeof n === "number") {
      updateLocalUnread(n);
      if (GC.messagesPageState) {
        GC.messagesPageState.unreadSyncedFromApi = true;
      }
      return true;
    }
    return false;
  }

  function updateLocalUnread(count) {
    const n = Math.max(0, Number(count) || 0);
    const el = document.getElementById("messages-unread-count");
    if (el) el.textContent = String(n);
    if (typeof GC.updateMessagesUnreadBadges === "function") {
      GC.updateMessagesUnreadBadges(n);
    }
    if (typeof GC.setMessagesUnreadPollBaseline === "function") {
      GC.setMessagesUnreadPollBaseline(n);
    }
  }

  function refreshBadgesFromServer() {
    if (typeof GC.refreshGameState === "function") {
      return GC.refreshGameState("messages_sync");
    }
    return Promise.resolve();
  }

  function getComposeDialog() {
    return document.getElementById("messages-compose-dialog");
  }

  function openCompose(recipient = "", subject = "") {
    const composeDialog = getComposeDialog();
    if (!composeDialog) return;
    const r = document.getElementById("messages-compose-recipient");
    const s = document.getElementById("messages-compose-subject");
    const b = document.getElementById("messages-compose-body");
    const composeStatus = document.getElementById("messages-compose-status");
    if (r) r.value = recipient;
    if (s) s.value = subject;
    if (b) b.value = "";
    if (composeStatus) composeStatus.textContent = "";
    if (typeof composeDialog.showModal === "function") {
      composeDialog.showModal();
    }
  }

  function closeCompose() {
    const dlg = getComposeDialog();
    if (dlg?.open) dlg.close();
  }

  function isCurrentInit(state, initSeq) {
    return (
      state === GC.messagesPageState &&
      state?.initSeq === initSeq &&
      initSeq === _messagesInitSeq &&
      !!getMessagesDom()
    );
  }

  function isCurrentRequest(state, initSeq, requestId) {
    return isCurrentInit(state, initSeq) && state.requestSeq === requestId;
  }

  function ensureMessagesState() {
    if (!document.getElementById("messages-page")) return null;
    if (!GC.messagesPageState) {
      initMessagesPage();
    }
    return GC.messagesPageState || null;
  }

    function resetMessagesPageState() {
    const prev = GC.messagesPageState;
    if (prev) {
      prev.requestSeq += 1;
      prev.loading = false;
      prev.listInflight = null;
      prev.inflightFilter = null;
      prev.listAbort = null;
      prev.unreadSyncedFromApi = false;
    }
    GC.messagesPageState = null;
    closeCompose();
    closeCombatReportModal();
  }

  function bindMessagesUiOnce() {
    if (GC._messagesUiBound) return;
    GC._messagesUiBound = true;

    const registerCleanup = GC.registerPageCleanup || GC.registerCleanup;
    if (typeof registerCleanup === "function") {
      registerCleanup(() => {
        msgDebug("[messages] cleanup (leave page)");
        resetMessagesPageState();
      }, { persistent: true });
    }

    const composeForm = document.getElementById("messages-compose-form");
    composeForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const state = GC.messagesPageState;
      const recipient = document.getElementById("messages-compose-recipient")?.value || "";
      const subject = document.getElementById("messages-compose-subject")?.value || "";
      const body = document.getElementById("messages-compose-body")?.value || "";
      const composeStatus = document.getElementById("messages-compose-status");
      if (composeStatus) composeStatus.textContent = "";

      const data = await messagesApi("/api/messages/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipient, subject, body }),
      });

      if (data?.ok) {
        if (composeStatus) composeStatus.textContent = t("messages.sent_success");
        closeCompose();
        await refreshBadgesFromServer();
        return;
      }

      const err = data?.error || "validation";
      if (composeStatus) {
        composeStatus.textContent = t(`messages.error_${err}`, t("messages.error_validation"));
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !COMBAT_MODAL.open) return;
      e.preventDefault();
      closeCombatReportModal();
    });

    cacheCombatModalElements();
    COMBAT_MODAL.root?.querySelectorAll("[data-cr-close]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        closeCombatReportModal();
      });
    });

    document.addEventListener("click", (e) => {
      const composeTo = e.target.closest("[data-messages-compose]");
      if (composeTo) {
        e.preventDefault();
        e.stopPropagation();
        openCompose(composeTo.dataset.recipientName || "");
        return;
      }

      if (!document.getElementById("messages-page")) return;

      const state = ensureMessagesState();
      if (!state) return;

      if (e.target.closest("#messages-compose-btn")) {
        e.preventDefault();
        e.stopPropagation();
        openCompose();
        return;
      }
      if (e.target.closest("#messages-compose-close")) {
        e.preventDefault();
        closeCompose();
        return;
      }

      if (e.target.closest("#messages-mark-all-read")) {
        e.preventDefault();
        e.stopPropagation();
        state.onMarkAllRead?.();
        return;
      }

      const tabBtn = e.target.closest("#messages-tabs .tab-btn[data-filter]");
      if (tabBtn) {
        e.preventDefault();
        e.stopPropagation();
        const tabsEl = document.getElementById("messages-tabs");
        tabsEl?.querySelectorAll(".tab-btn").forEach((b) => {
          const active = b === tabBtn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", active ? "true" : "false");
        });
        state.filter = tabBtn.dataset.filter || "all";
        state.selectedId = null;
        state.setDetailVisible?.(false);
        state.loadList?.(true, { force: true });
        return;
      }

      const openCombatBtn = e.target.closest("[data-open-combat-report]");
      if (openCombatBtn) {
        e.preventDefault();
        e.stopPropagation();
        const id = Number(openCombatBtn.dataset.openCombatReport);
        if (Number.isFinite(id)) {
          openCombatReportById(id);
        }
        return;
      }

      const item = e.target.closest(".gc-messages-item[data-id]");
      if (item) {
        e.preventDefault();
        const id = Number(item.dataset.id);
        if (Number.isFinite(id)) state.openMessage?.(id);
        return;
      }

      const actionBtn = e.target.closest("#messages-detail-actions button[data-action]");
      if (actionBtn && state.selectedId) {
        e.preventDefault();
        const msg = state.messages?.find((m) => m.id === state.selectedId);
        if (msg) state.handleAction?.(actionBtn.dataset.action, msg);
      }
    });
  }

  function readActiveFilterFromDom() {
    const activeTab = document.querySelector("#messages-tabs .tab-btn.active[data-filter]");
    return activeTab?.dataset.filter || "all";
  }

  function initMessagesPage(options) {
    bindMessagesUiOnce();

    if (!document.getElementById("messages-page")) {
      resetMessagesPageState();
      return;
    }

    const initSeq = ++_messagesInitSeq;
    resetMessagesPageState();

    const tabsEl = document.getElementById("messages-tabs");
    tabsEl?.querySelectorAll(".tab-btn[data-filter]").forEach((btn) => {
      const isAll = (btn.dataset.filter || "") === "all";
      btn.classList.toggle("active", isAll);
      btn.setAttribute("aria-selected", isAll ? "true" : "false");
    });

    const filter = "all";
    console.debug("[messages] init", { initSeq, filter });
    msgDebug("[messages] init detail", { pjax: Boolean(options && options.pjax) });

    const state = {
      initSeq,
      filter,
      messages: [],
      selectedId: null,
      requestSeq: 0,
      listAbort: null,
      listInflight: null,
      inflightFilter: null,
      unreadSyncedFromApi: false,
      loading: false,
      listLoaded: false,
    };

    function setDetailVisible(show) {
      const dom = getMessagesDom();
      if (!dom) return;
      if (dom.detail) dom.detail.hidden = !show;
      if (dom.detailEmpty) dom.detailEmpty.hidden = show;
    }

    function showListMessage(html) {
      const dom = getMessagesDom();
      if (!dom?.list) return;
      dom.list.innerHTML = html;
    }

    function showLoadingList() {
      state.loading = true;
      const dom = getMessagesDom();
      if (!state.listLoaded) {
        state.listLoaded = false;
        showListMessage(`<div class="gc-messages-empty">${esc(t("messages.loading"))}</div>`);
      } else if (dom?.list) {
        dom.list.classList.add("is-loading");
      }
    }

    function cancelInboxFetch() {
      if (state.listAbort) {
        try {
          state.listAbort.abort();
        } catch (_) {}
        state.listAbort = null;
      }
      state.listInflight = null;
      state.inflightFilter = null;
      state.loading = false;
      getMessagesDom()?.list?.classList.remove("is-loading");
    }

    function showErrorList(errKey, withRetry = true) {
      state.loading = false;
      state.listLoaded = true;
      const dom = getMessagesDom();
      dom?.list?.classList.remove("is-loading");
      const errLabel = esc(t(`messages.error_${errKey}`, t("messages.error_load")));
      const retryBtn = withRetry
        ? `<button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-messages-retry>` +
          `${esc(t("messages.retry", "Erneut laden"))}</button>`
        : "";
      showListMessage(
        `<div class="gc-messages-empty"><p>${errLabel}</p>${retryBtn}</div>`
      );
      dom?.list?.querySelector("[data-messages-retry]")?.addEventListener("click", () => {
        loadList(true, { force: true });
      });
    }

    function renderList() {
      const dom = getMessagesDom();
      if (!dom?.list) return;
      dom.list.classList.remove("is-loading");

      if (state.loading || !state.listLoaded) {
        if (!state.listLoaded) {
          showListMessage(`<div class="gc-messages-empty">${esc(t("messages.loading"))}</div>`);
        }
        return;
      }

      if (!state.messages.length) {
        showListMessage(`<div class="gc-messages-empty">${esc(t("messages.empty"))}</div>`);
        state.selectedId = null;
        setDetailVisible(false);
        return;
      }

      dom.list.innerHTML = state.messages
        .map((m) => {
          const unread = !m.is_read;
          const active = state.selectedId === m.id ? " is-active" : "";
          const unreadCls = unread ? " is-unread" : "";
          const combatCls = isCombatReportMsg(m) ? " gc-messages-item--combat" : "";
          const teaser =
            isCombatReportMsg(m) ?
              renderCombatReportTeaser(m.metadata || {}, { compact: true, messageId: m.id })
            : "";
          return (
            `<button type="button" class="gc-messages-item${active}${unreadCls}${combatCls}" data-id="${m.id}">` +
            `<span class="gc-messages-item-subject">${esc(m.subject)}</span>` +
            (teaser ? `<span class="gc-messages-item-teaser">${teaser}</span>` : "") +
            `<span class="gc-messages-item-meta">${esc(categoryLabel(m.category))} · ${esc(formatTime(m.created_at))}</span>` +
            `</button>`
          );
        })
        .join("");
    }

    function renderDetail(msg) {
      if (!msg) {
        setDetailVisible(false);
        return;
      }
      const dom = getMessagesDom();
      if (!dom) return;
      setDetailVisible(true);
      if (dom.detailSubject) dom.detailSubject.textContent = msg.subject || "";
      const sender = msg.sender_name || categoryLabel(msg.category);
      if (dom.detailMeta) {
        dom.detailMeta.textContent = `${sender} · ${categoryLabel(msg.category)} · ${formatTime(msg.created_at)}`;
      }
      const rendered = renderMessageBody(msg);
      if (dom.detailBody) {
        if (rendered.combatReport) {
          dom.detailBody.classList.add("gc-messages-detail-body--report");
          dom.detailBody.innerHTML = renderCombatReportTeaser(msg.metadata || {}, {
            compact: false,
            messageId: msg.id,
          });
        } else if (rendered.html) {
          dom.detailBody.classList.add("gc-messages-detail-body--report");
          dom.detailBody.innerHTML = rendered.html;
        } else {
          dom.detailBody.classList.remove("gc-messages-detail-body--report");
          dom.detailBody.textContent = rendered.plain;
        }
      }
      if (!dom.detailActions) return;
      dom.detailActions.innerHTML = "";

      const mkBtn = (label, action, variant = "outline") => {
        const b = document.createElement("button");
        b.type = "button";
        const cls =
          variant === "primary"
            ? "gc-btn gc-btn-primary gc-btn-sm"
            : variant === "danger"
              ? "gc-btn gc-btn-danger gc-btn-sm"
              : "gc-btn gc-btn-outline gc-btn-sm";
        b.className = cls;
        b.dataset.action = action;
        b.textContent = label;
        return b;
      };

      if (rendered.combatReport) {
        dom.detailActions.appendChild(
          mkBtn(t("combat_report_open_full", "Open full report"), "open_combat_report", "primary")
        );
      }
      if (!msg.is_read) dom.detailActions.appendChild(mkBtn(t("messages.read"), "read", "outline"));
      if (msg.reply_to_player_id || msg.sender_player_id) {
        dom.detailActions.appendChild(mkBtn(t("messages.reply"), "reply", "primary"));
      }
      if (!msg.is_archived) dom.detailActions.appendChild(mkBtn(t("messages.archive"), "archive", "outline"));
      dom.detailActions.appendChild(mkBtn(t("messages.delete"), "delete", "danger"));
    }

    function clearLoadingIfStale(requestId) {
      if (state.requestSeq !== requestId) return;
      state.loading = false;
      getMessagesDom()?.list?.classList.remove("is-loading");
    }

    function finishLoadAttempt(requestId) {
      if (!isCurrentRequest(state, initSeq, requestId)) return false;
      state.loading = false;
      return true;
    }

    async function loadListImpl(retryNotReady = true) {
      const requestId = ++state.requestSeq;
      const ctrl = new AbortController();
      state.listAbort = ctrl;
      const timeoutMs = 20000;
      const timeoutId = setTimeout(() => {
        try {
          ctrl.abort();
        } catch (_) {}
      }, timeoutMs);

      showLoadingList();

      try {
        const params = new URLSearchParams({ limit: "50" });
        if (state.filter && state.filter !== "all") params.set("category", state.filter);
        if (state.filter === "archive") params.set("include_archived", "1");

        const data = await messagesApi(`/api/messages?${params.toString()}`, {
          signal: ctrl.signal,
        });

        if (!isCurrentRequest(state, initSeq, requestId)) {
          clearLoadingIfStale(requestId);
          return;
        }

        if (!data || !data.ok) {
          const err = data?.error || "error_load";
          if (
            (err === "messages_not_ready" || data?.status === 503) &&
            retryNotReady &&
            isCurrentRequest(state, initSeq, requestId)
          ) {
            await new Promise((r) => setTimeout(r, 400));
            if (isCurrentRequest(state, initSeq, requestId)) {
              return loadListImpl(false);
            }
            return;
          }
          if (finishLoadAttempt(requestId)) {
            console.debug("[messages] inbox load failed", { error: err, filter: state.filter });
            showErrorList(err);
          }
          return;
        }

        if (!finishLoadAttempt(requestId)) return;

        state.messages = data.data?.messages || [];
        state.listLoaded = true;
        state.unreadSyncedFromApi = true;
        syncUnreadFromResponse(data);
        renderList();
        console.debug("[messages] inbox loaded", {
          count: state.messages.length,
          unread: data.data?.unread_count,
          filter: state.filter,
        });
        msgDebug("[messages] inbox detail", { initSeq, requestId, player_id: data.data?.player_id });

        if (state.selectedId) {
          const current = state.messages.find((m) => m.id === state.selectedId);
          if (current) renderDetail(current);
          else {
            state.selectedId = null;
            setDetailVisible(false);
          }
        }
      } catch (err) {
        if (err?.name === "AbortError") {
          clearLoadingIfStale(requestId);
          return;
        }
        if (!isCurrentRequest(state, initSeq, requestId)) {
          clearLoadingIfStale(requestId);
          return;
        }
        if (finishLoadAttempt(requestId)) {
          console.debug("[messages] inbox load error", err);
          showErrorList("error_load");
        }
      } finally {
        clearTimeout(timeoutId);
        if (state.listAbort === ctrl) state.listAbort = null;
      }
    }

    async function loadList(retryNotReady = true, opts = {}) {
      if (!isCurrentInit(state, initSeq)) return;
      const force = Boolean(opts && opts.force);

      if (state.listInflight) {
        if (!force && state.inflightFilter === state.filter) {
          return state.listInflight;
        }
        cancelInboxFetch();
        state.requestSeq += 1;
      }

      state.inflightFilter = state.filter;
      const run = loadListImpl(retryNotReady);
      state.listInflight = run;
      try {
        return await run;
      } finally {
        if (state.listInflight === run) {
          state.listInflight = null;
          state.inflightFilter = null;
        }
      }
    }

    function showDetailError(key) {
      setDetailVisible(true);
      const dom = getMessagesDom();
      if (!dom) return;
      if (dom.detailSubject) dom.detailSubject.textContent = t("messages.error_load", "Could not load message.");
      if (dom.detailMeta) dom.detailMeta.textContent = "";
      if (dom.detailBody) {
        dom.detailBody.textContent = t(`messages.error_${key}`, t("messages.error_load"));
      }
      if (dom.detailActions) dom.detailActions.innerHTML = "";
    }

    async function openMessage(id) {
      const data = await messagesApi(`/api/messages/${id}`);
      if (!isCurrentInit(state, initSeq)) return;
      if (!data || !data.ok) {
        showDetailError(data?.error || "load");
        return;
      }
      const msg = data.data?.message;
      if (!msg) {
        showDetailError("load");
        return;
      }
      state.selectedId = id;
      const idx = state.messages.findIndex((m) => m.id === id);
      if (idx >= 0) state.messages[idx] = msg;
      renderList();
      renderDetail(msg);
      if (!syncUnreadFromResponse(data)) await refreshBadgesFromServer();
    }

    async function postAction(url) {
      const data = await messagesApi(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!syncUnreadFromResponse(data)) await refreshBadgesFromServer();
      return data;
    }

    async function handleAction(action, msg) {
      if (!msg) return;
      if (action === "read") await postAction(`/api/messages/${msg.id}/read`);
      else if (action === "archive") await postAction(`/api/messages/${msg.id}/archive`);
      else if (action === "delete") {
        if (!window.confirm(t("messages.delete_confirm"))) return;
        await postAction(`/api/messages/${msg.id}/delete`);
        state.selectedId = null;
        setDetailVisible(false);
      } else if (action === "reply") {
        openCompose(msg.reply_to_name || msg.sender_name || "", msg.subject ? `Re: ${msg.subject}` : "");
        return;
      } else if (action === "open_combat_report") {
        openCombatReportModal(msg);
        return;
      }
      await loadList();
      if (state.selectedId && action !== "delete") await openMessage(state.selectedId);
    }

    state.onMarkAllRead = async () => {
      const payload = {};
      if (state.filter && !["all", "archive"].includes(state.filter)) {
        payload.category = state.filter;
      }
      const data = await messagesApi("/api/messages/read-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (data?.ok) {
        syncUnreadFromResponse(data);
        await loadList();
      } else {
        showErrorList(data?.error || "error_load");
      }
    };

    state.loadList = loadList;
    state.openMessage = openMessage;
    state.handleAction = handleAction;
    state.setDetailVisible = setDetailVisible;

    GC.messagesPageState = state;

    queueMicrotask(() => {
      if (GC.messagesPageState === state && isCurrentInit(state, initSeq)) {
        loadList(true, { force: true });
      }
    });
  }

  GC.modules = GC.modules || {};
  GC.modules.messages = initMessagesPage;
  GC.initMessagesPage = initMessagesPage;
  GC.openMessagesCompose = openCompose;
  GC.ensureMessagesState = ensureMessagesState;
  GC.openCombatReportModal = openCombatReportModal;
  GC.closeCombatReportModal = closeCombatReportModal;

  bindMessagesUiOnce();
})();
