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


def building_progress_floor_seconds(building_type: str, target_level: int) -> int:
    """Return the canonical normal-build floor for one building target level.

    Non-mine buildings keep the shared 10-second floor. Production mines keep
    that floor through L224, then gain a gentle triangular pacing floor every
    25 levels. This preserves unlimited progression while preventing 10-slot
    queues from blasting through late-game mine levels in a few seconds.

    Anchors:
      L200/L224 -> 10 s
      L225      -> 12 s
      L300      -> 30 s
      L400      -> 82 s
      L500      -> 166 s
      L650      -> 352 s
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
    return MIN_PROGRESS_DURATION_SECONDS + MINE_ENDGAME_PACING_STEP_SECONDS * triangular


def clamp_progress_duration_seconds(value: int | float) -> int:
    """Return a whole-second normal queue duration with the shared base floor."""
    return max(MIN_PROGRESS_DURATION_SECONDS, int(value))
