# Universe Search (GC-880)

OGame-style discovery for players, planets, and alliances. Server-authoritative; UI displays search results only.

**Owner:** `game/universe_search.py`  
**Routes:** `GET /search`, `GET /api/search`  
**UI:** `templates/search.html`, `GC.modules.search` / `initSearch`

## Product rules

| Mode | Matches | Coordinates shown |
|------|---------|-------------------|
| **player** | `players.name` prefix (`LIKE q%`) | **Homeworld only** (`planets.is_homeworld = 1`) |
| **planet** | `planets.name` contains | That planet’s slot `[G:S:P]` |
| **alliance** | `alliances.tag` or `name` contains | Alliance + members; each member’s **homeworld** |
| **coords** | `parse_coordinate_query` (`G:S` / `G:S:P`) | `meta.coord_jump` → Galaxy deep-link (no name LIKE) |

Banned players (`banned_until` in the future) are excluded from player/planet results.

## API

`GET /api/search?type=player|planet|alliance&q=`

```json
{
  "ok": true,
  "error": null,
  "results": [ /* typed rows */ ],
  "meta": {
    "query": "Hans",
    "type": "player",
    "limit": 25,
    "coord_jump": null
  }
}
```

Guards: login required · min query length 2 (except pure coords) · limit 25 · read-only.

## Alliance roster

`get_alliance_members()` joins homeworld coords (`homeworld`, `homeworld_coords`). Hub + visitor templates show a Homeworld column with `galaxy_coord_link`. Search reuses the same member shape.

## Related

- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — coordinate model, `galaxy_coord_link`
- [ALLIANCE_SYSTEM.md](ALLIANCE_SYSTEM.md) — member roster
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17 — owner table
