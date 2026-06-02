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

  function coordLink(raw, label) {
    if (typeof GC.coordLinkHtml === "function") {
      return GC.coordLinkHtml(raw, { label: label != null ? label : raw });
    }
    const text = label != null ? label : raw;
    return esc(text || "—");
  }

  function coordRoute(fromRaw, toRaw) {
    if (typeof GC.coordRouteHtml === "function") {
      return GC.coordRouteHtml(fromRaw, toRaw);
    }
    const from = String(fromRaw || "").trim();
    const to = String(toRaw || "").trim();
    if (from && to) return `${esc(from)} → ${esc(to)}`;
    return esc(from || to || "—");
  }

  function coordLabelLink(templateKey, fallback, coords) {
    const tpl = t(templateKey, fallback);
    if (!tpl.includes("%(coords)s")) return esc(tpl);
    const parts = tpl.split("%(coords)s");
    if (parts.length !== 2) return esc(tpl);
    const c = String(coords || "—");
    return esc(parts[0]) + coordLink(c, c) + esc(parts[1]);
  }

  function linkifyCoordsText(text) {
    if (typeof GC.linkifyCoordsInText === "function") {
      return GC.linkifyCoordsInText(text);
    }
    return esc(text || "");
  }

  function renderPlainMessageHtml(text) {
    const raw = String(text || "").trim();
    if (!raw) return `<p class="gc-messages-plain-line">${esc("—")}</p>`;
    return raw
      .split(/\n/)
      .map((line) => `<p class="gc-messages-plain-line">${linkifyCoordsText(line)}</p>`)
      .join("");
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

  const REPORT_MODAL = {
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

  function isSpyReportMsg(msg) {
    const meta = msg?.metadata || {};
    return msg?.category === "espionage" && Number(meta.report_version) >= 2 && Boolean(meta.intel_tiers);
  }

  function isExpeditionReportMsg(msg) {
    const meta = msg?.metadata || {};
    return msg?.category === "expedition" && Number(meta.report_version) >= 2 && Boolean(meta.event_key);
  }

  function getInboxReportKind(msg) {
    if (isCombatReportMsg(msg)) return "combat";
    if (isSpyReportMsg(msg)) return "spy";
    if (isExpeditionReportMsg(msg)) return "expedition";
    return null;
  }

  function inboxReportOpenAttrs(messageId, kind) {
    if (messageId == null || !Number.isFinite(Number(messageId)) || !kind) return "";
    return ` data-open-inbox-report="${Number(messageId)}" data-report-kind="${esc(kind)}"`;
  }

  function devCombatSimEnabled() {
    const page = document.getElementById("messages-page");
    return page?.dataset?.devCombat === "1";
  }

  function parseTargetCoordsForFleet(coords) {
    const m = String(coords || "").match(/\[?(\d+):(\d+):(\d+)\]?/);
    if (!m) return null;
    return { galaxy: m[1], system: m[2], position: m[3] };
  }

  function fleetAttackHrefFromCoords(coords) {
    const c = parseTargetCoordsForFleet(coords);
    if (!c) return null;
    return `/fleet?mission=attack&target_galaxy=${c.galaxy}&target_system=${c.system}&target_position=${c.position}`;
  }

  function navigateFleetAttack(coords) {
    const href = fleetAttackHrefFromCoords(coords);
    if (!href) return;
    if (typeof GC.navigateTo === "function") {
      GC.navigateTo(href);
      return;
    }
    window.location.href = href;
  }

  function renderSpyReportActionBar(meta, messageId) {
    const coords = meta?.target_coords;
    const attackHref = fleetAttackHrefFromCoords(coords);
    const parts = [];
    if (attackHref) {
      parts.push(
        `<a href="${esc(attackHref)}" class="gc-btn gc-btn-danger gc-btn-sm" data-spy-action="attack">${esc(
          t("spy_report_attack_btn", "Attack target")
        )}</a>`
      );
    }
    if (devCombatSimEnabled() && messageId != null && Number.isFinite(Number(messageId))) {
      parts.push(
        `<button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-spy-action="dev_sim" data-message-id="${Number(
          messageId
        )}">${esc(t("spy_report_dev_sim_btn", "DEV: Combat simulator"))}</button>`
      );
    }
    if (!parts.length) return "";
    return `<div class="gc-spy-report-actions">${parts.join("")}</div>`;
  }

  function combatViewerOutcome(meta) {
    const winner = String(meta?.result || meta?.winner || "undecided");
    const perspective = String(meta?.perspective || "attacker");
    if (winner === "draw") return "draw";
    if (winner === "undecided") return "open";
    if (winner === perspective) return "victory";
    return "defeat";
  }

  function combatResultVisual(meta) {
    const outcome = combatViewerOutcome(meta && typeof meta === "object" ? meta : {});
    if (outcome === "victory") {
      return { theme: "emerald", icon: "⚔", badge: "victory" };
    }
    if (outcome === "defeat") {
      return { theme: "rose", icon: "🛡", badge: "defeat" };
    }
    if (outcome === "draw") {
      return { theme: "amber", icon: "◇", badge: "draw" };
    }
    return { theme: "cyan", icon: "◈", badge: "open" };
  }

  function combatResultLabel(meta) {
    const winner = String(meta?.result || meta?.winner || "undecided");
    const perspective = String(meta?.perspective || "attacker");
    const objective = t(`combat_report_winner_${winner}`, winner);
    if (winner === "draw" || winner === "undecided") return objective;
    if (winner === perspective) {
      return t("combat_report_outcome_you_won", "Victory");
    }
    return t("combat_report_outcome_you_lost", "Defeat");
  }

  function combatResultSubtitle(meta) {
    const winner = String(meta?.result || meta?.winner || "undecided");
    if (winner === "draw" || winner === "undecided") return "";
    return t(`combat_report_winner_${winner}`, winner);
  }

  function combatCoordsPlain(meta) {
    const from = String(meta?.origin_coords || "").trim();
    const to = String(meta?.target_coords || "").trim();
    if (from && to) return `${from} → ${to}`;
    return to || from || "—";
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

  function renderCombatLossColumn(sideLabel, stock, defenseStock, roleKey) {
    const total = unitCountTotal(stock);
    return (
      `<div class="gc-combat-loss-col gc-combat-loss-col--${esc(roleKey)}">` +
        `<div class="gc-combat-loss-col-head">` +
          `<span class="gc-combat-loss-col-role">${esc(sideLabel)}</span>` +
          `<span class="gc-combat-loss-col-total gc-mono">${esc(formatInt(total))}</span>` +
        `</div>` +
        `<div class="gc-combat-loss-col-body">${renderCombatUnitGrid(stock, defenseStock)}</div>` +
      `</div>`
    );
  }

  function renderCombatLossesSplit(meta, defenseStock) {
    return (
      `<div class="gc-combat-losses-split">` +
        renderCombatLossColumn(
          t("combat_report_section_attacker", "Attacker"),
          meta.attacker_losses,
          null,
          "attacker"
        ) +
        renderCombatLossColumn(
          t("combat_report_section_defender", "Defender"),
          meta.defender_losses,
          defenseStock,
          "defender"
        ) +
      `</div>`
    );
  }

  function renderCombatRoundBody(rnd, defenseStock) {
    return (
      `<div class="gc-combat-round-split">` +
        `<div class="gc-combat-round-half gc-combat-round-half--attacker">` +
          `<span class="gc-combat-round-half-label">${esc(
            t("combat_report_round_atk_losses", "Attacker losses this round")
          )}</span>` +
          renderCombatUnitGrid(rnd.attacker_losses, null) +
        `</div>` +
        `<div class="gc-combat-round-half gc-combat-round-half--defender">` +
          `<span class="gc-combat-round-half-label">${esc(
            t("combat_report_round_def_losses", "Defender losses this round")
          )}</span>` +
          renderCombatUnitGrid(rnd.defender_losses, defenseStock) +
        `</div>` +
      `</div>`
    );
  }

  function renderCombatDefenderForces(meta, defenseStock) {
    const fleetTotal = unitCountTotal(meta.defending_ships);
    const defTotal = unitCountTotal(defenseStock);
    return (
      `<div class="gc-combat-defender-forces">` +
        `<div class="gc-combat-force-block">` +
          `<div class="gc-combat-force-head">` +
            `<span class="gc-combat-force-label">${esc(t("combat_report_defender_fleet", "Fleet"))}</span>` +
            `<span class="gc-combat-force-count gc-mono">${esc(formatInt(fleetTotal))}</span>` +
          `</div>` +
          renderCombatUnitGrid(meta.defending_ships, null) +
        `</div>` +
        `<div class="gc-combat-force-block">` +
          `<div class="gc-combat-force-head">` +
            `<span class="gc-combat-force-label">${esc(t("combat_report_defender_structures", "Defense"))}</span>` +
            `<span class="gc-combat-force-count gc-mono">${esc(formatInt(defTotal))}</span>` +
          `</div>` +
          renderCombatUnitGrid(defenseStock, defenseStock) +
        `</div>` +
      `</div>`
    );
  }

  function combatCoordsRoute(meta) {
    const from = String(meta?.origin_coords || "").trim();
    const to = String(meta?.target_coords || "").trim();
    if (from && to) return coordRoute(from, to);
    return coordLink(to || from, to || from);
  }

  function renderCombatBattleOverview(meta) {
    const targetCoords = meta.target_coords || "—";
    const originCoords = meta.origin_coords || "—";
    const targetPlanet = String(meta.target_planet_name || "").trim();
    const originPlanet = String(meta.origin_planet_name || "").trim();
    const atkShips = unitCountTotal(meta.attacking_ships);
    const defFleet = unitCountTotal(meta.defending_ships);
    const defStruct = unitCountTotal(meta.defending_defense || {});
    const defUnitsLine = t("combat_report_side_defense", "%(fleet)s fleet · %(def)s defense")
      .replace("%(fleet)s", formatInt(defFleet))
      .replace("%(def)s", formatInt(defStruct));
    const originPlanetLine = originPlanet
      ? `<span class="gc-combat-report-side-planet">${esc(originPlanet)}</span>`
      : "";
    const targetPlanetLine = targetPlanet
      ? `<span class="gc-combat-report-side-planet">${esc(targetPlanet)}</span>`
      : "";

    return (
      `<section class="gc-combat-report-overview">` +
        `<h4 class="gc-combat-report-panel-title">${esc(t("combat_report_battlefield", "Battlefield"))}</h4>` +
        `<div class="gc-combat-report-battlefield gc-mono">${combatCoordsRoute(meta)}</div>` +
        `<div class="gc-combat-report-sides">` +
          `<div class="gc-combat-report-side gc-combat-report-side--attacker">` +
            `<span class="gc-combat-report-side-role">${esc(t("combat_report_section_attacker", "Attacker"))}</span>` +
            `<strong class="gc-combat-report-side-name">${esc(meta.attacker_name || "—")}</strong>` +
            originPlanetLine +
            `<span class="gc-combat-report-side-coords gc-mono">${coordLabelLink(
              "combat_report_origin_coords",
              "Launched from: %(coords)s",
              originCoords
            )}</span>` +
            `<span class="gc-combat-report-side-units">${esc(
              t("combat_report_side_ships", "%(count)s ships").replace("%(count)s", formatInt(atkShips))
            )}</span>` +
          `</div>` +
          `<div class="gc-combat-report-side gc-combat-report-side--defender">` +
            `<span class="gc-combat-report-side-role">${esc(t("combat_report_section_defender", "Defender"))}</span>` +
            `<strong class="gc-combat-report-side-name">${esc(meta.defender_name || "—")}</strong>` +
            targetPlanetLine +
            `<span class="gc-combat-report-side-coords gc-mono">${coordLabelLink(
              "combat_report_target_coords",
              "Target planet: %(coords)s",
              targetCoords
            )}</span>` +
            `<span class="gc-combat-report-side-units">${esc(defUnitsLine)}</span>` +
          `</div>` +
        `</div>` +
      `</section>`
    );
  }

  function renderCombatReportTeaser(meta, opts = {}) {
    const compact = Boolean(opts.compact);
    const messageId = opts.messageId;
    const resultKey = meta.result || meta.winner || "undecided";
    const visual = combatResultVisual(meta);
    const resultLabel = combatResultLabel(meta);
    const resultSub = combatResultSubtitle(meta);
    const rounds = formatInt(meta.rounds_fought || (meta.rounds || []).length || 0);
    const loot = meta.loot || {};
    const lootTotal = expeditionLootTotal(loot);
    const vsLine = t("combat_report_vs", "%(attacker)s vs %(defender)s")
      .replace("%(attacker)s", meta.attacker_name || "—")
      .replace("%(defender)s", meta.defender_name || "—");
    const lootHint =
      lootTotal > 0
        ? `${formatInt(loot.metal || 0)} / ${formatInt(loot.crystal || 0)} / ${formatInt(loot.fuel_cells || 0)}`
        : t("combat_report_loot_none", "No plunder");
    const coordsLine = compact
      ? coordLink(meta.target_coords, meta.target_coords || "—")
      : combatCoordsRoute(meta);

    return (
      `<div class="gc-combat-teaser gc-combat-teaser--${esc(visual.badge)}${compact ? " gc-combat-teaser--compact" : ""}" data-result="${esc(resultKey)}">` +
        `<div class="gc-combat-teaser-top">` +
          `<span class="gc-combat-teaser-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-combat-teaser-headings">` +
            `<span class="gc-combat-teaser-coords gc-mono">${coordsLine}</span>` +
            `<span class="gc-combat-teaser-vs">${esc(compact ? resultLabel : vsLine)}</span>` +
          `</div>` +
          `<span class="gc-combat-teaser-badge">${esc(resultLabel)}` +
          (resultSub && !compact ? `<span class="gc-combat-teaser-badge-sub">${esc(resultSub)}</span>` : "") +
          `</span>` +
        `</div>` +
        (!compact
          ? `<p class="gc-combat-teaser-meta gc-mono">${esc(
              t("combat_report_rounds_total", "%(count)s rounds").replace("%(count)s", rounds)
            )} · ${esc(lootHint)}</p>`
          : "") +
        (!compact ? `<p class="gc-combat-teaser-hint">${esc(t("combat_report_teaser_hint", ""))}</p>` : "") +
        (!compact
          ? `<span class="gc-btn gc-btn-primary gc-btn-sm gc-combat-teaser-open" role="button" tabindex="0"${inboxReportOpenAttrs(messageId, "combat")}>${esc(
              t("combat_report_open_btn", "Open report")
            )}</span>`
          : "") +
      `</div>`
    );
  }

  function renderCombatReportFull(meta) {
    const resultKey = meta.result || meta.winner || "undecided";
    const visual = combatResultVisual(meta);
    const resultLabel = combatResultLabel(meta);
    const resultSub = combatResultSubtitle(meta);
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
            `<div class="gc-combat-report-coords gc-mono">${combatCoordsRoute(meta)}</div>` +
            `<div class="gc-combat-report-vs">${esc(
              t("combat_report_vs", "%(attacker)s vs %(defender)s")
                .replace("%(attacker)s", meta.attacker_name || "—")
                .replace("%(defender)s", meta.defender_name || "—")
            )}</div>` +
          `</div>` +
          `<span class="gc-combat-report-result-badge">` +
            `<span class="gc-combat-report-result-main">${esc(resultLabel)}</span>` +
            (resultSub
              ? `<span class="gc-combat-report-result-sub">${esc(resultSub)}</span>`
              : "") +
          `</span>` +
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

    sections.push(renderCombatBattleOverview(meta));

    sections.push(
      renderCombatPanel(
        t("combat_report_section_forces", "Forces"),
        `<div class="gc-combat-report-columns gc-combat-report-columns--forces">` +
          `<div class="gc-combat-report-panel gc-combat-report-panel--attacker gc-combat-report-panel--inline">` +
            `<h4 class="gc-combat-report-panel-title">${esc(t("combat_report_section_attacker", "Attacker"))}</h4>` +
            `<div class="gc-combat-report-panel-body">` +
              `<div class="gc-combat-force-head gc-combat-force-head--solo">` +
                `<span class="gc-combat-force-count gc-mono">${esc(formatInt(unitCountTotal(meta.attacking_ships)))}</span>` +
              `</div>` +
              renderCombatUnitGrid(meta.attacking_ships, null) +
            `</div>` +
          `</div>` +
          `<div class="gc-combat-report-panel gc-combat-report-panel--defender gc-combat-report-panel--inline">` +
            `<h4 class="gc-combat-report-panel-title">${esc(t("combat_report_section_defender", "Defender"))}</h4>` +
            `<div class="gc-combat-report-panel-body">${renderCombatDefenderForces(meta, defenseStock)}</div>` +
          `</div>` +
        `</div>`,
        "gc-combat-report-panel--forces-wrap"
      )
    );

    sections.push(
      renderCombatPanel(
        t("combat_report_section_losses", "Total losses"),
        renderCombatLossesSplit(meta, defenseStock),
        "gc-combat-report-panel--losses"
      )
    );

    const roundList = Array.isArray(meta.rounds) ? meta.rounds : [];
    if (roundList.length) {
      const roundHtml = roundList
        .map((rnd) => {
          const n = rnd.number || 0;
          const atkRnd = unitCountTotal(rnd.attacker_losses);
          const defRnd = unitCountTotal(rnd.defender_losses);
          return (
            `<details class="gc-combat-round" ${n === 1 ? "open" : ""}>` +
            `<summary class="gc-combat-round-title">` +
              `<span class="gc-combat-round-title-main">${esc(
                t("combat_report_section_round", "Round %(n)s").replace("%(n)s", formatInt(n))
              )}</span>` +
              `<span class="gc-combat-round-title-stats gc-mono">` +
                `<span class="gc-combat-round-stat gc-combat-round-stat--atk">${esc(formatInt(atkRnd))}</span>` +
                `<span class="gc-combat-round-stat-sep" aria-hidden="true">/</span>` +
                `<span class="gc-combat-round-stat gc-combat-round-stat--def">${esc(formatInt(defRnd))}</span>` +
              `</span>` +
            `</summary>` +
            `<div class="gc-combat-round-body">${renderCombatRoundBody(rnd, defenseStock)}</div>` +
            `</details>`
          );
        })
        .join("");
      sections.push(
        renderCombatPanel(t("combat_report_section_rounds", "Round log"), roundHtml, "gc-combat-report-panel--rounds")
      );
    }

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

  function cacheReportModalElements() {
    if (REPORT_MODAL.root && REPORT_MODAL.content) return REPORT_MODAL.root;
    REPORT_MODAL.root = document.getElementById("gc-combat-report-root");
    if (!REPORT_MODAL.root) return null;
    REPORT_MODAL.dialog = REPORT_MODAL.root.querySelector(".gc-combat-report-dialog");
    REPORT_MODAL.titleEl = document.getElementById("gc-combat-report-title");
    REPORT_MODAL.content = REPORT_MODAL.root.querySelector("[data-cr-content]");
    return REPORT_MODAL.root;
  }

  function renderInboxReportFull(msg, opts = {}) {
    const meta = msg?.metadata || {};
    const kind = getInboxReportKind(msg);
    const reportOpts = { ...opts, messageId: opts.messageId ?? msg?.id };
    if (kind === "combat") return renderCombatReportFull(meta);
    if (kind === "spy") return renderSpyReportFull(meta, reportOpts);
    if (kind === "expedition") return renderExpeditionReportFull(meta);
    return "";
  }

  function reportModalTitle(msg) {
    const meta = msg?.metadata || {};
    const kind = getInboxReportKind(msg);
    const coords = meta.target_coords || "—";
    if (kind === "combat") {
      const prefix = meta.dev_simulated
        ? t("combat_report_dev_sim_title", "DEV combat simulation")
        : t("combat_report_modal_title", "Combat report");
      return `${prefix} — ${combatCoordsPlain(meta)}`;
    }
    if (kind === "spy") {
      return `${t("spy_report_modal_title", "Spy report")} — ${coords}`;
    }
    if (kind === "expedition") {
      const eventLabel = t(meta.event_label_key || `expedition_event_${meta.event_key}`, meta.event_key || "");
      return `${t("expedition_report_modal_title", "Expedition report")} — ${eventLabel}`;
    }
    return t("messages.detail", "Message");
  }

  function reportModalTheme(msg) {
    const meta = msg?.metadata || {};
    const kind = getInboxReportKind(msg);
    if (kind === "combat") return combatResultVisual(meta).theme;
    if (kind === "spy") return "cyan";
    if (kind === "expedition") return expeditionEventVisual(meta.event_key || "void_scan").theme;
    return "cyan";
  }

  function openInboxReportModal(msg) {
    if (!msg || !getInboxReportKind(msg)) return;
    const root = cacheReportModalElements();
    if (!root || !REPORT_MODAL.content) return;
    if (REPORT_MODAL.dialog) {
      REPORT_MODAL.dialog.setAttribute("data-theme", reportModalTheme(msg));
    }
    if (REPORT_MODAL.titleEl) {
      REPORT_MODAL.titleEl.textContent = reportModalTitle(msg);
    }
    REPORT_MODAL.content.innerHTML = renderInboxReportFull(msg, { messageId: msg.id });
    root.hidden = false;
    root.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-combat-report-open");
    REPORT_MODAL.open = true;
    const closeBtn = root.querySelector("[data-cr-close].gc-player-card-close");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
  }

  function closeInboxReportModal() {
    const root = cacheReportModalElements();
    if (!root) return;
    if (REPORT_MODAL.content) REPORT_MODAL.content.innerHTML = "";
    root.hidden = true;
    root.setAttribute("aria-hidden", "true");
    document.body.classList.remove("gc-combat-report-open");
    REPORT_MODAL.open = false;
  }

  const closeCombatReportModal = closeInboxReportModal;

  function openCombatReportModal(msg) {
    openInboxReportModal(msg);
  }

  function resolveInboxReportMessage(messageId, kind) {
    const id = Number(messageId);
    if (!Number.isFinite(id)) return null;
    const state = GC.messagesPageState;
    const cached = state?.messages?.find((m) => m.id === id);
    if (cached && getInboxReportKind(cached) === kind) return cached;
    return null;
  }

  async function openInboxReportById(messageId, kind) {
    let msg = resolveInboxReportMessage(messageId, kind);
    if (!msg) {
      const data = await messagesApi(`/api/messages/${messageId}`);
      const loaded = data?.ok ? data.data?.message : null;
      if (loaded && getInboxReportKind(loaded) === kind) msg = loaded;
    }
    if (msg) openInboxReportModal(msg);
  }

  async function openCombatReportById(messageId) {
    return openInboxReportById(messageId, "combat");
  }

  function buildingLabel(key) {
    return t(`building_${key}`, key);
  }

  function missionLabel(mission) {
    return t(`fleet_mission_${mission}`, mission);
  }

  function renderIntelPanel(title, bodyHtml, locked, lockedText, extraClass = "") {
    if (locked) {
      return renderCombatPanel(
        title,
        `<p class="gc-combat-report-empty">${esc(lockedText)}</p>`,
        `gc-combat-report-panel--locked ${extraClass}`.trim()
      );
    }
    return renderCombatPanel(title, bodyHtml, extraClass);
  }

  function renderBuildingGrid(buildings) {
    const entries = Object.entries(buildings || {}).filter(([, lvl]) => Number(lvl) > 0);
    if (!entries.length) {
      return `<p class="gc-combat-report-empty">${esc(t("fleet_spy_report_buildings_empty", "No buildings"))}</p>`;
    }
    return (
      `<div class="gc-combat-unit-grid">` +
      entries
        .sort(([a], [b]) => a.localeCompare(b))
        .map(
          ([key, lvl]) =>
            `<div class="gc-combat-unit-chip gc-combat-unit-chip--building">` +
            `<span class="gc-combat-unit-chip-name">${esc(buildingLabel(key))}</span>` +
            `<strong class="gc-combat-unit-chip-qty">L${esc(formatInt(lvl))}</strong>` +
            `</div>`
        )
        .join("") +
      `</div>`
    );
  }

  function renderSpyResourceChips(res, tiers) {
    const rows = [];
    if (tiers.resources) {
      if (Number(res.metal || 0) > 0) rows.push(["metal", res.metal]);
      if (Number(res.crystal || 0) > 0) rows.push(["crystal", res.crystal]);
    }
    if (tiers.fuel && Number(res.fuel_cells || 0) > 0) rows.push(["fuel_cells", res.fuel_cells]);
    if (!rows.length) {
      return `<p class="gc-combat-report-empty">${esc(t("fleet_spy_report_fleet_empty", "—"))}</p>`;
    }
    const loot = {};
    rows.forEach(([k, v]) => {
      loot[k] = v;
    });
    return renderCombatLootChips(loot);
  }

  function renderSpyReportTeaser(meta, opts = {}) {
    const compact = Boolean(opts.compact);
    const messageId = opts.messageId;
    const tiers = meta.intel_tiers || {};
    const unlocked = Object.values(tiers).filter(Boolean).length;
    const owner = meta.target_owner || "—";
    const planet = meta.target_planet || t("fleet_spy_report_unknown_planet", "Unknown");

    return (
      `<div class="gc-combat-teaser gc-combat-teaser--open gc-combat-teaser--intel${compact ? " gc-combat-teaser--compact" : ""}">` +
        `<div class="gc-combat-teaser-top">` +
          `<span class="gc-combat-teaser-icon" aria-hidden="true">🔍</span>` +
          `<div class="gc-combat-teaser-headings">` +
            `<span class="gc-combat-teaser-coords gc-mono">${coordLink(meta.target_coords, meta.target_coords || "—")}</span>` +
            `<span class="gc-combat-teaser-vs">${esc(`${owner} · ${planet}`)}</span>` +
          `</div>` +
          `<span class="gc-combat-teaser-badge">${esc(t("spy_report_badge", "Spy report"))}</span>` +
        `</div>` +
        `<p class="gc-combat-teaser-meta gc-mono">${esc(
          t("spy_report_teaser_meta", "%(probes)s probes · %(sections)s intel sections")
            .replace("%(probes)s", formatInt(meta.probe_count || 0))
            .replace("%(sections)s", formatInt(unlocked))
        )}</p>` +
        (!compact ? `<p class="gc-combat-teaser-hint">${esc(t("spy_report_teaser_hint", ""))}</p>` : "") +
        (!compact
          ? `<span class="gc-btn gc-btn-primary gc-btn-sm gc-combat-teaser-open" role="button" tabindex="0"${inboxReportOpenAttrs(messageId, "spy")}>${esc(
              t("spy_report_open_btn", "Open report")
            )}</span>`
          : "") +
      `</div>`
    );
  }

  function renderSpyTargetOverview(meta) {
    const coords = meta.target_coords || "—";
    const owner = meta.target_owner || "—";
    const planet = meta.target_planet || t("fleet_spy_report_unknown_planet", "Unknown");
    return (
      `<section class="gc-combat-report-overview gc-combat-report-overview--intel">` +
        `<h4 class="gc-combat-report-panel-title">${esc(t("spy_report_target", "Target"))}</h4>` +
        `<div class="gc-combat-report-battlefield gc-mono">${coordLink(coords, coords)}</div>` +
        `<div class="gc-combat-report-sides">` +
          `<div class="gc-combat-report-side gc-combat-report-side--defender">` +
            `<span class="gc-combat-report-side-role">${esc(t("spy_report_target_owner", "Commander"))}</span>` +
            `<strong class="gc-combat-report-side-name">${esc(owner)}</strong>` +
            `<span class="gc-combat-report-side-planet">${esc(planet)}</span>` +
            `<span class="gc-combat-report-side-coords gc-mono">${coordLabelLink(
              "combat_report_target_coords",
              "Target: %(coords)s",
              coords
            )}</span>` +
            `<span class="gc-combat-report-side-units">${esc(
              t("spy_report_probe_line", "%(count)s probes deployed").replace(
                "%(count)s",
                formatInt(meta.probe_count || 0)
              )
            )}</span>` +
          `</div>` +
          `<div class="gc-combat-report-side gc-combat-report-side--attacker">` +
            `<span class="gc-combat-report-side-role">${esc(t("spy_report_intel_quality", "Intel quality"))}</span>` +
            `<strong class="gc-combat-report-side-name">${esc(formatInt(meta.spy_accuracy_pct || 0))}%</strong>` +
            `<span class="gc-combat-report-side-units">${esc(
              t("spy_report_sections_unlocked", "%(count)s data sections")
                .replace("%(count)s", formatInt(Object.values(meta.intel_tiers || {}).filter(Boolean).length))
            )}</span>` +
          `</div>` +
        `</div>` +
      `</section>`
    );
  }

  function renderSpyReportFull(meta, opts = {}) {
    const tiers = meta.intel_tiers || {};
    const res = meta.resources || {};
    const ships = meta.ships || {};
    const defense = meta.defense || {};
    const buildings = meta.buildings || {};
    const activity = Array.isArray(meta.activity) ? meta.activity : [];
    const fleetTotal = unitCountTotal(ships);
    const defUnits = Number(defense.total_units || 0);
    const buildCount = Object.values(buildings).filter((lvl) => Number(lvl) > 0).length;
    const resTotal =
      (tiers.resources ? Number(res.metal || 0) + Number(res.crystal || 0) : 0) +
      (tiers.fuel ? Number(res.fuel_cells || 0) : 0);

    const sections = [];

    sections.push(
      `<header class="gc-combat-report-hero gc-combat-report-hero--open gc-combat-report-hero--intel">` +
        `<div class="gc-combat-report-hero-top">` +
          `<span class="gc-combat-report-hero-icon" aria-hidden="true">🔍</span>` +
          `<div class="gc-combat-report-hero-text">` +
            `<div class="gc-combat-report-coords gc-mono">${coordLink(meta.target_coords, meta.target_coords || "—")}</div>` +
            `<div class="gc-combat-report-vs">${esc(meta.target_owner || "—")} · ${esc(meta.target_planet || "—")}</div>` +
          `</div>` +
          `<span class="gc-combat-report-result-badge">` +
            `<span class="gc-combat-report-result-main">${esc(t("spy_report_badge", "Spy report"))}</span>` +
            `<span class="gc-combat-report-result-sub">${esc(
              t("spy_report_accuracy_sub", "~%(pct)s%% accuracy").replace(
                "%(pct)s",
                formatInt(meta.spy_accuracy_pct || 0)
              )
            )}</span>` +
          `</span>` +
        `</div>` +
      `</header>`
    );

    sections.push(
      `<div class="gc-player-card-stats gc-combat-report-stats">` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("spy_report_stat_probes", "Probes"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(meta.probe_count || 0))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("spy_report_stat_fleet", "Fleet"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(fleetTotal))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("spy_report_stat_defense", "Defense"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(defUnits))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("spy_report_stat_resources", "Resources"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(resTotal))}</span>` +
        `</div>` +
      `</div>`
    );

    sections.push(renderSpyTargetOverview(meta));

    let fleetHtml = "";
    if (tiers.fleet) {
      fleetHtml = renderCombatUnitGrid(ships, null);
    }
    sections.push(
      renderIntelPanel(
        t("fleet_spy_report_section_fleet", "Orbital fleet"),
        fleetHtml,
        !tiers.fleet,
        t("fleet_spy_report_fleet_locked", "Locked"),
        "gc-combat-report-panel--defender"
      )
    );

    let defenseHtml = "";
    if (tiers.defense) {
      defenseHtml =
        `<div class="gc-spy-report-stats-row gc-mono">` +
          `<span>${esc(t("fleet_spy_report_defense_power", "Defense power"))}: <strong>${esc(formatInt(defense.defense_power || 0))}</strong></span>` +
          `<span>${esc(t("fleet_spy_report_shield_power", "Shield power"))}: <strong>${esc(formatInt(defense.shield_power || 0))}</strong></span>` +
        `</div>` +
        renderCombatUnitGrid(defense.units || {}, defense.units || {});
      if (defense.accuracy_pct != null && !defense.exact) {
        defenseHtml += `<p class="gc-combat-report-empty">${esc(
          t("fleet_spy_report_defense_accuracy", "Intel accuracy: ~%(pct)s%%").replace(
            "%(pct)s",
            formatInt(defense.accuracy_pct || 0)
          )
        )}</p>`;
      }
    }
    sections.push(
      renderIntelPanel(
        t("fleet_spy_report_section_defense", "Planetary defense"),
        defenseHtml,
        !tiers.defense,
        t("fleet_spy_report_defense_locked", "Locked"),
        "gc-combat-report-panel--defender"
      )
    );

    let resHtml = "";
    if (tiers.resources || tiers.fuel) {
      resHtml = renderSpyResourceChips(res, tiers);
    }
    sections.push(
      renderIntelPanel(
        t("fleet_spy_report_section_resources", "Resources"),
        resHtml,
        !tiers.resources && !tiers.fuel,
        t("fleet_spy_report_resources_locked", "Locked"),
        "gc-combat-report-panel--loot"
      )
    );

    let buildHtml = "";
    if (tiers.buildings) {
      buildHtml = renderBuildingGrid(buildings);
      if (meta.energy) {
        buildHtml += `<p class="gc-combat-report-empty">${esc(
          t("fleet_spy_report_energy", "Energy: %(balance)s (%(total)s / %(used)s)")
            .replace("%(balance)s", formatInt(meta.energy.balance || 0))
            .replace("%(total)s", formatInt(meta.energy.total || 0))
            .replace("%(used)s", formatInt(meta.energy.used || 0))
        )}</p>`;
      }
    }
    sections.push(
      renderIntelPanel(
        t("fleet_spy_report_section_buildings", "Surface installations"),
        buildHtml || `<p class="gc-combat-report-empty">${esc(t("fleet_spy_report_buildings_empty", "—"))}</p>`,
        !tiers.buildings,
        t("fleet_spy_report_buildings_locked", "Locked")
      )
    );

    let activityHtml = "";
    if (tiers.activity) {
      activityHtml = activity.length
        ? activity
            .map(
              (row) =>
                `<div class="gc-spy-report-activity-row gc-combat-report-activity-row">${esc(
                  t("fleet_spy_report_activity_row", "%(mission)s → %(coords)s (%(status)s)")
                    .replace("%(mission)s", missionLabel(row.mission || ""))
                    .replace("%(coords)s", "%%COORD%%")
                    .replace("%(status)s", row.status || "")
                ).replace("%%COORD%%", coordLink(row.coords, row.coords || "—"))}</div>`
            )
            .join("")
        : `<p class="gc-combat-report-empty">${esc(t("fleet_spy_report_activity_empty", "No activity"))}</p>`;
    }
    sections.push(
      renderIntelPanel(
        t("fleet_spy_report_section_activity", "Fleet activity"),
        activityHtml,
        !tiers.activity,
        t("fleet_spy_report_activity_locked", "Locked"),
        "gc-combat-report-panel--rounds"
      )
    );

    const actions = renderSpyReportActionBar(meta, opts.messageId);
    return (
      `<div class="gc-player-card-shell gc-combat-report-shell gc-combat-report-shell--intel" data-theme="cyan">` +
      sections.join("") +
      actions +
      `</div>`
    );
  }

  async function runDevCombatSimFromSpy(messageId) {
    const id = Number(messageId);
    if (!Number.isFinite(id)) return;
    const btn = document.querySelector(`[data-spy-action="dev_sim"][data-message-id="${id}"]`);
    if (btn) {
      btn.disabled = true;
      btn.textContent = t("spy_report_dev_sim_running", "Simulating…");
    }
    try {
      const res = await GC.fetchGameAction("/api/dev/combat/simulate-spy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: id }),
      });
      const meta = res?.data?.metadata;
      if (!res?.ok || !meta) {
        if (typeof GC.showNotify === "function") {
          GC.showNotify(t("spy_report_dev_sim_error", "Simulation failed."), "error");
        }
        return;
      }
      const simMsg = {
        id,
        category: "combat",
        subject: t("combat_report_dev_sim_title", "DEV combat simulation"),
        metadata: meta,
      };
      openInboxReportModal(simMsg);
    } catch (_) {
      if (typeof GC.showNotify === "function") {
        GC.showNotify(t("spy_report_dev_sim_error", "Simulation failed."), "error");
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = t("spy_report_dev_sim_btn", "DEV: Combat simulator");
      }
    }
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

  function expeditionHeroBadge(eventKey) {
    const visual = expeditionEventVisual(eventKey);
    const badgeByTheme = {
      fund: "victory",
      anomaly: "open",
      disturbance: "draw",
      alert: "defeat",
      relic: "victory",
    };
    return { ...visual, badge: badgeByTheme[visual.theme] || "open" };
  }

  function renderExpeditionReportTeaser(meta, opts = {}) {
    const compact = Boolean(opts.compact);
    const messageId = opts.messageId;
    const eventKey = meta.event_key || "void_scan";
    const eventLabel = t(meta.event_label_key || `expedition_event_${eventKey}`, eventKey);
    const visual = expeditionHeroBadge(eventKey);
    const rewards = meta.rewards || {};
    const lootTotal = expeditionLootTotal(rewards);
    const lootHint =
      lootTotal > 0
        ? `${formatInt(rewards.metal || 0)} / ${formatInt(rewards.crystal || 0)} / ${formatInt(rewards.fuel_cells || 0)}`
        : t("combat_report_loot_none", "No plunder");

    return (
      `<div class="gc-combat-teaser gc-combat-teaser--${esc(visual.badge)} gc-combat-teaser--expedition${compact ? " gc-combat-teaser--compact" : ""}" data-event="${esc(eventKey)}">` +
        `<div class="gc-combat-teaser-top">` +
          `<span class="gc-combat-teaser-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-combat-teaser-headings">` +
            `<span class="gc-combat-teaser-coords gc-mono">${coordLink(meta.target_coords, meta.target_coords || "—")}</span>` +
            `<span class="gc-combat-teaser-vs">${esc(eventLabel)}</span>` +
          `</div>` +
          `<span class="gc-combat-teaser-badge">${esc(expeditionEventBadge(eventKey, meta.event_severity))}</span>` +
        `</div>` +
        (!compact ? `<p class="gc-combat-teaser-meta gc-mono">${esc(lootHint)}</p>` : "") +
        (!compact ? `<p class="gc-combat-teaser-hint">${esc(t("expedition_report_teaser_hint", ""))}</p>` : "") +
        (!compact
          ? `<span class="gc-btn gc-btn-primary gc-btn-sm gc-combat-teaser-open" role="button" tabindex="0"${inboxReportOpenAttrs(messageId, "expedition")}>${esc(
              t("expedition_report_open_btn", "Open report")
            )}</span>`
          : "") +
      `</div>`
    );
  }

  function renderExpeditionReportFull(meta) {
    const eventKey = meta.event_key || "void_scan";
    const eventLabel = t(meta.event_label_key || `expedition_event_${eventKey}`, eventKey);
    const descKey = meta.event_desc_key || `expedition_event_${eventKey}_desc`;
    const desc = t(descKey, "");
    const severity = meta.event_severity || "normal";
    const visual = expeditionHeroBadge(eventKey);
    const rewards = meta.rewards || {};
    const lootTotal = expeditionLootTotal(rewards);
    const cargoTotal = Number(meta.cargo_total || 0);
    const delayExtra = Number(meta.delay_extra || 0);
    const badge = expeditionEventBadge(eventKey, severity);
    const risk = expeditionRiskLabel(eventKey);
    const find = expeditionFindLabel(rewards, severity, eventKey);
    const returnLabel = expeditionReturnLabel(delayExtra);
    const fleet = meta.fleet_ships || {};
    const fleetTotal = unitCountTotal(fleet);

    const sections = [];

    sections.push(
      `<header class="gc-combat-report-hero gc-combat-report-hero--${esc(visual.badge)} gc-combat-report-hero--expedition">` +
        `<div class="gc-combat-report-hero-top">` +
          `<span class="gc-combat-report-hero-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-combat-report-hero-text">` +
            `<div class="gc-combat-report-coords gc-mono">${coordLink(meta.target_coords, meta.target_coords || "—")}</div>` +
            `<div class="gc-combat-report-vs">${esc(eventLabel)}</div>` +
          `</div>` +
          `<span class="gc-combat-report-result-badge">` +
            `<span class="gc-combat-report-result-main">${esc(badge)}</span>` +
            `<span class="gc-combat-report-result-sub">${esc(
              t("fleet_expedition_report_meta_line", "%(return)s · Risk: %(risk)s · Find: %(find)s")
                .replace("%(return)s", returnLabel)
                .replace("%(risk)s", risk)
                .replace("%(find)s", find)
            )}</span>` +
          `</span>` +
        `</div>` +
        (desc ? `<p class="gc-combat-report-hero-desc">${esc(desc)}</p>` : "") +
      `</header>`
    );

    sections.push(
      `<div class="gc-player-card-stats gc-combat-report-stats">` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("expedition_report_stat_loot", "Loot"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(lootTotal))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("expedition_report_stat_cargo", "Cargo"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(lootTotal))}/${esc(formatInt(cargoTotal))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("expedition_report_stat_delay", "Delay"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(delayExtra))}</span>` +
        `</div>` +
        `<div class="gc-player-card-stat">` +
          `<span class="gc-player-card-stat-label">${esc(t("expedition_report_stat_fleet", "Fleet"))}</span>` +
          `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(fleetTotal))}</span>` +
        `</div>` +
      `</div>`
    );

    sections.push(
      renderCombatPanel(
        t("fleet_expedition_report_section_fleet", "Expedition fleet"),
        renderCombatUnitGrid(fleet, null) +
          `<p class="gc-combat-report-fleet-status">${esc(
            t("fleet_expedition_report_fleet_summary", "%(ships)s · Cargo %(used)s/%(total)s · Status: %(status)s")
              .replace("%(ships)s", formatInt(fleetTotal))
              .replace("%(used)s", formatInt(lootTotal))
              .replace("%(total)s", formatInt(cargoTotal))
              .replace("%(status)s", expeditionFleetStatus(delayExtra, lootTotal))
          )}</p>`,
        "gc-combat-report-panel--attacker"
      )
    );

    sections.push(
      renderCombatPanel(
        t("fleet_expedition_report_section_loot", "Recovered cargo"),
        renderCombatLootChips(rewards),
        `gc-combat-report-panel--loot${lootTotal > 0 ? " gc-combat-report-panel--loot-found" : ""}`
      )
    );

    return (
      `<div class="gc-player-card-shell gc-combat-report-shell gc-combat-report-shell--expedition" data-theme="${esc(visual.theme)}">` +
      sections.join("") +
      `</div>`
    );
  }

  function renderInboxReportTeaser(msg, opts = {}) {
    const meta = msg.metadata || {};
    const kind = getInboxReportKind(msg);
    if (kind === "combat") return renderCombatReportTeaser(meta, opts);
    if (kind === "spy") return renderSpyReportTeaser(meta, opts);
    if (kind === "expedition") return renderExpeditionReportTeaser(meta, opts);
    return "";
  }

  function renderMessageBody(msg) {
    const kind = getInboxReportKind(msg);
    if (kind) {
      return { html: null, plain: msg.body || "", inboxReport: true, reportKind: kind };
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
      if (e.key === "Escape" && REPORT_MODAL.open) {
        e.preventDefault();
        closeInboxReportModal();
        return;
      }
      if (e.key !== "Enter" && e.key !== " ") return;
      const item = e.target.closest(".gc-messages-item[data-id][role='button']");
      if (!item || !document.getElementById("messages-page")) return;
      if (
        e.target.closest(
          "a.gc-galaxy-coord-link, [data-open-inbox-report], [data-open-combat-report], [data-spy-action]"
        )
      ) {
        return;
      }
      e.preventDefault();
      const id = Number(item.dataset.id);
      if (Number.isFinite(id)) ensureMessagesState()?.openMessage?.(id);
    });

    cacheReportModalElements();
    REPORT_MODAL.root?.querySelectorAll("[data-cr-close]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        closeInboxReportModal();
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

      if (e.target.closest("a.gc-galaxy-coord-link")) {
        return;
      }

      const spyAttack = e.target.closest('[data-spy-action="attack"]');
      if (spyAttack) {
        e.preventDefault();
        e.stopPropagation();
        const href = spyAttack.getAttribute("href");
        if (href && typeof GC.navigateTo === "function") {
          GC.navigateTo(href);
        } else if (href) {
          window.location.href = href;
        }
        return;
      }

      const spySimBtn = e.target.closest('[data-spy-action="dev_sim"]');
      if (spySimBtn) {
        e.preventDefault();
        e.stopPropagation();
        const mid = Number(spySimBtn.dataset.messageId);
        if (Number.isFinite(mid)) runDevCombatSimFromSpy(mid);
        return;
      }

      const openReportBtn = e.target.closest("[data-open-inbox-report], [data-open-combat-report]");
      if (openReportBtn) {
        e.preventDefault();
        e.stopPropagation();
        const id = Number(openReportBtn.dataset.openInboxReport || openReportBtn.dataset.openCombatReport);
        const kind = openReportBtn.dataset.reportKind || "combat";
        if (Number.isFinite(id)) {
          openInboxReportById(id, kind);
        }
        return;
      }

      const item = e.target.closest(".gc-messages-item[data-id]");
      if (item) {
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
          const reportKind = getInboxReportKind(m);
          const reportCls = reportKind ? ` gc-messages-item--report gc-messages-item--${reportKind}` : "";
          const teaser = reportKind ? renderInboxReportTeaser(m, { compact: true, messageId: m.id }) : "";
          return (
            `<div role="button" tabindex="0" class="gc-messages-item${active}${unreadCls}${reportCls}" data-id="${m.id}">` +
            `<span class="gc-messages-item-subject">${linkifyCoordsText(m.subject)}</span>` +
            (teaser ? `<span class="gc-messages-item-teaser">${teaser}</span>` : "") +
            `<span class="gc-messages-item-meta">${esc(categoryLabel(m.category))} · ${esc(formatTime(m.created_at))}</span>` +
            `</div>`
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
      if (dom.detailSubject) {
        dom.detailSubject.innerHTML = linkifyCoordsText(msg.subject || "");
      }
      const sender = msg.sender_name || categoryLabel(msg.category);
      if (dom.detailMeta) {
        dom.detailMeta.textContent = `${sender} · ${categoryLabel(msg.category)} · ${formatTime(msg.created_at)}`;
      }
      const rendered = renderMessageBody(msg);
      if (dom.detailBody) {
        if (rendered.inboxReport) {
          dom.detailBody.classList.add("gc-messages-detail-body--report");
          dom.detailBody.innerHTML = renderInboxReportTeaser(msg, {
            compact: false,
            messageId: msg.id,
          });
        } else {
          dom.detailBody.classList.remove("gc-messages-detail-body--report");
          dom.detailBody.innerHTML = renderPlainMessageHtml(rendered.plain);
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

      if (rendered.inboxReport) {
        const openKey =
          rendered.reportKind === "spy"
            ? "spy_report_open_full"
            : rendered.reportKind === "expedition"
              ? "expedition_report_open_full"
              : "combat_report_open_full";
        const openFallback =
          rendered.reportKind === "spy"
            ? "Open spy report"
            : rendered.reportKind === "expedition"
              ? "Open expedition report"
              : "Open full report";
        dom.detailActions.appendChild(mkBtn(t(openKey, openFallback), "open_inbox_report", "primary"));
        if (rendered.reportKind === "spy") {
          const meta = msg.metadata || {};
          const attackHref = fleetAttackHrefFromCoords(meta.target_coords);
          if (attackHref) {
            const atk = document.createElement("a");
            atk.href = attackHref;
            atk.className = "gc-btn gc-btn-danger gc-btn-sm";
            atk.dataset.spyAction = "attack";
            atk.textContent = t("spy_report_attack_btn", "Attack target");
            dom.detailActions.appendChild(atk);
          }
          if (devCombatSimEnabled()) {
            dom.detailActions.appendChild(
              mkBtn(t("spy_report_dev_sim_btn", "DEV: Combat simulator"), "spy_dev_sim", "outline")
            );
          }
        }
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
      } else if (action === "open_inbox_report" || action === "open_combat_report") {
        openInboxReportModal(msg);
        return;
      } else if (action === "spy_dev_sim") {
        await runDevCombatSimFromSpy(msg.id);
        return;
      } else if (action === "spy_attack") {
        navigateFleetAttack(msg.metadata?.target_coords);
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
  GC.openInboxReportModal = openInboxReportModal;
  GC.closeInboxReportModal = closeInboxReportModal;
  GC.openCombatReportModal = openCombatReportModal;
  GC.closeCombatReportModal = closeCombatReportModal;

  bindMessagesUiOnce();
})();
