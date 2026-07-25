# World Boss System — Genesis Colonies

Server-wide PvE bosses: shared HP, multi-player contribution, exclusive meta rewards, recurring LiveOps windows.

**Status:** ✅ EPIC-20 (GC-W01…GC-W08)  
**Owner:** `game/world_boss.py`  
**Epic:** EPIC-20 — World Boss Events

---

## Architecture (GC-000)

| Concern | Owner | Notes |
|---------|--------|--------|
| Event state, HP, schedule, contribution, claims | `game/world_boss.py` | Single domain owner |
| Fleet send / attack arrival | `game/fleet.py` | Mission stays `attack`; target type `world_boss` |
| World-native target type | `game/fleet_target.py` | `world_boss` in `WORLD_NATIVE_TARGET_TYPES` |
| Battle math | `game/combat.py` | `simulate_battle()` only — no second combat engine |
| Galaxy visibility | `game/galaxy.py` | Slot attach like debris |
| Loot pools | `game/inventory_loot.py` | Meta-only (`item` / `booster`) |
| Grants | `game/inventory.py` | `grant_inventory_item` |
| Cron spawn/expire | `game/fleet_worker.py` piggyback | No module-owned polling |
| Directives | `game/directives/progress.py` | Event kind `world_boss_damage` |
| News | `game/universe_news.py` | `category="EVENT"` |
| Alliance aggregation | `game/alliance.py` + world_boss | Contribution `alliance_id` |

**Forbidden:** expedition pirate ratio combat for bosses; Command Map as live gate; frontend HP math; parallel fleet/combat modules; resource/ship loot boxes.

---

## Tables

| Table | Role |
|-------|------|
| `world_boss_definitions` | Catalog (key, stacks JSON, max_hp, duration, loot tiers) |
| `world_boss_events` | Active/ended instances (coords, HP, phase, schedule) |
| `world_boss_contributions` | Per player (+ alliance) damage ledger |
| `world_boss_claims` | Idempotent reward claims |

---

## Combat contract

1. Player sends `attack` to boss coordinates (`target_type=world_boss`, no `target_planet_id`).
2. On arrival, `world_boss.resolve_attack_arrival` builds defender stacks from event `fleet_stacks_json` (scaled by remaining HP phase).
3. `simulate_battle` runs; attacker losses apply to return fleet.
4. Boss HP damage = `wipe_fraction × WAVE_HP_FRACTION × max_hp × overkill_mult`, capped at `MAX_WAVE_HP_FRACTION × max_hp`.
   - `wipe_fraction = defender_losses_score / wave_stack_score` (0..1)
   - `overkill_mult = max(1, log2(1 + attacker_fleet_score / wave_stack_score))` (combat prestige scores; not raw HP)
   - Defaults: base 3% (`WAVE_HP_FRACTION`), cap 100% (`MAX_WAVE_HP_FRACTION`); even fights stay near 3%, mega fleets scale toward ~40–60%+ per wipe
5. Stacks persist for subsequent waves; debris may spawn; combat report uses defender name = boss label, `defender_id=0`.
6. When HP ≤ 0 → status `defeated`; rewards unlock. On `ends_at` with HP > 0 → `expired`.

### Anti-farm

| Rule | Default |
|------|---------|
| Account cooldown between waves | 300 s |
| Max waves per player per event | 40 |
| Even-fight full wipe HP | ~3% of `max_hp` (`WAVE_HP_FRACTION`) |
| Overkill scaling | `log2(1 + attacker_score / wave_score)` |
| Cap HP per wave | 100% of `max_hp` (`MAX_WAVE_HP_FRACTION`) |
| Min ships for attack | ≥ 1 combat-capable unit (fleet mission rules) |
| Contribution | Server-only from battle → HP mapping; never client-reported |

---

## Rewards

Claim once per player after `defeated` or `expired` (if contribution > 0):

| Tier | Condition | Grant |
|------|-----------|--------|
| `participate` | any contribution | `container_event_special` ×1 |
| `top10` | top 10% by damage (min rank 1–10) | `container_void_artifact` ×1 |
| `top1` | rank 1 | `container_mythic` ×1 |
| `alliance_top` | member of #1 alliance by sum damage | `container_ancient_relic` ×1 |

Tiers stack (player may receive multiple containers in one claim). Auction/vote remain free of event inflation.

---

## Schedule

- At most **one** `active` event universe-wide.
- Cron (`fleet_worker` post-maintenance): expire due events; if none active and cooldown elapsed, spawn next catalog boss (rotation order).
- Admin: `POST /api/admin/world-boss/spawn` force-spawns; Admin UI tab uses `GET /api/admin/world-boss` for status/definitions.

Default window: **48 h**; inter-event cooldown: **24 h**.

---

## Catalog keys

| Key | Role |
|-----|------|
| `ancient_leviathan` | High HP tank |
| `void_titan` | Heavy combat stacks |
| `planet_eater` | Dense-system spawn bias |
| `rogue_ai_nexus` | Phase stack swaps |

---

## APIs / UI

| Route | Role |
|-------|------|
| `GET /world-boss` | Contribution board + active event |
| `GET /api/world-boss` | JSON payload |
| `POST /api/world-boss/claim` | Claim rewards `{ ok, state }` |
| `POST /api/admin/world-boss/spawn` | Admin force spawn |
| `GET /api/admin/world-boss` | Admin status + definitions catalog |
| Galaxy system slots | `slot.world_boss` + `has_world_boss` (ring marker + inspector) |

### Admin LiveOps tab

Admin panel tab **World Boss** (`templates/admin_panel.html` + `static/admin.js`):

- Loads `GET /api/admin/world-boss` → `{ ok, event, schedule, definitions }`
- Spawn form posts to existing `POST /api/admin/world-boss/spawn` (`boss_key`, optional G/S/P, `force`, `announce`)
- No second spawn owner — same `spawn_world_boss` path as cron/admin API

Fleet deep-link: `/fleet?mission=attack&target_galaxy=G&target_system=S&target_position=P`

Boss art: `static/img/bosses/{boss_key}.png` with fallback `_placeholder.png`.

Active event UI: centered Monster-Warlord-style hero (portrait `object-fit: contain`, glow pulse, HP bar under art). Sidebar nav pulses via `nav_badges.world_boss` + SSR `WORLD_BOSS_ACTIVE`.

### Idle / Help UX

Payload always includes `schedule`:

| Field | Meaning |
|-------|---------|
| `next_eligible_at` | Earliest next spawn (`last_ended_at + inter_event_cooldown_sec`, or `server_now` if never ended) |
| `spawn_ready` | Cooldown elapsed and no active boss (spawn on next fleet cron tick) |
| `has_active` | Active event currently running |

UI: countdown via `data-countdown-at` when idle; `event.ends_at` countdown when active. Panel `?` opens a help modal (shared HP, attack, boards, rewards, limits, schedule).

---

## Tickets

| Ticket | Focus |
|--------|--------|
| GC-W01 | Spec + CORE §17 + ROADMAP |
| GC-W02 | Migration + `world_boss.py` core |
| GC-W03 | Fleet/combat hook |
| GC-W04 | Galaxy UI attach (ring marker + inspector + attack) |
| GC-W05 | Rewards + board |
| GC-W06 | Schedule + admin spawn |
| GC-W07 | Alliance aggregation |
| GC-W08 | Directives + universe news |
| GC-W09 | Spawn ETA + help modal |
| GC-W10 | Admin World Boss spawn tab |
| GC-W11 | Hero Warlord layout + nav live pulse |

---

## Tests

`tests/test_world_boss.py` — schema, spawn, attack, claim, schedule, admin GET, deep-link, galaxy UI, HP damage mapping, hero/nav contracts, `nav_badges.world_boss`.
