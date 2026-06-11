# GC-557 — Megabunker UX Feedback Polish (Epic)

> **Quelle:** Spieler-Feedback (Megabunker) · **Ziel:** Mehr Übersicht, bessere Lesbarkeit, klarere Navigation (Mobile + Desktop).

**Nummernkollision:** `GC-550` ist in [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) / [ROADMAP.md](ROADMAP.md) bereits **Auktionshaus**. Dieses Epic nutzt **GC-557** (557A–557F).

Stand: 2026-06-12 · Status: 📋 geplant · **Priorität:** Veteran-UX (Megabunker-Feedback)

Verwandt: [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md) (Building Cards), [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) (Trader Hub), [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md), [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md), [STATE_AJAX.md](STATE_AJAX.md)

---

## Product-Rationale

Megabunker denkt nicht wie ein Entwickler, sondern wie ein OGame/XNova/Imperia-Veteran. Genau diese Spieler entscheiden in den **ersten 30 Sekunden**, ob Genesis Colonies „Boah geil“ oder „unübersichtlich“ wirkt.

**Ziel-Kommentar nach Wave 1 (557A + 557B + 557E):**

> „Joa, das fühlt sich direkt besser an.“

---

## Priorität & Umsetzungsreihenfolge

| Prio | Ticket | Warum |
|------|--------|-------|
| **S** | **557A** Ressourcenleiste | Wichtigste UI im Spiel — Ferronit/Crytite/Brennzellen müssen auf einen Blick unterscheidbar sein |
| **S** | **557B** Navigation | Feature-Liste → Kategorien = sofort professioneller |
| **A** | **557E** Building Cards | Button/Timer-Springen zerstört unbewusst Wertigkeit |
| **A** | **557F** Technische Daten | Veteranen-Wunsch; stärkt Strategiespiel-Gefühl |
| **B** | **557C** Copy + Mobile-Scroll | Quick Win, sichtbar erst auf Empire |
| **B** | **557D** Trader Hub Limit | Sinnvoll, aber Hardcaps zuerst — sonst Top-Spieler-Explosion |

**Umsetzungsreihenfolge (bindend):**

```text
557A → 557B → 557E → 557F → 557C → 557D
```

557A, 557B und 557E sieht der Spieler **sofort nach Login** — das ist Wave 1 für schnelles Feedback.

---

## UX-Regeln (global)

| Verboten | Pflicht |
|----------|---------|
| Knalliges Grün für Upgrade-CTAs | Genesis-Türkis (`--gc-primary` / `--gc-primary-2`) — kompakt, rechts in der Card |
| Statisches Trader-Limit nur aus `game_settings` | Limit **serverseitig** aus Empire-Tagesproduktion (EffectResolver), UI zeigt Server-Wert |
| Frontend-Formeln für Produktion/Kosten/Level-Projektion | Modal-Daten aus `game/buildings.py` + EffectResolver (Regel 16) |
| `location.reload()` für Modal/Nav | PJAX + `applyActionState`; Button-Styles stabil nach Poll |
| Horizontaler Page-Overflow auf Mobile | `overflow-x: hidden` auf Shell + Cards stacken; Matrix-Hinweis **vertikal** |

---

## Ticket-Kette

| Ticket | Prio | Titel | Owner / Dateien (max. 5) |
|--------|------|-------|---------------------------|
| **GC-557A** | S | Ressourcenleiste — Icons, Kontrast, Mobile | `static/style.css`, `templates/base.html`, `static/main.js` |
| **GC-557B** | S | Navigation — logische Gruppen | `templates/partials/sidebar.html`, `locales/de.json`, `locales/en.json` |
| **GC-557E** | A | Building Cards — Upgrade-Button & Layout | `static/style.css`, `templates/buildings.html`, `static/main.js`, `tests/test_static_live_updates.py` |
| **GC-557F** | A | Gebäude — Technische-Daten-Modal (5 Level) | `game/buildings.py`, `app.py` (GET API), `templates/buildings.html`, `static/main.js`, `static/style.css` |
| **GC-557C** | B | Empire-Matrix Copy + Mobile Page-Scroll | `locales/de.json`, `locales/en.json`, `templates/empire.html`, `static/style.css` |
| **GC-557D** | B | Trader Hub — dynamisches Tageslimit | `game/exchange.py`, `game/effects/` (Empire-Aggregat), `docs/ECONOMY_SYSTEM.md`, `tests/test_exchange.py` |

---

## GC-557A — Ressourcenleiste · Prio **S**

### Problem

Ferronit, Crytite und Brennzellen in der HUD-Leiste (`resource-bar`) wirken zu gleich; Werte auf Mobile gequetscht.

> Spieler-Feedback: *„Meine Rentneraugen sehen da keinen Unterschied.“*

Das bedeutet nicht „hässlich“, sondern:

- Zu wenig **Farbtrennung**
- Zu wenig **Icon-Trennung**
- **Zahlen dominieren** — Ressourcen-Identität geht verloren

Wenn die wichtigste UI im Spiel auf einen Blick nicht lesbar ist, verliert sie ihren Zweck.

### Anforderungen

1. **Farbcodes pro Ressource** (bestehende Tokens nutzen, keine neuen Parallel-Farben):
   - Ferronit / Metall — kühles Cyan-Grün (bestehend `.hud-res-metal`)
   - Crytite / Kristall — Blau-Violett
   - Brennzellen — warmes Amber (bestehend `.hud-res-fuel-cells`)
2. **Icons** klarer trennbar (`render_resource_icon` / `.res-icon` — stärkerer Glow pro Block).
3. **Werte** größer und kontrastreicher (`.res-value`, tabular-nums).
4. **Mobile:** mehr vertikaler Abstand, kein Schrumpfen unter ~320px; ggf. zweizeiliger Wrap statt Horizontal-Overflow.

### Akzeptanz

- [ ] Drei Ressourcen auf einen Blick unterscheidbar (Farbe + Icon)
- [ ] Mobile Header: keine abgeschnittenen Werte
- [ ] Live-Update via `/api/game-state` unverändert funktional

---

## GC-557B — Navigation neu gruppieren · Prio **S**

### Problem

Aktuelle Sidebar wirkt wie eine **Feature-Liste**:

```text
Buildings · Research · Planet Evolution · Fleet · Empire · Galaxy · …
```

Veteranen denken in **Kategorien** — das wirkt sofort größer und professioneller:

```text
ÜBERSICHT      → Empire, Tech-Tree
PRODUKTION     → Gebäude, Forschung, Evolution
MILITÄR        → Werft, Flotte, Verteidigung, Logistik
UNIVERSUM      → Galaxie, Allianz, Ranking
VERWALTUNG     → Kommando, Optionen, Admin
```

Technisch: `templates/partials/sidebar.html` — heute Kolonie / Imperium / Militär / Kommando-Untermenü / Galaxie / System.

### Ziel-IA

| Sektion | Einträge |
|---------|----------|
| **Übersicht** | Empire, Tech-Tree |
| **Produktion** | Gebäude (+ Tab-Submenu), Forschung, Planet Evolution |
| **Militär** | Militärproduktion (Werft + Verteidigung), Flotte, Logistik, Verteidigung *(ein Link wenn Submenu reicht)* |
| **Universum** | Galaxie, Allianz, Ranking |
| **Verwaltung** | Kommando *(Trader Hub, Inventar, Auktionshaus, Vote Center, WIP-Einträge)*, Optionen, Admin |

Overview bleibt **oberhalb** oder als erster Link außerhalb der Gruppen (Shell-Standard beibehalten).

### Anforderungen

1. Section-Labels via i18n (`nav_section_*` Keys in `de.json` / `en.json`).
2. Bestehende Submenu-JS (`gc-nav-*-group`) wiederverwenden — **kein** zweites Nav-System.
3. Mobile Bottom-Nav / Drawer spiegeln Desktop-Gruppen (falls in `base.html` separater Block — mitziehen).

### Akzeptanz

- [ ] Gruppierung entspricht Tabelle oben
- [ ] Aktiver Zustand + PJAX-Links unverändert
- [ ] Keine broken `url_for`-Routes

---

## GC-557C — „Horizontal scrollen“ → Vertikal + Mobile Page-Scroll · Prio **B**

Quick Win — sichtbar erst auf Empire, nicht im Login-Flow.

### Problem

Empire-Matrix zeigt irreführenden Copy:

- `empire_matrix_hint` — „horizontal scrollen“
- `empire_matrix_scroll_label` — „Matrix horizontal scrollen“

(`templates/empire.html`, `locales/de.json` / `en.json`)

Spieler-Feedback: Matrix soll **vertikal** scrollen; Mobile soll **keinen** horizontalen Page-Scroll haben.

### Anforderungen

1. Copy auf vertikales Scrollen korrigieren (DE + EN).
2. `aria-label` / Hint an tatsächliches Scroll-Verhalten anpassen (`empire-matrix-scroll` Region).
3. Mobile-Audit: Shell (`body.gc-body-ingame`), Building Cards, Header — `overflow-x` / min-width-Fallen beheben (Referenz: Kommentar in `style.css` ~6012 „Mobile: stack card fields“).

### Akzeptanz

- [ ] Empire-Hinweistext sagt „vertikal scrollen“
- [ ] iPhone-Breite (~390px): kein horizontaler Page-Scroll auf Overview, Buildings, Empire
- [ ] Matrix-Spalten scrollen weiterhin innerhalb der Region (nicht Body)

---

## GC-557D — Trader Hub Tageslimit · Prio **B**

### Problem

Tageslimit ist statisch (`exchange_daily_limit` in `game_settings`, Default 2 Mrd.) — `game/exchange.py` · `get_exchange_config()`.

### Ziel

Limit **pro Commander** aus Empire-Wirtschaft — aber **immer mit Hardcaps**, damit Top-Spieler nicht explodieren:

```text
Empire Tagesproduktion  (Summe aller Kolonien, EffectResolver)
        ↓
      15 %
        ↓
   Trader Limit
        ↓
 clamp(min … max)
```

Summe = Ferronit + Crytite + Brennzellen pro Tag (analog `empire_page.py` · `*_day` Zeilen).

### Regeln

| Setting | Default | Bedeutung |
|---------|---------|-----------|
| `exchange_daily_limit_pct` | `15` | Prozent der Empire-Tagesproduktion (Gesamtsumme aller drei Ressourcen) |
| `exchange_daily_limit_min` | `100000` | Untergrenze (Early Game) |
| `exchange_daily_limit_max` | `2000000000` | **Hard-Cap** (Speedgame-Obergrenze; verhindert Top-Spieler-Explosion) |

Spielerbereich laut Feedback: **10–25 %** — Default 15 %. **`exchange_daily_limit_max` ist Pflicht**, nicht optional.

### Implementierung

1. Empire-Aggregat in **`game/exchange.py`** (Owner) — Aggregat-Logik aus `empire_page.py` wiederverwenden, nicht duplizieren.
2. Formel: `daily_limit = clamp(empire_day_total * pct / 100, min, max)`.
3. Statisches `exchange_daily_limit` in `game_settings` kann als zusätzlicher Admin-Hard-Cap dienen: `min(computed, setting)`.
4. UI: Trader Hub zeigt optional die Kette (Produktion → % → Limit) — rein Anzeige aus Server.
5. Tests: `tests/test_exchange.py` — Early Game = min, Mid = skaliert, Endgame = max.

### Akzeptanz

- [ ] Limit ≠ konstant bei unterschiedlicher Empire-Produktion
- [ ] Early Game ≥ `exchange_daily_limit_min`
- [ ] Speedgame ≤ `exchange_daily_limit_max`
- [ ] `ECONOMY_SYSTEM.md` aktualisiert

---

## GC-557E — Building Cards — Upgrade-Button & Layout · Prio **A**

### Problem

Upgrade-Button wirkt zu grell (Grün), **springt nach AJAX/Poll**; Timer und Card **verschieben sich** — zerstört unbewusst die Wertigkeit. Mehrfach gemeldet.

### Ziel-Layout (ruhige Card)

```text
[Bild]

Level 25
5:14

[ + ]   ← kompakt, türkis, rechts
```

Nur **Zahlen** wechseln bei Live-Update — Layout bleibt fix.

### Anforderungen

1. **Button:** kompakt, **rechts** in `.gc-bld-hero-action-col`, Klasse z. B. `.gc-bld-upgrade-btn` — Türkis, kein `.gc-prog-affordable` Grün für den CTA.
2. **Card:** etwas breiteres Grid (`minmax` in Buildings-Grid), Timer · Level-Badge · Button **vertikal** in Action-Spalte.
3. **Live-Update:** `static/main.js` Buildings-Patch (`patchBuildingCard` o. ä.) darf Button-Klassen nicht auf Legacy-Grün zurücksetzen — SSR- und JS-Markup synchron halten.
4. Queue-Status (GC-536B) unverändert funktional.

### Betroffene Selektoren (Referenz)

- `templates/buildings.html` — `render_building_head_action`, `render_hero_time_chip`
- `static/style.css` — `.gc-building-card`, `.gc-bld-hero-action-col`, `.gc-prog-affordable`

### Akzeptanz

- [ ] Upgrade-Button dauerhaft türkis (Initial + nach Poll)
- [ ] Kein Layout-Springen bei Timer-Tick
- [ ] `pytest tests/test_static_live_updates.py -k building` grün

---

## GC-557F — Technische-Daten-Modal (OGame-Stil) · Prio **A**

### Problem

Nur Kurz-Popover (`render_info_popover_trigger`) — kein Level-Projektions-Overlay.

**Zielgruppe:** Veteranen lieben es; Neue Spieler ignorieren es oft — trotzdem lohnt es sich für Strategiespiel-Tiefe.

### Ziel

Button **„Technische Daten“** pro Gebäude-Card → Modal:

```text
Level 26   Produktion …   Energie …   Kosten …
Level 27   Produktion …   Energie …   Kosten …
Level 28   …
…
(current + 5 Level)
```

| Spalte | Quelle |
|--------|--------|
| Level | `target_level` |
| Ferronit/h, Crytite/h, Brennzellen/h | EffectResolver / `get_building_production_per_hour` |
| Bauzeit | `game/buildings.py` |
| Kosten (M/C/FC) | `building_cost()` |
| Energie (+/−) | EffectResolver |

### API (Vorschlag)

`GET /api/buildings/<building_type>/tech-sheet?planet_id=` (context planet) → `{ ok, levels: [...] }` — **read-only**, kein `{ok,state}` nötig; Modal öffnet per PJAX-safe Fetch.

Owner: **`game/buildings.py`** · Route dünn in **`app.py`**.

### UI

- Modal-Komponente in `buildings.html` + `GC.registerCleanup` in `main.js`
- Tabellarische Ansicht (scrollbar), Mobile: volle Breite, vertikal scrollen

### Akzeptanz

- [ ] Modal zeigt Level `current` … `current+5`
- [ ] Werte = Server (Snapshot bei Öffnen; optional Refresh via game-state)
- [ ] Keine Client-Formeln für Kosten/Produktion
- [ ] Schließen ohne Page-Reload

---

## Epic-Akzeptanzkriterien

- [ ] Mobile: kein horizontaler Page-Scroll (Overview, Buildings, Empire)
- [ ] Navigation logisch gruppiert (557B)
- [ ] Ressourcen visuell klar unterscheidbar (557A)
- [ ] Trader Hub Limit skaliert mit Empire-Produktion (557D)
- [ ] Gebäude-Cards: türkiser Upgrade-Button stabil nach AJAX/Poll (557E)
- [ ] Info-Modal: aktuelles + 5 Folge-Level (557F)

---

## Discord-Antwort (Copy)

> Mega gutes Feedback, Bratwurst wurde ernst genommen 🌭  
> Ressourcenleiste, Navigation, Trader-Limit, Vertikal-Text und Build-Info-Cards kommen als eigenes UX-Polish-Paket **GC-557** rein. Grün wird’s nicht — maximal türkis mit Genesis-Vibe 😄

---

## Referenz-Docs (vor Start)

- [ ] [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regeln 15–17
- [ ] [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)
- [ ] [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) — Trader Hub
- [ ] [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md)
