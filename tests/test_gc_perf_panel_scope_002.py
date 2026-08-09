"""GC-PERF-PANEL-SCOPE-002: heavy panels only for explicit panel_page / finish_source."""

from __future__ import annotations

from unittest.mock import patch

import app as app_module

pytest_plugins = ["tests.test_game_state_live"]


def test_unscoped_include_panel_builds_no_heavy_catalogs(game_client):
    client, _uid = game_client
    body = client.get("/api/game-state?include_panel=1").get_json()
    assert body.get("ok") is True
    assert "buildings_panel" not in body
    assert "techs" not in (body.get("research") or {})
    assert not (body.get("overview") or {}).get("rows")
    assert "defense" not in body
    assert "shipyard" not in body
    assert "auction_house" not in body
    assert "exchange" not in body
    assert "scrapyard" not in body
    assert "collector_exchange" not in body


def test_buildings_page_skips_defense_shipyard_auction(game_client):
    client, _uid = game_client
    body = client.get(
        "/api/game-state?include_panel=1&panel_page=buildings&panel_tab=resources"
    ).get_json()
    assert body.get("ok") is True
    assert "resources" in (body.get("buildings_panel") or {})
    assert "techs" not in (body.get("research") or {})
    assert "defense" not in body
    assert "shipyard" not in body
    assert "auction_house" not in body
    assert "exchange" not in body
    assert not (body.get("overview") or {}).get("rows")


def test_research_page_skips_buildings_catalog(game_client):
    client, _uid = game_client
    body = client.get("/api/game-state?include_panel=1&panel_page=research").get_json()
    assert body.get("ok") is True
    techs = (body.get("research") or {}).get("techs") or []
    assert len(techs) >= 1
    assert "buildings_panel" not in body
    assert "defense" not in body
    assert "shipyard" not in body
    assert "auction_house" not in body


def test_auction_bid_finish_source_maps_to_auction_only():
    assert app_module._resolve_effective_panel_page("", "api_auction_house_bid") == "auction_house"
    heavy = app_module._heavy_panels_for_page("auction_house")
    assert heavy == frozenset({"auction_house"})
    assert "buildings" not in heavy
    assert "overview" not in heavy


def test_auction_page_payload_skips_buildings_and_overview(game_client):
    """Auction-scoped panel must not build buildings/overview catalogs."""
    client, _uid = game_client
    calls = {"buildings": 0, "overview": 0}

    def _guard_buildings(*_a, **_k):
        calls["buildings"] += 1
        raise AssertionError("buildings catalog must not run for auction panel")

    def _guard_overview(*_a, **_k):
        calls["overview"] += 1
        raise AssertionError("overview rows must not run for auction panel")

    with patch("game.buildings.get_buildings_panel_rows", side_effect=_guard_buildings), patch(
        "game.buildings.get_overview_building_rows", side_effect=_guard_overview
    ):
        r = client.get("/api/game-state?include_panel=1&panel_page=auction-house")
    body = r.get_json() or {}
    assert r.status_code == 200
    assert body.get("ok") is True
    assert "buildings_panel" not in body
    assert not (body.get("overview") or {}).get("rows")
    assert calls["buildings"] == 0
    assert calls["overview"] == 0
    assert "defense" not in body
    assert "shipyard" not in body


def test_finish_source_legacy_sites_set_panel_page_contract():
    """Legacy include_panel=True sites must resolve via finish_source map."""
    mapping = app_module._FINISH_SOURCE_PANEL_PAGE
    assert mapping["api_auction_house_bid"] == "auction_house"
    assert mapping["api_exchange"] == "trader_hub"
    assert mapping["api_collector_exchange"] == "trader_hub"
    assert mapping["api_shipyard_build"] == "shipyard"
    assert mapping["api_defense_overview"] == "defense"
    assert mapping["api_research_start"] == "research"
    assert mapping["api_world_boss_companion_mission"] == "overview"
    assert mapping["api_world_boss_catch"] == "overview"
    assert (
        app_module._resolve_effective_panel_page("", "api_world_boss_companion_mission")
        == "overview"
    )
    assert "overview" in app_module._heavy_panels_for_page("overview")
    assert "game_state" not in mapping
    assert "game_state_panel" not in mapping


def test_panels_built_meta_on_scoped_buildings(game_client, monkeypatch):
    from game import live_state

    class _State:
        meta = {}
        phases = {}

    state = _State()
    monkeypatch.setattr(live_state, "_request_perf_state", lambda: state)
    client, _uid = game_client
    body = client.get(
        "/api/game-state?include_panel=1&panel_page=buildings&panel_tab=resources"
    ).get_json()
    assert body.get("ok") is True
    built = str(state.meta.get("panels_built") or "")
    assert "buildings" in built.split(",")
    assert "defense" not in built
    assert "auction_house" not in built
