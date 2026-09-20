"""Canonical minimum durations for normal progression queues.

Speed modifiers may accelerate progression, but normal server-calculated
construction/research/production jobs must never collapse to instant/1-second
completion. Explicit skip mechanics (for example Timekeeper/admin actions) are
separate mutations and do not use this scaling floor.
"""

MIN_PROGRESS_DURATION_SECONDS = 10


def clamp_progress_duration_seconds(value: int | float) -> int:
    """Return a whole-second normal queue duration with the canonical floor."""
    return max(MIN_PROGRESS_DURATION_SECONDS, int(value))
