"""Ship unlock requirement summaries for client UI."""

from game.ship_requirements import requirements_summary_for_client


def test_requirements_summary_omits_orbital_shipyard_building_dup():
    summary = requirements_summary_for_client(
        "atlas_hauler",
        buildings={"orbital_shipyard": 3, "research_lab": 5},
        research={"storage_tech": 2, "mining_tech": 3},
    )
    keys = [(item["type"], item["key"]) for item in summary["items"]]
    assert ("building", "orbital_shipyard") not in keys
    assert ("research", "storage_tech") in keys
    assert ("research", "mining_tech") in keys
    assert summary["met"] is False


def test_requirements_summary_includes_non_shipyard_buildings():
    summary = requirements_summary_for_client(
        "falcon_interceptor",
        buildings={"orbital_shipyard": 2, "barracks": 0},
        research={"weapon_tech": 5},
    )
    keys = [(item["type"], item["key"]) for item in summary["items"]]
    assert ("building", "barracks") in keys
    assert ("building", "orbital_shipyard") not in keys
    assert ("research", "weapon_tech") in keys
