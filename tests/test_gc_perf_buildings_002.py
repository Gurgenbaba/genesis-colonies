"""GC-PERF-BUILDINGS-002 — dedupe DB-backed modifier probes across target resolvers."""

from __future__ import annotations

import re
from unittest.mock import patch

from game.buildings import BuildingsPanelContext, get_buildings_panel_rows
from game.db import db
from game.effects import EffectResolver
from game.effects.effect_resolver import clear_effect_resolver_cache
from game.models import get_homeworld, get_planet_buildings, get_research_levels

pytest_plugins = ["tests.test_game_state_live"]

_SELECT = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def _trace_selects(conn, fn):
    statements: list[str] = []

    def trace(stmt: str) -> None:
        if _SELECT.match(stmt):
            statements.append(" ".join(stmt.split()))

    conn.set_trace_callback(trace)
    try:
        result = fn()
    finally:
        conn.set_trace_callback(None)
    return result, statements


def _legacy_unshared_target_resolver(
    self: BuildingsPanelContext, building_type: str, target_level: int
) -> EffectResolver:
    """Control path reproducing BUILDINGS-002's pre-fix target resolver behavior."""
    key = (str(building_type), int(target_level))
    cached = self._bumped_resolvers.get(key)
    if cached is not None:
        return cached
    bumped = dict(self.buildings)
    bumped[building_type] = int(target_level)
    base = self.resolver
    resolver = EffectResolver(
        bumped,
        self.research_levels,
        settings=base._settings,
        player_id=base.player_id,
        planet_id=base.planet_id,
        planet_position=base.planet_position,
        galaxy_id=base.galaxy_id,
        conn=base._conn,
    )
    self._bumped_resolvers[key] = resolver
    return resolver


def test_buildings_panel_target_resolvers_cut_repeated_sql_without_payload_drift(game_client):
    _client, uid = game_client
    conn = db()
    try:
        planet = get_homeworld(int(uid), conn=conn)
        assert planet is not None
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        levels = get_research_levels(int(uid), conn=conn)

        def build_panel():
            return get_buildings_panel_rows(
                planet,
                buildings,
                active_tab="resources",
                conn=conn,
                research_levels=levels,
            )

        clear_effect_resolver_cache()
        with patch.object(
            BuildingsPanelContext,
            "resolver_at_target",
            _legacy_unshared_target_resolver,
        ):
            legacy_rows, legacy_selects = _trace_selects(conn, build_panel)

        clear_effect_resolver_cache()
        shared_rows, shared_selects = _trace_selects(conn, build_panel)

        assert shared_rows == legacy_rows
        assert len(legacy_selects) > 0
        assert len(shared_selects) < len(legacy_selects), (
            f"expected fewer SELECTs with shared probes: "
            f"legacy={len(legacy_selects)} shared={len(shared_selects)}"
        )
        # This is intentionally relative to the reproduced legacy path, not a
        # machine-specific latency threshold. External DB probes should collapse
        # to roughly one panel snapshot instead of once per synthetic resolver.
        assert len(shared_selects) <= int(len(legacy_selects) * 0.65), (
            f"BUILDINGS-002 SQL reduction too small: "
            f"legacy={len(legacy_selects)} shared={len(shared_selects)}"
        )
    finally:
        clear_effect_resolver_cache()
        conn.close()


def test_shared_probe_cache_keeps_building_level_modifiers_dynamic(game_client):
    _client, uid = game_client
    conn = db()
    try:
        planet = get_homeworld(int(uid), conn=conn)
        assert planet is not None
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        levels = get_research_levels(int(uid), conn=conn)
        ctx = BuildingsPanelContext.for_planet(
            planet,
            buildings,
            levels,
            1.0,
            conn=conn,
        )

        base = ctx.resolver
        academy_now = int(buildings.get("academy", 0) or 0)
        target = ctx.resolver_at_target("academy", academy_now + 1)

        assert target.shared_external_probe_cache() is base.shared_external_probe_cache()
        base_speed = float(base.get_modifiers()["research_time_speed"])
        target_speed = float(target.get_modifiers()["research_time_speed"])
        expected_ratio = (1.0 + 0.05 * (academy_now + 1)) / (1.0 + 0.05 * academy_now)
        assert target_speed / base_speed == pytest.approx(expected_ratio)
        assert target_speed > base_speed
    finally:
        clear_effect_resolver_cache()
        conn.close()


def test_mine_evolution_panel_rank_read_reuses_request_connection(game_client):
    _client, uid = game_client
    conn = db()
    try:
        planet = get_homeworld(int(uid), conn=conn)
        assert planet is not None
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        levels = get_research_levels(int(uid), conn=conn)

        def forbid_orphan_db(*_args, **_kwargs):
            raise AssertionError("Mine Evolution opened an orphan db() during buildings panel read")

        with patch("game.mine_evolution.service.db", side_effect=forbid_orphan_db):
            rows = get_buildings_panel_rows(
                planet,
                buildings,
                active_tab="resources",
                conn=conn,
                research_levels=levels,
            )
        assert rows.get("resources")
    finally:
        clear_effect_resolver_cache()
        conn.close()
