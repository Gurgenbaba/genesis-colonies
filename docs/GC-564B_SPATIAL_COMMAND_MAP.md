# GC-564B — Spatial Command Map (Sternenkarte statt Freischaltbaum)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **H** — Darstellungs-Korrektur nach GC-564  
> **Status:** ✅ erledigt  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-564 ✅ · GC-563B ✅

Vorgänger: [GC-564_REGIONS_SECTORS.md](GC-564_REGIONS_SECTORS.md) (Daten + Region-Keys — **bleibt**)

---

## Diagnose — warum GC-564 noch nicht „Universum" fühlt

GC-564 liefert technisch korrekt:

- `region_key` auf Knoten
- Teaser-Sites pro Region
- Gates + dimmed State
- Pan/Zoom

Die **Darstellung** ist jedoch:

```text
Liste → horizontale Container → Knoten
```

Das Gehirn liest: **Tech-Tree / Freischaltbaum**.

Gewünscht:

```text
Raum → Entfernung → Richtung → Expansion
```

**Architektur + Daten: ~70 % richtig. Darstellung: ~30–40 % auf dem Weg zur Vision.**

GC-564B ändert **nur Layout + Visual Layer** — keine neue Mechanik, keine Migration, keine Spieler-Overlays.

---

## Leitplanke (für Cursor)

> Regionen **bleiben** — aber als **Nebel-/Territoriums-Hintergrund**, nicht als Box-Container.  
> Knoten liegen **frei im Raum** um Genesis Ark.  
> **`/empire` nicht anfassen.** Klassische **`/galaxy` nicht anfassen.**  
> **Keine fremden Spieler** auf der Imperiumskarte — Präsenz = [GC-569](GC-569_PRESENCE_LAYER.md) (separater Toggle).

---

## Was bleibt unverändert (GC-564 Datenlayer)

| Behalten | Owner |
|----------|-------|
| `IMPERIUM_REGIONS`, `region_key`, `is_dimmed` | `imperium_regions.py` |
| 5 `EXPANSION_SITES`, Homeworld-Gates | `expansion_gates.py` |
| Edges (trade, hub_link, expansion_locked/unlocked) | `command_map.py` |
| Pan/Zoom, Zentrum → Genesis Ark | `main.js` GC-563B |
| Planet Evolution Teaser | `dashboard.py` |

**Nur ersetzen:** `layout_band` (horizontale Streifen) → **`layout_zone`** (räumliche Zone) + **spatial node placement**.

---

## Zielbild — räumliche Sternenkarte

```text
                    ✦ Dark Expanse (Nebel oben)
              🔒 Abyss Gate        🔒 Void Frontier


        🔒 Ancient Relay              🔒 Archive Nexus
              (Ancient Sector Nebel — rechts/oben)


              🔒 Frontier IX
                 (Outer Rim Nebel — nord)


                    🏛 Genesis Ark
           ⛏              🔬              ⚓
                        🛡

              (Genesis Core Nebel — zentral, hell)
```

**Keine sichtbaren Rechteck-Boxen.** Region-Labels dezent **in** der Nebelzone (floating caption), nicht als Panel-Header.

---

## Scope (MVP)

### 1. Spatial Layout Engine (`command_map.py`)

- **Hub fix:** Genesis Ark bei `(50%, 52%)` — visuelles Zentrum der Karte
- **Kolonien:** Ring um Hub (Radius ~14–20 %), Winkel nach Rolle:
  - mining → SW, research → NW, shipyard → E, fortress → S, …
- **Expansion Sites:** Position nach Region + `layout_bearing` (statisch):

  | Site | Region | Bearing (Grad von Hub) | Radius % |
  |------|--------|------------------------|----------|
  | frontier_ix | outer_rim | 0° (N) | 38 |
  | ancient_relay | ancient_sector | 55° (NE) | 42 |
  | archive_nexus | ancient_sector | 75° (E) | 48 |
  | abyss_gate | dark_expanse | 350° (NNW) | 52 |
  | void_frontier | dark_expanse | 20° (NNE) | 55 |

  Formel: `x = cx + r * sin(θ)`, `y = cy - r * cos(θ)` (Server-seitig, Regel 16)

### 2. Region Zones statt Bands (`imperium_regions.py`)

Ersetze / ergänze `layout_band` durch `layout_zone`:

```python
"genesis_core": {
    "layout_zone": {
        "kind": "ellipse",
        "cx_pct": 50.0, "cy_pct": 52.0,
        "rx_pct": 28.0, "ry_pct": 22.0,
    },
},
"outer_rim": {
    "layout_zone": {
        "kind": "ellipse",
        "cx_pct": 50.0, "cy_pct": 22.0,
        "rx_pct": 32.0, "ry_pct": 18.0,
    },
},
# ancient_sector: ellipse rechts-oben
# dark_expanse: ellipse oben/weit
```

`build_regions_payload()` liefert `layout_zone` statt `layout_band` für Template/SVG.

### 3. Hintergrund-Layer (Template + CSS)

- **Entfernen:** `.galaxy-command-map-region` Rechteck-Panels mit Border/Header-Box
- **Neu:** SVG `<ellipse>` / `<path>` pro Region unter Knoten:
  - `.galaxy-command-map-nebula--core` — teal glow, nicht gedimmt
  - `--rim`, `--ancient`, `--dark` — Tone-Farben
  - `.is-dimmed` → niedrigere Opacity + desaturate (wie heute, aber auf Nebel)
- Region-Titel: kleine Caption **innerhalb** der Ellipse (opacity 0.5), nicht als Panel-Titel

### 4. Canvas-Proportionen

- Zurück zu **quadratischer / breiter** Canvas (nicht vertikal gestapelt)
- `min-height` moderat (~520–620px); Pan/Zoom für weite Entfernungen

### 5. Edges

- Hub → Expansion Sites: weiterhin `expansion_locked` / `expansion_unlocked`
- Lange diagonale Kanten **gewollt** — vermitteln Entfernung
- Trade routes + hub_link unverändert

---

### Explizit NICHT in GC-564B

| Verboten | Ticket |
|----------|--------|
| Fremde Spieler auf Imperiumskarte | GC-569 Presence Layer |
| `[ Imperium ]` / `[ Präsenz ]` Toggle | GC-569 |
| Gameplay-Modifikatoren pro Region | GC-566 / GC-568 |
| Chokepoints | GC-565 |
| Migration / DB | — |
| `/empire`, klassische Galaxy | — |

---

## Presence Overlay — Vision (GC-569, nicht GC-564B)

Ebene 1 — **Command Map:** nur eigenes Imperium (wie heute).

Ebene 2 — optionaler Toggle:

```text
[ Imperium ]  [ Präsenz ]
```

Präsenz zeigt fremde Marker (🔴🟢🟡) — **Standard: AUS**. Kein Mischmodell auf derselben Ebene ohne Toggle.

---

## Betroffene Dateien (Implementierung)

- `game/planet_evolution/imperium_regions.py` — `layout_zone`, Payload-Anpassung
- `game/planet_evolution/command_map.py` — polar/spatial layout statt band stack
- `templates/partials/galaxy_command_map_panel.html` — SVG Nebel-Layer, keine Box-Panels
- `static/style.css` — Nebula-Styles, Box-Panel-Styles entfernen/deprecated
- `tests/test_imperium_regions.py`, `tests/test_command_map.py` — Layout-Assertions anpassen

**Nicht:** `expansion_gates.py` Site-Defs (außer optional `layout_bearing`), `/empire`, `galaxy.py`

---

## Akzeptanzkriterien

- [ ] Keine horizontalen Region-Container / Box-Listen mehr sichtbar
- [ ] Genesis Ark visuell zentral; Kolonien im Ring drumherum
- [ ] Expansion Sites räumlich verteilt (N / NE / E / NNW — nicht gestapelt)
- [ ] Regionen als Nebel-Ellipsen im Hintergrund, Tone + dimmed
- [ ] Alle 5 Teaser-Sites + Kolonien weiter sichtbar (GC-564A)
- [ ] Pan/Zoom + Zentrum funktionieren
- [ ] Subjektiv: Karte wirkt wie **Raum**, nicht wie Freischaltbaum
- [ ] `/empire` + klassische Galaxy unverändert
- [ ] Tests grün

---

## Cursor-Prompt (Implementierung)

```md
Implementiere GC-564B exakt nach docs/GC-564B_SPATIAL_COMMAND_MAP.md.

GC-564 Datenlayer behalten (region_key, sites, gates, dimmed).
Nur Darstellung ändern:

- Horizontale Region-Boxen entfernen
- Spatial/polar Layout um Genesis Ark
- Regionen als SVG-Nebel-Ellipsen (Hintergrund)
- Knoten frei im Raum
- Kein neues Gameplay, keine Migration, keine fremden Spieler
- GC-563B Pan/Zoom muss funktionieren
```

---

## EPIC-15 — Reihenfolge (aktualisiert)

```text
GC-564   Region Data + Teaser Sites     ✅
GC-564B  Spatial Sternenkarte           ✅
GC-565   Chokepoints / Pfade            ✅
GC-566   Influence / Eigenreich-Fläche  ✅
GC-567   Expansion Sites v2             ✅
GC-567B  Region Landmarks               ✅
GC-570   World Map + Role Actions       ✅
GC-566B  Dynamic Influence              ⬅ nächster Schritt
GC-571   Shared World Presence
GC-568   Territorial Warfare
```

---

## Referenz

- [GC-564_REGIONS_SECTORS.md](GC-564_REGIONS_SECTORS.md) — Datenlayer (bleibt gültig)
- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Mockup-Richtung (Raum, nicht Liste)

---

## Ausgabe (nach Abschluss)

### Root Cause

Horizontale Region-Boxen (GC-564) lasen sich als Freischaltbaum — nicht als Sternenkarte.

### Changed Files

- `game/planet_evolution/imperium_regions.py` — `layout_zone` Ellipsen statt `layout_band`
- `game/planet_evolution/expansion_gates.py` — `layout_bearing_deg` + `layout_radius_pct`
- `game/planet_evolution/command_map.py` — polar/spatial layout um Hub (50%, 52%)
- `templates/partials/galaxy_command_map_panel.html` — SVG-Nebel-Layer, keine Box-Panels
- `static/style.css` — Nebula-Styles, quadratischer Canvas
- Tests + docs/ROADMAP/EPICS

### Tests

`pytest tests/test_imperium_regions.py tests/test_command_map.py tests/test_command_map_viewport.py tests/test_expansion_gates.py -q` → 24 passed

### Ergebnis

Genesis Ark zentral; Kolonien im Ring; Expansion Sites räumlich verteilt; Regionen als Nebel-Ellipsen; Pan/Zoom/Zentrum unverändert.
