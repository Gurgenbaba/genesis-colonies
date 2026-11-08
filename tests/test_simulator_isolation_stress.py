"""Stress tests for the isolation of simulated universes: threads, reused worker processes, parallel processes (measurement tooling).

Different endgame curves and colonisation gates run in the same process (threads, a reused pool worker) and in parallel
processes.  Every universe must see exactly its own parameters and prices, and the process must be back to its defaults afterwards.
"""

from __future__ import annotations

import sys
import threading
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.planet_evolution import expansion_protocol as ep  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402

UNIVERSES: Tuple[Tuple[str, str], ...] = (
    ("legacy", "none"),
    ("uni1", "none"),
    ("legacy", "colony_gate_pl10"),
    ("uni1", "colony_gate_pl10"),
)
DWELL = 0.002


def _reference() -> Dict[Tuple[str, str], Dict[str, Any]]:
    """What each universe looks like when it runs alone (no concurrency)."""
    return {u: pj.universe_probe(*u) for u in UNIVERSES}


def _check(universe: Tuple[str, str], got: Dict[str, Any], ref: Dict[str, Any], base: Tuple[Any, ...]) -> List[str]:
    problems: List[str] = []
    if got["before"] != base or got["after"] != base:
        problems.append(f"{universe}: process not at its defaults around the run: {got['before']} -> {got['after']} (expected {base})")
    if got["inside"]["key"] != ref["inside"]["key"] or got["inside"]["key_after_dwell"] != ref["inside"]["key"]:
        problems.append(f"{universe}: key changed inside the universe: {got['inside']['key']} / {got['inside']['key_after_dwell']} vs {ref['inside']['key']}")
    if got["inside"]["gate"] != ref["inside"]["gate"]:
        problems.append(f"{universe}: colony gate {got['inside']['gate']} vs {ref['inside']['gate']}")
    if got["inside"]["price"] != ref["inside"]["price"]:
        problems.append(f"{universe}: price {got['inside']['price']} vs {ref['inside']['price']}")
    return problems


def _probe(args: Tuple[str, str]) -> Dict[str, Any]:  # module-level: picklable for the process pools
    curve, lever = args
    from scripts import player_journey_sim as sim

    return sim.universe_probe(curve, lever, DWELL)


def test_the_four_universes_really_differ():
    ref = _reference()
    prices = {u: r["inside"]["price"] for u, r in ref.items()}
    gates = {u: r["inside"]["gate"] for u, r in ref.items()}
    assert prices[("legacy", "none")] != prices[("uni1", "none")]  # the curve changes the L250 price by orders of magnitude
    assert prices[("legacy", "none")] == prices[("legacy", "colony_gate_pl10")]  # the gate does not
    assert gates[("legacy", "none")] == 15 and gates[("legacy", "colony_gate_pl10")] == 10 and gates[("uni1", "colony_gate_pl10")] == 10
    assert len({r["inside"]["key"] for r in ref.values()}) == 4  # four different cache keys


def test_threads_with_different_universes_never_see_each_other():
    ref, base = _reference(), pj.universe_key()
    problems: List[str] = []
    guard = threading.Lock()

    def worker(tid: int) -> None:
        for i in range(30):
            u = UNIVERSES[(tid + i) % len(UNIVERSES)]
            found = _check(u, pj.universe_probe(u[0], u[1], DWELL), ref[u], base)
            if found:
                with guard:
                    problems.extend(found)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120.0)
    assert not any(t.is_alive() for t in threads)
    assert problems == []
    assert pj.universe_key() == base and ep.COLONY_MATURITY_REQUIRED_LEVEL == 15


def test_a_reused_worker_process_does_not_carry_one_scenario_into_the_next():
    ref, base = _reference(), pj.universe_key()
    order = [UNIVERSES[i] for i in (0, 3, 0, 1, 2, 3, 1, 0, 2, 2)]  # one worker runs them all, in this order
    problems: List[str] = []
    with ProcessPoolExecutor(max_workers=1) as pool:
        for u, got in zip(order, pool.map(_probe, order)):
            problems += _check(u, got, ref[u], base)
    assert problems == []


def test_parallel_processes_with_different_universes_agree_with_the_reference():
    ref, base = _reference(), pj.universe_key()
    order = [UNIVERSES[i % len(UNIVERSES)] for i in range(16)]
    problems: List[str] = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        for u, got in zip(order, pool.map(_probe, order)):
            problems += _check(u, got, ref[u], base)
    assert problems == []


def test_whole_scenarios_back_to_back_leave_the_process_at_its_defaults():
    """The real entry point, with a different curve and gate each time, twice in one process."""
    base = pj.universe_key()
    for curve, lever in (("uni1", "colony_gate_pl10"), ("legacy", "none")):
        sc = pj.Scenario("stress", "S1", "optimizer", "mid", "none", 2.0, strategy="v2", asc="never", lever=lever)
        res = pj.run_scenario(sc, curve)
        assert res["invariants"]["ok"] and res["economy_curve"] == curve
        assert pj.universe_key() == base and ep.COLONY_MATURITY_REQUIRED_LEVEL == 15
