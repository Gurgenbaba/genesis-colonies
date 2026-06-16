# GC-621 — First 30 Minutes (Manual QA)

**Status:** Offen — Spieler-Perspektive, kein Pytest  
**Priorität:** P1 — **vor** GC-SEC-P0 bei geschlossener / eingeladener Alpha  
**Voraussetzung:** [GC-620 Full Alpha Readiness Audit](GC-620_FULL_ALPHA_READINESS_AUDIT.md) abgeschlossen; Vollsuite grün (GC-620F + GC-620C)

---

## Warum dieses Ticket existiert

```text
Der Code vertraut sich wieder selbst.
Jetzt muss ein Spieler dem Spiel vertrauen.
```

Pytest beantwortet: *„Liefert die API 200?“*  
GC-621 beantwortet: *„Will ich nach 5 Minuten weiterspielen?“*

**Nicht Ziel:** Feature-Inventur oder System-Parität zu OGame.  
**Ziel:** Ein neuer Commander kann nach 30 Minuten **eine Geschichte erzählen** — ohne Wiki, ohne Erklärung von außen.

---

## Setup

| Item | Wert |
|------|------|
| Server | `python app.py` → [http://127.0.0.1:5000](http://127.0.0.1:5000) |
| Account | **Frisch** — `/register`, neuer Commander, keine Cheats |
| Browser | Desktop 1440×900 **und** Mobile 390×844 (zwei Durchläufe empfohlen) |
| DevTools | Console offen; Network-Tab bei Flotten/Expedition |
| Sprache | `de` (Primär); Stichprobe `en` optional |
| Zeit | Echtzeit — keine Admin-Beschleunigung, außer explizit als Anhang dokumentiert |

**Ergänzt:** [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) (technische Regression).  
**Folge-Tickets aus Findings:** [GC-620B](GC-620_FULL_ALPHA_READINESS_AUDIT.md#gc-620b--locale--player-facing-copy-reality-sync) (Copy), GC-SEC-P0 (öffentliche Alpha).

---

## So wird getestet

1. **Eine Person = ein Durchlauf.** Timer starten bei Register.
2. Pro Minute: **Pass / Fail / Unklar** + 1 Satz Spieler-Gedanke (Zitat).
3. Screenshots nur bei Fail oder „Magie-Moment“.
4. Findings kategorisieren (siehe § Ergebnis-Log).

**Definition „Pass“:** Ein durchschnittlicher Strategy-Spieler versteht *was* und *warum* — ohne „Was mache ich jetzt?“.

---

## Minute 0 — Register & erster Eindruck

**Route:** `/register` → Redirect (typisch `/overview`)

### Fragen (laut denken)

- Was ist Genesis Colonies?
- Was ist mein Ziel?
- Was mache ich als Erstes?

### Erwartung

| # | Check | Pass-Kriterium |
|---|-------|----------------|
| 0.1 | Register-Form | Klar, kein Crash, sinnvolle Fehlermeldungen |
| 0.2 | Erster Screen nach Login | Hauptsitz / Overview — nicht leer, nicht Admin |
| 0.3 | Identität | Ich bin „Commander“ / Spielername sichtbar |
| 0.4 | Ton | Sci-Fi-Strategie, nicht generisches Dashboard |

### Darf **nicht** passieren

- Zu viele gleichwertige Buttons ohne Hierarchie
- Fünf Menüs gleichzeitig ohne Fokus
- Unklare Begriffe ohne Kontext (z. B. nur „PE“ ohne Erklärung)
- Gefühl: *„Was mache ich jetzt?“*

**Spieler-Zitat (notieren):** _________________________________

---

## Minute 1 — Hauptsitz & Ressourcen

**Route:** `/overview` (Homeworld)

### Erwartung

```text
Ich lande auf meinem Hauptsitz.

Ich sehe:

  Genesis Ark (oder Homeworld-Name)
  Level 1

  Ferronit · Crytite · Brennzellen (bzw. en: Ferronit / Crytite / Fuel Cells)

  und eine klare nächste Aktion:

  → Baue etwas. / Forschung. / Erkunde.
```

| # | Check | Pass-Kriterium |
|---|-------|----------------|
| 1.1 | Planet-Name & Level | Homeworld erkennbar, Level sichtbar |
| 1.2 | Resource-Bar | Fe / Cr / Fuel (oder lokalisierte Namen), Werte plausibel |
| 1.3 | Live-Tick | 10–15 s warten: Werte oder Anzeige aktualisiert sich (Poll) |
| 1.4 | Nächster Schritt | Mindestens ein CTA oder Teaser zeigt Richtung (Build/Research/Map) |
| 1.5 | Navigation | Sidebar (Desktop) oder Bottom-Nav (Mobile) — nicht überladen |

### Darf **nicht** passieren

- Ressourcen ohne Einheit / ohne Rate-Hinweis wo erwartet
- Voller Page-Reload bei erstem Nav-Klick (PJAX-Shell)
- Placeholder-Texte auf Kernseiten (*„coming soon“* auf Overview)

**Spieler-Zitat:** _________________________________

---

## Minute 3 — Erste Forschung

**Route:** `/research`

### Flow

```text
Ich öffne Forschung.

↓

Verstehe: Warum forsche ich das?

↓

Starte Forschung (1. Tech).

↓

Timer läuft sauber (Card-Queue, kein Reload).
```

| # | Check | Pass-Kriterium |
|---|-------|----------------|
| 3.1 | Tech-Liste | Kosten, Dauer, mindestens ein „startbar“ sichtbar |
| 3.2 | Motivation | Tech-Name + Kurzinfo → ich verstehe den Nutzen grob |
| 3.3 | Start | Klick startet Queue; Ressourcen abgezogen |
| 3.4 | Timer | `gc-card-queue-timer` / Card-Status AKTIV; Countdown läuft |
| 3.5 | Copy-Wahrheit | Kein Text widerspricht Backend (siehe § Bekannte Copy-Risiken) |

### Darf **nicht** passieren

```text
„Kampf nicht verfügbar“ / „Combat not active“

obwohl Combat im Spiel existiert und Reports ankommen.
```

**Bekannte Copy-Risiken (Audit GC-620):** → Ticket **GC-620B**

| Key (de) | Aktuell (verdächtig) |
|----------|----------------------|
| `fleet_mission_hint_attack` | „Kampfsimulation noch nicht aktiv (Phase 1)…“ |
| `logistics_tab_distribute_soon` | „Verteilen — folgt in einem späteren Update“ |

**Spieler-Zitat:** _________________________________

---

## Minute 5 — Erste Expedition (kritischer Moment)

**Das ist der wichtigste Abschnitt.** Hier entscheidet sich, ob Genesis sich wie ein eigenes Spiel anfühlt.

### Zwei gültige Pfade

**A) World Map (bevorzugt für GC-621)**

1. `/galaxy?view=command_map`
2. Strategisches Weltfeld / Expeditions-Zone wählen
3. World Inspector Modal → Expedition starten
4. Fleet-Prefill → Senden

**B) Klassische Galaxy**

1. `/galaxy?view=system`
2. Expeditions-Slot (Pos. 16) oder Shortcut
3. `/fleet?mission=expedition` → Senden

### Erwartung

```text
Ich schicke ein Schiff.

↓

Die Route leuchtet / Fleet-Route auf der Map sichtbar.

↓

Activity-Feed oder Map reagiert.

↓

Ich bekomme einen Bericht (Messages).

↓

Ein neuer Ort / Status / Bekanntheit wirkt spürbar.

↓

Ich denke: „Oh cool.“
```

| # | Check | Pass-Kriterium |
|---|-------|----------------|
| 5.1 | Schiff verfügbar | Mindestens 1 Expeditions-Schiff (ggf. vorher Shipyard — notieren wenn Blocker) |
| 5.2 | Send | Preview grün oder **klare** Block-Meldung (nicht stumm) |
| 5.3 | Route VFX | Fleet-Route auf Command Map oder Fleet-UI sichtbar |
| 5.4 | Wartezeit | Countdown verständlich; kein Reload nötig |
| 5.5 | Bericht | Message mit Expedition-Report; lesbarer Inhalt |
| 5.6 | Discovery | GC-596-Moment: Modal/Flavor bei Erstentdeckung — **nicht** nur `+15000 Metall` |
| 5.7 | Map-Feedback | Feld/Node zeigt neuen Status (expedition / familiarity / badge) |

### Darf **nicht** passieren

```text
+15000 Metall — fertig.
```

Dann ist der Discovery-Moment (GC-596) verschenkt: Belohnung ohne Geschichte.

Weitere No-Gos:

- Flotte verschwindet ohne Feedback
- Bericht nur technische Koordinaten ohne Flavor
- Inspector schließt sich / Map verwirrt nach Klick

**Spieler-Zitat:** _________________________________  
**Magie-Moment (ja/nein):** ______ **Warum:** _________________

---

## Minute 8 — Command Map

**Route:** `/galaxy?view=command_map`

### Fragen (ohne Wiki beantworten)

| Frage | Pass wenn … |
|-------|-------------|
| Was ist meine Hauptwelt? | Homeworld-Knoten / Genesis Core erkennbar |
| Welche Kolonien habe ich? | Eigene Knoten unterscheidbar |
| Welche Orte sind spannend? | Expedition / Colonize / Landmarks visuell differenziert |
| Was kann ich anklicken? | World Inspector Modal öffnet sich konsistent |
| Warum Expeditionen? | Mindestens ein Ort wirkt „lohnend“ (Promise/Reward/Flavor) |

| # | Check | Pass-Kriterium |
|---|-------|----------------|
| 8.1 | Full-Map Layout | Kein rechtes Sidebar-HUD; Modal statt Site-Inspector (GC-597C) |
| 8.2 | Pan/Zoom | Map bedienbar (Desktop + Touch) |
| 8.3 | Inspector | Klick auf Kolonie / Weltfeld / Landmark → Modal mit Aktionen |
| 8.4 | Aktionen | Colonize / Expedition / Fleet-Prefill aus Inspector erreichbar |
| 8.5 | Klarheit | Nach 3 Klicks: **weniger** verwirrt, nicht mehr |

### Darf **nicht** passieren

```text
Ich klicke 3 Dinge und bin verwirrter als vorher.
```

- Doppelte Inspector-Patterns (Modal + verstecktes Legacy-Shell)
- Klick ohne Feedback
- Fremde Kolonie: Crash oder zu viel Intel

**Spieler-Zitat:** _________________________________

---

## Minute 15 — Wiederkommen?

### Reflexions-Block (Pflicht)

**Will ich wiederkommen?** ☐ Ja ☐ Nein ☐ Unklar

Wenn **Ja** — warum? (max. 2 ankreuzen)

- ☐ Discovery / Erkundung
- ☐ Progress / Queue läuft
- ☐ Command Map / Imperium-Gefühl
- ☐ Flotten / Routen
- ☐ Wirtschaft / Bau
- ☐ Atmosphäre / UI

Wenn **Nein** — warum? (max. 2 ankreuzen)

- ☐ Zu langsam (nichts passiert)
- ☐ Zu kompliziert
- ☐ Zu wenig Feedback
- ☐ Nicht verstanden
- ☐ Copy widerspricht Spiel
- ☐ Bug / Crash

| # | Check | Pass-Kriterium |
|---|-------|----------------|
| 15.1 | Offene Loops | Mindestens 1 Queue oder Flotte „läuft noch“ |
| 15.2 | Neugier | Mindestens 1 Ort auf der Map wirkt unerkundet |
| 15.3 | Kein Dead End | Ich weiß, was ich als Nächstes *könnte* tun |

**Spieler-Zitat (1 Satz):** _________________________________

---

## Minute 30 — Optional (Stretch)

Nur wenn Minute 15 **Ja** war:

| # | Thema | Kurz-Check |
|---|--------|------------|
| 30.1 | Zweite Kolonie / Claim | World-Colonize-Flow verständlich? |
| 30.2 | Messages | Kampf/Spionage/Expedition-Karten lesbar? |
| 30.3 | Meta | Vote / Auction / Ranking — wirken live oder Placeholder? |
| 30.4 | Mobile | Zweiter Durchlauf 390px — gleiche Story? |

---

## Ergebnis-Log (pro Durchlauf ausfüllen)

| Feld | Wert |
|------|------|
| Datum | |
| Tester | |
| Browser / Viewport | |
| Locale | de / en |
| Account | frisch / bestehend |
| Gesamt | ☐ Pass ☐ Fail ☐ Pass mit Findings |

### Minuten-Scorecard

| Minute | Pass | Fail | Unklar | Notiz |
|--------|------|------|--------|-------|
| 0 Register | | | | |
| 1 Hauptsitz | | | | |
| 3 Forschung | | | | |
| 5 Expedition | | | | |
| 8 Command Map | | | | |
| 15 Wiederkommen | | | | |

### Finding-Kategorien

| Kategorie | Bedeutung | Typisches Ticket |
|-----------|-----------|------------------|
| **A — Copy-Lüge** | Text sagt „nicht verfügbar“, System ist live | GC-620B |
| **B — Präsentation** | System da, Spieler sieht nicht warum es cool ist | GC-621x / UX Polish |
| **C — Flow-Lücke** | Spieler kommt nicht zum Feature (Shipyard, Schiff, Fuel) | Gameplay / Onboarding |
| **D — Bug** | Crash, 500, Timer hängt, State falsch | Bug-Ticket |
| **E — Placeholder OK** | Alliance / Politics — bewusst WIP | Doku only |

### Bekannte Findings (aus erstem Durchlauf)

| ID | Kat. | Minute | Beschreibung | Status |
|----|------|--------|--------------|--------|
| F1 | C | 0–1 | Desktop-Sidebar „Wirtschaft“: Vote, Inventar, Auktionshaus nicht erreichbar (nur Mobile-Drawer) | ✅ Fix: Trading-Subnav in `sidebar.html` wiederhergestellt |
| F2 | B | 0–1 | Nachrichten nur in Header/Verwaltung — Spieler erwarten eigenen Sidebar-Eintrag | ✅ Fix: Nachrichten unter **Kommando**, Header-HUD entfernt, Unread-Badge in Sidebar |

### Findings-Liste

| ID | Kat. | Minute | Beschreibung | Screenshot | Ticket-Vorschlag |
|----|------|--------|--------------|------------|------------------|
| F1 | | | | | |
| F2 | | | | | |

---

## Abnahme GC-621

GC-621 ist **grün**, wenn:

1. **Mindestens 2 unabhängige Durchläufe** (Desktop + Mobile) dokumentiert
2. Minute **5** und **8** jeweils **Pass** oder dokumentierte Findings mit Ticket
3. Minute **15** mindestens 1× **Ja** mit nachvollziehbarem Grund
4. Kein **Kategorie-D** Blocker ohne Ticket
5. Ergebnis-Log in diesem Doc oder verlinktem `GC-621_QA_LOG_YYYY-MM-DD.md`

GC-621 ist **rot**, wenn:

- Expedition endet ohne Bericht / ohne spürbares Feedback
- Command Map nach 3 Interaktionen unverständlicher
- Kern-Copy behauptet Features seien deaktiviert, die spielbar sind

---

## Hypothese (Audit GC-620)

```text
Ihr findet eher nicht:

  „Fehlendes System“

sondern:

  System existiert
  ↓
  Spieler sieht nicht, warum er es lieben soll.
```

GC-621 ist der Test dafür.

---

## North Star

> Ein neuer Spieler erstellt einen Account, erlebt die ersten 30 Minuten und sagt:
>
> **„Okay… das ist nicht OGame.“**

Nicht weil mehr Features da sind — sondern weil **eine eigene Geschichte** in den ersten Minuten beginnt.

---

## Verwandte Dokumente

- [GC-620 Full Alpha Readiness Audit](GC-620_FULL_ALPHA_READINESS_AUDIT.md)
- [GC-620F Test Contract Sync](GC-620F_TEST_CONTRACT_SYNC.md)
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md)
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — Command Map / `view=system`
- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — Expedition, World-native targets (GC-590A)
- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Command Map Vision
