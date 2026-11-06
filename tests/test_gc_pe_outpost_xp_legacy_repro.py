"""Reproduction (sandbox, canonical owners): XP on a level-0 outpost ends its outpost status.

Findings from the Trait-R3 player-journey simulator (docs/GC_TRAIT_R3_PLAYER_JOURNEY_REPORT.md):

* `add_planet_xp` reads `planet_level or 1`, so the first XP grant on a level-0 outpost writes
  `planet_level = 1` (colonize XP of 300 writes level 2).
* `is_legacy_full_colony()` treats `planet_level >= 1` as a grandfathered colony, so
  `is_outpost_planet()` turns False without any establishment milestone.
* `ensure_planet_evolution()` -> `bootstrap_legacy_establishment()` then sets `dna_reveal_tier = 1`
  on the next planet load.

The build queue deliberately has no outpost gate (GC-976, see test_galaxy_gameplay_contract.py), so
this is NOT a building unlock exploit; the affected rules are "DNA hidden until establishment" and
the outpost-only mechanics flags (world-type start conditions).

The two `xfail` tests assert the documented intent (docs/EXPANSION_PROTOCOL.md) and are expected to
fail until a separate fix lands; `strict=False` so the fix PR can simply drop the marker.
No DNA is re-rolled by any of this.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import player_journey_sim as pj  # noqa: E402
from game.activity_xp import SOURCE_COLONIZE, grant_activity_xp, grant_fleet_activity_xp  # noqa: E402
from game.planet_evolution.bootstrap import ensure_planet_evolution  # noqa: E402
from game.planet_evolution.expansion_phase import is_establishment_complete  # noqa: E402
from game.planet_evolution.expansion_protocol import is_outpost_planet  # noqa: E402


def _fresh_outpost(sb: pj.Sandbox) -> int:
    sb.conn.execute("UPDATE planets SET planet_level = 5 WHERE id = ?;", (sb.home_planet_id,))
    sb.set_research("interstellar_expansion", 1)
    ok, reason, pid = sb.found_colony("ReproOutpost", sb.next_binding())
    assert ok, reason
    return pid


def _row(sb: pj.Sandbox, pid: int) -> dict:
    return dict(sb.conn.execute("SELECT planet_level, planet_xp, dna_reveal_tier FROM planets WHERE id = ?;", (pid,)).fetchone())


def test_fresh_outpost_is_level_zero_hidden_and_restricted():
    with pj.Sandbox() as sb:
        pid = _fresh_outpost(sb)
        ensure_planet_evolution(pid, sb.conn)
        row = _row(sb, pid)
        assert (row["planet_level"], row["planet_xp"], row["dna_reveal_tier"]) == (0, 0, 0)
        assert is_outpost_planet(pid, conn=sb.conn)
        assert not is_establishment_complete(pid, conn=sb.conn)


@pytest.mark.xfail(reason="add_planet_xp: `planet_level or 1` lifts a level-0 outpost to level>=1 on the first XP grant", strict=False)
def test_first_xp_grant_keeps_unestablished_outpost_restricted():
    with pj.Sandbox() as sb:
        pid = _fresh_outpost(sb)
        res = grant_activity_xp(sb.user_id, pid, "building_finish", conn=sb.conn, idempotency_key="repro:b1", now=pj.SIM_EPOCH + 5)
        sb.conn.commit()
        assert res["granted"] and res["amount"] == 3
        assert is_outpost_planet(pid, conn=sb.conn), "3 XP from one building must not end outpost status"


@pytest.mark.xfail(reason="colonize XP (300) -> level 2 -> legacy full colony -> bootstrap reveals dna_reveal_tier=1 before establishment", strict=False)
def test_colonize_xp_does_not_reveal_dna_before_establishment():
    with pj.Sandbox() as sb:
        pid = _fresh_outpost(sb)
        grant_fleet_activity_xp(sb.user_id, pid, SOURCE_COLONIZE, 4242, conn=sb.conn, now=pj.SIM_EPOCH + 100.0)
        sb.conn.commit()
        ensure_planet_evolution(pid, sb.conn)  # first planet load after arrival
        sb.conn.commit()
        assert not is_establishment_complete(pid, conn=sb.conn)
        assert _row(sb, pid)["dna_reveal_tier"] == 0, "DNA must stay hidden until the establishment milestones are met"
