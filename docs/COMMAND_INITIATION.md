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

## Design goal

Phase 1 is the **way to go** for early economy — aligned with the fresh-account sim strategy (`docs/GC-829_FRESH_ACCOUNT_PROGRESSION.md`):

> Solar → Mines → Energy balance → Lab → Energy Tech → Fuel → grow mines → Mining Tech → Command Center → Shipyard → first fleet

Hints explain *why* (energy before mines, Crytite unlocks Lab/Fuel, Energy Tech keeps production efficient).

## Phases

### Phase 1 — Colony Core (efficient build)

1. Solar Collector Field ×1 (energy first)
2. Ferronite Mine ×2
3. Crytite Extractor ×2 (Lab + Fuel gates)
4. Solar ×1 (keep energy ahead)
5. Ferronite ×1 (reach Mine 3 for Lab)
6. Research Lab ×1
7. Complete **Energy Tech** ×1
8. Fuel Cell Plant ×1
9. Ferronite ×2 / Crytite ×1 / Solar ×1 (grow + balance)
10. Complete **Mining Tech** ×1
11. Command Center ×2 → Orbital Shipyard building ×1
12. Build a ship → send a fleet
13. Visit Galaxy + Planet Evolution

`upgrade_buildings` / `complete_research` accept optional `building_types` / `research_keys` filters.

### Phase 2 — Empire & Expansion

Visit: Empire, Messages, Combat Simulator, Tech Tree, Skill Tree, Ranking, Hall of Fame.

### Phase 3 — LiveOps & Meta

Visit: Directives, Story, Login, Season Pass, Shop, Inventory, Trader, Auction, World Boss, Alliance, Politics, Vote, Referrals.

## UX

- Header icon rail: Initiation + Login Rewards + Season Pass
- Mission cards with Go deep-links (`highlight=` for buildings/research)
- `initiation` on `/api/game-state` patches the HUD

## Rules

- Server-authoritative; idempotent `source_event_id`
- Auto-start once; no daily reset
- Page visits only when the active step is `visit_page` for that page
- Pack version bump on restructure; mid-track players keep `step_index`

## Related

- [GC-829_FRESH_ACCOUNT_PROGRESSION.md](GC-829_FRESH_ACCOUNT_PROGRESSION.md) — sim strategy
- [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) — requirement gates
- [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) — shared event bus
- [GENESIS_STORY_OPS.md](GENESIS_STORY_OPS.md) — lore (not tutorial)
