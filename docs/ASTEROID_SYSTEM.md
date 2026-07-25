# Asteroid System — Genesis Colonies

Temporary asteroid belts in densely settled classic galaxy systems. Harvest with existing **`harvest_reclaimer`** via mission **`recycle`**.

**Status:** GC-AST-01…04  
**Owner:** `game/asteroids.py`

---

## Architecture (GC-000)

| Concern | Owner | Notes |
|---------|--------|--------|
| Spawn, types, TTL, claim, loot roll | `game/asteroids.py` | Single domain owner |
| Fleet send / recycle arrival | `game/fleet.py` | Mission stays `recycle`; target type `asteroid` |
| World-native / overlay target | `game/fleet_target.py` | `asteroid` in `WORLD_NATIVE_TARGET_TYPES` |
| Galaxy visibility | `game/galaxy.py` | Slot attach like debris / world boss |
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
| Deploy | `ensure_asteroids_present` on Galaxy view + empty-universe bootstrap in schedule tick |
| Slots | free classic positions 1–15 only (no planet / active boss / active asteroid) |
| Race | multiple outbound OK; **first arrival** atomic claim; late arrivals miss |
| Ship | `harvest_reclaimer` (role `recycle`) |
| Loot | metal / crystal / fuel_cells only — rolled at spawn, random within type range |

---

## Galaxy board (GC-AST-UX-01)

`list_system` → `active_asteroid_board` via `build_asteroid_board_entries` (active fields, TTL-sorted, `galaxy_href` jump).

Viewer filter: once the player has committed a ``recycle`` flight to an active field
(``outbound`` / ``returning`` / ``completed``, departure ≥ field ``spawned_at``), that
field is omitted from *their* board for the rest of its life. Cancelled/failed do not
count. A later spawn at the same slot shows again. Ring marker stays until claim.

UI: `templates/partials/galaxy_asteroid_board.html` in the Galaxy HUD — collapsed bar by default (count badge), expand for list + Jump + `?` help modal. No dedicated `/asteroids` page.

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
2. On arrival: `try_claim_harvest` — `claimed` → load cargo; `missed` → empty return + miss report; `none` → existing debris recycle path.
3. No remove-on-send.
4. Galaxy One-Click: `min(available_reclaimers, recycler_slots_needed)` via `GalaxyQuickAction`.

---

## Table

`asteroid_fields` (migration `104_asteroid_fields.sql`): coords, rolled resources, `status` (`active` / `claimed` / `expired`), TTL, claim metadata.

---

## Tests

See `tests/test_asteroids.py` — density spawn, TTL, first-arrival race, miss path, galaxy payload, recycle gate, board entries.
