# Planet Scope System

Single source of truth für Multi-Kolonie-Kontext in Genesis Colonies (Stand v1.5.9.2).

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

### Planet Registry (GC-575 / GC-575A)

- Template: `templates/partials/planet_registry.html` — Desktop/Tablet rechte Sidebar; Phone: Header-Pfeil → `#gc-planet-registry-sheet` (nicht MEHR/META)
- Kein Header-Planet-Switcher — Wechsel nur über Registry (Desktop + Mobile-Drawer)
- Mini-Cards: Name, Empire-Rolle/Identity, Koordinaten, `is-active`
- Spec: [GC_PLANET_REGISTRY.md](GC_PLANET_REGISTRY.md)

### Planet Limit (GC-532)

- Anzeige im Registry-Header (`data-planet-limit-value`)
- Format: `Planeten X / Y` (`X` = besessene Planeten, `Y` = Limit-Block / Settings)
- Live-State: `/api/game-state` liefert `planet_limit: { current, max }` (Owner: `game/logic.py` → `get_planet_limit_block`)
- Frontend: `patchHeaderPlanetLimitFromState` in `static/main.js` (Polling, Planetwechsel, Kolonisierung via `applyActionState`)

### Switch-Flow (`static/main.js`)

```
Klick Kolonie (Registry-Card)
  → POST /api/planets/active
  → applyActionState(res, "planet_switch")
  → unlockShellEarly (before SSR)
  → rebuildPlanetRegistry / updatePlanetRegistryFromState
  → applyPlanetLandscapeFromState (CSS --planet-landscape; Slot-Herocard via planet_visuals)
  → GC.reloadCurrentPage({ force: true })  # skipped on fleet/admin/…
```

**GC-PERF-PLANET-SWITCH-003:** `POST /api/planets/active` does **not** run empire `finish_player_due_work` or the HTTP `before_request` fleet tick. State uses `read_player_live_state_for_planet_switch` (projected resources for the new active planet). Queue finish stays on poll / maintenance worker — Bauleiste must not block colony switching.

**GC-PERF-PLANET-SWITCH-004:** On buildings / research / shipyard / defense / overview (and similar), planet switch **skips PJAX SSR** and soft-patches via `forceCanonicalGameStateRefresh("planet_switch_panel", { planetId })`. Late `upgrade_success` for the previous planet is HUD-only when DOM scope already moved — avoids stutter after enqueue→instant switch.

**GC-PERF-PLANET-SWITCH-005:** Soft panel refresh after switch is **exclusive** (does not coalesce onto an in-flight `queue_timer_zero` / panel fetch). In-flight canonical refreshes are token-superseded on switch start so a pre-switch `include_panel` response cannot re-paint the previous colony’s unaffordable/grey cards onto the new active planet. Response must match `planetId` **and** DOM scope; stuck upgrade `is-busy` buttons are cleared after the panel patch.

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
python -m pytest tests/test_planet_instancing.py tests/test_planet_registry.py tests/test_planet_state_scoping.py -v
```

---

## Verboten (Architektur)

- Paralleles Session-basiertes Planet-Tracking neben `active_planet_id`
- Homeworld-only hardcoden in neuen Features
- Separate Ressourcenmodelle pro UI-Seite

**Erlaubt:** Explizites `planet_id` in APIs wenn Ownership geprüft (`resolve_owned_planet_id`).

---

## Player Article

```yaml
---
codex_id: planet_scope
band: II
difficulty: beginner
estimated_read: 2 min
surfaces:
  - quick_help
  - faq
routes:
  - overview
  - buildings_view
  - fleet_view
related_codex:
  - genesis_ark
  - planet_evolution
terminology: GENESIS_TERMINOLOGY
unlock:
  type: always
---
```

## Quick Help

Genesis Colonies spielt sich pro **aktiver Welt**. Der Planet-Switcher im Header legt fest, welche Kolonie Gebäude, Ressourcen und Werft zeigt — Account-Forschung bleibt imperiumsweit.

## Summary

**Planet Scope** ist der Kontext, in dem du spielst: eine **aktive Welt**, von der Ressourcen-Anzeige, Bau-Queue, Werft, Trader Hub und Flotten-Abgang defaulten. Dein **Imperium** umfasst alle Welten — aber Aktionen auf Planeten-Gebäude passieren immer auf der gewählten Welt.

## Why

Multi-Kolonie ohne Scope würde verwirren: Welche Mine produziert gerade? Wo baut die Werft? Scope trennt **imperiumsweite** Systeme (Account-Forschung, alle Flottenbewegungen) von **weltgebundenen** (Gebäude, Ressourcen-Tick, Shipyard).

## How it works

- **Planet Switcher** im Header: bei mehreren Welten Dropdown; bei einer Welt deaktiviert.
- Wechsel → API setzt active planet → Seite aktualisiert Ressourcen, Queues und Labels.
- **Homeworld** = Genesis Ark; bei ungültigem Kontext Fallback auf Homeworld.
- **Planet Evolution** zeigt immer die **aktive** Welt — kein zweiter Switcher auf der Seite.
- Kolonisierung und Flotten nutzen explizite Ziele; Logistics sammelt zwischen **eigenen** Welten.

## Related Systems

- genesis_ark
- planet_evolution
- fleet
- buildings

## Commander Tips

- Vor dem Upgrade prüfen: auf welcher Welt bist du aktiv?
- Account-Forschung zahlst du von der aktiven Welt — plane Ressourcen dort.
- Inaktive Kolonien bauen im Hintergrund weiter; Scope betrifft nur die UI-Kontext-Anzeige.

## FAQ

**Warum ändern sich meine Ressourcen nach dem Wechsel?**
Jede Welt hat eigene Lager und Produktion. Der Switcher wechselt den Kontext, nicht dein gesamtes Imperium.

**Kann ich eine Nicht-Homeworld löschen?**
Ja — aktive Nicht-Homeworld kann gelöscht werden; active springt auf die Genesis Ark.

## Discord Summary

**Planet Scope — aktive Welt vs. Imperium**

Spielaktionen auf Gebäude, Ressourcen und Werft laufen über die **aktive Welt** (Header-Switcher). Account-Forschung und Flottenübersicht sind imperiumsweit. Homeworld = Genesis Ark. Planet Evolution zeigt die aktive Welt.
