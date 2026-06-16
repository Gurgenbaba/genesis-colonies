# GC-583B — World Expedition Reports

> **Epic:** EPIC-15 · **Status:** ✅ · **Stand:** 2026-06-13  
> **Voraussetzung:** GC-583A ✅ (world_key + expedition send)

Expeditions zu Strategic Worlds liefern **Ortsbezogene Berichte** statt roher `field:…`-Koordinaten.

---

## Kernthese

```text
Vorher:  Expedition report — field:anomaly_zone:1820:2140
Nachher: Expedition report — Omega Rift

Bericht:
  Ort:     Omega Rift
  Risiko:  Instabile Raumzeit
  Ereignis: Verlassenes Forschungslabor
  Ausbeute: +125.000 Ferronit
  Verluste: Keine
```

Kein neues Loot-System. `resolve_expedition_outcome()` bleibt kanonisch — nur Report-Präsentation + strukturierte Metadata.

---

## Scope (583B)

| In | Out |
|----|-----|
| `build_expedition_report(..., world_context=…)` | Neue Loot-Tabellen |
| Metadata: `world_key`, `world_name_key`, `world_risk_key`, `losses` | Map „Expedition aktiv“ UI (→ 583C) |
| Subject + Body mit Weltname | Orte verändern sich (→ 583D) |
| Messages-UI zeigt Weltname statt field-Key | wreckage_field spielbar |

---

## Metadata (Inspector / Messages)

```json
{
  "report_kind": "world_expedition",
  "world_key": "field:anomaly_zone:1820:2140",
  "world_name_key": "strategic_world_name_omega_rift",
  "world_type_key": "strategic_world_type_anomaly_zone",
  "world_risk_key": "strategic_world_risk_reality_tears",
  "world_risk_level": "high",
  "event_key": "ancient_stash",
  "rewards": { "metal": 125000 },
  "losses": {},
  "losses_total": 0
}
```

---

## Owner

| Domäne | Modul |
|--------|--------|
| World presentation from key | `game/planet_evolution/strategic_worlds.py` |
| Report body + metadata | `game/expedition_events.py` |
| Arrival hook | `game/fleet.py` |
| Inbox render | `static/js/messages.js` |

---

## Ticket-Reihenfolge (583-Serie)

| Ticket | Scope |
|--------|--------|
| **GC-583A** ✅ | Fleet send + world_key expedition targets |
| **GC-583B** | World expedition reports (dieses Ticket) |
| **GC-583C** | Command Map: Expedition aktiv + Report im Inspector |
| **GC-583D** | Orte entwickeln sich (Expedition-Counter, neue Missionen) |
