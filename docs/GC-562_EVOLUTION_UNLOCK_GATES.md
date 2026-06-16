# GC-562 — Evolution Unlock Gates

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **S** — nächster Schritt nach GC-563  
> **Status:** ✅ erledigt  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-560 ✅ · GC-563 ✅

Design Manifest: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · Command Map: [GC-563_COMMAND_MAP_MVP.md](GC-563_COMMAND_MAP_MVP.md)

---

## Leitplanke (für Cursor)

> **Planet Evolution ist das Spiel.** Expansion wird durch **Homeworld-Level** freigeschaltet — nicht durch freie Koordinaten oder dekorative Regionen.  
> **`/empire` nicht anfassen.** Klassische **`/galaxy` Systemansicht nicht entfernen.**  
> **Keine Regionen (GC-564)** in diesem Ticket — nur benannte **Expansion Sites** mit Level-Gates.  
> Gates in **`planet_mechanics` / Definitions** — keine parallelen Systeme (GC-000 Regel 15).

---

## Warum jetzt — nicht GC-564

GC-563 liefert **Command Map Foundation** (Darstellung). Ohne Evo-Gates wären Regionen nur Dekoration:

```text
Genesis Core / Outer Rim / Dark Expanse  ← hübsch, aber bedeutungslos
```

Mit GC-562 wird die Karte zum **Fortschrittssystem**:

```text
Planet Evolution Level 5
        ↓
Frontier IX freigeschaltet
        ↓
Command Map zeigt neuen Knoten
```

**Reihenfolge EPIC-15 (aktualisiert):**

```text
GC-560 Identity          ✅
GC-563 Command Map MVP   ✅
GC-562 Evolution Gates   ⬅ dieses Ticket
GC-564 Regions
GC-565 Chokepoints
GC-566 Influence
GC-567 Expansion Sites (Gameplay-Tiefe)
GC-568 Territorial Warfare
```

---

## Product-Rationale — der „Wow"-Moment

### Planet Evolution UI

**Level 4 — Vorschau:**

```text
Nächste Freischaltung:

🔒 Frontier IX
Benötigt Evolution Level 5
```

**Level 5 erreicht:**

```text
✨ Neuer Bereich entdeckt

Frontier IX
```

### Command Map

| Zustand | Darstellung |
|---------|-------------|
| Vor Unlock | `🏛 ───── 🔒` (gesperrter Spoke) |
| Nach Unlock | `🏛 ───── ⛏` (Kolonie / Site sichtbar) |

Der Spieler versteht: **Mein Planet entwickelt sich → mein Imperium wächst.**

---

## Scope (MVP)

### Was rein gehört

1. **Expansion-Site-Definitionen** (statisch, Seed/Constants — keine Migration)
   - Beispiel-Sites: `frontier_ix` (Level 5), später erweiterbar
   - Felder: `site_key`, `label_key`, `required_homeworld_level`, `role_icon`, `layout_slot`

2. **Unlock-Auflösung serverseitig**
   - Gate basiert auf **Genesis-Ark-Level** (`is_homeworld` + `planet_level`)
   - Unlocked Sites → in `planet_mechanics.flags` oder abgeleitet aus Level bei `compile_planet_mechanics`
   - Erweiterung `LEVEL_UNLOCKS` in `constants.py` um Expansion-Tokens **oder** separates `EXPANSION_SITE_UNLOCKS` Dict im Owner-Modul

3. **Command Map Integration**
   - Gesperrte Sites als `🔒`-Knoten auf der Karte (layout_slot vorgegeben)
   - Freigeschaltete Sites als normale/expansion-Knoten
   - Hub→Site-Kante (locked = gestrichelt/grau, unlocked = aktiv)

4. **Planet Evolution Dashboard**
   - „Nächste Freischaltung" in Progression (erweitert `_progression_milestones` oder Expansion-Teaser)
   - Unlock-Event/Toast optional minimal (Copy only)

### Was nicht rein gehört

| Verboten | Ticket |
|----------|--------|
| Regionen-Polygone / `[G:S]`-Mapping | GC-564 |
| Kolonisierung blockieren/enforcen | GC-567 |
| Evo-Gates auf Nicht-Homeworld | — |
| `/empire` | — |
| Neue DB-Tabellen | — |
| Fleet/Galaxy-Koordinatenmodell ändern | — |

---

## Technische Leitplanken

- **Owner:** `game/planet_evolution/expansion_gates.py` (neu) — Site-Defs, Unlock-Check, Payload für Map + Dashboard
- **Reuse:** `build_command_map_payload()` erweitern — locked + unlocked nodes
- **Reuse:** `LEVEL_UNLOCKS` / `planet_mechanics` Pattern aus [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md)
- **Homeworld-Level:** `level_progress(homeworld_id)` — nicht context planet, **immer Homeworld** für Expansion-Gates
- **Keine Frontend-Gate-Logik** (Regel 16)

---

## API / Payload-Erweiterung

```python
# expansion_gates.py
EXPANSION_SITES = {
    "frontier_ix": {
        "label_key": "expansion_site_frontier_ix",
        "required_homeworld_level": 5,
        "layout_slot": "north",
        "role_icon": "🌌",
    },
    # Illustrativ — Balancing später
}

def list_expansion_sites_for_player(player_id, conn) -> list[dict]:
    """Each site: site_key, label_key, is_unlocked, required_level, layout_slot, ..."""

# command_map payload erweitert:
{
    "nodes": [...],  # bestehend + expansion sites (locked/unlocked)
    "edges": [...],
    "expansion": {
        "homeworld_level": 4,
        "next_unlock": {"site_key": "frontier_ix", "required_level": 5, "label_key": "..."},
    },
}
```

---

## Betroffene Dateien (max. ~5 Kern)

- `game/planet_evolution/expansion_gates.py` — **neu**
- `game/planet_evolution/command_map.py` — locked/unlocked expansion nodes
- `game/planet_evolution/dashboard.py` — next unlock teaser (minimal)
- `templates/partials/galaxy_command_map_panel.html` — locked node styling
- `static/style.css` — `.galaxy-command-map-node--locked`
- `locales/de.json`, `locales/en.json` — expansion site keys
- `tests/test_expansion_gates.py` — **neu**

**Nicht bearbeiten:** `templates/empire.html`, `game/empire_page.py`, klassische Galaxy-Slots, `game/galaxy.py`

---

## Implementierungsreihenfolge

```text
1. expansion_gates.py — Definitionen + is_unlocked(homeworld_level)
2. command_map.py — locked/unlocked nodes + edges
3. dashboard.py — next unlock in progression payload
4. Template + CSS — 🔒 Knoten
5. Tests
```

---

## Akzeptanzkriterien

- [ ] Homeworld Level 4: Command Map zeigt `🔒 Frontier IX` (oder nächste Site) als gesperrten Spoke
- [ ] Homeworld Level ≥ 5: Site erscheint freigeschaltet (kein 🔒)
- [ ] Planet Evolution zeigt „Nächste Freischaltung" mit Level-Anforderung
- [ ] Unlock-Logik **serverseitig** — pytest ohne UI
- [ ] `/empire` und klassische `/galaxy` unverändert
- [ ] Keine Regionen, keine neue Migration
- [ ] `pytest tests/test_expansion_gates.py tests/test_command_map.py -v` grün

---

## Referenz-Docs

- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — „Evolution unlockt Expansion"
- [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) — Level, mechanics, dashboard
- [GC-563_COMMAND_MAP_MVP.md](GC-563_COMMAND_MAP_MVP.md) — Graph-Basis
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regeln 15–17

---

## Ausgabe (nach Abschluss)

### Root Cause

### Changed Files

### Tests

### Ergebnis
