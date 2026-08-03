# GC-950A1 — Landkarte des Wissens (Informationsarchitektur)

> **Epic:** EPIC-16 Genesis Knowledge Base  
> **Status:** 📋 Architektur (kein Player-Text)  
> **Stand:** 2026-08-03  
> **Parent:** [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md)  
> **Catalog:** `generated/codex/catalog.json` (27 Artikel · Stand Regeneration 2026-08)

Dieses Dokument ist die **Landkarte des Wissens**: welcher Artikel wohin gehört, **wann** der Spieler ihn sieht, und **wo** jede Art von Inhalt gepflegt wird. Kein Codex-Text — nur Struktur.

**Status-Spalte:** **Shipped** = Artikel in `generated/codex/catalog.json` · **Planned** = Landkarte / Backlog, noch nicht im Catalog.

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
| **III** | Operative Systeme | Tag 3–14 | Flotte, Kampf, LiveOps, Wirtschaft |
| **IV** | Endgame | Wochen+ | Spezialisierung, Diplomatie, Ascension |

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

**Resolver-Owner:** `game/codex.py` → `is_codex_unlocked(player_id, codex_id)` — liest `generated/codex/unlocks.json` + Live-State.

---

## Landkarte — Catalog (Shipped) + Planned

Spalten: **Doc** · **Band** · **Route** · **Surfaces** · **Unlock** · **Status**

### Band I — Erste Stunde

| codex_id | Master Doc | Route (`endpoint`) | Unlock | Status |
|----------|------------|-------------------|--------|--------|
| `genesis_ark` | [IMPERIUM_VISION.md](IMPERIUM_VISION.md) | `overview` → `/overview` | `always` | **Shipped** |
| `resources` | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) | `overview`, `buildings_view` | `always` | **Shipped** |
| `buildings` | [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) | `buildings_view` | `always` | **Shipped** |
| `research` | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) | `research_view` | `always` | **Shipped** |

**Band I — Hinweise**

- `genesis_ark` = Identität der Genesis Ark (Homeworld). **Overview bleibt merged:** es gibt **keinen** separaten Codex-Artikel `overview` — Imperium-Kurzintro und Ark-Identität sitzen in `genesis_ark` (Catalog bestätigt).
- Ressourcen-Copy: **Ferronit / Crytite / Brennzellen** — nie Metall/Krytit ([GENESIS_TERMINOLOGY.md](GENESIS_TERMINOLOGY.md)).

---

### Band II — Frühes Imperium

| codex_id | Master Doc | Route | Unlock | Status |
|----------|------------|-------|--------|--------|
| `planet_evolution` | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) | `planet_evolution_view` | `always` | **Shipped** |
| `planet_scope` | [PLANET_SCOPE.md](PLANET_SCOPE.md) | Header Switcher / Shell | `always` | **Shipped** |
| `expansion` | [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) | `empire_view`, `galaxy_view` | `homeworld_level: 5` + site | **Shipped** |
| `fleet` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) | `fleet_view`, `shipyard_view` | `building: orbital_shipyard` | **Shipped** |
| `galaxy` | [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) | `galaxy_view`, `empire_view` | `always` | **Shipped** |
| `commander_classes` | [COMMANDER_CLASSES.md](COMMANDER_CLASSES.md) | `skilltree_view` → `/skilltree` | `route_visit: skilltree_view` | **Shipped** |
| `story_ops` | [GENESIS_STORY_OPS.md](GENESIS_STORY_OPS.md) | `story_view` → `/story` | `route_visit: story_view` | **Shipped** |
| `liveops_retention` | [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md) | `login_rewards_view`, `premium_view` | `route_visit: login_rewards_view` | **Shipped** |
| `command_map` | [GC-563_COMMAND_MAP_MVP.md](GC-563_COMMAND_MAP_MVP.md) | `galaxy_view` (Weltkarte), `empire_view` | `homeworld_level: 5` | **Shipped** |
| `influence` | [GC-566_INFLUENCE_LAYER.md](GC-566_INFLUENCE_LAYER.md) | `galaxy_view`, `empire_view` | `homeworld_level: 10` | **Shipped** |

**Band II — Unlock-Anker (Code)**

- Erste Expansion: `EXPANSION_SLOT_GATES[0]` → Homeworld **L5** + Interstellar Expansion **L1**.
- Flotte: Orbitalwerft auf aktivem Planet (`orbital_shipyard`).
- Commander Classes / Story Ops / Login+Pass: erster Besuch der jeweiligen Route.

---

### Band III — Operative Systeme & LiveOps

| codex_id | Master Doc | Route | Unlock | Status |
|----------|------------|-------|--------|--------|
| `combat` | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) | `fleet_view` | `player_flag: first_fleet_sent` | **Shipped** |
| `defense` | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) | `defense_view` | `building: defense_factory` | **Shipped** |
| `trader` | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) | `trader_hub_view` | `route_visit: trader_hub_view` | **Shipped** |
| `world_boss` | [WORLD_BOSS_SYSTEM.md](WORLD_BOSS_SYSTEM.md) | `world_boss_view` | `route_visit: world_boss_view` | **Shipped** |
| `titans` | [WORLD_BOSS_SYSTEM.md](WORLD_BOSS_SYSTEM.md) | `world_boss_view`, `overview` | `route_visit: world_boss_view` | **Shipped** |
| `pirates` | [PIRATE_ECOSYSTEM.md](PIRATE_ECOSYSTEM.md) | `galaxy_view` | `route_visit: galaxy_view` | **Shipped** |
| `alliance` | [ALLIANCE_SYSTEM.md](ALLIANCE_SYSTEM.md) | `alliance_view` | `route_visit: alliance_view` | **Shipped** |
| `inventory` | [INVENTORY_SYSTEM.md](INVENTORY_SYSTEM.md) | `inventory_view` | `route_visit: inventory_view` | **Shipped** |
| `case_battles` | [CASE_BATTLES.md](CASE_BATTLES.md) | `inventory_view` (Relikt-Arena-Tab) | `route_visit: inventory_view` | **Shipped** |
| `shop_identity` | [PAYMENT_SHOP.md](PAYMENT_SHOP.md) | `shop_view` | `route_visit: shop_view` | **Shipped** |
| `collector_exchange` | [COLLECTOR_EXCHANGE.md](COLLECTOR_EXCHANGE.md) | `trader_hub_view` | `route_visit: trader_hub_view` | **Shipped** |
| `asteroids` | [ASTEROID_SYSTEM.md](ASTEROID_SYSTEM.md) | `galaxy_view`, `fleet_view` | `route_visit: galaxy_view` | **Shipped** |
| `salvage` | [GC-584_WRECKAGE_SALVAGE.md](GC-584_WRECKAGE_SALVAGE.md) | `empire_view`, `fleet_view`, `galaxy_view` | `route_visit: empire_view` | **Shipped** |
| `expeditions` | [GC-583_EXPEDITION_WORLDS.md](GC-583_EXPEDITION_WORLDS.md) | `fleet_view`, `galaxy_view` | `homeworld_level: 10` | **Shipped** |
| `logistics` | [GC-900_LOGISTICS.md](GC-900_LOGISTICS.md) | `logistics_view`, `fleet_view` | `building: orbital_shipyard` | **Shipped** |
| `ranking` | [SCORE_SYSTEM.md](SCORE_SYSTEM.md) | `ranking_view` | `route_visit: ranking_view` | **Shipped** |
| `auction` | [AUCTION_HOUSE.md](AUCTION_HOUSE.md) | `auction_house_view` | `route_visit: auction_house_view` | **Shipped** |
| `messages` | [MESSAGES.md](MESSAGES.md) | `messages_view` | `always` / `route_visit` | **Shipped** |
| `referrals` | [REFERRALS.md](REFERRALS.md) | `referrals_view` | `route_visit: referrals_view` | **Shipped** |

---

### Band IV — Endgame

| codex_id | Master Doc | Route | Unlock | Status |
|----------|------------|-------|--------|--------|
| `ascension` | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) | `planet_evolution_view` | `homeworld_level: 15` | **Shipped** |
| `galactic_directives` | [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) | `galactic_politics_view` | `route_visit: galactic_politics_view` | **Shipped** |
| `strategic_worlds` | [GC-581_STRATEGIC_WORLDS.md](GC-581_STRATEGIC_WORLDS.md) | `galaxy_view`, `planet_evolution_view` | `homeworld_level: 15` | **Shipped** |
| `diplomacy` | [GALACTIC_DIPLOMACY.md](GALACTIC_DIPLOMACY.md) | `galactic_politics_view` | `route_visit: galactic_politics_view` | **Shipped** |
| `imperial_directives` | [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) | `imperial_directives_view` | `route_visit: imperial_directives_view` | **Shipped** |
| `faq_general` | [FAQ_GENERAL.md](FAQ_GENERAL.md) | Codex / Overview | `always` | **Shipped** |

---

## Landkarte — Planned (kein Catalog-Eintrag)

Kein offenes P1/P2-Backlog mehr nach dem Knowledge Catch-up 2026-08-03. Neue Domänen erst nach IA-Erweiterung.

**Bewusst kein eigener Artikel:** `overview` → bleibt gemerged in `genesis_ark`.

---

## Catalog-Inventar (2026-08-03)

**39 Shipped-IDs** in `generated/codex/catalog.json`:

`alliance`, `ascension`, `asteroids`, `auction`, `buildings`, `case_battles`, `collector_exchange`, `combat`, `command_map`, `commander_classes`, `defense`, `diplomacy`, `expansion`, `expeditions`, `faq_general`, `fleet`, `galactic_directives`, `galaxy`, `genesis_ark`, `imperial_directives`, `influence`, `inventory`, `liveops_retention`, `logistics`, `messages`, `pirates`, `planet_evolution`, `planet_scope`, `ranking`, `referrals`, `research`, `resources`, `salvage`, `shop_identity`, `story_ops`, `strategic_worlds`, `titans`, `trader`, `world_boss`

**Merged / kein Catalog:** `overview` → `genesis_ark`.

---

## Master-Doc-Kategorien (Pflege — nicht Codex-Navigation)

| Kategorie | Docs |
|-----------|------|
| **Core** | CORE_ARCHITECTURE, GENESIS_TERMINOLOGY, IMPERIUM_VISION, WORKFLOW |
| **Imperium** | IMPERIUM_VISION, GC-563–567, GC-592, IMPERIAL_DIRECTIVES |
| **Expansion** | EXPANSION_PROTOCOL, PLANET_EVOLUTION, PLANET_SCOPE, GALAXY_SYSTEM, GC-582, GC-581, GC-583 |
| **Economy** | ECONOMY_SYSTEM, BUILDINGS_SYSTEM, RESEARCH_SYSTEM, PRODUCTION_FORMULA_SYSTEM, INVENTORY_SYSTEM, PAYMENT_SHOP, COLLECTOR_EXCHANGE |
| **Military / LiveOps** | FLEET_SYSTEM, COMBAT_SYSTEM, DEFENSE_SYSTEM, WORLD_BOSS_SYSTEM, PIRATE_ECOSYSTEM, ASTEROID_SYSTEM, CASE_BATTLES |
| **Social / Retention** | ALLIANCE_SYSTEM, COMMANDER_CLASSES, GENESIS_STORY_OPS, LIVEOPS_RETENTION, GALACTIC_DIPLOMACY, GALACTIC_DIRECTIVES |
| **Admin** | SECURITY, Operator-Docs |

**Regel:** Kategorie = Pflege-Cluster. **Band** = Spieler-Progression (Tabelle oben).

---

## Route → Context Help (GC-950D)

| `request.endpoint` | Primärer `codex_id` | FAQ / Related aus |
|--------------------|---------------------|-------------------|
| `overview` | `genesis_ark` (+ Titans-Teaser) | `resources`, `titans` |
| `buildings_view` | `buildings` | `resources` |
| `research_view` | `research` | `buildings` |
| `planet_evolution_view` | `planet_evolution` | `ascension` (wenn unlock) |
| `empire_view` | `command_map` | `expansion`, `salvage`, `expeditions` |
| `galaxy_view` | `galaxy` | `expansion`, `asteroids`, `pirates`, `command_map` |
| `fleet_view` | `fleet` | `combat`, `expeditions`, `logistics`, `asteroids`, `salvage` |
| `logistics_view` | `logistics` | `fleet`, `resources` |
| `shipyard_view` | `fleet` | — |
| `defense_view` | `defense` | `combat` |
| `trader_hub_view` | `trader` | `collector_exchange`, `resources` |
| `world_boss_view` | `world_boss` | `titans` |
| `skilltree_view` | `commander_classes` | `research`, `fleet` |
| `story_view` | `story_ops` | `liveops_retention`, `shop_identity` |
| `login_rewards_view` | `liveops_retention` | — |
| `premium_view` | `liveops_retention` | `shop_identity` |
| `shop_view` | `shop_identity` | `liveops_retention`, `inventory` |
| `inventory_view` | `inventory` | `case_battles`, `collector_exchange` |
| `alliance_view` | `alliance` | `world_boss`, `fleet` |
| `imperial_directives_view` | `imperial_directives` | `inventory` |
| `galactic_politics_view` | `diplomacy` | `galactic_directives` |
| `ranking_view` | `ranking` | — |
| `auction_house_view` | `auction` | `inventory` |
| `referrals_view` | `referrals` | — |
| `messages_view` | `messages` | — |

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
- [x] Shipped vs Planned anhand `generated/codex/catalog.json` markiert (Stand 2026-08-03)
- [x] `overview` merged in `genesis_ark` (kein separater Artikel)
- [x] LiveOps-/Catalog-IDs in der Landkarte
- [x] Unlock-Typen definiert mit Code-Ankern
- [x] Source-of-Truth-Tabelle global
- [x] Route → Context-Help-Mapping (inkl. neue Endpoints)
- [x] Planned-Backlog separat
- [x] **Kein** Player-Article-Text geschrieben
- [ ] Team-Review: Unlock-Schwellen bestätigt (offen)

## GC-950A2 — Voraussetzung

Player Blocks für Shipped-Artikel existieren bzw. werden regeneriert. **`overview` bleibt merged in `genesis_ark`** — kein separater Block.

---

## Verwandte Dokumente

- [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md) — Pipeline-Charta
- [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) — Expansion Copy-Vorbild
- [GC-562_EVOLUTION_UNLOCK_GATES.md](GC-562_EVOLUTION_UNLOCK_GATES.md) — Level → Site Gates
- [GC-621_FIRST_30_MINUTES.md](GC-621_FIRST_30_MINUTES.md) — QA-Zielbild ohne Wiki
