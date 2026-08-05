"""Command Initiation — once-through do-first guidance (GC-Initiation Phase 1)."""

from __future__ import annotations

from .engine import credit_existing_progress, ensure_player_initiation, initiation_schema_ready
from .progress import apply_gameplay_events, maybe_record_page_visit_from_request, record_page_visit
from .service import (
    count_initiation_attention,
    get_initiation_state,
    get_initiation_summary,
)

__all__ = [
    "apply_gameplay_events",
    "count_initiation_attention",
    "credit_existing_progress",
    "ensure_player_initiation",
    "get_initiation_state",
    "get_initiation_summary",
    "initiation_schema_ready",
    "maybe_record_page_visit_from_request",
    "record_page_visit",
]
