"""
Placeholder / preview pages for upcoming modules (nav with Dev badge).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

FeaturePair = Tuple[str, str]

PLACEHOLDER_MODULES: Dict[str, Dict[str, Any]] = {
    "auction_house": {
        "slug": "auction-house",
        "endpoint": "auction_house_view",
        "title_key": "nav_auction_house",
        "hint_key": "placeholder_auction_hint",
        "intro_key": "placeholder_auction_intro",
        "note_key": "placeholder_auction_note",
        "features": [
            ("placeholder_auction_f1_title", "placeholder_auction_f1_desc"),
            ("placeholder_auction_f2_title", "placeholder_auction_f2_desc"),
            ("placeholder_auction_f3_title", "placeholder_auction_f3_desc"),
        ],
        "pills": [
            "placeholder_auction_pill_1",
            "placeholder_auction_pill_2",
            "placeholder_auction_pill_3",
        ],
    },
    "skilltree": {
        "slug": "skilltree",
        "endpoint": "skilltree_view",
        "title_key": "nav_skilltree",
        "hint_key": "placeholder_skilltree_hint",
        "intro_key": "placeholder_skilltree_intro",
        "note_key": "placeholder_skilltree_note",
        "features": [
            ("placeholder_skilltree_f1_title", "placeholder_skilltree_f1_desc"),
            ("placeholder_skilltree_f2_title", "placeholder_skilltree_f2_desc"),
            ("placeholder_skilltree_f3_title", "placeholder_skilltree_f3_desc"),
        ],
        "pills": [
            "placeholder_skilltree_pill_1",
            "placeholder_skilltree_pill_2",
            "placeholder_skilltree_pill_3",
        ],
    },
}


def get_placeholder_module(key: str) -> Dict[str, Any] | None:
    return PLACEHOLDER_MODULES.get(str(key or "").strip())


def list_placeholder_modules() -> List[Dict[str, Any]]:
    return list(PLACEHOLDER_MODULES.values())


def placeholder_nav_keys() -> List[str]:
    return list(PLACEHOLDER_MODULES.keys())
