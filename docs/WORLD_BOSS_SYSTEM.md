# World Boss System — Genesis Colonies

Server-wide PvE bosses: shared HP, multi-player contribution, exclusive meta rewards, recurring LiveOps windows.

**Status:** ✅ EPIC-20 (GC-W01…GC-W08) · 🔄 Encounter Stage · ✅ GC-WB-TAME (Catch + Companions)  
**Owner:** `game/world_boss.py` (+ companions helper `game/world_boss_companions.py`)  
**Epic:** EPIC-20 — World Boss Events

---

## Architecture (GC-000)

| Concern | Owner | Notes |
|---------|--------|--------|
| Event state, HP, schedule, contribution, claims, **instant attack** | `game/world_boss.py` | Single domain owner |
| Catch / tame, ownership, companion missions | `game/world_boss_companions.py` | EPIC-20 subdomain — **no** combat/fleet math |
| Legacy fleet arrival resolve | `game/fleet.py` | Outbound WB sends **blocked** (`use_world_boss_attack`); arrival path kept for in-flight leftovers |
| World-native target type | `game/fleet_target.py` | `world_boss` in `WORLD_NATIVE_TARGET_TYPES` (galaxy attach) |
| Ship combat stats / research mods | `game/combat.py` + `combat_models` | Instant path reuses stats + EffectResolver mods — **no** second combat engine |
| Galaxy visibility | `game/galaxy.py` | Slot attach like debris |
| Loot pools | `game/inventory_loot.py` | Meta-only (`item` / `booster`) |
| Grants | `game/inventory.py` | `grant_inventory_item` (incl. Ark-Token `story_scrap_token` from missions) |
| Cron spawn/expire (+ auto-attack + mission ready) | `game/fleet_worker.py` piggyback | No module-owned polling |
| Overview landscape hotspots | `game/overview_page.py` + templates | Display-only companions from companions payload |
| Directives | `game/directives/progress.py` | Event kind `world_boss_damage` |
| News | `game/universe_news.py` | `category="EVENT"` |
| Alliance aggregation | `game/alliance.py` + world_boss | Contribution `alliance_id`; Ally XP via `grant_alliance_xp` |

**Forbidden:** expedition pirate ratio combat for bosses; Command Map as live gate; frontend HP math / catch RNG; parallel fleet/combat modules; resource/ship loot boxes; new WB attacks as `fleet_movements`; companion combat/fleet stat buffs; second Ark-Token currency.

---

## Tables

| Table | Role |
|-------|------|
| `world_boss_definitions` | Catalog (key, stacks JSON, max_hp, duration, loot tiers) |
| `world_boss_events` | Active/ended instances (coords, HP, phase, schedule) |
| `world_boss_contributions` | Per player (+ alliance) damage ledger |
| `world_boss_claims` | Idempotent reward claims |
| `player_boss_companions` | One tamed companion per `boss_key` per player |
| `player_boss_catch_state` | Catch attempt CD / counters per boss |
| `player_boss_missions` | Companion mission status (`idle` / `away` / `ready`) + `variant_key` / `fail_chance` / `outcome` |
| `player_boss_capacity` | Shop bonus slots (`bonus_slots`; capacity = min(4, 1 + bonus)) |

---

## Combat contract (instant encounter)

1. Player posts `POST /api/world-boss/attack` with `event_id`, optional `ships`, optional `request_id` / `X-Request-Id`.
2. Server validates cooldown, wave limit, active HP, and that selected ships ⊆ active-planet hangar (**ships are not deducted**).
3. `attack_power` = Σ effective ship attack × qty (`combat_stats_for_ship` + research weapon bonus via EffectResolver).
4. HP damage from prestige score ratio vs current phase stacks (`compute_instant_hp_damage`) with same band as before: even fight ≈ **2%** `max_hp`, soft overkill, hard cap **8%**. Optional crit (`INSTANT_CRIT_CHANCE`).
5. Boss HP reduced atomically (`MAX(0, current_hp - damage)`); never below 0; further attacks blocked when defeated.
6. Contribution + `last_attack_at` updated; `cooldown_until = now + 300`.
7. Response: `{ ok, attack, boss, player, state }` — client animates only; no client damage math.
8. Ally XP = `min(40, damage // 40_000)` via `grant_alliance_xp` when applicable.
9. When HP ≤ 0 → status `defeated`; rewards unlock. On `ends_at` with HP > 0 → `expired`.

### Legacy arrival path

`resolve_attack_arrival` + `simulate_battle` remain for any pre-cutover outbound movements. New sends via `send_fleet` with `target_type=world_boss` return `use_world_boss_attack`.

### Anti-farm

| Rule | Default |
|------|---------|
| Account cooldown between waves | 300 s — starts on **instant attack** |
| Max waves per player per event | 40 |
| Even-fight strike HP | ~2% of `max_hp` (`WAVE_HP_FRACTION`) |
| Overkill scaling | `1 + 0.15 × log2(max(1, attacker_score / wave_score))` |
| Cap HP per wave | 8% of `max_hp` (`MAX_WAVE_HP_FRACTION`) |
| Ship losses | **None** (Community DPS; hangar unchanged) |
| Contribution | Server-only; never client-reported |

---

## Rewards

Claim once per player after `defeated` or `expired` (if contribution > 0).
Participate / discoverer / top10 bonus use the boss definition `loot_pool_key`
(e.g. Leviathan → Event-Container, Void Titan → Void-Artefakt, Nexus → Antikes Relikt).

| Tier | Condition | Grant |
|------|-----------|--------|
| `participate` | any contribution | `loot_pool_key` ×2 |
| `top10` | top 10% by damage | `container_void_artifact` ×1 + `loot_pool_key` ×1 |
| `top1` | rank 1 | `container_mythic` ×1 |
| `alliance_top` | member of #1 alliance by sum damage | `container_ancient_relic` ×1 |
| `discoverer` | Expo-Finder (must also deal damage) | `loot_pool_key` ×1 extra |

Same item keys stack. Each World Boss card shows:
- **`reward_outlook`** — concrete grants for this player (`claimable` / `projected` / `claimed`) so UI can show “Deine Belohnung”
- **`rewards_preview`** — full tier catalog with `earned` flags for reached tiers, including the Ally-XP rule (`+1 / 40k damage`, max 40 / wave)

Auction/vote remain free of event inflation.

Expo discovery ≈ **5.5%** per expedition resolve when under the concurrent cap; spawn is server-wide for everyone.

---

## Catch & companions (GC-WB-TAME)

Meta retention loop: **fight → HP Phase 3 → tame attempt → Overview companion → mission → Ark-Token** (Free Shop). Companions are **flavor + missions only** — no combat/fleet bonuses.

| Rule | Value |
|------|--------|
| Catch gate | Event `active` + UI phase **3** (≤25% HP) + free companion capacity |
| Catch chance | **10%** (server RNG only) |
| Catch cost | **10h Timekeeper** (`36000` sec) via `timekeeper.debit` |
| Catch cooldown | **1h** between attempts (independent of attack CD) |
| Ownership | **1** companion per `boss_key`; **capacity** starts at **1**, Shop SKU `titan_slot_plus` +1 (max **4**) |
| Mission picks | Always **3** variants: `patrol` (2h, 10% fail), `strike` (4h, 25% fail), `void_run` (8h, 40% fail) |
| Mission reward | `base (2–4) + (capacity - 1) + variant_bonus` Ark-Token (`story_scrap_token`); fail grants **0** |
| Concurrent missions | 1 per companion (up to capacity) |

### Catch contract

1. `POST /api/world-boss/catch` with `event_id` (+ optional `request_id`).
2. Server validates phase 3, not owned, catch CD free, TK ≥ 10h.
3. Debit TK → record attempt/CD → roll 10%.
4. On success: insert `player_boss_companions` + idle mission row → event status **`tamed`** (HP 0, removed from live galaxy/auto-attack) → **auto-claim** contribution rewards for every damage participant → news banner.
5. Response `{ ok, catch, state }` — UI toasts; no client RNG. Manual `/api/world-boss/claim` remains for defeat/expire leftover cases (`already_claimed` after tame payout).

### Mission contract

1. Overview hotspot / `POST /api/world-boss/companion/mission` with `action=start|claim`, `boss_key`, optional `variant_key`.
2. Idle companions always expose `mission_offers` (3 server-authored picks).
3. Start: owned + idle + valid variant → `away` until `ends_at` (stores `fail_chance`).
4. Worker (`tick_companion_missions`) rolls success/fail once, marks `away` → `ready` with `outcome`.
5. Claim grants Ark-Token on success (0 on fail), resets to `idle`. Starting again auto-claims if `ready`.
6. Due missions resolve on live-state refresh + `action=sync` (countdown zero) — not only the 60s fleet_worker tick.

Overview: landscape hotspots on `#overview-planet-hero` (locked silhouettes + owned companions); popover shows flavor stats + **3 mission cards**. Encounter: Attack / Auto / Catch share one action row.

---

## Schedule

- Up to **3** concurrent `active` events (distinct `boss_key`).
- Active bosses never share the same `[G:S:P]` — auto-pick skips occupied boss slots; explicit coords return `coords_occupied`.
- Cron (`fleet_worker`): expire due events; if `active < 3` and ≥ **4 h** since last spawn, weighted spawn (`spawn_weight`).
- Rare **expedition discovery** (~3%) may spawn when under cap.
- Admin: `POST /api/admin/world-boss/spawn` (`force` may exceed cap / replace same key).

Default window: **48 h**; inter-spawn gap: **4 h**.

---

## Catalog keys

| Key | Role |
|-----|------|
| `ancient_leviathan` | High HP tank |
| `void_titan` | Heavy combat stacks |
| `planet_eater` | Dense-system spawn bias |
| `rogue_ai_nexus` | Phase stack swaps |

---

## APIs / UI

| Route | Role |
|-------|------|
| `GET /world-boss` | Encounter stage + contribution board |
| `GET /api/world-boss` | JSON payload |
| `POST /api/world-boss/attack` | Instant strike `{ ok, attack, boss, player, state }` (idempotent via `request_id`) |
| `POST /api/world-boss/auto-attack` | Toggle server auto-attack `{ ok, auto_attack, attack?, boss?, player?, state }` — enable fires immediately when CD free; follow-ups via `fleet_worker` (also on idle-skip) + opportunistic flush on WB page/API load |
| `POST /api/world-boss/claim` | Claim rewards `{ ok, state }` |
| `POST /api/world-boss/catch` | Phase-3 tame attempt `{ ok, catch, state }` |
| `POST /api/world-boss/companion/mission` | Start/claim companion mission `{ ok, mission, state }` |
| `POST /api/admin/world-boss/spawn` | Admin force spawn |
| `GET /api/admin/world-boss` | Admin status + definitions catalog |
| Galaxy system slots | `slot.world_boss` + `has_world_boss`; deep-link → `/world-boss` |

### Admin LiveOps tab

Admin panel tab **World Boss** (`templates/admin_panel.html` + `static/admin.js`):

- Loads `GET /api/admin/world-boss` → `{ ok, event, schedule, definitions }`
- Spawn form posts to existing `POST /api/admin/world-boss/spawn` (`boss_key`, optional G/S/P, `force`, `announce`)
- No second spawn owner — same `spawn_world_boss` path as cron/admin API

Galaxy deep-link: `/world-boss` (encounter). Fleet mission send for `target_type=world_boss` is rejected.

Boss art: `static/img/bosses/{boss_key}.png|.webp` with alpha cutout (fallback `_placeholder.png`); stage glow/phase is CSS `drop-shadow` + aura — no art panel border.

Active event UI: cinematic Encounter Stage (compact floating boss, ambient nebula/particles, HP bar, in-frame V-formation with ship counts + attack FX). Fleet counts live only on formation slots (no duplicate fleet strip). Phase art variants and boss abilities are a follow-up. Sidebar nav pulses via `nav_badges.world_boss` + SSR `WORLD_BOSS_ACTIVE`.

### Idle / Help UX

Payload always includes `schedule`:

| Field | Meaning |
|-------|---------|
| `next_eligible_at` | Earliest next spawn (`last_ended_at + inter_event_cooldown_sec`, or `server_now` if never ended) |
| `spawn_ready` | Cooldown elapsed and no active boss (spawn on next fleet cron tick) |
| `has_active` | Active event currently running |

UI: countdown via `data-countdown-at` when idle; `event.ends_at` countdown when active. Panel `?` opens a help modal (shared HP, attack, boards, rewards, limits, schedule).

---

## Tickets

| Ticket | Focus |
|--------|--------|
| GC-W01…W11 | Original EPIC-20 delivery |
| GC-WB-VISUAL-001 | Encounter Stage layout + CSS phase glow |
| GC-WB-ATTACK-002 | Instant attack contract (no flight / no losses) |
| GC-WB-COMBAT-FX-003 | Formation + projectile / hit FX |
| GC-WB-AUTO-004 | Server-side auto-attack tick |
| GC-WB-REWARD-005 | Collapsible rewards + progress UX |
| GC-WB-TAME-01…06 | Catch schema/API, Encounter CTA, Overview hotspots, missions, i18n/docs |

---

## Tests

`tests/test_world_boss.py` — schema, spawn, instant attack, claim, schedule, admin GET, galaxy UI, HP damage mapping, encounter/nav contracts, `nav_badges.world_boss`.

`tests/test_world_boss_companions.py` — companions schema, Phase-3 catch + TK + CD + once-per-boss, 3 mission variants, success/fail rolls, Ark-Token claim.

---

## Player Article

```yaml
---
codex_id: world_boss
band: III
difficulty: intermediate
estimated_read: 5 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - world_boss_view
related_codex:
  - titans
  - fleet
  - alliance
  - inventory
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: world_boss_view
teaser_key: codex_unlock_world_boss_teaser
---
```

## Quick Help

**World Boss**-Events sind serverweite PvE-Begegnungen: alle Commander teilen sich den Boss, treffen ihn in der Encounter-Stage und sammeln Beitrag für Meta-Belohnungen.

## Summary

Unter `/world-boss` öffnet die **Encounter Stage**: ein aktiver Boss mit gemeinsamer Lebensleiste, Wellen-Angriffen aus deinem Hangar und Boards für persönlichen sowie Allianz-Beitrag. Bosse erscheinen in der Galaxie und bleiben nur für ein LiveOps-Fenster aktiv. Nach Sieg oder Ablauf kannst du Belohnungen claimen — Container und Meta-Items, keine Schiffe und keine Rohstoff-Stacks.

## Why

World Boss verbindet LiveOps, Community-DPS und Meta-Progression. Du kämpfst nicht allein um einen lokalen Slot — der Server teilt ein Event, und dein Beitrag zählt für Ränge, Allianz-XP und Claim-Tiers. Catch und Titan-Companions sind der Retention-Loop danach (eigener Codex-Eintrag).

## How it works

- Öffne **World Boss** in der Navigation oder folge dem Deep-Link aus der Galaxie, wenn ein Boss-Slot sichtbar ist.
- **Angriff:** sofortiger Encounter-Schlag — Schiffe bleiben im Hangar (Community-DPS, keine Verluste auf diesem Pfad). Cooldown und Wellenlimit setzt der Server.
- **Auto-Angriff:** optional serverseitig; der nächste Schlag folgt, wenn der Cooldown frei ist.
- **Beitrag:** Schaden und Ränge pflegt nur der Server; Allianz-Mitglieder aggregieren gemeinsam.
- **Phasen:** die Stage zeigt Phase und Aura — bei kritischer Phase wird **Zähmung** möglich (siehe Titans).
- **Belohnungen:** nach `defeated` oder `expired` (mit Beitrag) claimen — Tiers für Teilnahme, Top-Beiträge, Allianz-Top und Entdecker. Die UI zeigt deine Outlook und den Katalog.
- Idle-State: Countdown bis zum nächsten Spawn-Fenster; Hilfe-Modal erklärt die Stage ohne Formeln.

## Related Systems

- titans
- fleet
- alliance
- inventory
- galaxy

## Commander Tips

- Aktiven Boss früh angreifen — Beitrag und Ränge bauen sich über das Fenster auf.
- Allianz-Beitrag zählt für gemeinsame Tiers; koordiniert Waves, wenn ihr den Ally-Top wollt.
- Entdecker-Bonus braucht Expedition-Fund **und** eigenen Schaden.

## FAQ

**Verliere ich Schiffe beim World-Boss-Angriff?**
Nein — der Instant-Pfad zieht keine Hangar-Verluste. Schiffe werden nur für die Schlagkraft gelesen.

**Wo finde ich den Boss?**
Aktive Events erscheinen in der Galaxie und auf `/world-boss`. Deep-Links führen zur Encounter Stage.

**Wann kann ich belohnen claimen?**
Wenn das Event besiegt oder abgelaufen ist und du Beitrag geleistet hast — oder automatisch nach erfolgreicher Zähmung für alle Schaden-Teilnehmer.

## Discord Summary

**World Boss — serverweite Encounter Stage**

`/world-boss`: gemeinsamer Boss, Instant-Angriffe ohne Hangar-Verlust, Beitragsboards, Claim-Tiers. Galaxie zeigt aktive Slots. Catch/Titans = eigener Codex.

---

## Player Article

```yaml
---
codex_id: titans
band: III
difficulty: intermediate
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - world_boss_view
  - overview
related_codex:
  - world_boss
  - story_ops
  - shop_identity
  - inventory
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: world_boss_view
teaser_key: codex_unlock_titans_teaser
---
```

## Quick Help

**Titans** (Boss-Companions) entstehen durch Zähmung in der World-Boss-Stage. Gezähmte Titans leben auf der Overview — Missionen bringen **Ark-Token** für den Free Shop.

## Summary

Wenn ein World Boss in die kritische Phase fällt, kannst du einen **Catch**-Versuch starten (Timekeeper-Kosten, Chance und Cooldown setzt der Server). Erfolg bindet den Titan an dich: Flavor-Companion ohne Kampf- oder Flottenboni. Auf der **Overview** erscheinen Hotspots und Klick-SFX nur für **deine eigenen** Titans; gesperrte Silhouetten markieren noch nicht gezähmte Bosse. Missionen (Patrouille, Strike, Void Run) laufen serverseitig und zahlen bei Erfolg Ark-Token (`story_scrap_token`) — dieselbe Währung wie Story/Free Shop.

## Why

Titans verlängern den World-Boss-Loop: Fight → Catch → Overview-Präsenz → Mission → Meta-Währung. Sie sind Prestige und Side-Content, kein zweites Combat-System.

## How it works

- **Catch:** nur bei aktivem Event in kritischer Phase, freier Companion-Kapazität und ohne bestehenden Besitz dieses Boss-Keys.
- **Kapazität:** startet niedrig; Shop-SKU kann Slots erweitern (Deckel serverseitig).
- **Overview:** Landschafts-Hotspots + Popover mit Flavor und drei Mission-Karten — Interaktion und SFX nur für **owned** Titans.
- **Missionen:** Start/Claim über Overview oder API; eine Mission pro Companion; Erfolg → Ark-Token, Misserfolg → kein Token.
- Keine Combat-/Fleet-Stat-Buffs durch Companions.

## Related Systems

- world_boss
- story_ops
- shop_identity
- inventory

## Commander Tips

- Catch erst planen, wenn Timekeeper und Kapazität reichen — Fehlversuche starten den Catch-Cooldown.
- Mission-Varianten tauschen Dauer gegen Risiko; längere Runs lohnen sich nur, wenn du Claim-Zeiten einhalten kannst.
- Overview-Hotspots sind kein Galaxie-Kampf — nur Companion-Missionen.

## FAQ

**Geben Titans Kampfboni?**
Nein. Flavor, Overview-Präsenz und Ark-Token-Missionen — keine Weapon-/Fleet-Mods.

**Warum höre ich keinen Klick-SFX auf einem Hotspot?**
SFX und Mission-Popover gelten nur für **gezähmte** Titans. Silhouetten ohne Besitz bleiben locked.

**Wohin mit Ark-Token?**
Free-Shop-Tab unter `/shop` (Story-Owner) — nicht der EUR-Payment-Katalog.

## Discord Summary

**Titans — Companions, Overview, Ark-Token**

World-Boss-Catch → eigener Titan. Overview-Hotspots/SFX nur für owned. Missionen → Ark-Token für Free Shop. Keine Combat-Buffs.
