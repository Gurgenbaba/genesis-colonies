# GC-858 — Build-Time Modifier Audit

**Status:** DONE (audit). **Nanofactory formula section superseded by GC-NANO-BUILDTIME-AUDIT-001** (2026-07).

## Supersession note (GC-NANO-BUILDTIME-AUDIT-001)

Runtime nanofactory is **not** `duration × 0.70^level` and the card is **not** flat `level × 30 %`.

Canonical (unchanged balance):

```text
speed_nano = 1 + 0.55 × level^0.8
duration   = duration_without_nano / speed_nano
```

Owner: `EffectResolver.nanofactory_build_speed` / `get_build_time_seconds`.  
UI preview owner: `technical_data.build_nanofactory_time_preview`.  
Authoritative docs: [EFFECTS.md](EFFECTS.md), [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md), [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md).

`command_center` still applies `duration × 0.75^cc_level` for **nanofactory upgrades only**.

The sections below retain historical endgame / 1 s floor findings; treat any `0.70` / flat-30% nano wording as obsolete.

---

## Root Cause (original audit)

Endgame **~1 s** mine builds are **runtime-correct**: multiplicative speed stacks divide `power_build_seconds()` until the **`max(int(seconds), 1)`** floor in `EffectResolver.get_build_time_seconds()`.

Player confusion (updated):

| UI element | Issue |
|------------|--------|
| Nanofactory card (pre-GC-NANO) | Speed-bonus % without concrete before/after seconds → players misread marginal saves as “25 % of base” |
| Production milestone | `+1470 %` = **production**, not build speed |
| `build_time_reduction_percent` on cards | Caps at **100 %** while true effective speed can be much higher |

**Card = Modal = Queue** for **seconds** remains true (GC-850A contract).

---

## Modifier Sources (runtime — current)

Owner: `game/effects/effect_resolver.py` · base: `game/economy_balance.power_build_seconds()`

| Source | Key / path | Stack mode | Applies to |
|--------|------------|------------|------------|
| GC-821 design base | `power_build_seconds(btype, level)` | — | All buildings |
| Universe / admin | `settings.build_speed` | × effective speed | All buildings |
| Research | `buildtime_tech` | duration `× 0.985^level` | All buildings + research time |
| Building | `nanofactory` | speed `1 + 0.55 × level^0.8` (duration ÷) | All buildings (CC path separate) |
| Building | `command_center` | `duration × 0.75^cc_level` | **Nanofactory upgrades only** |
| Galactic directives | `build_time_speed` | × (whitelist) | Per active directive |
| Galactic diplomacy | `build_time_speed` | × (whitelist) | Per active diplomacy bundle |
| Climate | — | **no** build-time effect | Solar only |
| Planet evolution | — | **none found** | — |
| Inventory boost | `inventory_use._apply_build_time_boost` | Queue job only | Active job, not card preview |

**Not** in building build-time path: `academy` (research only), shipyard `BUILD_TIME_LEVEL_FACTOR` (unit production, not building upgrades).

---

## Formula (authoritative — current)

```text
base = power_build_seconds(building_type, target_level)

mods_build_time_speed = 1.0
mods_build_time_speed ×= (1 / 0.985^buildtime_tech_level)
mods_build_time_speed ×= galactic_directive_build_time_speed
mods_build_time_speed ×= galactic_diplomacy_build_time_speed

building_duration = 1 / (1 + 0.55 × nanofactory_level^0.8)   # level 0 → 1.0
if building_type == "nanofactory":
    building_duration ×= 0.75^command_center_level

player_speed = max(0.1, mods_build_time_speed / building_duration)
effective_speed = max(0.1, player_speed × build_speed_setting)

seconds = base / effective_speed
return max(int(seconds), 1)             # 1-second floor
```

---

## Example Profiles (historical, 2026-06-24)

Profiles below were computed under an older nano model documentation; **recompute via `get_build_time_seconds` for live numbers**. Kept for 1 s floor / stacking discussion.

Settings: `production_speed=1`, `research_speed=1`.

### neutral

| Building | Level | Base (s) | Final (s) | Effective speed |
|----------|-------|----------|-----------|-----------------|
| metal_mine | 20 | 6 505 | 6 505 | 1.0× |
| metal_mine | 30 | 11 246 | 11 246 | 1.0× |

### Endgame floor

With high nano + `buildtime_tech` + high `build_speed`, many upgrades hit the **1 s** floor. That behaviour is **runtime-correct**; whether it is desired balance is a separate product decision (GC-858B).

---

## Display vs Runtime

| Check | Result |
|-------|--------|
| Card seconds = Modal seconds = Queue enqueue | **OK** (`get_build_time_seconds` single path) |
| Nanofactory explains cumulative vs marginal | **GC-NANO-001** — server preview payload |
| Milestone `+1470 %` explains build speed | **UI GAP** — production milestone, not build time |
| 1 s floor documented | **OK** (EFFECTS.md + here) |
| Endgame 1 s for mines/lab/yard intended? | **BALANCE DECISION REQUIRED** |

---

## Next Step

| Priority | Ticket | Action |
|----------|--------|--------|
| If balance team wants slower endgame | GC-858B | Raise floor, cap speed, or rebalance nano coeff / admin `build_speed` |
| Player confusion (nano %) | **GC-NANO-BUILDTIME-AUDIT-001** | Docs + tech-card preview (this ticket family) |
| If perceived slowness is visual | GC-859 | Building hero image LCP audit |

**Do not nerf** until product decides **BALANCE DECISION REQUIRED**.

---

## Tests

- `tests/test_gc858_build_time_modifier_audit.py` — stacking / floor / display helpers
- `tests/test_gc_nano_buildtime_audit.py` — diminishing-returns L0→L1 + preview contract (GC-NANO-001)
