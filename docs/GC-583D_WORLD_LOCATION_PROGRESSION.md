# GC-583D — World Location Progression

**Status:** ✅ D1  
**Owner:** `game/planet_evolution/world_progress.py`

## Ziel

Expedition-Orte (`expedition_zone`, `anomaly_zone`, `ruins_world`) sammeln pro Spieler Bekanntheit durch abgeschlossene World-Expeditionen.

## Stufen

| Expeditionen | `familiarity_status` | UI |
|--------------|----------------------|-----|
| 0 | `unknown` | Unbekannt |
| 1+ | `mapped` | Kartografiert |
| 5+ | `stabilized` | Stabilisiert |
| 10+ | `outpost_prepared` | Außenposten vorbereitet |

## Persistenz

- Migration `059_world_progress.sql` — `(player_id, world_key)` → `expedition_count`
- Inkrement in `fleet.py` bei abgeschlossener World-Expedition (nach Status-Claim, vor Report)
- Salvage / Classic Slot-16: **kein** Increment

## Payload (Map-Nodes)

- `expedition_count`
- `familiarity_status`
- `familiarity_label_key`
- `next_milestone` (1 | 5 | 10 | null)

## UI

- Inspector: Bekanntheit + Fortschritt bis nächste Stufe
- Status-Zeile zeigt Bekanntheitsstufe statt generischem „Expeditionsziel“

## Out of scope (D1)

- EffectResolver / Boni
- Kolonisierung aus Progress
- Recycler / Außenposten-Gameplay

## Tests

- `tests/test_gc583d_world_progress.py`
