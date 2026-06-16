# GC-597D — Command Map DEV PREVIEW

**Status:** Done  
**Ziel:** Closed Alpha kann die World Map zeigen, ohne dass Spieler erwarten, alle Fleet-Missionen / Foreign Worlds zu haben.

## Produkt-Label

| Ansicht | Status |
|---------|--------|
| Klassische Galaxy (`view=system`) | **STABLE** — Fleet, Combat, Standard-Alpha |
| Command Map (`view=command_map`) | **DEV PREVIEW** — Badge + Hinweis, keine Sperre |

## Technik

- Flag: `GC_COMMAND_MAP_DEV_MODE` (default `1` / an)
- Template: `COMMAND_MAP_DEV_MODE` via `inject_globals`
- Client: `GC_CLIENT_CONFIG.command_map_dev_mode`
- Badge: Sidebar „Galaxie“, Tab „Weltkarte“, Banner auf Command Map
- Telemetrie (optional, nur bei DEV-Flag): `POST /api/command-map/telemetry`
  - Events: `map_open`, `node_click`, `inspector_open`
  - Server: `logger.info` (grep `command_map_telemetry`)

## Nach Closed Alpha

```text
GC-598 — Mission Actions (Spy, Attack, Transport, Recycle, Expedition …)
GC-599 — Foreign Worlds / Enemy Nodes
→ dann GC_COMMAND_MAP_DEV_MODE=0 und Badge entfernen
```
