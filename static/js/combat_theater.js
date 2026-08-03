/**
 * Combat Encounter Theater — cinematic face-off before combat reports.
 * Server metadata only; no combat math. Owner: docs/COMBAT_THEATER.md
 */
(function (global) {
  "use strict";

  const GC = global.GC || (global.GC = {});

  const SHIP_SIGNATURES = {
    spark_drone: "spark_drone",
    veil_probe: "veil_probe",
    falcon_interceptor: "falcon_interceptor",
    solar_skiff: "solar_skiff",
    mule_courier: "mule_courier",
    atlas_hauler: "atlas_hauler",
    ironclad_frigate: "ironclad_frigate",
    eclipse_runner: "eclipse_runner",
    harvest_reclaimer: "harvest_reclaimer",
    seed_ark: "seed_ark",
    deep_vault_ark: "deep_vault_ark",
    planet_breaker: "planet_breaker",
  };

  const DEFENSE_SIGNATURES = {
    slug_launcher: "slug_launcher",
    sentinel_turret: "sentinel_turret",
    plasma_arc: "plasma_arc",
    ion_bastion: "ion_bastion",
    flak_array: "flak_array",
    pulse_barrier: "pulse_barrier",
    orbital_shield: "orbital_shield",
  };

  const BOLT_BURST = {
    spark_drone: [3, 5],
    veil_probe: [1, 2],
    falcon_interceptor: [2, 4],
    solar_skiff: [2, 3],
    mule_courier: [1, 2],
    atlas_hauler: [1, 2],
    ironclad_frigate: [2, 3],
    eclipse_runner: [2, 3],
    harvest_reclaimer: [2, 3],
    seed_ark: [1, 2],
    deep_vault_ark: [1, 2],
    planet_breaker: [1, 2],
    slug_launcher: [2, 3],
    sentinel_turret: [2, 3],
    plasma_arc: [2, 3],
    ion_bastion: [1, 2],
    flak_array: [4, 6],
    pulse_barrier: [1, 2],
    orbital_shield: [1, 2],
  };

  const HEAVY_KEYS = { planet_breaker: 1, ion_bastion: 1, deep_vault_ark: 1 };

  // Legacy aliases kept for tests / older callers
  const SHIP_PROFILES = {
    spark_drone: "kinetic_light",
    veil_probe: "kinetic_light",
    falcon_interceptor: "laser_mid",
    solar_skiff: "laser_mid",
    mule_courier: "kinetic_light",
    atlas_hauler: "kinetic_light",
    ironclad_frigate: "laser_mid",
    eclipse_runner: "plasma_heavy",
    harvest_reclaimer: "laser_mid",
    seed_ark: "missile",
    deep_vault_ark: "missile",
    planet_breaker: "plasma_heavy",
  };

  const DEFENSE_PROFILES = {
    slug_launcher: "kinetic_light",
    sentinel_turret: "laser_mid",
    plasma_arc: "plasma_heavy",
    ion_bastion: "plasma_heavy",
    flak_array: "flak",
    pulse_barrier: "laser_mid",
    orbital_shield: "missile",
  };

  let _active = null;
  let _fightAudios = [];

  /** One-shot SFX pool — one random clip per salvo (attacker / defender alternating beats). */
  const COMBAT_FIGHT_SOUNDS = [
    "/static/sounds/combat/theater_fight_sound.mp3",
    "/static/sounds/combat/theater_fight_sound_2.mp3",
    "/static/sounds/combat/theater_fight_sound_3.mp3",
  ];
  const COMBAT_FIGHT_BASE_VOLUME = 0.45;
  const COMBAT_PIRATE_DOWN_SOUND = "/static/sounds/combat/piratedown_theater.mp3";
  const COMBAT_PIRATE_DOWN_BASE_VOLUME = 0.55;

  function stopFightSounds() {
    (_fightAudios || []).forEach((audio) => {
      try {
        audio.pause();
        audio.currentTime = 0;
      } catch (_) {}
    });
    _fightAudios = [];
  }

  function playCombatTheaterOneShot(src, baseVolume) {
    try {
      const volume =
        typeof GC.sfxVolumeForKind === "function"
          ? GC.sfxVolumeForKind("combat", baseVolume)
          : baseVolume;
      if (!(volume > 0) || !src) return;
      const audio = new Audio(src);
      audio.volume = volume;
      _fightAudios.push(audio);
      const drop = () => {
        _fightAudios = _fightAudios.filter((a) => a !== audio);
      };
      audio.addEventListener("ended", drop, { once: true });
      const promise = audio.play();
      if (promise && typeof promise.catch === "function") {
        promise.catch(drop);
      }
    } catch (_) {}
  }

  function playFightSalvoSound() {
    const pool = COMBAT_FIGHT_SOUNDS;
    if (!pool.length) return;
    const src = pool[Math.floor(Math.random() * pool.length)];
    playCombatTheaterOneShot(src, COMBAT_FIGHT_BASE_VOLUME);
  }

  function playCombatSoundPreview() {
    playCombatTheaterOneShot(COMBAT_FIGHT_SOUNDS[0], COMBAT_FIGHT_BASE_VOLUME);
  }
  GC.playCombatSoundPreview = playCombatSoundPreview;

  /** Explosion SFX — stop overlapping salvo clips so the wipe is audible. */
  function playPirateDownSound() {
    stopFightSounds();
    playCombatTheaterOneShot(COMBAT_PIRATE_DOWN_SOUND, COMBAT_PIRATE_DOWN_BASE_VOLUME);
  }

  function countWipedClasses(stock, losses) {
    let wiped = 0;
    const before = stock && typeof stock === "object" ? stock : {};
    Object.entries(losses || {}).forEach(([k, v]) => {
      const key = String(k || "").trim();
      if (!key) return;
      const loss = Math.max(0, Math.trunc(Number(v) || 0));
      if (!loss) return;
      const prev = Math.max(0, Math.trunc(Number(before[key]) || 0));
      if (prev > 0 && prev - loss <= 0) wiped += 1;
    });
    return wiped;
  }

  /** True when this resolve empties an entire stock (fleet/defense line wiped). */
  function stockWipedByLosses(stock, losses) {
    const before = unitCountTotal(stock);
    if (before <= 0) return false;
    return unitCountTotal(applyLosses(stock, losses)) <= 0;
  }

  function shouldPlayPirateDown(meta, evt, shipLoss, defLossMap) {
    const wipedClasses =
      countWipedClasses(meta._liveAtk, evt.attacker_losses) +
      countWipedClasses(meta._liveDefShips, shipLoss) +
      countWipedClasses(meta._liveDefDefense, defLossMap);
    if (wipedClasses > 0) return true;
    if (stockWipedByLosses(meta._liveAtk, evt.attacker_losses)) return true;
    const defBefore =
      unitCountTotal(meta._liveDefShips) + unitCountTotal(meta._liveDefDefense);
    if (defBefore <= 0) return false;
    const defAfter =
      unitCountTotal(applyLosses(meta._liveDefShips, shipLoss)) +
      unitCountTotal(applyLosses(meta._liveDefDefense, defLossMap));
    return defAfter <= 0;
  }

  function t(key, fallback) {
    if (typeof GC.t === "function") return GC.t(key, fallback);
    return fallback || key;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtInt(n) {
    const v = Math.max(0, Math.trunc(Number(n) || 0));
    if (typeof GC.formatInt === "function") return GC.formatInt(v);
    return String(v);
  }

  function preferWebp(url) {
    return typeof GC.preferWebpStaticUrl === "function" ? GC.preferWebpStaticUrl(url) : url;
  }

  function shipBattleIconUrl(key) {
    if (typeof GC.shipBattleIconUrl === "function") return GC.shipBattleIconUrl(key);
    const k = String(key || "").trim();
    return preferWebp(`/static/img/ships/cutout/${k}.png`);
  }

  function defenseBattleIconUrl(key) {
    if (typeof GC.defenseBattleIconUrl === "function") return GC.defenseBattleIconUrl(key);
    const k = String(key || "").trim();
    return preferWebp(`/static/img/defense/cutout/${k}.png`);
  }

  function hashSeed(str) {
    let h = 2166136261;
    const s = String(str || "");
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function unitCountTotal(stock) {
    let n = 0;
    Object.values(stock || {}).forEach((v) => {
      n += Math.max(0, Math.trunc(Number(v) || 0));
    });
    return n;
  }

  function cloneStock(stock) {
    const out = {};
    Object.entries(stock || {}).forEach(([k, v]) => {
      const n = Math.max(0, Math.trunc(Number(v) || 0));
      if (n > 0) out[String(k)] = n;
    });
    return out;
  }

  function applyLosses(stock, losses) {
    const out = cloneStock(stock);
    Object.entries(losses || {}).forEach(([k, v]) => {
      const key = String(k);
      const loss = Math.max(0, Math.trunc(Number(v) || 0));
      if (!loss) return;
      const next = Math.max(0, (out[key] || 0) - loss);
      if (next > 0) out[key] = next;
      else delete out[key];
    });
    return out;
  }

  function topEntries(stock, limit) {
    return Object.entries(stock || {})
      .map(([k, v]) => [String(k), Math.max(0, Math.trunc(Number(v) || 0))])
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, limit);
  }

  function profileForShip(key) {
    return SHIP_PROFILES[String(key || "").trim()] || "laser_mid";
  }

  function profileForDefense(key) {
    return DEFENSE_PROFILES[String(key || "").trim()] || "laser_mid";
  }

  function profileForUnit(key, kind) {
    return kind === "defense" ? profileForDefense(key) : profileForShip(key);
  }

  function projectileSignature(key, kind) {
    const k = String(key || "").trim();
    if (kind === "defense") return DEFENSE_SIGNATURES[k] || "laser_mid";
    if (DEFENSE_SIGNATURES[k] && !SHIP_SIGNATURES[k]) return DEFENSE_SIGNATURES[k];
    return SHIP_SIGNATURES[k] || "laser_mid";
  }

  function boltBurstFor(key) {
    const range = BOLT_BURST[String(key || "").trim()] || [2, 3];
    return range;
  }

  function dominantProfile(entries, kind) {
    if (!entries.length) return kind === "defense" ? "flak" : "laser_mid";
    return profileForUnit(entries[0][0], kind);
  }

  function salvoCountForRound(seed, roundIndex, lossTotal) {
    const h = hashSeed(`${seed}:r${roundIndex}`);
    if (lossTotal >= 40) return 3;
    return h % 2 === 0 ? 2 : 3;
  }

  function actorLabel(name) {
    const n = String(name || "").trim();
    return n || "—";
  }

  // Beat timing — deliberate fire exchange, not a flash. User must click for report.
  const BEAT = {
    intro: 650,
    roundAnnounce: 500,
    salvoGap: 820,
    sideSwitch: 420,
    resolveHold: 1100,
    roundGap: 450,
  };

  function buildTimeline(meta) {
    const safe = meta && typeof meta === "object" ? meta : {};
    const seed = String(safe.fleet_id || safe.target_coords || safe.attacker_id || "combat");
    const rounds = Array.isArray(safe.rounds) ? safe.rounds : [];
    const events = [];
    let tMs = 0;

    events.push({ type: "intro", at: tMs });
    tMs += BEAT.intro;

    if (!rounds.length) {
      events.push({ type: "finale", at: tMs, winner: safe.winner || safe.result || "undecided" });
      return events;
    }

    rounds.forEach((rnd, idx) => {
      const n = Math.max(1, Math.trunc(Number(rnd.number) || idx + 1));
      const atkLoss = unitCountTotal(rnd.attacker_losses);
      const defLoss = unitCountTotal(rnd.defender_losses);
      const salvos = salvoCountForRound(seed, n, atkLoss + defLoss);

      events.push({ type: "round_start", at: tMs, round: n, salvos });
      tMs += BEAT.roundAnnounce;

      for (let s = 0; s < salvos; s++) {
        events.push({
          type: "salvo",
          at: tMs,
          side: "attacker",
          index: s,
          salvos,
          round: n,
        });
        tMs += BEAT.salvoGap;
      }
      tMs += BEAT.sideSwitch;
      for (let s = 0; s < salvos; s++) {
        events.push({
          type: "salvo",
          at: tMs,
          side: "defender",
          index: s,
          salvos,
          round: n,
        });
        tMs += BEAT.salvoGap;
      }

      events.push({
        type: "resolve",
        at: tMs,
        round: n,
        attacker_losses: rnd.attacker_losses || {},
        defender_losses: rnd.defender_losses || {},
        heavy: atkLoss + defLoss >= 40,
      });
      tMs += BEAT.resolveHold;
      tMs += BEAT.roundGap;
    });

    events.push({
      type: "finale",
      at: tMs,
      winner: safe.winner || safe.result || "undecided",
    });
    return events;
  }

  function fmtCompact(n) {
    const v = Math.max(0, Math.trunc(Number(n) || 0));
    if (typeof GC.formatNumberCompact === "function") return GC.formatNumberCompact(v);
    if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e4) return `${(v / 1e3).toFixed(1)}K`;
    return fmtInt(v);
  }

  function slotHtml(key, count, kind, rank) {
    const png =
      kind === "defense"
        ? `/static/img/defense/cutout/${encodeURIComponent(key)}.png`
        : `/static/img/ships/cutout/${encodeURIComponent(key)}.png`;
    const webp = preferWebp(png);
    const fallback =
      kind === "defense"
        ? `/static/img/defense/${encodeURIComponent(key)}.png`
        : `/static/img/ships/${encodeURIComponent(key)}.png`;
    const rankClass =
      rank === 0 ? " is-flagship" : rank === 1 ? " is-wing" : " is-escort";
    const cls =
      (kind === "defense" ? "gc-ct-slot gc-ct-slot--defense" : "gc-ct-slot gc-ct-slot--ship") +
      rankClass;
    return (
      `<div class="${cls}" data-ct-slot data-unit-key="${esc(key)}" data-unit-kind="${esc(kind)}" data-unit-count="${count}" style="--ct-rank:${rank}">` +
      `<div class="gc-ct-slot-glow" aria-hidden="true"></div>` +
      `<picture>` +
      `<source type="image/webp" srcset="${esc(webp)}">` +
      `<img class="gc-ct-slot-img" src="${esc(png)}" alt="" width="120" height="80" loading="eager" ` +
      `onerror="this.onerror=null;this.src='${esc(fallback)}';">` +
      `</picture>` +
      `<span class="gc-ct-slot-count gc-mono" title="×${esc(fmtInt(count))}">×${esc(fmtCompact(count))}</span>` +
      `<span class="gc-ct-muzzle" aria-hidden="true"></span>` +
      `</div>`
    );
  }

  function formationHtml(stock, kind, limit) {
    const entries = topEntries(stock, limit);
    if (!entries.length) return "";
    return entries.map(([k, c], i) => slotHtml(k, c, kind, i)).join("");
  }

  function renderStage(meta) {
    const safe = meta && typeof meta === "object" ? meta : {};
    const kind = String(safe.combat_kind || "").trim().toLowerCase();
    const atk = cloneStock(safe.attacking_ships);
    const defShips = cloneStock(safe.defending_ships);
    const defDefense = cloneStock(safe.defending_defense);
    const hasDefense = unitCountTotal(defDefense) > 0;
    const vs = t("combat_report_vs", "%(attacker)s vs %(defender)s")
      .replace("%(attacker)s", actorLabel(safe.attacker_name))
      .replace("%(defender)s", actorLabel(safe.defender_name));
    const place = String(safe.target_coords || "").trim();
    const pirateClass = kind === "pirate" ? " is-pirate" : "";
    const stars = Array.from({ length: 28 }, (_, i) => {
      const x = ((i * 37) % 97) + 1;
      const y = ((i * 53) % 89) + 1;
      const s = 1 + (i % 3);
      return `<span class="gc-ct-star" style="--x:${x}%;--y:${y}%;--s:${s}px;--d:${(i % 7) * 0.4}s"></span>`;
    }).join("");

    return (
      `<div class="gc-combat-theater${pirateClass}" data-ct-stage data-ct-playing="1">` +
      `<div class="gc-ct-toolbar">` +
      `<div class="gc-ct-toolbar-left">` +
      `<span class="gc-ct-live-pip" aria-hidden="true"></span>` +
      `<span class="gc-ct-round-label gc-mono" data-ct-round-label>${esc(
        t("combat_theater_engaging", "Engaging…")
      )}</span>` +
      `</div>` +
      `<div class="gc-ct-toolbar-actions">` +
      `<button type="button" class="gc-btn gc-btn-ghost gc-btn-xs" data-ct-skip>${esc(
        t("combat_theater_skip", "Skip")
      )}</button>` +
      `</div>` +
      `</div>` +
      `<div class="gc-ct-arena" data-ct-arena>` +
      `<div class="gc-ct-backdrop" aria-hidden="true">` +
      `<div class="gc-ct-nebula gc-ct-nebula--a"></div>` +
      `<div class="gc-ct-nebula gc-ct-nebula--b"></div>` +
      `<div class="gc-ct-stars">${stars}</div>` +
      `<div class="gc-ct-horizon"></div>` +
      `<div class="gc-ct-planet"></div>` +
      `<div class="gc-ct-grid"></div>` +
      `<div class="gc-ct-vignette"></div>` +
      `<div class="gc-ct-scanlines"></div>` +
      `</div>` +
      `<div class="gc-ct-fx" aria-hidden="true">` +
      Array.from({ length: 14 }, (_, i) => `<span class="gc-ct-particle" style="--i:${i}"></span>`).join("") +
      `</div>` +
      `<div class="gc-ct-flash" data-ct-flash aria-hidden="true"></div>` +
      `<div class="gc-ct-side gc-ct-side--attacker" data-ct-side="attacker">` +
      `<div class="gc-ct-side-meta">` +
      `<div class="gc-ct-side-label">${esc(t("combat_theater_attacker", "Attacker"))}</div>` +
      `<div class="gc-ct-name">${esc(actorLabel(safe.attacker_name))}</div>` +
      `</div>` +
      `<div class="gc-ct-formation" data-ct-formation="attacker" data-ct-ships>${formationHtml(
        atk,
        "ship",
        4
      )}</div>` +
      `<div class="gc-ct-dmg" data-ct-dmg="attacker" aria-hidden="true"></div>` +
      `</div>` +
      `<div class="gc-ct-vs" aria-hidden="true">` +
      `<div class="gc-ct-rift"></div>` +
      `<span class="gc-ct-vs-badge">VS</span>` +
      (place ? `<span class="gc-ct-vs-place gc-mono">${esc(place)}</span>` : "") +
      `</div>` +
      `<div class="gc-ct-side gc-ct-side--defender" data-ct-side="defender">` +
      `<div class="gc-ct-side-meta">` +
      `<div class="gc-ct-side-label">${esc(t("combat_theater_defender", "Defender"))}</div>` +
      `<div class="gc-ct-name">${esc(actorLabel(safe.defender_name))}</div>` +
      `</div>` +
      `<div class="gc-ct-formation" data-ct-formation="defender" data-ct-ships>${formationHtml(
        defShips,
        "ship",
        4
      )}</div>` +
      `<div class="gc-ct-formation gc-ct-formation--defense${hasDefense ? "" : " is-empty"}" data-ct-formation="defense" data-ct-defense>${formationHtml(
        defDefense,
        "defense",
        4
      )}</div>` +
      `<div class="gc-ct-dmg" data-ct-dmg="defender" aria-hidden="true"></div>` +
      `</div>` +
      `<div class="gc-ct-projectiles" data-ct-projectiles aria-hidden="true"></div>` +
      `</div>` +
      `<p class="gc-ct-caption">${esc(vs)}</p>` +
      `<div class="gc-ct-finale" data-ct-finale hidden></div>` +
      `</div>`
    );
  }

  function updateFormation(root, side, stock, kind, limit) {
    const sel =
      side === "defense"
        ? '[data-ct-formation="defense"]'
        : `[data-ct-formation="${side}"]`;
    const mount = root.querySelector(sel);
    if (!mount) return;
    mount.innerHTML = formationHtml(stock, kind, limit);
    if (side === "defense") {
      mount.classList.toggle("is-empty", unitCountTotal(stock) <= 0);
    }
  }

  function fireSalvo(root, side, meta, salvoIndex) {
    const projMount = root.querySelector("[data-ct-projectiles]");
    const arena = root.querySelector("[data-ct-arena]");
    if (!projMount || !arena) return;
    playFightSalvoSound();

    const shipForm = root.querySelector(
      side === "attacker" ? '[data-ct-formation="attacker"]' : '[data-ct-formation="defender"]'
    );
    const defForm = side === "defender" ? root.querySelector('[data-ct-formation="defense"]') : null;
    const slots = [];
    if (shipForm) slots.push(...shipForm.querySelectorAll("[data-ct-slot]"));
    if (defForm) slots.push(...defForm.querySelectorAll("[data-ct-slot]"));

    const stageRect = arena.getBoundingClientRect();
    const targetLeft = side === "attacker" ? 76 : 24;
    let anyHeavy = false;
    let boltOrdinal = 0;

    const fireFromSlot = (slot) => {
      const key = String(slot.getAttribute("data-unit-key") || "").trim();
      const kind = String(slot.getAttribute("data-unit-kind") || "ship").trim() || "ship";
      const sig = projectileSignature(key, kind);
      const [lo, hi] = boltBurstFor(key);
      const count = lo + ((salvoIndex + boltOrdinal) % Math.max(1, hi - lo + 1));
      if (HEAVY_KEYS[key]) anyHeavy = true;

      let origin = { left: side === "attacker" ? 22 : 78, top: 42 };
      if (stageRect.width > 0 && stageRect.height > 0) {
        const r = slot.getBoundingClientRect();
        origin = {
          left: ((r.left + r.width / 2 - stageRect.left) / stageRect.width) * 100,
          top: ((r.top + r.height / 2 - stageRect.top) / stageRect.height) * 100,
        };
      }

      for (let i = 0; i < count; i++) {
        const el = document.createElement("span");
        el.className =
          `gc-ct-projectile gc-ct-bolt gc-ct-bolt--${sig} is-flying` +
          (side === "defender" ? " is-from-defender" : "");
        el.style.setProperty("--ct-x0", `${origin.left}%`);
        el.style.setProperty("--ct-y0", `${origin.top}%`);
        el.style.setProperty("--ct-x1", `${targetLeft + (i % 5) * 2.5 - 5}%`);
        el.style.setProperty("--ct-y1", `${30 + (i % 5) * 9}%`);
        el.style.animationDelay = `${boltOrdinal * 28 + i * 40 + salvoIndex * 25}ms`;
        projMount.appendChild(el);

        if (sig === "falcon_interceptor" || sig === "solar_skiff" || sig === "ion_bastion") {
          const twin = document.createElement("span");
          twin.className = el.className + " is-twin";
          twin.style.setProperty("--ct-x0", `${origin.left}%`);
          twin.style.setProperty("--ct-y0", `${origin.top + 2}%`);
          twin.style.setProperty("--ct-x1", `${targetLeft + (i % 5) * 2.5 - 3}%`);
          twin.style.setProperty("--ct-y1", `${32 + (i % 5) * 9}%`);
          twin.style.animationDelay = `${boltOrdinal * 28 + i * 40 + 30 + salvoIndex * 25}ms`;
          projMount.appendChild(twin);
        }
      }

      slot.classList.add("is-firing");
      slot.setAttribute("data-ct-bolt", sig);
      setTimeout(() => {
        slot.classList.remove("is-firing");
        slot.removeAttribute("data-ct-bolt");
      }, 320 + boltOrdinal * 20);
      boltOrdinal += 1;
    };

    if (slots.length) {
      slots.forEach((slot) => fireFromSlot(slot));
    } else {
      const fallbackKey = side === "attacker" ? "falcon_interceptor" : "spark_drone";
      for (let i = 0; i < 4; i++) {
        const el = document.createElement("span");
        const sig = projectileSignature(fallbackKey, "ship");
        el.className =
          `gc-ct-projectile gc-ct-bolt gc-ct-bolt--${sig} is-flying` +
          (side === "defender" ? " is-from-defender" : "");
        el.style.setProperty("--ct-x0", `${side === "attacker" ? 20 + i * 6 : 80 - i * 6}%`);
        el.style.setProperty("--ct-y0", `${38 + (i % 2) * 10}%`);
        el.style.setProperty("--ct-x1", `${targetLeft}%`);
        el.style.setProperty("--ct-y1", `${40 + i * 4}%`);
        el.style.animationDelay = `${i * 40}ms`;
        projMount.appendChild(el);
      }
    }

    arena.classList.add("is-firing");
    setTimeout(() => arena.classList.remove("is-firing"), 700);

    const targetSide = side === "attacker" ? "defender" : "attacker";
    const hitEl = root.querySelector(`[data-ct-side="${targetSide}"]`);
    if (hitEl) {
      hitEl.classList.add("is-hit");
      const impact = document.createElement("span");
      impact.className = "gc-ct-impact";
      hitEl.appendChild(impact);
      setTimeout(() => {
        hitEl.classList.remove("is-hit");
        impact.remove();
      }, 520);
    }
    const flash = root.querySelector("[data-ct-flash]");
    if (flash) {
      flash.classList.remove("is-on", "is-heavy");
      void flash.offsetWidth;
      flash.classList.add("is-on", side === "attacker" ? "from-atk" : "from-def");
      if (anyHeavy) flash.classList.add("is-heavy");
      setTimeout(() => flash.classList.remove("is-on", "from-atk", "from-def", "is-heavy"), 400);
    }

    if (shipForm) shipForm.classList.add("is-lunging");
    if (defForm && side === "defender") defForm.classList.add("is-lunging");
    setTimeout(() => {
      if (shipForm) shipForm.classList.remove("is-lunging");
      if (defForm) defForm.classList.remove("is-lunging");
    }, 620);
  }

  function showResolve(root, meta, evt) {
    const atkLoss = unitCountTotal(evt.attacker_losses);
    const defLoss = unitCountTotal(evt.defender_losses);
    const atkMount = root.querySelector('[data-ct-dmg="attacker"]');
    const defMount = root.querySelector('[data-ct-dmg="defender"]');
    if (atkMount) {
      atkMount.innerHTML =
        atkLoss > 0
          ? `<span class="gc-ct-dmg-num">−${esc(fmtCompact(atkLoss))}</span>` +
            (evt.heavy ? `<span class="gc-ct-dmg-heavy">${esc(t("combat_theater_heavy", "HEAVY"))}</span>` : "")
          : "";
    }
    if (defMount) {
      defMount.innerHTML =
        defLoss > 0
          ? `<span class="gc-ct-dmg-num">−${esc(fmtCompact(defLoss))}</span>` +
            (evt.heavy ? `<span class="gc-ct-dmg-heavy">${esc(t("combat_theater_heavy", "HEAVY"))}</span>` : "")
          : "";
    }

    const shipLoss = {};
    const defLossMap = {};
    Object.entries(evt.defender_losses || {}).forEach(([k, v]) => {
      if (Object.prototype.hasOwnProperty.call(meta._liveDefDefense, k) || DEFENSE_PROFILES[k]) {
        defLossMap[k] = v;
      } else {
        shipLoss[k] = v;
      }
    });

    // Wipe / fleet-defeat SFX before applying losses (stock still has pre-resolve counts).
    if (shouldPlayPirateDown(meta, evt, shipLoss, defLossMap)) {
      playPirateDownSound();
      meta._pirateDownPlayed = true;
    }

    meta._liveAtk = applyLosses(meta._liveAtk, evt.attacker_losses);
    meta._liveDefShips = applyLosses(meta._liveDefShips, shipLoss);
    meta._liveDefDefense = applyLosses(meta._liveDefDefense, defLossMap);

    updateFormation(root, "attacker", meta._liveAtk, "ship", 4);
    updateFormation(root, "defender", meta._liveDefShips, "ship", 4);
    const defMountForm = root.querySelector('[data-ct-formation="defense"]');
    updateFormation(root, "defense", meta._liveDefDefense, "defense", 4);
    if (defMountForm) {
      defMountForm.classList.toggle("is-empty", unitCountTotal(meta._liveDefDefense) <= 0);
    }

    const arena = root.querySelector("[data-ct-arena]");
    if (arena) {
      arena.classList.add("is-resolve");
      if (evt.heavy) arena.classList.add("is-shake");
    }
    setTimeout(() => {
      if (arena) arena.classList.remove("is-resolve", "is-shake");
      const proj = root.querySelector("[data-ct-projectiles]");
      if (proj) proj.innerHTML = "";
    }, 780);
  }

  function showFinale(root, meta, winner) {
    const el = root.querySelector("[data-ct-finale]");
    if (!el) return;
    // Safety net: if a side was emptied but no mid-resolve wipe fired (edge timelines).
    if (meta && !meta._pirateDownPlayed) {
      const atkEmpty = unitCountTotal(meta._liveAtk) <= 0;
      const defEmpty =
        unitCountTotal(meta._liveDefShips) + unitCountTotal(meta._liveDefDefense) <= 0;
      if (atkEmpty || defEmpty) {
        playPirateDownSound();
        meta._pirateDownPlayed = true;
      }
    }
    const w = String(winner || "").toLowerCase();
    let label = t("combat_report_winner_undecided", "Outcome pending");
    let cls = "is-draw";
    if (w === "attacker" || w === "attacker_win" || w === "victory") {
      label = t("combat_report_winner_attacker", "Victory: Attacker");
      cls = "is-attacker";
    } else if (w === "defender" || w === "defender_win" || w === "defeat") {
      label = t("combat_report_winner_defender", "Victory: Defender");
      cls = "is-defender";
    } else if (w === "draw") {
      label = t("combat_report_winner_draw", "Draw");
      cls = "is-draw";
    }
    el.hidden = false;
    el.className = `gc-ct-finale ${cls}`;
    el.innerHTML =
      `<div class="gc-ct-finale-label">${esc(label)}</div>` +
      `<button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-ct-open-report>${esc(
        t("combat_theater_open_report", "Open report")
      )}</button>` +
      `<button type="button" class="gc-btn gc-btn-ghost gc-btn-xs" data-ct-replay>${esc(
        t("combat_theater_replay", "Replay")
      )}</button>`;
    root.classList.add("is-finale");
    root.setAttribute("data-ct-playing", "0");
  }

  function reducedMotion() {
    try {
      return !!(global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (_) {
      return false;
    }
  }

  function stop() {
    stopFightSounds();
    if (!_active) return;
    (_active.timers || []).forEach((id) => clearTimeout(id));
    if (_active.abort) _active.abort();
    _active = null;
  }

  function revealReport(wrap) {
    if (!wrap) return;
    const stage = wrap.querySelector("[data-ct-stage]");
    const report = wrap.querySelector("[data-ct-report]");
    if (stage) {
      stage.hidden = true;
      stage.setAttribute("data-ct-playing", "0");
    }
    if (report) report.hidden = false;
  }

  function keepTheaterVisible(wrap) {
    const stage = wrap.querySelector("[data-ct-stage]");
    const report = wrap.querySelector("[data-ct-report]");
    if (stage) stage.hidden = false;
    if (report) report.hidden = true;
  }

  function playOn(wrap, meta, opts) {
    stop();
    const options = opts || {};
    const safe = meta && typeof meta === "object" ? meta : {};
    const host = wrap.querySelector("[data-ct-host]");
    const report = wrap.querySelector("[data-ct-report]");
    if (!host) {
      if (typeof options.onComplete === "function") options.onComplete();
      return;
    }

    const liveMeta = {
      ...safe,
      _liveAtk: cloneStock(safe.attacking_ships),
      _liveDefShips: cloneStock(safe.defending_ships),
      _liveDefDefense: cloneStock(safe.defending_defense),
    };

    host.innerHTML = renderStage(safe);
    const root = host.querySelector("[data-ct-stage]");
    if (report) report.hidden = true;

    const finish = (mode) => {
      stop();
      if (mode === "reveal") {
        revealReport(wrap);
      }
      if (typeof options.onComplete === "function") options.onComplete(mode);
    };

    const skipBtn = root && root.querySelector("[data-ct-skip]");
    if (skipBtn) {
      skipBtn.addEventListener("click", () => finish("reveal"));
    }

    root?.addEventListener("click", (e) => {
      const openBtn = e.target.closest("[data-ct-open-report]");
      if (openBtn) {
        finish("reveal");
        return;
      }
      const replayBtn = e.target.closest("[data-ct-replay]");
      if (replayBtn) {
        keepTheaterVisible(wrap);
        playOn(wrap, safe, options);
      }
    });

    if (options.skip) {
      showFinale(root, liveMeta, safe.winner || safe.result);
      finish("reveal");
      return;
    }

    if (reducedMotion()) {
      // Still require an explicit click — no auto-jump to the report.
      showFinale(root, liveMeta, safe.winner || safe.result);
      _active = { timers: [], abort: null };
      return;
    }

    const timeline = buildTimeline(safe);
    const timers = [];
    const later = (fn, ms) => {
      const id = setTimeout(fn, ms);
      timers.push(id);
      return id;
    };

    timeline.forEach((evt) => {
      later(() => {
        if (!_active) return;
        const label = root.querySelector("[data-ct-round-label]");
        if (evt.type === "round_start" && label) {
          label.textContent = t("combat_theater_round", "Round %(n)s").replace(
            "%(n)s",
            fmtInt(evt.round)
          );
        }
        if (evt.type === "intro") {
          root.querySelectorAll("[data-ct-formation]").forEach((f) => f.classList.add("is-lunging"));
          later(() => {
            root.querySelectorAll("[data-ct-formation]").forEach((f) => f.classList.remove("is-lunging"));
          }, 360);
        }
        if (evt.type === "salvo") {
          fireSalvo(root, evt.side, liveMeta, evt.index || 0);
        }
        if (evt.type === "resolve") {
          showResolve(root, liveMeta, evt);
        }
        if (evt.type === "finale") {
          // Stay on theater until the player opens the report (or skips).
          showFinale(root, liveMeta, evt.winner);
        }
      }, evt.at);
    });

    _active = {
      timers,
      abort: () => {},
    };

    if (typeof GC.registerCleanup === "function") {
      GC.registerCleanup(() => stop());
    }
  }

  function mountAndPlay(contentEl, meta, opts) {
    if (!contentEl) return;
    let wrap = contentEl.querySelector("[data-ct-wrap]");
    if (!wrap) {
      // Legacy: content is report only
      if (typeof (opts || {}).onComplete === "function") (opts || {}).onComplete("reveal");
      return;
    }
    playOn(wrap, meta, opts);
  }

  GC.combatTheater = {
    buildTimeline,
    profileForUnit,
    profileForShip,
    profileForDefense,
    projectileSignature,
    mountAndPlay,
    playOn,
    stop,
    revealReport,
    renderStage,
  };
})(typeof window !== "undefined" ? window : globalThis);
