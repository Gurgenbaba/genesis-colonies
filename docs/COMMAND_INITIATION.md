# Command Initiation

Once-through **do-first** guidance that teaches the **efficient colony build order**, then walks the rest of the game. Not Story Ops (lore) and not Imperial Directives (daily).

## Owner

| Layer | Path |
|-------|------|
| Module | `game/initiation/` |
| Pack | `game/initiation/packs/command_initiation.json` |
| Schema | `migrations/142_command_initiation.sql` |
| Routes | `GET /initiation`, `GET /api/initiation/state` |
| Event bus | Fan-out from `game/directives/progress.py` (`_fanout_story_events`) |
| Page visits | `record_page_visit` / `maybe_record_page_visit_from_request` |
| BiS guide | `game/initiation/build_order.py` (`plan_build_order`) — advice only, not enqueue |

## Design goal

Phase 1 is the **way to go** for early economy — aligned with the fresh-account sim strategy (`docs/GC-829_FRESH_ACCOUNT_PROGRESSION.md`):

> Solar → Mines → Energy balance → Lab → Energy Tech → Fuel → grow mines → Mining Tech → Command Center → Shipyard → first fleet

Hints explain *why* (energy before mines, Crytite unlocks Lab/Fuel, Energy Tech keeps production efficient).

The **Build Order** tab is a separate personalized guide to producer **level 100** (mines + solar + fuel), including nanofactory / Bauoptimierung and geothermal / planet-core for the level cap.

## Phases

### Phase 1 — Colony Core (efficient build)

Targets are **level thresholds** (have Solar ≥ 3), not “build N more upgrades”.

1. Solar Collector Field ≥ **3** (energy first)
2. Ferronite Mine ≥ 2
3. Crytite Extractor ≥ 2 (Lab + Fuel gates)
4. Solar ≥ 4 (keep energy ahead)
5. Ferronite ≥ 3 (Lab gate)
6. Research Lab ≥ 1
7. Energy Tech ≥ 1
8. Fuel Cell Plant ≥ 1
9. Ferronite ≥ 5 / Crytite ≥ 3 / Solar ≥ 5
10. Mining Tech ≥ 1
11. Command Center ≥ 2 → Orbital Shipyard ≥ 1
12. Build a ship → send a fleet
13. Visit Galaxy + Planet Evolution

**Existing progress credit:** on ensure/state load, building/tech/hangar levels already met auto-advance (veterans with Solar 12 skip the Solar ≤3/4/5 steps). Prior `fleet_movements` credit the send-fleet step. Owner: `credit_existing_progress` / `world_progress_for_step`.

`upgrade_buildings` / `complete_research` accept optional `building_types` / `research_keys` filters.

### Phase 2 — Empire & Expansion

Visit: Empire, Messages, Combat Simulator, Tech Tree, Skill Tree, Ranking, Hall of Fame.

### Phase 3 — LiveOps & Meta

Visit: Directives, Story, Login, Season Pass, Shop, Inventory, Trader, Auction, World Boss, Alliance, Politics, Vote, Referrals.

## Page-visit credit

- Every qualifying page open logs an idempotent `ini_page_seen:{page}:{player_id}` row (even before that visit step is active).
- When the cursor reaches a `visit_page` step, `credit_existing_progress` completes it from the seen log.
- Durable proxy: Alliance membership credits `visit_alliance` without a re-open.
- Progress strip uses **completed** count (`step_index` while active, `step_count` when done) — not `step_index + 1`.

## BiS Build Order (guide)

Greedy server planner on the active planet (`get_context_planet`):

1. Energy gate (keep `energy_ratio` healthy via Solar)
2. Cap gate (raise `geothermal_nexus` / `planet_core_nexus` when producers hit `get_max_building_level`)
3. Early nanofactory unlock + ROI on nano / `buildtime_tech` / Command Center
4. Economy push toward metal / crystal / solar / fuel **100**

Uses `EffectResolver` + `BUILDING_REQUIREMENTS` / research requirements. Does **not** enqueue — AI enqueue stays in `auto_empire`.

## UX

- Header icon rail: Initiation + Login Rewards + Season Pass
- Page tabs: **Doctrine** (mission cards) | **Build Order** (sequence list)
- Mission cards with Go deep-links (`highlight=` for buildings/research)
- `initiation` on `/api/game-state` patches the HUD
- `get_initiation_state` includes `build_order` + `completed_steps`

## Rules

- Server-authoritative; idempotent `source_event_id`
- Auto-start once; no daily reset
- **Credit existing levels** on ensure/state (buildings, research, hangar/defense ownership, prior fleet sends)
- **Credit prior page visits** via `ini_page_seen` + alliance membership proxy
- Page visits via `_load_page_live_context` on **full loads and PJAX** (poll path no longer drops visit credit)
- Named `finish_source` for visit surfaces (galaxy, messages, ranking, …) plus path fallback
- Pack version bump on restructure; mid-track players keep `step_index` (targets refresh on advance)

## Related

- [GC-829_FRESH_ACCOUNT_PROGRESSION.md](GC-829_FRESH_ACCOUNT_PROGRESSION.md) — sim strategy
- [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) — requirement gates
- [EFFECTS.md](EFFECTS.md) — build time / max level
- [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) — shared event bus
- [GENESIS_STORY_OPS.md](GENESIS_STORY_OPS.md) — lore (not tutorial)
