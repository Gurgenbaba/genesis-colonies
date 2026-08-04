"""Command Initiation — once-through do-first guidance (GC-Initiation Phase 1)."""

from __future__ import annotations

from .engine import ensure_player_initiation, initiation_schema_ready
from .progress import apply_gameplay_events
from .service import (
    count_initiation_attention,
    get_initiation_state,
    get_initiation_summary,
)

__all__ = [
    "apply_gameplay_events",
    "count_initiation_attention",
    "ensure_player_initiation",
    "get_initiation_state",
    "get_initiation_summary",
    "initiation_schema_ready",
]
