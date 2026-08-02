# Server Events

Timed global LiveOps bonuses. Owner: `game/server_events.py`.

## Scope (v1)

| Effect kind | Payload | Gameplay hook |
|-------------|---------|---------------|
| `production_mult` | `{ "kind": "production_mult", "mult": 2.0 }` | `ProductionContext.event_modifier` via `production_context_from_resolver` |
| `expedition_hold_mult` | `{ "kind": "expedition_hold_mult", "mult": 0.75 }` | `fleet.expedition_stay_seconds` |

Concurrent active events multiply factors together. Unknown kinds are rejected on save.

## Schema

Migration `128_server_events.sql` → table `server_events` (`slug`, `title`, `starts_at`/`ends_at` unix UTC, `enabled`, `effects_json`).

## Admin

LiveOps tab **events** on `/admin`:

- `GET /api/admin/events` — list + active factors + kind catalog
- `POST /api/admin/events` — create
- `PATCH /api/admin/events/<id>` — update
- `DELETE /api/admin/events/<id>` — delete (audit logged)

**UI:** datetime-local pickers in the admin’s local timezone (converted to UTC unix on save). Quick actions: Wochenend-Boost (+100% prod / −25% hold until Sun 20:00), effect chips, duration chips (24h / 48h / until Sunday). Slug auto-fills from title.

**Player visibility**

`/api/game-state` includes `server_events: { events, production_mult, expedition_hold_mult }`.

Resource bar: active `production_mult` is merged into `active_boosters.active_effects` (same chips as inventory +25/+50/+75%). Example: `+50 % · Event +100 % · 1h 59m`. Technical Data shows `technical_bonus_event` when production mult ≠ 1.

Universe News announcements stay separate (manual EVENT posts).

**Login calendar overlay**

`/login-rewards` projects attendance streak days 1–30 onto UTC buckets and flags days whose window overlaps active/scheduled server events (`event`, `events[]` with effect summary). Claim rules are unchanged — events are visual/context only.

## Not in v1

Build/research time, loot, Timekeeper, auto-news, Battle Pass coupling.
