# GC-836 — Alpha Starter Resources

> Kanonische Defaults: [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) § Universe-Defaults · `game/models.py` `DEFAULT_GAME_SETTINGS`  
> Sim-Ergebnisse: `python scripts/fresh_account_progression_sim.py` → [GC-829_FRESH_ACCOUNT_PROGRESSION.md](GC-829_FRESH_ACCOUNT_PROGRESSION.md)

## Problem

Fresh-Account-Sim (GC-829) zeigte: Fortschritt in den ersten Stunden zu selten sichtbar. Mit 3k/1,5k Start kam der Spieler nach wenigen Gebäudestufen in tagelange Wartezeiten — Crytite-Engpass, Labor erst nach Tagen.

## Ziel

Der erste Spielstart soll aktiv spielbar sein:

- mehrere Gebäude-Upgrades direkt möglich
- Forschungslabor früh erreichbar
- Crytite-Engpass entschärft
- erste Forschung innerhalb der ersten Session möglich
- **keine** Änderung an `calculate_resource_output()`

## Umsetzung

`DEFAULT_GAME_SETTINGS` (Homeworld bei Account-Erstellung):

| Ressource | Alt | Neu (GC-836) |
|-----------|----:|-------------:|
| Ferronit (`start_metal`) | 3.000 | **150.000** |
| Crytite (`start_crystal`) | 1.500 | **100.000** |
| Brennzellen (`start_fuel_cells`) | 500 (hardcoded) | **25.000** (Setting) |

Owner: `game/models.py` (`ensure_player_homeworld`).

## Sim-Checkpoints (Alpha: `production_speed=1`, `build_speed=1.1`, `research_speed=0.85`)

| Zeit | Mine M/C | Solar | Labor | Forschung | Bau/R | Prod Ferronit/h |
|------|---------|------|-------|-----------|------|----------------:|
| 1h | 7 / 7 | L5 | L1 | E0 | 21 / 0 | 482 |
| 24h | 17 / 17 | L8 | L1 | E13 | 44 / 13 | 1.938 |
| 7d | 23 / 23 | L8 | L1 | E28 | 56 / 28 | 3.096 |

*(Automatisch generiert — Werte können leicht schwanken, Tests fixieren Untergrenzen.)*

## Akzeptanzkriterien

| Kriterium | Sim 1h | Status |
|-----------|--------|--------|
| Ferronit-Mine ca. L8–10 | L7 | nah dran (Session weiter spielbar) |
| Crytite L6–8 | L7 | ✓ |
| Solar L5–7 | L5 | ✓ |
| Labor erreichbar | L1 | ✓ |
| Erste Forschung startbar | Lab L1 | ✓ (Abschluss ~1h36 Alpha) |
| 8–15 sichtbare Aktionen / 1h | 21 Bau | ✓ |
| 24h kein Stillstand | M17, 13 Forschung | ✓ |

## Wichtig

- Nur Startressourcen / Onboarding-Pacing
- Keine Produktionsformel, keine ROI-Kurve, kein Endgame

## Tests

```bash
python -m pytest tests/test_gc836_starter_resources.py tests/test_gc829_fresh_account_progression.py -q
```
