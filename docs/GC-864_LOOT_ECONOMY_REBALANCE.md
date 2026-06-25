# GC-864 — Lootbox Economy Rebalance

> Epic: EPIC-04 Economy  
> Status: **done** (meta-only cut)

---

## Problem

Lootboxen konnten die Economy direkt beeinflussen (Ressourcen, Schiffe, Defense) und mussten bei jedem Economy-Rework neu balanciert werden.

## Entscheidung (Alpha)

**Lootboxen sind ein Meta-/Progression-System — keine Economy-Druckmaschine.**

| Erlaubt | Verboten |
|---------|----------|
| Booster | `metal`, `crystal`, `fuel_cells` |
| DNA-/Artefakt-Fragmente | Schiffe |
| Forschungs-Items | Verteidigung |
| Container / Keys | |
| Utility- / Event-Items | |

## Implementierung

- `LOOT_POOLS` — nur `item` / `booster`
- `sanitize_loot_pool()` — filtert Admin-Overrides
- `_apply_rewards()` — Gutschrift nur ins Inventar
- `inventory_admin` — validiert nur Meta-Rewards

Keine zweite Loot-Engine. Expedition-/Combat-Loot unverändert.

## Betroffene Dateien

- `game/inventory_loot.py`
- `game/inventory.py`
- `game/inventory_admin.py`
- `game/economy_balance.py` (Balance-Tabelle)
- `docs/ECONOMY_SYSTEM.md`
- `docs/GC-864_LOOT_BALANCE_TABLE.md`
- `locales/en.json`, `locales/de.json`
- `tests/test_gc864_loot_economy_rebalance.py`
- `tests/test_inventory_containers.py`
- `tests/test_admin_control_center.py`

## Tests

```bash
python -m pytest tests/test_gc864_loot_economy_rebalance.py tests/test_inventory_containers.py -q
python scripts/gen_loot_balance_table.py
```

## Ausgabe (nach Abschluss)

- Root Cause
- Changed Files
- Tests
- Ergebnis
