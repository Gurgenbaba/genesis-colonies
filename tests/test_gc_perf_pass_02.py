"""GC-PERF-PASS-02 — request connection reuse regressions."""

from __future__ import annotations

pytest_plugins = ["tests.test_game_state_live"]


def test_game_state_research_modifiers_reuses_request_connection(game_client, monkeypatch):
    import game.logic as logic

    client, _pid = game_client
    real = logic.get_research_modifiers
    seen = []

    def wrapped(user_id, conn=None):
        seen.append(conn)
        return real(user_id, conn=conn)

    monkeypatch.setattr(logic, "get_research_modifiers", wrapped)
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert seen
    assert all(conn is not None for conn in seen)


def test_resolver_identity_uses_loaded_planet_fields_without_coordinate_db_probe(monkeypatch):
    import game.galaxy as galaxy
    from game.effects.effect_resolver import clear_effect_resolver_cache, get_effect_resolver

    clear_effect_resolver_cache()

    def forbidden(_planet):
        raise AssertionError("resolver identity must not call get_planet_coordinates")

    monkeypatch.setattr(galaxy, "get_planet_coordinates", forbidden)
    resolver = get_effect_resolver(
        7,
        buildings={"metal_mine": 3},
        research={"energy_tech": 2},
        settings={},
        planet={"id": 99, "galaxy": 1, "system": 42, "position": 3},
    )
    assert resolver.planet_id == 99
    assert resolver.galaxy_id == 1
    assert resolver.planet_position == 3
    clear_effect_resolver_cache()
