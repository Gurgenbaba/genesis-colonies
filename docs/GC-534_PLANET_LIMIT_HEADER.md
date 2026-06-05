# GC-534 – Planet Limit im Header & kompakte Logistics-UI

**Epic:** EPIC-01 Planet Scope / EPIC-02 Fleet (UI)  
**Status:** Implementiert (Dokumentation / Nummerierung)

Ursprünglich fälschlich als „GC-532 Planet-Limit“ geführt — **GC-532** ist das Fleet-Audit-Ticket.

---

## Scope

### Planet Limit (Header)

- Anzeige `Planeten X / Y` in der Ressourcenzeile (`templates/base.html`, `hud-res-planet-limit`)
- Live-State: `/api/game-state` → `planet_limit: { current, max }` (`game/logic.py` → `get_planet_limit_block`)
- Frontend: `patchHeaderPlanetLimitFromState` in `static/main.js`

Siehe [PLANET_SCOPE.md § Header Planet Limit](PLANET_SCOPE.md#header-planet-limit-gc-534).

### Logistics UI (compact)

- Markup: `templates/fleet_logistics.html` (include von `templates/logistics.html`)
- Client: Preview `can_launch` vor Submit, Clamp MAX, `showNotify` bei Fehlern
- Server: `validate_logistics_manual_ships()` / `fleet_logistics_validate_ships()` — Cargo-only

Siehe [FLEET_SYSTEM.md § Fleet Logistics](FLEET_SYSTEM.md#fleet-logistics-gc-526534).

---

## Manuelle QA

Planet-Limit: Header nach Kolonisierung / Planetwechsel — Wert aktualisiert ohne Reload.

Logistics-UI: Teil von **GC-533** (Browser-Regression Collect/Distribute).
