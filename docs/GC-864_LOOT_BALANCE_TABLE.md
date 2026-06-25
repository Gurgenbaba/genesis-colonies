# GC-864 — Loot Balance Table

> Auto-generated from `game/inventory_loot.py`.
> **Meta-only:** boosters, fragments, items, containers — no resources/ships/defense.

## Container overview

| Container | Entries | Total weight | Jackpots ≤2% | Economy drops |
|-----------|---------|--------------|--------------|---------------|
| `container_basic` | 5 | 100 | 1 ok | no |
| `container_rare` | 7 | 100 | 1 ok | no |
| `container_epic` | 8 | 91 | 1 ok | no |
| `container_relic` | 7 | 100 | — | no |
| `container_wreckage` | 5 | 100 | 1 ok | no |
| `container_research_cache` | 7 | 100 | 1 ok | no |
| `container_military_cache` | 6 | 100 | — | no |
| `container_event_special` | 9 | 100 | 2 ok | no |
| `container_mythic` | 5 | 100 | 1 ok | no |
| `container_ancient_relic` | 4 | 100 | — | no |
| `container_void_artifact` | 5 | 100 | — | no |

## Duplicate reward audit (3+ pools)

| Reward | Pools | Containers |
|--------|-------|------------|
| `fragment_artifact_alpha` (item) | 5 | `container_rare`, `container_epic`, `container_research_cache`, `container_military_cache`, `container_event_special` |
| `artifact_core_fragment` (item) | 4 | `container_relic`, `container_mythic`, `container_ancient_relic`, `container_void_artifact` |
| `fragment_genesis` (item) | 4 | `container_relic`, `container_mythic`, `container_ancient_relic`, `container_void_artifact` |
| `fragment_quantum` (item) | 4 | `container_relic`, `container_mythic`, `container_ancient_relic`, `container_void_artifact` |
| `mythic_genesis_core` (item) | 4 | `container_relic`, `container_mythic`, `container_ancient_relic`, `container_void_artifact` |
| `booster_build_1h` (booster) | 3 | `container_epic`, `container_military_cache`, `container_event_special` |
| `container_relic` (item) | 3 | `container_epic`, `container_event_special`, `container_mythic` |
| `fragment_dna_epic` (item) | 3 | `container_epic`, `container_relic`, `container_event_special` |
| `research_data_energy` (item) | 3 | `container_basic`, `container_rare`, `container_research_cache` |

## Drops by rarity (ITEM_CATALOG)

### `container_basic`

- **common**: booster:booster_build_5m ×1 (30.0%); item:fragment_dna_common ×1–2 (28.0%); booster:booster_research_5m ×1 (25.0%)
- **uncommon**: item:research_data_energy ×1 (15.0%); item:container_rare ×1 (2.0%)

### `container_rare`

- **uncommon**: booster:booster_build_15m ×1–2 (20.0%); booster:booster_research_15m ×1–2 (18.0%); item:research_data_mining ×1 (15.0%); item:research_data_energy ×1 (10.0%)
- **rare**: item:fragment_dna_rare ×1–2 (25.0%); item:fragment_artifact_alpha ×1 (10.0%)
- **epic**: item:container_epic ×1 (2.0%)

### `container_epic`

- **rare**: booster:booster_build_1h ×1–2 (19.8%); booster:booster_research_1h ×1–2 (19.8%); booster:booster_shipyard_1h ×1 (15.4%); item:fragment_alien ×1–2 (13.2%); item:fragment_artifact_alpha ×1–2 (13.2%); item:evo_planet_xp_5000 ×1 (11.0%)
- **epic**: item:fragment_dna_epic ×1 (6.6%)
- **legendary**: item:container_relic ×1 (1.1%)

### `container_relic`

- **epic**: item:fragment_quantum ×1–2 (12.0%); item:fragment_dna_epic ×1 (4.0%)
- **legendary**: booster:booster_build_24h ×1 (16.0%); booster:booster_research_24h ×1 (16.0%); item:artifact_core_fragment ×1–2 (18.0%); item:fragment_genesis ×1–3 (20.0%); item:mythic_genesis_core ×1 (14.0%)

### `container_wreckage`

- **common**: item:fragment_dna_common ×1–2 (18.0%); booster:booster_build_5m ×1 (10.0%)
- **uncommon**: item:fragment_wreck_reactor ×1–3 (35.0%); item:fragment_wreck_hull ×1–3 (35.0%); item:container_rare ×1 (2.0%)

### `container_research_cache`

- **uncommon**: booster:booster_research_15m ×1–2 (24.0%); item:research_data_energy ×1 (16.0%); item:research_data_weapons ×1 (14.0%)
- **rare**: booster:booster_research_1h ×1 (18.0%); item:fragment_dna_rare ×1–2 (14.0%); item:fragment_artifact_alpha ×1 (12.0%)
- **legendary**: item:research_instant_level ×1 (2.0%)

### `container_military_cache`

- **uncommon**: booster:booster_shipyard_15m ×1–2 (20.0%); item:fleet_computer ×1 (17.0%)
- **rare**: booster:booster_build_1h ×1–2 (22.0%); booster:booster_shipyard_1h ×1 (18.0%); item:fragment_artifact_alpha ×1 (11.0%)
- **epic**: item:fleet_hyperdrive_module ×1 (12.0%)

### `container_event_special`

- **rare**: booster:booster_production_50 ×1 (18.0%); item:fragment_artifact_alpha ×1 (10.0%); booster:booster_build_1h ×1 (10.0%)
- **epic**: item:expo_alien_relic ×1 (18.0%); item:fragment_dna_epic ×1 (14.0%); item:fleet_hyperdrive_module ×1 (14.0%)
- **legendary**: item:placeholder_special_item ×1 (12.0%); item:container_relic ×1 (2.0%); item:mythic_ancient_nexus ×1 (2.0%)

### `container_mythic`

- **epic**: item:fragment_quantum ×1–2 (8.0%)
- **legendary**: item:fragment_genesis ×1–2 (45.0%); item:artifact_core_fragment ×1–2 (30.0%); item:mythic_genesis_core ×1 (15.0%); item:container_relic ×1 (2.0%)

### `container_ancient_relic`

- **epic**: item:fragment_quantum ×1–2 (35.0%)
- **legendary**: item:artifact_core_fragment ×1–2 (40.0%); item:fragment_genesis ×1–2 (17.0%); item:mythic_genesis_core ×1 (8.0%)

### `container_void_artifact`

- **epic**: item:expo_alien_relic ×1 (20.0%); item:fragment_quantum ×1–2 (8.0%)
- **legendary**: item:fragment_genesis ×1–3 (35.0%); item:mythic_genesis_core ×1 (25.0%); item:artifact_core_fragment ×1–2 (12.0%)

---

_Regenerate: `python scripts/gen_loot_balance_table.py`_