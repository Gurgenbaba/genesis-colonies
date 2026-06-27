# GC-950A1 — Landkarte des Wissens (Informationsarchitektur)

> **Epic:** EPIC-16 Genesis Knowledge Base  
> **Status:** 📋 Architektur (kein Player-Text)  
> **Stand:** 2026-06-27  
> **Parent:** [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md)  
> **Nächster Schritt:** GC-950A2 — Player Blocks für P1-Artikel schreiben

Dieses Dokument ist die **Landkarte des Wissens**: welcher Artikel wohin gehört, **wann** der Spieler ihn sieht, und **wo** jede Art von Inhalt gepflegt wird. Kein Codex-Text — nur Struktur.

---

## Grundregel

> **Nichts wird erklärt, bevor es relevant wird.**

Analog zu Gameplay:

```text
Gameplay:  Nichts wird berechnet, bevor es gebraucht wird.  (Queue-Engine, finish_due_work_once)
Wissen:    Nichts wird erklärt, bevor es relevant wird.      (Codex-Unlock, Quick Help)
```

Der Codex wächst mit dem Imperium — gesperrte Bände zeigen einen **Teaser** (i18n-Key), keinen leeren Slot.

---

## Vier Schichten + Unlock

```text
Master Docs (Entwickler)
        │
        ▼
Player Article Blocks (+ unlock in YAML)
        │
        ▼
Knowledge Generator
        │
        ▼
Surfaces (mit Unlock-Filter zur Laufzeit)
```

**Codex-UI (Zielbild):**

```text
Genesis Codex

Band I — Erste Stunde
  ✓ Genesis Ark
  ✓ Ressourcen
  …

Band II — Frühes Imperium
  ✓ Planet Evolution
  🔒 Expansion
     „Schalte die erste Expansion Site frei (Genesis Ark Entwicklungsstufe 5).“

Band III — Operative Systeme
  🔒 Expeditionen
     „Entdecke eine Ancient World auf der Command Map.“
```

Quick Help und Context-FAQ folgen dem gleichen Unlock — **gesperrt = kein Panel**, nicht versteckter Spoiler.

---

## Source of Truth (global — keine Diskussion)

| Inhalt | Quelle | Nie hier |
|--------|--------|----------|
| **Gameplay-Mechanik** (Dev) | Master Doc (System-Abschnitt) | Codex, Wiki |
| **Spieler-Narrativ** | Player Article Block | `special_panel.html` hardcoded |
| **Begriffe** (Ferronit, Welt, …) | [GENESIS_TERMINOLOGY.md](GENESIS_TERMINOLOGY.md) | Freie Copy in Blocks |
| **Zahlen, ROI, Formeln** | `game/technical_data.py` | Codex, Player Blocks |
| **Produktions-/Kampf-Math** | `EffectResolver`, Domänen-Module | Frontend, Codex |
| **Tooltips** (generiert) | Generator → `locales/` | Handpflege parallel |
| **FAQ** | Player Block `## FAQ` | Support-Tickets als Quelle |
| **Commander Tips** | Player Block `## Commander Tips` | Random UI-Text |
| **Discord Guides** | Player Block `## Discord Summary` | Manuell in Discord |
| **Codex-Unlock** | Player Block YAML `unlock` + `game/codex.py` Resolver | Ad-hoc in Templates |

---

## Progression-Bands (Spieler-Reihenfolge)

Codex-Bände folgen **nicht** der Doc-Ordnerstruktur, sondern **wann Systeme relevant werden**.

| Band | Spieler-Phase | Typische Spielzeit | Kernfrage |
|------|---------------|--------------------|-----------|
| **I** | Erste Stunde | 0–60 min | Was ist Genesis? Was baue ich zuerst? |
| **II** | Frühes Imperium | Tag 1–3 | Wie wächst mein Imperium? |
| **III** | Operative Systeme | Tag 3–14 | Flotte, Kampf, Expeditionen, Wirtschaft |
| **IV** | Endgame | Wochen+ | Spezialisierung, Diplomatie, Ascension |

**P1-Artikel** = alle Zeilen mit `P1` in der Landkarte unten. GC-950A2 schreibt nur diese Blocks.

---

## Unlock-Typen (YAML + Runtime)

Erweiterung des Player-Block-Frontmatter (siehe [GC-950](GC-950_KNOWLEDGE_PIPELINE.md)):

```yaml
unlock:
  type: always | homeworld_level | expansion_site | interstellar_tech | building | research | route_visit | has_world_type | expansion_phase | player_flag
  value: 5                    # je nach type
  site_key: frontier_ix       # expansion_site
  building: orbital_shipyard  # building
  tech: interstellar_expansion
  route: trader_hub_view
  world_type: ruins_world
  phase: colony
  flag: first_expedition_complete
teaser_key: codex_unlock_expansion_teaser   # i18n wenn gesperrt
```

| `type` | Prüfung (Owner) | Code-Anker |
|--------|-----------------|------------|
| `always` | Account existiert | — |
| `homeworld_level` | Genesis Ark `planet_level` | `expansion_gates.get_homeworld_level` |
| `expansion_site` | Site auf Command Map sichtbar | `EXPANSION_SITES`, `is_expansion_site_unlocked` |
| `interstellar_tech` | Account-Tech-Stufe | `interstellar_expansion_level` |
| `building` | Gebäude auf aktivem Planet ≥ 1 | `get_planet_buildings` |
| `research` | Account-Tech ≥ Stufe | `get_research_levels` |
| `route_visit` | Spieler hat Route mindestens einmal geöffnet | `player_flags` / Session (GC-950B+) |
| `has_world_type` | Strategic World Typ auf Map | `strategic_worlds`, world map |
| `expansion_phase` | Welt in Phase | `expansion_phase.py` |
| `player_flag` | Persistierter Unlock | `player_unlocks` (optional GC-950B+) |

**Resolver-Owner (geplant):** `game/codex.py` → `is_codex_unlocked(player_id, codex_id)` — liest `generated/codex/unlocks.json` + Live-State.

---

## Landkarte — P1-Artikel (vollständige Matrix)

Spalten: **Doc** · **Band** · **Route** · **Surfaces** · **Unlock** · **Source of Truth** · **P1**

### Band I — Erste Stunde

| codex_id | Master Doc | Route (`endpoint` → Pfad) | Surfaces | Unlock | SoT (Narrativ) | P1 |
|----------|------------|---------------------------|----------|--------|----------------|-----|
| `genesis_ark` | [IMPERIUM_VISION.md](IMPERIUM_VISION.md) | `overview` → `/overview` | Quick Help, Codex, Tips | `always` | Player Block | ✓ |
| `overview` | [IMPERIUM_VISION.md](IMPERIUM_VISION.md) (Kurz) | `overview` → `/overview` | Quick Help | `always` | Player Block | ✓ |
| `resources` | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) | `overview`, `buildings_view` → `/overview`, `/buildings` | Quick Help, Codex, FAQ | `always` | Player Block + Terminology | ✓ |
| `buildings` | [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) | `buildings_view` → `/buildings` | Quick Help, Codex, FAQ, Tips | `always` | Player Block | ✓ |
| `research` | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) | `research_view` → `/research` | Quick Help, Codex, FAQ, Tips | `always` | Player Block | ✓ |

**Band I — Hinweise**

- `genesis_ark` = Identität der Genesis Ark (Homeworld), nicht generisches „Imperium“.
- `overview` = dünn: Imperium-Ziel in 2 Sätzen; Detail in `genesis_ark`.
- Ressourcen-Copy: **Ferronit / Crytite / Brennzellen** — nie Metall/Krytit ([GENESIS_TERMINOLOGY.md](GENESIS_TERMINOLOGY.md)).

---

### Band II — Frühes Imperium

| codex_id | Master Doc | Route | Surfaces | Unlock | SoT | P1 |
|----------|------------|-------|----------|--------|-----|-----|
| `planet_evolution` | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) | `planet_evolution_view` → `/planet-evolution` | Quick Help, Codex, FAQ, Tips, Discord | `always` | Player Block | ✓ |
| `planet_scope` | [PLANET_SCOPE.md](PLANET_SCOPE.md) | Header Switcher (alle Shell-Routen) | Quick Help, FAQ | `always` | Player Block | ✓ |
| `expansion` | [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) | `empire_view` → `/empire`, `galaxy_view` → `/galaxy` | Quick Help, Codex, FAQ, Tips, Discord | `homeworld_level: 5` **oder** `expansion_site: frontier_ix` | Player Block | ✓ |
| `command_map` | [GC-563_COMMAND_MAP_MVP.md](GC-563_COMMAND_MAP_MVP.md) | `empire_view` → `/empire` | Quick Help, Codex | `homeworld_level: 5` (Site-Gate) | Player Block | ✓ |
| `fleet` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) | `fleet_view` → `/fleet`, `shipyard_view` → `/shipyard` | Quick Help, Codex, FAQ, Tips | `building: orbital_shipyard` | Player Block | ✓ |
| `galaxy` | [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) | `galaxy_view` → `/galaxy` | Quick Help, Codex | `always` (Nav sichtbar) | Player Block | ✓ |

**Band II — Unlock-Anker (Code)**

- Erste Expansion: `EXPANSION_SLOT_GATES[0]` → Homeworld **L5** + Interstellar Expansion **L1** (`expansion_protocol.py`).
- Erste Expansion Site: `frontier_ix` → `required_homeworld_level: 5` (`expansion_gates.py`).
- Flotte: Orbitalwerft auf aktivem Planet (`orbital_shipyard`).

**Teaser-Keys (Vorschlag):**

- `codex_unlock_expansion_teaser` — „Schalte die erste Expansion Site frei (Entwicklungsstufe 5).“
- `codex_unlock_fleet_teaser` — „Baue eine Orbitalwerft, um Flotten zu entsenden.“

---

### Band III — Operative Systeme

| codex_id | Master Doc | Route | Surfaces | Unlock | SoT | P1 |
|----------|------------|-------|----------|--------|-----|-----|
| `expeditions` | [GC-583_EXPEDITION_WORLDS.md](GC-583_EXPEDITION_WORLDS.md) | `fleet_view` → `/fleet`, `empire_view` → `/empire` | Quick Help, Codex, FAQ, Tips, Discord | `expansion_site: ancient_relay` **oder** `has_world_type: ruins_world` | Player Block | ✓ |
| `trader` | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) (Trader Hub) | `trader_hub_view` → `/trader-hub` | Quick Help, Codex, FAQ | `route_visit: trader_hub_view` | Player Block | ✓ |
| `combat` | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) | `fleet_view` → `/fleet` | Quick Help, Codex, FAQ | `building: orbital_shipyard` + `player_flag: first_fleet_sent` | Player Block | ✓ |
| `defense` | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) | `defense_view` → `/defense` | Quick Help, Codex, FAQ | `building: defense_factory` | Player Block | ✓ |
| `logistics` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) (Logistics) | `fleet_view` → `/fleet?mode=collect` | Quick Help, FAQ | `building: orbital_shipyard` | Player Block | P2 |

**Band III — Hinweise**

- Expeditionen: Ancient Relay Site ab Homeworld **L10**; Ruins/Expedition-Zonen auf Strategic Worlds (`GC-583`).
- Trader: Nav-Modul `trading` ist prominent auf allen Welten — Unlock = **erster Besuch** `/trader-hub` (Spieler „entdeckt“ den Hub).
- Combat: nach erster Flottenmission (Flag in GC-950B persistieren).

**Teaser-Keys:**

- `codex_unlock_expeditions_teaser` — „Entdecke eine Ancient World oder Expedition-Zone auf der Command Map.“
- `codex_unlock_combat_teaser` — „Sende deine erste Flotte — dann öffnet sich der Kampf-Guide.“

---

### Band IV — Endgame

| codex_id | Master Doc | Route | Surfaces | Unlock | SoT | P1 |
|----------|------------|-------|----------|--------|-----|-----|
| `strategic_worlds` | [GC-581_STRATEGIC_WORLDS.md](GC-581_STRATEGIC_WORLDS.md) | `planet_evolution_view`, `empire_view` | Codex, FAQ | `expansion_phase: strategic_world` **oder** Homeworld L15+ | Player Block | ✓ |
| `diplomacy` | [GALACTIC_DIPLOMACY.md](GALACTIC_DIPLOMACY.md) | `galactic_politics` → `/galactic-politics` | Codex | `route_visit: galactic_politics_view` | Player Block | P1 |
| `ascension` | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) (Ascension) | `planet_evolution_view` | Codex, FAQ | Planet Ascension sichtbar / Queue aktiv | Player Block | P1 |
| `imperial_directives` | [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) | `imperial_directives_view` | Codex, Tips | `route_visit: imperial_directives_view` | Player Block | P1 |

---

## Landkarte — P2 (nach P1, nicht GC-950A2)

| codex_id | Master Doc | Band | Unlock (kurz) |
|----------|------------|------|----------------|
| `influence` | [GC-566_INFLUENCE_LAYER.md](GC-566_INFLUENCE_LAYER.md) | II | Homeworld L10+ |
| `salvage` | [GC-584_WRECKAGE_SALVAGE.md](GC-584_WRECKAGE_SALVAGE.md) | III | Wreckage field spielbar |
| `ranking` | Ranking / Scores | III | `route_visit: ranking_view` |
| `inventory` | Inventory / Items | III | `route_visit: inventory_view` |
| `auction` | Auktionshaus | III | `route_visit: auction_house_view` |
| `messages` | Messages / Chat | I–III | `always` (Nav) |
| `galactic_directives` | [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) | IV | Community-Feature live |
| `referrals` | Referrals | III | `route_visit: referrals_view` |
| `faq_general` | Querschnitt | — | `always` |

---

## Master-Doc-Kategorien (Pflege — nicht Codex-Navigation)

Für Entwickler: welches Doc in welcher Domäne liegt.

| Kategorie | Docs |
|-----------|------|
| **Core** | CORE_ARCHITECTURE, GENESIS_TERMINOLOGY, IMPERIUM_VISION, WORKFLOW |
| **Imperium** | IMPERIUM_VISION, GC-563–567, GC-592, IMPERIAL_DIRECTIVES |
| **Expansion** | EXPANSION_PROTOCOL, PLANET_EVOLUTION, PLANET_SCOPE, GALAXY_SYSTEM, GC-582, GC-581, GC-583 |
| **Economy** | ECONOMY_SYSTEM, BUILDINGS_SYSTEM, RESEARCH_SYSTEM, PRODUCTION_FORMULA_SYSTEM |
| **Military** | FLEET_SYSTEM, COMBAT_SYSTEM, DEFENSE_SYSTEM, GALACTIC_DIPLOMACY |
| **Social** | Messages/Chat (ARCHITECTURE), Alliance (EPIC-09) |
| **Admin** | SECURITY, Operator-Docs |

**Regel:** Kategorie = Pflege-Cluster. **Band** = Spieler-Progression (Tabelle oben).

---

## Route → Context Help (GC-950D)

| `request.endpoint` | Primärer `codex_id` | FAQ aus |
|--------------------|---------------------|---------|
| `overview` | `overview` + `genesis_ark` | beide |
| `buildings_view` | `buildings` | `resources` |
| `research_view` | `research` | `buildings` |
| `planet_evolution_view` | `planet_evolution` | `ascension` (wenn unlock) |
| `empire_view` | `command_map` + `expansion` | `expeditions` |
| `galaxy_view` | `galaxy` | `expansion` |
| `fleet_view` | `fleet` | `expeditions`, `combat` |
| `shipyard_view` | `fleet` | — |
| `defense_view` | `defense` | `combat` |
| `trader_hub_view` | `trader` | `resources` |
| `imperial_directives_view` | `imperial_directives` | — |
| `galactic_politics` | `diplomacy` | — |
| `ranking_view` | `ranking` (P2) | — |

---

## Visuelle Landkarte (Datenfluss)

```text
                    ┌─────────────────────────────────────┐
                    │     GENESIS_TERMINOLOGY.md          │
                    │     (Begriffe — Lint für alle Copy) │
                    └─────────────────┬───────────────────┘
                                      │
┌──────────────┐    Player Block      │     ┌──────────────────┐
│ Master Doc   │ ─────────────────────┼────►│ generate_knowledge│
│ (Dev-Teil)   │    + unlock YAML     │     │ (GC-950B)         │
└──────────────┘                      │     └────────┬─────────┘
                                      │              │
                    ┌─────────────────┴──────────────┼─────────────────┐
                    │                                │                 │
                    ▼                                ▼                 ▼
             Quick Help (1–3s)              Codex (2–5 min)    Commander Tips
             nur wenn unlock                Bands I–IV + 🔒      nur wenn unlock
                    │                                │                 │
                    └────────────────┬───────────────┴─────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
        Context FAQ            Discord Export          Technical Data
        (?-Panel)              (Markdown)              technical_data.py
        FAQ Section            Discord Summary         (NICHT Generator)
```

---

## GC-950A1 — Akzeptanzkriterien

- [x] Landkarte mit Band I–IV nach **Spieler-Reihenfolge** (nicht alphabetisch)
- [x] Jeder P1-`codex_id` hat: Master Doc, Route, Surfaces, Unlock, SoT
- [x] Unlock-Typen definiert mit Code-Ankern
- [x] Source-of-Truth-Tabelle global
- [x] Route → Context-Help-Mapping
- [x] P2-Backlog separat
- [x] **Kein** Player-Article-Text geschrieben
- [ ] Team-Review: P1-Liste + Unlock-Schwellen bestätigt (offen)

## GC-950A2 — Voraussetzung

Start nur wenn GC-950A1 Review ✅. Schreibt Player Blocks für alle `P1 ✓` Zeilen in der Landkarte (17 Artikel — `overview` kann in `genesis_ark` merge wenn gewünscht → Ziel **12–15** Blocks).

---

## Verwandte Dokumente

- [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md) — Pipeline-Charta
- [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) — Expansion Copy-Vorbild
- [GC-562_EVOLUTION_UNLOCK_GATES.md](GC-562_EVOLUTION_UNLOCK_GATES.md) — Level → Site Gates
- [GC-621_FIRST_30_MINUTES.md](GC-621_FIRST_30_MINUTES.md) — QA-Zielbild ohne Wiki
