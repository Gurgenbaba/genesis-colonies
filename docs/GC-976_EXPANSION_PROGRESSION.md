# GC-976 — Expansion Progression (Planet Evolution → Imperium)

> **Epic:** EPIC-05 Planet Evolution × EPIC-15 Imperium & Expansion  
> **Status:** 📋 Design-Spec — **keine Implementierung in diesem Ticket**  
> **Stand:** Jun 2026  
> **Voraussetzung:** GC-972–974B ✅, GC-975 (Philosophie) ✅

---

## Produkt-These

Planet Evolution existiert primär, damit der Spieler **sein Imperium ausdehnt** — nicht als zweiter Forschungsbaum.

| Schicht | Rolle |
|---------|--------|
| **Planet-Techs** | Kurzfristige Werkzeuge (Sofort-Bonus + XP) — [GC-975](GC-975_PLANET_EVOLUTION_REWARD_PASS.md) |
| **Homeworld Planet-Level** | Langfristiger Imperiums-Reward: **neue Kolonien / Expansion** |
| **Account-Forschung** | Imperiumsweit, **nicht** primärer Kolonie-Slot-Treiber (Product-Ziel GC-976) |

**Ziel-Schleife (geschlossen):**

```text
Planet-Tech (Homeworld)
        │
        ▼
Sofort stärker + Planet-XP
        │
        ▼
Homeworld-Entwicklungsstufe steigt
        │
        ▼
Neuer Expansionsslot freigeschaltet
        │
        ▼
Neue Region / Site auf Command Map
        │
        ▼
Neue Kolonie (Seed Ark)
        │
        ▼
Planet Evolution auf der Kolonie (Charakter-Welt)
        │
        ▼
Mehr Produktion fürs Imperium
```

---

## Ist-Zustand (ehrlich)

Expansion ist **nicht** bei Null — aber die **sichtbare Progressionsquelle** ist noch fragmentiert.

### Bereits implementiert

| Mechanismus | Ort | Verhalten |
|-----------|-----|-----------|
| **Homeworld-Level** | `expansion_gates.get_homeworld_level()` | Liest `planet_level` der **Genesis Ark**, nicht der aktiven Kolonie |
| **Expansion-Sites** | `EXPANSION_SITES` | Sites bei HW-L5 / 10 / 15 / 20 / 25 auf Command Map |
| **Slot-Gates** | `EXPANSION_SLOT_GATES` in `expansion_protocol.py` | Nächste Kolonie braucht HW-L5+Tech1, L10+Tech2, … L30+Tech6 |
| **Dual-Gate** | `evaluate_expansion_gates()` | **Beides:** Homeworld-Level **und** Account-Tech `interstellar_expansion` |
| **Admin-Ceiling** | `get_max_planets_per_player()` | Statisch aus `game_settings.max_colonies_per_player` (Default **9**) — **nicht** aus PE |
| **Colonize-Flow** | `can_found_expansion_world()` | Gates → dann `total < admin_ceiling` |

### EXPANSION_SLOT_GATES (heute)

| Kolonie # | Homeworld-Level | Interstellar Expansion (Account) |
|-----------|----------------:|----------------------------------|
| 1 | 5 | 1 |
| 2 | 10 | 2 |
| 3 | 15 | 3 |
| 4 | 20 | 4 |
| 5 | 25 | 5 |
| 6 | 30 | 6 |

Sites auf der Command Map folgen **dieselben HW-Schwellen** (L5, L10, …).

### Die eigentliche Lücke (GC-976)

1. **Admin-Cap (9)** wirkt wie das „echte“ Limit — entkoppelt von Homeworld-Progression in der Spielerwahrnehmung.
2. **Dual-Gate:** Account-Forschung `interstellar_expansion` ist **gleichwertiger** Slot-Treiber — widerspricht der Vision „PE steuert Expansion“.
3. **UX:** `get_expansion_limit_block()` liefert `"max": None` — kein klares „3 / 6 Kolonien freigeschaltet“ aus Homeworld-Level.
4. **Planet-Evolution-Dashboard** kommuniziert Level-Ups nicht als **Imperiums-Expansion** (975 Goal-Copy erwähnt Expansion abstrakt).

→ Technisch **teilweise** da; produktisch **noch nicht der eine Kreislauf**.

---

## Kanonische Designregel (GC-976)

> **Die Anzahl erlaubter Kolonien (Expansion-Slots) leitet sich aus der Homeworld-Entwicklungsstufe ab — nicht aus einem statischen Admin-Wert und nicht primär aus Account-Forschung.**

### Auslegung

| Frage | GC-976-Antwort |
|-------|----------------|
| Was zählt? | Nur **Homeworld** `planet_level` (Genesis Ark) |
| Was zählt nicht als Slot-Quelle? | `max_colonies_per_player` als Gameplay-Cap (wird Safety-Ceiling) |
| Account `interstellar_expansion`? | **Product-Entscheidung** — siehe Varianten unten |
| Grandfathering? | Spieler mit mehr Welten als neues Limit: **Welten behalten**, keine neuen bis Gate erfüllt |
| Kolonie-Level? | Jede Kolonie hat **eigene** PE — steuert **nicht** Imperiums-Slots |

---

## Varianten

### Variante A — PE-only Slots (empfohlen, Vision-pur)

- `max_allowed_colonies(hw_level)` = aus `EXPANSION_SLOT_GATES` / abgeleitete Formel
- `interstellar_expansion` entfällt als **Gate** für neue Kolonien (Tech bleibt für Flugreichweite / andere Boni oder wird umgedeutet)
- Admin-Ceiling = `max(derived_max + buffer, 50)` oder fest `MAX_PLANETS_PER_PLAYER_MAX` nur als Exploit-Schutz

**Vorteile:** Klarer Kreislauf PE → Expansion; eine Progressionsquelle.  
**Nachteile:** Account-Forschungs-Linie verliert Kolonie-Gate-Rolle; Save-Migration / Copy-Anpassung.

### Variante B — PE primary, Account secondary (Kompromiss)

- Slot frei wenn `hw_level >= gate` **ODER** legacy `interstellar_expansion >= gate` (Übergang)
- Neue Spieler: nur PE
- Nach 1–2 Releases: Account-Gate entfernen

**Vorteile:** Sanfte Migration.  
**Nachteile:** Zwei Systeme temporär — verwirrend wenn nicht klar kommuniziert.

### Variante C — Status quo + UX only

- Dual-Gate bleibt
- Nur Admin-Cap durch `f(hw_level)` ersetzen + HUD zeigt Slots

**Vorteile:** Minimaler Code.  
**Nachteile:** Vision „PE steuert Expansion“ nur halb erfüllt.

**Empfehlung:** **Variante A** für neues Design; Grandfathering + ehrliche Copy für `interstellar_expansion` (Reichweite, Missionen, nicht „Kolonie #3“).

---

## Ziel-Mechanik (Variante A — Spec)

### `expansion_slots_unlocked(homeworld_level) -> int`

Anzahl **zusätzlicher** Kolonien (ohne Homeworld), die HW-Level erlaubt:

| HW-Level | Kolonien erlaubt | Site (Map) |
|----------|------------------|------------|
| 1–4 | 0 | — |
| 5–9 | 1 | `frontier_ix` |
| 10–14 | 2 | `ancient_relay` |
| 15–19 | 3 | `archive_nexus` |
| 20–24 | 4 | `abyss_gate` |
| 25–29 | 5 | `void_frontier` |
| 30 | 6 | (Cap aus Slot-Tabelle) |

Entspricht **bestehenden** `EXPANSION_SLOT_GATES` HW-Spalte — Sites bleiben aligned.

### Effektives Limit

```text
effective_max_worlds = 1 + expansion_slots_unlocked(hw_level)
can_found = owned_worlds < effective_max_worlds
           AND hw_level >= gate_for_next_colony
           AND expansion_site_unlocked (falls Site-Pfad)
```

`get_max_planets_per_player()` → **nur** `min(effective_max, ADMIN_ABSOLUTE_MAX)` oder deprecated für Gameplay.

### UX (Pflicht)

| Ort | Inhalt |
|-----|--------|
| Homeworld Planet-Evolution | „Nächste Kolonie bei Entwicklungsstufe X“ |
| `get_expansion_limit_block` | `max_colonies_unlocked`, `next_unlock_level`, `can_expand` |
| Command Map | Site gesperrt → „Genesis Ark Stufe X erforderlich“ |
| Game-State HUD | `3/4 Kolonien` (aus HW, nicht Admin-9) |

---

## Vollständige Touchpoint-Inventur (Code)

Alle Stellen, die heute das **klassische Kolonielimit** oder **Dual-Gate** nutzen:

### Kanonische Cap-Quelle (Ziel: eine Pipeline)

```text
get_expansion_slots_unlocked(hw_level)     ← neu (976A)
        ↓
can_found_expansion_world()                ← expansion_protocol.py
        ↓
check_planet_cap_available()             ← logic.py (Adapter, bleibt)
        ↓
colonize_planet() / fleet colonize / world_colonization
```

### Server — Limit & Validierung

| Datei | Symbol / Stelle | Rolle heute | Migration (976) |
|-------|-----------------|-------------|-----------------|
| `game/logic.py` | `get_max_planets_per_player()` | Admin-Setting `max_colonies_per_player` (Default 9), Hard-Ceiling | Nur **Safety** (`min(derived, admin, 50)`); Docstring bereits „Deferred PE“ |
| `game/logic.py` | `check_planet_cap_available()` | Delegiert an `can_found_expansion_world` | Unverändert als Adapter |
| `game/logic.py` | `get_planet_limit_block()` | Delegiert an `get_expansion_limit_block` | Payload erweitern (976C) |
| `game/planet_evolution/expansion_protocol.py` | `EXPANSION_SLOT_GATES` | HW + `interstellar_expansion` pro Slot | HW-only (976A); Tech-Spalte entfernen oder ignorieren |
| `game/planet_evolution/expansion_protocol.py` | `WORLD_TYPE_GATES` | Zusätzliche HW+Tech pro Welttyp | HW-only für Slot; Tech ggf. Reichweite (976B) |
| `game/planet_evolution/expansion_protocol.py` | `evaluate_expansion_gates()` | Dual-Gate | Tech-Check entfernen (976B) |
| `game/planet_evolution/expansion_protocol.py` | `can_found_expansion_world()` | Gates + `total < admin_ceiling` | `total < effective_max` aus HW (976A) |
| `game/planet_evolution/expansion_protocol.py` | `get_expansion_limit_block()` | `max: None`, `admin_ceiling`, Dual-Gate-Felder | `max` = unlocked slots; `next_unlock_level` (976C) |
| `game/planet_evolution/expansion_protocol.py` | `build_expansion_launch_checklist()` | Checklist inkl. `interstellar_expansion` Item | Tech-Item umdeuten/entfernen (976B/C) |
| `game/planet_evolution/expansion_protocol.py` | `interstellar_expansion_reach_label()` | Forschungs-UI Reichweiten-Labels | Behalten für Reichweite, nicht Slots |
| `game/planet_evolution/service.py` | `colonize_planet()` | Legacy-Pfad: direkt `get_max_planets_per_player`; Expansion-Pfad: `check_planet_cap_available` | Beide Pfade → kanonische Cap (976A) |
| `game/planet_evolution/world_colonization.py` | `can_player_found_expansion_world()` | `check_planet_cap_available` | Automatisch via Adapter |
| `game/planet_evolution/world_colonization.py` | `validate_world_colonize_target()` | Zielvalidierung vor Fleet | Gate-Copy anpassen falls Tech-Fehler weg |
| `game/fleet.py` | Colonize-Fail-Mapping | `max_colonies*` → `expansion_admin_ceiling_reached` | Neuer Reason `expansion_slot_cap_reached` o.ä. (976D) |
| `game/planet_evolution/expansion_gates.py` | `EXPANSION_SITES`, `get_homeworld_level()` | Site-Freischaltung nur HW | Bereits aligned — Copy only |
| `game/planet_evolution/expansion_gates.py` | Dashboard unlock block | Nutzt `get_expansion_limit_block` | An neues `max` anbinden |
| `game/planet_evolution/dashboard.py` | `_next_action_cta()` | Priorität: `interstellar_expansion` vor HW-Level | HW-first; Tech-CTA entfernen (976C) |
| `game/research.py` | `interstellar_expansion` Tech-Def | Account-Forschung | Beschreibung: Reichweite/Missionen, nicht Kolonie-Slots (976B) |
| `game/admin_balance.py` | `max_colonies_per_player` | Admin 1–50 | Label/Help: „Safety ceiling“, nicht Gameplay-Limit |
| `game/empire_page.py` | `colony_limit` in API | `get_planet_limit_block` | Anzeige aus neuem Block |
| `app.py` | `header_planet_limit`, `/api/game-state` `planet_limit` | Server-Payload für HUD | `max` aus HW statt `GAME_SETTINGS` |

### Client & Templates

| Datei | Stelle | Rolle heute | Migration |
|-------|--------|-------------|-----------|
| `templates/base.html` | `pl_max = max_colonies_per_player\|default(9)` | SSR-Fallback HUD | `HEADER_PLANET_LIMIT.max` aus Block |
| `templates/partials/header_planet_switcher.html` | `hp_pl_max` Fallback Admin-9 | Planeten `X / Y` | `Y` = `planet_limit.max` (unlocked) |
| `static/main.js` | `patchHeaderPlanetLimitFromState()` | Liest `block.max`; Title bei `gate_reason` | `max` immer gesetzt; Copy-Keys |
| `templates/admin_panel.html` | Admin-Hint | „Forschung erhöht Limit nicht“ | Text: Safety-Ceiling |
| `locales/*.json` | `expansion_gate_*`, `header_planet_limit`, PE-CTAs | Dual-Gate-Copy | HW als primäre Quelle (9 Sprachen) |

### Tests (Pflicht-Updates 976D)

| Datei | Abdeckung |
|-------|-----------|
| `tests/test_planet_cap_hard.py` | Admin-Ceiling, Grandfathering, `get_planet_limit_block` |
| `tests/test_expansion_protocol.py` | Gate-Matrix, Tech-Gate, Admin-Ceiling |
| `tests/test_expansion_gates.py` | Site-Freischaltung HW |
| `tests/test_header_planet_switcher.py` | `planet_limit` in game-state |
| `tests/test_game_state_live.py` | Live `planet_limit` Payload |

### Docs (nach Implementierung)

- `docs/EXPANSION_PROTOCOL.md` — Dual-Gate → HW-primary
- `docs/PLANET_EVOLUTION.md` § Expansion
- `docs/CORE_ARCHITECTURE.md` §17 Owner bestätigen (expansion_protocol bleibt Owner)

**Kein neues Parallel-System** — `EXPANSION_SLOT_GATES` konsolidieren, nicht zweites Cap-Modul (GC-000 §15).

---

## Migrationsplan (Schrittfolge)

### Phase 0 — Design-Freeze (dieses Ticket)

- Variante **A** (PE-only Slots) bestätigt
- Touchpoint-Inventur ✅ (oben)
- UI-Design-Regel: `.cursor/rules/genesis-colonies-ui-design.mdc`

### Phase 976A — Slot-Logik (Owner: `expansion_protocol.py`)

1. `expansion_slots_unlocked(hw_level) -> int` aus `EXPANSION_SLOT_GATES` HW-Spalte ableiten.
2. `effective_max_worlds(player_id)` = `1 + expansion_slots_unlocked(hw_level)` (Homeworld zählt mit).
3. `can_found_expansion_world`: ersetze `total < admin_ceiling` durch `total < effective_max_worlds` **und** per-Slot-Gate (`hw_level >= gate_for_next`).
4. Grandfathering: `owned > effective_max` → Welten behalten, `can_found = false`.
5. `get_max_planets_per_player(conn)` → `min(effective_max_for_player?, ADMIN_ABSOLUTE_MAX)` nur wenn player_id bekannt; sonst Safety-Constant für Admin-Panel.

### Phase 976B — Account-Gate (`interstellar_expansion`)

1. `evaluate_expansion_gates`: Tech-Check entfernen; `WORLD_TYPE_GATES` Tech-Spalte ignorieren oder auf Reichweite verschieben.
2. `build_expansion_launch_checklist`: Item `interstellar_expansion` entfernen oder als optionaler Reichweiten-Hinweis.
3. `game/research.py` + Locales: Tech-Beschreibung ≠ Kolonie-Slots.
4. Bestehende Saves: Spieler mit Tech aber ohne HW — **kein** neuer Slot (Produktentscheidung Variante A).

### Phase 976C — UX / State

1. `get_expansion_limit_block`: `max` = `effective_max_worlds`, `expansion_slots_unlocked`, `next_unlock_homeworld_level`, `owned_worlds`.
2. `templates/base.html` + `header_planet_switcher.html`: kein `default(9)` mehr als Gameplay-Anzeige.
3. PE-Dashboard: Next-Action HW-Level-Up als Imperiums-Expansion; Command-Map-Copy.
4. `patchHeaderPlanetLimitFromState`: `3 / 4` aus Server, Tooltip mit nächstem Gate.

### Phase 976D — Tests & Locales

1. Slot-Matrix HW 5/10/15/…
2. Grandfathering over-cap
3. Tech-only Spieler blockiert
4. Fleet + `colonize_planet` gleicher Reason-Code
5. Alle 9 Locale-Dateien

---

## Betroffene Module (Kurz)

| Owner | Änderung |
|-------|----------|
| `game/planet_evolution/expansion_protocol.py` | Slot-Limit aus HW; Account-Gate entfernen |
| `game/logic.py` | `get_max_planets_per_player` → Safety only |
| `game/planet_evolution/expansion_gates.py` | Sites unverändert (bereits HW) |
| `game/planet_evolution/dashboard.py` | Next-action / Goal: Expansion bei Level-Up |
| `game/planet_evolution/service.py` | `colonize_planet` / Cap-Check vereinheitlichen |
| `locales/*` | Keine „9 Planeten“-Caps; Entwicklungsstufe als Gate |
| `tests/test_expansion_protocol.py`, `test_planet_cap_hard.py`, `test_expansion_gates.py` | Slot-Matrix, Grandfathering |

---

## Grandfathering & Saves

| Situation | Verhalten |
|-----------|-----------|
| Spieler mit 5 Kolonien, HW-L8 nach Regel (max 1) | 5 Welten **bleiben**; `can_found` = false bis L10 |
| Admin hatte `max_colonies=9` | Gameplay ignoriert für Anzeige; Safety max 50 |
| `interstellar_expansion` L6, HW-L3 | Nach Variante A: **kein** neuer Slot bis HW-L5 |

Tests: explizit „over cap legacy“ + „cannot found but keep worlds“.

---

## Abgrenzung

### In Scope GC-976

- Kolonie-Limit ↔ Homeworld-Level (Gameplay)
- Expansion-UX / game-state / PE-Dashboard-Hinweis
- Tests + Locales + Docs (`EXPANSION_PROTOCOL.md`, `PLANET_EVOLUTION.md` §Expansion)

### Out of Scope

- Neue Planet-Techs (→ GC-975C)
- Conversion / Experimental (→ GC-973 / 972E)
- World-Map-Redesign jenseits Copy/Gates
- Kolonie-Level beeinflusst Imperiums-Slots (bewusst nein)

---

## Empfohlene Sub-Tickets

| Ticket | Inhalt |
|--------|--------|
| **976A** | `expansion_slots_unlocked(hw_level)` + `can_found` / Cap-Logik |
| **976B** | Account-Gate `interstellar_expansion` entfernen oder umdeuten + Migration-Copy |
| **976C** | UX: `expansion_limit_block`, PE Hero, Command Map |
| **976D** | Tests + Grandfathering + Locales (9 Sprachen) |

**Reihenfolge nach GC-975:** **976 vor 975C** — erst Imperiums-Kreislauf schließen, dann Tech-Feintuning.

---

## Akzeptanzkriterien (Implementierung)

1. Spieler sieht **max Kolonien aus Homeworld-Level**, nicht aus Admin-9.
2. HW-Level-Up auf Stufe 5/10/15/… schaltet nächsten Slot **messbar** frei (API + UI).
3. Bestehende Welten werden bei Regelwechsel **nicht** gelöscht.
4. `colonize_planet` / Fleet-colonize nutzen dieselbe kanonische Cap-Quelle.
5. Tests decken Slot-Matrix, Grandfathering, Site-Gate ab.

---

## Referenz

- [GC-975_PLANET_EVOLUTION_REWARD_PASS.md](GC-975_PLANET_EVOLUTION_REWARD_PASS.md)
- [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md)
- [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md)
- `game/planet_evolution/expansion_protocol.py` — `EXPANSION_SLOT_GATES`
- `game/planet_evolution/expansion_gates.py` — `EXPANSION_SITES`
