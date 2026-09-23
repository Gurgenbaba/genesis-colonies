"""Canonical minimum durations for normal progression queues.

Speed modifiers may accelerate progression, but normal server-calculated
construction/research/production jobs must never collapse to instant/1-second
completion. Explicit skip mechanics (for example Timekeeper/admin actions) are
separate mutations and do not use this scaling floor.

GC-MANDO-PACING-001 adds a mine-only endgame pacing floor. Production mines stay
unbounded, but very high levels can no longer sit on the global 10-second floor
forever when Nanofactory/research/universe speed stacks become enormous.
"""

MIN_PROGRESS_DURATION_SECONDS = 10

PRODUCTION_MINE_BUILDING_TYPES = frozenset({
    "metal_mine",
    "crystal_mine",
    "fuel_cell_plant",
})
MINE_ENDGAME_PACING_START_LEVEL = 200
MINE_ENDGAME_PACING_STEP_LEVELS = 25
MINE_ENDGAME_PACING_STEP_SECONDS = 2

# GC-FERDI-DEEP-PACING-002 — empire-pooling guardrail.
# Keep the existing gentle floor through L400, then make record pushing consume
# real calendar time even when an 11-world empire can fully fund every upgrade.
# This is deliberately unbounded: there is still no maximum mine level.
MINE_DEEP_PACING_START_LEVEL = 400
MINE_DEEP_PACING_BASE_SECONDS = 82
MINE_DEEP_PACING_CUBIC_STEP_SECONDS = 60
MINE_DEEP_PACING_CUBIC_END_LEVEL = 1000
MINE_DEEP_PACING_LINEAR_STEP_SECONDS = 50_000


def building_progress_floor_seconds(building_type: str, target_level: int) -> int:
    """Return the canonical normal-build floor for one building target level.

    Non-mine buildings keep the shared 10-second floor. Production mines keep
    that floor through L224, then gain the existing gentle triangular pacing
    through L400. Above L400 a cubic 25-level step becomes the dominant minimum
    through L1000; beyond that point it continues linearly without a cap. The
    linear continuation preserves the no-max big-number contract because the
    canonical L^1.35 base build curve eventually remains dominant. The deep tail
    is intentionally account-income agnostic: pooling production from many
    worlds can pay the resource bill, but cannot turn record pushing into
    thousands of near-instant queue completions.

    Anchors:
      L200/L224 -> 10 s
      L225      -> 12 s
      L300      -> 30 s
      L400/L424 -> 82 s
      L425      -> 142 s
      L500      -> 3922 s  (~1h 05m)
      L650      -> 60082 s (~16h 41m)
      L800      -> 245842 s (~2d 20h)
      L1000     -> 829522 s (~9d 14h)
      L2000     -> 2829522 s (~32d 18h)

    There is no pacing cap and no mine level cap.
    """
    if str(building_type or "") not in PRODUCTION_MINE_BUILDING_TYPES:
        return MIN_PROGRESS_DURATION_SECONDS

    level = max(0, int(target_level or 0))
    steps = max(
        0,
        (level - MINE_ENDGAME_PACING_START_LEVEL) // MINE_ENDGAME_PACING_STEP_LEVELS,
    )
    if steps <= 0:
        return MIN_PROGRESS_DURATION_SECONDS

    triangular = steps * (steps + 1) // 2
    gentle_floor = (
        MIN_PROGRESS_DURATION_SECONDS
        + MINE_ENDGAME_PACING_STEP_SECONDS * triangular
    )
    if level <= MINE_DEEP_PACING_START_LEVEL:
        return gentle_floor

    deep_steps = max(
        0,
        (level - MINE_DEEP_PACING_START_LEVEL) // MINE_ENDGAME_PACING_STEP_LEVELS,
    )
    cubic_end_steps = max(
        0,
        (MINE_DEEP_PACING_CUBIC_END_LEVEL - MINE_DEEP_PACING_START_LEVEL)
        // MINE_ENDGAME_PACING_STEP_LEVELS,
    )
    if deep_steps <= cubic_end_steps:
        deep_floor = (
            MINE_DEEP_PACING_BASE_SECONDS
            + MINE_DEEP_PACING_CUBIC_STEP_SECONDS * (deep_steps ** 3)
        )
    else:
        cubic_end_floor = (
            MINE_DEEP_PACING_BASE_SECONDS
            + MINE_DEEP_PACING_CUBIC_STEP_SECONDS * (cubic_end_steps ** 3)
        )
        deep_floor = (
            cubic_end_floor
            + MINE_DEEP_PACING_LINEAR_STEP_SECONDS
            * (deep_steps - cubic_end_steps)
        )
    return max(gentle_floor, deep_floor)


def clamp_progress_duration_seconds(value: int | float) -> int:
    """Return a whole-second normal queue duration with the shared base floor."""
    return max(MIN_PROGRESS_DURATION_SECONDS, int(value))
