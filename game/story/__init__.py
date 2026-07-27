"""Genesis Story Ops — immersive lore arcs / side ops (EPIC-25)."""

from __future__ import annotations

from .engine import (
    advance_active_beat,
    apply_choice,
    ensure_player_story,
)
from .progress import apply_gameplay_events
from .service import (
    count_story_attention,
    get_story_state,
    get_story_summary,
)

__all__ = [
    "advance_active_beat",
    "apply_choice",
    "apply_gameplay_events",
    "count_story_attention",
    "ensure_player_story",
    "get_story_state",
    "get_story_summary",
]
