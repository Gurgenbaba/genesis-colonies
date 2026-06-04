# Planet Scope System

Single source of truth für Multi-Kolonie-Kontext in Genesis Colonies (v1.5.3).

---

## Konzept

| Begriff | Bedeutung |
|---------|-----------|
| **Context planet** | Der Planet, auf dem UI-Actions und Ressourcen-Anzeige basieren |
| **Active planet** | Persistiert in `players.active_planet_id` (DB, nicht Flask-Session) |
| **Homeworld** | `planets.is_homeworld = 1` — Fallback wenn active invalid |
| **Empire** | Alle `planets` eines `player_id` |

**Regel:** Ressourcen, Gebäude-Queue, Shipyard, Trader Hub, Exchange-Kontostand und Fleet-Origin defaulten auf den **context planet**. Account-Forschung und Flottenbewegungen sind **spielerweit**.

---

## Auflösung (Backend)

```python
get_context_planet(player_id)  # game/planet_evolution/repository.py
```

1. Wenn Planet-Evolution-Schema fehlt → Homeworld
2. Lade `players.active_planet_id`
3. Validiere Ownership → sonst Homeworld
4. Gib Planet-Row zurück

**Setzen:**

```python
set_active_planet(user_id, planet_id)  # game/planet_evolution/service.py
```

→ `POST /api/planets/active` mit `{ "planet_id": N }`

Antwort enthält vollständigen `state` (game-state payload) + `planets[]`.

---

## Scope-Matrix

| System | Scope | Resolver |
|--------|-------|----------|
| Ressourcen-Anzeige / Tick-UI | Planet | `get_context_planet()` |
| Bau-Queue | Planet | `planet_id` auf Queue-Row |
| Shipyard-Queue | Planet | `resolve_owned_planet_id()` |
| Account-Forschung | Spieler | `user_id`; Kosten vom context planet |
| Planet-Forschung (Evolution) | Planet | URL `/api/planets/<id>/…` + Owner-Check |
| Fleet send / preview | Origin planet | Body `origin_planet_id` oder context |
| Fleet movements (Overview) | Spieler | Alle aktiven Bewegungen |
| Exchange daily limit | Spieler | `players.exchange_daily_*` |
| Fuel exchange daily | Planet | `planets.fuel_exchange_daily_*` |
| Galaxy `is_active_planet` | Markierung | `active_planet_id` Parameter |

**Queue-Finish:** `finish_player_due_work()` arbeitet **alle Kolonien** des Spielers ab (inaktive Kolonien bauen im Hintergrund weiter).

---

## Frontend

### Header Planet Switcher

- Template: `templates/partials/header_planet_switcher.html`
- `data-multi="0"` bei einer Kolonie (disabled)
- `data-multi="1"` bei 2+ — Dropdown mit allen Kolonien

### Header Planet Limit (GC-532)

- Anzeige in der Ressourcenzeile (`templates/base.html`), Panel `hud-res-planet-limit` direkt nach Brennzellen
- Format: `Planeten X / Y` (`X` = besessene Planeten, `Y` = `game_settings.max_colonies_per_player`, Fallback `9`)
- Live-State: `/api/game-state` liefert `planet_limit: { current, max }` (Owner: `game/logic.py` → `get_planet_limit_block`)
- Frontend: `patchHeaderPlanetLimitFromState` in `static/main.js` (Polling, Planetwechsel, Kolonisierung via `applyActionState`)

### Switch-Flow (`static/main.js`)

```
Klick Kolonie
  → POST /api/planets/active
  → applyActionState(res, "planet_switch")
  → rebuildHeaderPlanetSwitcher / updateHeaderPlanetSwitcherFromState
  → applyPlanetLandscapeFromState (CSS --planet-landscape)
  → GC.reloadCurrentPage({ force: true })
```

### DOM-Planet-ID

Scoped Pages tragen `data-planet-id`:

| Seite | Root-Element |
|-------|--------------|
| Fleet | `#fleet-page` |
| Shipyard | `#shipyard-page` |
| Trader Hub | trader-hub root |
| Build queue panel | `#build-queue-root` |

`getDomPlanetId()` liest diese Werte. `reloadPageForActivePlanet()` PJAX-reload wenn Poll-State ≠ DOM (außer bei `reason === "planet_switch"`).

### Labels

`build-queue-planet-label`, `research-planet-label` werden nach Switch aktualisiert.

---

## Kolonisierung

- **Galaxy:** Leere Slots → Link `/fleet?…&mission=colonize`
- **Fleet arrival:** `colonize_planet()` in Evolution-Service
- **API:** `POST /api/planets/colonize` (Owner-Check, max colonies aus `game_settings`)
- **Kein** In-Page-Colonize-UI auf Planet Evolution (nur Header-Switcher)

---

## Planet löschen

`POST /api/planet/delete` — löscht **aktive Nicht-Homeworld**-Kolonie, setzt active auf Homeworld.

---

## Integration Planet Evolution

`/planet-evolution` zeigt immer den **aktiven** Planeten (`get_active_planet_id()`).

Evolution-Tick läuft in `update_planet_resources()` für die **jeweilige Planet-Row** (nicht nur active).

Details: Tabellen und APIs in [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md).

---

## Tests

```bash
python -m pytest tests/test_planet_instancing.py tests/test_header_planet_switcher.py tests/test_planet_state_scoping.py -v
```

---

## Verboten (Architektur)

- Paralleles Session-basiertes Planet-Tracking neben `active_planet_id`
- Homeworld-only hardcoden in neuen Features
- Separate Ressourcenmodelle pro UI-Seite

**Erlaubt:** Explizites `planet_id` in APIs wenn Ownership geprüft (`resolve_owned_planet_id`).
