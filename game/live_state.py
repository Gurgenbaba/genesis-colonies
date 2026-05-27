"""
Request-scoped guard for the single-pass live refresh pipeline.
"""

from __future__ import annotations


def mark_request_live_refreshed() -> None:
    """Mark that finish + derived sync already ran this HTTP request."""
    try:
        from flask import g, has_request_context

        if has_request_context():
            g.gc_live_state_refreshed = True
    except ImportError:
        pass


def request_live_state_already_refreshed() -> bool:
    try:
        from flask import g, has_request_context

        return bool(has_request_context() and getattr(g, "gc_live_state_refreshed", False))
    except ImportError:
        return False


def coerce_skip_finish(skip_finish: bool) -> bool:
    """
    After refresh_player_live_state in the same request, force skip_finish=True
    so get_research_status / get_build_queue_status never run a second finish pass.
    """
    if skip_finish:
        return True
    return request_live_state_already_refreshed()
