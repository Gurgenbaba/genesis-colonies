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
| Alliance aggregation | `game/alliance.py` + world_boss | Contribution `alliance_id`; Ally XP via `grant_alliance_xp` |

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
2. On **send**, `note_attack_dispatched` sets `last_attack_at` (wave cooldown starts). In-flight outbound attacks to the same slot are blocked (`world_boss_inflight`).
3. On arrival, `world_boss.resolve_attack_arrival` builds defender stacks; arrival does **not** reset `last_attack_at`.
4. `simulate_battle` runs; attacker losses apply to return fleet.
5. Boss HP damage = `wipe_fraction × WAVE_HP_FRACTION × max_hp × overkill_mult`, capped at `MAX_WAVE_HP_FRACTION × max_hp`.
   - `wipe_fraction = defender_losses_score / wave_stack_score` (0..1)
   - `overkill_mult = max(1, 1 + OVERKILL_LOG_SCALE × log2(max(1, attacker_fleet_score / wave_stack_score)))`
   - Defaults: base 2%, soft overkill `0.15`, cap **8%** → solo mega fleets need ~10–20 waves
6. If the attacker is in an alliance: Ally XP = `min(20, damage // 75_000)` via `grant_alliance_xp` (owner `game/alliance.py`).
7. Stacks persist for subsequent waves; debris may spawn; combat report uses defender name = boss label, `defender_id=0`.
8. When HP ≤ 0 → status `defeated`; rewards unlock. On `ends_at` with HP > 0 → `expired`.

### Anti-farm

| Rule | Default |
|------|---------|
| Account cooldown between waves | 300 s — starts on **fleet send** |
| In-flight lock | one outbound attack per player per boss slot |
| Max waves per player per event | 40 |
| Even-fight full wipe HP | ~2% of `max_hp` (`WAVE_HP_FRACTION`) |
| Overkill scaling | `1 + 0.15 × log2(max(1, attacker_score / wave_score))` |
| Cap HP per wave | 8% of `max_hp` (`MAX_WAVE_HP_FRACTION`) |
| Contribution | Server-only from battle → HP mapping; never client-reported |

---

## Rewards

Claim once per player after `defeated` or `expired` (if contribution > 0).
Participate / discoverer / top10 bonus use the boss definition `loot_pool_key`
(e.g. Leviathan → Event-Container, Void Titan → Void-Artefakt, Nexus → Antikes Relikt).

| Tier | Condition | Grant |
|------|-----------|--------|
| `participate` | any contribution | `loot_pool_key` ×2 |
| `top10` | top 10% by damage | `container_void_artifact` ×1 + `loot_pool_key` ×1 |
| `top1` | rank 1 | `container_mythic` ×1 |
| `alliance_top` | member of #1 alliance by sum damage | `container_ancient_relic` ×1 |
| `discoverer` | Expo-Finder (must also deal damage) | `loot_pool_key` ×1 extra |

Same item keys stack. Each World Boss card shows `rewards_preview` from the server (no client math). Auction/vote remain free of event inflation.

Expo discovery ≈ **5.5%** per expedition resolve when under the concurrent cap; spawn is server-wide for everyone.

---

## Schedule

- Up to **3** concurrent `active` events (distinct `boss_key`).
- Active bosses never share the same `[G:S:P]` — auto-pick skips occupied boss slots; explicit coords return `coords_occupied`.
- Cron (`fleet_worker`): expire due events; if `active < 3` and ≥ **4 h** since last spawn, weighted spawn (`spawn_weight`).
- Rare **expedition discovery** (~3%) may spawn when under cap.
- Admin: `POST /api/admin/world-boss/spawn` (`force` may exceed cap / replace same key).

Default window: **48 h**; inter-spawn gap: **4 h**.

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
