"""UNI1 launch contract: expedition cargo follows the canonical ship registry."""

from game.expedition_events import calculate_expedition_loot_cap
from game.fleet_defs import get_ship


def test_uni1_expedition_cargo_uses_current_hull_registry():
    skiff = get_ship("solar_skiff")
    atlas = get_ship("atlas_hauler")
    assert skiff and atlas

    solo = calculate_expedition_loot_cap({"solar_skiff": 1})
    with_escort = calculate_expedition_loot_cap(
        {"solar_skiff": 1, "falcon_interceptor": 10}
    )
    with_haulers = calculate_expedition_loot_cap(
        {"solar_skiff": 1, "atlas_hauler": 2}
    )

    assert solo == int(skiff["cargo"])
    assert with_escort == solo
    assert with_haulers == solo + 2 * int(atlas["cargo"])
