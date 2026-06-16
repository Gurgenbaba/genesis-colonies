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
