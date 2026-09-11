"""Ranking public facade — GC-RANKING-PAGE-004.

The mature ranking engine lives in ``ranking_core``. This facade keeps the historic
``game.ranking`` import surface intact while widening the public 100-row payload so
the browser can expose page 2+ without changing score/order semantics.

Presence source contract: get_effective_last_seen_by_ids.
"""

from __future__ import annotations

import sys as _sys

from . import ranking_core as _core

RANKING_UI_PAGE_SIZE = 100
_bounded_build_ranking_api_payload = _core.build_ranking_api_payload


def build_ranking_api_payload(current_player_id: int, *, limit: int = 100, refresh: bool = False):
    requested_limit = max(1, int(limit or RANKING_UI_PAGE_SIZE))
    if requested_limit != RANKING_UI_PAGE_SIZE:
        return _bounded_build_ranking_api_payload(
            int(current_player_id),
            limit=requested_limit,
            refresh=refresh,
        )

    raw = _core._build_ranking_api_payload_raw(
        int(current_player_id),
        limit=_core._SQL_ALL_ROWS_LIMIT,
        refresh=refresh,
    )
    raw["pagination"] = {
        "page_size": RANKING_UI_PAGE_SIZE,
        "total_players": len(raw.get("top_players") or []),
        "total_alliances": len(raw.get("top_alliances") or []),
    }
    return _core._json_safe_bigints(raw)


_core.RANKING_UI_PAGE_SIZE = RANKING_UI_PAGE_SIZE
_core.build_ranking_api_payload = build_ranking_api_payload
_sys.modules[__name__] = _core
