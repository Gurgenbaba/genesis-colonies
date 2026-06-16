# GC-590B — Fleet UI Named Targets

## Ziel

Fleet-UI zeigt benannte Ziele primär; G:S:P nur noch als sekundäre technische Info.

## Scope

- `templates/fleet.html` — Preview-Hero + Active-Card Named Target
- `static/main.js` — `formatFleetNamedTarget`, Preview/Active Rendering
- `game/fleet.py` — `_enrich_movement_world_target` auf `list_active_movements`
- `game/fleet_target.py` — Expedition-Label für `_resolve_target_name`
- Locales + CSS

## Nicht im Scope

- Keine Timer-/Fleet-Math-Änderungen
- Kein neues Target-System (nutzt `target.world_target` aus GC-590A)
- Galaxy-Prefill / Send-Pipeline unverändert

## UI

- **Preview:** `data-preview-target-name` + `data-preview-target-native-type`; Koordinaten in `data-preview-target-coords`
- **Active fleets:** `fleet-active-target-name` + Typ; Koordinaten in `fleet-active-coords-secondary`
- Legacy Preview-Stats (`data-preview-target-type/owner`) bleiben im DOM, hidden

## Tests

```bash
python -m pytest tests/test_fleet.py tests/test_gc557c_time_authority.py tests/test_gc557d_timer_dom_audit.py tests/test_gc590b_fleet_ui_world_native.py -v
```
