# Pirate Ecosystem — Living Threat (EPIC-21)

Galaxy Heat, pirate factions/bases, player-like AI raids (Spy→Intel→Attack), Threat/Bounty, galaxy crises, Admin Bot-Log + Kill-Switch.

**Status:** ✅ EPIC-21 shipped (GC-P00…GC-P20) · Phase 2 in progress (GC-P21…GC-P25 living economy + colony destroy)  
**Owner:** `game/pirates/`  
**Epic:** EPIC-21 — Pirate Ecosystem (Living Threat)

---

## Architecture (GC-000)

| Concern | Owner | Notes |
|---------|--------|--------|
| Heat, factions, bases, threat, bounty, brain, intel, action log, kill-switch | `game/pirates/` | Single domain owner |
| Fleet send / attack / spy / recycle | `game/fleet.py` | Same missions as players; target type `pirate_base` for bases |
| World-native target type | `game/fleet_target.py` | `pirate_base` in `WORLD_NATIVE_TARGET_TYPES` |
| Battle math | `game/combat.py` | `simulate_battle()` only |
| Galaxy visibility | `game/galaxy.py` | Slot attach like world boss / asteroids |
| Cron tick | `game/fleet_worker.py` | Piggyback orchestrator — no module polling |
| News / inbox | `game/universe_news.py`, `game/messages.py` | EVENT + combat reports |
| Crisis overlay | `game/galactic_diplomacy/` | Emergency key `pirate_war` (Heat ≥700) |
| Expo skirmish | `game/expedition_events.py` | Ratio combat remains; ambush escalates via `pirates/ambush.py` |
| Admin Bot-Log UI | Admin Control Center + `game/pirates/` | Ops only |

**Forbidden:** second combat/fleet system; Chat/Social bots; frontend heat/combat math; pirate `planets` rows (Expansion Protocol); cheat hangars; live AI without kill-switch + bot log; Command Map as gate.

---

## Design contracts

### Player-like AI (no chat)

Pirates act through canonical player actions only: spy/scout, attack, recycle, hold/return, fleet-save/panic.  
**No** chat, fake PMs, vote farming, or roleplay inbox.

### Fairness

Outbound fleets come from **base opportunity targeting + real home hangar fractions** (living economy). Flight times use `fleet_calc`. No instant jumps, no ignore-defense. Soft-On stocks a **utility** hangar (probes/reclaimers/Seed Ark) plus a one-time resource seed — combat ships are produced via shipyard queues, not unlimited cheat restock.

### Destroy

Destroying a pirate base sets status `destroyed`, frees the galaxy slot, recalls/cancels that base’s outbound raids (fleet-save). Instance is gone until Heat respawns another.

### Kill-Switch

**Default (GC-2611):** once an admin has ever toggled the kill-switch, that `runtime_state` choice always wins (Soft-Off stays available anytime). Before any admin choice, the default follows `is_production()` — a freshly deployed production universe ships with a living pirate AI without a manual admin click; dev/staging stays off by default.

| Mode | Behavior |
|------|----------|
| Soft-Off (`pirates_ai_enabled=0`) | No new spawns, spies, or raids |
| Soft-On | Enables AI **and** bootstraps all 4 faction bots + home fleets (`bots_bootstrapped` log) |
| Hard-Off | Soft-Off + recall pending pirate outbound/holding fleets (`mode=hard` on `/api/admin/pirates/ai`) |

Stored in `runtime_state` key `pirates_ai_enabled` (default off until LiveOps enables).

### Admin Bot-Log

Every brain decision (spy, intel score, attack, skip reason, destroy, AI disabled) writes `pirate_action_log`. Admin panel tab **Pirate Bot-Log** (`/api/admin/pirates`, Soft-On/Off via `/api/admin/pirates/ai`, Force Spawn via `/api/admin/pirates/force-spawn`, **Force Tick jetzt** via `/api/admin/pirates/force-tick`, GC-2613): bot roster, live bases, heat top, KPIs (bots/raids/spies/spawns/wars/infiltrations/smugglers/**economy ticks/builds finished**, GC-2611 — derived from existing `pirate_action_log`, no new log system), `pirate_war` chips, action feed, kill-switch controls.

Owner helpers: `game/pirates/admin.py` (`build_admin_pirates_payload`, `admin_set_ai`, `admin_hard_disable_ai`, `admin_force_spawn_hottest`, `admin_force_tick`).

**Force Tick jetzt (GC-2613):** calls the same `maybe_tick_pirate_bases` owner the fleet-worker cron uses (`force=True` semantics via direct call, no cadence guard) — economy for ALL bots + one round-robin strategic-mission batch execute immediately. Needed because `embedded_cron` is off by default outside production (`game.config.is_embedded_cron_enabled`), so nothing ticks the bots locally without it.

### Living bots (GC-P19 / GC-P20)

When AI is on, faction bots participate via canonical fleets:

| Heat | Behavior |
|------|----------|
| Soft-On (any heat) | 4 bots exist in Ranking/Galaxy/PlayerCard with utility hangars (+ Seed Ark) + resource seed |
| ≥150 Patrol | Real `spy` missions from homeworlds → arrival writes `pirate_intel` |
| ≥150 Colonize | Real `colonize` with `seed_ark` to free classic slots (soft cap 3 planets/bot) |
| ≥300 Raids | Attacks from live bases **and** homeworlds using **real hangar fractions** (no template overwrite) |
| ≥150 + debris | Opportunistic `recycle` (max 1/tick) |
| Planet floor | Always ≥1 planet; restore homeworld if wiped (`bot_planet_floor`) |

### Living economy (GC-P21–P23) + player loop (GC-P26–P28)

Owner: `game/auto_empire.py` (enqueue) · `game/pirates/economy.py` (Soft-On seed + wrapper) · `game/pirates/play_loop.py` — Soft-On tick runs `run_play_loop_tick` (one player-like step per bot), then secondary base raids / recycle. Expeditions: `dispatch_expedition_from_home` (canonical `send_fleet`).

| Concern | Behavior |
|---------|----------|
| Bootstrap | One-time resource + fuel seed; **one-time** utility fleet seed (`utility_seeded`); **one-time building floor** (mines/lab/OS) so Soft-On bots produce + score immediately |
| Tick | **Economy for ALL bots every Soft-On tick** (chain enqueue); then Priority missions: spy → raid → colonize → recycle → **expedition** on round-robin ≤3 bots/tick (`GC_PIRATE_PLAY_BOTS_PER_TICK`) |
| Progress | Mines → CC/Lab → OS/Barracks/DF → research gates → ships/defense by personality |
| Timekeeper-Boost (GC-2616) | Defense/Shipyard have no `duration_cap` (real formula) → `_auto_boost_timekeeper` in `game/auto_empire.py` auto-credits 10h Timekeeper when the bot's balance is empty and auto-applies it `mode="max"` right after a successful enqueue — same shared owner as inactive-human autoplay ([INACTIVE_AUTOPLAY.md](INACTIVE_AUTOPLAY.md#live-universe-dauerpräsenz-sichtbare-aktivität-timekeeper-boost-gc-2614-2616)), no parallel speed mechanic |
| Anti-clone variance (GC-2618) | Bots already had a per-faction `personality` (`_personality_for_bot`); the shared `auto_empire.py` now uses it for **build/research pick order** too (`BUILD_PRIORITY_BY_PERSONALITY`/`RESEARCH_PRIORITY_BY_PERSONALITY`, same key sets, different order) and a small deterministic target-level jitter (`_stable_jitter`) — bots with different personalities no longer converge on identical building/tech levels. Standing play-loop ticks (`_run_bot_economy_only`, `run_bot_play_step`) also pass `AUTOPLAY_STANDING_IDLE_CHANCE` so a bot occasionally starts nothing new for a round; direct/test calls to `plan_bot_planet_tick` default to `idle_chance=0` and stay deterministic. See [INACTIVE_AUTOPLAY.md#gc-2618](INACTIVE_AUTOPLAY.md#gc-2618--anti-klon-varianz-accounts-wirken-nicht-mehr-wie-kopien) for the full owner writeup (shared with inactive-human autoplay). |
| Raids | `_raid_fleet_from_hangar` — never `set_planet_ships` template wipe; home raids via play loop |
| Fleet-save | Inbound human attack on AI planet → `panic_recall_faction_fleets` (`inbound_attack`) |

### Colony destroy (GC-P24 / GC-P31)

Moon-analog (no moons in GC): after attacker win + hangar/defense fully wiped + `planet_breaker` in returning fleet + target is **non-homeworld** → `destroy_colony_planet`. Works for **AI and human** colonies. Consumes breaker; AI wipe raises bounty + heat + recolonize cooldown; human wipe logs `colony_destroyed` + threat. Homeworld never destroyable; planet floor keeps AI ≥1 planet.

Force Spawn (admin) bypasses heat gate for LiveOps testing without changing threshold design.

**Temporary pirate bases** (Galaxy `PIRATENBASIS`) still expire/destroy — that is not the bot vanishing.

---

## OGX port notes (playOGX.com_beta)

Port **patterns**, not PHP.

| Port | Skip |
|------|------|
| Spy → intel store → combat from scores | `BotChat`, vote bots, alliance social V2 |
| Personalities + playtime windows | Direct DB fleet inserts / probe top-ups |
| Anti-pile-on + tick budgets | Hardcoded cron tokens |
| Fleet-save / panic | Full dual Alliance stacks |
| Admin run log + dashboard KPIs | Expedition scripted pirates as AI substitute |

---

## Tables

| Table | Role |
|-------|------|
| `galaxy_heat` | Per-galaxy heat 0–1000 |
| `pirate_faction_defs` | Catalog (key, stacks, aggression, lore keys) |
| `pirate_bases` | Live instances (coords, strength, status) |
| `pirate_base_contributions` / `pirate_base_claims` | Destroy rewards |
| `player_threat` | 0–100 threat meter |
| `player_bounty` | Per-faction bounty |
| `pirate_intel` | Spy-derived opportunity scores |
| `pirate_bot_state` | Playtime, personality, next_action |
| `pirate_action_log` | Admin Bot-Log (retention capped) |
| `pirate_infiltrations` | Timed debuffs |
| `smuggler_contacts` | Ephemeral offers |

---

## Heat thresholds (defaults)

| Heat | Effect |
|------|--------|
| 150 | Patrol / scout waves |
| 300 | Raids enabled |
| 500 | Elite fleets |
| 700 | `pirate_war` emergency candidate |
| 1000 | Full pirate war pressure |

Heat sources: combat, expedition finish, asteroid harvest, world-boss damage, colonize — via `record_heat_event(galaxy_id, kind, amount)`.

---

## Factions (v1 + Phase 3)

| Key | Role |
|-----|------|
| `crimson_corsairs` | Fast raiders, high loot, weak base |
| `iron_collective` | Armor, slow, strong base, low loot |
| `void_cult` | Spy/infiltration bias |
| `nomad_swarm` | Many small ships |
| `ash_raiders` | Elite heavy strikes |
| `salt_cartel` | Economy / turtle cartel |

Homes are **distributed** across Galaxy 1 systems `100 / 200 / 300 / 400 / 450 / 480` (not a single campable belt).

Personality + playtime live in `pirate_faction_defs.personality_json` and `pirate_bot_state` (GC-P09).  
Bounty: `player_bounty` rises on base damage/destroy and AI colony wipe; raid brain prefers high-bounty revenge targets (GC-P10 / GC-P29). Galaxy inspector shows viewer bounty for the base’s faction.

### AI visibility (human-facing)

Faction bots (`gc_pirate_*`) are **real player rows** and appear in:

- Ranking (with `is_ai` + AI badge; never shown as inactive)
- Galaxy (distributed homeworlds, AI status chip)
- PlayerCard (`player_mode=ai_pirate`, personality/mode keys, no whisper/message/edit)

Identity owner: `game/pirates/accounts.py` (`get_pirate_ai_profile`, `pirate_ai_profiles_by_ids`, `ensure_bot_planet_floor`).

---

## Tickets

| Ticket | Focus | Status |
|--------|-------|--------|
| GC-P00 | This master doc + CORE/EPICS/ROADMAP | **done** |
| GC-P01 | Schema + package skeleton + AI flag | **done** |
| GC-P02 | Heat hooks + Galaxy Heat UI + News | **done** |
| GC-P03–P05 | Bases spawn / destroy / escalate | **done** |
| GC-P06–P08 | Brain Spy→Intel→Attack + Admin Bot-Log | **done** |
| GC-P09–P10 | Faction content + bounty | **done** |
| GC-P11–P12 | `pirate_war` + diplomacy hooks | **done** |
| GC-P13–P15 | Ambush, infiltration, smugglers, fleet-save | **done** |
| GC-P16–P18 | Directives, LiveOps dashboard, E2E ship-gate | **done** |
| GC-P19 | Living bots: Soft-On bootstrap, patrol spy, home raids, recycle, force-spawn | **done** |
| GC-P20 | Colonize via Seed Ark + planet floor (≥1) | **done** |
| GC-P21 | Living economy planner + bootstrap resource seed; utility hangar only | **done** |
| GC-P22 | Research + shipyard progress; hangar-fraction raids (no template overwrite) | **done** |
| GC-P23 | Defense build + inbound fleet-save | **done** |
| GC-P24 | AI colony destroy (`planet_breaker`) + bounty/heat | **done** |
| GC-P25 | Balance / LiveOps / ship-gate doc pass | **done** |
| GC-P26 | Player-loop brain (`play_loop`: economy→rebuild→spy→raid→colonize→expedition) | **done** |
| GC-P27 | Cheat teardown: utility/fuel one-time seed only | **done** |
| GC-P28 | Economy depth + personality reserves / colony parity | **done** |
| GC-P29 | Anti-farm bounty/heat + wipe recolonize cooldown | **done** |
| GC-P30 | Ash Raiders + Salt Cartel; distributed homes | **done** |
| GC-P31 | Human colony destroy + docs/tests/ship-gate | **done** |

---

## Ship-Gate

Feature is live for players **and**:

1. Admin Bot-Log shows every AI action  
2. Kill-Switch soft/hard works  
3. Destroyed bases disappear (+ fleet-save recall)  
4. Pirate accounts never post to chat  
5. All raids use `simulate_battle` + visible ETA  
6. Heat ≥700 can start `pirate_war` (does not stomp other emergencies)  
7. Expo pirate loss can plant timed infiltration; smugglers spawn in hot galaxies  
8. Soft-On bootstraps **6** AI commanders with **one-time utility** hangars + resource/fuel seed; play-loop tick builds/researches/ships/defense then spies/raids/colonizes; patrol spies at Heat ≥150; home raids at ≥300 from real hangars  
9. Soft-On stocks Seed Ark; colonize at Heat ≥150; planet floor restores ≥1 colony if wiped; colony soft-cap per bot  
10. Inbound attack on AI → fleet-save recall; colony wipe (AI **or** human non-homeworld) requires `planet_breaker` + full military wipe (homeworld protected) 

**LiveOps enable:** run migrations through `114_pirate_phase3_factions.sql`, then Soft-On AI in Admin → Pirate Bot-Log. Use **Force Spawn** if Heat is still below 150.

---

## Player Article

```yaml
---
codex_id: pirates
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
  - galaxy_view
related_codex:
  - galaxy
  - fleet
  - combat
  - alliance
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: galaxy_view
teaser_key: codex_unlock_pirates_teaser
---
```

## Quick Help

**Piraten** sind eine lebende Bedrohung in der Galaxie: Basen, Fraktions-KI und Heat. Du spionierst, greifst an und bergst wie gegen Spieler — über dieselbe Flotten- und Kampf-Pipeline.

## Summary

Das Pirate Ecosystem füllt dichtere Galaxien mit temporären **Piratenbasen**, Fraktions-Commandern im Ranking und Raids, die mit steigender **Galaxy Heat** eskalieren. Piraten nutzen Spy → Intel → Angriff wie echte Flotten; Kampf und Flugzeiten laufen kanonisch. Du kannst Basen zerstören, Bounty und Threat beobachten und in Krisen (`pirate_war`) geraten, wenn die Heat kritisch wird. Expositionen können Ambush und Infiltration nachziehen.

## Why

Statt leerer Systeme entsteht ein lebendiger Gegnerdruck: Farm-Ziele, Risiko für Kolonien und eine Fairness-Linie (kein Cheat-Hangar, sichtbare ETAs, Kill-Switch nur Ops). Piraten halten die Galaxie „wach“, ohne Chat-Bots oder Fake-PMs.

## How it works

- **Galaxie:** Basen und KI-Welten erscheinen mit Status-Chips; Inspector zeigt Fraktion und deine Bounty gegenüber der Fraktion.
- **Heat:** Aktivität in der Galaxie (Kampf, Expo, Asteroiden, World Boss, Kolonisierung) heizt Systeme auf — ab Schwellen starten Patrouillen, Raids und Krisen.
- **Spieleraktionen:** Spy, Attack, Recycle gegen Basen über `/fleet` und Galaxy-Quick-Actions — gleiche Missionen wie PvP.
- **Zerstörung:** Basis weg → Slot frei, ausgehende Raids der Basis werden zurückgerufen.
- **KI-Commanders:** echte Konten im Ranking/PlayerCard (AI-Badge), bauen und forschen spielerähnlich; Homeworlds sind geschützt, Kolonien können unter harten Bedingungen fallen.
- **Threat / Bounty:** wer Basen und KI hart trifft, wird bevorzugtes Vergeltungsziel.

## Related Systems

- galaxy
- fleet
- combat
- asteroids
- world_boss

## Commander Tips

- Vor dem Raid spionieren — Intel steuert, wie die KI zuschlägt, und du brauchst dieselbe Vorsicht.
- Heat-Hotspots sind lukrativ und gefährlich; Kolonien dort absichern.
- Debris und Basen teilen sich oft Systeme — Recycler und Raid-Flotten nicht vermischen ohne Plan.

## FAQ

**Sind Piraten echte Spieler?**
Fraktions-Bots sind KI-Konten mit Hangar und Planeten — sichtbare Flotten, kein Chat. Temporäre Basen sind Map-Instanzen, keine Expansion-Welten.

**Kann meine Genesis Ark zerstört werden?**
Nein. Homeworlds sind geschützt; nur Nicht-Heimat-Kolonien können unter Planet-Breaker-Bedingungen fallen.

**Warum werde ich plötzlich geraidet?**
Hohe Threat/Bounty oder heiße Galaxie — die KI bevorzugt lohnende Ziele mit sichtbarer Flugzeit.

## Discord Summary

**Piraten — lebende Galaxy-Bedrohung**

Basen + Fraktions-KI, Heat-Eskalation, Spy/Attack über kanonische Flotte. Ranking zeigt AI-Commanders. Homeworld sicher; Kolonien unter Risiko.
