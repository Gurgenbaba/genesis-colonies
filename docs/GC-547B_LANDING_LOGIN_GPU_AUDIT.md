# GC-547B – Landing/Login GPU Audit

**Epic:** Performance / Alpha UX  
**Priorität:** P0-Follow-up zu [GC-547](GC-547_GPU_PERFORMANCE_AUDIT.md)  
**Status:** ✅ Implementiert · **Schließen nach** manueller Console-Abnahme (siehe unten)

---

## Entscheidungsregel (GC-547 vs GC-547B)

| Beobachtung | Nächster Fokus |
|-------------|----------------|
| Overview idle sauber, Landing/Login heiß | **GC-547B** |
| Auch Overview idle heiß | **GC-547** nochmal nachschärfen |

---

## Problem

Spieler melden: **„Sobald ich das Spiel betrete, wird die GPU heiß.“**

GC-547 fixte die **Ingame-Shell** (Overview-Idle-Ticker, Landscape-`backdrop-filter`, Tab-Hidden).  
Wenn Reports **danach** weitergehen, trifft der Schmerz oft schon **vor** der Overview:

| Phase | Route | Layout |
|-------|-------|--------|
| Landing | `/` | `gc-body-simple` + `.gc-bg` |
| Login / Register | `/login`, `/register` | `gc-body-simple` + `.gc-bg` + Auth-Panels |
| Erster Ingame-Screen | `/overview` | volle Shell (GC-547) |

**Ursache:** Vollflächiger `.gc-bg` (Multi-Layer-Gradients + `::after` Nebula) + Scanlines auf jedem `.gc-panel` + Header-`backdrop-filter` + Text-Glow erzeugten **statische GPU-Compositor-Last** — ohne JS-Loops.

---

## Fix (implementiert)

| Bereich | Änderung |
|---------|----------|
| `body.gc-body-simple` | Flat body background; `gc-perf-idle` auf Simple-Pages |
| `.gc-bg` / `.gc-bg-simple` | Ein linearer Gradient statt 4-Layer + Grid; kein `::after` Nebula |
| `.gc-panel::before/::after` | Scanlines auf Simple-Pages aus |
| `.gc-header` / `.gc-header-cmd` | `backdrop-filter: none`; flacher Schatten; kein `::after` Glow |
| `.landing-title`, `.auth-title` | `text-shadow: none` |
| `.landing-hero-left`, `.auth-error` | Glow-Box-Shadows durch inset-Border ersetzt |

**Dateien:** `static/style.css`, `templates/base.html`, `tests/test_static_live_updates.py`

**Nicht betroffen (Login/Landing):** `GC.startProgressTicker`, Polling, Chat — `gc-body-simple` skippt Game-Loop (`shouldRunGameLoop` = false).

**Console-Bestätigung (JS ruhig):**

```text
game loop skipped (auth/simple page)
polling aborted
polling stopped
```

→ Login/Landing-GPU-Problem war **CSS/Compositor**, nicht JS. GC-547B war der richtige Fokus.

---

## Manuelle Abnahme (Schließen von GC-547 + GC-547B)

Auf **`/`**, **`/login`**, **`/register`** je einmal in der Konsole:

```javascript
({
  gcPerfIdle: document.body.classList.contains('gc-perf-idle'),
  simple: document.body.classList.contains('gc-body-simple'),
  polling: GC.polling?.running,
  runningAnims: document.getAnimations?.().filter(a => a.playState === 'running').length
})
```

**Erwartung:**

```javascript
{ gcPerfIdle: true, simple: true, polling: false, runningAnims: 0 }
```

Zusätzlich je Route **30 s idle** → DevTools Performance flach, GPU ruhig.

**Wenn alles passt (FPS idle ≈ 0–1, GPU Process < 2 %):** [GC-547](GC-547_GPU_PERFORMANCE_AUDIT.md) + GC-547B **schließen** → Roadmap **GC-611**.  
**Wenn FPS dauerhaft 144+:** [GC-547C](GC-547C_FPS_COMPOSITOR_AUDIT.md) — kein weiterer GC-547B-Fix blind.

---

## Falls GPU trotzdem heiß bleibt

| Verdacht | Was prüfen |
|----------|------------|
| Großes Hintergrundbild / Asset-Decoding | Network → Landscape/Images, Decode-Zeit |
| Browser-HW-Beschleunigung + große fixed Layer | DevTools → Rendering → Layer borders |
| Chat/Images lazy-load | Nicht kritisch auf Simple-Pages, aber beobachten |
| `.gc-bg` als alleiniger Layer | Mini-Test in DevTools (Styles): |

```css
.gc-bg { display: none !important; }
```

Wenn GPU **sofort** ruhig wird → Ursache liegt **100 % am Background-Layer** (weiter vereinfachen oder auf Simple-Pages ganz weglassen).

---

## Akzeptanz

- [x] CSS: kein `backdrop-filter` / Nebula / Scanlines auf `gc-body-simple`
- [x] `gc-perf-idle` + `gc-bg-simple` auf SIMPLE_LAYOUT
- [x] `python -m pytest tests/test_static_live_updates.py -v` grün
- [ ] Landing 30 s idle: `runningAnims: 0`, kein rAF, kein Polling, Performance flach
- [ ] Login / Register 30 s idle: idem
- [ ] GPU bleibt ruhig (DevTools → Performance + Layer borders)

---

## Testplan (Browser)

Siehe auch [GC-547_BROWSER_VALIDATION.md](GC-547_BROWSER_VALIDATION.md).

```text
/           30s idle → Console-Snapshot OK, Performance flach
/login      30s idle → idem
/register   30s idle → idem
→ Login → /overview  → GC-547 Szenarien weiterhin grün
```

```bash
python scripts/gc547_browser_audit.py   # optional: --routes landing,login
```

---

## Abhängigkeit

- **Empfohlen nach:** GC-547 Browser-Validation auf Overview grün
- **Blockiert nichts** — Fleet Close-Out parallel möglich
