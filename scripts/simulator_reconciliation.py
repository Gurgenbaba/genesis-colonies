#!/usr/bin/env python3
"""Reconciliation of the two long-horizon mine simulators (measurement only, no game change).

Why this exists
---------------
Two deterministic tools answer "how long does a mine need from L200 to L300?" with very different numbers:

* ``scripts/sim_ascension_breakthroughs.py`` (the *record-mine control*): 887 days.
* ``scripts/player_journey_sim.py`` (the *journey player*, ``never`` arm): about 325 days for the metal mine.

Both call the same canonical owners (``power_upgrade_cost`` / ``get_upgrade_cost``, ``production_formula``,
``building_progress_floor_seconds``).  They differ in the *setup*.  This module lines the setup up one assumption at a
time (a ladder) and prices every rung with the canonical owners, so the 887 -> 325 gap is split into named causes:

    R0  control as published (neutral modifiers, one mine, one currency)
    R1  + canonical production modifiers of the journey at L200 (slot, temperature, mining / drone / crystal tech)
    R2  + research continues exactly as the journey bought it during the climb
    R3  + second currency: crystal is paid from the crystal mine (frozen at its L200 depth, no Trader)
    R4  + the crystal mine is upgraded alongside, in the order the journey did it
    R5  + the other spending the journey actually did in that window (research, solar, storage, infrastructure)
    J   the journey as measured

Nothing here is a second game engine: rates come from ``production_formula`` with the journey's research state, prices
from ``get_upgrade_cost``, the construction floor from ``building_progress_floor_seconds``.  The ladder is a
*decomposition*, not a forecast.  Tests pin the rung arithmetic to the canonical ``EffectResolver``.

Run::

    python scripts/simulator_reconciliation.py --out-json artifacts/reconciliation/latest.json \
        --out-md docs/GC_SIMULATOR_RECONCILIATION_REPORT.md
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game import production_formula as pf  # noqa: E402
from game.time_floors import building_progress_floor_seconds  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402

RECON_VERSION = "simulator-reconciliation/1"
STYLES: Tuple[str, ...] = ("casual", "active", "optimizer")
START_LEVEL = 200
END_LEVEL = 300
WINDOWS: Tuple[Tuple[int, int], ...] = ((200, 300), (100, 200))  # metal-mine windows that are reconciled; (200, 300) is the headline
MARK_LEVELS: Tuple[int, ...] = (100, 150, 200, 250, 300)
HORIZON_DAYS_AFTER_START: Tuple[float, ...] = (182.5, 365.0)
HORIZON_MAX_LEVEL = 420
DEFAULT_DAYS = 900.0  # long enough for the slowest style (casual) to reach L300 with the metal mine
DAY_H = 24.0
EPS = 1e-9

# ladder rungs: key -> (label, kwargs of climb())
RUNGS: Tuple[Tuple[str, str, Dict[str, Any]], ...] = (
    ("R0", "control as published: neutral modifiers, one mine, one currency", dict(mods="neutral", currencies="one", crystal="none", side=False, caps=False, stock=False)),
    ("R1", "+ canonical production modifiers on the window's first day (slot, mining / drone tech)", dict(mods="frozen", currencies="one", crystal="none", side=False, caps=False, stock=False)),
    ("R2", "+ research continues as the journey bought it", dict(mods="timeline", currencies="one", crystal="none", side=False, caps=False, stock=False)),
    ("R3", "+ second currency: crystal from a crystal mine that is upgraded alongside (journey's order), no Trader", dict(mods="timeline", currencies="two", crystal="lockstep", side=False, caps=False, stock=False)),
    ("R4", "+ other spending of the window (research, solar, storage, nexus ...) as the journey's measured share of production", dict(mods="timeline", currencies="two", crystal="lockstep", side=True, caps=False, stock=False)),
    ("R5", "+ depots: storage capacity of the journey's storage buildings and tech (canonical resolver); surplus above it is lost", dict(mods="timeline", currencies="two", crystal="lockstep", side=True, caps=True, stock=False)),
    ("R6", "+ construction time: a level produces only after the canonical build time; the two mines share one serial queue", dict(mods="timeline", currencies="two", crystal="lockstep", side=True, caps=True, latency=True, stock=False)),
    ("R6s", "+ stock on hand when the window began", dict(mods="timeline", currencies="two", crystal="lockstep", side=True, caps=True, latency=True, stock=True)),
)
# Trader branch: crystal and metal fungible 1:1 (what the canonical Trader gives for crystal -> metal, without its spread / limit)
TRADER_RUNGS: Tuple[Tuple[str, str, Dict[str, Any]], ...] = (
    ("P3", "pooled 1:1 (Trader upper bound), crystal mine upgraded alongside", dict(mods="timeline", currencies="pooled", crystal="lockstep", side=False, caps=False, stock=False)),
    ("P4", "+ other spending (measured share)", dict(mods="timeline", currencies="pooled", crystal="lockstep", side=True, caps=False, stock=False)),
    ("P5", "+ construction time + start stock", dict(mods="timeline", currencies="pooled", crystal="lockstep", side=True, caps=False, latency=True, stock=True)),
)

BUILD_FIELDS = ("t", "key", "target", "cost_m", "cost_c", "stock_m", "stock_c")


@contextlib.contextmanager
def uni1_curve():
    """UNI1 endgame curve, serialised against other simulated universes in this process.

    The simulator's price caches are keyed by the active universe (endgame curve, colony gate), so a lookup under another
    curve can no longer serve a stale price; the caches are still cleared on exit to bound memory.
    """
    with pj.SIM_LOCK, pj.economy_curve("uni1"):
        try:
            yield
        finally:
            pj._upgrade_cost.cache_clear()


# ---------------------------------------------------------------------------
# Recording the journey (a subclass: the simulator itself is untouched)
# ---------------------------------------------------------------------------


class RecordingJourney(pj.Journey):
    """The unchanged journey simulator plus a read-only log of world 0's builds, research and window marks."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.builds: List[List[Any]] = []
        self.research_log: List[List[Any]] = []
        self.marks: Dict[str, Dict[str, Any]] = {}

    def finish_build(self, w: pj.World, job: pj.Job) -> None:  # type: ignore[override]
        before = len(self.completed_ids)
        super().finish_build(w, job)
        if len(self.completed_ids) == before or w.idx != 0:  # duplicate completion or a colony
            return
        self.builds.append([round(self.t / pj.DAY, 6), job.key, int(job.target), int(job.cost_m), int(job.cost_c), float(w.metal), float(w.crystal)])
        if job.key == "metal_mine" and int(job.target) in MARK_LEVELS:
            self.marks[str(int(job.target))] = {
                "day": round(self.t / pj.DAY, 6),
                "spend_metal": {k: float(v) for k, v in self.spend.items()},
                "spend_crystal": {k: float(v) for k, v in self.spend_c.items()},
                "stock_metal": float(w.metal),
                "stock_crystal": float(w.crystal),
                "produced_metal": float(w.produced_m),
                "produced_crystal": float(w.produced_c),
                "wasted_metal": float(w.wasted_m),
                "wasted_crystal": float(w.wasted_c),
            }

    def finish_research(self, job: pj.Job) -> None:  # type: ignore[override]
        before = len(self.completed_ids)
        super().finish_research(job)
        if len(self.completed_ids) != before:
            self.research_log.append([round(self.t / pj.DAY, 6), job.key, int(job.target), int(job.cost_m), int(job.cost_c)])


def record_journey(style: str, days: float = DEFAULT_DAYS, *, trader: bool = False, asc: str = "never") -> Dict[str, Any]:
    """Run one S1 journey (policy v2, no Ascension) and return its timeline."""
    sc = pj.Scenario(f"recon-{style}-{'tr' if trader else 'plain'}", "S1", style, "mid", "none", float(days), strategy="v2", asc=asc, trader=bool(trader))
    with uni1_curve(), pj.lever_context(sc.lever), pj.Sandbox(sc.rng_seed) as sb:
        j = RecordingJourney(sc, sb)
        j.run()
        slot = int(j.worlds[0].slot)
        return {
            "style": style,
            "trader": bool(trader),
            "days": float(days),
            "slot": slot,
            "builds": j.builds,
            "research": j.research_log,
            "marks": j.marks,
            "invariants": list(j.invariant_violations),
            "final_buildings": dict(j.worlds[0].buildings),
            "final_research": dict(j.research),
        }


# ---------------------------------------------------------------------------
# Timeline helpers
# ---------------------------------------------------------------------------


def level_day(tl: Dict[str, Any], key: str, level: int) -> Optional[float]:
    for b in tl["builds"]:
        if b[1] == key and int(b[2]) == int(level):
            return float(b[0])
    return None


def level_at(tl: Dict[str, Any], key: str, day: float) -> int:
    lvl = 0
    for b in tl["builds"]:
        if float(b[0]) > day + EPS:
            break
        if b[1] == key:
            lvl = max(lvl, int(b[2]))
    return lvl


def research_at(tl: Dict[str, Any], day: float) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for t, tech, target, _cm, _cc in tl["research"]:
        if float(t) > day + EPS:
            break
        out[tech] = max(out.get(tech, 0), int(target))
    return out


def buildings_at(tl: Dict[str, Any], day: float) -> Dict[str, int]:
    """Building levels of the journey's homeworld on ``day`` (from the completion log)."""
    out: Dict[str, int] = {}
    for b in tl["builds"]:
        if float(b[0]) > day + EPS:
            break
        out[b[1]] = max(out.get(b[1], 0), int(b[2]))
    return out


def storage_caps_at(tl: Dict[str, Any], day: float) -> Tuple[float, float]:
    """(metal, crystal) depot capacity on ``day`` from the canonical resolver and the journey's storage buildings / tech."""
    from game.effects import EffectResolver

    r = EffectResolver(buildings_at(tl, day), research_at(tl, day), settings=pj._settings(), planet_position=int(tl["slot"]))
    caps = r.get_storage_capacity()
    return float(caps.get("metal", math.inf)), float(caps.get("crystal", math.inf))


def build_time_hours(tl: Dict[str, Any], key: str, target: int, day: float) -> float:
    """Canonical construction time of ``key`` -> ``target`` with the journey's buildings and research on ``day``."""
    from game.effects import EffectResolver

    r = EffectResolver(buildings_at(tl, day), research_at(tl, day), settings=pj._settings(), planet_position=int(tl["slot"]))
    return float(r.get_build_time_seconds(key, int(target))) / 3600.0


def research_events(tl: Dict[str, Any], after_day: float) -> List[float]:
    """Days after ``after_day`` at which a production-relevant tech changes."""
    return sorted({float(t) for t, tech, *_ in tl["research"] if float(t) > after_day + EPS and tech in ("mining_tech", "crystal_tech", "drone_tech")})


def canonical_modifier(resource: str, slot: int, research: Dict[str, int]) -> float:
    """slot x temperature x research - the factors that are not 1.0 in the sandbox (verified by the tests)."""
    return float(pf.slot_modifier_for(resource, slot)) * float(pf.temperature_modifier_for(resource, pf.temperature_mid_c_for_slot(slot))) * float(pf.research_modifier_for(resource, research))


def output_per_hour(resource: str, level: int, modifier: float) -> float:
    """Canonical output per hour: (standard + mine) x modifier, energy ratio 1 (same expression as calculate_resource_output)."""
    return (float(pf.standard_output_decimal(resource)) + float(pf.mine_output_decimal(resource, int(level)))) * float(modifier)


def window_side_spend(tl: Dict[str, Any], start: int = START_LEVEL, end: int = END_LEVEL) -> Dict[str, float]:
    """Spending outside the mines (research, solar, storage, infrastructure) between the two marks - read from the ledger."""
    a, b = tl["marks"].get(str(start)), tl["marks"].get(str(end))
    if not a or not b:
        return {"metal": 0.0, "crystal": 0.0}
    out = {"metal": 0.0, "crystal": 0.0}
    for cat in b["spend_metal"]:
        if cat == "mines":
            continue
        out["metal"] += b["spend_metal"][cat] - a["spend_metal"].get(cat, 0.0)
        out["crystal"] += b["spend_crystal"].get(cat, 0.0) - a["spend_crystal"].get(cat, 0.0)
    return out


def window_shares(tl: Dict[str, Any], start: int, end: int) -> Dict[str, float]:
    """Measured fractions of the window's metal / crystal production that went to non-mine spending and to full depots."""
    a, b = tl["marks"].get(str(start)), tl["marks"].get(str(end))
    zero = {"side_metal": 0.0, "side_crystal": 0.0, "waste_metal": 0.0, "waste_crystal": 0.0}
    if not a or not b:
        return zero
    side = window_side_spend(tl, start, end)
    out = dict(zero)
    for res in ("metal", "crystal"):
        produced = float(b[f"produced_{res}"]) - float(a[f"produced_{res}"])
        if produced <= 0.0:
            continue
        out[f"side_{res}"] = max(0.0, side[res] / produced)
        out[f"waste_{res}"] = max(0.0, (float(b[f"wasted_{res}"]) - float(a[f"wasted_{res}"])) / produced)
    return out


def window_ledger(tl: Dict[str, Any], start: int = START_LEVEL, end: int = END_LEVEL) -> Dict[str, Any]:
    """Who received the production between the metal mine's L200 and L300? (all values metal + crystal)."""
    a, b = tl["marks"].get(str(start)), tl["marks"].get(str(end))
    if not a or not b:
        return {}
    ta, tb = float(a["day"]), float(b["day"])
    mm = [x for x in tl["builds"] if x[1] == "metal_mine" and start < int(x[2]) <= end]
    cm = [x for x in tl["builds"] if x[1] == "crystal_mine" and ta < float(x[0]) <= tb + EPS]
    fp = [x for x in tl["builds"] if x[1] == "fuel_cell_plant" and ta < float(x[0]) <= tb + EPS]
    pay = lambda rows: sum(int(r[3]) + int(r[4]) for r in rows)  # noqa: E731
    side = window_side_spend(tl, start, end)
    produced = (float(b["produced_metal"]) - float(a["produced_metal"])) + (float(b["produced_crystal"]) - float(a["produced_crystal"]))
    wasted = (float(b["wasted_metal"]) - float(a["wasted_metal"])) + (float(b["wasted_crystal"]) - float(a["wasted_crystal"]))
    return {
        "days": tb - ta,
        "produced": produced,
        "metal_mine": pay(mm),
        "crystal_mine": pay(cm),
        "fuel_plant": pay(fp),
        "side": side["metal"] + side["crystal"],
        "wasted": wasted,
        "crystal_mine_levels": [level_at(tl, "crystal_mine", ta), level_at(tl, "crystal_mine", tb)],
    }


# ---------------------------------------------------------------------------
# The ladder: an exact (event driven) integrator over canonical rates and prices
# ---------------------------------------------------------------------------


def advance_until_affordable(
    t: float,
    stock: Tuple[float, float],
    need: Tuple[float, float],
    rates: Callable[[float], Tuple[float, float]],
    events: Sequence[float],
) -> Tuple[float, Tuple[float, float]]:
    """Advance (hours, stock) until both stocks cover ``need``.  ``rates(t)`` is constant between ``events`` (hours)."""
    sm, sc = stock
    nm, nc = need
    ev = [e for e in events if e > t + EPS]
    k = 0
    for _ in range(100000):
        rm, rc = rates(t)
        waits = []
        for s, n, r in ((sm, nm, rm), (sc, nc, rc)):
            if s >= n - EPS:
                waits.append(0.0)
            elif r <= 0.0:
                waits.append(math.inf)
            else:
                waits.append((n - s) / r)
        dt = max(waits)
        while k < len(ev) and ev[k] <= t + EPS:
            k += 1
        if math.isinf(dt):
            if k >= len(ev):
                raise RuntimeError("purchase can never be afforded (non-positive production)")
            dt = ev[k] - t
            sm, sc = sm + rm * dt, sc + rc * dt
            t = ev[k]
            continue
        if k < len(ev) and t + dt > ev[k] + EPS:
            step = ev[k] - t
            sm, sc = sm + rm * step, sc + rc * step
            t = ev[k]
            continue
        return t + dt, (sm + rm * dt, sc + rc * dt)
    raise RuntimeError("integrator did not converge")


def climb(
    tl: Dict[str, Any],
    *,
    mods: str,
    currencies: str,
    crystal: str,
    side: bool,
    stock: bool,
    caps: bool = False,
    latency: bool = False,
    start: int = START_LEVEL,
    end: int = END_LEVEL,
) -> Dict[str, Any]:
    """Days for the metal mine from ``start`` to ``end`` under one set of assumptions.

    mods        neutral (control) | frozen (research / slot of the journey on the day it reached ``start``) | timeline
    currencies  one (metal + crystal price paid from the metal mine, as the control does) | two | pooled (1:1)
    crystal     none | fixed (crystal mine at its depth on the start day) | lockstep (journey's order)
    side        the journey's non-mine spending of the window, removed from income as its measured share of production
    caps        depots: stock above the canonical storage capacity (journey's storage buildings / tech) is lost; two currencies only
    latency     a level produces only once built (canonical build time); the two mines share one serial queue, purchases pipeline
    stock       start with the stock the journey held when the metal mine reached ``start``
    """
    if mods not in ("neutral", "frozen", "timeline") or currencies not in ("one", "two", "pooled") or crystal not in ("none", "fixed", "lockstep"):
        raise ValueError("unknown ladder option")
    slot = int(tl["slot"])
    t_start = level_day(tl, "metal_mine", start)
    t_end = level_day(tl, "metal_mine", end)
    if t_start is None:
        raise ValueError(f"journey never reached metal mine L{start}")
    frozen_research = research_at(tl, t_start)
    crystal_level0 = level_at(tl, "crystal_mine", t_start)
    sh = window_shares(tl, start, end)
    avail_m = max(0.0, 1.0 - (sh["side_metal"] if side else 0.0))
    avail_c = max(0.0, 1.0 - (sh["side_crystal"] if side else 0.0))
    mark = tl["marks"].get(str(start), {})
    st0 = (float(mark.get("stock_metal", 0.0)), float(mark.get("stock_crystal", 0.0))) if stock else (0.0, 0.0)

    # crystal mine level the journey owned when its metal mine reached each level (lockstep order)
    crystal_target: Dict[int, int] = {}
    if crystal == "lockstep":
        for lvl in range(start, end + 1):
            d = level_day(tl, "metal_mine", lvl)
            crystal_target[lvl] = level_at(tl, "crystal_mine", d) if d is not None else crystal_level0
    events_h = [] if mods != "timeline" else [e * DAY_H for e in research_events(tl, t_start)]

    def modifier(res: str, t_h: float) -> float:
        if mods == "neutral":
            return 1.0
        research = frozen_research if mods == "frozen" else research_at(tl, t_h / DAY_H)
        return canonical_modifier(res, slot, research)

    t = t_start * DAY_H
    state = {"cl": crystal_level0, "ml": start, "eff_m": start, "eff_c": crystal_level0}
    pending: List[Tuple[float, str, int]] = []  # (completion hour, "m" | "c", level) while latency is on
    queue_free = t

    def rates(t_h: float) -> Tuple[float, float]:
        while pending and pending[0][0] <= t_h + EPS:
            _done, which, lvl = pending.pop(0)
            state["eff_m" if which == "m" else "eff_c"] = max(state["eff_m" if which == "m" else "eff_c"], lvl)
        rm = output_per_hour("metal", state["eff_m"], modifier("metal", t_h)) * avail_m
        rc = 0.0 if crystal == "none" else output_per_hour("crystal", state["eff_c"], modifier("crystal", t_h)) * avail_c
        if currencies == "pooled":
            return rm + rc, 0.0
        if currencies == "one":
            return rm, 0.0
        return rm, rc

    stock_now = st0 if currencies == "two" else (st0[0] + st0[1], 0.0)
    ml = start
    t_by_level: Dict[int, float] = {start: t / DAY_H}
    last_done = t
    while ml < end:
        state["ml"] = ml
        cm, cc = price("metal_mine", ml)  # price of metal mine level ml + 1
        need_m, need_c = float(cm), float(cc)
        cl_new = state["cl"]
        if crystal == "lockstep":
            while cl_new < crystal_target.get(ml + 1, cl_new):  # bought together with this metal level; produces only afterwards
                km, kc = price("crystal_mine", cl_new)  # price of crystal mine level cl_new + 1
                need_m += float(km)
                need_c += float(kc)
                cl_new += 1
        if currencies == "two":
            need = (need_m, need_c)
        else:  # one / pooled: a single currency (the control pays crystal costs from metal; pooled = Trader at 1:1)
            need = (need_m + need_c, 0.0)
        floor_h = building_progress_floor_seconds("metal_mine", ml + 1) / 3600.0
        t_prev = t
        events = list(events_h) + [d for d, _w, _l in pending]
        t, stock_now = advance_until_affordable(t, stock_now, need, rates, events)
        if caps and currencies == "two":  # the depot is full while the other resource is awaited: the surplus is lost
            cap_m, cap_c = storage_caps_at(tl, t / DAY_H)
            stock_now = (min(stock_now[0], max(cap_m, need[0])), min(stock_now[1], max(cap_c, need[1])))
        if t - t_prev < floor_h:  # the queue floor is a minimum duration per level; production keeps flowing meanwhile
            extra = floor_h - (t - t_prev)
            rm, rc = rates(t)
            stock_now = (stock_now[0] + rm * extra, stock_now[1] + rc * extra)
            t += extra
        stock_now = (stock_now[0] - need[0], stock_now[1] - need[1])
        if latency:  # paid now, built by the serial queue: the new level produces when its job completes
            clock = max(t, queue_free)
            done_m = clock + build_time_hours(tl, "metal_mine", ml + 1, clock / DAY_H)
            pending.append((done_m, "m", ml + 1))
            clock = done_m
            for k in range(state["cl"] + 1, cl_new + 1):
                clock += build_time_hours(tl, "crystal_mine", k, clock / DAY_H)
                pending.append((clock, "c", k))
            queue_free = clock
            pending.sort()
            last_done = done_m
        else:
            state["eff_m"], state["eff_c"] = ml + 1, cl_new
            last_done = t
        state["cl"] = cl_new
        ml += 1
        t_by_level[ml] = last_done / DAY_H
    return {"days": last_done / DAY_H - t_start, "t_start": t_start, "t_end_model": last_done / DAY_H, "t_end_journey": t_end, "t_by_level": t_by_level}


def price(key: str, current_level: int) -> Tuple[int, int]:
    """(metal, crystal) to take ``key`` from ``current_level`` to ``current_level + 1`` - the canonical owner's convention.

    ``game.economy_balance.power_upgrade_cost(key, target_level)`` (used by the record-mine control) is the same table
    indexed by the *target* level; the tests pin ``price(k, L) == power_upgrade_cost(k, L + 1)``.
    """
    return pj._upgrade_cost(key, int(current_level))


def control_days(start: int = START_LEVEL, end: int = END_LEVEL) -> float:
    """The published control (baseline q3) - the number R0 has to reproduce."""
    from decimal import Decimal

    from scripts import sim_ascension_breakthroughs as ctl

    scenario = ctl.Scenario("baseline_q3", "Baseline q3", start_level=start)
    with pj.SIM_LOCK, ctl.uni1_endgame_curve():
        return float(ctl.hours_to_target(scenario, end) / Decimal(24))


def build_window(tl: Dict[str, Any], tl_trader: Optional[Dict[str, Any]], start: int, end: int) -> Optional[Dict[str, Any]]:
    """Ladder for one metal-mine window of one style (None when the journey never completed it)."""
    t_start, t_end = level_day(tl, "metal_mine", start), level_day(tl, "metal_mine", end)
    if t_start is None or t_end is None:
        return None
    measured = t_end - t_start
    rows: List[Dict[str, Any]] = []
    prev: Optional[float] = None
    for key, label, kw in RUNGS:
        days = climb(tl, start=start, end=end, **kw)["days"]
        rows.append({"rung": key, "label": label, "days": days, "step": None if prev is None else days - prev, "vs_measured": days / measured - 1.0})
        if key != "R6s":
            prev = days
    trader_rows: List[Dict[str, Any]] = []
    measured_tr: Optional[float] = None
    if tl_trader is not None:
        a, b = level_day(tl_trader, "metal_mine", start), level_day(tl_trader, "metal_mine", end)
        if a is not None and b is not None:
            measured_tr = b - a
            for key, label, kw in TRADER_RUNGS:
                days = climb(tl_trader, start=start, end=end, **kw)["days"]
                trader_rows.append({"rung": key, "label": label, "days": days, "vs_measured": days / measured_tr - 1.0})
    return {
        "start": start,
        "end": end,
        "control_days": control_days(start, end),
        "measured_days": measured,
        "measured_start_day": t_start,
        "measured_end_day": t_end,
        "crystal_mine_end_day": level_day(tl, "crystal_mine", end),
        "rungs": rows,
        "trader_rungs": trader_rows,
        "measured_trader_days": measured_tr,
        "ledger": window_ledger(tl, start, end),
        "modifiers": modifiers_report(tl, start),
    }


def horizon_levels(tl: Dict[str, Any], start: int = START_LEVEL) -> Dict[str, Any]:
    """Metal-mine depth a given number of days after ``start`` under the control's and the researched one-mine model.

    The record-mine control starts at L200 on day 0 and publishes its depth after 6 / 12 months.  Re-priced with the
    journey's research (R2: still one mine, one currency, no other spending) the same question gets a different answer.
    """
    out: Dict[str, Any] = {}
    for key, kw in (("R0", RUNGS[0][2]), ("R2", RUNGS[2][2])):
        res = climb(tl, start=start, end=HORIZON_MAX_LEVEL, **kw)
        levels = {}
        for tau in HORIZON_DAYS_AFTER_START:
            reached = [lvl for lvl, t in res["t_by_level"].items() if t - res["t_start"] <= tau + EPS]
            levels[f"{tau:g}"] = max(reached) if reached else start
        out[key] = levels
    return out


def modifiers_report(tl: Dict[str, Any], level: int = START_LEVEL) -> Dict[str, Any]:
    t_start = level_day(tl, "metal_mine", level)
    if t_start is None:
        return {}
    r = research_at(tl, t_start)
    slot = int(tl["slot"])
    return {
        "day": t_start,
        "level": level,
        "research": {k: r.get(k, 0) for k in ("mining_tech", "drone_tech", "crystal_tech")},
        "metal": {"slot": float(pf.slot_modifier_for("metal", slot)), "research": float(pf.research_modifier_for("metal", r)), "total": canonical_modifier("metal", slot, r)},
        "crystal": {"slot": float(pf.slot_modifier_for("crystal", slot)), "research": float(pf.research_modifier_for("crystal", r)), "total": canonical_modifier("crystal", slot, r)},
        "metal_h": output_per_hour("metal", level, canonical_modifier("metal", slot, r)),
        "control_metal_h": output_per_hour("metal", level, 1.0),
    }


def build_ladder(tl: Dict[str, Any], tl_trader: Optional[Dict[str, Any]] = None, windows: Sequence[Tuple[int, int]] = WINDOWS) -> Dict[str, Any]:
    """All windows for one style (plus the Trader branch when a Trader journey is given)."""
    with uni1_curve():
        wins = [w for w in (build_window(tl, tl_trader, a, b) for a, b in windows) if w is not None]
        horizons = horizon_levels(tl) if level_day(tl, "metal_mine", START_LEVEL) is not None else {}
    return {"style": tl["style"], "windows": wins, "horizons": horizons, "invariants": tl.get("invariants", [])}


# ---------------------------------------------------------------------------
# Early game: start resources, settings and the first week against the fresh-account simulator
# ---------------------------------------------------------------------------


def early_game_anchor(days: float = 31.0) -> Dict[str, Any]:
    """The journey's first month against ``fresh_account_progression_sim`` (a third, independent greedy builder)."""
    from game.models import DEFAULT_GAME_SETTINGS
    from scripts import fresh_account_progression_sim as fs

    preset = fs.PRESETS["alpha_current"]
    pj._upgrade_cost.cache_clear()
    _state, cps = fs.run_simulation(preset)
    fresh = {
        k: {x: cps[k][x] for x in ("metal_mine", "crystal_mine", "solar_plant", "research_lab", "mining_tech", "prod_metal_h", "prod_crystal_h", "build_active_pct")}
        for k in ("24h", "7d", "30d")
    }
    start_same = (
        float(DEFAULT_GAME_SETTINGS.get("start_metal", 150000)) == float(fs.START_METAL)
        and float(DEFAULT_GAME_SETTINGS.get("start_crystal", 100000)) == float(fs.START_CRYSTAL)
        and float(DEFAULT_GAME_SETTINGS.get("start_fuel_cells", 25000)) == float(fs.START_FUEL)
    )
    journeys: Dict[str, Any] = {}
    for style in STYLES:
        sc = pj.Scenario(f"early-{style}", "S1", style, "mid", "none", float(days), strategy="v2", asc="never")
        with uni1_curve():
            res = pj.run_scenario(sc)
        by_day = {int(round(r["day"])): r for r in res["daily"]}
        rows: Dict[str, Any] = {}
        for d, label in ((1, "24h"), (7, "7d"), (30, "30d")):
            r = by_day.get(d)
            if r is not None:
                rows[label] = {"metal_mine": r["mine_depth_max"], "prod_metal_h": r["empire_metal_h"], "prod_crystal_h": r["empire_crystal_h"]}
        journeys[style] = rows
    return {
        "start_resources_equal": bool(start_same),
        "start": {"metal": float(fs.START_METAL), "crystal": float(fs.START_CRYSTAL), "fuel_cells": float(fs.START_FUEL)},
        "settings_equal": all(abs(float(pj._settings()[k]) - float(preset[k])) < 1e-12 for k in ("production_speed", "build_speed", "research_speed")),
        "settings": {k: float(preset[k]) for k in ("production_speed", "build_speed", "research_speed")},
        "fresh": fresh,
        "journeys": journeys,
    }


# ---------------------------------------------------------------------------
# Matrix / report
# ---------------------------------------------------------------------------


def run_all(days: float = DEFAULT_DAYS, styles: Sequence[str] = STYLES, with_trader: bool = True, with_early: bool = True) -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    for style in styles:
        plain = record_journey(style, days)
        trader = record_journey(style, days, trader=True) if with_trader else None
        out.append(build_ladder(plain, trader))
    return {
        "version": RECON_VERSION,
        "days": days,
        "windows": [list(w) for w in WINDOWS],
        "styles": out,
        "early_game": early_game_anchor() if with_early else {},
    }


def _d(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:,.0f}"


def _x(a: Optional[float], b: Optional[float]) -> str:
    return "-" if (a is None or not b) else f"x{a / b:.2f}"


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{100 * x:+.1f}%"


def _window(style_entry: Dict[str, Any], start: int, end: int) -> Optional[Dict[str, Any]]:
    return next((w for w in style_entry["windows"] if w["start"] == start and w["end"] == end), None)


def render_window(data: Dict[str, Any], start: int, end: int, number: int) -> List[str]:
    entries = [(s, _window(s, start, end)) for s in data["styles"]]
    entries = [(s, w) for s, w in entries if w is not None]
    if not entries:
        return []
    L: List[str] = [
        f"## {number}. Ladder, metal mine L{start} -> L{end}",
        "",
        "Days for the **metal mine**.  Every rung adds one assumption of the journey simulator to the control; rates come from `production_formula`, prices from `get_upgrade_cost`, the floor from `building_progress_floor_seconds`.  `step` is the change versus the previous rung (the order is a choice - the steps are not additive causes).",
        "",
        "| Rung | Assumption added | " + " | ".join(f"{s['style']} days | step" for s, _w in entries) + " |",
        "|---|---|" + "---:|---:|" * len(entries),
    ]
    for key, label, _kw in RUNGS:
        cells: List[str] = []
        for _s, w in entries:
            r = next(x for x in w["rungs"] if x["rung"] == key)
            cells += [_d(r["days"]), "-" if r["step"] is None else f"{r['step']:+,.0f}"]
        L.append(f"| {key} | {label} | " + " | ".join(cells) + " |")
    j_cells: List[str] = []
    for _s, w in entries:
        j_cells += [f"**{_d(w['measured_days'])}**", ""]
    L.append("| **J** | **journey as measured (`never`)** | " + " | ".join(j_cells) + " |")
    L += ["", f"| Style | Control (R0) | Journey, metal mine | Control / journey | R3 vs measured | R4 vs measured | R5 vs measured | R6 vs measured | R6s vs measured | Crystal mine reaches L{end} | Metal mine reaches L{end} |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s, w in entries:
        rv = {x["rung"]: x["vs_measured"] for x in w["rungs"]}
        L.append(f"| {s['style']} | {_d(w['control_days'])} | {_d(w['measured_days'])} | {_x(w['control_days'], w['measured_days'])} | {_pct(rv['R3'])} | {_pct(rv['R4'])} | {_pct(rv['R5'])} | {_pct(rv['R6'])} | {_pct(rv['R6s'])} | day {_d(w['crystal_mine_end_day'])} | day {_d(w['measured_end_day'])} |")
    L += [""]
    return L


def render_markdown(data: Dict[str, Any]) -> str:
    L: List[str] = [
        "# Simulator reconciliation - generated tables",
        "",
        f"Version `{data['version']}`.  S1 journeys (policy v2, `never`, UNI1 endgame curve), {data['days']:g} days.",
        "Generated by `scripts/simulator_reconciliation.py`; the curated reading is in `docs/GC_SIMULATOR_RECONCILIATION.md`.",
        "",
    ]
    n = 1
    for a, b in data["windows"]:
        block = render_window(data, a, b, n)
        if block:
            L += block
            n += 1
    L += [f"## {n}. Production modifiers on the first day of each window", "", "| Style | Window | Day | mining / drone / crystal tech | metal: slot x research = total | crystal total | metal / h (journey) | metal / h (control) |", "|---|---|---:|---|---:|---:|---:|---:|"]
    for s in data["styles"]:
        for w in s["windows"]:
            m = w["modifiers"]
            if not m:
                continue
            rs = m["research"]
            L.append(
                f"| {s['style']} | L{w['start']}->L{w['end']} | {m['day']:.0f} | {rs['mining_tech']} / {rs['drone_tech']} / {rs['crystal_tech']} | {m['metal']['slot']:.2f} x {m['metal']['research']:.3f} = {m['metal']['total']:.3f} | {m['crystal']['total']:.3f} | {pj._human(m['metal_h'])} | {pj._human(m['control_metal_h'])} |"
            )
    n += 1
    L += ["", f"## {n}. Who receives the production inside each window?", "", "Metal + crystal summed.  Shares of production in the window (spending is booked when queued, so the window edges carry about one level).", "", "| Style | Window | Days | Produced | Metal mine | Crystal mine | Fuel plant | Other (research, solar, storage, nexus, ...) | Lost to full depots |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in data["styles"]:
        for w in s["windows"]:
            g = w["ledger"]
            if not g:
                continue
            p = g["produced"] or 1.0
            L.append(f"| {s['style']} | L{w['start']}->L{w['end']} | {g['days']:.0f} | {pj._human(g['produced'])} | {100 * g['metal_mine'] / p:.0f}% | {100 * g['crystal_mine'] / p:.0f}% | {100 * g['fuel_plant'] / p:.0f}% | {100 * g['side'] / p:.0f}% | {100 * g['wasted'] / p:.0f}% |")
    n += 1
    if any(w["trader_rungs"] for s in data["styles"] for w in s["windows"]):
        L += ["", f"## {n}. Trader branch", "", "Crystal and metal fungible 1:1 is what the control silently assumes (it pays a metal + crystal price from metal output).  The canonical Trader gives crystal -> metal at 1:1 (daily limit, minimum, score guard), so the pooled rung is its upper bound.", "", "| Style | Window | Journey with Trader (measured) | P3 pooled 1:1 | vs measured | P4 + other spending | vs measured | P5 + construction time + stock | vs measured | Journey without Trader |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for s in data["styles"]:
            for w in s["windows"]:
                if not w["trader_rungs"]:
                    continue
                tr = {x["rung"]: x for x in w["trader_rungs"]}
                L.append(
                    f"| {s['style']} | L{w['start']}->L{w['end']} | {_d(w['measured_trader_days'])} | {_d(tr['P3']['days'])} | {_pct(tr['P3']['vs_measured'])} | {_d(tr['P4']['days'])} | {_pct(tr['P4']['vs_measured'])} | {_d(tr['P5']['days'])} | {_pct(tr['P5']['vs_measured'])} | {_d(w['measured_days'])} |"
                )
        n += 1
    if any(s.get("horizons") for s in data["styles"]):
        L += ["", f"## {n}. The control's 6 / 12-month levels, re-priced", "", "The record-mine control starts at L200 on day 0 and publishes its depth after 6 / 12 months (baseline q3: L223 / L245).  Same question, same start, with the journey's research: R0 = control, R2 = one mine, one currency, canonical modifiers and the research the journey bought.", "", "| Style | Model | 6 months after L200 | 12 months after L200 |", "|---|---|---:|---:|"]
        for s in data["styles"]:
            h = s.get("horizons") or {}
            for key, label in (("R0", "R0 control"), ("R2", "R2 researched")):
                if key in h:
                    L.append(f"| {s['style']} | {label} | L{h[key]['182.5']} | L{h[key]['365']} |")
        n += 1
    eg = data.get("early_game") or {}
    if eg:
        L += ["", f"## {n}. Early game: start resources, settings and the first week", "", f"Start resources equal: **{eg['start_resources_equal']}** ({eg['start']['metal']:,.0f} metal / {eg['start']['crystal']:,.0f} crystal / {eg['start']['fuel_cells']:,.0f} fuel cells).  Speed settings equal: **{eg['settings_equal']}** ({eg['settings']}).", "", "`fresh` = `scripts/fresh_account_progression_sim.py` (greedy, always attentive, one homeworld; it buys no mining tech and stops progressing after the first week).  Journey rows are the three player styles.", "", "| Model | Day | Metal mine | Metal / h | Crystal / h |", "|---|---:|---:|---:|---:|"]
        for label, day in (("24h", 1), ("7d", 7), ("30d", 30)):
            f = eg["fresh"].get(label)
            if f:
                L.append(f"| fresh-account sim | {day} | L{f['metal_mine']} | {f['prod_metal_h']:,} | {f['prod_crystal_h']:,} |")
            for style, rows in eg["journeys"].items():
                r = rows.get(label)
                if r:
                    L.append(f"| journey {style} | {day} | L{r['metal_mine']} | {r['prod_metal_h']:,} | {r['prod_crystal_h']:,} |")
        n += 1
    inv = [(s["style"], s["invariants"]) for s in data["styles"] if s.get("invariants")]
    L += ["", f"## {n}. Simulator invariants", "", "none violated" if not inv else "\n".join(f"* {st}: {v}" for st, v in inv), ""]
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=float, default=DEFAULT_DAYS)
    ap.add_argument("--styles", default=",".join(STYLES))
    ap.add_argument("--no-trader", action="store_true")
    ap.add_argument("--no-early", action="store_true")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    ap.add_argument("--render-from", default="", help="render markdown from an existing JSON instead of running")
    args = ap.parse_args(argv)
    if args.render_from:
        data = json.loads(Path(args.render_from).read_text(encoding="utf-8"))
    else:
        styles = [s for s in args.styles.split(",") if s]
        data = run_all(args.days, styles, with_trader=not args.no_trader, with_early=not args.no_early)
    if args.out_json:
        p = Path(args.out_json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1), encoding="utf-8")
    md = render_markdown(data)
    if args.out_md:
        Path(args.out_md).write_text(md + "\n", encoding="utf-8")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
