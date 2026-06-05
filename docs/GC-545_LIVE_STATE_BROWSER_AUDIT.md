# GC-545 – Live-State Browser Audit

**Epic:** STATE / PJAX / Live-Updates  
**Status:** In Arbeit — pytest ✅ (2026-06-05); Browser-Matrix 📋 ausstehend  
**Voraussetzung:** GC-539–544 abgeschlossen (HUD Single Source, einheitliche Timer, Messages)

Automatische Tests (`test_static_live_updates`, Queue-Timer-Regression) sind grün. Dieses Ticket ist **kein Blind-Fix** — es sammelt Browser-Beweise für die eine Live-Komponente, die im echten UI noch nicht synchron läuft.

**Follow-up:** Findings → **GC-546** als gezielter 1–2-Datei-Fix. **Voraussetzung:** [GC-610](GC-610_COMPLETE_DEFINITION_AUDIT.md) DoC — Fleet E-Kriterien (Live-State) explizit offen.

---

## Problem

Forschung und Werft können laut pytest korrekt sein, im Browser aber hängen (Countdown steht, Balken friert, Fertigstellung braucht F5). Typische Ursache nach GC-540–542: **Render-Lifecycle** (PJAX, fehlende Timer-Attribute, Panel-Patch greift nicht), nicht Queue-Business-Logik.

---

## Betroffene Dateien

- `docs/GC-545_LIVE_STATE_BROWSER_AUDIT.md` (dieses Dokument — Findings eintragen)
- ggf. `docs/ALPHA_TESTPLAN.md` (Kurzverweis + Ergebnis)

**Nicht implementieren:** Kein Code-Fix in diesem Ticket. Kein Refactor, kein neues Timer-System.

---

## Anforderungen

### 1. Flows manuell prüfen

| Flow | Prüfen |
|------|--------|
| **Gebäude starten** | Countdown läuft? Fortschrittsbalken läuft? Fertig ohne F5? |
| **Forschung starten** | Countdown auf Research-Seite; Overview-Aktivitäten; **nach Planetwechsel** |
| **Werft starten** | Countdown auf Shipyard; Overview; **nach Planetwechsel** |
| **Fleet senden** | Fleet Page; Overview; Rückflug-Countdown |
| **Nachrichten** | Badge verschwindet sofort nach Lesen? Kein Reload nötig? |

Pro Flow: **bestanden / fehlgeschlagen** + kurze Notiz (Seite, Planet, Aktion).

### 2. DevTools — State-Snapshot

In der Browser-Console (F12), während der Bug sichtbar ist:

```js
GC.lastState?.research
GC.lastState?.shipyard
GC.lastState?.build_queue
GC._pageTimerLoopRunning
document.querySelectorAll("[data-timer-target]").length
document.querySelectorAll("[data-countdown-at]").length
```

### 3. DevTools — Timer-DOM-Audit

Zeigt sofort, ob der Timer im DOM fehlt, falsch formatiert ist, oder nur der Ticker nicht läuft:

```js
[...document.querySelectorAll("[data-timer-target], [data-countdown-at]")].map(el => ({
  text: el.textContent.trim(),
  target: el.dataset.timerTarget,
  countdownAt: el.dataset.countdownAt,
  kind: el.dataset.timerKind,
  refresh: el.dataset.refreshOnZero,
  remaining: el.dataset.serverRemaining
}))
```

### 4. Minimaler Repro (Forschung / Werft hängt)

1. Forschung oder Werft-Job starten  
2. F12 → **Elements** + **Console**  
3. Screenshots sichern:
   - aktives Queue-Element im DOM (`data-timer-target`, `data-countdown-at`, `data-finish-time`, `data-server-remaining`)
   - Console (Fehler/Warnungen)
   - Ausgabe von `GC.lastState.research` bzw. `GC.lastState.shipyard`

### 5. Typische Restfehler (Hypothesen — mit Beweis bestätigen)

| Symptom | Verdacht |
|---------|----------|
| `lastState` korrekt, DOM ohne Timer-Attrs | PJAX-Partial ersetzt ohne `data-timer-target` |
| DOM-Attrs da, Text steht | Ticker läuft nicht (`_pageTimerLoopRunning === false`) |
| Nur Overview kaputt, Detail-Seite ok | `patchResearchPanelFromState` / Overview-Teaser nicht gepatcht |
| Nach Planetwechsel falsch | Scope-Sync ok, Panel noch alter Planet |
| Countdown 0, UI stale | `data-refresh-on-zero` / Chain-Refresh (`timer_done`) |

---

## Akzeptanzkriterien

- [ ] Alle fünf Flow-Blöcke (Build, Research, Shipyard, Fleet, Messages) dokumentiert.
- [ ] Pro **Fehler**: Console-Snapshot + Timer-DOM-Audit + `GC.lastState`-Ausschnitt.
- [ ] Root Cause als **eine** konkrete Hypothese formuliert (Datei/Funktion wenn erkennbar).
- [ ] GC-546-Ticket-Skizze (1–2 Dateien, kein Epic).
- [ ] Kein Code-Change außer Doc-Update in diesem Ticket.

---

## Tests (Regression vor Audit — erwartet grün)

```bash
python -m pytest tests/test_static_live_updates.py -v
python -m pytest tests/test_game_state_live.py -v
```

**Ergebnis 2026-06-05:** `41 passed` in ~220s — automatisierte Live-State-Regression grün. Browser-Flows (§1) weiterhin manuell erforderlich.

---

## Findings (ausfüllen nach Audit)

| Flow | Status | Seite / Planet | Notiz |
|------|--------|----------------|-------|
| Build | | | |
| Research | | | |
| Shipyard | | | |
| Fleet | | | |
| Messages | | | |

### Root Cause (Kandidat für GC-546)

_(leer bis Audit abgeschlossen)_

### GC-546 Skizze

- **Problem:** …
- **Dateien:** …
- **Fix:** …

---

## Referenz-Docs

- [STATE_AJAX.md](STATE_AJAX.md)
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)
- [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md)
- [GC-610_COMPLETE_DEFINITION_AUDIT.md](GC-610_COMPLETE_DEFINITION_AUDIT.md)
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) § Timer / Single Poll

---

## Ausgabe (nach Abschluss)

### Root Cause

_(Browser-Beweis, nicht Vermutung)_

### Changed Files

_(typisch nur dieses Doc + ggf. ALPHA_TESTPLAN)_

### Tests

_(pytest weiterhin grün; manuelle Matrix oben ausgefüllt)_

### Ergebnis

_(GC-546 bereit zum Start ja/nein)_
