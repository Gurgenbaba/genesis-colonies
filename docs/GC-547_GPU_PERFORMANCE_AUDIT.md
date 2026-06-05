# GC-547 – P0 GPU/Performance Emergency Audit

**Status:** ✅ Implementiert · Abnahme: FPS-Messung ausstehend ([Validation](GC-547_BROWSER_VALIDATION.md))  
**Priorität:** P0 — Idle-GPU-Last blockiert Alpha-Spielbarkeit

---

## Problem

Spieler berichteten hohe GPU-Last direkt auf der Startseite/Overview im Idle — typisch für dauerhafte Compositor-Layer, `backdrop-filter`, permanente Timer-Loops und CSS-Animationen.

---

## Root Cause

| Ursache | Impact |
|---------|--------|
| `_hasActiveProgressJobs()` treatete `#overview-research-active` als **immer aktiv** (Element im DOM, nur `display:none`) | Progress-Ticker lief permanent auf Overview (~1 Hz DOM + Progress-Updates) |
| Abgelaufene Fleet-Countdowns hielten Ticker via `_hasStaleMovementCountdown()` am Leben (50–250 ms Intervall) | CPU/GPU auch ohne sichtbare Timer |
| Landscape-Modus: `backdrop-filter: blur()` auf Sidebar, Header, Panels | Ständige GPU-Compositing-Last |
| `.gc-bg` mit `filter:` + `translateZ(0)` auf Vollbild-Layer | Extra Compositor-Layer |
| `gc-bld-delta-pulse` infinite CSS-Animation | Unnötige Repaints (Buildings) |
| Tab hidden: Polling stoppte, **Resource-/Progress-Ticker liefen weiter** | Hintergrund-GPU/CPU |

---

## Fixes

### `static/main.js`

- `shouldRunVisualLoops()` — Game-Loop nur bei sichtbarem Tab
- `pauseVisualLoops()` / `resumeVisualLoops()` — Tab-Wechsel + PJAX-sicher via bestehendes `cleanupPage`
- `_hasVisibleOverviewResearchTimer()` — Progress-Ticker nur bei echtem Research-Countdown
- Stale Fleet-Countdowns: `_maybeRefreshStaleMovementCountdowns()` on game-state apply (kein Dauer-Ticker)
- Resource-Ticker: 5 s idle / 1 s bei aktiven Jobs; pausiert bei hidden tab
- `prefers-reduced-motion`: `animateNumber` ohne rAF
- Body-Klassen: `gc-tab-hidden`, `gc-reduced-motion`, `gc-perf-idle`

### `static/style.css`

- Landscape: `backdrop-filter` entfernt → undurchsichtige Panel-Hintergründe
- `.gc-bg`: `filter` / `translateZ(0)` entfernt
- Infinite `gc-bld-delta-pulse` entfernt
- `will-change: width` nur wenn `body:not(.gc-perf-idle)`
- Global `prefers-reduced-motion` + hidden-tab Scanline-Reduktion

---

## Performance-Test (manuell)

**Vollständige Browser-Matrix:** [GC-547_BROWSER_VALIDATION.md](GC-547_BROWSER_VALIDATION.md)

**Voraussetzung:** Eingeloggt, Overview, keine aktiven Queues/Fleet.

1. **DevTools → Performance** — 10 s Aufnahme im Idle  
   - Erwartung: keine dauerhaften 60 FPS; wenige Layout/Paint-Events  
   - Kein permanenter `requestAnimationFrame`-Stack (nur kurz bei Score-Delta o.ä.)

2. **DevTools → Rendering**  
   - „Frame Rendering Stats“: Idle FPS nahe 0 (Monitor-Refresh only)  
   - „Paint flashing“: keine Vollflächen-Repaints im HUD

3. **Tab hidden**  
   - Performance: CPU fällt auf ~0 für GC-Skripte  
   - Network: game-state polling pausiert (bestehend GC-546)

4. **Mit aktivem Build-Timer**  
   - Progress-Ticker läuft (setTimeout, kein rAF)  
   - Resource-Bar 1 s; nach Finish → `gc-perf-idle`, Ticker stoppt

5. **`prefers-reduced-motion: reduce`** (OS/DevTools)  
   - Keine Score-/Delta-Animationen; Body-Klasse `gc-reduced-motion`

```bash
python -m pytest tests/test_static_live_updates.py -v
```

---

## Akzeptanz

- [x] Overview Idle: kein permanenter Progress-Ticker
- [x] Keine globalen infinite CSS-Animationen im HUD/Shell
- [x] Timer via setTimeout (bestehend GC-540/541), stoppen wenn fertig
- [x] Hidden Tab: visuelle Loops pausiert
- [x] Landscape ohne backdrop-filter
- [x] Regression-Tests grün

**Follow-up:** [GC-547C](GC-547C_FPS_COMPOSITOR_AUDIT.md) — Idle ~41 FPS trotz `runningAnims: 0`: `isPerfIdle()` für Simple-Pages, `.gc-bg` bei perf-idle ausblenden.

**Simple-Pages:** [GC-547B](GC-547B_LANDING_LOGIN_GPU_AUDIT.md) (CSS/Compositor).

---

## Changed Files

- `static/main.js`
- `static/style.css`
- `tests/test_static_live_updates.py`
- `docs/GC-547_GPU_PERFORMANCE_AUDIT.md`
