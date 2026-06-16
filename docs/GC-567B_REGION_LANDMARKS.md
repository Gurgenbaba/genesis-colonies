# GC-567B — Region Landmarks (visuelle Weltpunkte)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **H** — Imperiumskarte lebendig machen, **vor** Presence  
> **Status:** ✅ Implementiert  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-564B ✅ · GC-565 ✅ · GC-567 ✅

Design: [GC-564B_SPATIAL_COMMAND_MAP.md](GC-564B_SPATIAL_COMMAND_MAP.md) · [IMPERIUM_VISION.md](IMPERIUM_VISION.md)

---

## Leitplanke

> **Landmarks = Dekoration + Lesbarkeit** — interessante Punkte pro Region.  
> **Kein Gameplay.** Keine Migration. Keine fremden Spieler (→ GC-569).  
> **Kein Fleet/Scan.** `/empire` + klassische `/galaxy` unverändert.

---

## Warum jetzt — nach GC-567, vor GC-569

GC-560–567 liefert **Mein Imperium** (Identity, Wege, Einfluss, Expansionsziele).

Das Referenzmockup lebt von **Gebieten mit interessanten Punkten** — nicht von anderen Spielern.

Regionen wirken noch leer neben Nebel + wenigen Sites. Landmarks füllen die Karte mit **Atmosphäre und Orientierung**, ohne das Universum zu öffnen.

```text
Referenz:  überall kleine interessante Punkte
Heute:    4 Nebel + 3 Gates + 5 Sites + Kolonien
567B:     +12–18 statische Landmarks in Outer/Ancient/Dark
```

---

## Product-Ziel

| Vor GC-567B | Nach GC-567B |
|-------------|--------------|
| Region = Nebel + 1–2 Sites | Region = Nebel + **Landmark-Feld** |
| Leere Flächen zwischen Pfaden | Ruinen, Relais, Trümmer, Signale |
| „Karte meines Reiches" | „Karte einer **Welt** die mir gehört" |

Landmarks sind **klickbar** mit Inspector-Flavor — **nicht erschließbar**, kein Gameplay.

---

## Scope (MVP)

### 1. Neuer Owner: `game/planet_evolution/region_landmarks.py`

Statische `REGION_LANDMARKS` — pro Eintrag:

```python
{
    "landmark_key": "broken_relay",
    "label_key": "landmark_broken_relay",
    "flavor_key": "landmark_broken_relay_flavor",
    "region_key": "outer_rim",
    "layout_bearing_deg": 12,
    "layout_radius_pct": 34,
    "role_icon": "📡",
    "tone": "rim",  # CSS: dim, small
}
```

**Vorschlag pro Region (MVP ~4–6 each):**

| Region | Beispiele |
|--------|-----------|
| **outer_rim** | Broken Relay, Mining Debris, Abandoned Colony, Drift Beacon |
| **ancient_sector** | Ancient Beacon, Data Vault, Crumbled Spire, Echo Array |
| **dark_expanse** | Void Signal, Abyss Rift, Dead Station, Gravity Scar |

Genesis Core: **keine** Landmarks (Kolonien + Hub reichen).

### 2. Command Map Integration

- `node_kind=landmark` — nicht in Influence, keine Edges, nicht klickbar
- `list_landmarks_for_map()` → Layout polar wie Sites (kleinerer Radius-Spread)
- Payload: `landmarks: [...]` optional summary
- Nodes nach Layout: colonies → chokepoints → **landmarks** → expansion sites (Landmarks unter Sites im z-index)

### 3. Template + CSS

- `.galaxy-command-map-node--landmark` — klein, gedimmt, kein Border wie Kolonie
- Kein Inspector (MVP) — `title` / `aria-label` mit Flavor
- Landmarks **über** Nebel, **unter** Influence oder **über** Influence aber **unter** Edges — visuell dezent

### 4. Locales DE/EN — `landmark_*` + `landmark_*_flavor`

### 5. Tests — `tests/test_region_landmarks.py`

---

## Explizit nicht

| Verboten | Ticket |
|----------|--------|
| Gameplay-Boni / Ressourcen | später |
| Klick → Aktion / Kolonisierung | GC-567C / GC-568 |
| Fremde Spieler | GC-569 |
| DB / Migration | — |
| Landmarks in Genesis Core | — |

---

## Technische Leitplanken

| Modul | Verantwortung |
|-------|---------------|
| **`region_landmarks.py`** (neu) | `REGION_LANDMARKS`, `list_landmarks_for_map()` |
| **`command_map.py`** | Landmark-Nodes ins Layout |
| **`galaxy_command_map_panel.html`** | Landmark-Markup |
| **`style.css`** | `.galaxy-command-map-node--landmark` |

**Reuse:** `_polar_to_pct` aus GC-564B. **Kein** paralleles Map-System.

---

## Akzeptanzkriterien

- [x] Outer Rim, Ancient Sector, Dark Expanse haben sichtbare Landmark-Punkte
- [x] Landmarks sind klein/gedimmt — dominieren nicht Ark/Sites/Gates
- [x] Kein Einfluss auf Influence-Blob (GC-566)
- [x] Pan/Zoom + bestehende Schichten unverändert
- [x] Kein Gameplay, keine Migration
- [x] `pytest tests/test_region_landmarks.py -v` grün

---

## Cursor-Prompt (Implementierung)

```md
Implementiere GC-567B exakt nach docs/GC-567B_REGION_LANDMARKS.md.

Ziel: Statische Landmark-Knoten pro Region — Karte wirkt bewohnt, kein Gameplay.

Priorität:
1. region_landmarks.py — REGION_LANDMARKS + list für Map
2. command_map.py — landmark nodes (node_kind=landmark)
3. Template + CSS — kleine gedimmte Marker, title/flavor only
4. GC-564B/565/566/567 unverändert in Verhalten
5. Tests test_region_landmarks.py
```

---

## EPIC-15 — Reihenfolge (aktualisiert)

```text
GC-567   Expansion Sites v2              ✅
GC-567B  Region Landmarks               ✅
GC-570   World Map + Role Actions       ⬅ nächster Schritt
GC-566B  Dynamic Influence
GC-571   Shared World Presence
GC-568   Territorial Warfare
```

**Erst Welt spielbar machen (570) → Einfluss lebendiger (566B) → dann Fremde (571).**

---

## Ausgabe (nach Abschluss)

### Root Cause · Changed Files · Tests · Ergebnis
