# Command Initiation

Once-through **do-first** guidance: deep-link to a page, complete a concrete objective, advance. Not Story Ops (lore) and not Imperial Directives (daily).

## Owner

| Layer | Path |
|-------|------|
| Module | `game/initiation/` |
| Pack | `game/initiation/packs/phase1_colony_core.json` |
| Schema | `migrations/142_command_initiation.sql` |
| Routes | `GET /initiation`, `GET /api/initiation/state` |
| Event bus | Fan-out from `game/directives/progress.py` (`_fanout_story_events`) |

## Phase 1 (Colony Core)

1. Upgrade Ferronite Mine ×3 (`/buildings`)
2. Upgrade Crytite Extractor ×1
3. Upgrade Solar Collector Field ×1
4. Complete research ×1 (`/research`)
5. Build a ship ×1 at Orbital Shipyard (`/shipyard`)
6. Build defense ×1 (`/defense`)
7. Send a fleet ×1 (`/fleet`)

Objectives reuse directive keys via `gameplay_event_delta`. `upgrade_buildings` accepts optional `filters.building_types`.

Player-facing copy uses Genesis Colonies building names only (no OGame “Metal Mine” wording).

## UX

- Compact header icon rail (`partials/header_icon_rail.html`): Initiation + Login Rewards + Season Pass (sidebar entries removed)
- Mission page: compact image card grid (no oversized featured duplicate)
- Go links for building steps use `/buildings?tab=…&highlight=<building_key>`; Buildings marks the stage prop / card
- `initiation` on `/api/game-state` (diet-safe) patches the icon via `GC.patchInitiationHud`

## Rules

- Server-authoritative progress; idempotent `source_event_id`
- Auto-start on first ensure; one-time track (no daily reset)
- Meta rewards deferred to later phase tickets
- Later phases (Empire / LiveOps meta) extend the same pack — no parallel tracker

## Related

- [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) — shared event bus
- [GENESIS_STORY_OPS.md](GENESIS_STORY_OPS.md) — lore (not tutorial)
- [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md) — reading help (optional links later)
