# Imperial Directives — Genesis Colonies

> **Imperial Directives sind persönliche operative Befehle des High Command — kein Daily-Quest-System, kein paralleles Fortschrittssystem.**  
> Fortschritt entsteht ausschließlich aus bestehenden Gameplay-Events. Belohnungen werden aktiv abgeholt.

Epic: **EPIC-17 Imperial Directives** · Status: 📋 Design / Master-Doc · Stand: v1.0 (2026-06-27)

---

## Kernthese

Jeder Spieler erhält regelmäßig **3 Daily Directives** und **1 Weekly Directive** vom High Command. Sie:

- fördern Economy, Science, Fleet, Military und Exploration,
- skalieren automatisch anhand des Imperiums (`player_scores.total_score`),
- belohnen normales Spielen (Gebäude, Forschung, Flotte, Kampf, Expeditionen),
- erzeugen **kein Pflichtgefühl** — unvollständige Direktiven verfallen beim Reset.

```text
Gameplay-Event (Build finish, Combat, Expedition, …)
        │
        ▼
game/directives/progress.py  →  player_directives.progress
        │
        ▼
Live-State + Imperial-Directives-Seite (Anzeige only)
        │
        ▼
POST claim → inventory (Container + Booster)
```

---

## Abgrenzung (GC-000)

| System | Scope | Verwechslungsgefahr |
|--------|-------|---------------------|
| **Galactic Directives** (`game/galactic_directives/`) | Galaxie, Community-Abstimmung, Makro-Politik | **Anderer Name, anderer Owner** — EPIC-16 |
| **Imperial Directives** (`game/directives/`) | Account, persönliche Befehle | Dieses Dokument — EPIC-17 |
| **Chronicles** (`game/chronicle_entries.py`) | Archiv / Historie | Kein Fortschritt, kein Claim |
| **Vote Rewards** (`game/vote_rewards.py`) | Externe Vote-Postbacks | Kein Gameplay-Tracking |
| **Planet Evolution Quests** | Planet-Scope, DNA-Slots | Account-weite Imperiums-Befehle ≠ PE-Queue |
| **Genesis Story Ops** (`game/story/`) | Persistente Lore-Arcs / Side Ops, Transmission-UI | **Anderer Owner** — teilt nur den Gameplay-Event-Bus (Fan-out); kein Daily-Ops-Duplikat — [GENESIS_STORY_OPS.md](GENESIS_STORY_OPS.md) |

**Verboten:**

- `Accept` / `Track` / `Start`-Buttons — Direktiven sind immer aktiv
- Frontend-Zielberechnung oder Skalierung (Regel 16)
- Eigenes Polling/Tick für Directive-Fortschritt
- Paralleles Daily-Quest-Modul neben `game/directives/` (Story Ops = eigene Domäne EPIC-25, nicht Daily-Ops)
- Änderungen an Queue-Engine oder parallele Queue-Typen
- Verwechslung mit `galactic_directives` in UI-Texten (i18n: `imperial_directives_*` vs. `galactic_directives_*`)

---

## Spielregeln

| Regel | Wert |
|-------|------|
| Daily Directives pro Spieler | 3 |
| Weekly Directives pro Spieler | 1 |
| Daily Reset | alle 24 h (UTC-Anker, siehe Generator) |
| Weekly Reset | 1× pro Woche (Montag 00:00 UTC, Vorschlag) |
| Verfall | Nicht abgeschlossene Direktiven beim Reset ersetzt |
| Claim | Manuell; nach Claim bleibt Karte sichtbar bis Reset (`status=claimed`) |
| Legendary-Rarity | ~1–2 % bei Daily-Roll |

---

## Kategorien & Objective-Keys

Exploration ist Phase 1 Teil von **Fleet**; eigene Kategorie optional in Phase 2.

### Economy

| Objective key | Event-Quelle |
|---------------|--------------|
| `upgrade_buildings` | `buildings.complete_finished_builds_for_planet` |
| `produce_metal` | Ressourcen-Tick / produzierte Menge (account-summiert) |
| `produce_crystal` | wie oben |
| `produce_fuel_cells` | wie oben |
| `spend_resources` | Build/Research/Shipyard/Defense-Kosten bei Queue-Start |
| `upgrade_storages` | Build finish, Filter `storage_*` |
| `upgrade_solar_plants` | Build finish, Filter `solar_plant` |
| `upgrade_fuel_plants` | Build finish, Filter `fuel_cell_plant` |

### Science

| Objective key | Event-Quelle |
|---------------|--------------|
| `start_research` | Research queue enqueue |
| `complete_research` | `research.complete_finished_research` |
| `upgrade_mining_tech` | complete_research, tech-Filter |
| `upgrade_energy_tech` | complete_research, tech-Filter |
| `upgrade_navigation_tech` | complete_research, tech-Filter |
| `spend_research_resources` | Research queue cost snapshot |

### Fleet

| Objective key | Event-Quelle |
|---------------|--------------|
| `launch_expeditions` | Fleet send, mission=expedition |
| `complete_expeditions` | Expedition report / fleet return |
| `send_fleet_missions` | Fleet send (any mission) |
| `recycle_debris` | Recycle mission complete |
| `build_ships` | Shipyard queue finish |

### Military

| Objective key | Event-Quelle |
|---------------|--------------|
| `win_battles` | Combat resolver, attacker win |
| `destroy_enemy_ships` | Combat losses (defender ships) |
| `destroy_enemy_defense` | Combat losses (defense) |
| `build_defense` | Defense queue finish |
| `build_combat_ships` | Shipyard finish, combat hull filter |
| `defeat_pirates` | Expedition/combat, NPC tag |
| `deal_world_boss_damage` | World Boss contribution damage (EPIC-20) |

### Exploration (Fleet-Subphase 1)

| Objective key | Event-Quelle |
|---------------|--------------|
| `trigger_expedition_events` | `expedition_events` outcome |
| `find_rare_loot` | Expedition loot rarity |
| `recover_ancient_technology` | Expedition event type |
| `salvage_ancient_ships` | Expedition event type |

---

## Seltenheit & Belohnungen

| Rarity | Daily-Schwierigkeit | Container (kanonisch) | Booster |
|--------|---------------------|------------------------|---------|
| `common` | leicht | `container_basic` | klein (z. B. `booster_build_5m`) |
| `rare` | mittel | `container_rare` | mittel (z. B. `booster_build_15m`) |
| `epic` | schwer | `container_epic` | mehrere / stärker |
| `legendary` | sehr selten | `container_relic` | optional + Jackpot |

Weekly: gleiche Rarity-Tabelle, **höhere Skalierung** (Multiplikator in `scaling.py`) und mindestens Rare-Baseline.

Belohnungen werden über **`game/inventory.grant_inventory_item`** ausgegeben — keine neuen Parallel-Loot-Tabellen.

Langfristige Kosmetik (Commander Titles, Banners, Tokens): Phase 3 — nicht in GC-911–914.

---

## Skalierung (serverseitig)

**Anker:** `player_scores.total_score` via `game/ranking.get_player_score_cached()` (nicht Frontend, nicht Session).

```python
# Konzept — Implementierung in game/directives/scaling.py
target = floor(base_target * (max(total_score, score_floor) / score_anchor) ** scale_exponent)
target = clamp(target, min_target, max_target_for_key)
```

| Parameter | Rolle |
|-----------|--------|
| `base_target` | pro Objective-Key + Rarity in `definitions.py` |
| `score_anchor` | Universe-Default (z. B. 20_000 — „Midgame“-Referenz) |
| `score_floor` | verhindert Zero/NaN für Neulinge |
| `scale_exponent` | 0.45–0.65 je Kategorie (Produce ~0.58) |
| Weekly multiplier | z. B. 5×–10× Daily-Ziel |

Beispiele aus Vision (Qualitätsziel für Tests):

- 20k Punkte → Produce ~150k Ferronit
- 500M Punkte → Produce ~45M Ferronit
- 300B Punkte → Produce ~3.8B Ferronit

Kalibrierung: `tests/test_imperial_directives_scaling.py` gegen Ankerkurven.

---

## Architektur

### Owner-Modul (Regel 17)

| Domäne | Owner |
|--------|--------|
| Definitionen, Generator, Skalierung, Progress, Rewards, Claim | `game/directives/` |
| Live-State-Slice | `game/live_state.py` + `app.py` `_build_game_state_payload` |
| Route + Template | `app.py`, `templates/imperial_directives.html` |
| Container/Booster-Ausgabe | `game/inventory.py` (Consumer) |

### Modulstruktur

```text
game/directives/
    __init__.py
    definitions.py    # objective keys, categories, rarity weights, base targets
    generator.py      # daily/weekly roll, expiry, idempotent reset
    scaling.py        # imperium score → target value
    progress.py       # on_event hooks, idempotent increments
    rewards.py        # rarity → container + booster mapping, claim
    service.py        # player-facing state, ensure_generated, claim API
```

### Datenbank (Migration `080_imperial_directives.sql`)

**`directive_definitions`** — statische Katalogzeilen (seed in Migration)

| Spalte | Typ |
|--------|-----|
| `key` | TEXT PK |
| `category` | TEXT |
| `cadence` | `daily` \| `weekly` \| `both` |
| `objective_kind` | `count` \| `accumulate` |
| `base_target` | INTEGER |
| `scale_profile` | TEXT |
| `weight` | INTEGER |
| `min_rarity` | TEXT |
| `max_rarity` | TEXT |
| `filters_json` | TEXT |

**`player_directives`** — aktive Instanz pro Spieler

| Spalte | Typ |
|--------|-----|
| `id` | INTEGER PK |
| `player_id` | INTEGER |
| `definition_key` | TEXT |
| `cadence` | TEXT |
| `rarity` | TEXT |
| `target_value` | INTEGER |
| `progress_value` | INTEGER |
| `status` | `active` \| `completed` \| `claimed` \| `expired` |
| `reward_json` | TEXT |
| `period_key` | TEXT (z. B. `daily:2026-06-27`) |
| `expires_at` | INTEGER |
| `completed_at` | INTEGER NULL |
| `claimed_at` | INTEGER NULL |

Index: `(player_id, cadence, period_key)`.

**`directive_progress`** — optional Audit/Idempotenz für Event-Dedup

| Spalte | Typ |
|--------|-----|
| `id` | INTEGER PK |
| `player_directive_id` | INTEGER |
| `source_event_id` | TEXT UNIQUE |
| `delta` | INTEGER |
| `created_at` | INTEGER |

> Keine separate `directive_rewards`-Tabelle in Phase 1 — Belohnung in `player_directives.reward_json` + Claim über Inventory.

---

## Event-Integration (kein Polling)

Zentraler Entry:

```python
from game.directives.progress import apply_directive_events

apply_directive_events(
    player_id,
    events=[{"kind": "build_complete", "building_type": "metal_mine", "amount": 1, "source_event_id": "build:123"}],
    conn=conn,
)
```

**Hook-Punkte (Ticket GC-912A/B):**

| Modul | Funktion |
|-------|----------|
| `game/buildings.py` | nach Build-Finish |
| `game/research.py` | enqueue + finish |
| `game/shipyard.py` / `shipyard_queue.py` | finish |
| `game/defense.py` | finish |
| `game/combat.py` | battle resolved |
| `game/fleet.py` | send + mission complete |
| `game/expedition_events.py` | event outcome |
| `game/resources.py` | produzierte Ressourcen-Delta (accumulate objectives) |

Hooks sind **best-effort innerhalb derselben DB-Transaction** wie die auslösende Mutation.

---

## API & Live-State

### Game-State-Slice

```json
"imperial_directives": {
  "ready": true,
  "daily_reset_at": 1719504000,
  "weekly_reset_at": 1719792000,
  "claimable_count": 1,
  "directives": [ { "id", "category", "rarity", "title_key", "description_key", "progress", "target", "status", "expires_at", "rewards_preview": [] } ]
}
```

Generierung lazy bei erstem `/api/game-state` oder Page-Load nach Reset (`service.ensure_player_directives`).

### Actions

| Route | Body | Response |
|-------|------|----------|
| `POST /api/imperial-directives/claim` | `{ "directive_id": N, "request_id": "…" }` | `{ ok, state }` |
| `POST /api/imperial-directives/claim-all` | `{ "request_id": "…" }` | `{ ok, state }` |

Frontend: `GC.fetchGameAction` → `applyActionState()`.

### Page

- Route: `/imperial-directives`
- Template: `templates/imperial_directives.html`
- Design: High-Command-Terminal (`.gc-panel`, Directive Cards, Progress aus Server)
- Nav: Meta-Sidebar oder Imperium-Section — Badge via `nav_badges_for_game_state`

---

## UI — Directive Card

Pflichtfelder pro Karte:

- Kategorie (Icon + Label)
- Schwierigkeit / Rarity
- Fortschrittsbalken (`progress/target` vom Server)
- Beschreibung (i18n mit interpoliertem `target_value`)
- Belohnungs-Vorschau (Container-Image aus `inventory_catalog`)
- Restzeit (`expires_at` — Countdown Client aus Server-Timestamp)

States:

| status | UI |
|--------|-----|
| `active` | Progress bar |
| `completed` | **CLAIM REWARD** Button |
| `claimed` | Abgeschlossen-Häkchen, kein Button |
| `expired` | Ausgegraut (nur bis Reset sichtbar, dann ersetzt) |

---

## Ticket-Zerlegung (EPIC-17)

**Nicht als Ganzes implementieren.**

| Ticket | Fokus | Max. Dateien |
|--------|-------|--------------|
| **GC-910** | Master-Doc (dieses Dokument) + EPICS-Eintrag | Docs |
| **GC-911A** | Migration + `definitions.py` + `generator.py` + `scaling.py` | 4–5 |
| **GC-911B** | `service.py` + lazy generate + Unit-Tests Generator/Scaling | 3–4 |
| **GC-912A** | `progress.py` + Hooks Economy/Science | 4–5 |
| **GC-912B** | Hooks Fleet/Military/Exploration | 4–5 |
| **GC-913** | `rewards.py` + Claim API + Inventory-Grant | 3–4 |
| **GC-914A** | Live-State + nav badge + game-state tests | 3–4 |
| **GC-914B** | Page UI + i18n (alle 8 Locales) + PJAX init | 4–5 |

Empfohlene Reihenfolge: **910 → 911A → 911B → 912A → 912B → 913 → 914A → 914B**.

---

## Tests (Pflicht pro Ticket)

| Ticket | Tests |
|--------|-------|
| GC-911A/B | `tests/test_imperial_directives_generator.py`, `tests/test_imperial_directives_scaling.py` |
| GC-912A/B | `tests/test_imperial_directives_progress.py` — realistische Fixtures, kein Mock der Queue-Engine |
| GC-913 | Claim idempotent, inventory grant, `{ ok, state }` |
| GC-914A | `tests/test_game_state_live.py` slice, nav badge |
| GC-914B | `tests/test_imperial_directives_page.py` — PJAX route, card markup |

---

## Referenz-Docs

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regeln 15–17
- [STATE_AJAX.md](STATE_AJAX.md) — Live-State, kein Modul-Polling
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — Actions, Cleanup
- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) — Container/Booster (GC-540 / GC-864)
- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Imperiums-Framing
- [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) — **Nicht mischen**

---

## Ergebnis (Epic-Ziel)

Spieler erleben operative High-Command-Befehle statt einer Quest-Liste. Das System:

- skaliert über das gesamte Spiel,
- belohnt normales Spielen über Event-Hooks,
- nutzt bestehendes Inventar/Loot,
- integriert sich in `/api/game-state` ohne Parallel-Polling.
