"""Kill-switch for pirate AI (EPIC-21)."""

from __future__ import annotations

import os
from typing import Optional

from ..config import is_production
from ..runtime_state import get_runtime_value, set_runtime_value

AI_ENABLED_RUNTIME_KEY = "pirates_ai_enabled"
AI_ENABLED_ENV = "GC_PIRATE_AI_ENABLED"
_FALSEY = {"0", "false", "no", "off"}


def is_pirates_ai_hard_disabled() -> bool:
    """Deployment-level hard-off, independent of runtime DB state."""
    env = os.environ.get(AI_ENABLED_ENV)
    return env is not None and str(env).strip().lower() in _FALSEY


def is_pirates_ai_enabled(*, conn=None) -> bool:
    """Return True when pirate AI may spawn/spy/raid.

    GC_PIRATE_AI_ENABLED=0 is a deployment hard-off and wins over both the
    runtime admin switch and the production default. This lets a universe ship
    with pirate AI permanently silent without mutating DB runtime_state.

    When the env hard-off is absent, GC-2611 semantics remain unchanged:
    runtime_state Soft-On/Off wins once set; otherwise production defaults on.
    """
    if is_pirates_ai_hard_disabled():
        return False

    raw = get_runtime_value(AI_ENABLED_RUNTIME_KEY, conn=conn)
    if raw is None:
        return is_production()
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def set_pirates_ai_enabled(enabled: bool, *, conn=None) -> None:
    set_runtime_value(AI_ENABLED_RUNTIME_KEY, "1" if enabled else "0", conn=conn)
