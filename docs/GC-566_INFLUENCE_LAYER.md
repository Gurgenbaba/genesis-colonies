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
---

## Player Article

```yaml
---
codex_id: influence
band: II
difficulty: beginner
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - galaxy_view
  - empire_view
related_codex:
  - command_map
  - galaxy
  - expansion
  - genesis_ark
terminology: GENESIS_TERMINOLOGY
unlock:
  type: homeworld_level
  value: 10
teaser_key: codex_unlock_influence_teaser
---
```

## Quick Help

**Einfluss** ist das sichtbare teal Territorium um deine Genesis Ark und Kolonien auf der Command Map — Fußabdruck deines Imperiums, kein Kampf-Buff.

## Summary

Einfluss malt dein eigenes Reich auf der Weltkarte: eine weiche teal Fläche um den Ark-Hub und verbundene Kolonien. Gesperrte Expansion Sites bleiben außen. Abgeleitet aus Kolonie-Positionen — keine separate DB-Ökonomie und im MVP keine Feind-Gebiete.

## Why

Du sollst auf einen Blick sehen „das gehört mir“. Einfluss macht Hub-and-Spoke-Besitz lesbar, bevor fremde Commander-Präsenz dazukommt.

## How it works

- Öffne die **Command Map** (`/galaxy` Weltkarte-Tab).
- Teal-Einfluss umgibt die Genesis Ark und deine Kolonien.
- Expansion Sites erhalten keinen Einfluss, solange sie locked / unbeansprucht sind.
- Pan/Zoom hält den Layer unter Nebel und über dem Hintergrund.
- Keine Produktions- oder Kampf-Modifikatoren in dieser Schicht — zuerst Darstellung.
- Codex-Freischaltung ab Ark-Entwicklungsstufe **10**.

## Related Systems

- command_map
- galaxy
- expansion
- genesis_ark

## Commander Tips

- Einfluss als Fußabdruck lesen, während du Expansion planst.
- Lücken zwischen Kolonien sind normal, bis du mehr Welten gründest.
- Erwarte keine PvP-Buffs vom teal Glow — das ist Territoriums-Visualisierung.

## FAQ

**Gibt Einfluss Boni?**
Nicht in der Basis-Einflussschicht — sie visualisiert dein Imperiums-Territorium.

**Sehe ich Einfluss anderer Spieler?**
MVP fokussiert dein eigenes Reich; fremde Präsenz ist eine spätere Schicht.

## Discord Summary

**Einfluss — Imperiums-Glow auf der Karte**

Command Map: teal Fußabdruck um Ark + Kolonien. Display-Layer, keine Kampf-Math. Codex ab Ark-Stufe 10.
