# GC-583 — Expedition Worlds (World Map)

> **Epic:** EPIC-15 · **Status:** ✅ 583A–583C · **Stand:** 2026-06-13  
> **Voraussetzung:** GC-582 Dynamic Colonization ✅ (world_key, Fleet, Claims)

Strategic Worlds die man **nicht kolonisiert**, sondern **expeditioniert** — gleiche Welt-Identität (`world_key`), andere Fleet-Mission.

---

## Kernthese

```text
Nicht:  Kolonie gründen (GC-582 colonize + Seed Ark)
Sondern: Weltkarte → Strategic World → Expedition → Fleet → Bericht (bestehende Expedition-Pipeline)
```

Kein paralleles Expedition-System. `resolve_expedition_outcome()` bleibt kanonisch — kein neues Loot-System in 583A.

---

## Typen

| `world_type` | GC-582 | GC-583 |
|--------------|--------|--------|
| `mining_world` … `trade_world` | Kolonisierbar | — |
| `expedition_zone` | Inspector only | **Expedition** |
| `anomaly_zone` | Inspector only | **Expedition** |
| `ruins_world` | → Expedition (583A) | **Expedition** |
| `wreckage_field` | — | **Prepared** (583A blockiert, 583B+) |

---

## Flow (583A)

```text
Strategic World (expedition type, unclaimed optional)
    ↓ Inspector „Expedition starten“ → /fleet?mission=expedition&world_key=…
    ↓ POST /api/fleet/send  mission=expedition  world_key=…
    ↓ Ankunft: bestehend handler in fleet.py
    ↓ resolve_expedition_outcome(movement_id) — unverändert
    ↓ World expedition report (GC-583B: Ort, Risiko, Ausbeute, Metadata)
```

---

## Ticket-Split

| Ticket | Scope |
|--------|--------|
| **GC-583A** ✅ | `world_key` + `mission=expedition` für expedition_zone, anomaly_zone, ruins_world; wreckage_field prepared |
| **GC-583B** ✅ | World expedition reports — Ort/Risiko/Ausbeute/Metadata |
| **GC-583C** ✅ | Command Map expedition activity (active/returning/report badge + inspector) |
| **GC-583D** | Orte entwickeln sich (Expedition-Counter, neue Missionen) |

---

## API (583A)

- `GET /api/worlds/expedition-preview?world_key=…` — Validierung + Presentation
- `POST /api/fleet/send` — bestehend, + `world_key` bei `mission_type=expedition`
- `POST /api/fleet/preview` — bestehend, + `world_key`

---

## Owner

| Domäne | Modul |
|--------|--------|
| World target validation | `game/planet_evolution/world_colonization.py` |
| Fleet send/arrival | `game/fleet.py` |
| Expedition outcomes | `game/expedition_events.py` (unverändert 583A) |
| Preview route | `app.py` |

---

## Explizit nicht in 583A

- Neues Loot / neue Event-Tabelle
- `wreckage_field` spielbar
- `/empire`, `/galaxy?view=system`
- Test-Fixture-Optimierung

---

## Player Article

```yaml
---
codex_id: expeditions
band: III
difficulty: intermediate
estimated_read: 5 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - fleet_view
  - galaxy_view
  - empire_view
related_codex:
  - fleet
  - galaxy
  - strategic_worlds
  - combat
  - command_map
terminology: GENESIS_TERMINOLOGY
unlock:
  type: homeworld_level
  value: 10
teaser_key: codex_unlock_expeditions_teaser
---
```

## Quick Help

**Expeditionen** sind Erkundungsmissionen: klassischer Expeditions-Slot in der Galaxie oder Strategic Worlds (Expeditionszonen, Anomalien, Ruinen) — Flotte senden, Event bei Ankunft, Bericht in den Nachrichten.

## Summary

Expeditionen nutzen die **kanonische Fleet-Mission Expedition** und die Event-Engine. Ziele: **Position 16** (synthetischer Expeditions-Slot) in der Systemansicht und **Expedition Worlds** auf der Weltkarte (`expedition_zone`, `anomaly_zone`, `ruins_world`). Kein paralleles Loot-System — Ergebnis und Bericht kommen aus dem bestehenden Expeditions-Pipeline.

## Why

Nicht jede Welt soll sofort Kolonie werden. Expeditionen belohnen Erkundung mit Funden, Risiken und Berichten — und erschließen Orte, die man **expeditioniert**, statt zu kolonisieren.

## How it works

- **Klassisch:** Galaxie-Systemansicht → Expeditions-Slot (Position 16) → Fleet mit Mission Expedition.
- **Weltkarte:** Strategic World vom Expeditionstyp → Inspector „Expedition starten“ → Prefill auf Fleet mit `world_key`.
- Bei Ankunft würfelt der Server Events (Funde, Hazards, Piraten, seltene Begegnungen) — UI zeigt nur Serverdaten.
- **Expo-Hüllen** tragen die Loot-Rolle; **Frachter** erhöhen Bergungskapazität; Kampf-/Eskort-Rollen schützen bei Piraten, zählen nicht als Expo-Wert.
- Berichte landen im **Posteingang** (Event-Karte); Piratenkämpfe können zusätzlich einen Kampfbericht öffnen.
- Mass-Expedition und Tagesrhythmus: Server begrenzt Effizienz bei sehr vielen Expeditionen am selben UTC-Tag — Details nur in der UI/Preview, nicht im Codex rechnen.
- Ancient Relay und höhere Expansion Sites öffnen mit Ark-Stufe weitere Expeditions-/Welt-Optionen — Codex-Freischaltung ab Entwicklungsstufe **10**.

## Related Systems

- fleet
- galaxy
- strategic_worlds
- command_map
- combat
- logistics

## Commander Tips

- Expo-Schiffe für Funde mitnehmen; Frachter für Bergung; Eskorten gegen Piraten.
- World-Expeditionen über Inspector starten — Ziel bleibt an den Ort gebunden.
- Berichte immer im Posteingang lesen; Preview nur vom Server vertrauen.

## FAQ

**Expedition vs. Kolonisierung?**
Kolonisierung gründet mit Seed Ark eine Welt. Expedition erkundet und bringt Bericht/Loot — keine neue Kolonie.

**Wo starte ich?**
Fleet-Mission Expedition: klassischer Slot Pos. 16 oder Expedition World auf der Weltkarte.

**Warum wenig Loot?**
Cargo-Cap der Expo-/Fracht-Hüllen und serverseitige Event-/Tageslogik — keine Client-Formel.

## Discord Summary

**Expeditionen — Erkundung statt Kolonie**

Mission Expedition: Galaxie-Slot 16 oder Expedition Worlds (Zonen, Anomalien, Ruinen). Event-Engine, Inbox-Bericht. Expo-Hüllen + Frachter. Codex ab Ark-Stufe 10.
