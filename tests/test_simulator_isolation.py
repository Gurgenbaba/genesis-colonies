"""Isolation of simulated universes inside one process (measurement tooling, no game change).

The journey simulator patches process-global state while it runs (endgame curve, colony gate, database path, environment) and
caches prices.  Different universe parameters must never leak into each other - not through a stale cache entry, and not through
a second thread that runs a scenario at the same time.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game import production_formula as pf  # noqa: E402
from game.economy_balance import power_upgrade_cost  # noqa: E402
from game.planet_evolution import expansion_protocol as ep  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402

WAIT = 10.0


def _price(level: int):
    return tuple(pj._upgrade_cost("metal_mine", level))


# ---------------------------------------------------------------------------
# Caches are keyed by the universe
# ---------------------------------------------------------------------------


def test_price_cache_never_serves_a_price_of_another_curve_without_any_clearing():
    pj._upgrade_cost.cache_clear()
    outside = _price(250)  # default (legacy) curve, cached
    with pj.economy_curve("uni1"):
        inside = _price(250)  # same level, other curve: must be a different, correct price
        assert inside == tuple(power_upgrade_cost("metal_mine", 251))
    assert outside != inside
    assert _price(250) == outside  # and the legacy price is still served outside
    assert outside == tuple(power_upgrade_cost("metal_mine", 251))


def test_price_cache_order_does_not_matter():
    pj._upgrade_cost.cache_clear()
    with pj.economy_curve("uni1"):
        first = _price(300)
    outside = _price(300)
    with pj.economy_curve("uni1"):
        assert _price(300) == first
    assert first != outside


def test_universe_key_covers_curve_and_gate_and_restores():
    base = pj.universe_key()
    with pj.economy_curve("uni1"):
        k_curve = pj.universe_key()
        with pj.lever_context("colony_gate_pl10"):
            k_gate = pj.universe_key()
    assert len({base, k_curve, k_gate}) == 3
    assert k_curve[0] == "active" and k_gate[3] == 10 and base[3] == 15
    assert pj.universe_key() == base


def test_research_payment_cache_is_keyed_too():
    pj._research_payment.cache_clear()
    args = ("mining_tech", 60, 10**9, 1.0, 5)
    with pj.economy_curve("uni1"):
        inside = tuple(pj._research_payment(*args))
    outside = tuple(pj._research_payment(*args))
    from game.research import get_research_payment_cost

    assert outside == tuple(get_research_payment_cost(args[0], args[1], cost_context={"empire_combined_per_hour": args[2], "maturity_index": args[3], "world_count": args[4]}))
    with pj.economy_curve("uni1"):
        assert tuple(pj._research_payment(*args)) == inside


# ---------------------------------------------------------------------------
# One universe at a time
# ---------------------------------------------------------------------------


def _hold(context_factory, entered: threading.Event, release: threading.Event, seen: list):
    with context_factory():
        seen.append(pj.universe_key())
        entered.set()
        release.wait(WAIT)
        seen.append(pj.universe_key())


def test_a_second_thread_cannot_enter_a_universe_while_another_is_running():
    entered, release, seen_a = threading.Event(), threading.Event(), []
    a = threading.Thread(target=_hold, args=(lambda: pj.economy_curve("uni1"), entered, release, seen_a))
    a.start()
    assert entered.wait(WAIT)
    seen_b: list = []
    b_done = threading.Event()

    def b():
        with pj.lever_context("colony_gate_pl10"):  # a different universe: default curve, gate 10
            seen_b.append(pj.universe_key())
        b_done.set()

    tb = threading.Thread(target=b)
    tb.start()
    assert not b_done.wait(0.3)  # blocked while A holds its curve
    release.set()
    a.join(WAIT)
    assert b_done.wait(WAIT)
    tb.join(WAIT)
    # neither universe ever saw the other's parameters
    assert seen_a[0] == seen_a[1] and seen_a[0][0] == "active" and seen_a[0][3] == 15
    assert seen_b == [("legacy", seen_b[0][1], seen_b[0][2], 10)] or (seen_b[0][0] != "active" and seen_b[0][3] == 10)
    assert pj.universe_key()[0] != "active" and ep.COLONY_MATURITY_REQUIRED_LEVEL == 15


def test_same_thread_may_nest_contexts():
    with pj.economy_curve("uni1"), pj.lever_context("colony_gate_pl10"), pj.economy_curve("uni1"):
        assert pj.universe_key()[0] == "active" and pj.universe_key()[3] == 10
    assert pj.universe_key()[3] == 15 and pf.ENDGAME_ECONOMY_MODE != "active"


def test_sandbox_holds_the_universe_lock_for_its_whole_life():
    entered, release = threading.Event(), threading.Event()

    def a():
        with pj.Sandbox():
            entered.set()
            release.wait(WAIT)

    ta = threading.Thread(target=a)
    ta.start()
    assert entered.wait(60.0)
    got: list = []

    def probe():
        got.append(pj.SIM_LOCK.acquire(blocking=False))
        if got[-1]:
            pj.SIM_LOCK.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join(WAIT)
    assert got == [False]  # another thread cannot start a scenario while the sandbox is alive
    release.set()
    ta.join(WAIT)
    t2 = threading.Thread(target=probe)
    t2.start()
    t2.join(WAIT)
    assert got == [False, True]


def test_failed_sandbox_start_releases_the_lock(monkeypatch):
    def boom(self):
        raise RuntimeError("sandbox start failed")

    monkeypatch.setattr(pj.Sandbox, "_enter", boom)
    with pytest.raises(RuntimeError):
        with pj.Sandbox():
            pass
    got: list = []

    def probe():
        got.append(pj.SIM_LOCK.acquire(blocking=False))
        if got[-1]:
            pj.SIM_LOCK.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join(WAIT)
    assert got == [True]


def test_a_context_that_raises_still_restores_the_universe():
    base = pj.universe_key()
    with pytest.raises(ValueError):
        with pj.economy_curve("uni1"), pj.lever_context("colony_gate_pl10"):
            raise ValueError("scenario failed")
    assert pj.universe_key() == base
