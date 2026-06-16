# GC-566B — Dynamic Influence (Einfluss wächst mit Imperium)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **H** — Evolution von GC-566, **vor** GC-569  
> **Status:** 📋 Spec bereit — **noch nicht implementieren**  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-566 ✅ · GC-565 ✅ · GC-567 ✅ · GC-567B 📋 (empfohlen)

Design: [GC-566_INFLUENCE_LAYER.md](GC-566_INFLUENCE_LAYER.md)

---

## Leitplanke

> **566B = Einfluss reagiert auf Imperiumsstand** — sichtbar wachsend/dehnend.  
> **Nur Darstellung** — keine Produktions-/Kampf-Modifikatoren (→ GC-568).  
> **Keine fremden Spieler** (→ GC-569). **Keine Migration.**

---

## Warum — nach Landmarks, vor Presence

GC-566 liefert einen **statischen Blob** um Ark + Kolonien.

Das Mockup suggeriert **Territorium das wächst**:

```text
Kolonie gegründet     → Blob wächst
Site erschlossen      → Blob dehnt sich Richtung Region
Chokepoint auf Pfad   → Einfluss verbindet Regionen (visuell)
```

Das ist noch **Mein Imperium** — nicht Universum.

---

## Product-Ziel

| Trigger (visuell) | Effekt auf Influence |
|-------------------|----------------------|
| + Kolonie | Größerer Radius / stärkerer Beitrag zum Hull |
| Expansion Site **unlocked** | Zusätzlicher Blob-Fleck Richtung Site-Position |
| Chokepoint auf Pfad | Schmalere „Brücke" entlang Gate-Position (optional MVP: nur unlocked sites) |
| Locked Site | **Kein** Einfluss dort |

Kein Frontend-Timing — Server berechnet Form aus `nodes`-State.

---

## Scope (MVP)

### 1. Owner bleibt `influence_layer.py` — `build_influence_payload()` erweitern

**Input erweitern:**

- Colony nodes (`is_own`, `layout_x_pct`, `layout_y_pct`, `is_homeworld`)
- Unlocked expansion sites (`is_unlocked`, position) — **keine** locked
- Optional: chokepoint positions als **Verbindungspunkte** (niedrigere Opacity-Strips, nicht voller Blob)

**Output erweitern:**

```python
{
    "visible": True,
    "svg_path": "M ... Z",           # Kern-Blob (Kolonien + Hub)
    "expansion_paths": ["M ... Z"],  # optional: Flecken zu unlocked sites
    "bridge_paths": ["M ... Z"],     # optional: entlang Gates
    "sources": {
        "colony_keys": [...],
        "unlocked_site_keys": [...],
    },
}
```

**Algorithmus (MVP):**

1. Kolonie-Hull wie GC-566 (convex hull + smooth path)
2. Pro **unlocked** Site: Ellipse/Blob um Site-Position mit moderatem Radius, **merged** in SVG als zweiter `<path>` oder union-approximation
3. Optional: dünne Pfad-Strips Hub → Gate → unlocked Site (low opacity) — „Einfluss folgt dem Korridor"

Locked sites: ausgeschlossen.

### 2. Template

- Zusätzliche `<path class="galaxy-command-map-influence-expansion">` Layer
- Optional `<path class="galaxy-command-map-influence-bridge">`

Reihenfolge: Nebel → Influence core → influence expansion → Edges → Nodes

### 3. CSS

- Core: bestehend `rgba(70, 229, 255, 0.12)`
- Expansion flecks: `rgba(70, 229, 255, 0.08)`
- Bridges: `rgba(127, 255, 217, 0.06)` stroke oder fill

### 4. Tests — `tests/test_dynamic_influence.py`

- Homeworld only → nur core path (wie GC-566)
- Unlocked frontier_ix → expansion path enthält site key in sources
- Locked sites → nicht in sources
- Chokepoints → nicht in colony sources

---

## Explizit nicht

| Verboten | Ticket |
|----------|--------|
| Animations-Timeline / CSS keyframes | optional polish später |
| Gameplay-Boni | GC-568 |
| Landmarks in Influence | GC-567B |
| Fremde Reichs-Farben | GC-569 |

---

## Akzeptanzkriterien

- [ ] Mehr Kolonien → sichtbar größerer Einfluss (vs. 1 Kolonie)
- [ ] Unlocked Site → Einflussfleck Richtung Site (nicht bei locked)
- [ ] Bestehende Pan/Zoom, Gates, Landmarks, Inspector OK
- [ ] Kein Gameplay, keine Migration
- [ ] `pytest tests/test_dynamic_influence.py tests/test_influence_layer.py -v` grün

---

## Cursor-Prompt (Implementierung)

```md
Implementiere GC-566B exakt nach docs/GC-566B_DYNAMIC_INFLUENCE.md.

Ziel: Influence reagiert auf Kolonien + unlocked Sites — Darstellung only.

Priorität:
1. influence_layer.py — expansion/bridge paths aus nodes
2. command_map.py — keine Logik duplizieren, nodes an build_influence_payload
3. Template + CSS — zusätzliche SVG paths
4. Tests test_dynamic_influence.py
```

---

## EPIC-15 — Reihenfolge

```text
GC-567B  Region Landmarks
GC-570   World Map + Role Actions     ⬅ nächster Schritt
GC-566B  Dynamic Influence
GC-571   Shared World Presence
GC-568   Territorial Warfare
```

---

## Langfristig (nicht 566B)

- Site-Inspector: „Produziert / Verbindet" (GC-567C)
- Chokepoint-Kontrolle ändert Bridge-Stärke (GC-568)

---

## Ausgabe (nach Abschluss)

### Root Cause · Changed Files · Tests · Ergebnis
