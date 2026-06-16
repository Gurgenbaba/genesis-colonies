# GC-566 — Influence Layer (Eigenreich-Territorium)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **M** — nach GC-565 Chokepoints  
> **Status:** ✅ Implementiert  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-565 📋 · GC-564B ✅

---

## Leitplanke

> **Einfluss = sichtbares Territorium um eigenes Imperium** — blaue/teal Fläche um Ark + Kolonien.  
> **Darstellung zuerst** — keine Produktions-/Kampf-Modifikatoren (→ GC-568).  
> **Keine fremden Spieler** — das ist GC-569.

---

## Product-Ziel

Referenzbild: **Eigenes Reich leuchtet** — man sieht sofort „das gehört mir".

| Element | Darstellung |
|---------|-------------|
| Genesis Core | Teal-Nebel (existiert) + **Influence-Blob** um Hub |
| Kolonien | Influence-Flecken / Verbindung zum Hub-Blob |
| Expansion Sites | Kein Influence bis unlocked (optional dim outer glow) |
| Chokepoints | Auf Influence-Grenze / Pfad (GC-565) |

---

## Scope (MVP)

1. **Server:** `build_influence_zones()` aus Kolonie-Positionen + Hub — SVG path oder zusätzliche Ellipsen
2. **Template:** SVG `<path>` oder `<ellipse>` Layer **unter** Nebel, **über** Hintergrund — `.galaxy-command-map-influence`
3. **CSS:** `rgba(70, 229, 255, 0.12)` — „blaue Eigenreich-Fläche"
4. **Keine DB** — abgeleitet aus `nodes` (colonies only)

**Nicht:** Feind-Gebiete, Allianz-Farben, Gameplay-Boni.

---

## Akzeptanz (Entwurf)

- [x] Sichtbare teal/blaue Fläche um Genesis Ark + Kolonien
- [x] Kein Influence um locked Expansion Sites
- [x] GC-565 Gates + GC-564B Nebel bleiben sichtbar
- [x] Pan/Zoom OK

---

## Reihenfolge

```text
GC-566   Influence (statischer Blob)     ✅
GC-567B  Region Landmarks
GC-566B  Dynamic Influence               ← Evolution von GC-566
GC-569   Presence
```

**Erst eigene Welt vollständig und lebendig, dann Fremd-Overlay.**

---

## Ausgabe (nach Abschluss)

### Root Cause · Changed Files · Tests · Ergebnis
