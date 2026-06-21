# GC-700A — Battle Reports v2

> Epic: GC-700 Combat Polish — **Presentation only**  
> Voraussetzung: Combat Resolver ✅ ([COMBAT_SYSTEM.md](COMBAT_SYSTEM.md), [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) § GC-700)  
> **Nicht:** Combat-Math, Resolver, Fleet-Tick, DB-Migrationen, Metadata-Schema-Änderungen am Backend

---

## Problem

Combat Reports sind **funktional vorhanden**, wirken aber noch nicht wie ein PvP-Highlight. Spieler erinnern sich an Siege und Niederlagen — nicht an Tabellen mit Zahlen.

Die Combat-Engine ist fertig. Dieses Ticket ist **ausschließlich** ein Presentation-/UX-Pass auf bestehende Inbox- und Modal-Renderer.

---

## Ziel

Bestehende Kampfberichte visuell stärker machen:

- klarer Sieger / Verlierer (Hero-Zeile)
- Attacker vs. Defender als nebeneinander stehende Cards
- Verluste übersichtlich (Unit-Loss-Chips)
- Loot prominent
- Debris prominent **wenn Metadata vorhanden**
- Research-/Techboni sauber integriert (`renderCombatResearchPanel` behalten)
- **Keine** Änderung am Combat Resolver oder an Battle-Ergebnissen

---

## Ist-Zustand (Code)

| Baustein | Status | Ort |
|----------|--------|-----|
| Report-Metadata (Server) | ✅ | `game/combat.py` — `build_combat_report()` → `player_messages.metadata` |
| Inbox + Modal Renderer | ✅ | `static/js/messages.js` — `renderCombatReportFull`, `renderCombatReportTeaser` |
| Modal Shell (PJAX-persistent) | ✅ | `templates/partials/combat_report_modal.html` |
| Research-Panel | ✅ | `renderCombatResearchPanel()` in `messages.js` |
| Unit-Chips / Loss-Split | ✅ | `renderCombatUnitGrid`, `renderCombatLossesSplit` |
| Loot-Chips | ✅ | `renderCombatLootChips` |
| Round-Log (`<details>`) | ✅ | `meta.rounds[]` |
| Debris in Metadata | ❌ | **Nicht** in `build_combat_report()` — siehe § Debris |

### Metadata-Felder (read-only für dieses Ticket)

Aus `build_combat_report()` — **nicht erweitern** in GC-700A:

| Feld | Typ | UI-Nutzung |
|------|-----|------------|
| `report_version` | int | optional Badge |
| `origin_coords`, `target_coords` | str | Hero / Route |
| `origin_planet_name`, `target_planet_name` | str | Subtitles |
| `attacker_id`, `defender_id` | int | Perspective |
| `attacker_name`, `defender_name` | str | Cards / VS |
| `attacking_ships`, `defending_ships` | map | Force grids |
| `defending_defense` | map | Defender structures |
| `result`, `winner` | str | Outcome (`attacker` / `defender` / `draw`) |
| `attacker_losses`, `defender_losses` | map | Loss columns |
| `return_ships` | map | Return panel |
| `loot` | map | Loot panel |
| `rounds_fought`, `rounds` | int / list | Stats + round log |
| `attacker_combat_research`, `defender_combat_research` | list | Research panel |
| `perspective`, `dev_simulated`, `fleet_id` | misc | optional |

**Debris:** Trümmer werden serverseitig in `debris_fields` persistiert, sind aber **aktuell nicht** im Report-Metadata enthalten. GC-700A rendert ein Debris-Panel **nur**, wenn zukünftig `meta.debris` (oder `meta.debris_field`) mit `{ metal, crystal }` vorhanden ist — sonst Panel weglassen. Backend-Ergänzung → separates Ticket (z. B. GC-700D), **nicht** GC-700A.

---

## Architektur (GC-000)

| Regel | Umsetzung |
|-------|-----------|
| Kein Frontend-Combat-Math | Nur Anzeige von Server-Metadata; keine Debris-/Loot-Berechnung im Client |
| Kein Resolver-Touch | `game/combat.py`, `game/combat_models.py`, `game/fleet.py` **tabu** |
| Shell / PJAX | Modal bleibt in `base.html`; Inbox öffnet Report ohne `location.reload()` |
| Duplicate Math (Regel 16) | Keine Formeln für Verluste, Loot, Debris — nur `formatInt` / Chips |
| Owner | Presentation = `static/js/messages.js` + `static/style.css` |

Referenz: [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §3, [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md), [STATE_AJAX.md](STATE_AJAX.md).

---

## Ziel-Layout (Modal / Inbox Full Report)

```text
┌─────────────────────────────────────────────────────────────┐
│  🏆 SIEG / NIEDERLAGE          [Attacker] vs [Defender]     │
│  [G:S:P] → [G:S:P] · Planetname                             │
├─────────────────────────────────────────────────────────────┤
│  Runden │ ATK Verluste │ DEF Verluste │ Beute (Summe)       │
├──────────────────────────┬──────────────────────────────────┤
│  ANGREIFER               │  VERTEIDIGER                     │
│  Schiffe + Chips         │  Flotte + Verteidigung + Chips   │
├──────────────────────────┴──────────────────────────────────┤
│  VERLUSTE (gesamt)     ATK-Spalte  │  DEF-Spalte             │
├─────────────────────────────────────────────────────────────┤
│  BEUTE (wenn loot > 0)     Ferronit · Crytite · …           │
├─────────────────────────────────────────────────────────────┤
│  TRÜMMER (nur wenn meta.debris)  ☄ Metal · Crystal         │
├─────────────────────────────────────────────────────────────┤
│  FORSCHUNGS-BONI (renderCombatResearchPanel — integriert)   │
├─────────────────────────────────────────────────────────────┤
│  RUNDEN-LOG (details, bestehend — optisch anpassen)         │
└─────────────────────────────────────────────────────────────┘
```

Mobile ≤390px: Hero → Stats → Cards **gestapelt** (Attacker, dann Defender) → Panels full-width → kein horizontaler Page-Overflow.

---

## Anforderungen

1. **Bestehende Combat-Metadata** weiterverwenden — kein neues API, kein Backend-Patch.
2. **`renderCombatResearchPanel`** nicht entfernen; optisch in Genesis-Panel-Stil einbinden (nicht isoliert „hängen“).
3. **Report-Modal / Full Report** im Genesis-Stil:
   - Hero-Zeile mit Outcome (`combatResultVisual`, `combatResultLabel`)
   - Attacker / Defender nebeneinander (Desktop), gestapelt (Mobile)
   - Unit-Loss-Chips (bestehende Chip-Renderer)
   - Loot-Panel (prominent wenn `lootTotal > 0`)
   - Debris-Panel (nur wenn `meta.debris` / `meta.debris_field` mit Werten)
   - Research-Bonus-Panel
4. **Kein Frontend-Combat-Math** — Verboten: Debris aus Losses ableiten, Sieg neu berechnen.
5. **Defensive Rendering** — fehlende/leere Meta-Felder → leere States / Panel weglassen, kein JS-Throw.
6. **Alte Reports** — niedrigere `report_version` oder fehlende optionale Felder müssen ohne Crash rendern.
7. **Teaser** (`renderCombatReportTeaser`) optional leicht anpassen (Outcome + VS + Loot-Hint), ohne Inbox-Regression.
8. **Mobile** 390px ohne horizontalen Overflow im Report-Container.
9. **PJAX** — Modal-Cleanup unverändert; `cacheReportModalElements()` weiter nutzbar.

---

## Betroffene Dateien

| Datei | Änderung |
|-------|----------|
| `static/js/messages.js` | Layout `renderCombatReportFull` / ggf. Teaser; ggf. `renderCombatDebrisPanel()` (read meta only) |
| `static/style.css` | Genesis-Glow, Grid, Mobile, Loot/Debris-Highlight |
| `templates/partials/combat_report_modal.html` | Nur wenn Shell-Struktur nötig (minimal) |
| `locales/de.json`, `locales/en.json` | Neue UI-Labels (Debris-Section, Hero-Texte) |

### Nicht bearbeiten

- `game/combat.py`
- `game/fleet.py`
- `game/combat_models.py`
- `game/messages.py` (außer zwingender Regression — **vermeiden**)
- Datenbank / `migrations/*`
- `templates/messages.html` (nur wenn unvermeidbar — **vermeiden**)

---

## Akzeptanzkriterien

- [ ] Alte Combat Reports rendern ohne Crash.
- [ ] Reports mit Loot zeigen Loot-Panel (hervorgehoben wenn > 0).
- [ ] Reports **ohne** Loot zeigen sauberen Empty-State (kein kaputtes Panel).
- [ ] Debris-Panel erscheint **nur**, wenn Metadata-Feld vorhanden; sonst kein Panel / kein Platzhalter-Fehler.
- [ ] Research-Boni werden angezeigt, wenn `attacker_combat_research` / `defender_combat_research` vorhanden.
- [ ] Sieger/Verlierer visuell klar (Hero + Badge-Farben).
- [ ] Attacker/Defender-Cards nebeneinander (Desktop), gestapelt (Mobile).
- [ ] Mobile 390px ohne horizontalen Overflow im Report.
- [ ] Keine Änderung an Battle-Ergebnissen (kein Backend-Diff in Combat/Fleet).
- [ ] PJAX: Report aus Inbox öffnen/schließen ohne Full-Reload.
- [ ] Tests grün:

```bash
python -m pytest tests/test_combat.py tests/test_messages.py -v
```

---

## Tests & Manuelle QA

**Automatisch:** `test_combat.py` (Resolver unberührt), `test_messages.py` (Inbox/Metadata-Pfade).

**Manuell:**

1. Inbox → Combat-Report mit Loot öffnen (Modal + Inline).
2. Report ohne Loot (Draw / leere Beute).
3. Alter Report (falls in DB) — kein JS-Error.
4. Dev-Sim-Report (`dev_simulated`) falls verfügbar.
5. Mobile 390px — Modal scroll, kein Overflow.
6. PJAX: Overview → Messages → Report → Galaxy → zurück Messages — Modal-State ok.

---

## Out of Scope (Follow-up)

| Ticket | Inhalt |
|--------|--------|
| **GC-700B** | Hall of Fame v2 — Kategorien, historische Kämpfe |
| **GC-700C** | `/pvp` — Aggregation, Tabs |
| **GC-700D** | Debris in Metadata + Galaxy Recycler-CTA + HoF-Debris |
| **GC-701** | Battle Timeline — Runden-Animation, Verlustgraph |

Debris-Werte im Report erfordern **Backend-Metadata** → nicht GC-700A.

---

## Referenz-Docs

- [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md)
- [FLEET_SYSTEM.md](FLEET_SYSTEM.md)
- [STATE_AJAX.md](STATE_AJAX.md)
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md)

---

## Ausgabe nach Abschluss

```
Root Cause
Changed Files
Tests
Ergebnis
Manuelle QA
```
