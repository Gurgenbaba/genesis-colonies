# Economy System

Ressourcen, Produktion, Trader Hub und Exchange (v1.5.3).

Formeln: autoritativ in `game/effects/effect_resolver.py` — siehe [EFFECTS.md](EFFECTS.md).

---

## Ressourcen

| Key | UI-Name | Storage cap | Scope |
|-----|---------|-------------|-------|
| `metal` | Ferronit | Ja (`metal_storage` + Tech) | Planet |
| `crystal` | Crytite | Ja (`crystal_storage` + Tech) | Planet |
| `fuel_cells` | Brennzellen | **Nein** (unbounded) | Planet |
| `energy_total` / `energy_used` | Energie | Derived, persisted | Planet |

**Kein Deuterium** — Fuel für Schiffe = `fuel_cells`.

Spalten auf `planets`; Gebäude-Level auf `planet_buildings` pro `planet_id`.

---

## Produktions-Tick

Entry: `update_planet_resources()` in `game/resources.py`

```
finish_due_work_once()          # optional, wenn nicht skip_queue_finish
elapsed = now - last_update
EffectResolver → rates, energy
apply_production_delta(metal, crystal)  # capped by storage
fuel_cells += delta                     # uncapped
save last_update, energy_*
evolution_tick_planet()         # wenn Schema ready
```

Aufgerufen von:

- `refresh_player_live_state()` — context planet für Poll
- Admin/Worker ticks
- Nach Queue-Finish (`sync_derived_state_after_queue_finish`)

---

## Energie

- **Supply:** `solar_plant` (+ `geothermal_nexus` via `solar_output_factor`)
- **Demand:** `metal_mine`, `crystal_mine`, `fuel_cell_plant`
- **Skalierung:** `energy_ratio = min(1, total/used)` drosselt alle Produktionsraten
- **`energy_tech`:** reduziert nur Minen-Verbrauch (`mine_energy_factor`, min 40%)

---

## Produktionsraten (EffectResolver)

| Ressource | Basis |
|-----------|-------|
| Metal | `0.04 × metal_mine^1.4 × metal_prod_factor` |
| Crystal | `0.03 × crystal_mine^1.35 × crystal_prod_factor` |
| Fuel cells | `20/h × fuel_cell_plant_level × 1.35^(level-1)` |

Modifier: `mining_tech`, `drone_tech`, `storage_tech`, Settings (`resource_speed`).

---

## Storage

- Basis 100.000 pro Typ (metal/crystal)
- Wachstum via Storage-Gebäude + `STORAGE_GROW^1.8`
- Multiplier: `storage_tech`, `terraformer`, `storage_factor`
- Produktion kann Storage nicht überschreiten; bestehendes Overflow wird nicht getrimmt

---

## Trader Hub (`/trader-hub`)

Seite mit drei Panels (Partials):

| Panel | Modul | API |
|-------|-------|-----|
| Metall ↔ Kristall | `game/exchange.py` | `POST /api/exchange` |
| Brennzellen kaufen | `game/fuel_exchange.py` | `POST /api/trader/fuel-exchange` |
| Schrottplatz | `game/scrapyard.py` | `POST /api/trader/scrapyard` |

Scope: **context planet** für Salden; Exchange-Tageslimit **pro Spieler**.

Poll liefert `exchange`, `fuel_exchange`, `scrapyard` in `/api/game-state`.

---

## Instant Exchange (Metal ↔ Crystal)

| Setting | Default |
|---------|---------|
| `exchange_enabled` | 1 |
| `exchange_rate_metal_to_crystal` | 0.8 |
| `exchange_rate_crystal_to_metal` | 0.8 |
| `exchange_daily_limit` | 500.000.000 |
| `exchange_min_amount` | 100 |

- Abbuchung vom context planet
- Gutschrift capped by storage capacity
- Log: `exchange_log`
- Migrationen: `024`, `025`

---

## Fuel Exchange

| Setting | Default |
|---------|---------|
| `fuel_exchange_enabled` | 1 |
| `fuel_exchange_metal_per_unit` | 45 |
| `fuel_exchange_crystal_per_unit` | 28 |
| `fuel_exchange_min_units` | 10 |
| `fuel_exchange_daily_units` | 5000 |

- Kosten: metal **und** crystal pro Einheit
- Tageslimit **pro Planet** (`fuel_exchange_daily_used`, Migration `031`)
- Kein Storage-Cap auf fuel_cells

---

## Scrapyard

Recycelt Schiffe vom context planet → Ressourcen-Rückerstattung nach `fleet_defs` / Scrapyard-Logik.

---

## Shipyard-Kosten

Schiffsbau zieht metal, crystal **und fuel_cells** ab (siehe [FLEET_SYSTEM.md](FLEET_SYSTEM.md)).

---

## Dateien

| Datei | Rolle |
|-------|-------|
| `game/resources.py` | Tick, deltas |
| `game/effects/effect_resolver.py` | Formeln |
| `game/exchange.py` | Metall/Kristall-Tausch |
| `game/fuel_exchange.py` | Brennzellen-Kauf |
| `game/scrapyard.py` | Recycling |
| `game/logic.py` | Poll-Fassade |
| `templates/trader_hub.html` | UI |

---

## Tests

```bash
python -m pytest tests/test_effects.py tests/test_exchange.py tests/test_fuel_exchange.py tests/test_scrapyard.py tests/test_fuel_cells_resource_bar.py tests/test_trader_hub.py -v
```
