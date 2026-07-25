# Asteroid System — Genesis Colonies

Temporary asteroid belts in densely settled classic galaxy systems. Harvest with existing **`harvest_reclaimer`** via mission **`recycle`**.

**Status:** GC-AST endgame (engagement + hunt UX)  
**Owner:** `game/asteroids.py`

---

## Architecture (GC-000)

| Concern | Owner | Notes |
|---------|--------|--------|
| Spawn, types, TTL, claim, loot roll | `game/asteroids.py` | Single domain owner |
| Durable hunt engagement | `asteroid_engagements` + `record_asteroid_engagement` | Survives fleet `resources_json` wipes |
| Fleet send / recycle arrival | `game/fleet.py` | Mission stays `recycle`; preserves `asteroid_id` meta; expired ≠ debris |
| World-native / overlay target | `game/fleet_target.py` | `asteroid` in `WORLD_NATIVE_TARGET_TYPES` |
| Galaxy visibility | `game/galaxy.py` | Slot attach + viewer en-route flags |
| Cron spawn/expire | `game/fleet_worker.py` piggyback | No module-owned polling |

**Forbidden:** second fleet send path; putting asteroid loot in `debris_fields`; frontend loot math; new miner ship; inventory/item loot.

---

## Rules

| Rule | Value |
|------|-------|
| TTL | 2 h (`TTL_SECONDS`) |
| Cap | 15 concurrent `active` fields |
| Wave cooldown | 45 min between belt spawns |
| Belt size | 3–6 asteroids per dense system (1–2 systems / wave) |
| Spawn bias | densest `[G:S]` with free classic slots (search up to 64 systems) |
| Anti-pop | claimed/expired coords stay blocked until original `expires_at` |
| Deploy | `ensure_asteroids_present` on Galaxy view + empty-universe bootstrap in schedule tick |
| Slots | free classic positions 1–15 only (no planet / active boss / reserved TTL / active asteroid) |
| Race | multiple outbound OK; **first arrival** atomic claim; late arrivals miss |
| Expire en route | asteroid-stamped flight → `expired` report, **no** debris fallback |
| Ship | `harvest_reclaimer` (role `recycle`) |
| Loot | metal / crystal / fuel_cells only — rolled at spawn, random within type range |

---

## Galaxy board (GC-AST-UX-01)

`list_system` → `active_asteroid_board` via `build_asteroid_board_entries` plus `asteroid_schedule` from `build_schedule_info`.

Viewer hunt UX:
- Send records `asteroid_engagements` + stamps `asteroid_id` on the movement.
- Board/ring show **Unterwegs / En route** with ETA (not silent hide).
- Harvest button disabled while own outbound fleet is flying.
- Cap line shows global active vs visible board count; next-wave countdown in header + empty state.

Expire-on-view: `expire_due_asteroids` runs from board build / system attach (debris parity). Countdown zero → Galaxy PJAX reload (`data-refresh-on-zero="galaxy"`).

---

## Types (catalog in `asteroids.py`)

| Key | Split (approx) | Total range |
|-----|----------------|-------------|
| `ferronite_rock` | 70/25/5 M/C/F | 600k–3.0M |
| `crytite_shard` | 25/70/5 | 600k–3.0M |
| `fuel_ice` | 15/15/70 | 500k–2.5M |
| `mixed_belt` | 40/40/20 | 800k–4.5M |

Cargo take = `min(fleet_cargo, pool)`; asteroid is fully claimed and removed even if leftover cargo capacity is insufficient (remainder lost).

---

## Fleet contract

1. Active asteroid at `[G:S:P]` → `target_type=asteroid`, allowed mission `recycle` only (priority over debris; world boss still wins if present).
2. On send: stamp `asteroid_id` + `record_asteroid_engagement`.
3. On arrival: `try_claim_harvest` — `claimed` / `missed` / `expired`; asteroid-stamped flights never fall through to debris.
4. Arrival/recall merge asteroid meta into `resources_json` (do not wipe stamps).
5. Galaxy One-Click: `min(available_reclaimers, recycler_slots_needed)` via `GalaxyQuickAction`.

---

## Tables

- `asteroid_fields` (migration `104_asteroid_fields.sql`)
- `asteroid_engagements` (migration `105_asteroid_engagements.sql`): `(player_id, asteroid_id)` unique

---

## Tests

See `tests/test_asteroids.py` — density spawn, TTL, first-arrival race, engagement durability after tick, anti-pop slot reserve, expired≠debris, board en-route UX contracts.
