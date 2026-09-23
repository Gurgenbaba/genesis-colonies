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

The sections below retain historical endgame / 10 s floor findings; treat any `0.70` / flat-30% nano wording as obsolete.

---

## Root Cause (original audit)

Historically, endgame mines could sit permanently at **~10 s** because multiplicative speed stacks divided `power_build_seconds()` down to the global floor. **GC-MANDO-PACING-001** introduced a gentle mine-only floor from L225. **GC-FERDI-DEEP-PACING-002** preserves that curve through L400, adds cubic deep pacing through L1000, and then continues linearly without a cap, specifically to stop mature multi-world resource pooling from collapsing calendar-time progression while preserving the astronomical no-max base-time contract.

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
floor = building_progress_floor_seconds(building_type, target_level)
return max(int(seconds), floor)          # base 10s; production mines ramp after L224
```

---

## Example Profiles (historical, 2026-06-24)

Profiles below were computed under an older nano model documentation; **recompute via `get_build_time_seconds` for live numbers**. Kept for 10 s floor / stacking discussion.

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
| Base 10 s floor documented | **OK** (EFFECTS.md + here) |
| Endgame mines permanently stuck at 10 s? | **RESOLVED — GC-MANDO-PACING-001 level-aware mine floor** |

---

## Next Step

| Priority | Ticket | Action |
|----------|--------|--------|
| Endgame mine pacing | **GC-MANDO-PACING-001** | ✅ Dynamic mine-only floor; no max level and no speed-stack rewrite |
| Player confusion (nano %) | **GC-NANO-BUILDTIME-AUDIT-001** | Docs + tech-card preview (this ticket family) |
| If perceived slowness is visual | GC-859 | Building hero image LCP audit |

**Do not nerf** until product decides **BALANCE DECISION REQUIRED**.

---

## Tests

- `tests/test_gc858_build_time_modifier_audit.py` — stacking / floor / display helpers
- `tests/test_gc_nano_buildtime_audit.py` — diminishing-returns L0→L1 + preview contract (GC-NANO-001)


## Mine pacing anchors (GC-MANDO-PACING-001 + GC-FERDI-DEEP-PACING-002)

The floor is intentionally mine-only and the deep tail is unbounded:

| Target level | Minimum normal build duration |
|---:|---:|
| 200 | 10 s |
| 224 | 10 s |
| 225 | 12 s |
| 300 | 30 s |
| 400 / 424 | 82 s |
| 425 | 142 s |
| 500 | 3922 s (~1h 05m) |
| 650 | 60082 s (~16h 41m) |
| 800 | 245842 s (~2d 20h) |
| 1000 | 829522 s (~9d 14h) |
| 2000 | 2829522 s (~32d 18h) |

Through L400 the original triangular 25-level pacing remains unchanged. From
L425 through L1000, `deep_steps = floor((level - 400) / 25)` and the deep
minimum is `82 + 60 × deep_steps³` seconds. Beyond L1000 it continues from
that value at +50000 seconds per additional full 25-level step. The legacy
triangular schedule stops at L400; above L400 the deep schedule is authoritative.
This prevents the old O(level²) floor from overtaking the canonical base-time
curve at astronomical no-max levels.

There is **no 3600-second cap anymore and still no maximum mine level**. The
post-L1000 linear continuation intentionally grows slower than canonical
`power_build_seconds ~ level^1.35`, preserving the big-number invariant. This is
a calendar-time guardrail, not a resource-price rewrite. Nodebuster rebuild-time
discounts may not reduce a mine below this floor. Even with every upgrade funded
in advance, the queue ceiling stays below roughly L775 at six months and L850 at
twelve months from L200.
