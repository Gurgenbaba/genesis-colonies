# Server Events

Timed global LiveOps bonuses + recurring schedule materializer. Owner: `game/server_events.py`.

## Scope

| Effect kind | Payload | Gameplay hook |
|-------------|---------|---------------|
| `production_mult` | `{ "kind": "production_mult", "mult": 2.0 }` | `ProductionContext.event_modifier` via `production_context_from_resolver` |
| `expedition_hold_mult` | `{ "kind": "expedition_hold_mult", "mult": 0.75 }` | `fleet.expedition_stay_seconds` |
| `shop_discount_bps` | `{ "kind": "shop_discount_bps", "bps": 2000 }` | Auto EUR-shop discount via `shop._resolve_cart_discount` (no promo code) |
| `build_time_speed` | `{ "kind": "build_time_speed", "mult": 1.25 }` | `EffectResolver.get_modifiers` after boosters/classes |
| `research_time_speed` | `{ "kind": "research_time_speed", "mult": 1.25 }` | same |
| `asteroid_spawn_mult` | `{ "kind": "asteroid_spawn_mult", "mult": 2.0 }` | `asteroids.build_schedule_info` — cooldown `/` mult, cap up to ×2, +1 belt system at ≥1.5 |
| `world_boss_spawn_mult` | `{ "kind": "world_boss_spawn_mult", "mult": 2.0 }` | `world_boss.build_schedule_info` — inter-spawn cooldown `/` mult (floor 30m); concurrent cap unchanged |
| `inactive_farm_mult` | `{ "kind": "inactive_farm_mult", "mult": 3.0 }` | `inactive_autoplay._ensure_resource_floor` — soft floor × mult |

Concurrent active events: mult kinds **multiply**; shop discount takes **max bps**. Unknown kinds are rejected on save.

Shop stacking with promo codes: `effective_discount_bps = max(event_bps, promo_bps)` — no double-dip. Creator commission only when the promo wins.

## Scheduler (auto-materialize)

Table `server_event_schedules` (migration `144`). Cron stage `liveops_schedules` in `fleet_worker` post-maint **before** world_boss/asteroids.

| Rule | Behaviour |
|------|-----------|
| Tick | `maybe_tick_schedules` (60s throttle) → `materialize_schedule` |
| Materialize | **INSERT-only** `server_events` row; never PATCH/DELETE active events |
| Idempotency | `last_materialized_key = "{schedule_id}:{starts_at}"` |
| Lookahead | 6h — creates future-window rows so calendars/HUD can show scheduled status |
| WB actions | Only if window `start <= now` at materialize time |

Default seed rules (shipped **disabled** / opt-in): weekend prod/expo, Sunday shop sale, Friday asteroid storm, Saturday boss hunt, inactive farm weekend. Fleet tick only materializes `enabled=1` rules — enable in Admin → LiveOps → Events → Kalender.

Admin: LiveOps → Events → **Scheduler** (enable/disable, „Jetzt materialisieren“).

## Presets

Server catalog `EVENT_PRESETS` / `list_presets()` / `apply_preset()` includes chaos presets (`asteroid_storm_48h`, `boss_hunt_24h`, `inactive_farm_weekend`, `chaos_weekend`) plus earlier prod/shop/build/WB presets.

World Boss instant spawn remains a preset **action**, not an effect kind / deferred row.

## Schema

- Migration `128_server_events.sql` → `server_events`
- Migration `144_server_event_schedules.sql` → `server_event_schedules` + default rules

## Admin

LiveOps tab **events** on `/admin`:

- `GET /api/admin/events` — list + active factors + kinds + presets + schedules
- `POST /api/admin/events` — create
- `PATCH /api/admin/events/<id>` — update
- `DELETE /api/admin/events/<id>` — delete (audit logged)
- `GET /api/admin/events/presets` — preset catalog
- `POST /api/admin/events/presets/<id>/apply` — apply preset
- `GET /api/admin/events/schedules` — schedule rules
- `PATCH /api/admin/events/schedules/<id>` — `{ enabled }`
- `POST /api/admin/events/schedules/<id>/materialize` — force materialize slot

## Player visibility

`/api/game-state` includes `server_events` factors (incl. asteroid/boss/farm mults).

LiveOps icon rail shows active events (effect summaries include Asteroid / Boss Hunt / Inactive Farms). Production still merges into resource-bar booster chips; other kinds appear as event rows.

## Not in scope

Loot, Timekeeper, auto-news, Battle Pass coupling, Free Shop discount, deferred WB `STATUS_SCHEDULED` rows, pirate heat schedule kinds, canceling active events on materialize.
