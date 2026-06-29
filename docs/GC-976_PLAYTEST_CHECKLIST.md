# GC-976 — Planet Evolution Playtest-Checkliste

> **Stand:** Jun 2026  
> **Kontext:** Nach GC-972 (Complete), GC-974A/B, GC-975 (Design), GC-976A (HW-Cap)  
> **Ziel:** Prüfen, ob Planet Evolution als **Expansionssystem** verstanden wird — nicht als zweiter Forschungsbaum.

---

## 1. Testziel

Wir wollen wissen, ob Spieler nach kurzer Spielzeit den Kreislauf verstehen:

```text
Planet-Tech → Sofortbonus + XP → Homeworld-Level → Kolonieslot → Imperium wächst
```

**Erfolg:** Die fünf Kernfragen werden überwiegend positiv beantwortet.  
**Misserfolg:** Feedback lässt sich eindeutig einem Ticket zuordnen (siehe Abschnitt 5).

**Bewusst im Ist-Zustand (vor 976B/C):**

- Dual-Gate: `interstellar_expansion` blockiert Slots noch zusätzlich zu HW-Level.
- Expansion-UX teilweise schwach (HUD, Checklist, PE-Dashboard noch nicht HW-first).
- Nicht jede Planet-Tech hat vollen Sofort-Reward (975C offen).

Playtest-Ergebnisse trennen daher **Produkt-These** von **bekannten UX-Lücken**.

**Ergebnisse dokumentieren in:** [GC-976_PLAYTEST_RESULTS_ALPHA1.md](GC-976_PLAYTEST_RESULTS_ALPHA1.md) (nach Session ausfüllen).

---

## 2. Setup

### Tester

- **5–10 Spieler**, möglichst gemischt (Neu + leicht Fortgeschritten).
- Session: **30–45 Minuten** freies Spielen auf Homeworld, danach **5 Minuten** strukturiertes Feedback.

### Account / Welt

- Frische oder halbfrische Accounts (Homeworld, Planet Evolution sichtbar).
- Sprache: bevorzugt **DE** (Locales für PE/Expansion vorhanden).
- Kein Admin-Cheat außer ggf. Ressourcen-Boost, wenn Queue-Stau den Test blockiert.

### Was Tester tun sollen (frei, nicht vorgeben)

1. Planet Evolution öffnen und mindestens **eine Planet-Tech** starten oder abschließen.
2. **Info-Buttons** (`?`) bei Techs nutzen, wenn neugierig.
3. Bei verfügbarer **Pfadwahl** (Orbital vs. Deep Core) eine Entscheidung treffen.
4. Prüfen, ob klar ist, **wann/wie** eine weitere Kolonie möglich ist (HUD, PE, Command Map).
5. Kurz notieren, wenn sie **nicht wissen**, was als Nächstes sinnvoll ist.

### Was Moderatoren mitnotieren (still)

- Suchverhalten (HUD Planetenlimit, Forschung, Command Map).
- Klicks auf PE-Info, Checklist, Expansion-Sites.
- Verwechslungen: Account-Forschung vs. Planet-Tech vs. Genesis-Ark-Level.
- Ob `interstellar_expansion` als **Slot-Pflicht** wahrgenommen wird.

---

## 3. Fünf Kernfragen an Spieler

Nach dem freien Spielblock — **mündlich oder kurzes Formular**. Antwort: Ja / Teilweise / Nein + 1 Satz Begründung.

| # | Frage | Was wir hören wollen |
|---|--------|----------------------|
| **1** | Verstehst du nach **5 Minuten**, **warum** Planet Evolution existiert? | Expansion / Homeworld stärken / Imperium — nicht „noch ein Forschungsbaum“. |
| **2** | Ist **klar**, wie du einen **neuen Kolonieslot** freischaltest? | Genesis Ark Level, nicht Admin-9, nicht nur Account-Forschung. |
| **3** | Fühlt sich **jede Planet-Tech** nach einer **Belohnung** an? | Sofort-Effekt spürbar; XP allein reicht nicht als Gefühl. |
| **4** | War **Orbital vs. Deep Core** eine **echte Wahl**? | Beide Pfade attraktiv, Trade-offs verständlich, keine Offensichtlich-Falle. |
| **5** | Wusstest du **immer**, was du als **Nächstes** tun sollst? | PE-Dashboard / Next-Action / klare Gates — keine Sackgasse. |

**Zusatz (optional):** „Was war verwirrend?“ — freies Feld, 1–3 Sätze.

---

## 4. Beobachtungsnotizen für Tester / Moderatoren

Während der Session mit ✓ / ✗ / ? markieren:

| Beobachtung | Notiz |
|-------------|--------|
| Sucht Spieler den **Kolonieslot** im HUD (Planeten `X / Y`)? | |
| Klickt er auf **Info-Buttons** (`?`) bei Planet-Techs? | |
| Versteht er **XP** und **Planet-Level** (Homeworld)? | |
| Versteht er **Expansion über Genesis Ark** (nicht Kolonie-Level)? | |
| Wird **`interstellar_expansion`** noch als **Slot-Pflicht** verstanden? | |
| Öffnet er **Command Map** für Expansion? | |
| Nutzt er **„Später verfügbar“** / gesperrte Techs? | |
| Verwechselt er **Account-Forschung** mit **Planet-Tech**? | |

**Rote Flaggen (sofort im Debrief nennen):**

- Raw-Keys oder technische Strings in der UI.
- Queue-Jobs vertikal gestapelt statt kompakt nebeneinander (Regression).
- „9 Planeten“ oder Admin-Cap als Progressionsgefühl.
- Nur Tech-Level-Up als Weg zu Kolonie, ohne HW-Level zu erwähnen.

---

## 5. Auswertung → Ticket-Priorität

| Ergebnis | Wahrscheinliche Ursache | Nächster Schritt |
|----------|-------------------------|------------------|
| **Frage 2** scheitert (Kolonieslot unklar) | Dual-Gate, schwache Expansion-UX, HUD | **GC-976B** (Gate entfernen/umdeuten) + **GC-976C** (HUD, PE, Command Map) |
| **Frage 3** scheitert (Techs fühlen sich leer) | Fehlende Sofort-Rewards | **GC-975C** (gelbe Techs, Reward-Pass) |
| **Frage 4** scheitert (Pfadwahl trivial) | Parity/Copy/Benefits | **GC-974B** nachschärfen oder Choice-UX |
| **Frage 5** scheitert (kein nächster Schritt) | Dashboard / Next-Action | PE-Dashboard, Goal-Copy, Expansion-CTA |
| **Frage 1** scheitert (Zweck unklar) | Gesamt-Onboarding PE | Epic-Review: Hero, Benefits-Popover, erste Session |
| **`interstellar_expansion` als Slot** | Erwartetes Ist bis 976B | **976B** bestätigt priorisieren |

### Auswertungs-Template (pro Session)

```text
Datum:
Tester:
Spielzeit:
Q1 Zweck PE:        [ ] Ja  [ ] Teilweise  [ ] Nein  — 
Q2 Kolonieslot:     [ ] Ja  [ ] Teilweise  [ ] Nein  — 
Q3 Tech-Belohnung:  [ ] Ja  [ ] Teilweise  [ ] Nein  — 
Q4 Pfadwahl:        [ ] Ja  [ ] Teilweise  [ ] Nein  — 
Q5 Nächster Schritt:[ ] Ja  [ ] Teilweise  [ ] Nein  — 
Top-1 Ticket:       
Zitat (optional):   
```

### Entscheidungsregel

- **≥ 4 von 5** Kernfragen „Ja“ oder „Teilweise“ → mit **976B** weitermachen wie geplant.
- **≤ 2** positiv → Playtest wiederholen oder Scope der nächsten Tickets anpassen, bevor große Features.

---

## Referenz

- [GC-976_EXPANSION_PROGRESSION.md](GC-976_EXPANSION_PROGRESSION.md)
- [GC-975_PLANET_EVOLUTION_REWARD_PASS.md](GC-975_PLANET_EVOLUTION_REWARD_PASS.md)
- [GC-974B_DEEP_CORE_PARITY.md](GC-974B_DEEP_CORE_PARITY.md)
