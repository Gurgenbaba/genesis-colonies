"""Read-only Planet Trait Atlas. Planet DNA and definitions remain canonical.

The Atlas never reveals unrevealed traits of an individual world; the catalogue
describes possibilities, not hidden information about a specific planet.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Mapping

from .definitions import get_research_defs, get_specializations, get_traits
from .dna import all_trait_keys
from .repository import _json_loads
from .ux_copy import trait_effect_lines


_TRAIT_COLUMNS = (
    "geology_traits_json",
    "atmosphere_traits_json",
    "environment_traits_json",
    "anomaly_traits_json",
    "hidden_traits_json",
)
_TRAIT_GROUPS = (
    "geology_traits",
    "atmosphere_traits",
    "environment_traits",
    "anomaly_traits",
    "hidden_traits",
)
_RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4}


def _visible_traits(dna: Mapping[str, Any], reveal: int) -> set[str]:
    """Respect the same establishment visibility gate as the evolution page."""
    if reveal <= 0:
        return set()
    return set(all_trait_keys(dict(dna), reveal_tier=min(2, reveal)))


def _catalogue_uses() -> tuple[Dict[str, List[dict]], Dict[str, List[dict]]]:
    research: Dict[str, List[dict]] = {}
    for key, definition in get_research_defs().items():
        req = definition.get("requirements") or {}
        for trait in req.get("traits_any") or []:
            research.setdefault(str(trait), []).append(
                {"key": str(key), "label_key": definition.get("label_key") or str(key)}
            )

    specializations: Dict[str, List[dict]] = {}
    for key, definition in get_specializations().items():
        for trait in definition.get("required_traits_any") or []:
            specializations.setdefault(str(trait), []).append(
                {"key": str(key), "label_key": definition.get("label_key") or f"spec_{key}"}
            )
    return research, specializations


def build_trait_atlas(
    *,
    planet_id: int,
    player_id: int,
    dna: Mapping[str, Any],
    reveal_tier: int,
    conn: sqlite3.Connection,
) -> dict:
    """Show trait opportunities and revealed traits across OWNED colonies.

    A single bounded query is used for the empire view. No per-trait DB reads,
    no other players, and no hidden DNA keys are returned for locked planets.
    """
    definitions = get_traits()
    research_uses, spec_uses = _catalogue_uses()
    current_known = _visible_traits(dna, reveal_tier)

    owned: Dict[str, List[dict]] = {}
    for record in conn.execute(
        """
        SELECT p.id, p.name, p.dna_reveal_tier,
               d.geology_traits_json, d.atmosphere_traits_json,
               d.environment_traits_json, d.anomaly_traits_json, d.hidden_traits_json
          FROM planets p
          LEFT JOIN planet_dna d ON d.planet_id = p.id
         WHERE p.player_id = ?
         ORDER BY p.id
        """,
        (int(player_id),),
    ).fetchall():
        world = dict(record)
        reveal = int(world.get("dna_reveal_tier") or 0)
        if reveal <= 0:
            continue  # Establishment must not leak an outpost's hidden identity.
        world_dna = {
            group: _json_loads(world.get(column), [])
            for group, column in zip(_TRAIT_GROUPS, _TRAIT_COLUMNS)
        }
        for trait in _visible_traits(world_dna, reveal):
            owned.setdefault(trait, []).append(
                {
                    "planet_id": int(world["id"]),
                    "name": str(world.get("name") or ""),
                    "is_current": int(world["id"]) == int(planet_id),
                }
            )

    all_on_planet = set(all_trait_keys(dict(dna), reveal_tier=2))
    unknown_count = max(0, len(all_on_planet) - len(current_known))
    rows = []
    for key, definition in definitions.items():
        matches = owned.get(str(key), [])
        state = (
            "current" if str(key) in current_known
            else "empire" if matches
            else "unfound"
        )
        rows.append(
            {
                "key": str(key),
                "label_key": f"trait_{key}",
                "rarity": str(definition.get("rarity") or "common"),
                "rarity_label_key": f"pe_rarity_{definition.get('rarity') or 'common'}",
                "category": str(definition.get("category") or "geology"),
                "category_label_key": f"pe_cat_{definition.get('category') or 'geology'}",
                "status": state,
                "effect_lines": trait_effect_lines(definition),
                "owned_planets": matches,
                "techs": research_uses.get(str(key), []),
                "specializations": spec_uses.get(str(key), []),
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row["status"] == "current" else 1 if row["status"] == "empire" else 2,
            -_RARITY_ORDER.get(row["rarity"], 0),
            row["key"],
        )
    )

    return {
        "entries": rows,
        "catalogue_count": len(rows),
        "on_current": len(current_known & definitions.keys()),
        "known_empire": sum(1 for row in rows if row["status"] != "unfound"),
        "unknown_on_current": unknown_count if reveal_tier > 0 else None,
        "reveal_tier": int(reveal_tier),
        "next_reveal_level": 3 if reveal_tier < 1 else 15 if reveal_tier < 2 else None,
        "can_see_current": reveal_tier > 0,
    }
