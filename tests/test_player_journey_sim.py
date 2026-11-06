"""Trait-R3 player-journey simulator (measurement only) - contract tests.

The simulator must run canonical owners in a throw-away sandbox, stay
deterministic, never bypass the colony cap/gates, never leak hidden DNA, and
never enable R3 live.  Horizons are short so the suite stays fast.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for _p in (ROOT, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import player_journey_sim as pj  # noqa: E402
from game.buildings import get_upgrade_cost  # noqa: E402
from game.planet_evolution import dna_analysis  # noqa: E402
from game.planet_evolution.expansion_protocol import (  # noqa: E402
    COLONY_MATURITY_REQUIRED_LEVEL,
    expansion_slots_unlocked,
)


def _run(sid: str, topology: str, policy: str, days: float, *, trait: str = "none", climate: str = "mid", **kw):
    sc = pj.Scenario(sid, topology, policy, climate, trait, days, **kw)
    return pj.run_scenario(sc, curve="uni1")


def _strip(result: dict) -> dict:
    out = dict(result)
    out.pop("wall_seconds", None)
    return out


def test_s1_is_deterministic_and_never_touches_configured_db(monkeypatch, tmp_path):
    marker = tmp_path / "must_not_be_created.db"
    monkeypatch.setenv("GC_DB_PATH", str(marker))
    a = _run("S1-a", "S1", "active", 12)
    b = _run("S1-a", "S1", "active", 12)
    assert json.dumps(_strip(a), sort_keys=True) == json.dumps(_strip(b), sort_keys=True)
    assert not marker.exists(), "sandbox must not use the configured database path"
    import os

    assert os.environ["GC_DB_PATH"] == str(marker), "sandbox must restore the environment"


def test_first_decisions_use_canonical_costs():
    with pj.Sandbox() as sb:
        j = pj.Journey(pj.Scenario("t", "S1", "active", "mid"), sb)
        key, target, cm, cc = j.choose_build(j.hw())
        assert (key, target) == ("solar_plant", 1)
        assert (cm, cc) == tuple(int(v) for v in get_upgrade_cost("solar_plant", 0))
        assert j.hw().metal == 150000 and j.hw().crystal == 100000


def test_s1_scan_cooldown_cost_and_tier_invariants():
    r = _run("S1-scan", "S1", "active", 40)
    assert r["invariants"]["ok"], r["invariants"]
    world = r["final"]["per_world"][0]
    assert world["scans"] >= 1
    assert world["scans"] <= 40, "at most one DNA analysis per rolling 24h"
    assert world["scan_spend_metal"] >= world["scans"] * dna_analysis.scan_cost(dna_analysis.SCAN_MIN_LEVEL)["metal"]
    assert world["reveal_tier"] >= 1 and world["planet_level"] >= dna_analysis.SCAN_MIN_LEVEL
    # no negative or duplicate state anywhere in the daily trace
    assert all(row["empire_metal_h"] >= 0 for row in r["daily"])
    assert r["final"]["paid_accelerators"] == 0
    assert r["final"]["free_accelerators_applied_sec"] == 0


def test_s11_expands_only_through_canonical_gates():
    r = _run("S11-gates", "S11", "optimizer", 75)
    assert r["invariants"]["ok"], r["invariants"]
    founded = [e for e in r["colony_log"] if e["event"] == "founded"]
    assert founded, "an optimizer should found the first colony within 75 days"
    assert len(r["gate_audit"]) >= len(founded)
    for n, audit in enumerate(r["gate_audit"], start=1):
        # Ark level gate: the n-th colony needs the n-th expansion slot
        assert audit["expansion_index"] == n
        assert expansion_slots_unlocked(audit["hw_planet_level"]) >= n, audit
        # maturity gate: every earlier colony reached PL15 before the next one is launched
        assert all(level >= COLONY_MATURITY_REQUIRED_LEVEL for level in audit["colony_levels"]), audit
    # worlds in the report equal the sandbox rows
    assert r["final"]["worlds"] == 1 + len(founded)
    assert r["status"].startswith("partial_blocked") or r["status"] == "complete"
    assert "colony_maturity_required" in r["blockers"] or len(founded) == 1


def test_colony_state_mirrors_canonical_establishment_and_masks_unrevealed_dna():
    from game.planet_evolution.expansion_protocol import is_outpost_planet

    sc = pj.Scenario("mirror", "S11", "active", "mid", "none", 20)
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        journey = pj.Journey(sc, sb)
        result = journey.run()
        assert len(journey.worlds) >= 2
        for w, row in zip(journey.worlds, result["final"]["per_world"]):
            canonical = sb.planet(w.planet_id)
            assert row["reveal_tier"] == canonical["tier"]
            assert row["planet_level"] == canonical["level"]
            if not w.home:
                assert w.outpost == bool(is_outpost_planet(w.planet_id, conn=sb.conn))
            if canonical["tier"] < 1:
                assert row["traits_known"] == 0, "unrevealed worlds must not expose trait counts"


def test_dna_before_establishment_finding_matches_canonical_predicates():
    r = _run("S11-finding", "S11", "optimizer", 20)
    finding = r["findings"].get("dna_revealed_before_establishment")
    early = [w for w in r["final"]["per_world"][1:] if w["dna_before_establishment_day"] is not None]
    assert bool(finding) == bool(early)
    if finding:
        assert "mechanism" in finding and finding["worlds"]


def test_report_never_contains_hidden_trait_names():
    from game.planet_evolution.dna import all_trait_keys
    from game.planet_evolution.repository import get_planet_dna

    sc = pj.Scenario("leak", "S11", "optimizer", "mid", "none", 30)
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        result = pj.Journey(sc, sb).run()
        hidden_names = set()
        for w in result["final"]["per_world"]:
            pid = int(sb.conn.execute("SELECT id FROM planets WHERE player_id = ? ORDER BY id LIMIT 1 OFFSET ?;", (sb.user_id, w["idx"])).fetchone()[0])
            dna = get_planet_dna(pid, conn=sb.conn) or {}
            hidden_names |= set(all_trait_keys(dna, 3)) - set(all_trait_keys(dna, w["reveal_tier"]))
    blob = json.dumps(result)
    leaked = [name for name in hidden_names if name and f'"{name}"' in blob]
    assert not leaked


def test_admin_cap_is_never_bypassed_and_reported_as_unavailable():
    from game.admin_balance import save_balance_settings

    sc = pj.Scenario("cap", "S11", "optimizer", "mid", "none", 40)
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        _settings, err = save_balance_settings({"max_colonies_per_player": 1})
        assert err is None, err
        result = pj.Journey(sc, sb).run()
    assert result["final"]["worlds"] == 1
    assert result["status"] == "scenario_unavailable"
    assert "colony_limit_reached" in result["blockers"]


def test_resonance_requires_reveal_and_active_specialization():
    q = pj.resonance_qualified
    base = dict(enabled=True, planet_level=10, reveal_tier=1, specialization_active=True)
    assert q(**base)
    assert not q(**{**base, "enabled": False})
    assert not q(**{**base, "reveal_tier": 0}), "hidden trait must yield zero resonance"
    assert not q(**{**base, "specialization_active": False})
    assert not q(**{**base, "planet_level": 7}), "below specialisation unlock level"


def test_unqualified_resonance_scenario_equals_zero_trait_baseline():
    base = _run("S1-base", "S1", "active", 6)
    cand = _run("S1-base", "S1", "active", 6, trait="r12_one")
    assert cand["final"]["planet_levels"] == base["final"]["planet_levels"]
    assert cand["resonance_world"] is None, "no world is qualified before planet level 8"
    assert cand["checkpoints"].keys() == base["checkpoints"].keys()
    assert cand["final"]["mine_depth_max"] == base["final"]["mine_depth_max"]
    assert cand["final"]["empire_metal_h"] == base["final"]["empire_metal_h"]


def test_resonance_cap_one_world_only():
    r = _run("S11-res", "S11", "optimizer", 45, trait="r12_one")
    assert r["invariants"]["ok"]
    assert r["resonance_world"] in (None, 0, 1, 2)


def test_cli_writes_json_and_markdown(tmp_path):
    out_json = tmp_path / "pj.json"
    out_md = tmp_path / "pj.md"
    rc = pj.main(["--days", "6", "--quick", "--only", "S1-casual", "--skip-upper-bound", "--out-json", str(out_json), "--out-md", str(out_md)])
    assert rc == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["meta"]["policy_version"] == pj.POLICY_VERSION
    assert data["meta"]["code_sha"]
    assert data["meta"]["settings_digest"]
    assert data["not_modelled"], "limits must be disclosed"
    md = out_md.read_text(encoding="utf-8")
    for heading in ("## Upper bound vs simulated trajectories", "## Blockers", "## Not modelled", "## Invariants"):
        assert heading in md
    assert "R3 not enabled live" in md


def test_scenario_matrix_covers_playstyles_topologies_and_candidates():
    keys = {s.sid for s in pj.build_scenarios(365, quick=False)}
    for policy in ("casual", "active", "optimizer"):
        assert f"S11-{policy}-mid" in keys
        for climate in ("hot", "mid", "cold"):
            assert f"S1-{policy}-{climate}" in keys
    for trait in ("r5_one", "r10_one", "r12_one", "r12_all"):
        assert f"S1-active-mid-{trait}" in keys and f"S11-active-mid-{trait}" in keys
    quick = {s.sid for s in pj.build_scenarios(365, quick=True)}
    assert quick < keys


def test_no_new_gameplay_tables_or_migrations_added_by_simulator():
    migrations = sorted(p.name for p in (ROOT / "migrations").glob("*.sql"))
    assert not any("journey" in name.lower() for name in migrations)
    text = (SCRIPTS / "player_journey_sim.py").read_text(encoding="utf-8")
    assert "CREATE TABLE" not in text.upper()
