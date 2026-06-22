/* Genesis Colonies – player messages inbox (PJAX-safe) */
(() => {
  "use strict";

  const GC = window.GC;
  if (!GC || typeof GC !== "object") {
    console.error("[messages] GC namespace missing — load main.js before messages.js");
    return;
  }

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
      .map((line) => `<p class="gc-messages-plain-line">${formatPlainMessageLine(line)}</p>`)
      .join("");
  }

  function formatWorldKeyLine(line) {
    const m = String(line || "").trim().match(/^field:([a-z_]+):(\d+):(\d+)$/i);
    if (!m) return null;
    const typeKey = m[1];
    const coords = `${m[2]}:${m[3]}`;
    const typeLabel = t(`strategic_world_type_${typeKey}`, keyFallbackLabel(typeKey));
    return esc(`${typeLabel} [${coords}]`);
  }

  function formatErrorCodeLine(line) {
    const key = String(line || "").trim();
    if (!/^[a-z][a-z0-9_]*$/i.test(key)) return null;
    const colonize = t(`fleet_colonize_fail_${key}`, "");
    if (colonize) return esc(colonize);
    const generic = t(`messages.error_code.${key}`, "");
    if (generic) return esc(generic);
    return esc(keyFallbackLabel(key));
  }

  function formatPlainMessageLine(line) {
    const raw = String(line || "").trim();
    if (!raw) return esc("—");
    const worldOnly = formatWorldKeyLine(raw);
    if (worldOnly) return worldOnly;
    const worldPref = raw.match(/^World:\s*(field:.+)$/i);
    if (worldPref) {
      const formatted = formatWorldKeyLine(worldPref[1]);
      if (formatted) return esc(t("fleet_world_colonize_report_world_label", "World:")) + " " + formatted;
    }
    const weltPref = raw.match(/^Welt:\s*(field:.+)$/i);
    if (weltPref) {
      const formatted = formatWorldKeyLine(weltPref[1]);
      if (formatted) return esc(t("fleet_world_colonize_report_world_label", "World:")) + " " + formatted;
    }
    const code = formatErrorCodeLine(raw);
    if (code) return code;
    return linkifyCoordsText(raw);
  }

  function formatInt(n) {
    if (typeof GC.formatNumber === "function") return GC.formatNumber(n);
    const v = Number(n);
    if (!Number.isFinite(v)) return "0";
    return String(Math.trunc(v));
  }

  function keyFallbackLabel(raw) {
    return String(raw || "")
      .split("_")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  function shipLabel(key) {
    const k = String(key || "");
    return t(`fleet_ship_${k}`, keyFallbackLabel(k));
  }

  function defenseLabel(key) {
    const k = String(key || "");
    return t(`defense_${k}`, keyFallbackLabel(k));
  }

  function unitLabel(key, defenseStock) {
    const k = String(key || "");
    if (defenseStock && Object.prototype.hasOwnProperty.call(defenseStock, k)) {
      return defenseLabel(k);
    }
    return shipLabel(k);
  }

  function unitIconUrl(key, defenseStock) {
    const k = String(key || "").trim();
    if (!k) return "";
    if (defenseStock && Object.prototype.hasOwnProperty.call(defenseStock, k)) {
      return typeof GC.defenseIconUrl === "function"
        ? GC.defenseIconUrl(k)
        : `/static/img/defense/${k}.png`;
    }
    return typeof GC.shipyardIconUrl === "function"
      ? GC.shipyardIconUrl(k)
      : `/static/img/ships/${k}.png`;
  }

  function reportBuildingIconUrl(key) {
    const k = String(key || "").trim();
    if (!k) return "";
    return typeof GC.buildingIconUrl === "function"
      ? GC.buildingIconUrl(k)
      : `/static/img/buildings/${k}.png`;
  }

  function reportUnitChipImg(key, defenseStock) {
    const src = unitIconUrl(key, defenseStock);
    if (!src) return "";
    return (
      `<img class="gc-combat-unit-chip-img" src="${esc(src)}" alt="" loading="lazy" decoding="async"` +
      ` onerror="this.style.display='none'">`
    );
  }

  function reportBuildingChipImg(key) {
    const src = reportBuildingIconUrl(key);
    if (!src) return "";
    return (
      `<img class="gc-combat-unit-chip-img" src="${esc(src)}" alt="" loading="lazy" decoding="async"` +
      ` onerror="this.style.display='none'">`
    );
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
    const perspective = String(meta?.perspective || "attacker");
    if (winner === "draw" || winner === "undecided") return "";
    if (winner === perspective) return "";
    return t(`combat_report_winner_${winner}`, winner);
  }

  const COMBAT_RESEARCH_KEYS = ["weapon_tech", "armor_tech", "shield_tech"];
  const COMBAT_RESEARCH_LABEL_KEYS = {
    weapon_tech: "tech_weapon_tech",
    armor_tech: "tech_armor_tech",
    shield_tech: "tech_shield_tech",
  };

  function renderCombatResearchSide(research, roleClass) {
    const snap = research && typeof research === "object" ? research : {};
    const rows = COMBAT_RESEARCH_KEYS.map((key) => {
      const entry = snap[key] || {};
      const level = formatInt(entry.level || 0);
      const pct = formatInt(entry.bonus_pct || 0);
      const label = t(COMBAT_RESEARCH_LABEL_KEYS[key] || key, key);
      return (
        `<div class="gc-combat-research-row">` +
          `<span class="gc-combat-research-tech">${esc(label)}</span>` +
          `<span class="gc-combat-research-level gc-mono" title="${esc(t("combat_report_research_level", "Level"))}">L${esc(level)}</span>` +
          `<span class="gc-combat-research-bonus gc-mono" title="${esc(t("combat_report_research_bonus", "Battle bonus"))}">+${esc(pct)}%</span>` +
        `</div>`
      );
    }).join("");
    return `<div class="gc-combat-research-side gc-combat-research-side--${esc(roleClass)}">${rows}</div>`;
  }

  function renderCombatResearchPanel(meta) {
    const atk = meta.attacker_combat_research;
    const def = meta.defender_combat_research;
    if (!atk && !def) return "";
    const hint = t(
      "combat_report_research_hint",
      "Account research bonuses applied to attack, hull, and shields in this battle."
    );
    return renderCombatPanel(
      t("combat_report_section_research", "Combat technology"),
      `<p class="gc-combat-report-research-hint">${esc(hint)}</p>` +
        `<div class="gc-combat-research-columns">` +
          `<div class="gc-combat-research-col">` +
            `<h5 class="gc-combat-research-col-title">${esc(meta.attacker_name || t("combat_report_section_attacker", "Attacker"))}</h5>` +
            renderCombatResearchSide(atk, "attacker") +
          `</div>` +
          `<div class="gc-combat-research-col">` +
            `<h5 class="gc-combat-research-col-title">${esc(meta.defender_name || t("combat_report_section_defender", "Defender"))}</h5>` +
            renderCombatResearchSide(def, "defender") +
          `</div>` +
        `</div>`,
      "gc-combat-report-panel--research"
    );
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
            `${reportUnitChipImg(key, defenseStock)}` +
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

  const EXPEDITION_LOOTBOX_IMG_FALLBACK = "/static/img/lootboxes/Generic_Supply_Container.png";

  function expeditionLootboxImage(box) {
    const raw = String(box?.image || "").trim();
    if (raw) {
      return raw.startsWith("/") ? raw : `/static/${raw.replace(/^\/+/, "")}`;
    }
    const key = String(box?.key || "");
    const byKey = {
      generic_supply_container: "/static/img/lootboxes/Generic_Supply_Container.png",
      resource_cache: "/static/img/lootboxes/Rare_Container.png",
      research_capsule: "/static/img/lootboxes/Research_Cache.png",
      wreckage_container: "/static/img/lootboxes/Wreckage_Container.png",
      military_cache: "/static/img/lootboxes/Military_Cache.png",
      alien_cache: "/static/img/lootboxes/Epic_Container.png",
      premium_cache: "/static/img/lootboxes/Relic_Container.png",
      mythic_container: "/static/img/lootboxes/Epic_Container.png",
      ancient_relic: "/static/img/lootboxes/Relic_Container.png",
      void_artifact: "/static/img/lootboxes/Event_Container.png",
    };
    return byKey[key] || EXPEDITION_LOOTBOX_IMG_FALLBACK;
  }

  function renderExpeditionLootboxChips(lootboxes) {
    const rows = Array.isArray(lootboxes) ? lootboxes.filter((box) => box && box.key) : [];
    if (!rows.length) return "";
    return (
      `<div class="gc-expedition-lootbox-grid">` +
      rows
        .map((box) => {
          const name = box.name || t(box.name_key || "", box.key || "");
          const amount = Math.max(1, Number(box.amount) || 1);
          const img = esc(expeditionLootboxImage(box));
          return (
            `<div class="gc-expedition-lootbox-chip${box.jackpot ? " gc-expedition-lootbox-chip--jackpot" : ""}">` +
            `<img class="gc-expedition-lootbox-chip-img" src="${img}" alt="${esc(name)}" loading="lazy" onerror="this.onerror=null;this.src='${EXPEDITION_LOOTBOX_IMG_FALLBACK}';">` +
            `<div class="gc-expedition-lootbox-chip-body">` +
            `<span class="gc-expedition-lootbox-chip-label">${esc(name)}</span>` +
            `<strong class="gc-expedition-lootbox-chip-value">×${esc(formatInt(amount))}</strong>` +
            `</div>` +
            `</div>`
          );
        })
        .join("") +
      `</div>`
    );
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

  function combatWinnerSide(meta) {
    const winner = String(meta?.result || meta?.winner || "undecided");
    if (winner === "attacker" || winner === "defender" || winner === "draw") return winner;
    return "undecided";
  }

  function combatDebrisPayload(meta) {
    const raw = meta?.debris ?? meta?.debris_field;
    if (!raw || typeof raw !== "object") return null;
    const metal = Math.max(0, Number(raw.metal) || 0);
    const crystal = Math.max(0, Number(raw.crystal) || 0);
    if (metal <= 0 && crystal <= 0) return null;
    return { metal, crystal };
  }

  function renderCombatDebrisChips(debris) {
    const rows = [];
    if (Number(debris?.metal || 0) > 0) {
      rows.push(
        `<div class="gc-expedition-loot-chip gc-expedition-loot-chip--metal gc-combat-debris-chip">` +
          `<span class="gc-expedition-loot-label">${esc(t("resource_metal", "Ferronit"))}</span>` +
          `<strong class="gc-expedition-loot-value">${esc(formatInt(debris.metal))}</strong>` +
        `</div>`
      );
    }
    if (Number(debris?.crystal || 0) > 0) {
      rows.push(
        `<div class="gc-expedition-loot-chip gc-expedition-loot-chip--crystal gc-combat-debris-chip">` +
          `<span class="gc-expedition-loot-label">${esc(t("resource_crystal", "Crytite"))}</span>` +
          `<strong class="gc-expedition-loot-value">${esc(formatInt(debris.crystal))}</strong>` +
        `</div>`
      );
    }
    return `<div class="gc-expedition-loot-grid gc-combat-debris-grid">${rows.join("")}</div>`;
  }

  function renderCombatDebrisPanel(meta) {
    const debris = combatDebrisPayload(meta);
    if (!debris) return "";
    return renderCombatPanel(
      t("combat_report_section_debris", "Debris field"),
      renderCombatDebrisChips(debris),
      "gc-combat-report-panel--debris"
    );
  }

  function renderCombatSideCard(meta, role, defenseStock) {
    const isAttacker = role === "attacker";
    const winner = combatWinnerSide(meta);
    const winClass = winner === role ? " gc-combat-side-card--winner" : "";
    const loseClass =
      winner !== "draw" && winner !== "undecided" && winner !== role ? " gc-combat-side-card--loser" : "";
    const name = isAttacker ? meta.attacker_name : meta.defender_name;
    const planet = String((isAttacker ? meta.origin_planet_name : meta.target_planet_name) || "").trim();
    const coords = isAttacker ? meta.origin_coords : meta.target_coords;
    const coordsLabelKey = isAttacker ? "combat_report_origin_coords" : "combat_report_target_coords";
    const coordsFallback = isAttacker ? "Launched from: %(coords)s" : "Target planet: %(coords)s";
    let unitsHtml;
    let unitTotal;
    if (isAttacker) {
      unitTotal = unitCountTotal(meta.attacking_ships);
      unitsHtml = renderCombatUnitGrid(meta.attacking_ships, null);
    } else {
      unitTotal = unitCountTotal(meta.defending_ships) + unitCountTotal(defenseStock);
      unitsHtml = renderCombatDefenderForces(meta, defenseStock);
    }
    const badgeHtml =
      winner === role
        ? `<span class="gc-combat-side-card-badge">${esc(t("combat_report_side_winner", "Victory"))}</span>`
        : "";
    return (
      `<article class="gc-combat-side-card gc-combat-side-card--${role}${winClass}${loseClass}">` +
        `<header class="gc-combat-side-card-head">` +
          `<div class="gc-combat-side-card-head-top">` +
            `<span class="gc-combat-side-card-role">${esc(
              t(
                isAttacker ? "combat_report_section_attacker" : "combat_report_section_defender",
                isAttacker ? "Attacker" : "Defender"
              )
            )}</span>` +
            badgeHtml +
          `</div>` +
          `<strong class="gc-combat-side-card-name">${esc(name || "—")}</strong>` +
          (planet ? `<span class="gc-combat-side-card-planet">${esc(planet)}</span>` : "") +
          `<span class="gc-combat-side-card-coords gc-mono">${coordLabelLink(
            coordsLabelKey,
            coordsFallback,
            coords || "—"
          )}</span>` +
          `<span class="gc-combat-side-card-total gc-mono" title="${esc(
            t("combat_report_side_ships", "%(count)s ships").replace("%(count)s", formatInt(unitTotal))
          )}">${esc(formatInt(unitTotal))}</span>` +
        `</header>` +
        `<div class="gc-combat-side-card-body">${unitsHtml}</div>` +
      `</article>`
    );
  }

  function renderCombatForcesDuel(meta, defenseStock) {
    return (
      `<div class="gc-combat-report-columns gc-combat-report-columns--duel">` +
        renderCombatSideCard(meta, "attacker", defenseStock) +
        renderCombatSideCard(meta, "defender", defenseStock) +
      `</div>`
    );
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
    const safeMeta = meta && typeof meta === "object" ? meta : {};
    const resultKey = safeMeta.result || safeMeta.winner || "undecided";
    const visual = combatResultVisual(safeMeta);
    const resultLabel = combatResultLabel(safeMeta);
    const resultSub = combatResultSubtitle(safeMeta);
    const defenseStock = safeMeta.defending_defense || {};
    const roundsCount = safeMeta.rounds_fought || (safeMeta.rounds || []).length || 0;
    const atkLossTotal = unitCountTotal(safeMeta.attacker_losses);
    const defLossTotal = unitCountTotal(safeMeta.defender_losses);
    const loot = safeMeta.loot || {};
    const lootTotal = expeditionLootTotal(loot);
    const routeBits = [safeMeta.origin_planet_name, safeMeta.target_planet_name]
      .map((name) => String(name || "").trim())
      .filter(Boolean);
    const routeSub = routeBits.join(" · ");

    const sections = [];

    sections.push(
      `<header class="gc-combat-report-hero gc-combat-report-hero--${esc(visual.badge)}">` +
        `<div class="gc-combat-report-hero-top">` +
          `<span class="gc-combat-report-hero-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-combat-report-hero-text">` +
            `<div class="gc-combat-report-coords gc-mono">${combatCoordsRoute(safeMeta)}</div>` +
            (routeSub ? `<div class="gc-combat-report-route-sub">${esc(routeSub)}</div>` : "") +
            `<div class="gc-combat-report-vs">${esc(
              t("combat_report_vs", "%(attacker)s vs %(defender)s")
                .replace("%(attacker)s", safeMeta.attacker_name || "—")
                .replace("%(defender)s", safeMeta.defender_name || "—")
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
        (lootTotal > 0
          ? `<div class="gc-player-card-stat gc-player-card-stat--highlight">` +
              `<span class="gc-player-card-stat-label">${esc(t("combat_report_stat_loot", "Plunder"))}</span>` +
              `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(lootTotal))}</span>` +
            `</div>`
          : "") +
      `</div>`
    );

    sections.push(
      renderCombatPanel(
        t("combat_report_section_forces", "Forces"),
        renderCombatForcesDuel(safeMeta, defenseStock),
        "gc-combat-report-panel--forces-wrap"
      )
    );

    sections.push(
      renderCombatPanel(
        t("combat_report_section_losses", "Total losses"),
        renderCombatLossesSplit(safeMeta, defenseStock),
        "gc-combat-report-panel--losses"
      )
    );

    if (lootTotal > 0) {
      sections.push(
        renderCombatPanel(
          t("combat_report_section_loot", "Plundered cargo"),
          renderCombatLootChips(loot),
          "gc-combat-report-panel--loot gc-combat-report-panel--loot-found"
        )
      );
    }

    const debrisPanel = renderCombatDebrisPanel(safeMeta);
    if (debrisPanel) sections.push(debrisPanel);

    const researchPanel = renderCombatResearchPanel(safeMeta);
    if (researchPanel) sections.push(researchPanel);

    const ret = safeMeta.return_ships || {};
    if (unitCountTotal(ret) > 0) {
      sections.push(
        renderCombatPanel(
          t("combat_report_section_return", "Returning fleet"),
          renderCombatUnitGrid(ret, null),
          "gc-combat-report-panel--return"
        )
      );
    }

    const roundList = Array.isArray(safeMeta.rounds) ? safeMeta.rounds : [];
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

    return (
      `<div class="gc-player-card-shell gc-combat-report-shell" data-theme="${esc(visual.theme)}" data-result="${esc(
        resultKey
      )}">` +
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
      const place = expeditionTargetLabel(meta, { linked: false });
      const eventLabel = t(meta.event_label_key || `expedition_event_${meta.event_key}`, meta.event_key || "");
      if (meta.report_kind === "world_expedition" && place) {
        return `${t("expedition_report_modal_title", "Expedition report")} — ${place}`;
      }
      if (meta.report_kind === "world_salvage" && place) {
        return `${t("salvage_report_modal_title", "Salvage report")} — ${place}`;
      }
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
      syncUnreadFromResponse(data);
      const loaded = data?.ok ? data.data?.message : null;
      if (loaded && getInboxReportKind(loaded) === kind) msg = loaded;
    } else if (!msg.is_read) {
      const data = await messagesApi(`/api/messages/${messageId}`);
      syncUnreadFromResponse(data);
      const loaded = data?.ok ? data.data?.message : null;
      if (loaded) msg = loaded;
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
            `${reportBuildingChipImg(key)}` +
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
      ion_storm: { theme: "disturbance", icon: "⛈" },
      distress_beacon: { theme: "alert", icon: "✦" },
      ancient_minefield: { theme: "hazard", icon: "✸" },
      ancient_stash: { theme: "relic", icon: "✧" },
      lost_container: { theme: "treasure", icon: "▣" },
      abandoned_convoy: { theme: "fund", icon: "⛭" },
      ancient_derelict: { theme: "relic", icon: "✦" },
      spatial_rift: { theme: "legendary", icon: "◈" },
      time_anomaly: { theme: "legendary", icon: "⧖" },
      ancient_beacon: { theme: "legendary", icon: "✶" },
      pirate_encounter: { theme: "combat", icon: "☠" },
    };
    return map[eventKey] || { theme: "anomaly", icon: "◎" };
  }

  function expeditionEventBadge(eventKey, severity) {
    const badges = {
      nav_interference: "fleet_expedition_badge_disturbance",
      ion_storm: "fleet_expedition_badge_disturbance",
      sensor_glitch: "fleet_expedition_badge_anomaly",
      void_scan: "fleet_expedition_badge_anomaly",
      distress_beacon: "fleet_expedition_badge_alert",
      ancient_minefield: "fleet_expedition_badge_hazard",
      ancient_stash: "fleet_expedition_badge_relic",
      lost_container: "fleet_expedition_badge_treasure",
      abandoned_convoy: "fleet_expedition_badge_treasure",
      ancient_derelict: "fleet_expedition_badge_legendary",
      spatial_rift: "fleet_expedition_badge_legendary",
      time_anomaly: "fleet_expedition_badge_legendary",
      ancient_beacon: "fleet_expedition_badge_legendary",
      pirate_encounter: "fleet_expedition_badge_combat",
    };
    const key = badges[eventKey] || `fleet_expedition_badge_${severity || "normal"}`;
    return t(key, expeditionSeverityLabel(severity));
  }

  function expeditionRiskLabel(eventKey) {
    const high = new Set(["distress_beacon", "ancient_stash", "pirate_encounter", "ancient_minefield", "ancient_derelict", "abandoned_convoy", "spatial_rift", "time_anomaly", "ancient_beacon"]);
    const medium = new Set(["nav_interference", "ion_storm", "lost_container"]);
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
      if (eventKey === "nav_interference" || eventKey === "sensor_glitch" || eventKey === "ion_storm" || eventKey === "ancient_minefield") {
        return t("fleet_expedition_report_find_trace", "trace");
      }
      return t("fleet_expedition_report_find_none", "none");
    }
    if (severity === "major" || eventKey === "ancient_stash" || eventKey === "ancient_derelict" || eventKey === "abandoned_convoy" || eventKey === "spatial_rift" || eventKey === "ancient_beacon") {
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

  function expeditionCargoJackpotMult(meta) {
    const mult = Number(meta?.cargo_jackpot_mult ?? 1);
    return Number.isFinite(mult) && mult > 0 ? Math.floor(mult) : 1;
  }

  function expeditionEffectiveCargoCap(meta) {
    const base = Number(meta?.cargo_total ?? 0);
    if (!Number.isFinite(base) || base <= 0) {
      return null;
    }
    return Math.floor(base * expeditionCargoJackpotMult(meta));
  }

  function formatExpeditionCargoUsage(lootTotal, meta) {
    const effective = expeditionEffectiveCargoCap(meta);
    if (effective == null) {
      return formatInt(lootTotal);
    }
    return `${formatInt(lootTotal)}/${formatInt(effective)}`;
  }

  function renderExpeditionCargoStatHtml(lootTotal, meta) {
    const mult = expeditionCargoJackpotMult(meta);
    const base = Number(meta?.cargo_total ?? 0);
    const usage = formatExpeditionCargoUsage(lootTotal, meta);
    if (mult <= 1 || !Number.isFinite(base) || base <= 0) {
      return `<span class="gc-player-card-stat-value gc-mono">${esc(usage)}</span>`;
    }
    const badgeLabel = t("expedition_report_cargo_jackpot_badge", "Jackpot ×%(mult)s").replace(
      "%(mult)s",
      formatInt(mult)
    );
    const baseHint = t("expedition_report_cargo_base", "Base cargo: %(amount)s").replace(
      "%(amount)s",
      formatInt(base)
    );
    return (
      `<span class="gc-expedition-cargo-stat">` +
        `<span class="gc-player-card-stat-value gc-mono">${esc(usage)}</span>` +
        `<span class="gc-expedition-cargo-jackpot-badge">${esc(badgeLabel)}</span>` +
        `<span class="gc-expedition-cargo-base gc-mono">${esc(baseHint)}</span>` +
      `</span>`
    );
  }

  function expeditionTargetLabel(meta, { linked = true } = {}) {
    if (meta?.world_name_key) {
      return t(meta.world_name_key, meta.world_name_key);
    }
    const coords = meta?.target_coords || "—";
    return linked ? coordLink(coords, coords) : coords;
  }

  function expeditionHeroBadge(eventKey) {
    const visual = expeditionEventVisual(eventKey);
    const badgeByTheme = {
      fund: "victory",
      anomaly: "open",
      disturbance: "draw",
      alert: "defeat",
      relic: "victory",
      combat: "defeat",
      hazard: "defeat",
      treasure: "victory",
      legendary: "victory",
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
    const lootboxes = Array.isArray(meta.lootboxes) ? meta.lootboxes : [];
    const lootTotal = expeditionLootTotal(rewards);
    const lootHint =
      lootTotal > 0
        ? `${formatInt(rewards.metal || 0)} / ${formatInt(rewards.crystal || 0)} / ${formatInt(rewards.fuel_cells || 0)}`
        : lootboxes.length
          ? t("fleet_expedition_report_lootbox_teaser", "Lootbox secured")
          : t("combat_report_loot_none", "No plunder");

    return (
      `<div class="gc-combat-teaser gc-combat-teaser--${esc(visual.badge)} gc-combat-teaser--expedition${compact ? " gc-combat-teaser--compact" : ""}" data-event="${esc(eventKey)}">` +
        `<div class="gc-combat-teaser-top">` +
          `<span class="gc-combat-teaser-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-combat-teaser-headings">` +
            `<span class="gc-combat-teaser-coords gc-mono">${expeditionTargetLabel(meta)}</span>` +
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
    const lootboxes = Array.isArray(meta.lootboxes) ? meta.lootboxes : [];
    const lootTotal = expeditionLootTotal(rewards);
    const cargoTotal = Number(meta.cargo_total || 0);
    const effectiveCargoCap = expeditionEffectiveCargoCap(meta);
    const delayExtra = Number(meta.delay_extra || 0);
    const badge = expeditionEventBadge(eventKey, severity);
    const risk = expeditionRiskLabel(eventKey);
    const find = expeditionFindLabel(rewards, severity, eventKey);
    const returnLabel = expeditionReturnLabel(delayExtra);
    const fleet = meta.fleet_ships || {};
    const fleetTotal = unitCountTotal(fleet);
    const losses = meta.losses || {};
    const lossesTotal = Number(meta.losses_total || unitCountTotal(losses));
    const pirateCombat = meta.pirate_combat || null;

    const sections = [];

    sections.push(
      `<header class="gc-combat-report-hero gc-combat-report-hero--${esc(visual.badge)} gc-combat-report-hero--expedition">` +
        `<div class="gc-combat-report-hero-top">` +
          `<span class="gc-combat-report-hero-icon" aria-hidden="true">${esc(visual.icon)}</span>` +
          `<div class="gc-combat-report-hero-text">` +
            `<div class="gc-combat-report-coords gc-mono">${expeditionTargetLabel(meta)}</div>` +
            (meta.world_risk_key
              ? `<div class="gc-combat-report-world-risk">${esc(
                  t("fleet_world_expedition_report_risk", "Risk: %(risk)s").replace(
                    "%(risk)s",
                    t(meta.world_risk_key, "")
                  )
                )}</div>`
              : "") +
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
          renderExpeditionCargoStatHtml(lootTotal, meta) +
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

    if (lootTotal > 0) {
      sections.push(
        `<p class="gc-expedition-report-delivery-notice" role="note">${esc(
          t(
            "expedition_report_delivery_notice",
            "Reward is credited when the fleet returns to the origin planet."
          )
        )}</p>`
      );
    }

    if (pirateCombat) {
      const won = Boolean(meta.pirate_won ?? pirateCombat.won);
      sections.push(
        renderCombatPanel(
          t("expedition_report_section_pirate", "Pirate contact"),
          `<p class="gc-expedition-pirate-summary">${esc(
            t(
              won ? "expedition_report_pirate_win" : "expedition_report_pirate_loss",
              won ? "Your fleet repelled the pirate ambush." : "Your fleet broke contact under heavy fire."
            )
          )}</p>` +
            `<div class="gc-player-card-stats gc-combat-report-stats">` +
              `<div class="gc-player-card-stat">` +
                `<span class="gc-player-card-stat-label">${esc(t("expedition_report_stat_pirate_strength", "Pirate strength"))}</span>` +
                `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(pirateCombat.pirate_points || 0))}</span>` +
              `</div>` +
              `<div class="gc-player-card-stat">` +
                `<span class="gc-player-card-stat-label">${esc(t("expedition_report_stat_fleet_strength", "Fleet strength"))}</span>` +
                `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(pirateCombat.fleet_points || 0))}</span>` +
              `</div>` +
              `<div class="gc-player-card-stat">` +
                `<span class="gc-player-card-stat-label">${esc(t("expedition_report_stat_loss_rate", "Loss rate"))}</span>` +
                `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(pirateCombat.loss_pct || 0))}%</span>` +
              `</div>` +
            `</div>`,
          "gc-combat-report-panel--pirate"
        )
      );
    }

    const hazard = meta.hazard || null;
    if (hazard && (meta.event_key || "") === "ancient_minefield" && lossesTotal > 0) {
      sections.push(
        renderCombatPanel(
          t("expedition_report_section_minefield", "Ancient minefield"),
          `<p class="gc-expedition-hazard-summary">${esc(
            t(
              "expedition_report_minefield_damage",
              "The fleet crossed dormant mines — hull damage without hostile contact."
            )
          )}</p>` +
            `<div class="gc-player-card-stats gc-combat-report-stats">` +
              `<div class="gc-player-card-stat">` +
                `<span class="gc-player-card-stat-label">${esc(t("expedition_report_stat_loss_rate", "Loss rate"))}</span>` +
                `<span class="gc-player-card-stat-value gc-mono">${esc(formatInt(hazard.loss_pct || 0))}%</span>` +
              `</div>` +
            `</div>`,
          "gc-combat-report-panel--hazard"
        )
      );
    }

    const legendaryVariant = meta.legendary_variant || "";
    if (legendaryVariant && ["spatial_rift", "time_anomaly", "ancient_beacon"].includes(eventKey)) {
      const variantKey = `expedition_report_legendary_${eventKey}_${legendaryVariant}`;
      const variantDefaults = {
        spatial_rift_amplified: "Spatial distortion amplified recovered cargo.",
        spatial_rift_delayed: "The rift collapsed — return delayed.",
        time_anomaly_dilated: "Time dilation stretched the expedition.",
        time_anomaly_compressed: "Chrono compression registered — no return gain in this phase.",
        ancient_beacon_beacon: "The beacon unlocked a sealed cache from a forgotten age.",
      };
      const defaultText =
        variantDefaults[`${eventKey}_${legendaryVariant}`] || "Legendary discovery logged.";
      sections.push(
        renderCombatPanel(
          t("expedition_report_section_legendary", "Legendary discovery"),
          `<p class="gc-expedition-legendary-summary">${esc(t(variantKey, defaultText))}</p>`,
          "gc-combat-report-panel--legendary"
        )
      );
    }

    sections.push(
      renderCombatPanel(
        t("fleet_expedition_report_section_fleet", "Expedition fleet"),
        renderCombatUnitGrid(fleet, null) +
          `<p class="gc-combat-report-fleet-status">${esc(
            t("fleet_expedition_report_fleet_summary", "%(ships)s · Cargo %(used)s/%(total)s · Status: %(status)s")
              .replace("%(ships)s", formatInt(fleetTotal))
              .replace("%(used)s", formatInt(lootTotal))
              .replace(
                "%(total)s",
                effectiveCargoCap != null ? formatInt(effectiveCargoCap) : cargoTotal > 0 ? formatInt(cargoTotal) : "—"
              )
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

    if (lossesTotal > 0) {
      sections.push(
        renderCombatPanel(
          t("fleet_expedition_report_section_losses", "Ship losses"),
          renderCombatUnitGrid(losses, null),
          "gc-combat-report-panel--losses"
        )
      );
    }

    const salvaged = meta.salvaged_ships || {};
    const salvagedTotal = Number(meta.salvaged_total || unitCountTotal(salvaged));
    if (salvagedTotal > 0) {
      sections.push(
        renderCombatPanel(
          t("fleet_expedition_report_section_salvaged", "Salvaged ships"),
          renderCombatUnitGrid(salvaged, null),
          "gc-combat-report-panel--salvaged"
        )
      );
    }

    if (lootboxes.length) {
      sections.push(
        renderCombatPanel(
          t("fleet_expedition_report_section_lootboxes", "Lootboxes"),
          renderExpeditionLootboxChips(lootboxes),
          "gc-combat-report-panel--lootboxes"
        )
      );
    }

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
    const c = String(cat || "");
    return t(`messages.category.${c}`, keyFallbackLabel(c));
  }

  function formatTime(ts) {
    if (typeof GC.formatLocaleDateTime === "function") return GC.formatLocaleDateTime(ts);
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return "–";
    try {
      const ms = n < 1e12 ? n * 1000 : n;
      return new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(new Date(ms));
    } catch (_) {
      return "–";
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
    if (typeof GC.mergeLastState === "function") {
      GC.mergeLastState({ unread_messages_count: n }, "messages_local");
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

  function isActiveMessagesState(state) {
    return Boolean(state && state === GC.messagesPageState && document.getElementById("messages-page"));
  }

  function isCurrentInit(state, initSeq) {
    return isActiveMessagesState(state) && state.initSeq === initSeq;
  }

  function isCurrentRequest(state, initSeq, requestId) {
    return isCurrentInit(state, initSeq) && state.requestSeq === requestId;
  }

  function clearInboxLoadingUi() {
    getMessagesDom()?.list?.classList.remove("is-loading");
  }

  function recoverStuckInbox(st) {
    if (!st || !document.getElementById("messages-page")) return false;
    let recovered = false;
    if (st.loading && !st.listInflight) {
      st.loading = false;
      clearInboxLoadingUi();
      recovered = true;
      msgDebug("[messages] recovered stuck loading flag");
    }
    if (!messagesDomMatchesState(st) && !messagesDomNeedsFreshInit()) {
      syncMessagesDomInit(st.initSeq);
      recovered = true;
    }
    return recovered;
  }

  function ensureInboxFetching(st, opts = {}) {
    if (!isActiveMessagesState(st) || typeof st.loadList !== "function") return null;
    recoverStuckInbox(st);
    if (st.loading && st.listInflight) {
      attachInboxLoadPaint(st);
      return st.listInflight;
    }
    if (st.listInflight && st.inflightFilter === st.filter && !opts.force) {
      attachInboxLoadPaint(st);
      return st.listInflight;
    }
    if (st.listLoaded && inboxPaintIsHealthy(st)) return null;
    if (st.listLoaded && inboxNeedsRepaint(st)) {
      repairInboxPaint(st);
      if (inboxPaintIsHealthy(st)) return null;
    }
    const force = Boolean(opts.force) || inboxNeedsRepaint(st) || recoverStuckInbox(st);
    const run = st.listInflight || st.loadList(true, { force }) || null;
    if (run) attachInboxLoadPaint(st);
    return run;
  }

  function ensureMessagesState() {
    if (!document.getElementById("messages-page")) return null;
    let st = GC.messagesPageState;
    if (!st || messagesDomNeedsFreshInit() || !messagesDomMatchesState(st)) {
      initMessagesPage();
      st = GC.messagesPageState;
    }
    if (!st) return null;
    if (!st.listLoaded || !inboxPaintIsHealthy(st) || inboxNeedsRepaint(st)) {
      reconcileInboxPaint(st, "ensure");
    }
    return GC.messagesPageState || null;
  }

    function resetMessagesPageState() {
    const prev = GC.messagesPageState;
    if (prev) {
      prev.requestSeq += 1;
      if (prev.listAbort) {
        try {
          prev.listAbort.abort();
        } catch (_) {}
      }
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

      if (e.target.closest("#messages-enter-select")) {
        e.preventDefault();
        state.enterSelectionMode?.();
        return;
      }
      if (e.target.closest("#messages-exit-select")) {
        e.preventDefault();
        state.exitSelectionMode?.();
        return;
      }
      if (e.target.closest("#messages-bulk-read")) {
        e.preventDefault();
        state.runBulkAction?.("read");
        return;
      }
      if (e.target.closest("#messages-bulk-archive")) {
        e.preventDefault();
        state.runBulkAction?.("archive");
        return;
      }
      if (e.target.closest("#messages-bulk-delete")) {
        e.preventDefault();
        state.runBulkAction?.("delete");
        return;
      }
      if (e.target.closest("#messages-select-all")) {
        return;
      }
      const rowCheck = e.target.closest(".gc-messages-item-check input[type=checkbox]");
      if (rowCheck) {
        e.stopPropagation();
        state.toggleChecked?.(Number(rowCheck.dataset.id), rowCheck.checked);
        return;
      }

      const tabBtn = e.target.closest("#messages-tabs .tab-btn[data-filter]");
      if (tabBtn) {
        if (!e.isTrusted) return;
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
        state.exitSelectionMode?.({ skipRender: true });
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
      if (item && !e.target.closest("[data-stop-row]")) {
        const id = Number(item.dataset.id);
        if (!Number.isFinite(id)) return;
        if (state.selectionMode) {
          e.preventDefault();
          state.toggleChecked?.(id, !state.checkedIds.has(id));
          return;
        }
        state.openMessage?.(id);
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

  function whenMessagesDomReady(fn) {
    if (typeof fn !== "function") return;
    if (document.getElementById("messages-page") && document.getElementById("messages-list")) {
      fn();
      return;
    }
    let attempts = 0;
    const tick = () => {
      if (!document.getElementById("messages-page")) {
        if (++attempts > 120) {
          msgDebug("[messages] dom wait timeout");
          return;
        }
        const next =
          typeof requestAnimationFrame === "function" ? requestAnimationFrame : (cb) => setTimeout(cb, 16);
        next(tick);
        return;
      }
      if (!document.getElementById("messages-list")) {
        if (++attempts > 120) {
          msgDebug("[messages] dom wait timeout (list)");
          return;
        }
        const next =
          typeof requestAnimationFrame === "function" ? requestAnimationFrame : (cb) => setTimeout(cb, 16);
        next(tick);
        return;
      }
      fn();
    };
    tick();
  }

  function countInboxItemsInDocument() {
    return document.querySelectorAll("#messages-list .gc-messages-item").length;
  }

  function readActiveFilterFromDom() {
    const activeTab = document.querySelector("#messages-tabs .tab-btn.active[data-filter]");
    return activeTab?.dataset.filter || "all";
  }

  function syncMessagesDomInit(initSeq) {
    const page = document.getElementById("messages-page");
    if (page) page.dataset.messagesInit = String(initSeq);
  }

  function messagesDomMatchesState(st) {
    if (!st) return false;
    const page = document.getElementById("messages-page");
    if (!page) return false;
    return Number(page.dataset.messagesInit || 0) === Number(st.initSeq || 0);
  }

  function inboxHasRenderedItems() {
    return countInboxItemsInDocument() > 0;
  }

  /** True when the list still shows the server PJAX "loading" shell. */
  function inboxShowsLoadingShell() {
    const list = document.getElementById("messages-list");
    if (!list || inboxHasRenderedItems()) return false;
    const empty = list.querySelector(".gc-messages-empty");
    if (!empty) return false;
    if (empty.dataset.messagesShell === "loading") return true;
    const text = String(empty.textContent || "").trim();
    const loadingLabel = t("messages.loading", "Loading...");
    return text === loadingLabel || text.includes(loadingLabel);
  }

  /** True when the list is still the server PJAX shell (loading/empty), not rendered rows. */
  function inboxShowsPlaceholderOnly() {
    const list = document.getElementById("messages-list");
    if (!list) return false;
    if (inboxHasRenderedItems()) return false;
    return !!list.querySelector(".gc-messages-empty");
  }

  function messagesDomNeedsFreshInit() {
    const page = document.getElementById("messages-page");
    return Boolean(page && !page.dataset.messagesInit);
  }

  function inboxNeedsRepaint(st) {
    if (!st || !st.listLoaded || st.loading) return false;
    if (!document.getElementById("messages-page")) return false;
    if (!messagesDomMatchesState(st)) return true;
    const msgCount = Array.isArray(st.messages) ? st.messages.length : 0;
    if (msgCount > 0) return !inboxHasRenderedItems();
    return inboxShowsLoadingShell();
  }

  function flushInboxLayout() {
    const wrap = document.querySelector(".gc-messages-list-wrap");
    const list = document.getElementById("messages-list");
    const layout = document.querySelector(".gc-messages-layout");
    if (layout) void layout.offsetHeight;
    if (wrap) void wrap.offsetHeight;
    if (list) {
      list.classList.remove("is-loading");
      void list.offsetHeight;
    }
  }

  function repairInboxPaint(st) {
    if (!st || !document.getElementById("messages-page")) return false;
    if (!messagesDomMatchesState(st) && !messagesDomNeedsFreshInit()) {
      syncMessagesDomInit(st.initSeq);
    }
    if (typeof st.commitInboxRender === "function") {
      st.commitInboxRender();
    } else if (typeof st.repaintList === "function") {
      st.repaintList();
    }
    flushInboxLayout();
    return inboxPaintIsHealthy(st);
  }

  let _inboxPaintRepairToken = 0;

  /** Ensure inbox rows are painted without waiting for user interaction. */
  function scheduleInboxPaintRepair(st, reason) {
    if (!st || !document.getElementById("messages-page")) return;
    const token = ++_inboxPaintRepairToken;
    const runPass = (pass) => {
      if (token !== _inboxPaintRepairToken) return;
      const cur = GC.messagesPageState;
      if (!cur || cur.initSeq !== st.initSeq) return;
      if (inboxPaintIsHealthy(cur)) return;
      repairInboxPaint(cur);
      msgDebug("[messages] paint repair", { pass, reason, initSeq: cur.initSeq });
      if (!inboxPaintIsHealthy(cur) && pass < 3) {
        const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (fn) => queueMicrotask(fn);
        if (pass === 0) queueMicrotask(() => runPass(pass + 1));
        else if (pass === 1) raf(() => runPass(pass + 2));
        else setTimeout(() => runPass(pass + 3), 80);
      }
    };
    runPass(0);
  }

  function attachInboxLoadPaint(st) {
    if (!st?.listInflight || typeof st.listInflight.then !== "function") return;
    void st.listInflight
      .then(() => {
        const cur = GC.messagesPageState;
        if (!cur || cur.initSeq !== st.initSeq) return;
        if (!inboxPaintIsHealthy(cur)) scheduleInboxPaintRepair(cur, "load_settled");
      })
      .catch(() => {});
  }

  function inboxNeedsReload(st) {
    if (!document.getElementById("messages-page")) return false;
    if (!st) return true;
    if (!messagesDomMatchesState(st)) return true;
    if (st.loading && st.listInflight) return false;
    if (!st.listLoaded) return true;
    if (st.loading && !st.listInflight) return true;
    return false;
  }

  function inboxPaintIsHealthy(st) {
    if (!st || st.loading) return false;
    if (!document.getElementById("messages-page")) return false;
    if (inboxShowsLoadingShell()) return false;
    if (!messagesDomMatchesState(st)) return false;
    if (!st.listLoaded) return false;
    const msgCount = Array.isArray(st.messages) ? st.messages.length : 0;
    if (msgCount > 0) return inboxHasRenderedItems();
    return !inboxHasRenderedItems();
  }

  function reconcileInboxPaint(st, reason, opts = {}) {
    if (!st || !isActiveMessagesState(st)) return;
    recoverStuckInbox(st);
    if (inboxNeedsRepaint(st)) {
      repairInboxPaint(st);
    }
    if (!st.listLoaded || !inboxPaintIsHealthy(st)) {
      ensureInboxFetching(st, {
        force: Boolean(opts.force) || !st.listLoaded || inboxNeedsRepaint(st),
      });
      return;
    }
    const verify = () => {
      const cur = GC.messagesPageState;
      if (!cur || cur.initSeq !== st.initSeq) return;
      if (!inboxPaintIsHealthy(cur)) scheduleInboxPaintRepair(cur, reason || "reconcile");
    };
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => requestAnimationFrame(verify));
    } else {
      queueMicrotask(verify);
    }
  }

  function startMessagesInboxLoad(st, opts = {}) {
    return ensureInboxFetching(st, opts);
  }

  /** PJAX-safe inbox boot — continue or repair load; never re-init over mod(). */
  function bootMessagesInbox(opts = {}) {
    if (!document.getElementById("messages-page")) {
      whenMessagesDomReady(() => bootMessagesInbox(opts));
      return null;
    }
    let st = GC.messagesPageState;
    if (!st || messagesDomNeedsFreshInit() || !messagesDomMatchesState(st)) {
      initMessagesPage({ pjax: Boolean(opts && opts.pjax) });
      st = GC.messagesPageState;
    }
    if (!st) return null;
    if (st.listLoaded && inboxPaintIsHealthy(st) && !opts.force) {
      return st.listInflight || null;
    }
    if (!st.listLoaded || !inboxPaintIsHealthy(st) || inboxNeedsRepaint(st)) {
      reconcileInboxPaint(st, "boot", opts);
    }
    return st.listInflight || null;
  }

  function initMessagesPage(options) {
    bindMessagesUiOnce();

    if (!document.getElementById("messages-page")) {
      whenMessagesDomReady(() => initMessagesPage(options || {}));
      return;
    }

    const initSeq = ++_messagesInitSeq;
    resetMessagesPageState();

    syncMessagesDomInit(initSeq);

    const domFilter = readActiveFilterFromDom();

    const tabsEl = document.getElementById("messages-tabs");
    tabsEl?.querySelectorAll(".tab-btn[data-filter]").forEach((btn) => {
      const f = btn.dataset.filter || "all";
      const active = f === domFilter;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });

    const filter = domFilter;
    console.debug("[messages] init", { initSeq, filter });
    msgDebug("[messages] init detail", { pjax: Boolean(options && options.pjax) });

    const state = {
      initSeq,
      filter,
      messages: [],
      selectedId: null,
      selectionMode: false,
      checkedIds: new Set(),
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
      const hasMessage = Boolean(show);
      if (dom.detail) dom.detail.hidden = !hasMessage;
      if (dom.detailEmpty) dom.detailEmpty.hidden = hasMessage;
      const wrap = document.getElementById("messages-detail-wrap");
      if (wrap) wrap.classList.toggle("has-message", hasMessage);
    }

    function syncSelectionUi() {
      const n = state.checkedIds.size;
      const has = n > 0;
      const listWrap = document.querySelector(".gc-messages-list-wrap");
      if (listWrap) listWrap.classList.toggle("is-selecting", state.selectionMode);

      const normalBar = document.getElementById("messages-select-normal");
      const activeBar = document.getElementById("messages-select-active");
      const hasMessages = state.messages.length > 0 && state.listLoaded && !state.loading;

      if (normalBar) normalBar.hidden = state.selectionMode || !hasMessages;
      if (activeBar) activeBar.hidden = !state.selectionMode;

      ["messages-bulk-read", "messages-bulk-archive", "messages-bulk-delete"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !has;
      });

      const countEl = document.getElementById("messages-selected-count");
      if (countEl) {
        countEl.textContent =
          n > 0 ? t("messages.selected_count", "%(count)s selected").replace("%(count)s", String(n)) : "";
        countEl.hidden = n <= 0;
      }

      const selectAll = document.getElementById("messages-select-all");
      if (selectAll && state.messages.length && state.selectionMode) {
        selectAll.indeterminate = n > 0 && n < state.messages.length;
        selectAll.checked = n > 0 && n === state.messages.length;
      } else if (selectAll) {
        selectAll.indeterminate = false;
        selectAll.checked = false;
      }
    }

    function enterSelectionMode() {
      if (!state.messages.length) return;
      state.selectionMode = true;
      state.checkedIds.clear();
      syncSelectionUi();
      renderList();
    }

    function exitSelectionMode(opts = {}) {
      if (!state.selectionMode && !state.checkedIds.size) {
        syncSelectionUi();
        return;
      }
      state.selectionMode = false;
      state.checkedIds.clear();
      syncSelectionUi();
      if (!opts.skipRender) renderList();
    }

    function toggleChecked(id, checked) {
      if (!Number.isFinite(id)) return;
      if (checked) state.checkedIds.add(id);
      else state.checkedIds.delete(id);
      syncSelectionUi();
      const rowCheck = document.querySelector(`.gc-messages-item-check input[data-id="${id}"]`);
      if (rowCheck) rowCheck.checked = checked;
    }

    function setAllChecked(checked) {
      state.checkedIds.clear();
      if (checked) state.messages.forEach((m) => state.checkedIds.add(m.id));
      renderList();
    }

    async function runBulkAction(action) {
      const ids = [...state.checkedIds];
      if (!ids.length) return;
      if (action === "delete" && !window.confirm(t("messages.delete_confirm"))) return;
      const data = await messagesApi("/api/messages/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ids }),
      });
      if (!data?.ok) {
        showErrorList(data?.error || "error_load");
        return;
      }
      syncUnreadFromResponse(data);
      if (action === "delete" && state.selectedId && ids.includes(state.selectedId)) {
        state.selectedId = null;
        setDetailVisible(false);
      }
      state.checkedIds.clear();
      exitSelectionMode({ skipRender: true });
      await loadList(true, { force: true });
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
        showListMessage(
          `<div class="gc-messages-empty" data-messages-shell="loading">${esc(t("messages.loading"))}</div>`
        );
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
      if (!dom?.list) return 0;
      dom.list.classList.remove("is-loading");

      if (state.loading || !state.listLoaded) {
        if (!state.listLoaded) {
          showListMessage(
            `<div class="gc-messages-empty" data-messages-shell="loading">${esc(t("messages.loading"))}</div>`
          );
        }
        return 0;
      }

      if (!state.messages.length) {
        showListMessage(`<div class="gc-messages-empty">${esc(t("messages.empty"))}</div>`);
        state.selectedId = null;
        state.selectionMode = false;
        state.checkedIds.clear();
        setDetailVisible(false);
        syncSelectionUi();
        return 0;
      }

      dom.list.innerHTML = state.messages
        .map((m) => {
          const unread = !m.is_read;
          const active = state.selectedId === m.id ? " is-active" : "";
          const unreadCls = unread ? " is-unread" : "";
          const checked = state.checkedIds.has(m.id) ? " checked" : "";
          const reportKind = getInboxReportKind(m);
          const reportCls = reportKind ? ` gc-messages-item--report gc-messages-item--${reportKind}` : "";
          const teaser = reportKind ? renderInboxReportTeaser(m, { compact: true, messageId: m.id }) : "";
          const checkHtml = state.selectionMode
            ? `<label class="gc-messages-item-check" data-stop-row="1">` +
              `<input type="checkbox" data-id="${m.id}"${checked} aria-label="${esc(t("messages.select_one", "Select"))}" />` +
              `</label>`
            : "";
          return (
            `<div role="button" tabindex="0" class="gc-messages-item${active}${unreadCls}${reportCls}" data-id="${m.id}">` +
            checkHtml +
            `<span class="gc-messages-item-content">` +
            `<span class="gc-messages-item-subject">${linkifyCoordsText(m.subject)}</span>` +
            (teaser ? `<span class="gc-messages-item-teaser">${teaser}</span>` : "") +
            `<span class="gc-messages-item-meta">${esc(categoryLabel(m.category))} · ${esc(formatTime(m.created_at))}</span>` +
            `</span>` +
            `</div>`
          );
        })
        .join("");
      syncSelectionUi();
      flushInboxLayout();
      return countInboxItemsInDocument();
    }

    function commitInboxRender() {
      if (state !== GC.messagesPageState || !document.getElementById("messages-page")) return false;
      state.loading = false;
      getMessagesDom()?.list?.classList.remove("is-loading");
      const painted = renderList();
      const expected = Array.isArray(state.messages) ? state.messages.length : 0;
      const domCount = countInboxItemsInDocument();
      console.debug("[messages] rendered", {
        expected,
        dom: domCount,
        painted,
        filter: state.filter,
        initSeq,
      });
      if (expected > 0 && domCount === 0) {
        scheduleInboxPaintRepair(state, "commit_retry");
      }
      return domCount > 0 || expected === 0;
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
      if (msg.reply_to_player_id || msg.sender_player_id) {
        dom.detailActions.appendChild(mkBtn(t("messages.reply"), "reply", "primary"));
      }
      if (!msg.is_archived) dom.detailActions.appendChild(mkBtn(t("messages.archive"), "archive", "outline"));
      dom.detailActions.appendChild(mkBtn(t("messages.delete"), "delete", "danger"));
    }

    function clearLoadingIfStale(requestId) {
      if (state.requestSeq !== requestId) {
        if (!state.listInflight) state.loading = false;
        return;
      }
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
          if (state === GC.messagesPageState) state.loading = false;
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
        commitInboxRender();
        scheduleInboxPaintRepair(state, "load");
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
          if (state === GC.messagesPageState) state.loading = false;
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
      if (!isCurrentInit(state, initSeq)) {
        msgDebug("[messages] loadList ignored (stale init)", { initSeq });
        return;
      }
      recoverStuckInbox(state);
      const force = Boolean(opts && opts.force);

      if (state.listInflight) {
        if (state.inflightFilter === state.filter) {
          return state.listInflight;
        }
        if (!force) {
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
      const prevIdx = state.messages.findIndex((m) => m.id === id);
      const wasUnread = prevIdx >= 0 && !state.messages[prevIdx].is_read;
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
      if (!syncUnreadFromResponse(data)) {
        if (wasUnread && msg.is_read) {
          const cur =
            typeof GC.lastState?.unread_messages_count === "number"
              ? GC.lastState.unread_messages_count
              : 1;
          updateLocalUnread(Math.max(0, cur - 1));
        } else {
          await refreshBadgesFromServer();
        }
      }
      renderList();
      renderDetail(msg);
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
      if (!msg || !isActiveMessagesState(state)) return;
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
      await loadList(true, { force: true });
      if (state.selectedId && action !== "delete") await openMessage(state.selectedId);
    }

    state.loadList = loadList;
    state.repaintList = () => {
      if (!isCurrentInit(state, initSeq)) return;
      renderList();
    };
    state.commitInboxRender = () => {
      if (state !== GC.messagesPageState) return false;
      return commitInboxRender();
    };
    state.openMessage = openMessage;
    state.handleAction = handleAction;
    state.setDetailVisible = setDetailVisible;
    state.toggleChecked = toggleChecked;
    state.runBulkAction = runBulkAction;
    state.setAllChecked = setAllChecked;
    state.enterSelectionMode = enterSelectionMode;
    state.exitSelectionMode = exitSelectionMode;

    document.getElementById("messages-select-all")?.addEventListener("change", (ev) => {
      setAllChecked(Boolean(ev.target?.checked));
    });

    GC.messagesPageState = state;

    setDetailVisible(false);
    syncSelectionUi();

    attachInboxLoadPaint(state);
    ensureInboxFetching(state, { force: false });
  }

  GC.modules = GC.modules || {};
  GC.modules.messages = initMessagesPage;
  GC.initMessagesPage = initMessagesPage;
  GC.bootMessagesInbox = bootMessagesInbox;
  GC.scheduleInboxPaintRepair = scheduleInboxPaintRepair;
  GC.openMessagesCompose = openCompose;
  GC.ensureMessagesState = ensureMessagesState;
  GC.openInboxReportModal = openInboxReportModal;
  GC.closeInboxReportModal = closeInboxReportModal;
  GC.openCombatReportModal = openCombatReportModal;
  GC.closeCombatReportModal = closeCombatReportModal;

  bindMessagesUiOnce();
})();
