# Pirate Ecosystem — Living Threat (EPIC-21)

Galaxy Heat, pirate factions/bases, player-like AI raids (Spy→Intel→Attack), Threat/Bounty, galaxy crises, Admin Bot-Log + Kill-Switch.

**Status:** ✅ EPIC-21 shipped (GC-P00…GC-P19 living bots)  
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

Outbound fleets come from **base strength templates + home hangar caps**. Flight times use `fleet_calc`. No instant jumps, no ignore-defense. Soft-On stocks a thin home hangar (faction stacks + probes/reclaimers) so bots appear in ranking with fleet score — not unlimited cheat hangars.

### Destroy

Destroying a pirate base sets status `destroyed`, frees the galaxy slot, recalls/cancels that base’s outbound raids (fleet-save). Instance is gone until Heat respawns another.

### Kill-Switch

| Mode | Behavior |
|------|----------|
| Soft-Off (`pirates_ai_enabled=0`) | No new spawns, spies, or raids |
| Soft-On | Enables AI **and** bootstraps all 4 faction bots + home fleets (`bots_bootstrapped` log) |
| Hard-Off | Soft-Off + recall pending pirate outbound/holding fleets (`mode=hard` on `/api/admin/pirates/ai`) |

Stored in `runtime_state` key `pirates_ai_enabled` (default off until LiveOps enables).

### Admin Bot-Log

Every brain decision (spy, intel score, attack, skip reason, destroy, AI disabled) writes `pirate_action_log`. Admin panel tab **Pirate Bot-Log** (`/api/admin/pirates`, Soft-On/Off via `/api/admin/pirates/ai`, Force Spawn via `/api/admin/pirates/force-spawn`): bot roster, live bases, heat top, KPIs (bots/raids/spies/spawns/wars/infiltrations/smugglers), `pirate_war` chips, action feed, kill-switch controls.

Owner helpers: `game/pirates/admin.py` (`build_admin_pirates_payload`, `admin_set_ai`, `admin_hard_disable_ai`, `admin_force_spawn_hottest`).

### Living bots (GC-P19 / GC-P20)

When AI is on, faction bots participate via canonical fleets:

| Heat | Behavior |
|------|----------|
| Soft-On (any heat) | 4 bots exist in Ranking/Galaxy/PlayerCard with home hangars (+ Seed Ark) |
| ≥150 Patrol | Real `spy` missions from homeworlds → arrival writes `pirate_intel` |
| ≥150 Colonize | Real `colonize` with `seed_ark` to free classic slots (soft cap 3 planets/bot) |
| ≥300 Raids | Attacks from live bases **and** homeworlds (budget fill) |
| ≥150 + debris | Opportunistic `recycle` (max 1/tick) |
| Planet floor | Always ≥1 planet; restore homeworld if wiped (`bot_planet_floor`) |

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

## Factions (v1)

| Key | Role |
|-----|------|
| `crimson_corsairs` | Fast raiders, high loot, weak base |
| `iron_collective` | Armor, slow, strong base, low loot |
| `void_cult` | Spy/infiltration bias |
| `nomad_swarm` | Many small ships |

Personality + playtime live in `pirate_faction_defs.personality_json` and `pirate_bot_state` (GC-P09).  
Bounty: `player_bounty` rises on base damage/destroy; raid brain prefers high-bounty revenge targets (GC-P10). Galaxy inspector shows viewer bounty for the base’s faction.

### AI visibility (human-facing)

Faction bots (`gc_pirate_*`) are **real player rows** and appear in:

- Ranking (with `is_ai` + AI badge; never shown as inactive)
- Galaxy (homeworlds in belt `1:490–491`, AI status chip)
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
8. Soft-On bootstraps 4 AI commanders with hangars; patrol spies at Heat ≥150; home raids at ≥300  
9. Soft-On stocks Seed Ark; colonize at Heat ≥150; planet floor restores ≥1 colony if wiped  

**LiveOps enable:** run migrations through `108_pirate_war_emergency.sql`, then Soft-On AI in Admin → Pirate Bot-Log. Use **Force Spawn** if Heat is still below 150.
