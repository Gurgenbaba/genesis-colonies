"""Kill-switch for pirate AI (EPIC-21)."""

from __future__ import annotations

from typing import Optional

from ..runtime_state import get_runtime_value, set_runtime_value

AI_ENABLED_RUNTIME_KEY = "pirates_ai_enabled"


def is_pirates_ai_enabled(*, conn=None) -> bool:
    """Return True when pirate AI may spawn/spy/raid.

    Default is **off** until LiveOps enables it (safe ship default).
    """
    raw = get_runtime_value(AI_ENABLED_RUNTIME_KEY, conn=conn)
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def set_pirates_ai_enabled(enabled: bool, *, conn=None) -> None:
    set_runtime_value(AI_ENABLED_RUNTIME_KEY, "1" if enabled else "0", conn=conn)
