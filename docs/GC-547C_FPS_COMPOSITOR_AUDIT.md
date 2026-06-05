# GC-547C – FPS / Compositor Audit

**Epic:** Performance / Alpha UX  
**Priorität:** P0-Follow-up zu [GC-547](GC-547_GPU_PERFORMANCE_AUDIT.md) / [GC-547B](GC-547B_LANDING_LOGIN_GPU_AUDIT.md)  
**Status:** ✅ Implementiert (2026-06-05) · Browser-FPS erneut messen

---

## Befund (vor Fix)

| Metrik | Wert | OK? |
|--------|------|-----|
| `runningAnims` | 0 | ✅ |
| `polling` (Simple) | false | ✅ |
| `gcPerfIdle` (Overview) | true | ✅ |
| CPU | 1–2 % | ✅ |
| Netzwerk | 0 | ✅ |
| GPU Memory | ~30 MB | ✅ |
| **FPS idle** | **~41.8** | ❌ |

Idle sollte **0–1 FPS** sein. Browser repaintet weiter ohne laufende Animationen → **Compositor/FPS-Last**, kein JS-/Polling-Bug.

**Simple-Pages:** `gcPerfIdle: false` trotz `gc-body-simple` — `syncPerfBodyClasses()` setzte `gc-perf-idle` nur bei `shouldRunGameLoop() && !jobs`, entfernte die Klasse auf Auth-Seiten.

---

## Root Cause

1. **`syncPerfBodyClasses`** — Simple/Auth-Pages verlieren `gc-perf-idle` nach JS-Init
2. **Fixed `.gc-bg`** — Vollbild-Compositor-Layer (Gradients, Landscape, Nebula) repaintet auch ohne Animation
3. **Scanlines / Header blur** — `.gc-panel::before`, `.resource-bar::before`, `backdrop-filter` auf sticky Header
4. **Resource-Ticker** — 5 s Intervall im Idle (gering, aber unnötig bei perf-idle)

---

## Fixes

### `static/main.js`

- `isPerfIdle()` — `true` wenn `!shouldRunGameLoop()` **oder** keine aktiven Progress-Jobs
- `syncPerfBodyClasses()` — nutzt `isPerfIdle()`; pausiert Resource-Ticker bei idle
- `startResourceTicker()` / `tickLiveResourceBar()` — skip bei `isPerfIdle()`

### `static/style.css`

- **GC-547B:** `body.gc-body-simple .gc-bg` → `display: none` (Body-Fill reicht)
- **GC-547C:** bei `body.gc-perf-idle`:
  - `.gc-bg { display: none }` + ingame Body solid fill
  - Nebula, Scanlines, Header-Glow, `backdrop-filter` aus

### `templates/base.html`

- Unverändert: `gc-perf-idle` initial auf Body (JS hält Klasse jetzt)

---

## Akzeptanz

- [x] Simple/Login: `gcPerfIdle: true` nach JS-Init
- [x] `runningAnims: 0`
- [ ] FPS idle nahe 0–1 (deutlich unter ~42) — **Browser remessen**
- [x] CPU bleibt niedrig
- [ ] GPU Process bleibt niedrig — **Browser remessen**
- [x] `python -m pytest tests/test_static_live_updates.py -v` grün

**Console-Snapshot (Simple + Overview idle):**

```javascript
({
  gcPerfIdle: document.body.classList.contains('gc-perf-idle'),
  simple: document.body.classList.contains('gc-body-simple'),
  polling: GC.polling?.running,
  runningAnims: document.getAnimations?.().filter(a => a.playState === 'running').length
})
```

Erwartung Simple: `{ gcPerfIdle: true, simple: true, polling: false, runningAnims: 0 }`

---

## Diagnose (falls FPS noch hoch)

DevTools Styles testweise:

```css
.gc-bg { display: none !important; }
```

Wenn GPU sofort ruhig → Background-Layer bestätigt (547C sollte das im Idle bereits tun).

---

## Abschluss

FPS idle ≈ 0–1 + Metriken grün → **GC-547 + GC-547B + GC-547C schließen** → Roadmap **GC-611** Fleet Close-Out.

---

## Changed Files

- `static/main.js`
- `static/style.css`
- `tests/test_static_live_updates.py`
- `docs/GC-547C_FPS_COMPOSITOR_AUDIT.md`
