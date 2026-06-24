# GC-GALAXY-LAST-VIEW — Persist last galaxy coords + view tab

**Status:** DONE

## Root Cause

Sidebar `/galaxy` ohne Parameter landete immer auf Command Map mit Koordinaten des aktiven Planeten — Session-Last-Coords wurden geschrieben, aber beim erneuten Öffnen nicht gelesen; der bevorzugte Tab ging verloren.

## Fix

| Layer | Änderung |
| ----- | -------- |
| Backend (`app.py`) | Ohne URL-Koordinaten: `session["galaxy_view_galaxy/system"]` vor active planet |
| Frontend (`main.js`) | `gc_galaxy_prefs_v1` — view + coords bei Galaxy-Init; Sidebar-Link baut URL aus Prefs |

**Priorität:** URL > localStorage view > Session coords > active planet

## Changed Files

- `app.py`
- `static/main.js`
- `docs/GALAXY_SYSTEM.md`
- `tests/test_gc_galaxy_last_view.py`

## Tests

```bash
python -m pytest tests/test_gc_galaxy_last_view.py tests/test_galaxy.py -q
```

## Ergebnis

Spieler in klassischer Ansicht G3:S42 → Sidebar Galaxie → wieder klassisch G3:S42. Ohne gespeicherten State bleibt Command Map Default.

**Follow-up (erledigt):** `tests/test_galaxy.py` nutzt `session_transaction` statt `POST /login` (gleiches Pattern wie `test_gc_galaxy_last_view.py`).
