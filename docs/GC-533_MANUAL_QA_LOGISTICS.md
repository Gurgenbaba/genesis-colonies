# GC-533 – Manual QA Fleet Logistics Browser Regression

**Epic:** EPIC-02 Fleet System  
**Status:** Offen (manuell)  
**Voraussetzung:** GC-532 abgeschlossen (automatisierte Tick/Report/Exploit-Regression grün)

Automatische Tests decken Tick, Reports, Multi-Collect, Distanz und Return-Verhalten ab. Dieses Ticket ist **nur** manuelle Browser-QA.

---

## Problem

Offen ist die manuelle Browser-QA für Collect/Distribute mit Reload, Planetwechsel und Galaxy-Shortcuts — nicht durch pytest ersetzbar.

---

## Betroffene Dateien

- `docs/ALPHA_TESTPLAN.md` (§ 12 — Checkliste + Ergebnis-Tabelle)
- ggf. `docs/FLEET_SYSTEM.md` (Verweis)

**Nicht implementieren:** Kein neuer Backend-Code, kein UI-Redesign — nur QA + Dokumentation der Findings.

---

## Anforderungen

### 1. Collect im Browser

| Schritt | Detail |
|---------|--------|
| Hub wählen | Aktiver Planet / Hub-Select |
| Quellen | **2–3** eigene Kolonien (≠ Hub) |
| Cargo | `mule_courier` (oder Cargo-Rolle); Preview `can_launch` |
| Start | `POST /api/fleet/logistics/collect` → `{ ok, state }` |
| Reload | **F5** oder PJAX weg/zurück **während** Hinflug |
| Rückkehr | Hub-Fracht, Schiffe, Posteingang prüfen |

### 2. Distribute im Browser

| Schritt | Detail |
|---------|--------|
| Ziele | 2–3 Kolonien (≠ Hub) |
| Modi | **equal** und **custom** (`target_resources`); Collect bleibt **all** (kein equal/custom) |
| Planetwechsel | Header-Switch **während** aktiver Mission |
| Reload | während Hin- **und** Rückflug |

### 3. Galaxy-Shortcuts

| Schritt | Erwartung |
|---------|-----------|
| `/galaxy` → Fleet-Aktion (own / foreign / empty / expedition) | `/fleet?target_galaxy=…&mission=…` Prefill |
| Mission/Target | Preview grün oder klare Block-Meldung |
| PJAX/Reload | Koordinaten + Mission stabil |

### 4. Findings dokumentieren

In `docs/ALPHA_TESTPLAN.md` § 12.6:

- bestanden / fehlgeschlagen pro Block (C/D/P/G/R)
- Screenshot-Hinweise (optional)
- Console- / Network-Fehler

---

## Akzeptanzkriterien

- [ ] Collect funktioniert nach Reload stabil.
- [ ] Distribute funktioniert nach Reload stabil.
- [ ] Planetwechsel verändert keine laufenden Missionen falsch (Hub-Credit bleibt am ursprünglichen Hub).
- [ ] Galaxy-Shortcuts setzen korrektes Ziel.
- [ ] Keine doppelten Reports (`report_phase` pro `fleet_id`).
- [ ] Keine doppelten Ship-/Fuel-Abzüge.
- [ ] Ergebnis in `docs/ALPHA_TESTPLAN.md` § 12.6 ausgefüllt.

---

## Tests (vor manueller QA)

```bash
python -m pytest tests/test_fleet.py tests/test_galaxy.py -v
```

Fokus Logistics + GC-532:

```bash
python -m pytest tests/test_fleet.py -k "logistics or collect_creates_report or distribute or api_fleet_state_five" -v
```

---

## Ausgabe nach Abschluss

### Root Cause

_(nur bei Fehlern — Bug-Ticket ableiten)_

### Changed Files

_(typisch nur `docs/ALPHA_TESTPLAN.md`)_

### Tests

_(pytest grün + manuelle Matrix ausgefüllt)_

### Ergebnis

_(Datum, Browser, Pass/Fail, offene Bugs)_

---

## Ticket-Nummern (Kanonisch)

| Ticket | Inhalt |
|--------|--------|
| **GC-532** | Fleet Mission Audit & Exploit Hunt (pytest) — **erledigt** |
| **GC-533** | Manuelle Logistics Browser-QA (dieses Dokument) |
| **GC-534** | Planet Limit im Header + kompakte Logistics-UI (Implementierung, siehe [PLANET_SCOPE.md](PLANET_SCOPE.md), [FLEET_SYSTEM.md](FLEET_SYSTEM.md)) |
