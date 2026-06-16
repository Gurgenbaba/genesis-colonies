"""Region landmarks — atmospheric map points, no gameplay (GC-567B)."""

from __future__ import annotations

from typing import Any, Dict, List

# Static definitions — no migration. Genesis Core has no landmarks.
# layout_radius_world = distance from own hub (GC-571F outer discovery ring).
REGION_LANDMARKS: Dict[str, Dict[str, Any]] = {
    "broken_relay": {
        "label_key": "landmark_broken_relay",
        "flavor_key": "landmark_broken_relay_flavor",
        "region_key": "outer_rim",
        "layout_bearing_deg": 320,
        "layout_radius_world": 1020.0,
        "role_icon": "📡",
        "tone": "rim",
    },
    "mining_debris": {
        "label_key": "landmark_mining_debris",
        "flavor_key": "landmark_mining_debris_flavor",
        "region_key": "outer_rim",
        "layout_bearing_deg": 40,
        "layout_radius_world": 1080.0,
        "role_icon": "🪨",
        "tone": "rim",
    },
    "abandoned_colony": {
        "label_key": "landmark_abandoned_colony",
        "flavor_key": "landmark_abandoned_colony_flavor",
        "region_key": "outer_rim",
        "layout_bearing_deg": 350,
        "layout_radius_world": 1120.0,
        "role_icon": "🏚",
        "tone": "rim",
    },
    "ancient_beacon": {
        "label_key": "landmark_ancient_beacon",
        "flavor_key": "landmark_ancient_beacon_flavor",
        "region_key": "ancient_sector",
        "layout_bearing_deg": 48,
        "layout_radius_world": 1200.0,
        "role_icon": "🏺",
        "tone": "ancient",
    },
    "archive_vault": {
        "label_key": "landmark_archive_vault",
        "flavor_key": "landmark_archive_vault_flavor",
        "region_key": "ancient_sector",
        "layout_bearing_deg": 68,
        "layout_radius_world": 1280.0,
        "role_icon": "🗄",
        "tone": "ancient",
    },
    "silent_observatory": {
        "label_key": "landmark_silent_observatory",
        "flavor_key": "landmark_silent_observatory_flavor",
        "region_key": "ancient_sector",
        "layout_bearing_deg": 82,
        "layout_radius_world": 1350.0,
        "role_icon": "🔭",
        "tone": "ancient",
    },
    "void_signal": {
        "label_key": "landmark_void_signal",
        "flavor_key": "landmark_void_signal_flavor",
        "region_key": "dark_expanse",
        "layout_bearing_deg": 5,
        "layout_radius_world": 1420.0,
        "role_icon": "⚫",
        "tone": "dark",
    },
    "abyss_rift": {
        "label_key": "landmark_abyss_rift",
        "flavor_key": "landmark_abyss_rift_flavor",
        "region_key": "dark_expanse",
        "layout_bearing_deg": 340,
        "layout_radius_world": 1550.0,
        "role_icon": "🌀",
        "tone": "dark",
    },
    "dark_matter_scar": {
        "label_key": "landmark_dark_matter_scar",
        "flavor_key": "landmark_dark_matter_scar_flavor",
        "region_key": "dark_expanse",
        "layout_bearing_deg": 28,
        "layout_radius_world": 1680.0,
        "role_icon": "💠",
        "tone": "dark",
    },
}

_LANDMARK_ORDER: List[str] = [
    "broken_relay",
    "mining_debris",
    "abandoned_colony",
    "ancient_beacon",
    "archive_vault",
    "silent_observatory",
    "void_signal",
    "abyss_rift",
    "dark_matter_scar",
]


def _landmark_row(landmark_key: str, landmark: Dict[str, Any]) -> Dict[str, Any]:
    region_key = str(landmark.get("region_key") or "outer_rim")
    return {
        "node_kind": "landmark",
        "landmark_key": landmark_key,
        "label_key": str(landmark.get("label_key") or landmark_key),
        "flavor_key": str(landmark.get("flavor_key") or ""),
        "region_key": region_key,
        "region_label_key": f"imperium_region_{region_key}",
        "layout_bearing_deg": float(landmark.get("layout_bearing_deg") or 0),
        "layout_radius_world": float(landmark.get("layout_radius_world") or 1100),
        "role_icon": str(landmark.get("role_icon") or "✦"),
        "tone": str(landmark.get("tone") or "rim"),
        "empire_role_icon": str(landmark.get("role_icon") or "✦"),
        "is_interactive": True,
        "is_unlockable": False,
    }


def list_landmarks_for_map() -> List[Dict[str, Any]]:
    """All region landmarks for Command Map layout."""
    rows: List[Dict[str, Any]] = []
    for key in _LANDMARK_ORDER:
        landmark = REGION_LANDMARKS.get(key)
        if not landmark:
            continue
        rows.append(_landmark_row(key, landmark))
    return rows
