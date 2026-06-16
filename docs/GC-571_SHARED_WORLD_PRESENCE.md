# GC-571 — Shared World Presence (alle Spieler, eine Karte)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **H** — nach GC-570 World Map Direction  
> **Status:** ✅ Implementiert  
> **Stand:** 2026-06-13  
> **Voraussetzung:** GC-570 ✅

Ersetzt/erweitert Vision von [GC-569_PRESENCE_LAYER.md](GC-569_PRESENCE_LAYER.md).

---

## Strategische Einordnung

Die Weltkarte zeigt **alle besiedelten Reiche** auf derselben Karte:

```text
Spieler A          Spieler B
   🏛                  🏛
  / | \               / | \
 ⛏ 🔬 ⚓             ⛏ 🛡 🔬
```

- Eigenes Reich: vollständig (Kolonien, Sites, Landmarks, Aktionen)
- Fremde Reiche: Genesis Ark + reduzierte Kolonie-Satelliten (visuell)
- Kein Toggle — Präsenz ist Standard auf `/galaxy?view=command_map`

---

## Owner

| Modul | Verantwortung |
|-------|---------------|
| **`world_map.py`** | Weltkoordinaten, Fremd-Cluster, Shared-Layout |
| **`command_map.py`** | Eigenes Reich + Aufruf `apply_shared_world_layout` |
| **`galaxy_command_map_panel.html`** | own / foreign Node-Templates, Inspector |
| **`static/main.js`** | Foreign-Empire-Inspector |

---

## Weltkoordinaten (Phase 1)

Keine DB-Migration. Deterministisch aus `[G:S]` + `player_id`:

```python
compute_empire_world_center(galaxy, system, player_id) -> (world_x, world_y)
```

Lokales Cluster-Layout (GC-564B) bleibt; Offset auf Welt-Slot → Normalisierung auf Canvas-%.

Payload-Feld `world`: `mode`, `empire_count`, `viewer_center`, `bounds`, `hub_layout_*`.

---

## Explizit nicht

- Dynamic Influence (GC-566B)
- Kampf / Territorial Warfare (GC-568)
- Special Fields (GC-572)
- `/empire` anfassen
- Legacy `/galaxy?view=system` entfernen

---

## Akzeptanzkriterien

- [x] Zwei Spieler mit Homeworlds erscheinen auf derselben Map
- [x] Eigener Spieler sieht Ark + Kolonien vollständig
- [x] Fremde Spieler als eigene Ark-Cluster (Inspector bei Klick)
- [x] Pan/Zoom bleibt erhalten
- [x] Legacy-Systemansicht funktioniert weiter
- [x] `pytest tests/test_world_map.py -v` grün

---

## Ausgabe (nach Abschluss)

### Root Cause · Changed Files · Tests · Ergebnis
