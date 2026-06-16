# GC-582 — Dynamic Colonization (World Map)

> **Epic:** EPIC-15 · **Status:** 📋 Spec · **Stand:** 2026-06-13  
> **Voraussetzung:** GC-581 Strategic Worlds ✅ · Weltkarte visuell + Inspector ✅

Die **Command Map** wird zur Hauptansicht von Genesis Colonies. Kolonisierung darüber ist kein UI-Trick, sondern das **Fundament für die nächsten 20 Imperium-Features** (Rollen, Expeditionen, Influence, Handel, Territorium).

---

## Kernthese

```text
Nicht:  Galaxy → System → Slot 7 → Kolonisieren
Sondern: Weltkarte → Strategic World → Kolonisieren → Flotte → Kolonie → Map aktualisiert
```

Keine Fake-Kolonie. Es entsteht ein **echter Planet** mit bestehendem Planet-Scope, Queues, Fleet, DNA — erweitert um **Weltkoordinaten und Rolle**.

---

## Phase 1 — Strategic Worlds besiedeln (MVP)

### Flow

```text
Strategic World (world_field, unclaimed)
    ↓ Inspector: „Kolonisieren“
    ↓ POST Action (world_key + colony_name + origin_planet_id)
    ↓ Fleet mission colonize → world target (nicht nur G:S:P-Slot)
    ↓ Ankunft (bestehend: fleet.py colonize handler)
    ↓ colonize_planet() + world binding
    ↓ Strategic World → colony node auf Map
    ↓ applyActionState — kein Full Reload
```

### Bestehende Systeme erweitern (Regel 15)

| System | Heute | GC-582 |
|--------|-------|--------|
| `colonize_planet()` | `galaxy/system/position` + DNA | + `world_x/world_y`, `sector_x/y`, `planet_role`, `origin_world_id` |
| `game/fleet.py` | `colonize` → leerer Galaxy-Slot | + Target `world_field_key` / world coords |
| `strategic_worlds.py` | Präsentation | + `colonizable`, `claimed_by`, bindbare Metadaten |
| `world_map.py` | Generiert freie Felder | Entfernt/ersetzt Feld nach Claim; zeigt Kolonie |
| Legacy `/galaxy?view=system` | Unverändert | **Nicht anfassen** |

Kein paralleles `colonize_v2`, kein zweites Fleet-Modul.

---

## Datenmodell (Migration erforderlich)

Neue Spalten auf `planets` (kanonisch, eine Wahrheit):

| Spalte | Typ | Bedeutung |
|--------|-----|-----------|
| `world_x` | REAL NULL | Command-Map-Weltposition |
| `world_y` | REAL NULL | Command-Map-Weltposition |
| `sector_x` | INTEGER NULL | `sector_grid.sector_coords()` |
| `sector_y` | INTEGER NULL | `sector_grid.sector_coords()` |
| `planet_role` | TEXT NULL | z. B. `mining_world`, `research_world` |
| `origin_world_id` | TEXT NULL | Strategic-World-Key vor Claim (`field:mining_world:1820:2140`) |

Neue Tabelle **`world_claims`** (oder JSON auf `planets` — bevorzugt Tabelle für Multiplayer):

| Spalte | Bedeutung |
|--------|-----------|
| `world_key` | PK — deterministischer Strategic-World-Key |
| `planet_id` | FK → `planets.id` |
| `player_id` | Besitzer |
| `claimed_at` | Timestamp |

Homeworld / Legacy-Kolonien: `world_x/y` NULL → weiter über Empire-Cluster-Layout; nur Map-Kolonien aus Strategic Worlds tragen Weltbindung.

---

## Planetenrollen (Phase 1 Präsentation, Phase 2 Effekte)

Rollen kommen aus `strategic_worlds.world_type` beim Claim — **kein Zufall**.

| Kategorie (Spieler-Sprache) | `world_type` / `planet_role` | Versprechen (581) | Später (EffectResolver) |
|-----------------------------|------------------------------|-------------------|-------------------------|
| Bergbauwelt | `mining_world` | + Ferronit | Produktion Ferronit |
| Industriewelt | `industrial_world` | + Schiffsbau | Bauzeit Werft |
| Forschungswelt | `research_world` | + Forschung | Research speed |
| Militärwelt | `fortress_world` | + Verteidigung | Defense bonus |
| Handelswelt | `trade_world` *(582 neu)* | + Handel | Trade range |
| Reliktwelt | `ruins_world` | Antike Strukturen | Spezialtech |
| Anomalie | `anomaly_zone` | Energie-Signatur | Expedition hook |
| Expeditionswelt | `expedition_zone` | Missionen | GC-583 only |
| Wrackfeld | `wreckage_field` | Bergung | GC-583 salvage |

**Phase 1:** Rolle in DB + Inspector + Kolonie-Panel — Hints aus GC-581, **keine echten Boni** (wie Expansion Sites).  
**Phase 2 (GC-582B):** `EffectResolver`-Hooks pro `planet_role` — siehe [EFFECTS.md](EFFECTS.md).

Beispiel Inspector nach Kolonisierung:

```text
Helios Prime · Bergbauwelt
+ Ferronit · − Forschung (Hints)
```

---

## Strategic World Kategorien (fest, nicht zufällig)

GC-581 liefert bereits deterministische Typen pro `(world_x, world_y)`. GC-582:

1. **`trade_world`** als 9. Kolonisierbare Kategorie ergänzen (Locale + `STRATEGIC_WORLD_TYPE_DEFS`).
2. **`expedition_zone`**, **`anomaly_zone`**, **`wreckage_field`**: Phase 1 **nicht kolonisierbar** → Inspector zeigt „Expedition“ (disabled bis GC-583).
3. Claim prüft: `world_type in COLONIZABLE_WORLD_TYPES`.

```python
COLONIZABLE_WORLD_TYPES = (
    "mining_world", "industrial_world", "research_world",
    "fortress_world", "trade_world", "ruins_world",
)
```

---

## API & UI (Phase 1)

### Action

`POST /api/world-map/colonize` (oder Erweiterung `/api/fleet/send` mit `target_world_key`)

Request:

```json
{
  "world_key": "field:mining_world:1820:2140",
  "colony_name": "Helios Prime",
  "origin_planet_id": 42,
  "ships": { "seed_ark": 1, "cargo_drone": 10 }
}
```

Response: `{ ok, state }` — [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md).

### Inspector (Strategic World, unclaimed)

- Button **Kolonisieren** → Fleet-Modal / Route zu Fleet mit Prefill (`world_key`, Zielname)
- Anzeige: Risiko, Rolle, Kolonie-Limit (`planet_limit`)

### Map nach Claim

- `world_field`-Node verschwindet an `(world_x, world_y)`
- Neuer `colony`-Node am selben Ort mit `planet_role`, Empire-Identity
- Influence/Edges neu berechnet (bestehende Pipeline)

---

## Ticket-Split (empfohlen)

| Ticket | Scope | Max Files |
|--------|-------|-----------|
| **GC-582A** ✅ | Migration + `world_claims` + `colonize_planet` world binding | migration, service, strategic_worlds |
| **GC-582B** ✅ | Fleet target `world_key` + Ankunft + Tests | fleet.py, app.py, world_colonization.py |
| **GC-582C** ✅ | Inspector „Kolonisieren“ + Fleet prefill + applyActionState | template, main.js, strategic_worlds |
| **GC-582D** ✅ | Map payload: claimed fields → colonies | world_map.py, command_map.py |
| **GC-582E** | `planet_role` Effects (optional, nach MVP) | effects/, strategic_worlds |

Nicht alles in einem PR.

---

## Folge: GC-583 Expedition Worlds

Welten die man **nicht kolonisieren**, sondern **erforschen**:

```text
Verlassene Sternenbasis · Alien-Artefakt · Ancient Vault · Wurmloch · Dyson-Wrack
```

| | GC-582 | GC-583 |
|---|--------|--------|
| Ziel | Eroberbar → echte Kolonie | Erkundbar → Bericht/Loot/Forschung |
| Typen | `COLONIZABLE_WORLD_TYPES` | `expedition_zone`, `anomaly_zone`, `wreckage_field` + dedizierte Sites |
| Fleet | `colonize` + Seed Ark | `expedition` Mission (bestehend erweitern) |
| Ergebnis | `planet_id` | Kein Planet — Expedition Report |

GC-582 legt `world_key`, Fleet-Target und Claim-Tabelle so an, dass GC-583 dieselbe Welt-Identität nutzt.

---

## Prioritäten (Imperium-Pfad)

```text
GC-582 Dynamic Colonization     ← jetzt
GC-583 Expedition Worlds
GC-566B Dynamic Influence
GC-584 Trade Routes
GC-571C Alliance Presence
GC-568 Territorial Warfare
```

Damit wird die Weltkarte das **Herzstück** — OGame-Galaxiebrowser bleibt Legacy, nicht Hauptweg.

---

## Explizit nicht in GC-582

- `/empire` umbauen
- `/galaxy?view=system` ändern
- Sector Loader / Background (580B/C)
- Dynamic Influence (566B)
- Echte Produktionsboni (→ 582E oder später)
- Alliance / Warfare

---

## Akzeptanz Phase 1 (582A–D)

- [x] **582A:** Migration `world_claims` + Planet-Spalten; `reserve_world_claim()`; colonizable validation
- [x] **582B:** Fleet target `world_key` + Ankunft → `colonize_planet()` + `complete_world_claim`
- [x] **582C:** Inspector „Kolonisieren“ + Fleet prefill
- [x] **582D:** Map payload — claimed field entfernt, Kolonie an `world_x/y`, Fremd-Claim als `foreign_world_colony`
- [x] Ankunft erzeugt echten `planets`-Row mit `world_x/y`, `planet_role`, `origin_world_key` (Fleet-Tests)
- [x] `world_claims` verhindert Doppel-Claim
- [x] Map zeigt Kolonie statt freiem Feld — gleiche Weltposition
- [x] Legacy Galaxy-Kolonisierung funktioniert weiter (ohne `world_key`)
- [x] Tests: claim, double-claim block, fleet arrival, map node swap
- [ ] Strategic World → Kolonisieren → Fleet (Seed Ark) — Browser-Smoke optional
- [ ] `{ ok, state }` + `applyActionState` bei direktem Map-POST (Fleet-Flow nutzt `/api/fleet/send`)

---

## Owner (Ziel §17)

| Domäne | Modul |
|--------|--------|
| Strategic World Metadaten + Kolonisierbarkeit | `game/planet_evolution/strategic_worlds.py` |
| Claim + Planet binding | `game/planet_evolution/world_colonization.py` *(neu, schmal)* |
| Planet INSERT erweitern | `game/planet_evolution/service.py` (`colonize_planet`) |
| Fleet Ankunft | `game/fleet.py` |
| Map nach Claim | `game/planet_evolution/world_map.py` |
| Inspector / Action UI | `templates/partials/galaxy_command_map_panel.html`, `static/main.js` |

**Check vor Implementierung:** [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §15–17, [FLEET_SYSTEM.md](FLEET_SYSTEM.md), [PLANET_SCOPE.md](PLANET_SCOPE.md).
