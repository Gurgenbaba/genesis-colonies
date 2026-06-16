# GC-620B — Locale Reality Sync

## Ziel

Sichtbare Texte passen zum echten Projektstand. Keine UI-Lügen mehr für live Features.

## Geänderte Keys (Auszug)

| Key | Korrektur |
|-----|-----------|
| `fleet_mission_hint_attack` | Combat live beschrieben |
| `logistics_tab_distribute_soon` | Distribute live |
| `defense_placeholder_note` | Defense/Combat live |
| `galaxy_colony_target_hint` | Seed-Ark-Kolonisierung live |
| `strategic_world_inspector_*` | Expedition/Kolo/Bergung live |
| `world_map_inspector_foreign_hint` | DEV Preview ehrlich |
| `fleet_ship_*_desc` | Phase-2-Lügen entfernt |

Vollständige Liste: `tests/test_gc620b_locale_reality_sync.py` → `GC620B_SYNCED_KEYS`.

## Stable vs DEV Preview

**Stable:** Buildings, Research, Fleet, Combat, Defense, Logistics, Auction, Vote, Galaxy, Kolonisierung, Expeditionen, Bergung, Spionage.

**DEV Preview:** Command-Map-Missionen aus Inspector (GC-598), Foreign Nodes (GC-597E), Galactic Politics / Skilltree / Premium / Alliance Placeholder.

## Tests

```bash
python -m pytest tests/test_locale_keys.py tests/test_gc620b_locale_reality_sync.py -q
```

## Status

✅ Erledigt
