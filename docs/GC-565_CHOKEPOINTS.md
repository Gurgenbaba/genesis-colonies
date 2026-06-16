# GC-565 — Chokepoints (Gate-Knoten zwischen Regionen)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **H** — strategische Kartenschicht nach GC-564B  
> **Status:** ✅ Implementiert  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-564B ✅

Design Manifest: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · Spatial Map: [GC-564B_SPATIAL_COMMAND_MAP.md](GC-564B_SPATIAL_COMMAND_MAP.md)

---

## Leitplanke (für Cursor)

> **GC-565 = visuelle Engstellen** auf der Command Map — Gate-Knoten **zwischen** Regionen.  
> **Kein Fleet-/Scan-Enforcement** in diesem Ticket (→ GC-568).  
> **Kein Influence-Fill** (→ GC-566). **Keine fremden Spieler** (→ GC-569).  
> **`/empire` nicht anfassen.** Klassische **`/galaxy` nicht anfassen.**  
> **Keine Migration** — statische Definitionsdatei.

---

## Warum jetzt — nach GC-564B

GC-564B liefert **Raum** (Nebel, polar layout, Entfernung).  
Ohne Chokepoints fehlt die **strategische Lesbarkeit**:

```text
Wie komme ich von Genesis Core nach Outer Rim?
→ Durch den Helios Corridor.
```

Das Referenzbild zeigt nicht nur Orte, sondern **Pfade und Engstellen**. GC-565 macht die Karte strategisch — noch ohne Kampfregeln.

---

## Product-Ziel

| Vor GC-565 | Nach GC-565 |
|------------|-------------|
| Hub → Site direkt (eine Kante) | Hub → **Gate** → Site (Pfad durch Engpass) |
| Regionen schweben nebeneinander | Regionen **verbunden** durch benannte Korridore |
| „Schöne Karte" | „Karte mit **Zugängen**" |

Spieler versteht: *Expansion passiert durch benannte Pforten — nicht teleportiert.*

---

## Scope (MVP) — nur Darstellung

### Was rein gehört

1. **Statische Chokepoint-Definitionen** (`game/planet_evolution/chokepoints.py` — **neu**)

   ```python
   CHOKEPOINTS = {
       "helios_corridor": {
           "label_key": "chokepoint_helios_corridor",
           "connects_regions": ["genesis_core", "outer_rim"],
           "layout_bearing_deg": 0,
           "layout_radius_pct": 28.0,
           "role_icon": "🚪",
       },
       "ancient_threshold": {
           "label_key": "chokepoint_ancient_threshold",
           "connects_regions": ["outer_rim", "ancient_sector"],
           "layout_bearing_deg": 35,
           "layout_radius_pct": 36.0,
           "role_icon": "⛩",
       },
       "void_rift": {
           "label_key": "chokepoint_void_rift",
           "connects_regions": ["ancient_sector", "dark_expanse"],
           "layout_bearing_deg": 15,
           "layout_radius_pct": 46.0,
           "role_icon": "🌀",
       },
   }
   ```

2. **Command Map Integration**
   - Neuer `node_kind`: `chokepoint`
   - Position polar um Hub (wie Expansion Sites) — **zwischen** den verbundenen Regionen
   - Kanten-Umleitung:
     - Statt `hub → expansion_site` direkt: `hub → chokepoint → expansion_site` (wenn Site in Ziel-Region hinter Gate)
     - MVP-Regel: Expansion Sites in `outer_rim` hinter `helios_corridor`; Kanten über Gate

3. **Edge-Typen (neu)**
   - `chokepoint_link` — Hub/Gate/Site-Verbindung durch Engpass
   - Bestehende `expansion_locked` / `expansion_unlocked` nur auf **letzter** Teilstrecke Gate→Site (oder ersetzen durch durchgehende Kette)

4. **Template + CSS**
   - `.galaxy-command-map-node--chokepoint` — Gate-Icon, nicht klickbar
   - Kanten durch Gates etwas hervorgehoben (hellere Stroke auf `chokepoint_link`)
   - Label unter Gate-Name

5. **Payload**

   ```python
   {
       "nodes": [...],  # + chokepoint nodes
       "edges": [...],  # hub → helios_corridor → frontier_ix
       "regions": [...],
       "chokepoints": [...],  # optional summary block
   }
   ```

6. **Locales** — `chokepoint_helios_corridor`, etc. DE/EN

7. **Tests** — `tests/test_chokepoints.py`

---

### Routing-Logik (MVP, serverseitig)

```text
genesis_core Kolonien ←→ (kein Gate nötig untereinander)

hub → helios_corridor → outer_rim sites (frontier_ix)
helios_corridor → ancient_threshold → ancient_sector sites
ancient_threshold → void_rift → dark_expanse sites
```

Vereinfachung MVP: **eine Kette** von Gates nach außen — nicht vollständiger Graph.

| Gate | Zwischen | Sites dahinter |
|------|----------|----------------|
| Helios Corridor | Core ↔ Outer Rim | frontier_ix |
| Ancient Threshold | Outer Rim ↔ Ancient | ancient_relay, archive_nexus |
| Void Rift | Ancient ↔ Dark | abyss_gate, void_frontier |

Hub→Site-Kanten **ersetzen** durch Hub→Gate→…→Site wenn Site hinter Gate liegt.

---

### Was explizit NICHT rein gehört

| Verboten | Ticket |
|----------|--------|
| Fleet blockieren / Scan-Regeln | GC-568 |
| Gate „besetzen" / Kampf | GC-568 |
| Influence-Fill um Kolonien | GC-566 |
| Fremde Spieler an Gates | GC-569 |
| `[G:S]`-Mapping | GC-567 |
| Kolonisierung enforcen | GC-567 |
| Migration / DB | — |

---

## Visuelles Zielbild

```text
         [ Dark Expanse Nebel ]
              🌀 Void Rift
                    |
         [ Ancient Sector Nebel ]
           ⛩ Ancient Threshold
                    |
         [ Outer Rim Nebel ]
           🚪 Helios Corridor
                    |
              🏛 Genesis Ark
           ⛏    🔬    ⚓
         [ Genesis Core Nebel ]
```

Gates sitzen **auf den Pfaden** zwischen Nebelzonen — nicht in Boxen, nicht in Listen.

---

## Technische Leitplanken

| Modul | Verantwortung |
|-------|---------------|
| **`chokepoints.py`** (neu) | `CHOKEPOINTS`, `list_chokepoints_for_map()`, Gate-Routing-Hilfen |
| **`command_map.py`** | Chokepoint-Nodes, Edge-Ketten Hub→Gate→Site |
| **`galaxy_command_map_panel.html`** | Gate-Node-Markup |
| **`style.css`** | `.galaxy-command-map-node--chokepoint`, `--chokepoint_link` edge |

**Reuse:** polar layout aus GC-564B (`_polar_to_pct`). **Kein** paralleles Map-System.

**Pan/Zoom:** Gates innerhalb Canvas — GC-563B unverändert.

---

## Betroffene Dateien (Implementierung — max. ~6 Kern)

- `game/planet_evolution/chokepoints.py` — **neu**
- `game/planet_evolution/command_map.py` — Edge-Routing über Gates
- `templates/partials/galaxy_command_map_panel.html`
- `static/style.css`
- `locales/de.json`, `locales/en.json`
- `tests/test_chokepoints.py` — **neu**

**Nicht:** `expansion_gates.py` Gate-Levels, `/empire`, `galaxy.py`, Fleet

---

## Akzeptanzkriterien

- [x] **Helios Corridor** sichtbar zwischen Genesis Core und Outer Rim
- [x] Hub → Helios Corridor → Frontier IX (Kanten-Kette, nicht Direktlinie Hub→Frontier)
- [x] Ancient Threshold + Void Rift auf der Kette nach außen
- [x] Gate-Nodes: `node_kind=chokepoint`, nicht klickbar
- [x] Keine horizontalen Boxen; Nebel + Raum-Layout (GC-564B) erhalten
- [x] Pan/Zoom + Zentrum funktionieren
- [x] Kein Fleet-/Scan-Gameplay
- [x] `/empire` + klassische Galaxy unverändert
- [x] `pytest tests/test_chokepoints.py tests/test_command_map.py -v` grün

---

## Cursor-Prompt (Implementierung)

```md
Implementiere GC-565 exakt nach docs/GC-565_CHOKEPOINTS.md.

Ziel: Gate-Knoten zwischen Regionen — strategische Pfade, kein Gameplay-Enforcement.

Priorität:
1. chokepoints.py — CHOKEPOINTS + list für Map
2. command_map.py — chokepoint nodes + Hub→Gate→Site edge chains
3. Template + CSS — Gate-Nodes, chokepoint_link edges
4. GC-564B spatial layout + Nebel unverändert
5. Keine Migration, keine Fleet-Regeln, keine fremden Spieler
6. Tests test_chokepoints.py

Akzeptanz: Helios Corridor zwischen Core und Outer Rim; Kanten durch Gates.
```

---

## EPIC-15 — Schichten (aktualisiert)

```text
GC-564B  Raum / Sternenkarte           ✅
GC-565   Chokepoints / Pfade           ✅
GC-566   Influence / Eigenreich-Fläche ⬅ nächster Schritt
GC-569   Presence / fremde Spieler (Toggle, default AUS)
GC-567   Expansion Depth + [G:S]
GC-568   Territorial Warfare / Gate-Kontrolle (Gameplay)
```

**Reihenfolge bewusst:** Erst **Pfade** (565) → dann **Territorium** (566) → dann **andere Spieler** (569).

---

## Referenz-Docs

- [GC-564B_SPATIAL_COMMAND_MAP.md](GC-564B_SPATIAL_COMMAND_MAP.md)
- [GC-566_INFLUENCE_LAYER.md](GC-566_INFLUENCE_LAYER.md) — nächste Schicht danach
- [GC-569_PRESENCE_LAYER.md](GC-569_PRESENCE_LAYER.md) — optional Overlay
- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Chokepoints langfristig + Kampf

---

## Ausgabe (nach Abschluss)

### Root Cause · Changed Files · Tests · Ergebnis
