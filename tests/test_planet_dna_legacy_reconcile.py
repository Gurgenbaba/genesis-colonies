"""Legacy L15 DNA reveal reconciliation stays idempotent and never rerolls DNA."""

import sqlite3

import pytest

from game.planet_evolution import bootstrap


@pytest.fixture
def old_world(monkeypatch):
    c = sqlite3.connect(":memory:", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE planets (
            id INTEGER PRIMARY KEY,
            player_id INTEGER NOT NULL,
            planet_level INTEGER NOT NULL,
            dna_reveal_tier INTEGER NOT NULL,
            planet_class TEXT NOT NULL,
            dna_seed INTEGER NOT NULL,
            last_evolution_tick REAL NOT NULL,
            culture_archetype TEXT NOT NULL,
            is_homeworld INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE planet_culture (planet_id INTEGER PRIMARY KEY);
        CREATE TABLE planet_mechanics (planet_id INTEGER PRIMARY KEY);
        INSERT INTO planets VALUES (5, 9, 16, 1, 'terrestrial', 12345, 123456, 'frontier_settlers', 0);
        INSERT INTO planet_culture VALUES (5);
        INSERT INTO planet_mechanics VALUES (5);
        """
    )
    monkeypatch.setattr(bootstrap, "evolution_schema_ready", lambda conn: True)
    monkeypatch.setattr(bootstrap, "reload_definitions", lambda conn: None)
    monkeypatch.setattr(bootstrap, "expected_planet_class", lambda planet: "terrestrial")
    monkeypatch.setattr(bootstrap, "get_planet_dna", lambda planet_id, conn: {"hidden_traits": ["a", "b"]})
    monkeypatch.setattr(bootstrap, "ensure_planet_culture", lambda *args, **kwargs: None)
    monkeypatch.setattr(bootstrap, "generate_planet_dna", lambda **kwargs: pytest.fail("DNA must never reroll"))
    monkeypatch.setattr(bootstrap, "save_planet_dna", lambda *args, **kwargs: pytest.fail("DNA must never be replaced"))
    import game.planet_evolution.expansion_protocol as expansion
    monkeypatch.setattr(expansion, "bootstrap_legacy_establishment", lambda *args, **kwargs: None)
    compiled = []
    def compile_spy(planet_id, conn):
        tier = conn.execute("SELECT dna_reveal_tier FROM planets WHERE id=?", (planet_id,)).fetchone()[0]
        compiled.append((planet_id, tier))
    monkeypatch.setattr(bootstrap, "compile_planet_mechanics", compile_spy)
    yield c, compiled
    c.close()


def test_l15_legacy_reveal_repaired_exactly_once(old_world):
    c, compiled = old_world
    assert bootstrap.planet_evolution_needs_bootstrap(5, c) is True
    first = bootstrap.ensure_planet_evolution(5, c)
    assert first["ready"] and first["legacy_reveal_repaired"] is True
    assert first["dna_created"] is False
    assert c.execute("SELECT dna_reveal_tier FROM planets WHERE id=5").fetchone()[0] == 2
    assert compiled == [(5, 2)]
    assert bootstrap.planet_evolution_needs_bootstrap(5, c) is False
    second = bootstrap.ensure_planet_evolution(5, c)
    assert second["ready"] and second["dna_created"] is False
    assert compiled == [(5, 2)]


@pytest.mark.parametrize("level,tier", [(14, 1), (16, 0), (16, 2), (25, 3)])
def test_legacy_reconcile_never_changes_valid_or_masked_worlds(old_world, level, tier):
    c, compiled = old_world
    c.execute("UPDATE planets SET planet_level=?, dna_reveal_tier=? WHERE id=5", (level, tier))
    result = bootstrap.ensure_planet_evolution(5, c)
    assert result["ready"] is True
    assert c.execute("SELECT dna_reveal_tier FROM planets WHERE id=5").fetchone()[0] == tier
    assert compiled == []


def test_foreign_planet_state_is_authorized_before_bootstrap(monkeypatch, old_world):
    from game.planet_evolution import service
    c, compiled = old_world
    monkeypatch.setattr(service, "ensure_planet_evolution", lambda *a: pytest.fail("foreign bootstrap blocked"))
    assert service.get_planet_state_payload(5, player_id=10, conn=c) == {"ok": False, "error": "not_owner"}
    assert c.execute("SELECT dna_reveal_tier FROM planets WHERE id=5").fetchone()[0] == 1
    assert compiled == []
