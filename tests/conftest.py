"""
Pytest hooks for Genesis Colonies.

GC-PERF-PG-PARITY-001: load isolated Postgres fixtures from pg_fixtures.py
so session-scoped dependencies resolve correctly.
"""

import pytest

pytest_plugins = ["pg_fixtures"]


@pytest.fixture(autouse=True)
def _reset_auth_rate_limits_between_tests():
    """`game.security._LOGIN_BUCKETS`/`_REGISTER_BUCKETS` are process-global
    dicts keyed by client IP, and the Flask test client always uses the same
    IP. Since `game.security` is never `importlib.reload()`-ed between tests
    (only `app`/`game.models`/`game.db` typically are), those buckets
    otherwise accumulate across the whole pytest session and start
    rate-limiting unrelated tests' logins once ~10 logins have happened
    anywhere before them — a real, reproducible cross-test contamination
    bug, not flakiness. `game.security.reset_auth_rate_limits()` already
    existed as the canonical fix for exactly this (previously only called
    manually by a couple of test files); making it autouse closes the gap
    for every test instead of leaving most of the suite exposed.
    """
    from game.security import reset_auth_rate_limits

    reset_auth_rate_limits()
    yield


def unlock_colony_slots(conn, homeworld_id: int, slots: int = 1) -> None:
    """Bump a homeworld's `planet_level` to unlock `slots` additional colony
    slots for `colonize_planet()` (GC-976A gate,
    `game/planet_evolution/expansion_protocol.py::EXPANSION_SLOT_GATES`).

    Fixtures predating GC-976A used to assume a fresh homeworld could found a
    2nd/3rd colony unconditionally; the evolution-slot gate now blocks that
    with `planet_evolution_colony_slot_required` unless the homeworld has
    reached the required level. Shared here (instead of duplicated per test
    file) since it's pure test setup, not game logic under test.

    `slots` beyond the hardcoded `EXPANSION_SLOT_GATES` table (currently up to
    6) are resolved via the same extrapolation the production code uses for
    later slots (`next_expansion_slot_homeworld_level`), instead of capping at
    the last table entry — needed by tests that colonize more than 6 times.

    Monotonic (`MAX(planet_level, required)`): a test that first unlocks 1
    slot and later needs a 2nd (e.g. via a second helper call after already
    founding a colony) must not have its homeworld's level *lowered* back
    down to the 1-slot threshold, which would re-lock the slot it already
    used.
    """
    from game.planet_evolution.expansion_protocol import next_expansion_slot_homeworld_level

    required_level = next_expansion_slot_homeworld_level(int(slots) - 1)
    conn.execute(
        "UPDATE planets SET planet_level = MAX(planet_level, ?) WHERE id = ?;",
        (int(required_level), int(homeworld_id)),
    )
    conn.commit()
