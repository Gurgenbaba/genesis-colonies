# GC-564 — Regions & Sectors (Visual Layer)



> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  

> **Priorität:** **M** — Welt-Identität, nach GC-563B  

> **Status:** ✅ erledigt (Datenlayer) — **Darstellung → [GC-564B](GC-564B_SPATIAL_COMMAND_MAP.md)**  

> **Stand:** 2026-06-12 (GC-564A ergänzt)  

> **Voraussetzung:** GC-560 ✅ · GC-563 ✅ · GC-562 ✅ · GC-562A ✅ · GC-563B ✅



Design Manifest: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · Command Map: [GC-563_COMMAND_MAP_MVP.md](GC-563_COMMAND_MAP_MVP.md) · Viewport: [GC-563B_COMMAND_MAP_VIEWPORT.md](GC-563B_COMMAND_MAP_VIEWPORT.md)



---



## GC-564A — Spec-Ergänzung (vor Implementierung)



> **Ancient Sector und Dark Expanse dürfen nicht leer sein.**



Jede Region enthält **mindestens einen sichtbaren, aber gesperrten Expansion-Site-Teaser** (🔒 + Level-Anforderung).



**Ziel:** Die Command Map soll **zukünftige Inhalte visualisieren**, nicht nur aktuelle Inhalte anzeigen.



| Region | Teaser-Sites (alle locked bis Homeworld-Level) |

|--------|------------------------------------------------|

| **Genesis Core** | 🏛 Hub + Kolonien (Spieler-Inhalt) |

| **Outer Rim** | 🔒 Frontier IX — Level 5 |

| **Ancient Sector** | 🔒 Ancient Relay — Level 10 · 🔒 Archive Nexus — Level 15 |

| **Dark Expanse** | 🔒 Abyss Gate — Level 20 · 🔒 Void Frontier — Level 25 |



**Kein Gameplay:** Teaser-Sites sind dieselbe Mechanik wie Frontier IX — statische Definition, Homeworld-Level-Gate, **nur Darstellung** bis GC-567.



**Regionen-Darstellung:** Keine dünnen Trennlinien — **echte Bänder/Panels** (Border, Padding, Header-Label). Mit GC-563B Pan/Zoom wirken das wie Kartensektoren.



**Spieler-Erkenntnis nach GC-564:**



```text

Mein Imperium → bekannte Welt → unerforschte Welt → ferne Welt

```



---



## Leitplanke (für Cursor)



> **Regionen sind in GC-564 nur Kontext — kein Gameplay.**  

> Sie erscheinen als **Panel-Bänder** auf `/galaxy?view=command_map`.  

> **`/empire` nicht anfassen.** Klassische **`/galaxy?view=system` nicht anfassen.**  

> **Keine Migration** — statische Definitionsdatei reicht.  

> **Keine parallelen Systeme** (GC-000 Regel 15): kein zweites Galaxy-/Region-Backend.  

> **Keine leeren Regionen** — jede Region hat ≥1 Expansion-Site-Teaser (GC-564A).



---



## Warum jetzt — und warum nur Spec zuerst



GC-563B liefert **Skalierung** (Pan/Zoom). Ohne Regionen bleibt die Map ein technisch korrektes, aber **weltlos wirkendes** Hub-and-Spoke-Diagramm.



Mit GC-564 + GC-564A wird daraus **Orientierung und Vorschau**:



```text

╔════════════════════════════╗

║      Genesis Core         ║

║  🏛   ⛏   🔬   ⚓   🛡      ║

╚════════════════════════════╝



╔════════════════════════════╗

║       Outer Rim           ║

║         🔒 Frontier IX    ║

╚════════════════════════════╝



╔════════════════════════════╗

║     Ancient Sector        ║

║  🔒 Ancient Relay         ║

║  🔒 Archive Nexus         ║

╚════════════════════════════╝



╔════════════════════════════╗

║      Dark Expanse         ║

║  🔒 Abyss Gate            ║

║  🔒 Void Frontier         ║

╚════════════════════════════╝

```



Regionen sind ein **Design-Schritt größer als Pan/Zoom** — deshalb erst diese Spec, dann Implementierung.



---



## Product-Ziel — der „Universum"-Moment



Der Spieler soll nicht nur sehen *„mein Imperium wächst"*, sondern *„vor mir liegt noch eine ganze Welt"*.



| Vor GC-564 | Nach GC-564 + 564A |

|------------|---------------------|

| Knoten + Kanten | Knoten **in benannten Sektoren** |

| Frontier IX schwebt am Hub | Frontier IX lebt in **Outer Rim** |

| Leere Flächen unten | **Teaser-Sites** in Ancient / Dark |

| Gesperrt = nur 🔒 | Gesperrt = 🔒 **in gedimmtem Region-Band** |



**Gameplay bleibt unverändert:** Kolonisierung, Kampf, Scan, Fleet — alles wie bisher über klassische Galaxy + bestehende Systeme.



---



## Scope (MVP) — visueller Region-Layer + Teaser-Sites



### Was rein gehört



1. **Statische Region-Definitionen** (keine DB, keine Migration)



   | `region_key` | Anzeige (DE) | Inhalt MVP |

   |--------------|--------------|------------|

   | `genesis_core` | Genesis Core | Hub + alle Spieler-Kolonien |

   | `outer_rim` | Outer Rim | 🔒 Frontier IX (L5) |

   | `ancient_sector` | Ancient Sector | 🔒 Ancient Relay (L10), 🔒 Archive Nexus (L15) |

   | `dark_expanse` | Dark Expanse | 🔒 Abyss Gate (L20), 🔒 Void Frontier (L25) |



   Felder pro Region (Minimum):



   ```python

   {

       "region_key": "outer_rim",

       "label_key": "imperium_region_outer_rim",

       "sort_order": 20,

       "layout_band": {"y_min_pct": 28.0, "y_max_pct": 44.0},

       "tone": "rim",

       "panel_style": "band",  # volles Panel, keine Trennlinie

   }

   ```



2. **Expansion Sites — kanonische Liste (GC-564A)**



   Erweiterung von `EXPANSION_SITES` in `expansion_gates.py` — **eine Quelle**, kein Parallel-Dict:



   ```python

   EXPANSION_SITES = {

       "frontier_ix": {

           "label_key": "expansion_site_frontier_ix",

           "required_homeworld_level": 5,

           "region_key": "outer_rim",

           "layout_slot": "center",

           "role_icon": "🌌",

       },

       "ancient_relay": {

           "label_key": "expansion_site_ancient_relay",

           "required_homeworld_level": 10,

           "region_key": "ancient_sector",

           "layout_slot": "west",

           "role_icon": "🏛",

       },

       "archive_nexus": {

           "label_key": "expansion_site_archive_nexus",

           "required_homeworld_level": 15,

           "region_key": "ancient_sector",

           "layout_slot": "east",

           "role_icon": "📜",

       },

       "abyss_gate": {

           "label_key": "expansion_site_abyss_gate",

           "required_homeworld_level": 20,

           "region_key": "dark_expanse",

           "layout_slot": "west",

           "role_icon": "🕳",

       },

       "void_frontier": {

           "label_key": "expansion_site_void_frontier",

           "required_homeworld_level": 25,

           "region_key": "dark_expanse",

           "layout_slot": "east",

           "role_icon": "🌑",

       },

   }

   ```



   `layout_slot` innerhalb der Region-Band (relativ, nicht global hub-and-spoke).



3. **`region_key` auf Knoten**

   - **Homeworld + Kolonien** → `genesis_core` (MVP: alle owned planets)

   - **Expansion Sites** → `region_key` aus Definition



4. **Command Map Payload erweitern**



   ```python

   {

       "nodes": [...],       # je Node: region_key, layout innerhalb Band

       "edges": [...],       # Hub→Site nur innerhalb sinnvoller Verbindung; Cross-Region optional dezent

       "expansion": {...},

       "regions": [

           {

               "region_key": "genesis_core",

               "label_key": "imperium_region_genesis_core",

               "sort_order": 10,

               "layout_band": {"y_min_pct": 4.0, "y_max_pct": 24.0},

               "tone": "core",

               "node_count": 3,

               "is_dimmed": false,

               "teaser_count": 0,

           },

           {

               "region_key": "outer_rim",

               "is_dimmed": true,   # solange alle Sites locked

               "teaser_count": 1,

               ...

           },

           ...

       ],

   }

   ```



   `is_dimmed`: Region-Panel gedimmt, wenn **alle** Sites der Region noch locked (Outer/Ancient/Dark); Genesis Core nie gedimmt.



5. **Template — Region-Panel-Bänder (GC-564A)**



   - Pro Region: `.galaxy-command-map-region.galaxy-command-map-region--{tone}`

   - **Volles Panel:** Border, Hintergrund-Gradient, Padding, abgerundete Ecken — **keine dünnen Divider-Linien**

   - Header: Region-Label oben im Band (`.galaxy-command-map-region-title`)

   - Body: Platz für Knoten innerhalb des Bands (absolute % relativ zum Band)

   - Region-Layer `pointer-events: none`; Knoten interaktiv (Kolonie-Switch) bzw. Expansion locked

   - **Locked Teaser:** Site-Knoten + Region-Band gedimmt; Label + Level-Anforderung sichtbar



6. **Layout in `command_map.py`**

   - Vertikale Staffelung: Core → Rim → Ancient → Dark (Canvas-Höhe wächst oder Bands stacked)

   - Hub = Zentrum **Genesis Core**-Band (Reset „Zentrum" bleibt Genesis Ark)

   - Sites pro Region horizontal verteilt (`layout_slot` west/center/east)

   - `fitAllNodes()` / Viewport: Bounding-Box über **alle Region-Panels**



7. **Locales** — `imperium_region_*` + `expansion_site_*` für alle 5 Sites DE/EN



8. **Tests** — Region-Defs, alle Sites→Region, keine leere Region, Payload `regions[]`, Template-Panel-Marker



---



### Was explizit NICHT rein gehört



| Verboten | Ticket / Grund |

|----------|----------------|

| Regionen als Gameplay-Modifikator (Produktion, Risiko, Kampf) | GC-566 / GC-568 |

| `[G:S]`-Koordinaten-Mapping auf Regionen | GC-567 |

| Kolonisierung blockieren/enforcen per Region | GC-567 |

| Scan-/Fleet-Regeln pro Region | GC-565 / GC-568 |

| Spieler-Overlays / fremde Imperien | GC-569 Presence Layer |

| Fog of War | — |

| Leere Region-Bänder ohne Teaser | **GC-564A verbietet** |

| Neue DB-Tabellen / Migration | — |

| `/empire` | — |

| Klassische Galaxy-Systemansicht | — |

| Chokepoints | GC-565 |



---



## Visuelles Zielbild (Mock — keine Pixel-Spec)



```text

┌─────────────────────────────────────────┐

│ ╔═══════════════════════════════════╗   │

│ ║         GENESIS CORE              ║   │

│ ║    🏛 Genesis Ark   ⛏  🔬  ⚓      ║   │

│ ╚═══════════════════════════════════╝   │

│                                         │

│ ╔═══════════════════════════════════╗   │

│ ║          OUTER RIM        (dim)   ║   │

│ ║           🔒 Frontier IX          ║   │

│ ║      Benötigt Evolution L5      ║   │

│ ╚═══════════════════════════════════╝   │

│                                         │

│ ╔═══════════════════════════════════╗   │

│ ║        ANCIENT SECTOR     (dim)   ║   │

│ ║  🔒 Ancient Relay    🔒 Archive   ║   │

│ ║       L10                  L15    ║   │

│ ╚═══════════════════════════════════╝   │

│                                         │

│ ╔═══════════════════════════════════╗   │

│ ║        DARK EXPANSE       (dim)   ║   │

│ ║  🔒 Abyss Gate       🔒 Void      ║   │

│ ║       L20                  L25    ║   │

│ ╚═══════════════════════════════════╝   │

└─────────────────────────────────────────┘

              [ Zentrum ] → Genesis Ark

```



**Progression sichtbar:** Level 5 → Outer Rim heller · L10 → Ancient Relay unlock · usw. Region bleibt benannt; `is_dimmed` wird false, sobald ≥1 Site in der Region unlocked.



---



## Technische Leitplanken



### Owner (GC-000 Regel 17)



| Modul | Verantwortung |

|-------|---------------|

| **`game/planet_evolution/imperium_regions.py`** (neu) | `IMPERIUM_REGIONS`, `region_for_colony()`, `build_regions_payload()`, `region_is_dimmed()` |

| **`game/planet_evolution/expansion_gates.py`** | Alle 5 Sites + `region_key`; Site-Rows unverändert über bestehende Gate-Logik |

| **`game/planet_evolution/command_map.py`** | Region-Band-Layout, nodes mit `region_key`, `regions[]` Payload |

| **`templates/partials/galaxy_command_map_panel.html`** | Region-Panel-Bänder SSR |

| **`static/style.css`** | `.galaxy-command-map-region` Panel-Styles, `--dimmed`, `--core/rim/ancient/dark` |



### Kolonie → Region (MVP-Regel)



```python

def region_for_colony(planet_row) -> str:

    """MVP: alle Spieler-Planeten liegen in genesis_core."""

    return "genesis_core"

```



### Locked Sites + Region (GC-564A)



- **Jede Region** hat ≥1 Site in `EXPANSION_SITES` (Genesis Core ausgenommen — Spieler-Kolonien).

- Region-Panel immer gerendert (4 Bänder).

- `is_dimmed=True` wenn alle Sites der Region `is_locked`.

- Teaser zeigen **Name + Level-Anforderung** — gleiche Copy wie GC-562A locked nodes.



### Viewport (GC-563B)



- Region-Panels innerhalb `.galaxy-command-map-canvas` — Pan/Zoom transformiert alles gemeinsam.

- Canvas `min-height` / aspect-ratio ggf. anpassen für 4 gestapelte Bänder.

- `fitAllNodes()` über alle Region-Bands + Knoten.



---



## Betroffene Dateien (Implementierung — max. ~7 Kern)



- `game/planet_evolution/imperium_regions.py` — **neu**

- `game/planet_evolution/expansion_gates.py` — 5 Sites + `region_key`

- `game/planet_evolution/command_map.py` — region-band layout + payload

- `templates/partials/galaxy_command_map_panel.html` — Panel-Bänder

- `static/style.css` — Region-Panel-Styles (keine dünnen Linien)

- `locales/de.json`, `locales/en.json`

- `tests/test_imperium_regions.py` — **neu**; `tests/test_expansion_gates.py` erweitern



**Nicht bearbeiten:** `templates/empire.html`, `game/empire_page.py`, `game/galaxy.py`, klassische Galaxy-Templates, Fleet/Combat



---



## Implementierungsreihenfolge (wenn Spec approved)



```text

1. imperium_regions.py — 4 Regionen, build_regions_payload(), is_dimmed

2. expansion_gates.py — 5 EXPANSION_SITES mit region_key + Levels

3. command_map.py — vertikale Bands, Sites in Region, regions[] Payload

4. Template — Panel-Bänder mit Header + dim state

5. CSS — volle Bänder (border/padding/gradient), tone variants

6. Locales — region + 4 neue site keys

7. Tests — keine leere Region, Site→Region, dim logic, Template markers

8. Manuell: Pan/Zoom über 4 Bänder, Reset Zentrum → Genesis Ark

```



---



## Akzeptanzkriterien



- [ ] 4 **Panel-Bänder** sichtbar (keine dünnen Trennlinien)

- [ ] **Genesis Core:** Hub + Kolonien, Band nicht gedimmt

- [ ] **Outer Rim:** 🔒 Frontier IX (L5), Band gedimmt bis Unlock

- [ ] **Ancient Sector:** 🔒 Ancient Relay (L10) + 🔒 Archive Nexus (L15) — **nicht leer**

- [ ] **Dark Expanse:** 🔒 Abyss Gate (L20) + 🔒 Void Frontier (L25) — **nicht leer**

- [ ] Homeworld Level ≥5: Frontier IX unlocked, Outer Rim nicht mehr voll gedimmt (wenn alle Sites unlocked → Band hell)

- [ ] Jeder Node: `region_key`; jede Region: ≥1 Teaser-Site in Payload

- [ ] Planet Evolution „Nächste Freischaltung" zeigt weiterhin **nächste** locked Site (Frontier IX bei L4)

- [ ] Keine Kolonisierungs-/Kampf-/Scan-Regeln; `/empire` + klassische Galaxy unverändert

- [ ] Keine Migration

- [ ] Pan/Zoom (GC-563B) über alle Bänder

- [ ] `pytest tests/test_imperium_regions.py tests/test_expansion_gates.py tests/test_command_map.py -v` grün



---



## Cursor-Prompt (Implementierung — erst nach Spec-Review)



```md

Implementiere GC-564 inkl. GC-564A exakt nach docs/GC-564_REGIONS_SECTORS.md.



Priorität:

1. imperium_regions.py — 4 Region-Panel-Defs, is_dimmed, build_regions_payload()

2. expansion_gates.py — 5 EXPANSION_SITES mit region_key (Frontier IX + 4 Teaser)

3. command_map.py — vertikale Region-Bands, Sites in Region, regions[] Payload

4. Template + CSS — volle Panel-Bänder (nicht dünne Linien), locked Teaser gedimmt

5. Ancient Sector + Dark Expanse dürfen NICHT leer sein (GC-564A)

6. Kolonien MVP: alle genesis_core

7. /empire + klassische /galaxy nicht anfassen

8. GC-563B Viewport muss über alle Bänder funktionieren



Akzeptanz: visueller Layer only — Teaser-Sites = locked Expansion Sites, kein Gameplay.

```



---



## EPIC-15 — Reihenfolge (aktualisiert)



```text

GC-560  Identity              ✅

GC-563  Command Map MVP       ✅

GC-562  Evolution Gates       ✅

GC-562A Polish                ✅

GC-563B Viewport              ✅

GC-564  Regions + Teaser      📋 Spec ← dieses Ticket (+ GC-564A)

GC-565  Chokepoints

GC-566  Influence

GC-567  Expansion Sites (Depth + [G:S])

GC-568  Territorial Warfare

GC-569  Presence Layer

```



**Vision:**



> Mein Imperium → bekannte Welt → unerforschte Welt → ferne Welt → (später) Universum & andere Spieler.



---



## Referenz-Docs



- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Regionen langfristig — **GC-564 Phase 1: Panels + Teaser**

- [GC-562_EVOLUTION_UNLOCK_GATES.md](GC-562_EVOLUTION_UNLOCK_GATES.md) — Gate-Mechanik für alle Sites

- [GC-563B_COMMAND_MAP_VIEWPORT.md](GC-563B_COMMAND_MAP_VIEWPORT.md) — Canvas/Viewport

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regeln 15–17



---



## Ausgabe (nach Abschluss — Implementierung)



### Root Cause



### Changed Files



### Tests



### Ergebnis


