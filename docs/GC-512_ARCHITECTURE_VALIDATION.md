# GC-512 — Architecture Validation Pass (GC-000)

Einmal das **gesamte Spiel** gegen [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) prüfen — **bevor** Defense, Combat, Recycler.

**Baseline:** Architecture Constitution v1.0 (GC-000, GC-510, GC-512, GC-513)

---

## Durchführung

| Feld | Wert |
|------|------|
| Datum | 2026-06-02 |
| Tester | Agent (GC-512) |
| Methode | Static code audit + pytest guards + `python app.py` smoke (http://127.0.0.1:5000) |
| Git | committed with GC-600 / GC-601 |
| pytest | `test_queue_static_contract` + `test_core_architecture_enforcement` + `test_race_conditions` — **24/24 grün** |

**Hinweis:** Interaktive DevTools-Checks (Timer-Flackern, Back/Forward, doppelte Network-Polls) sind im Code-Pfad verifiziert (`cleanupPage`, `setSafeInterval`, Allowlists). Für Queue-Near-Finish und X5-Spam-Navigation empfiehlt sich ein kurzer **menschlicher** Spot-Check ([GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md)).

---

## Prüfschema (pro Modul)

| # | Frage | Verstoß wenn … |
|---|--------|----------------|
| R1 | **Reloads?** | `location.reload()` / `location.href =` für Ingame-Nav |
| R2 | **Eigene Wahrheit?** | Client berechnet Mechanik (Ressourcen, Queue, Fleet, Kampf) |
| R3 | **Eigenes Spiel-Polling?** | Zweites `/api/game-state` oder paralleler „Live-State“ |
| R4 | **Eigenes Queue-Verhalten?** | Cancel ohne Reschedule / ohne `finish_due_work` |
| R5 | **Planet Scope?** | Session-Planet, Homeworld-Hardcode, falscher `planet_id` |
| R6 | **AJAX Contract?** | POST ohne `{ ok, state }` + `applyActionState()` |

**Legende:** ✅ ok · ⚠️ dokumentierte Ausnahme · ❌ Fix-Ticket

---

## Modul-Matrix (Browser Validation)

| Modul | R1 | R2 | R3 | R4 | R5 | R6 | Ergebnis | Follow-up |
|------|----|----|----|----|----|----|----------|-----------|
| Overview | ✅ | ✅ | ✅ | — | ✅ | ✅ | OK | — |
| Buildings | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | OK | — |
| Research | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | OK | — |
| Trader Hub | ✅ | ✅ | ✅ | — | ✅ | ✅ | OK | — |
| Shipyard | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ | OK* | GC-512D |
| Fleet | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | OK* | GC-512B |
| Galaxy | ✅ | ✅ | ✅ | — | ✅ | ✅ | OK | — |
| Messages | ⚠️ | ✅ | ✅ | — | — | ✅ | OK* | GC-512C |
| Chat | ✅ | ✅ | ⚠️ | — | — | ✅ | OK* | — |
| Planet Evolution | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | OK* | GC-512A |
| Planet Switcher | ✅ | ✅ | ✅ | — | ✅ | ✅ | OK | — |
| Ranking | ✅ | ✅ | ✅ | — | — | ✅ | OK | — |
| Alliance | ✅ | ✅ | ✅ | — | — | ✅ | OK | — |

\* **OK mit dokumentierten Ausnahmen** — kein P0/P1-Blocker für Defense/Combat/Recycler.

### Modul-Notizen

- **Overview:** `GC.navigateTo` / `refreshGameState`; Movement-Countdowns über `data-countdown-at` + server `remaining`; kein zweites `/api/game-state` in Modul-JS (pytest).
- **Buildings / Research:** `applyActionState` auf upgrade/cancel/start; GC-510 Reschedule in `buildings.py` / `research.py`; Race-Tests grün.
- **Trader Hub:** `applyActionState` auf `/api/exchange` und `/api/trader/scrapyard`; Fuel-Panel clientseitig nur Anzeige aus `data-*` nach Server-Render.
- **Shipyard:** Kanonisch `orbital_shipyard` / `shipyard_queue.py`; Seiten-Poll `GET /api/shipyard` via `setSafeInterval` + `registerCleanup(stopShipyardTimers)` — kein game-state-Duplikat; Mutations nutzen `res.data` + `refreshGameState`, nicht `applyActionState(state)`.
- **Fleet:** `GET /api/fleet/state` bei Init/Countdown-Expiry/Send — kein Dauer-Poll parallel zu game-state; `applyActionState` auf send; URL-Prefill `applyFleetUrlPrefill`.
- **Galaxy:** PJAX-Nav + `prefetchGalaxyAdjacent`; Fleet-Links mit Query-Params.
- **Messages:** PJAX + `registerCleanup(resetMessagesPageState)`; `navigateTo` primär, `location.href` nur No-JS-Fallback (allowlisted).
- **Chat:** Eigenes `/api/chat/*`-Polling; `registerCleanup(stopPolling)` persistent — GC-000-Ausnahme.
- **Planet Evolution:** Server liefert `{ ok, state }` via `_action_json_response`; Client nutzt durchgängig `GC.reloadCurrentPage()` (PJAX, kein Document-Reload) statt `applyActionState`.
- **Planet Switcher:** `POST /api/planets/active` → `applyActionState` → `reloadCurrentPage` (PJAX scope refresh).
- **Ranking:** Einmal `GET /api/ranking`; Abort bei PJAX-Leave.
- **Alliance:** Platzhalter-Template, Shell-PJAX only.

---

## Querschnitt X1–X5

| ID | Schritt | R1 | R2 | R3 | R5 | R6 | Ergebnis |
|----|---------|----|----|----|----|----|----------|
| X1 | Nav-Loop (Overview → … → Overview) | ✅ | ✅ | ✅ | — | ✅ | OK — `cleanupPage` → `initPage` → ein game-state-Rhythmus |
| X2 | Planet Switch Under Load | ✅ | ✅ | ✅ | ✅ | ✅ | OK — `applyActionState` + scoped PJAX reload |
| X3 | Browser Back/Forward | ✅ | ✅ | ✅ | — | ✅ | OK — `popstate` → `GC.navigateTo` (code) |
| X4 | Action → State Sync | ✅ | ✅ | ✅ | ✅ | ⚠️ | OK* — PE/Shipyard nutzen PJAX/`data` statt `state`-Patch |
| X5 | Cleanup / schnelle Navigation | ✅ | — | ✅ | — | ✅ | OK — `pageLifecycle` intervals/timeouts/abort; Chat/Messages persistent cleanup |

Route X1 (Ticket): Overview → Buildings → Research → Trader Hub → Shipyard → Fleet → Galaxy → Planet Evolution → Messages → Overview.

---

## Queue-Manual-QA (GC-510)

Server- und Static-Verträge: **grün** (pytest inkl. Cancel/Reschedule/Near-finish-Races).

| Bereich | Automatisiert | Manuell ([Queue-QA](GC-512_QUEUE_MANUAL_QA.md)) |
|---------|---------------|--------------------------------------------------|
| A Build | Race + static | Empfohlen: A4/A6 Timer-UI |
| B Research | Race + static | Empfohlen: B4/B5 |
| C Planet | `applyActionState` + PJAX reload | Spot-check |
| D PJAX | `cleanupPage` / single poll | Spot-check |
| E GC-000 | Enforcement tests | Spot-check |

---

## Follow-up Kandidaten

### GC-512A – Planet Evolution: `applyActionState` statt PJAX-Reload

**Problem:** PE-POSTs liefern kanonisches `state`, der Client ignoriert es und ruft `GC.reloadCurrentPage()` auf (7 Action-Pfade in `bindPlanetEvolutionOnce`).

**Betroffene Datei(en):** `static/main.js` (PE-Handler ~6520–6618)

**Schwere:** P1

**Warum Verstoß gegen GC-000:** Regel 2/4 [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — Mutationen sollen UI aus `json.state` patchen, nicht Full-Fragment-Reload als Default.

---

### GC-512B – Fleet/Shipyard Seiten-APIs dokumentieren

**Problem:** `GET /api/fleet/state` und `GET /api/shipyard` sind legitime Seiten-Snapshots, aber nicht in `STATE_AJAX.md` Tabellenform festgehalten.

**Betroffene Datei(en):** `docs/STATE_AJAX.md`, `static/main.js`

**Schwere:** P2

**Warum Verstoß gegen GC-000:** Regel 4 — Ausnahme muss explizit dokumentiert sein (kein zweites game-state, aber zweite **Seiten**-Wahrheit).

---

### GC-512C – Messages `location.href` Fallback

**Problem:** `navigateFleetAttack` fällt auf `window.location.href` zurück wenn `GC.navigateTo` fehlt (allowlisted in pytest).

**Betroffene Datei(en):** `static/js/messages.js` (187, 1692)

**Schwere:** P2

**Warum Verstoß gegen GC-000:** Regel 2 No Full Reload — nur No-JS/Fatal; optional entfernen wenn Shell immer `main.js` lädt.

---

### GC-512D – Shipyard JSON-Envelope `{ ok, data }`

**Problem:** Shipyard-Mutations nutzen `fleet_ok` → `{ ok, data }` statt `{ ok, state }`; Client patched `res.data` manuell.

**Betroffene Datei(en):** `game/fleet_api.py`, `app.py` (shipyard routes), `static/main.js`

**Schwere:** P2

**Warum Verstoß gegen GC-000:** Regel 2/4 — einheitliches Action-State-Envelope; funktional OK durch `refreshGameState` nach Build.

---

## Abnahme

| Bereich | Static pytest | Browser / Code |
|---------|---------------|----------------|
| GC-000 Guards | ✅ `test_core_architecture_enforcement` | ✅ |
| Queue Contracts + Races | ✅ `test_queue_static_contract` + `test_race_conditions` | ✅ server; UI-Timer spot optional |
| Modul-Matrix | — | ✅ alle Zeilen |
| Querschnitt X1–X5 | — | ✅ (code-path) |
| P0/P1 offen | — | **Keine P0** — **1× P1** (GC-512A, nicht blockierend für Baseline) |

```
Architecture Baseline v1.0 = validated
```

Roadmap freigegeben für: **GC-600 Defense** · **GC-700 Combat** · **GC-800 Recycler** · **GC-900 Fleet Logistics**

---

## Referenzen

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regeln 1–17
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)
- [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md)
- [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md)
- [PLANET_SCOPE.md](PLANET_SCOPE.md)
- [STATE_AJAX.md](STATE_AJAX.md)
- [ROADMAP.md](ROADMAP.md)
