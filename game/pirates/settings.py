"""Kill-switch for pirate AI (EPIC-21)."""

from __future__ import annotations

from typing import Optional

from ..config import is_production
from ..runtime_state import get_runtime_value, set_runtime_value

AI_ENABLED_RUNTIME_KEY = "pirates_ai_enabled"


def is_pirates_ai_enabled(*, conn=None) -> bool:
    """Return True when pirate AI may spawn/spy/raid.

    GC-2611: the admin `runtime_state` Soft-On/Off always wins once set (Soft-Off
    stays available at any time). Only when no admin choice has ever been made
    does the default follow `is_production()` instead of a hard `False` — so a
    freshly deployed production universe ships with a living pirate AI without
    requiring a manual admin click first.
    """
    raw = get_runtime_value(AI_ENABLED_RUNTIME_KEY, conn=conn)
    if raw is None:
        return is_production()
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def set_pirates_ai_enabled(enabled: bool, *, conn=None) -> None:
    set_runtime_value(AI_ENABLED_RUNTIME_KEY, "1" if enabled else "0", conn=conn)
