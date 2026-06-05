# GC-546 — Live-State Fixes (Follow-up GC-545)

**Stand:** 2026-06-05 · **Quelle:** [GC-545 Browser Audit](GC-545_LIVE_STATE_BROWSER_AUDIT.md)  
**Epic:** STATE / PJAX / Production Completion Layer

GC-545 lieferte **Browser-Beweise** — kein Einzel-Fix. GC-546 ist die **Epic-Zerlegung** in fokussierte Tickets (je max. 3–5 Dateien).

---

## Kernerkenntnis GC-545

Die größte Baustelle ist **nicht** Fleet, Research oder Evolution.

Es ist die **Production Completion Layer**:

```text
Shipyard · Defense · Completion Refresh · State Sync · Polling · Inventory Refresh
```

pytest (41 passed) bestätigt Backend/Queue — Browser zeigt **Render-/Poll-Lifecycle**-Defekte nach Job-Fertigstellung.

---

## Fix-Reihenfolge (empfohlen)

| Prio | Ticket | Begründung |
|------|--------|------------|
| **1** | [GC-546D](#gc-546d--shipyarddefense-completion-poll-storm) | HTTP 499 / 56s+ Requests — mögliche Root Cause für C, A |
| **2** | [GC-546C](#gc-546c--production-completion-state-refresh-shipyard--defense) | ✅ Browser-QA bestanden (546D-Fix) |
| **3** | [GC-546E](#gc-546e--message-read-state-synchronization) | Badge nach Lesen (GC-539 Regression) |
| **4** | [GC-546B](#gc-546b--building-requirement-live-refresh) | ✅ Req-Box Live-Patch |
| **5** | [GC-546A](#gc-546a--score-delta-render-deduplication) | Mehrfach-Rendering +16.347 (evtl. Folge von D) |

---

## GC-546A — Score Delta Render Deduplication

| | |
|---|---|
| **Status** | 📋 |
| **Schwere** | 🔴 Hoch |
| **Finding** | F1 |

### Symptom

```text
+16.347
+16.347
+16.347
```

Punkte-Delta erscheint mehrfach (Ranking, Header Score, Delta-Animation).

### Verdacht

- Mehrfaches `showScoreDelta()`
- Mehrere Event Listener / PJAX-Rebind
- Polling triggert Animation erneut

### Scope (Vorschlag)

- `static/main.js` — Score-Delta / HUD-Patch
- ggf. Ranking-Teaser / Overview

### Akzeptanz

- [ ] Pro Score-Event maximal **eine** sichtbare Delta-Animation
- [ ] PJAX-Navigation + Poll erzeugen keine Duplikate
- [ ] pytest unverändert grün; manueller Repro aus GC-545 F1

---

## GC-546B — Building Requirement Live Refresh

| | |
|---|---|
| **Status** | ✅ Implementiert (2026-06-05) |
| **Schwere** | 🟠 Mittel |
| **Finding** | F2 |

### Symptom

Gebäude A fertig → Gebäude B backend-seitig baubar — UI zeigt weiter „Voraussetzungen nicht erfüllt“ bis Reload.

### Verdacht

- `applyActionState()` / `applyGameStateData()` patcht Requirements nicht
- `refreshBuildings()` oder buildings_panel nach Queue-Finish

### Scope (Vorschlag)

- `static/main.js` — buildings panel patch
- ggf. `templates/buildings.html` data-attrs

### Akzeptanz

- [x] Nach Bau-Finish ohne F5: gesperrte Karten werden baubar wenn Requirements erfüllt (Req-Box entfernt, Button aktiv)
- [ ] Planetwechsel konsistent (manuell)
- [ ] Browser-Repro GC-545 F2

### Root Cause

`patchBuildingPanel()` aktualisierte Level, Kosten, Action und Row-Klassen — **nicht** die `.gc-bld-card-req`-Box. Nach Unlock blieb die stale Requirement-Anzeige sichtbar.

### Umsetzung

- `patchBuildingRequirements()` — Req-Box live patchen/entfernen
- `_buildZeroHandled` — ein Completion-Refresh pro Build-Timer-Zero
- `data-building-req` auf Template-Req-Zeile

---

## GC-546C — Production Completion State Refresh (Shipyard + Defense)

| | |
|---|---|
| **Status** | ✅ Verifiziert (Browser QA 2026-06-05, via GC-546D) |
| **Schwere** | 🔴 Hoch |
| **Findings** | F3, F4 |

### Symptom

- **Shipyard:** Schiffe fertig, Stückzahl bleibt alt bis Reload
- **Defense:** identisches Verhalten (gleiche Queue-/Completion-Architektur)

> „Nach erstem Schiffbau knallt irgendwas“

### Verdacht

- Shipyard/Defense inventory patch nach Queue-Finish
- Overview / `planet_ships` / `defenses` slice nicht gepatcht
- Gemeinsamer Code-Pfad mit Defense-Queue (Parität Werft)

### Scope (Vorschlag)

- `static/main.js` — `initShipyard`, `initDefense`, completion handlers
- `applyGameStateData()` / shipyard + defense slices
- **Ein Ticket** — kein paralleler Fix nur Werft

### Akzeptanz

- [x] Schiff/Defense-Einheit fertig → Bestand + Queue ohne F5 aktualisiert (Browser: Werft + Verteidigung)
- [ ] Overview-Teaser während Bau auf Overview-Seite (nicht getestet)
- [x] Nach GC-546D: keine Poll-Storm bei Completion

### Browser-QA (2026-06-05, nach GC-546D)

| Check | Ergebnis |
|-------|----------|
| Werft öffnen | ✅ |
| 1 Schiff bauen | ✅ |
| Network: kein Hagel / keine 499 | ✅ |
| Bestand nach Fertigstellung live | ✅ |
| Verteidigung gleiches Verhalten | ✅ |

**Fazit:** F3/F4 waren Folge des Poll-Storms (546D). Kein separater Code-Fix nötig.

---

## GC-546D — Shipyard/Defense Completion Poll Storm

| | |
|---|---|
| **Status** | ✅ Implementiert (2026-06-05) |
| **Schwere** | 🔴 Sehr hoch |
| **Finding** | F5 |

### Symptom (DevTools Network)

```text
HTTP 499
/api/game-state
/api/defense
/shipyard
```

Latenz teilweise **56 s**, **1 min 25 s** — nach Shipyard/Defense-Aktionen.

### Verdacht

- Poll Loop / Endlosschleife
- Mehrfaches Refresh bei Completion (`timer_done`, `refreshOnZero`)
- Race: parallele Requests blockieren SQLite / Client

**Könnte Root Cause für F3/F4 und Teile von F1 sein.**

### Scope (Vorschlag)

- `static/main.js` — polling, `refreshGameState`, completion chain
- ggf. Shipyard/Defense module refresh on zero
- AbortController / in-flight dedup prüfen

### Akzeptanz

- [x] Nach Werft/Defense-Completion: kein Request-Sturm (Network ≤ erwartete Poll-Rate)
- [x] Keine parallelen `/api/shipyard` + `/api/defense` auf jedem game-state Poll
- [x] Single canonical poll ([STATE_AJAX.md](STATE_AJAX.md))
- [x] Manueller Browser-Repro (GC-545 F5) — DevTools Network bestätigen

### Umsetzung (`static/main.js`)

- `requestProductionCompletionSync()` — 1100 ms debounce, ein Refresh pro Timer-Zero
- `_timerZeroAlreadyFired` / `refreshFiredAt` — kein Doppel-Fire aus `updatePageTimers`
- `_productionZeroHandled` — kein Tick-Loop in `updateAllProgressBars`
- `patchDefensePanelFromGameState()` — Defense aus game-state statt Interval-Poll
- `refreshShipyardStateCoalesced` / `refreshDefenseStateCoalesced` — in-flight Dedup
- Entfernt: unconditional `scheduleShipyard/DefenseRefreshFromState` in `applyGameStateData`
- Entfernt: Defense `setInterval`-Poll in `startDefenseTimers`
- Shipyard/Defense Progress nur page-scoped (`#shipyard-page` / `#defense-page`)

### Untersuchung (Checkliste)

- [ ] Network-Waterfall bei Repro aufzeichnen
- [ ] Zählen paralleler `GET /api/game-state` pro Sekunde
- [ ] Prüfen ob `/api/defense` + game-state + page fetch gleichzeitig feuern

---

## GC-546E — Message Read State Synchronization

| | |
|---|---|
| **Status** | ✅ Implementiert (2026-06-05) |
| **Schwere** | 🟠 Mittel |
| **Finding** | F6 |

### Symptom

Nachricht lesen → Badge bleibt → erst erneutes Öffnen von „Nachrichten“ entfernt Badge.

Regression gegen GC-539 Intent.

### Verdacht

- `markRead()` → `GC.mergeLastState()` / `patchShellHudFromState()` nicht auf allen Pfaden
- Inbox-Partial vs. Shell-Badge desync

### Scope (Vorschlag)

- `static/js/messages.js`
- `static/main.js` — HUD badge patch

### Akzeptanz

- [x] Nach Lesen einer Nachricht: Badge sofort 0 / reduziert ohne Navigation
- [ ] GC-545 Flow „Messages“ manuell erneut bestätigen

### Root Cause

Stale in-flight `GET /api/game-state` (poll) konnte nach `messages.js` → `mergeLastState` einen **höheren** `unread_messages_count` zurückschreiben und das HUD-Badge wieder anzeigen.

### Umsetzung

- `coercePollUnreadForHud()` — Poll darf lokalen Unread-Stand 30 s nicht nach oben korrigieren
- `_messagesUnreadLocalAt` — gesetzt bei `mergeLastState(..., "messages_*")`
- `openInboxReportById()` — `syncUnreadFromResponse` auch beim Report-Öffnen

---

## Positiv (GC-545 — kein Fix nötig)

| System | Browser-QA | Notiz |
|--------|------------|-------|
| **Galaxy** | ✅ voll funktional | Großer Fortschritt vs. Phase 4 Anfang |
| **Planet Evolution** | ✅ soweit ok | Fehlt QA/Balance, nicht Technik (GC-610 bestätigt) |
| **Fleet** | ✅ Missionen + Nachrichten | Besser als erwartet; Risikokandidat entkräftet |
| **Research** | ✅ stabil | 90 % vor/nach |

---

## Verwandte Dokumente

- [GC-545_LIVE_STATE_BROWSER_AUDIT.md](GC-545_LIVE_STATE_BROWSER_AUDIT.md)
- [GC-610_COMPLETE_DEFINITION_AUDIT.md](GC-610_COMPLETE_DEFINITION_AUDIT.md)
- [STATE_AJAX.md](STATE_AJAX.md)
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)
