# Command Initiation

Once-through **do-first** guidance: deep-link to a page, complete a concrete objective, advance. Not Story Ops (lore) and not Imperial Directives (daily).

## Owner

| Layer | Path |
|-------|------|
| Module | `game/initiation/` |
| Pack | `game/initiation/packs/command_initiation.json` |
| Schema | `migrations/142_command_initiation.sql` |
| Routes | `GET /initiation`, `GET /api/initiation/state` |
| Event bus | Fan-out from `game/directives/progress.py` (`_fanout_story_events`) |
| Page visits | `record_page_visit` / `maybe_record_page_visit_from_request` (hooked in `_load_page_live_context`; Empire has a direct call) |

## Phases

### Phase 1 — Colony Core

1. Upgrade Ferronite Mine ×3 (`/buildings`)
2. Upgrade Crytite Extractor ×1
3. Upgrade Solar Collector Field ×1
4. Complete research ×1 (`/research`)
5. Build a ship ×1 at Orbital Shipyard (`/shipyard`)
6. Build defense ×1 (`/defense`)
7. Send a fleet ×1 (`/fleet`)
8. Visit Galaxy
9. Visit Messages
10. Visit Combat Simulator
11. Visit Planet Evolution

Action objectives reuse directive keys via `gameplay_event_delta`. `upgrade_buildings` accepts optional `filters.building_types`. Visit steps use `objective_key: visit_page` + `filters.pages`.

### Phase 2 — Empire & Expansion

Visit: Empire, Tech Tree, Skill Tree, Ranking, Hall of Fame.

### Phase 3 — LiveOps & Meta

Visit: Imperial Directives, Story Ops, Login Rewards, Season Pass, Shop, Inventory, Trader Hub, Auction House, World Boss, Alliance, Galactic Politics, Vote Center, Referrals.

Player-facing copy uses Genesis Colonies building names only (no OGame “Metal Mine” wording).

## UX

- Compact header icon rail (`partials/header_icon_rail.html`): Initiation + Login Rewards + Season Pass
- Mission page: compact image card grid
- Go links for building steps use `/buildings?tab=…&highlight=<building_key>`
- `initiation` on `/api/game-state` (diet-safe) patches the icon via `GC.patchInitiationHud`

## Rules

- Server-authoritative progress; idempotent `source_event_id`
- Auto-start on first ensure; one-time track (no daily reset)
- Page visits only when the **active** step is `visit_page` for that page (no premature consume)
- Meta rewards deferred to a later ticket
- Pack version bump when appending steps; existing `step_index` players continue mid-track

## Related

- [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) — shared event bus
- [GENESIS_STORY_OPS.md](GENESIS_STORY_OPS.md) — lore (not tutorial)
- [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md) — reading help (optional links later)
