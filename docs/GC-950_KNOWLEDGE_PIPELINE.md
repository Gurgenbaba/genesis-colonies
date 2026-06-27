# GC-950 — Genesis Knowledge Pipeline

> **Epic:** EPIC-16 Genesis Knowledge Base  
> **Status:** ✅ Implementiert (GC-950B–F) — Player Blocks P1 in 11 Master Docs  
> **Stand:** 2026-06-27  
> **Supersedes:** GC-630 (klassisches Tutorial) · Legacy Ingame-Wiki (`special_panel.html`)

Dieses Dokument ist **keine Feature-Liste** und **kein Codex-Inhalt**. Es definiert die verbindliche **Informationsarchitektur**: welche Wahrheit wo lebt, welche Surfaces daraus entstehen, und in welcher Reihenfolge Tickets implementiert werden.

---

## Grundregeln

> **Spieler-Wissen folgt derselben Hierarchie wie Gameplay-Mechanik: eine kanonische Quelle, viele Anzeigen — keine parallele Copy-Pflege.**

> **Nichts wird erklärt, bevor es relevant wird.** Codex-Artikel, Quick Help und Commander Tips haben **Unlock-Bedingungen** — der Codex wächst mit dem Imperium (siehe [GC-950A1](GC-950A1_INFORMATION_ARCHITECTURE.md)).

| Kanonische Quelle (heute) | Domäne |
|---------------------------|--------|
| [GAME_RULES.md](GAME_RULES.md) | Spielregeln (Master-Doc; UI: Rules Panel, nicht Codex) |
| `EffectResolver` | Gameplay-Effekte |
| `game/technical_data.py` | Zahlen, ROI, Stufen (Ebene 3) |
| [GENESIS_TERMINOLOGY.md](GENESIS_TERMINOLOGY.md) | Begriffe (Ferronit, Crytite, …) |
| **Player Article Blocks** (neu) | Spieler-Narrativ, FAQ, Tips |
| **Knowledge Generator** (neu) | Surfaces (Codex, Quick Help, …) |

### Leitfrage für jedes Knowledge-Ticket

> *Erklärt das **Genesis** — oder erklärt das **OGame mit anderen Namen**?*

Wenn die Antwort „OGame“ ist → Copy überdenken, nicht migrieren.

### Verboten

| Verboten | Warum |
|----------|--------|
| Wiki-Texte 1:1 in Codex kopieren | Zwei Wahrheiten |
| Formeln / ROI im Codex (Ebene 2) | Gehört in Technical Data (Ebene 3) |
| Master-Docs 1:1 an Spieler extrahieren | Dev-Schema ≠ Spieler-Narrativ |
| Heuristiken / KI-Raten im Generator | Nur explizite Block→Surface-Mapping |
| `location.reload()` für Codex-Navigation | PJAX / `GC.navigateTo` |
| Paralleles Wiki-System neben Pipeline | GC-000 Regel 15 |

### Erlaubt

- Player Article Block in bestehendem Master-Doc (Dev-Teil unverändert)
- Generator → `generated/codex/` → Locales / `game/codex.py`
- Legacy-Wiki-Inhalt **löschen**, nicht migrieren (OGame-Copy, Nerd-Formeln)
- Commander Tips aus demselben Block wie Codex-Tips

---

## Vier Schichten (verbindlich)

```text
Master Docs (Entwickler)
        │
        ▼
Player Article Blocks (strukturiert, YAML + Sections)
        │
        ▼
Knowledge Generator (scripts/generate_knowledge.py)
        │
        ▼
Surfaces (UI + Export)
```

**Reihenfolge der Tickets:** Informationsarchitektur **vor** Generator **vor** Surfaces **vor** Inhalt in großer Menge.

| Schicht | Inhalt | Wer pflegt |
|---------|--------|------------|
| 1 Master Docs | Schema, Module, APIs, Design-Charta | Entwickler (wie heute) |
| 2 Player Blocks | Spieler-Copy, FAQ, Tips, Discord-Summary | Design + Dev (in Master-Doc) |
| 3 Generator | Parsing, Validierung, Export, CI-Guard | `scripts/` |
| 4 Surfaces | Quick Help, Codex, Tips, FAQ-Panel, Discord | Templates + `game/codex.py` |

---

## Drei Ebenen Spieler-Hilfe (orthogonal zu den vier Schichten)

| Ebene | Surface | Zielgruppe | Länge | Owner heute / Ziel |
|-------|---------|------------|-------|---------------------|
| **1** | Quick Help | Jeder | 1–3 Sätze | Page-Header (neu, GC-950D) |
| **2** | Codex | Normale Spieler | 2–5 Min. | `special_panel` → Codex (GC-950C) |
| **3** | Technical Data | Power User | Zahlen/Formeln | `game/technical_data.py` ✅ |

Ebene 3 **nicht** in die Pipeline einbinden — nur verlinken („Technische Daten“-Button bleibt kanonisch).

---

## Surfaces (fest definiert)

Der Generator erzeugt **nur** diese Surfaces. Kein Section ohne Ziel-Surface.

| Surface | Zielgruppe | Länge | Quelle (Player Block Section) | Ziel (Zielpfad) |
|---------|------------|-------|-------------------------------|-----------------|
| **Quick Help** | Jeder | 1–3 Sätze | `## Quick Help` | Page-Header pro Route |
| **Codex** | Normale Spieler | 2–5 Min. | `Summary` + `Why` + `How it works` + `Related Systems` | Codex UI / `/codex` |
| **Commander Tip** | Wiederkehrende Spieler | 1 Tipp | `## Commander Tips` (Pool) | Sidebar / Overview |
| **FAQ** | Konkrete Frage | 30–60 s | `## FAQ` | Context-Help-Panel |
| **Discord Export** | Community | Markdown | `## Discord Summary` | `docs/export/discord/` |
| **Technical Data** | Power User | Zahlen | — | `technical_data.py` (nicht Generator) |

### Surface → Section Mapping (deterministisch)

```text
Quick Help          ←  ## Quick Help
Codex body          ←  ## Summary + ## Why + ## How it works + ## Related Systems
Commander Tips pool ←  ## Commander Tips  (jede Bullet = ein Tip)
FAQ                 ←  ## FAQ             (jede Q/A = ein Eintrag)
Discord Export      ←  ## Discord Summary
```

Keine Heuristiken. Kein „Rest des Dokuments“. Fehlende Section → Surface leer / Generator-Warnung in CI.

---

## Player Article Block — Schema (verbindlich)

Player Blocks leben **am Ende** des jeweiligen Master-Docs, nach einem Trennstrich `---`. Dev-Teil darüber bleibt unverändert.

### YAML Frontmatter (Pflicht)

```yaml
---
codex_id: expansion
band: III
difficulty: beginner | intermediate | advanced
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - empire_view
  - galaxy_view
related_codex:
  - planet_evolution
  - fleet
  - command_map
terminology: GENESIS_TERMINOLOGY  # Pflicht-Referenz, kein Duplikat
unlock:
  type: homeworld_level
  value: 5
  site_key: frontier_ix          # optional, alternativ zu value
teaser_key: codex_unlock_expansion_teaser  # i18n wenn gesperrt
---
```

| Feld | Pflicht | Bedeutung |
|------|---------|-----------|
| `codex_id` | ja | Stabiler Key (`snake_case`), i18n-Prefix `codex_{id}_*` |
| `band` | Codex-Artikel | Progression I–IV (Spieler-Reihenfolge) — siehe [GC-950A1](GC-950A1_INFORMATION_ARCHITECTURE.md) |
| `unlock` | ja | Runtime-Prüfung in `game/codex.py` — Typen in GC-950A1 |
| `teaser_key` | wenn nicht `always` | i18n für gesperrten Codex-Eintrag |
| `difficulty` | ja | Commander-Tip-Filter (optional später) |
| `estimated_read` | Codex-Artikel | Anzeige im Codex-Header |
| `surfaces` | ja | Welche Surfaces dieser Block füttert |
| `routes` | wenn Quick Help / Context | `request.endpoint` für Kontext-Hilfe |
| `related_codex` | empfohlen | Codex-Querverweise |
| `terminology` | ja | Verweis auf [GENESIS_TERMINOLOGY.md](GENESIS_TERMINOLOGY.md) |

### Markdown Sections (nach Frontmatter)

| Section | Pflicht wenn Surface | Inhalt |
|---------|----------------------|--------|
| `## Quick Help` | `quick_help` | 1–3 Sätze + optional CTA-Hinweis |
| `## Summary` | `codex` | Lead — was ist das System? |
| `## Why` | `codex` | Warum existiert es im Imperium? |
| `## How it works` | `codex` | Ablauf, Phasen, Spieler-Entscheidungen |
| `## Tips` | optional | Inline-Codex-Tipps (kurz) |
| `## FAQ` | `faq` | `**Frage?**` + Antwort (Markdown) |
| `## Related Systems` | `codex` | Bullet-Liste `codex_id` oder Anzeigename |
| `## Commander Tips` | `commander_tips` | Jede Bullet = ein Tip im Pool |
| `## Discord Summary` | `discord` | Community-Post (Markdown, kein HTML) |

**Sprache Player Blocks:** Primär **DE** in Master-Docs. EN (+ 6 Locales) via Generator-Pipeline oder `gc900`-ähnlicher Translate-Pass (GC-950B Detail).

### Beispiel (Struktur only — kein verbindlicher Inhalt)

Am Ende eines Master-Docs:

```text
---

## Player Article

(YAML frontmatter — siehe Schema oben)

## Quick Help
Planet Evolution ist das Herz deines Imperiums…

## Summary
…

## Why
…

## How it works
…

## FAQ
**Warum ist meine neue Welt noch keine Kolonie?**
Die Seed Ark gründet zuerst einen Frontier Outpost…

## Related Systems
- expansion
- imperium

## Commander Tips
- Entwicklungsstufe schaltet Regionen frei…

## Discord Summary
…
```

---

## Genesis Codex — Band-Struktur (Spieler-Navigation)

Codex-UI gruppiert nach **Progression-Band** (wann relevant), Master-Docs nach **Kategorie** (Pflege). Vollständige Landkarte: [GC-950A1_INFORMATION_ARCHITECTURE.md](GC-950A1_INFORMATION_ARCHITECTURE.md).

| Band | Spieler-Phase | P1-`codex_id` (Auszug) |
|------|---------------|------------------------|
| **I** | Erste Stunde | `genesis_ark`, `overview`, `resources`, `buildings`, `research` |
| **II** | Frühes Imperium | `planet_evolution`, `expansion`, `command_map`, `fleet`, `galaxy` |
| **III** | Operative Systeme | `expeditions`, `trader`, `combat`, `defense` |
| **IV** | Endgame | `strategic_worlds`, `diplomacy`, `ascension`, `imperial_directives` |

Gesperrte Bände: 🔒 + `teaser_key` — kein Spoiler-Body.

---

## Master-Doc-Katalog (Gameplay-Kategorien)

Nicht alphabetisch — nach **Gameplay-Domäne** für GC-950A1-Audit.

### Core

| Doc | Spieler-relevant? | Player Block (GC-950A1) | Priorität A2 |
|-----|-------------------|-------------------------|--------------|
| [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) | Dev only | ❌ kein Block | — |
| [GENESIS_TERMINOLOGY.md](GENESIS_TERMINOLOGY.md) | Referenz | ⚠️ Index, kein Narrativ | P2 |
| [IMPERIUM_VISION.md](IMPERIUM_VISION.md) | ja | 📋 `imperium` | **P1** |
| [PLANET_SCOPE.md](PLANET_SCOPE.md) | ja | 📋 `planet_scope` | P1 |

### Imperium

| Doc | Player Block | Priorität A2 |
|-----|--------------|--------------|
| [IMPERIUM_VISION.md](IMPERIUM_VISION.md) | `imperium` | **P1** |
| [GC-563_COMMAND_MAP_MVP.md](GC-563_COMMAND_MAP_MVP.md) / World Map | `command_map` | **P1** |
| [GC-566_INFLUENCE_LAYER.md](GC-566_INFLUENCE_LAYER.md) | `influence` | P2 |
| [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) | `imperial_directives` | P2 |

### Expansion

| Doc | Player Block | Priorität A2 |
|-----|--------------|--------------|
| [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) | `planet_evolution` | **P1** |
| [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) | `expansion` | **P1** |
| [GC-582_DYNAMIC_COLONIZATION.md](GC-582_DYNAMIC_COLONIZATION.md) | `colonization` | P1 (oder in `expansion` merge) |
| [GC-581_STRATEGIC_WORLDS.md](GC-581_STRATEGIC_WORLDS.md) | `strategic_worlds` | P2 |
| [PLANET_SCOPE.md](PLANET_SCOPE.md) | `planet_scope` | **P1** |
| [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) | `galaxy` | **P1** |

### Economy

| Doc | Player Block | Priorität A2 |
|-----|--------------|--------------|
| [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) | `economy`, `trader` | **P1** |
| [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md) | Dev + Ebene 3 only | ❌ |
| [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) | `buildings` | **P1** |
| [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) | `research` | **P1** |
| [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md) | Dev only | ❌ |

### Military

| Doc | Player Block | Priorität A2 |
|-----|--------------|--------------|
| [FLEET_SYSTEM.md](FLEET_SYSTEM.md) | `fleet`, `logistics` | **P1** |
| [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) | `combat` | **P1** |
| [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) | `defense` | P1 |
| [GALACTIC_DIPLOMACY.md](GALACTIC_DIPLOMACY.md) | `diplomacy` | P2 |
| [GC-583_EXPEDITION_WORLDS.md](GC-583_EXPEDITION_WORLDS.md) | `expeditions` | **P1** |
| [GC-584_WRECKAGE_SALVAGE.md](GC-584_WRECKAGE_SALVAGE.md) | `salvage` | P2 |

### Social

| Doc | Player Block | Priorität A2 |
|-----|--------------|--------------|
| ARCHITECTURE (Chat, Messages) | `messages`, `chat` | P2 |
| Alliance (Platzhalter) | später EPIC-09 | — |
| Ranking | `ranking` | P2 |

### Admin / Operator

| Doc | Player Block |
|-----|--------------|
| [SECURITY.md](SECURITY.md) | ❌ |
| Operator-Docs | ❌ |

### P1-Kern (12 Artikel für GC-950A2)

Verbindliche Startliste — erst nach GC-950A1-Mapping bestätigen:

1. `imperium` — IMPERIUM_VISION  
2. `planet_evolution` — PLANET_EVOLUTION  
3. `expansion` — EXPANSION_PROTOCOL  
4. `planet_scope` — PLANET_SCOPE  
5. `command_map` — Command Map / World Map  
6. `galaxy` — GALAXY_SYSTEM  
7. `economy` — ECONOMY_SYSTEM  
8. `buildings` — BUILDINGS_SYSTEM  
9. `research` — RESEARCH_SYSTEM  
10. `fleet` — FLEET_SYSTEM  
11. `combat` — COMBAT_SYSTEM (+ Defense Kurzverweis)  
12. `expeditions` — GC-583_EXPEDITION_WORLDS  

---

## Datenfluss (Generator)

```text
docs/**/*.md
  └─ parse: YAML frontmatter + Sections (nur ## Player Article Bereich)
        │
        ├─ validate: terminology refs, codex_id unique, routes known
        ├─ validate: forbidden terms (Metall, Krytit, Planet-Slot, …) vs GENESIS_TERMINOLOGY
        │
        ▼
generated/codex/
  ├─ articles.json          # strukturiert, alle Sprachen
  ├─ de.json / en.json …    # oder merge in locales/
  ├─ commander_tips.json    # flacher Tip-Pool
  └─ discord/               # pro codex_id ein .md

game/codex.py               # Loader, get_article(codex_id), get_tip_for_date()
        │
        ▼
Surfaces (GC-950C–F)
```

### CI-Guards (GC-950B)

- `generated/` muss mit Docs synchron sein (`pytest` oder pre-commit)
- Unbekannte `routes` → Fail
- Duplikat `codex_id` → Fail
- Player Block ohne `terminology` → Fail
- Verbotene UI-Begriffe in Player Blocks → Fail (Terminology-Lint)

### Owner (Regel 17 — bei Implementierung in CORE_ARCHITECTURE eintragen)

| Komponente | Owner |
|------------|--------|
| Player Block Schema (dieses Doc) | `docs/GC-950_KNOWLEDGE_PIPELINE.md` |
| Generator | `scripts/generate_knowledge.py` |
| Runtime API / Loader | `game/codex.py` |
| Codex UI | `templates/partials/codex_panel.html` (Wiki ersetzen) |
| Quick Help | Page-Templates + `templates/partials/quick_help.html` |
| Commander Tips | `sidebar_right.html` / `overview.html` |
| Technical Data | `game/technical_data.py` (unverändert) |

---

## Legacy-Wiki — Abwicklung

| Inhalt in `special_panel.html` | Aktion |
|--------------------------------|--------|
| Schnellstart „Metall/Krytit“ | **Löschen** |
| Nerd-Formeln (`metal_mine^1.4`) | **Löschen** → Ebene 3 existiert |
| Generische Planet-Evolution-Zeile | **Ersetzen** durch Generator-Codex |
| FAQ Energiemangel (legacy Begriffe) | **Neu** aus `economy` Player Block |

Wiki-Button → **Codex** (i18n: `codex_short`, `codex_title`). Zugang: Bottom Utility Bar + Special Bar (wie heute).

---

## Ticket-Zerlegung (verbindliche Reihenfolge)

| Ticket | Fokus | Output | Kein Scope |
|--------|-------|--------|------------|
| **GC-950** | Diese Charta | `GC-950_KNOWLEDGE_PIPELINE.md`, EPIC-16 | Generator, UI |
| **GC-950A1** | Landkarte des Wissens | [GC-950A1_INFORMATION_ARCHITECTURE.md](GC-950A1_INFORMATION_ARCHITECTURE.md) — Matrix + Unlock + SoT | Player-Text schreiben |
| **GC-950A2** | Player Blocks P1 (12 Docs) | YAML + Sections in Master-Docs (DE) | Generator, UI |
| **GC-950B** | Knowledge Generator | `scripts/generate_knowledge.py`, `generated/codex/`, CI-Tests | Surfaces |
| **GC-950C** | Codex UI | Wiki → Codex Panel, Bands I–V, PJAX | Quick Help |
| **GC-950D** | Context Help + Quick Help | `?`-Panel + Page-Header Pattern | Codex-Inhalt |
| **GC-950E** | Commander Tips | Täglicher Tip aus Pool, Sidebar + Overview | — |
| **GC-950F** | Discord / Export | `docs/export/discord/`, optional externe Wiki-Export | — |

**GC-630** (Overview-Tutorial): **geschlossen** — ersetzt durch progressive Surfaces (Quick Help + Tips + Codex).

---

## UI-Anker (bestehende Shell)

| Surface | Platzierung |
|---------|-------------|
| Codex | Bottom Utility Bar (`wiki` → `codex`), Special Bar, optional „Mehr“-Drawer |
| Quick Help | Page-Header je Route (`data-codex-id`) |
| Context FAQ | `?` neben Page-Title → Panel mit FAQ-Section |
| Commander Tips | Rechte Sidebar + Overview (Mobile) |
| Technical Data | Gebäude/Research-Cards (bestehend) |

Mobile Bottom Nav bleibt **Spiel-Navigation** — kein Codex-Slot.

---

## Langfristige Pipeline (nach GC-950F)

```text
Master Doc → Player Block → Generator
                ├── Codex
                ├── Quick Help
                ├── FAQ / Context
                ├── Commander Tips
                ├── Discord Guides
                ├── Locale Keys (8 Sprachen)
                └── (optional) KI-Hilfe mit codex_id als Kontext — nicht GC-950
```

---

## Referenz-Docs

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regel 15 (kein Parallel-Wiki), Regel 17 (Owner)
- [GENESIS_TERMINOLOGY.md](GENESIS_TERMINOLOGY.md) — Begriffe
- [GC-823_TECHNICAL_DATA.md](GC-823_TECHNICAL_DATA.md) — Ebene 3
- [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) — Expansion Copy-Vorbild
- [GC-621_FIRST_30_MINUTES.md](GC-621_FIRST_30_MINUTES.md) — QA ohne Wiki (Zielbild)
- [EPICS.md](EPICS.md) — EPIC-16
- [GC-950A1_INFORMATION_ARCHITECTURE.md](GC-950A1_INFORMATION_ARCHITECTURE.md) — Landkarte (GC-950A1)

---

## GC-950A1 — Akzeptanzkriterien

Siehe [GC-950A1_INFORMATION_ARCHITECTURE.md](GC-950A1_INFORMATION_ARCHITECTURE.md) § Akzeptanzkriterien.

## GC-950A2 — Akzeptanzkriterien (Vorlage)

- [ ] 12 P1 Player Blocks mit vollständigem YAML + allen Sections für geplante Surfaces
- [ ] Terminology-Lint: keine verbotenen Begriffe aus GENESIS_TERMINOLOGY
- [ ] EXPANSION_PROTOCOL Lifecycle in `expansion` Block korrekt
- [ ] Kein Generator, kein UI
