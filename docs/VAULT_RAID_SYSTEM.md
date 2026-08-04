# Secret Vault Raid — Planetary Bunker

**Stand:** GC-VAULT Phase 1 · Owner: `game/troops.py`, `game/troop_defs.py`, ground resolve in `game/combat.py` (`simulate_ground_raid`), steal in `game/vault_raid.py`; Barracks train UI = Defense page tab **Bodentruppen**

After a successful **orbital** `attack` battle, a optional **ground phase** resolves against planet troop stock trained at **Barracks**. Win steals capped account meta (Timekeeper + containers); fail wipes most attacking troops.

## Caps (locked)

| Vault slice | Cap |
|-------------|-----|
| Timekeeper | `min(defender_balance, 21600)` sec (6 h) |
| Meta containers | up to **5** from account inventory (`planet_id IS NULL`) |

Whitelist: catalog `item_type=container` keys in `CONTAINER_KEYS` except event exclusives blocked for raid (`container_event_special`).

## Incoming fleets vs Threat Net

| Layer | Owner | What the player sees |
|-------|--------|----------------------|
| **Incoming HUD** | `build_fleet_incoming_attack_alerts` | Every foreign `outbound` with target = owned planet: `attack`, `spy`, `deploy`, `transport` — always, no radar required |
| **Threat Net** | `build_radar_contacts` | Foreign `attack`/`spy`/`deploy` inside a radar bubble (early warning + intel tier) |

Spy aimed at your world is therefore visible in the Incoming HUD even without a Radar Array.

## Barracks troop capacity

Owner: `barracks_troop_capacity` in `game/troop_defs.py` (server-only; UI displays server value).

```text
capacity = 20 + level × 200 + level⁴ × 16   (level ≤ 0 → 0)
```

Approximate breakpoints: L1 ≈ 236 · L10 ≈ 162k · L25 ≈ 6.3M · L50 ≈ 100M.

Ground combat power and vault steal caps are independent of this curve.

## Training cycles (Werft/Defense pattern)

Owner: `game/troops.py` — reuses `orbital_production_batch_capacity` + `production_job_duration_seconds` from `game/shipyard.py`.

```text
cycle_seconds = ceil(train_seconds × 0.975^(barracks_level − 1))
batch_capacity = orbital_production_batch_capacity(barracks_level)
order_duration = ceil(amount / batch_capacity) × cycle_seconds
```

Progressive delivery mid-order (same batch helpers as defense). No frontend formula.

## Flow

1. Train troops on planet via Barracks → `troop_queue` → `planet_troops`.
2. Load troops onto outbound `attack` fleet (`fleet_movements.troops_json`).
3. Orbital `simulate_battle` as today.
4. If attacker wins **and** `troops_json` non-empty → `simulate_ground_raid`.
5. Win → `apply_vault_steal`; Fail → survivors ~5–10%, no steal, bad-news report.

## Schema

- `planet_troops (planet_id, troop_key, amount)`
- `troop_queue` (defense-queue pattern)
- `fleet_movements.troops_json`

## APIs

| Route | Role |
|-------|------|
| `GET /api/troops/state` | Stock + queue + capacity |
| `POST /api/troops/train` | `{ troop_key, amount }` → `{ ok, state }` |
| `POST /api/troops/cancel` | Cancel queue head/job |
| `GET /api/troop-units/<troop_key>` | Technical detail modal (HTML partial) |
| Fleet send | optional `troops` map on attack |

## Architecture

- No parallel combat/fleet/inventory/timekeeper engines.
- Barracks keeps `shipyard_time_speed` +2%/level; troop training is additional.
- Planet scope: troops per planet; steal hits defender **account** meta (by design).
