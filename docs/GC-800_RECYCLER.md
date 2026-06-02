# GC-800 — Recycler Mission (Debris Harvest)

> Epic: Military Core — **wirtschaftlicher Abschluss** nach Combat  
> Voraussetzung: [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md), GC-601 Roadmap-Pivot  
> **Nicht:** Combat-Resolver neu bauen (→ GC-700 nur Polish)

---

## Problem

Nach Angriffen entsteht Debris (`debris_fields`), Galaxy zeigt `has_debris`, Schiff `harvest_reclaimer` ist definierbar — aber es gibt **keine Spieler-Mission**, um Debris zu sammeln. Der Kreislauf endet bei:

```text
Kampf → Verluste → Debris → (nichts)
```

---

## Ist-Zustand (Code)

| Baustein | Status | Ort |
|----------|--------|-----|
| Debris-Persistenz | ✅ | `game/combat.py` — `spawn_combat_debris_at_planet`, `debris_fields` |
| Galaxy-Anzeige | ✅ | `game/galaxy.py` — `get_debris_for_system`, Slot `debris` / `has_debris` |
| Recycler-Schiff | ✅ | `fleet_defs` — `harvest_reclaimer`, Rolle `recycle` |
| Fleet-Mission | ❌ | `MISSION_TYPES` enthält **kein** `recycle`/`harvest` (nur u. a. `collect` = Logistics-Stub) |
| Harvest-Logik | ❌ | Kein Arrival-Handler für Debris-Abbau |

---

## Ziel (Phase 1 — MVP)

Spieler kann mit `harvest_reclaimer` (ggf. gemischter Flotte) zu einem **Debris-Feld** fliegen, Ressourcen laden, und mit Fracht nach Hause zurückkehren — **ohne** neuen Combat, **ohne** parallele Fleet-State-Engine.

---

## Architektur (GC-000)

| Regel | Umsetzung |
|-------|-----------|
| Owner | `game/fleet.py` (Mission, Tick, Arrival) + `game/combat.py` oder `game/debris.py` (Debris lesen/schreiben) |
| Kein Parallel-System | Bestehende `debris_fields` + `fleet_movements` |
| Planet Scope | Ressourcen-Gutschrift auf **Origin-Planet** der Flotte |
| Queue | Keine neue Queue |
| UI | Fleet send + Galaxy Prefill; `applyActionState` / `refreshFleetState` |
| Server authority | Harvest-Menge, Cargo-Cap, verbleibendes Debris nur serverseitig |

---

## Vorschlag Scope (max. 3–5 Dateien pro Implementierungs-Ticket)

**Ticket A — Backend Mission**

- `game/fleet_defs.py` — Mission `recycle` (oder klare Semantik für `collect` vs. Logistics trennen)
- `game/fleet.py` — Preview, `send_fleet`, Arrival: Debris abbuchen, Cargo füllen, Return-Flug
- `game/fleet_calc.py` — ggf. Flight/Cargo-Regeln für Recycler-Anteil
- `tests/test_recycler.py` — neu

**Ticket B — UI/PJAX (optional gesplittet)**

- `static/main.js` — Mission `recycle`, Galaxy → Fleet Prefill bei `has_debris`
- `templates/fleet.html` — Mission-Option, Recycler-Hinweise

**Nicht in GC-800 Phase 1**

- GC-900 Logistics (`collect_resources` / `distribute_resources` zwischen Planeten)
- Combat-Balancing (GC-700)
- Expedition `debris_salvage` Event (bereits separater Event-Pfad)

---

## Anforderungen

1. Neue Mission (Arbeitsname `recycle`): Ziel = Koordinate mit `debris_fields` Eintrag; leer → klare Fehlermeldung.
2. Preview: erwartete Metal/Crystal aus Debris (cap durch Recycler-Cargo / Schiffanzahl).
3. Send: idempotent (`request_id`), `{ ok, state }` über bestehenden Fleet-Action-Pfad.
4. Arrival: atomar Debris reduzieren + Cargo in Movement; kein Doppel-Harvest bei Tick-Retry (Idempotenz wie Attack).
5. Return: Ressourcen auf Origin-Planet bei Ankunft (bestehendes Transport-Muster).
6. Galaxy: Klick auf Debris-Slot → Fleet mit Mission + Koordinaten vorbefüllt.
7. Mindestens ein Recycler (`harvest_reclaimer`) in Flotte erforderlich.

---

## Akzeptanzkriterien

- [ ] Debris nach erfolgreicher Mission am Ziel reduziert oder entfernt
- [ ] Spieler erhält Metal/Crystal auf Origin-Planet nach Return
- [ ] Kein Full Reload; Fleet/Galaxy PJAX-konform
- [ ] Kein zweites game-state-Poll-System
- [ ] `pytest tests/test_recycler.py` grün
- [ ] [FLEET_SYSTEM.md](FLEET_SYSTEM.md) + [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) Recycler → ✅

---

## Referenz-Docs

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17 Owner
- [FLEET_SYSTEM.md](FLEET_SYSTEM.md)
- [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) — Debris-Spawn
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — Debris in Systemansicht
- [PLANET_SCOPE.md](PLANET_SCOPE.md)
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)

---

## Risiken

| Risiko | Mitigation |
|--------|------------|
| `collect` vs. `recycle` Namenskollision mit GC-900 | Mission eindeutig benennen; Logistics später eigenes API |
| Tick-Retry doppelt harvestet | Movement-Status / Harvest-Flag wie Combat |
| Debris-Race zwei Flotten | Row-Lock / `UPDATE … WHERE metal >= ?` |

---

## Reihenfolge

```text
GC-800 Recycler  →  GC-900 Logistics  →  GC-700 Combat Polish
```

Siehe [ROADMAP.md](ROADMAP.md) Phase 4.

---

## Implementierungsstand

| Ticket | Status |
|--------|--------|
| **GC-800A** Backend (`recycle` mission, debris harvest, report, `test_recycler.py`) | ✅ |
| **GC-800B** UI/PJAX (Fleet mission option, Galaxy prefill) | 📋 |
