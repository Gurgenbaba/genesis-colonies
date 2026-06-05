# GC-547 — Browser-Validation (Overview + Simple Pages)

**Datum:** 2026-06-05  
**Status:** Teilweise validiert (Task-Manager CPU/RAM/Netz OK) · **GPU/FPS noch messen**

**Schließen:** Wenn Overview **und** Landing/Login/Register Console-Snapshots + Task-Manager-GPU + FPS idle erfüllen → GC-547 + [GC-547B](GC-547B_LANDING_LOGIN_GPU_AUDIT.md) abnehmen, Spieler erneut testen lassen.

**Regel:** Keine weiteren Optimierungen, bis GPU + FPS gemessen sind. Bei sauberen Werten → GC-547/547B schließen, **[GC-611](GC-610_COMPLETE_DEFINITION_AUDIT.md)**. Bei hohen Idle-FPS → **[GC-547C](GC-547C_FPS_COMPOSITOR_AUDIT.md)** (erst dann implementieren).

---

## Kernerkenntnis (Task-Manager)

Der wichtigste Befund ist **nicht** die CPU — sondern das Gesamtprofil nach GC-545 → GC-547B:

```text
CPU ~0,5 %
Netzwerk 0
RAM ~97 MB
```

Das ist **nicht mehr das Profil eines Spiels mit JS-Performance-Bug**. Vor GC-546D wären Poll-Storms der erste Verdacht; jetzt eher:

```text
Browser rendert brav · GPU taktet eventuell hoch · Spieler sagen "heiß"
```

**Der spannendste fehlende Wert: FPS** — nicht CPU, nicht RAM.

---

## Automatisiert (CI)

```bash
python -m pytest tests/test_static_live_updates.py -v   # 32 passed
python scripts/gc547_browser_audit.py                 # Playwright (optional)
```

`scripts/gc547_browser_audit.py` startet `app.py` als Subprocess und misst rAF/setInterval/`gc-perf-idle` über 60 s Idle + 30 s Hidden Tab + Build-Timer. Auf Windows kann der Parent-Prozess SQLite-Locks halten — **verbindliche Abnahme bleibt DevTools + Browser-Task-Manager im echten Browser**.

---

## Task-Manager-Baseline (Chrome/Edge)

**Öffnen:** `Shift + Esc` → Genesis-Tab auswählen.

Typische **gesunde Idle-Werte** nach GC-547 + GC-547B (Beispiel-Messung Overview):

| Metrik | Gemessen | Erwartung Idle | Bedeutung |
|--------|----------|----------------|-----------|
| CPU | ~0,5 % | < 2 % | Kein Poll-Storm, kein Dauer-Timer |
| RAM | ~97 MB | stabil | Normal für SPA-Shell |
| Netzwerk | 0 | 0 (zwischen Polls) | Kein Request-Spam |

**Interpretation:** Bei JS-Loop, Poll-Storm oder permanenten Timern wären typischerweise **CPU 5–20 %+**, viele Netzwerk-Requests und steigende Browserlast sichtbar. Fehlt das → **GC-547 hat die JS-Ursache sehr wahrscheinlich bereits beseitigt.**

Der Browser-Task-Manager zeigt standardmäßig **keine** GPU-Auslastung oder FPS — dafür § GPU/FPS unten.

---

## GPU/FPS-Messung (2 Min)

### 1. GPU-Spalten aktivieren

`Shift + Esc` → Rechtsklick auf Tabellenkopf → aktivieren:

- **GPU-Speicher**
- **GPU-Prozess**

Dann auf **Landing** und **Overview** (je 30 s idle) prüfen:

| Wert | Erwartung Idle |
|------|----------------|
| GPU Memory | niedrig bis moderat |
| GPU Process | nahe 0–1 % |

### 2. Laufende Animationen

Konsole — **Overview** (Detail-Dump):

```javascript
document.getAnimations()
  .filter(a => a.playState === "running")
  .map(a => ({
    currentTime: a.currentTime,
    effect: a.effect?.target?.className
  }))
```

Erwartung: **`[]`** oder sehr wenige Einträge.

Kurz-Check (alle Routen):

```javascript
document.getAnimations().filter(a => a.playState === "running").length
```

Erwartung: **`0`**.

### 3. FPS Meter (entscheidend)

DevTools → **More tools → Rendering** → **FPS Meter**.

Je Route **30 s idle**: Landing, Login, Overview.

| Ergebnis | Bedeutung |
|----------|-----------|
| **0–1 FPS** / kaum Repaints | GC-547/547B erfolgreich → **schließen**, weiter zu GC-611 |
| **144 / 240 / 360+ FPS** dauerhaft | Täter gefunden → **[GC-547C](GC-547C_FPS_COMPOSITOR_AUDIT.md)** |

---

## Einschätzung nach erstem Task-Manager-Snapshot

| Ursache | Wahrscheinlichkeit | Hinweis |
|---------|-------------------|---------|
| Polling / Timer | ~1 % | CPU/Netz wären hoch |
| JS-Endlosschleife | ~1 % | CPU wäre hoch |
| Fleet/Queue-System | ~1 % | Nur bei aktiven Jobs |
| CSS Background-Layer | ~25 % | GC-547B reduziert; Layer-Test |
| **Unbegrenzte FPS (240–360)** | **~40 %** | FPS Meter prüfen |
| Nutzerwahrnehmung („GPU warm“) | ~30 % | Karte taktet ohne echten Bug |

Viele Spieler melden „GPU wird heiß“, wenn der Tab **uncapped mit 240–360 FPS** rendert und die Grafikkarte deshalb hochtaktet — ohne JS-Bug.

**Nächster Schritt:** FPS Meter + GPU messen — **nicht** blind weiter optimieren.

---

## Abschluss-Entscheidung

```text
FPS idle ≈ 0–1  +  runningAnims = 0  +  CPU/Netz wie oben
  → ✅ GC-547 schließen
  → ✅ GC-547B schließen
  → Roadmap: GC-611 Fleet Close-Out

FPS idle 144+  bei CPU ~0,5 %
  → 📋 GC-547C FPS / Compositor Audit (siehe Doc)
  → kein GC-547-Reopen
```

**Layer-Test (nur wenn GPU hoch, FPS unklar):** `.gc-bg { display: none !important; }` in DevTools.

---

## Manuelle Checkliste (5 Min)

**Setup:** `python app.py` → einloggen → `/overview` → **keine** aktiven Queues/Fleet.

### 1. Overview 60 s Idle

DevTools → **Performance** → Record **60 s** → Stop.

| Erwartung | Fail |
|-----------|------|
| CPU-Graph flach nach ~5 s Settle | Dauerhafte Spikes alle 50–250 ms |
| Keine 60 FPS Dauerlast | Kontinuierliches Rendering |
| Wenige Layout/Paint-Events | Vollflächige Repaints |

**Konsole (Snapshot):**

```javascript
({
  gcPerfIdle: document.body.classList.contains('gc-perf-idle'),
  polling: GC.polling?.running,
  shouldRunVisual: GC.shouldRunVisualLoops?.(),
  runningAnims: document.getAnimations?.().filter(a => a.playState === 'running').length,
})
```

Erwartung idle: `gcPerfIdle: true`, `shouldRunVisual: true`, `runningAnims: 0`.

### 2. Tab wechseln 30 s

Anderen Tab öffnen, **30 s** warten, zurück.

| Erwartung | Fail |
|-----------|------|
| `document.body` hat kurz `gc-tab-hidden` (optional prüfen) | — |
| Network: **kein** `/api/game-state` während hidden | Polls weiter alle 5 s |
| CPU im Task-Manager fällt sichtbar ab | GPU/CPU konstant hoch |

Nach Rückkehr: ein `/api/game-state` (tab_visible), dann normaler 5 s Idle-Poll.

### 3. Build-Timer aktiv → Ende

Kurzen Bau starten (z. B. Mine L1).

| Phase | Erwartung |
|-------|-----------|
| Während Bau | `gc-perf-idle` **fehlt**, Countdown tickt (~1 s), kein rAF-Dauerloop |
| Nach Fertigstellung | `gc-perf-idle` **wieder da**, Progress-Ticker stoppt |

### 4. Landing / Login / Register (GC-547B)

**Setup:** ausgeloggt → nacheinander `/`, `/login`, `/register`.

Console beim Laden (Simple-Pages):

```text
game loop skipped (auth/simple page)
polling aborted
polling stopped
```

**Snapshot je Route:**

```javascript
({
  gcPerfIdle: document.body.classList.contains('gc-perf-idle'),
  simple: document.body.classList.contains('gc-body-simple'),
  polling: GC.polling?.running,
  runningAnims: document.getAnimations?.().filter(a => a.playState === 'running').length
})
```

Erwartung: `{ gcPerfIdle: true, simple: true, polling: false, runningAnims: 0 }`  
Danach **30 s idle** → Performance flach, GPU ruhig.

**Diagnose falls GPU noch heiß:** DevTools Styles testweise `.gc-bg { display: none !important; }` — wenn sofort ruhig, Ursache = Background-Layer (siehe GC-547B-Doc).

---

## Rendering-Hilfen

DevTools → **More tools → Rendering**:

- **Frame Rendering Stats** — Idle: FPS ≈ 0–1, nicht 60
- **Layer borders** — keine unnötigen Fullscreen-Layer
- **Paint flashing** — Idle: kein Dauer-Grün über `.gc-bg` / HUD

---

## Wenn GPU weiter heiß läuft

| Kontext | Nächster Schritt |
|---------|------------------|
| Overview idle sauber, Landing/Login heiß | [GC-547B](GC-547B_LANDING_LOGIN_GPU_AUDIT.md) (CSS/Compositor) |
| Auch Overview idle heiß | GC-547 nochmal nachschärfen (JS-Loops, Ticker, Polling) |

Auf Simple-Pages gibt es **keine JS-Timer** (Console: `game loop skipped`, `polling stopped`), aber statische GPU-Last möglich (Background-Layer, große fixed Layers, Asset-Decode).

**Layer-Test:** `.gc-bg { display: none !important; }` in DevTools — sofort ruhige GPU → 100 % Background-Layer.

---

## Ergebnis-Vorlage

| Szenario | OK | Notiz |
|----------|----|-------|
| Overview 60 s idle | ☐ | GC-547 |
| Tab hidden 30 s | ☐ | GC-547 |
| Build-Timer → Ende | ☐ | GC-547 |
| `/` 30 s idle + Console-Snapshot | ☐ | GC-547B |
| `/login` 30 s idle + Console-Snapshot | ☐ | GC-547B |
| `/register` 30 s idle + Console-Snapshot | ☐ | GC-547B |
| Task-Manager CPU < 2 %, Netz 0 idle | ☑ | Beispiel ~0,5 % / 97 MB |
| GPU Process idle < 2 % | ☐ | Shift+Esc → GPU-Spalten |
| `getAnimations().running` = 0 | ☐ | Overview + Landing |
| FPS idle ≈ 0–1 (nicht 60+) | ☐ | Landing + Login + Overview |
| Abschluss → GC-611 | ☐ | nur wenn alle Messungen grün |

**Alle relevanten ☐ → ☑:** GC-547 + GC-547B schließen, Alpha-Retest, **→ GC-611 Fleet Close-Out**.  
**FPS dauerhaft 144+ bei sonst grünen Metriken:** → [GC-547C](GC-547C_FPS_COMPOSITOR_AUDIT.md), kein GC-547-Reopen.
