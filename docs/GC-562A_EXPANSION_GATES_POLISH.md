# GC-562A — Expansion Gates Polish

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** S — Stabilisierung nach GC-562  
> **Status:** ✅ erledigt  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-562 ✅

---

## Scope

1. Locked Expansion Nodes optisch klarer (gestrichelt, Lock-Ring, gedimmt)
2. Unlocked Site mit **„Neu entdeckt“** wenn `homeworld_level == required_level`
3. Planet Evolution: eigenes Panel **Imperiums-Expansion** (prominent nach Hero)
4. Kolonie aktiv: Hinweis **„Expansion basiert auf Genesis Ark“**
5. Tests: Expansion-Nodes ohne `planet_id`, Genesis-Ark-Hint, Newly-Discovered

**Nicht in Scope:** Regionen (GC-564), Pan/Zoom (GC-563B), fremde Spieler auf der Map.

---

## Akzeptanz

- [x] Level 4: 🔒 Frontier IX deutlich als gesperrt
- [x] Level 5: Frontier IX mit „Neu entdeckt“-Badge (Map + PE)
- [x] PE: Panel `#pe-section-expansion-gate` sichtbar
- [x] Kolonie-PE: Genesis-Ark-Hinweis + nächstes Gate
- [x] `pytest tests/test_expansion_gates.py tests/test_command_map.py -v` grün

---

## Root Cause

GC-562 lieferte die Mechanik; UX war noch zu dezent (Teaser in „Nächste Evolution“, locked nodes schwach).

## Changed Files

- `game/planet_evolution/expansion_gates.py`
- `game/planet_evolution/dashboard.py`
- `templates/planet_evolution.html`
- `templates/partials/galaxy_command_map_panel.html`
- `static/style.css`
- `locales/de.json`, `locales/en.json`
- `tests/test_expansion_gates.py`

## Tests

`pytest tests/test_expansion_gates.py tests/test_command_map.py tests/test_empire_identity.py -v`

## Ergebnis

Polish schließt den sichtbaren Loop: Evolution → Gate-Panel → Unlock → Command Map wächst mit „Neu entdeckt“.
