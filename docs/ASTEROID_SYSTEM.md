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
| Wave cooldown | 45 min between belt spawns (`INTER_WAVE_COOLDOWN_SEC`); LiveOps `asteroid_spawn_mult` divides cooldown and may raise cap (see [SERVER_EVENTS.md](SERVER_EVENTS.md)) |
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
- Hover/focus on an available Harvest action loads the canonical fleet preview (fuel, HR count, flight time); click reuses that preview and blocks locally-visible fuel shortages before send.
- Cap line shows global active vs visible board count; next-wave countdown in header + empty state.

Expire-on-view: `expire_due_asteroids` runs from board build / system attach (debris parity). Countdown zero → Galaxy PJAX reload (`data-refresh-on-zero="galaxy"`).

---

## Types (catalog in `asteroids.py`)

| Key | Split bias (approx) | Per-resource range |
|-----|---------------------|--------------------|
| `ferronite_rock` | 70/25/5 M/C/F | base roll 0.5M–5M × adaptive multiplier |
| `crytite_shard` | 25/70/5 | base roll 0.5M–5M × adaptive multiplier |
| `fuel_ice` | 15/15/70 | base roll 0.5M–5M × adaptive multiplier |
| `mixed_belt` | 40/40/20 | base roll 0.5M–5M × adaptive multiplier |

Each resource still rolls independently inside the 0.5M–5M base band; catalog split only biases toward the high end for preferred resources. **New standard fields are then multiplied server-side** by an adaptive progression factor.

### Adaptive Standard Belts (GC-AST-VALUE-01)

Standard belts use the median level of the universe's top 10 relevant mines (`metal_mine`, `crystal_mine`, `fuel_cell_plant`) with a minimum reference of **L30**. At the L30 floor the legacy roll is multiplied by **5×**. Above L30 the multiplier grows sub-linearly with the canonical `game.production_formula.level_growth()` curve (`progression^0.45`). There is no fixed late-game hard cap; a single extreme account cannot dominate the reference because the median is used.

This scaling applies **only when a new standard asteroid is spawned**. Existing active fields keep their stored pool until claimed/expired. Mega Belts remain separately storage-scaled and are intentionally the jackpot tier.

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

---

## Player Article

```yaml
---
codex_id: asteroids
band: III
difficulty: intermediate
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - galaxy_view
  - fleet_view
related_codex:
  - galaxy
  - fleet
  - salvage
  - resources
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: galaxy_view
teaser_key: codex_unlock_asteroids_teaser
---
```

## Quick Help

**Asteroidenfelder** erscheinen zeitlich begrenzt in dichten Galaxie-Systemen. Ernte sie mit dem **Ernter/Recycler** über die Mission **Recycle**.

## Summary

Wellen spawnen Gürtel aus Ferronit-Gestein, Crytite-Scherben, Brennstoff-Eis oder Mischgürteln auf freien klassischen Slots. Mehrere Flotten können starten — **wer zuerst ankommt**, claimt den Pool. Abgelaufene Felder erzeugen kein Debris-Fallback. Die Galaxy-Board zeigt Unterwegs-Status und Countdown zur nächsten Welle.

## Why

Kurzlebige, umkämpfte Rohstoff-Preise ohne neue Miner-Klasse: bestehende Recycle-Pipeline, sichtbarer Wettbewerb, LiveOps-Tempo in vollen Systemen.

## How it works

- Galaxie-System mit aktivem Asteroid-Board öffnen; Typ und Timer lesen.
- Flotte mit Ernter-Schiffen, Mission Recycle, Ziel Asteroid — Prefill/Quick-Action hilft.
- Ankunft: Claim, Miss (zu spät) oder Expired — Bericht erklärt den Ausgang.
- Eigenes Outbound disabled den Harvest-Button, bis die Flotte zurück ist oder das Feld weg ist.
- Loot nur Ferronit / Crytite / Brennzellen in den Frachtraum; Rest verfällt, wenn Cargo nicht reicht.

## Related Systems

- galaxy
- fleet
- salvage
- pirates
- resources

## Commander Tips

- Dichte Systeme beobachten — dort spawnen Gürtel zuerst.
- Fracht und Ernter-Anzahl vor dem Send checken; First-Arrival zählt.
- Nicht mit Debris-Recycle verwechseln: Asteroid-Flüge fallen nicht auf Debris zurück.

## FAQ

**Welches Schiff?**
Ernter mit Recycle-Rolle (`harvest_reclaimer`) — gemischte Flotten möglich, Mission bleibt Recycle.

**Verschwindet das Feld während meines Flugs?**
Ja möglich — dann Expired-Report, kein automatisches Debris.

**World Boss auf dem Slot?**
Boss hat Vorrang; Asteroid braucht freien klassischen Slot.

## Discord Summary

**Asteroiden — Timed Harvest**

Galaxy-Gürtel, Recycle-Mission, First-Arrival Claim. Nur Ressourcen-Loot. Board zeigt En-route und Wave-Timer.

## Mega Belt Fair-Share

Mega Belts use a server-authoritative **10% maximum share per player** based on the original spawn pool, enforced per resource. Large Harvest Reclaimer fleets can collect the remaining personal share in one trip; smaller fleets may repeat trips until the same 10% cap is reached. Outbound and returning are distinct live fleet states; historical engagement never keeps a completed flight visually locked.
