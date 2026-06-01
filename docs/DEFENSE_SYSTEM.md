# Defense System

Planet-scoped defensive structures (GC-410+). **No combat resolver** yet — persistence, definitions, ranking, and combat **data prep** (GC-416).

Kanonische Module: `game/defense_defs.py`, `game/combat_models.py`, `game/models.py` (planet_defense CRUD).

---

## Schema (Migration 039)

| Tabelle | Rolle |
|---------|-------|
| `planet_defense` | `(planet_id, defense_key, amount)` — Bestand pro Kolonie |

Gate: `defense_schema_ready()` — Features degradieren gracefully ohne Migration.

---

## Defense Units

Definiert in `game/defense_defs.py` (`DEFENSE_ORDER`):

| Key | Rolle |
|-----|-------|
| `sentinel_turret` | Leichtes Geschütz |
| `plasma_arc` | Mittleres Energiewehr |
| `ion_bastion` | Schweres Ionenwerk |
| `flak_array` | Flugabwehr-Batterie |
| `pulse_barrier` | Planetarer Schildemitter |
| `orbital_shield` | Orbitale Schutzkuppel |

Jede Definition enthält:

- `name_key` / `description_key` (i18n)
- `build_cost` (metal, crystal)
- `build_seconds` (Basis-Bauzeit für Queue)
- `requirements` (buildings, research)
- **Combat prep (GC-416):** `attack`, `shield`, `hull`, `score_value`, `rapid_fire_targets`

Bau-Gebäude: `defense_factory` ([BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md)).

---

## Combat preparation (GC-416)

**Keine Kampfberechnung.** Werte liegen im Datenmodell für einen späteren Resolver.

| Modul | Rolle |
|-------|-------|
| `game/combat_models.py` | Einheitlicher Zugriff: `CombatUnitStats`, `CombatStack`, `resolve_combat_unit()` |
| `game/defense_defs.py` | Rohdaten + `defense_combat_stats()` |
| `game/fleet_defs.py` | Schiffs-Rohdaten + `ship_combat_stats()` |

Resolver-API (read-only):

```python
from game.combat_models import combat_stats_for_defense, stacks_from_counts, COMBAT_UNIT_DEFENSE

stats = combat_stats_for_defense("flak_array")
# CombatUnitStats(attack=250, shield=0, hull=1200, score_value=23000, rapid_fire_targets={...})

stacks = stacks_from_counts(planet_defense_stock, unit_type=COMBAT_UNIT_DEFENSE)
```

`rapid_fire_targets`: Map Ziel-`unit_key` → Faktor (≥2). Semantik interpretiert der Resolver (Phase Combat).

Schiffe: gleiches Schema über `combat_stats_for_ship()` / `COMBAT_UNIT_SHIP`.

---

## Planet Scope

| Operation | Scope |
|-----------|-------|
| Bestand lesen | `get_planet_defense(planet_id)` |
| Bestand schreiben | `set_planet_defense` / `add_planet_defense` |
| Ranking | Summe über alle Planeten des Spielers |

Defense gilt **pro Planet**, analog zu `planet_ships`.

---

## Ranking

`compute_player_scores()` nutzt `score_value` pro Einheit (GC-414):

- Empire-Anteil Defense: `sum(amount × score_value)` über alle `planet_defense`-Zeilen
- Exponent aus `score_cost_exponent` (wie Fleet/Buildings)

Spalte `player_scores.score_defense` existiert seit Migration 014.

---

## Verboten / Nicht in dieser Phase

- Combat-Auflösung, Schaden, Fleet-Tick-Integration
- OGame-Namen oder parallele Fleet-/Building-Systeme

---

## Verwandte Docs

- [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) — `defense_factory`
- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — `planet_ships`, Schiffs-Combat-Prep
- [PLANET_SCOPE.md](PLANET_SCOPE.md) — aktiver Planet
- [EFFECTS.md](EFFECTS.md) — `weapon_tech` / `shield_tech` (prepared, kein Consumer)
