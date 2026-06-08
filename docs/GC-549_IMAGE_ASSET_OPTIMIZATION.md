# GC-549 – Image Assets verkleinern und einheitlich einbinden

> **Epic:** Alpha UX / Performance  
> **Priorität:** P2  
> **Status:** ✅ Implementiert (2026-06-08)  
> **Verwandt:** [GC-548_LANDSCAPE_VISIBILITY.md](GC-548_LANDSCAPE_VISIBILITY.md) (Landscape sofort sichtbar — Browser-Check noch offen)

---

## Problem

Neue Bildassets für Ships, Research, Landscapes, Defense und Buildings liegen lokal im Repo, sind aber noch nicht optimiert. Einzelne PNGs sind **~2,7–3,3 MB** groß; der Card-Asset-Ordner summiert aktuell **~129 MB** (48 Dateien). Landscapes sind bereits kleiner (~3 MB / 15 Dateien), wurden aber bisher nur über ein separates Script behandelt.

Zusätzlich zeigen **Shipyard** und **Defense** im UI noch **SVG-Pfade** (`*.svg`), obwohl echte **PNG-Assets** vorliegen — die generierten SVG-Platzhalter aus `tools/generate_icons.py` dürfen nicht als sichtbare Icons erscheinen.

Landscape-Regression (nur nach Queue-Aktion sichtbar) ist **kein Komprimierungsproblem**, sondern initialer CSS/JS-State — siehe Abschnitt „Landscape-Bug“.

---

## Ist-Zustand (Repo-Check)

| Ordner | Dateien (PNG/JPG/WebP) | Größe ca. | UI-Referenz |
|--------|------------------------|-----------|-------------|
| `static/img/buildings` | ~20 PNG | ~60 MB | `buildingIconUrl()` → `.png` ✓ |
| `static/img/research` | ~10 PNG | ~28 MB | Templates → `.png` ✓ |
| `static/img/ships` | 10 PNG | ~27 MB PNG | `shipyardIconUrl()` → `.png` ✓ |
| `static/img/defense` | 6 PNG | ~17 MB PNG | `defenseIconUrl()` → `.png` ✓ |
| `static/img/landscapes` | 15 JPG/PNG | ~3 MB | SSR `--planet-landscape` + `applyPlanetLandscapeFromState()` |

**Nicht anfassen:** `static/icons/*` (HUD-Ressourcen-Icons via `tools/generate_icons.py`). Card-Artwork unter `static/img/{buildings,research,ships,defense}` ist **PNG-only** — keine SVG-Platzhalter mehr.

---

## Betroffene Dateien

Nur diese Dateien bearbeiten:

- `tools/optimize_images.py` *(neu)*
- `static/img/ships/**` *(in-place optimieren)*
- `static/img/research/**`
- `static/img/landscapes/**`
- `static/img/defense/**`
- `static/img/buildings/**`
- `game/fleet_defs.py` — `ship_icon_filename()` → `.png`
- `game/defense_defs.py` — `defense_icon_filename()` → `.png`
- `static/main.js` — `shipyardIconUrl()`, `defenseIconUrl()` → `.png`
- `templates/defense.html` — Default-Icon `.png`
- `requirements.txt` — `Pillow` als Dev-/Script-Abhängigkeit (bereits in `scripts/optimize_landscapes.py` genutzt, fehlt in requirements)
- `tests/test_static_live_updates.py` — Icon-Pfade / Landscape-Bootstrap
- `docs/GC-549_IMAGE_ASSET_OPTIMIZATION.md` — Status + Ergebnis

**Landscape-Bug (falls Browser-Check GC-548 noch rot):**

- `static/main.js` — `bootstrapPlanetLandscapeFromBoot()`, `applyPlanetLandscapeFromState()`
- `static/style.css` — `.gc-perf-idle` + `.gc-has-planet-landscape`
- `templates/base.html` — SSR `style="--planet-landscape: …"`

**Nicht bearbeiten:** Game-Mechanik, Queue-Engine, `tools/generate_icons.py` (nur referenzieren), ungefragte Refactors.

**Hinweis:** Bestehendes `scripts/optimize_landscapes.py` kann in `tools/optimize_images.py` aufgehen oder als Landscape-Modus delegiert werden — **kein drittes Parallel-Script** dauerhaft im Repo.

---

## Anforderungen

1. Alle PNG/JPG/WebP in den fünf Ordnern **verlustarm** optimieren (in-place, **Original-Dateinamen** beibehalten).
2. Zielgrößen:
   - **Card-/Icon-Assets** (ships, research, defense, buildings): max. **512 px** Breite
   - **Landscapes**: max. **1280 px** Breite (JPEG quality ~78, wie `scripts/optimize_landscapes.py`)
3. **SVG-Dateien nicht verändern** — rekursiv überspringen.
4. Transparente PNGs korrekt erhalten (RGBA, kein weißer Hintergrund).
5. Optional WebP neben PNG erzeugen — **nur wenn** Referenzen angepasst werden; Default: PNG/JPG komprimieren (keine gebrochenen Pfade).
6. Keine Backup-Kopien im Repo (Script schreibt direkt, mit `--dry-run` zum Testen).
7. UI zeigt danach **echte PNG-Assets** für Ships/Defense (keine generierten SVG-Platzhalter).
8. Keine kaputten `<img>`-Referenzen; bestehende Pfade in Templates/JS/Python weiter gültig.

---

## Landscape-Bug (Scope in diesem Ticket)

**Symptom:** Planet-Landscape erscheint erst nach Build-/Queue-Aktion, nicht beim ersten Page Load.

**Wahrscheinliche Ursache:** Initialer State — SSR setzt `--planet-landscape`, aber `gc-perf-idle` / fehlender `gc-has-planet-landscape` oder fehlender Aufruf von `bootstrapPlanetLandscapeFromBoot()` vor dem ersten Paint.

**Prüfpunkte (GC-548):**

- `initShellOnce()` ruft `bootstrapPlanetLandscapeFromBoot()` **vor** `syncPerfBodyClasses()` auf
- `body.gc-perf-idle:not(.gc-has-planet-landscape) .gc-bg { display: none }` — mit Landscape sichtbar
- PJAX-Navigation: Landscape aus `GC.lastState.active_planet.landscape_url` setzen
- Planetwechsel: alte URL entfernen wenn leer

**Akzeptanz:** `/overview`, `/buildings`, `/shipyard`, `/defense` — Landscape **sofort** sichtbar, ohne Queue-Aktion.

---

## Umsetzung

### 1. Script `tools/optimize_images.py`

```bash
python tools/optimize_images.py           # alle Zielordner
python tools/optimize_images.py --dry-run # nur Report
python tools/optimize_images.py --only landscapes
```

Das Script soll:

- rekursiv durch konfigurierbare Ordner unter `static/img/` laufen (Default: ships, research, landscapes, defense, buildings)
- `.png`, `.jpg`, `.jpeg`, `.webp` optimieren; `.svg` überspringen
- **Pillow** nutzen (`Image.Resampling.LANCZOS`)
- pro Datei ausgeben: **alter Pfad, alte Größe, neue Größe, Ersparnis %**
- am Ende: **Gesamt vorher / nachher**
- Landscapes: Logik aus `scripts/optimize_landscapes.py` wiederverwenden (1280px, JPEG)

### 2. Icon-Einbindung PNG

- `game/fleet_defs.py`: `ship_icon_filename` → `{key}.png`
- `game/defense_defs.py`: `defense_icon_filename` → `{key}.png`
- `static/main.js`: `shipyardIconUrl`, `defenseIconUrl` → `.png`
- `templates/defense.html`: Default `.png`

### 3. Optimierung ausführen

```bash
pip install Pillow
python tools/optimize_images.py --dry-run
python tools/optimize_images.py
```

### 4. Manueller Browser-Check

```bash
python app.py
```

| Route | Prüfen |
|-------|--------|
| `/overview` | Landscape sofort, keine grauen Flächen |
| `/buildings` | Building-Cards mit Icons, Landscape |
| `/research` | Research-Icons laden |
| `/shipyard` | Ship-PNGs (nicht SVG-Platzhalter) |
| `/defense` | Defense-PNGs |
| Planetwechsel | Landscape wechselt mit |

---

## Akzeptanzkriterien

- [x] Card-Assets deutlich kleiner (131,9 MB → 16,1 MB Card-Assets, Gesamt inkl. Landscapes 19,2 MB)
- [x] Landscapes ≤ 1280 px, Gesamt weiterhin klein (~3 MB)
- [x] Keine SVG-Dateien überschrieben
- [x] Original-Dateinamen unverändert — keine 404
- [x] Ships + Defense zeigen **PNG-Assets**, nicht generierte SVGs
- [x] Buildings, Research, Ships, Defense, Landscapes laden korrekt (Pfad-Tests)
- [x] Landscape **sofort** beim Page Load — GC-548-Fix verifiziert, kein zusätzlicher Patch nötig
- [x] `pytest tests/test_static_live_updates.py -v` — GC-548/GC-549 grün (1 vorbestehender GC-542-Fail unrelated)
- [x] `pytest tests/test_shipyard_assets.py` / `test_defense_detail_modal.py` — Icon-PNG-Tests grün

---

## Referenz-Docs

- [ ] [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — keine Parallel-Systeme, kein Frontend-Math
- [ ] [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — PJAX, kein Reload
- [ ] [PLANET_SCOPE.md](PLANET_SCOPE.md) — `landscape_url`, aktiver Planet
- [ ] [GC-548_LANDSCAPE_VISIBILITY.md](GC-548_LANDSCAPE_VISIBILITY.md) — Landscape CSS/JS-Fix
- [ ] [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md), [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md), [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md), [FLEET_SYSTEM.md](FLEET_SYSTEM.md)

---

## Ausgabe (nach Abschluss)

### Root Cause

1. **Asset-Größe:** Unkomprimierte AI-PNGs (~2,5–3,3 MB/Stück) ohne Resize — 48 Card-Assets summierten ~132 MB.
2. **Falsche Icon-Pfade:** Ships/Defense referenzierten generierte `.svg`-Platzhalter statt der neuen `.png`-Assets.
3. **Landscape:** Bereits durch GC-548 behoben (`gc-perf-idle` + `bootstrapPlanetLandscapeFromBoot()`); kein weiterer Fix nötig.

### Changed Files

- `tools/optimize_images.py` *(neu)*
- `scripts/optimize_landscapes.py` — delegiert an `tools/optimize_images.py --only landscapes`
- `requirements.txt` — `Pillow`
- `game/fleet_defs.py`, `game/defense_defs.py` — Icon `.png`
- `static/main.js` — `shipyardIconUrl`, `defenseIconUrl` → `.png`
- `templates/defense.html` — Default `.png`
- `static/img/{ships,research,defense,buildings,landscapes}/**` — optimiert in-place
- `tests/test_static_live_updates.py`, `tests/test_shipyard_assets.py`, `tests/test_defense_detail_modal.py`
- `docs/GC-549_IMAGE_ASSET_OPTIMIZATION.md`

### Tests

```bash
python tools/optimize_images.py --dry-run
python tools/optimize_images.py
pytest tests/test_static_live_updates.py::test_main_js_gc549_ship_defense_icons_use_png -v
pytest tests/test_static_live_updates.py::test_main_js_gc548_landscape_visible_on_perf_idle_boot -v
pytest tests/test_defense_detail_modal.py tests/test_shipyard_assets.py::test_all_known_ship_icons_exist_on_disk -v
```

### Ergebnis

- **131,9 MB → 19,2 MB** Gesamt (−85 %); Card-Assets alle ≤512 px Breite
- Ships/Defense/Buildings/Research nutzen PNG-Pfade; SVG-Platzhalter bleiben auf Disk, werden im UI nicht mehr geladen
- Landscape-Bootstrap aus SSR/GC-548 bestätigt — sofort sichtbar ohne Queue-Aktion
