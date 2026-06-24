# GC-858 — Build-Time Modifier Audit

**Status:** DONE (audit only — no balance changes)

## Root Cause

Endgame **~1 s** mine builds are **runtime-correct**: multiplicative speed stacks divide `power_build_seconds()` until the **`max(int(seconds), 1)`** floor in `EffectResolver.get_build_time_seconds()`.

Player confusion comes mainly from **UI ≠ runtime**:

| UI element | Shows | Actually means |
|------------|-------|----------------|
| Nanofactory card | `level × 30 %` (e.g. 660 %) | Flat display constant; runtime uses `× 0.70^level` duration |
| Production milestone | `+1470 %` | **Production gain** at a future mine level — not build speed |
| `build_time_reduction_percent` on cards | caps at **100 %** | True effective speed can be **40 000×+** (Ferdi-like profile) |

**Card = Modal = Queue** for **seconds** remains true (GC-850A contract).

---

## Modifier Sources (runtime)

Owner: `game/effects/effect_resolver.py` · base: `game/economy_balance.power_build_seconds()`

| Source | Key / path | Stack mode | Applies to |
|--------|------------|------------|------------|
| GC-821 design base | `power_build_seconds(btype, level)` | — | All buildings |
| Universe / admin | `settings.build_speed` | × effective speed | All buildings |
| Research | `buildtime_tech` | `build_time_speed × (1 / 0.97^level)` | All buildings + research time |
| Building | `nanofactory` | `duration × 0.70^nano_level` (÷ in speed) | All buildings **except** CC-only path |
| Building | `command_center` | `duration × 0.75^cc_level` | **Nanofactory upgrades only** |
| Galactic directives | `build_time_speed` | × (whitelist) | Per active directive |
| Galactic diplomacy | `build_time_speed` | × (whitelist) | Per active diplomacy bundle |
| Climate | — | **no** build-time effect | Solar only |
| Planet evolution | — | **none found** | — |
| Inventory boost | `inventory_use._apply_build_time_boost` | Queue job only | Active job, not card preview |

**Not** in building build-time path: `academy` (research only), shipyard `BUILD_TIME_LEVEL_FACTOR` (unit production, not building upgrades).

---

## Formula (authoritative)

```text
base = power_build_seconds(building_type, target_level)
     = max(30, int(k × level^exp))     # per BUILD_TIME_CURVES

mods_build_time_speed = 1.0
mods_build_time_speed ×= (1 / 0.97^buildtime_tech_level)
mods_build_time_speed ×= galactic_directive_build_time_speed
mods_build_time_speed ×= galactic_diplomacy_build_time_speed

building_duration = 0.70^nanofactory_level
if building_type == "nanofactory":
    building_duration ×= 0.75^command_center_level

player_speed = max(0.1, mods_build_time_speed / building_duration)
effective_speed = max(0.1, player_speed × build_speed_setting)

seconds = base / effective_speed
return max(int(seconds), 1)             # 1-second floor
```

Display helpers (same resolver, player bonuses only — excludes `build_speed` setting):

- `get_build_time_speed_bonus_pct()` → `(player_speed − 1) × 100`
- `get_build_time_reduction_pct()` → `(1 − 1/player_speed) × 100`, **unbounded in math but UI often reads as “% faster”**

Nanofactory **card** uses separate flat constants in `game/buildings.py`:

```python
NANOFACTORY_BUILD_BONUS_PER_LEVEL = 30   # UI only
COMMAND_CENTER_NANOFACTORY_BUILD_BONUS_PER_LEVEL = 25   # UI only
```

---

## Example Profiles (computed 2026-06-24)

Settings: `production_speed=1`, `research_speed=1`.

### neutral

| Building | Level | Base (s) | Final (s) | Effective speed |
|----------|-------|----------|-----------|-----------------|
| metal_mine | 20 | 6 505 | 6 505 | 1.0× |
| metal_mine | 30 | 11 246 | 11 246 | 1.0× |
| research_lab | 30 | 19 665 | 19 665 | 1.0× |
| orbital_shipyard | 30 | 30 404 | 30 404 | 1.0× |

### midgame — nano 5, buildtime_tech 5, build_speed 1

| Building | Level | Base (s) | Final (s) | Effective speed |
|----------|-------|----------|-----------|-----------------|
| metal_mine | 20 | 6 505 | 938 | 6.9× |
| metal_mine | 30 | 11 246 | 1 623 | 6.9× |
| research_lab | 30 | 19 665 | 2 838 | 6.9× |
| orbital_shipyard | 30 | 30 404 | 4 388 | 6.9× |

Nanofactory UI: **150 %** (5×30). Runtime reduction display: **86 %**.

### ferdi_like — nano 22, buildtime_tech 17, build_speed 10

Buildings: `nanofactory=22`, `research_lab=30`, `command_center=10`.

| Building | Level | Base (s) | Final (s) | Effective speed |
|----------|-------|----------|-----------|-----------------|
| metal_mine | 20 | 6 505 | **1** | 42 926× |
| metal_mine | 30 | 11 246 | **1** | 42 926× |
| metal_mine | 50 | 22 413 | **1** | 42 926× |
| research_lab | 30 | 19 665 | **1** | 42 926× |
| orbital_shipyard | 30 | 30 404 | **1** | 42 926× |

Nanofactory UI: **660 %** (22×30). Runtime reduction display: **100 %** (saturated — true speed far higher).

`buildtime_tech` L17 speed bonus display: **~66 %** (not 1470 %).

---

## Display vs Runtime

| Check | Result |
|-------|--------|
| Card seconds = Modal seconds = Queue enqueue | **OK** (`get_build_time_seconds` single path) |
| Nanofactory % on card explains runtime | **UI GAP** — flat `level×30` vs `0.70^level` |
| Milestone `+1470 %` explains build speed | **UI GAP** — production milestone, not build time |
| Reduction % reflects true endgame speed | **UI GAP** — caps at 100 % while speed is 10⁴× |
| 1 s floor documented | **DOC GAP** — implicit in code, now documented here |
| Endgame 1 s for mines/lab/yard intended? | **BALANCE DECISION REQUIRED** |

---

## Classification

| Item | Verdict |
|------|---------|
| Runtime formula / stacking | **OK / intended** |
| 1 s floor behaviour | **OK / intended** (code) — balance TBD |
| Card = Modal = Queue times | **OK** |
| Nanofactory / CC card % | **UI GAP** |
| Production milestones on mine cards | **UI GAP** (misread as build bonus) |
| Floor documentation | **DOC GAP** (closed in this audit) |
| Code bug in stacking | **None found** |

---

## Next Step

| Priority | Ticket | Action |
|----------|--------|--------|
| If balance team wants slower endgame | GC-858B | Raise floor, cap speed, or rebalance `0.70`/admin `build_speed` |
| If player confusion is the issue | GC-858C | Align nanofactory card % with resolver; clarify milestone labels |
| If perceived slowness is visual | GC-859 | Building hero image LCP audit (`img.gc-bld-card-hero-img`) |

**Do not nerf** until product decides **BALANCE DECISION REQUIRED**.

---

## Tests

```bash
python -m pytest tests/test_gc858_build_time_modifier_audit.py tests/test_gc850a_build_time_wiring.py -v
```

## Related

- GC-850A — `power_build_seconds` wiring
- GC-856 — SSR profiling (separate from build-time balance)
- `docs/EFFECTS.md` § Build time
- `docs/BUILDINGS_SYSTEM.md` § Build duration
