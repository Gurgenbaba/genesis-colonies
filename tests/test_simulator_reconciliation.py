"""Reconciliation of the record-mine control and the player-journey simulator (measurement only).

The ladder must (a) reproduce the control exactly at its first rung, (b) use nothing but the canonical owners, and
(c) never change the behaviour of the journey simulator it records.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.economy_balance import power_upgrade_cost  # noqa: E402
from game.effects import EffectResolver  # noqa: E402
from game.models import DEFAULT_GAME_SETTINGS  # noqa: E402
from scripts import fresh_account_progression_sim as fresh  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402
from scripts import simulator_reconciliation as rc  # noqa: E402


@pytest.fixture()
def uni1():
    """The UNI1 endgame curve for one test (function scope: other test files re-import / reset the formula module)."""
    with rc.uni1_curve():
        yield


def _toy_timeline() -> dict:
    """A small hand-made journey: metal mine L100 -> L110 -> L120, crystal mine alongside, research growing, marks present."""
    builds = [[0.0, "metal_mine", 100, 0, 0, 0.0, 0.0], [0.0, "crystal_mine", 100, 0, 0, 0.0, 0.0]]
    day = 1.0
    for lvl in range(101, 121):
        builds.append([day, "metal_mine", lvl, 0, 0, 0.0, 0.0])
        builds.append([day + 0.1, "crystal_mine", lvl, 0, 0, 0.0, 0.0])
        day += 4.0
    research = [[0.0, "mining_tech", 30, 0, 0], [0.0, "drone_tech", 3, 0, 0], [0.0, "crystal_tech", 25, 0, 0], [30.0, "mining_tech", 34, 0, 0], [30.0, "crystal_tech", 28, 0, 0]]

    def mark(day_, pm, pc, wm, wc, sm, sc):
        return {
            "day": day_,
            "spend_metal": {"mines": 0.0, "research": sm},
            "spend_crystal": {"mines": 0.0, "research": sc},
            "stock_metal": 5e6,
            "stock_crystal": 2e6,
            "produced_metal": pm,
            "produced_crystal": pc,
            "wasted_metal": wm,
            "wasted_crystal": wc,
        }

    marks = {"100": mark(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), "120": mark(77.0, 1e12, 5e11, 0.0, 1e11, 1e11, 5e10)}
    return {"style": "toy", "slot": 8, "builds": builds, "research": research, "marks": marks, "invariants": []}


# ---------------------------------------------------------------------------
# Same owners, same numbers
# ---------------------------------------------------------------------------


def test_price_convention_matches_the_controls_cost_owner(uni1):
    """price(key, current level) is the control's power_upgrade_cost(key, target level) - the one-level offset that cost 19 days in a first draft."""
    for key in ("metal_mine", "crystal_mine"):
        for level in list(range(0, 60, 7)) + list(range(100, 520, 41)):
            assert tuple(rc.price(key, level)) == tuple(power_upgrade_cost(key, level + 1)), (key, level)


def test_start_resources_and_speed_settings_equal_the_fresh_account_simulator():
    assert float(DEFAULT_GAME_SETTINGS.get("start_metal", 150000)) == float(fresh.START_METAL)
    assert float(DEFAULT_GAME_SETTINGS.get("start_crystal", 100000)) == float(fresh.START_CRYSTAL)
    assert float(DEFAULT_GAME_SETTINGS.get("start_fuel_cells", 25000)) == float(fresh.START_FUEL)
    preset = fresh.PRESETS["alpha_current"]
    for key in ("production_speed", "build_speed", "research_speed"):
        assert float(pj._settings()[key]) == float(preset[key])


def test_rung_rates_equal_the_canonical_resolver(uni1):
    """output_per_hour x canonical_modifier is exactly EffectResolver.production_rates_per_sec (energy ratio 1)."""
    research = {"mining_tech": 47, "drone_tech": 3, "crystal_tech": 39}
    for slot in (1, 8, 15):
        for metal_l, crystal_l in ((60, 55), (150, 140), (250, 240)):
            buildings = {"metal_mine": metal_l, "crystal_mine": crystal_l, "solar_plant": 40}
            r = EffectResolver(dict(buildings), dict(research), settings=pj._settings(), planet_position=slot)
            m_ps, c_ps = r.production_rates_per_sec()
            ours_m = rc.output_per_hour("metal", metal_l, rc.canonical_modifier("metal", slot, research))
            ours_c = rc.output_per_hour("crystal", crystal_l, rc.canonical_modifier("crystal", slot, research))
            assert ours_m == pytest.approx(m_ps * 3600.0, rel=1e-9), (slot, metal_l)
            assert ours_c == pytest.approx(c_ps * 3600.0, rel=1e-9), (slot, crystal_l)


def test_every_non_trivial_modifier_is_accounted_for(uni1):
    """In the sandbox the resolver's modifiers other than slot x temperature x research are 1.0, so the ladder loses nothing."""
    from game import production_formula as pf

    research = {"mining_tech": 40, "drone_tech": 3, "crystal_tech": 30}
    r = EffectResolver({"metal_mine": 120, "crystal_mine": 110}, dict(research), settings=pj._settings(), planet_position=8)
    for res in ("metal", "crystal"):
        mods = pf.ProductionModifiers(pf.production_context_from_resolver(r, res))
        assert mods.combined_without_energy() == pytest.approx(rc.canonical_modifier(res, 8, research), rel=1e-12)
        for name in ("building_modifier", "planet_modifier", "empire_modifier", "alliance_modifier", "directive_modifier", "event_modifier", "seasonal_modifier"):
            assert getattr(mods, name)() == 1.0


def test_r0_reproduces_the_published_control(uni1):
    """The first rung is the control itself: 887 days from L200 to L300 (and the same for L100 -> L200)."""
    tl = {"style": "x", "slot": 8, "builds": [[10.0, "metal_mine", 200, 0, 0, 0.0, 0.0], [900.0, "metal_mine", 300, 0, 0, 0.0, 0.0], [10.0, "metal_mine", 100, 0, 0, 0.0, 0.0]], "research": [], "marks": {}}
    kw = rc.RUNGS[0][2]
    assert rc.climb(tl, start=200, end=300, **kw)["days"] == pytest.approx(rc.control_days(200, 300), abs=0.01)
    assert rc.control_days(200, 300) == pytest.approx(886.58, abs=0.01)
    assert rc.climb(tl, start=100, end=200, **kw)["days"] == pytest.approx(rc.control_days(100, 200), abs=0.01)


# ---------------------------------------------------------------------------
# The integrator
# ---------------------------------------------------------------------------


def test_integrator_constant_rates_and_rate_change():
    t, stock = rc.advance_until_affordable(0.0, (0.0, 0.0), (100.0, 50.0), lambda _t: (10.0, 5.0), [])
    assert t == pytest.approx(10.0)
    assert stock == pytest.approx((100.0, 50.0))
    # rates double at t = 4: 4 h x 10 = 40, then 60 more at 20 / h = 3 h -> 7 h
    t, stock = rc.advance_until_affordable(0.0, (0.0, 0.0), (100.0, 0.0), lambda x: (10.0, 0.0) if x < 4.0 - 1e-9 else (20.0, 0.0), [4.0])
    assert t == pytest.approx(7.0)
    assert stock[0] == pytest.approx(100.0)
    # the slower resource decides, the other carries a surplus
    t, stock = rc.advance_until_affordable(0.0, (0.0, 0.0), (10.0, 100.0), lambda _t: (10.0, 5.0), [])
    assert t == pytest.approx(20.0)
    assert stock == pytest.approx((200.0, 100.0))
    # stock on hand shortens the wait; an already affordable purchase costs no time
    assert rc.advance_until_affordable(3.0, (100.0, 50.0), (100.0, 50.0), lambda _t: (1.0, 1.0), [])[0] == pytest.approx(3.0)
    # no production and no later event: it can never be afforded
    with pytest.raises(RuntimeError):
        rc.advance_until_affordable(0.0, (0.0, 0.0), (1.0, 0.0), lambda _t: (0.0, 0.0), [])


# ---------------------------------------------------------------------------
# The ladder on a toy timeline (no full simulation needed)
# ---------------------------------------------------------------------------


def test_ladder_orderings_on_a_toy_timeline(uni1):
    tl = _toy_timeline()
    days = {key: rc.climb(tl, start=100, end=120, **kw)["days"] for key, _label, kw in rc.RUNGS}
    assert days["R1"] < days["R0"] / 2.0  # canonical research / slot modifiers are > 2x
    assert days["R2"] <= days["R1"] + 1e-9  # research that keeps growing can only help
    assert days["R3"] >= days["R2"] - 1e-9  # a second currency plus the crystal mine's own upgrades cost time
    assert days["R4"] >= days["R3"] - 1e-9  # other spending takes a share of production
    assert days["R5"] >= days["R4"] - 1e-9  # a depot cap can only lose stock
    assert days["R6"] >= days["R5"] - 1e-9  # construction latency delays production
    assert days["R6s"] <= days["R6"] + 1e-9  # stock on hand can only help
    assert all(math.isfinite(v) and v > 0 for v in days.values())


def test_pooled_currency_is_never_slower_than_two_currencies(uni1):
    tl = _toy_timeline()
    common = dict(mods="timeline", crystal="lockstep", side=False, stock=False, start=100, end=120)
    two = rc.climb(tl, currencies="two", **common)["days"]
    pooled = rc.climb(tl, currencies="pooled", **common)["days"]
    assert pooled <= two + 1e-9


def test_depot_cap_never_speeds_a_climb_up_and_clips_a_surplus(uni1, monkeypatch):
    tl = _toy_timeline()
    base = dict(mods="timeline", currencies="two", crystal="lockstep", side=False, stock=False, start=100, end=120)
    free = rc.climb(tl, caps=False, **base)["days"]
    monkeypatch.setattr(rc, "storage_caps_at", lambda _tl, _day: (1.0, 1.0))  # tiny depots: only the purchase itself fits
    tight = rc.climb(tl, caps=True, **base)["days"]
    assert tight >= free - 1e-9
    assert math.isfinite(tight)


def test_construction_latency_matches_the_canonical_build_time(uni1):
    tl = _toy_timeline()
    h = rc.build_time_hours(tl, "metal_mine", 110, 20.0)
    r = EffectResolver(rc.buildings_at(tl, 20.0), rc.research_at(tl, 20.0), settings=pj._settings(), planet_position=8)
    assert h == pytest.approx(r.get_build_time_seconds("metal_mine", 110) / 3600.0)
    assert h > 0.0


def test_window_shares_come_from_the_ledger():
    tl = _toy_timeline()
    sh = rc.window_shares(tl, 100, 120)
    assert sh["side_metal"] == pytest.approx(1e11 / 1e12)
    assert sh["side_crystal"] == pytest.approx(5e10 / 5e11)
    assert sh["waste_crystal"] == pytest.approx(1e11 / 5e11)
    assert sh["waste_metal"] == 0.0
    assert rc.window_shares({"marks": {}}, 100, 120) == {"side_metal": 0.0, "side_crystal": 0.0, "waste_metal": 0.0, "waste_crystal": 0.0}


def test_horizon_levels_with_research_exceed_the_neutral_control(uni1):
    tl = _toy_timeline()
    tl["builds"].append([1.0, "metal_mine", 200, 0, 0, 0.0, 0.0])
    h = rc.horizon_levels(tl, start=200)
    assert h["R2"]["365"] > h["R0"]["365"]
    assert h["R0"]["365"] == 245  # the control's published 12-month level (baseline q3)
    assert h["R0"]["182.5"] == 223


# ---------------------------------------------------------------------------
# The recorder must not change the journey
# ---------------------------------------------------------------------------


def _plain_and_recorded(style: str, days: float):
    sc = pj.Scenario("recon-test", "S1", style, "mid", "none", float(days), strategy="v2", asc="never")
    plain = pj.run_scenario(sc)
    with pj.economy_curve("uni1"), pj.lever_context(sc.lever), pj.Sandbox(sc.rng_seed) as sb:
        j = rc.RecordingJourney(sc, sb)
        recorded = j.run()
        return plain, recorded, j


def test_recorder_leaves_the_journey_unchanged_and_logs_in_order():
    plain, recorded, j = _plain_and_recorded("optimizer", 30.0)
    assert [r["empire_metal_h"] for r in plain["daily"]] == [r["empire_metal_h"] for r in recorded["daily"]]
    assert [r["mine_depth_max"] for r in plain["daily"]] == [r["mine_depth_max"] for r in recorded["daily"]]
    assert plain["final"]["per_world"][0]["buildings"] == recorded["final"]["per_world"][0]["buildings"]
    times = [b[0] for b in j.builds]
    assert times == sorted(times) and j.builds
    assert {b[1] for b in j.builds} >= {"metal_mine", "crystal_mine", "solar_plant"}
    assert [r[0] for r in j.research_log] == sorted(r[0] for r in j.research_log)
    # the log agrees with the final state
    final = recorded["final"]["per_world"][0]["buildings"]
    for key in ("metal_mine", "crystal_mine"):
        assert max(b[2] for b in j.builds if b[1] == key) == final[key]


def test_record_journey_marks_only_the_requested_levels():
    tl = rc.record_journey("optimizer", 100.0)
    assert tl["slot"] == 8 and tl["style"] == "optimizer" and tl["invariants"] == []
    assert set(tl["marks"]) <= {str(v) for v in rc.MARK_LEVELS}
    assert "100" in tl["marks"]  # the optimizer reaches metal mine L100 in about 74 days
    assert tl["marks"]["100"]["day"] == pytest.approx(rc.level_day(tl, "metal_mine", 100))
    assert rc.level_at(tl, "metal_mine", tl["marks"]["100"]["day"]) == 100


# ---------------------------------------------------------------------------
# Report plumbing
# ---------------------------------------------------------------------------


def test_early_game_anchor_structure():
    eg = rc.early_game_anchor(days=8.0)
    assert eg["start_resources_equal"] is True and eg["settings_equal"] is True
    assert set(eg["journeys"]) == set(rc.STYLES)
    assert {"24h", "7d"} <= set(eg["fresh"]) and "24h" in eg["journeys"]["optimizer"]


def test_render_and_cli_roundtrip(tmp_path, uni1):
    tl = _toy_timeline()
    entry = rc.build_ladder(tl, None, windows=((100, 120),))
    assert entry["windows"] and entry["windows"][0]["rungs"][0]["rung"] == "R0"
    data = {"version": rc.RECON_VERSION, "days": 100.0, "windows": [[100, 120]], "styles": [entry], "early_game": {}}
    md = rc.render_markdown(data)
    assert "Ladder, metal mine L100 -> L120" in md and "R6" in md and "simulator invariants" in md.lower()
    src = tmp_path / "recon.json"
    out = tmp_path / "recon.md"
    src.write_text(json.dumps(data), encoding="utf-8")
    assert rc.main(["--render-from", str(src), "--out-md", str(out)]) == 0
    assert out.read_text(encoding="utf-8").strip() == md.strip()
