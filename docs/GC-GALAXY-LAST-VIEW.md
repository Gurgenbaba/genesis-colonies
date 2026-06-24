# GC-GALAXY-LAST-VIEW — Persist galaxy view tab + active-planet coords

**Status:** DONE

## Root Cause

Sidebar `/galaxy` ohne Parameter landete immer auf der Command Map; der bevorzugte Tab (Klassik vs. Weltkarte) ging verloren. Erste Iteration speicherte auch Koordinaten — beim Planetenwechsel landete man im System des vorherigen Planeten statt am aktiven.

## Fix

| Layer | Änderung |
| ----- | -------- |
| Backend (`app.py`) | Ohne URL-Koordinaten: immer active/context planet |
| Backend (`game/galaxy.py`) | `sync_galaxy_view_session_for_planet` nach `/api/planets/active` |
| Frontend (`main.js`) | `gc_galaxy_prefs_v1` — nur `view`; Sidebar setzt kein `galaxy`/`system` |

**Priorität:** URL > localStorage view > active planet coords

## Changed Files

- `app.py`
- `game/galaxy.py`
- `static/main.js`
- `docs/GALAXY_SYSTEM.md`
- `tests/test_gc_galaxy_last_view.py`

## Tests

```bash
python -m pytest tests/test_gc_galaxy_last_view.py tests/test_galaxy.py -q
```

## Ergebnis

Klassische Ansicht bleibt gespeichert; Koordinaten folgen immer dem **aktiven Planeten**. Nach Planetenwechsel keine fremden Systeme mehr. Ohne gespeicherten View bleibt Command Map Default.

**Follow-up (erledigt):** `tests/test_galaxy.py` nutzt `session_transaction` statt `POST /login`.
