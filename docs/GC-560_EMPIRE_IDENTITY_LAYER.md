# GC-560 — Empire Identity Layer

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **S** — wichtigstes Ticket der Epic (Identität, nicht Mechanik)  
> **Status:** ✅ umgesetzt  
> **Stand:** 2026-06-12  
> **Nachfolger:** [GC-563 Command Map MVP](GC-563_COMMAND_MAP_MVP.md)

Design Manifest: [IMPERIUM_VISION.md](IMPERIUM_VISION.md)

---

## Product-Rationale

**GC-560 ist das wichtigste Ticket der ganzen Epic — nicht weil es technisch groß ist, sondern weil es Spielern erstmals zeigt:**

> *Genesis Colonies ist kein OGame-Klon mehr.*

Aktuell sieht ein Spieler:

```text
Homeworld / Heimatwelt
Kolonie Alpha
Aurora Prime
[1:42:7]
```

Die Daten existieren bereits (`is_homeworld`, Gebäude, Namen, Koordinaten). **Die Bedeutung fehlt.**

Nach GC-560 soll ein Spieler beim Öffnen seines Accounts sofort erkennen:

```text
Das hier ist mein Imperium.
```

nicht:

```text
Das sind meine Planeten.
```

**Bewusst ohne neue Mechanik:** Kein Evo-Gate, keine Regionen, keine Chokepoints, keine Boni, keine Migration, keine neuen Tabellen. Nur Identität.

---

## Problem

Genesis Colonies hat ein vollständiges Multi-Kolonie- und Planet-Evolution-Backend, präsentiert sich in der UI aber noch wie ein OGame-Klon:

| Heute | Fehlende Bedeutung |
|-------|-------------------|
| `header_planet_homeworld` → „Heimatwelt“ | Genesis Ark / Hauptsitz des Imperiums |
| `header_planet_colony` → „Kolonie“ | Rolle (Mining, Research, Shipyard, …) |
| Empire-Seite = Matrix + Produktion | Keine kompakte „Mein Imperium“-Identitätskarte |
| Default-Homeworld-Name `Aurora Prime` | Kein Genesis-Ark-Framing |
| Planet Switcher zeigt Name + Koordinate | Kein Imperiums-Kontext (Rolle, Hauptsitz) |

Planet Scope (`active_planet_id`) und alle Actions bleiben unverändert.

---

## Zielbild (nach GC-560)

### Genesis Ark (Homeworld)

Homeworld erhält überall eine eigene Identität:

```text
🏛 Genesis Ark
   Hauptsitz des Imperiums
```

Spielerdefinierte Namen bleiben möglich (Options/Profil). UI zeigt **immer** die Imperiums-Rolle als Subtitle/ Badge — unabhängig vom Custom-Namen.

Neue Accounts: Default-Homeworld-Name **`Genesis Ark`** statt `Aurora Prime` (`ensure_player_and_homeworld` — keine Migration für Bestandskonten).

### Colony Roles (nur Anzeige)

Jede Nicht-Homeworld-Kolonie erhält automatisch ein Badge, **serverseitig aus Gebäude-Leveln abgeleitet**:

| Rolle | Icon | Ableitung (Phase 1) |
|-------|------|---------------------|
| Mining Colony | ⛏ | Dominanz: `metal_mine` + `crystal_mine` + `fuel_cell_plant` |
| Research Colony | 🔬 | Dominanz: `research_lab` + `academy` |
| Shipyard Colony | ⚓ | Dominanz: `orbital_shipyard` + `defense_factory` |
| Fortress Colony | 🛡 | Dominanz: `defense_factory` + Verteidigungsgebäude (Türme/Schilder) |
| Trade Colony | 🏪 | Aktive `planet_trade_routes` am Planeten **oder** Trade-Specialization |
| Frontier Outpost | 🌌 | Fallback: niedrige Gesamt-Infrastruktur / frische Kolonie |
| General Colony | 🌍 | Tie-Break / keine klare Dominanz |

Keine Boni. Keine Queue-/Fleet-Änderung. Keine DB-Spalte `colony_role`.

### Command Map View (Galaxy Tab)

**Die Empire-Seite (`/empire`) darf NICHT verändert werden.** Empire bleibt Wirtschafts- und Produktionsübersicht.

GC-560 legt die Identitätsschicht für die **alternative Galaxy-Ansicht**:

**`/galaxy?view=command_map`** (Alias: `view=imperium` für Abwärtskompatibilität)

Tabs auf `/galaxy`:

```text
[ Command Map ] [ Klassische Galaxy ]
```

- **Klassische Galaxy** — `[1:42]` Position 1…15, Fleet, Kolonisierung, Scans (unverändert)
- **Command Map** — Genesis Ark, Kolonierollen, Imperiumsliste (GC-560 MVP; Graph in GC-563)

Klick auf Kolonie → `POST /api/planets/active` (bestehend). Koordinaten sekundär.

### Header Identity

Planet Switcher Trigger zeigt:

**Homeworld aktiv:**

```text
Genesis Ark          (oder Custom-Name)
Hauptsitz des Imperiums
```

**Kolonie aktiv:**

```text
Helios Gate
Forschungskolonie
```

Koordinaten bleiben sichtbar, aber **unter** Name + Rolle (nicht primäre Identität).

Dropdown-Items: Name + Rolle-Badge statt „Heimatwelt / Kolonie“.

Live-Update: `applyActionState` / `planets[]` Payload erweitern — `static/main.js` Switcher-Patch mit neuen Feldern.

### PlayerCard (Teaser / optional in GC-560)

Wenn Scope erlaubt (≤5 Dateien-Kern): PlayerCard-Stat-Zeile vorbereiten:

```text
Imperium: 5 Kolonien
Genesis Ark: Level 12
```

Vollständige PlayerCard-Erweiterung (Spezialisierung, „Technologisches Reich“) → **GC-561**, falls GC-560 Datei-Limit greift.

---

## Explizit NICHT in GC-560

| Verboten | Grund |
|----------|-------|
| **`/empire` anfassen** | Wirtschaft/Matrix bleibt unverändert |
| Command Map Graph / Regionen | GC-563 / GC-564 |
| Einflussgebiete | GC-566 |
| Chokepoints | GC-565 |
| Evolution Unlock Gates | GC-562 |
| Neue DB-Migration / Tabellen | — |
| Neue REST-Endpoints | Payload-Erweiterung in bestehenden APIs reicht |
| Klassische Galaxy-Slots entfernen | Fallback für Fleet/Kolo bleibt |
| Fleet / Queue | — |
| Gameplay-Boni durch Rollen | GC-561+ |

---

## Technische Leitplanken

- **Owner:** neues Modul `game/planet_evolution/empire_identity.py` (Regel 17 — kein Parallel-System)
- **Planet Scope unangetastet:** `get_context_planet()`, `active_planet_id`, `set_active_planet`
- **Keine Frontend-Mechanik:** Rollen nur Server-Berechnung aus `get_planet_buildings()` + optional Trade-Routes
- **PJAX:** Empire-Card und Switcher via SSR + State-Patch; kein `location.reload()`
- **i18n:** alle Rollen-Labels über `locales/de.json` + `locales/en.json`

---

## Betroffene Dateien

**Kern (Owner + Payload):**

- `game/planet_evolution/empire_identity.py` — **neu:** `resolve_homeworld_display()`, `derive_colony_role(planet_id)`, `empire_colony_identity_row(planet_row)`
- `game/planet_evolution/service.py` — `_planet_switcher_row()` um `empire_role_key`, `empire_role_label_key`, `empire_role_icon`, `empire_subtitle_key` erweitern
- `game/empire_page.py` — `empire.colonies_identity[]` für Overview-Card
- `game/models.py` — Default-Homeworld-Name `Genesis Ark` (nur Neuanlage)

**UI:**

- `templates/partials/header_planet_switcher.html` — Name + Rolle + Subtitle
- `templates/partials/galaxy_command_map_panel.html` — Command Map MVP auf `/galaxy?view=command_map`
- `templates/galaxy.html` — Tabs Command Map | Klassische Galaxy
- `static/main.js` — `patchPlanetSwitcherFromState()` / Menu-Rebuild mit Role-Feldern
- `static/style.css` — Badge/Subtitle-Styling (minimal, bestehende `--gc-*` Tokens)

**Locales:**

- `locales/de.json`, `locales/en.json` — Keys `empire_role_*`, `empire_my_imperium`, `empire_homeworld_subtitle`, …

**Tests:**

- `tests/test_empire_identity.py` — **neu:** Rollen-Ableitung, Homeworld-Payload, Switcher-Felder
- `tests/test_header_planet_switcher.py` — erweitern falls Payload-Contract

**Nicht bearbeiten:**

- `game/galaxy.py`, `game/fleet*.py`, `migrations/`, Queue-Engine
- Command Map / Regionen

---

## API / State-Contract (Erweiterung, kein neuer Endpoint)

Bestehende Payloads erweitern — **kein** neuer Route:

| Payload | Feld (neu) | Typ |
|---------|------------|-----|
| `planets[]` (game-state, switcher, `/api/planets/active`) | `empire_role_key` | `str` — z.B. `homeworld`, `mining`, `research` |
| | `empire_role_label_key` | `str` — i18n key |
| | `empire_role_icon` | `str` — Emoji/Symbol für UI |
| | `empire_subtitle_key` | `str` — optional, z.B. Hauptsitz |
| `empire` (SSR `/empire`) | `colonies_identity` | `list[{planet_id, name, role_key, role_label_key, icon, is_active, is_homeworld}]` |

Frontend: nur anzeigen — **keine** Rollen-Logik in JS.

---

## Anforderungen

1. **`empire_identity.py`** exportiert kanonische Rollen-Ableitung; pytest-deckbar ohne UI.
2. **Homeworld** zeigt Imperiums-Identität (🏛, „Hauptsitz des Imperiums“) in Switcher + Empire-Card.
3. **Kolonien** zeigen abgeleitete Rolle (Icon + Label) — nur Anzeige, keine Gameplay-Effekte.
4. **Empire Overview Card** „Mein Imperium“ auf `/empire` mit allen Kolonien + Rollen; Klick wechselt active planet.
5. **Header Switcher** zeigt Rolle/Subtitle für aktiven Planeten; Dropdown mit Rollen statt generischem „Kolonie“.
6. **Neue Spieler** erhalten Homeworld-Name `Genesis Ark` (Bestandskonten unverändert).
7. **Live-State:** nach Planetwechsel und Poll bleiben Rollen korrekt (`applyActionState`).
8. **i18n DE + EN** für alle neuen Strings.

---

## Akzeptanzkriterien

- [ ] Spieler sieht auf `/galaxy?view=command_map` Imperiumsliste mit Rollen-Badges
- [ ] `/empire` (Produktion/Matrix) bleibt unverändert — keine Identity-Cards dort
- [ ] Header Switcher zeigt bei Homeworld „Hauptsitz“-Subtitle, bei Kolonie Rollen-Label (z.B. „Forschungskolonie“)
- [ ] Rollen werden **serverseitig** aus Gebäuden abgeleitet; pytest belegt Mining vs Research vs Shipyard
- [ ] Keine neuen DB-Tabellen, keine Migration, keine neuen API-Routes
- [ ] Planet Scope / `POST /api/planets/active` unverändert funktional
- [ ] Keine Galaxy-, Fleet-, Queue-Regression
- [ ] `pytest tests/test_empire_identity.py tests/test_header_planet_switcher.py -v` grün

### Manuelle QA (60 Sekunden)

1. Login → Header zeigt Genesis-Ark-Identität (nicht nur „Planet“ + Koordinate)
2. `/empire` → „Mein Imperium“-Card sichtbar, Rollen plausibel
3. Kolonie mit dominanter Mine → ⛏ Badge
4. Planetwechsel via Card + Switcher → Subtitle/Rolle aktualisiert ohne Reload
5. Bestandskonto mit Custom-Homeworld-Name → Name bleibt, Rolle „Hauptsitz“ erscheint trotzdem

---

## Referenz-Docs

- [ ] [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — GC-560 Scope & Verbote
- [ ] [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regeln 15–17 (Owner, keine Parallel-Systeme)
- [ ] [PLANET_SCOPE.md](PLANET_SCOPE.md) — `active_planet_id`, Switcher
- [ ] [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) — Evolution-System (unverändert)
- [ ] [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — State-Patch, kein Reload
- [ ] [STATE_AJAX.md](STATE_AJAX.md) — `planets[]` in game-state

---

## Nachfolger

| Ticket | Fokus |
|--------|-------|
| **GC-561** | Colony Roles — PlayerCard, Overview, weitere Surfaces; Algorithmus-Verfeinerung |
| **GC-562** | Evolution Unlock Gates — Planet Level schaltet Orte/Regionen frei (**Magie-Moment**) |
| **GC-563** | Command Map MVP |

---

## Ausgabe (nach Abschluss)

### Root Cause

### Changed Files

### Tests

### Ergebnis
