"""GC-EFFECT-CACHE-CONN-001 — cached resolvers stay bound to one DB checkout."""

from __future__ import annotations

import sqlite3

from game.effects.effect_resolver import clear_effect_resolver_cache, get_effect_resolver


def test_resolver_cache_reuses_same_checkout_but_not_a_new_one():
    clear_effect_resolver_cache()
    conn1 = sqlite3.connect(":memory:")
    conn2 = sqlite3.connect(":memory:")
    buildings = {"metal_mine": 10, "planet_core_nexus": 2}
    research = {}
    planet = {"id": 77, "galaxy": 1, "position": 3}
    try:
        first = get_effect_resolver(
            9,
            buildings=buildings,
            research=research,
            planet=planet,
            conn=conn1,
        )
        same_checkout = get_effect_resolver(
            9,
            buildings=buildings,
            research=research,
            planet=planet,
            conn=conn1,
        )
        assert same_checkout is first

        second = get_effect_resolver(
            9,
            buildings=buildings,
            research=research,
            planet=planet,
            conn=conn2,
        )
        assert second is not first
        assert second._conn is conn2

        conn1.close()
        assert conn2.execute("SELECT 1").fetchone()[0] == 1
        assert second._conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        try:
            conn1.close()
        except Exception:
            pass
        conn2.close()
        clear_effect_resolver_cache()
