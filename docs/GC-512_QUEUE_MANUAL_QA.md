# GC-512 — Queue Regression Manual QA

Teil des [Architecture Validation Pass](GC-512_ARCHITECTURE_VALIDATION.md).  
Manuelle Browser-Checkliste nach **GC-510** (Build/Research Reschedule).  
Automatische Verträge: `tests/test_queue_static_contract.py`

**Voraussetzung:** `python app.py` → [http://127.0.0.1:5000](http://127.0.0.1:5000), DevTools offen (Console + Network).

**Account:** Kolonie mit genug Ressourcen; für Multi-Kolonie-Tests mindestens **2 Planeten**.

---

## Vor dem Test

| Check | Erwartung |
|-------|-----------|
| `python -m pytest tests/test_queue_static_contract.py tests/test_core_architecture_enforcement.py -v` | grün |
| Network-Filter `game-state` | Nur **ein** Poll-Typ über Zeit (kein zweites paralleles Spiel-State-Polling) |

---

## A — Build-Queue (`/buildings`)

Queue mit **3 Slots** füllen (z. B. drei verschiedene Gebäude). Countdown sichtbar.

| ID | Schritt | Erwartung |
|----|---------|-----------|
| A1 | **Cancel active** (erster Job) | Kein Full Reload; Queue springt sofort; Folgejob startet **jetzt** (Countdown plausibel, nicht +alter Offset) |
| A2 | Queue neu füllen → **Cancel middle** | Aktiver Job läuft weiter; Job danach startet direkt nach Ende des Aktiven |
| A3 | **Cancel last** | Keine Geister-Jobs; Queue-Anzahl −1 |
| A4 | **Near-finish enqueue** | Aktiver Bau &lt; ~10 s Rest → weiteres Upgrade anreihen | Kein negativer Timer; kein Sprung auf alte Finish-Basis; neuer Job verkettet korrekt |
| A5 | Nach Cancel/Enqueue | Network: `POST …/cancel` oder `upgrade` → Response enthält `state`; UI **ohne** Warten auf nächsten Poll aktualisiert |
| A6 | Countdown / Balken | Keine negativen Sekunden; kein 97→100→92→98-Flackern |

---

## B — Research-Queue (`/research`)

`research_lab` ≥ 3; Queue-Limit beachten (Lab 4 = 3 Slots).

| ID | Schritt | Erwartung |
|----|---------|-----------|
| B1 | **Cancel active** | Nächste Forschung startet sofort (Active-Block + Timer) |
| B2 | **Cancel middle** | Erste läuft weiter; dritte startet nach Finish der ersten |
| B3 | **Cancel last** | Queue leer oder nur verbleibende Jobs |
| B4 | **Near-finish enqueue** | Kurz vor Ende zweite Tech starten | Timer verkettet; kein negativer Countdown |
| B5 | `POST /api/research/cancel` | `state.research.queue` mit frischen `start_at` / `finish_at` |

---

## C — Planetwechsel (Queue läuft)

| ID | Schritt | Erwartung |
|----|---------|-----------|
| C1 | Auf Planet A Bau-Queue starten | Queue sichtbar auf Buildings |
| C2 | Header → Planet B wechseln | PJAX/Reload **nur** `#main-content`; Shell bleibt |
| C3 | Buildings auf B | Queue von B (leer oder andere Jobs), **nicht** Queue von A |
| C4 | Zurück zu A | Queue von A noch konsistent (Jobs liefen im Hintergrund weiter) |
| C5 | Network | `POST /api/planets/active` → `state`; kein `window.location.reload()` |

---

## D — PJAX während Queue

| ID | Schritt | Erwartung |
|----|---------|-----------|
| D1 | Aktiver Bau/Research | Countdown läuft |
| D2 | Nav: Overview → Buildings → Research → Buildings | Kein Full Reload; `#main-content` wechselt |
| D3 | Countdown | Läuft weiter oder setzt sich aus `state` korrekt fort |
| D4 | Console | Keine wachsenden Interval-Leaks (optional: Performance → Timer) |
| D5 | `GC.cleanupPage` | Nach Wechsel keine doppelten Polls (Network: max. ein `game-state`-Rhythmus) |

---

## E — State & Architektur (GC-000)

| ID | Schritt | Erwartung |
|----|---------|-----------|
| E1 | Beliebige Queue-Aktion | UI aktualisiert aus Response-`state`, nicht aus Client-Rechnung |
| E2 | Poll nach Aktion | Nächster `GET /api/game-state` zeigt **dieselbe** Queue wie Mutation |
| E3 | Reload-Verbot | Kein Full Reload außer Login/Logout (Network: kein Document-Reload bei Nav) |
| E4 | Negativ-Timer | Nirgends „-1s“ / „-42s“ in Queue-UI |

---

## Abnahme

| Kriterium | OK |
|-----------|-----|
| A1–A6 Build | ☐ |
| B1–B5 Research | ☐ |
| C1–C5 Planetwechsel | ☐ |
| D1–D5 PJAX | ☐ |
| E1–E4 GC-000 | ☐ |

**Ergebnis:** Datum · Browser · Viewport · Tester · Auffälligkeiten (Console-Screenshot).

Wenn alle Kästchen grün: **Queue-Fundament deploy-ready** (zusammen mit grünen pytest Guards).
