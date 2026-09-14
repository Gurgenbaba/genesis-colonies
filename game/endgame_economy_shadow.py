"""Shadow comparison helpers for the coordinated Endgame Economy V2 cutover."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .db import table_exists
from .models import get_planet_buildings, get_planets_by_player, get_research_levels
from .progression_valuation import (
    VALUATION_VERSION,
    building_progression_resources_v2,
    research_progression_resources_v2,
)
from .resource_score import score_from_resources


def _building_score_v2(player_id: int, *, conn) -> int:
    from .buildings import BUILDING_ORDER

    metal = crystal = fuel = 0
    for planet in get_planets_by_player(int(player_id), conn=conn):
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        for key in BUILDING_ORDER:
            level = int(buildings.get(key, 0) or 0)
            if level <= 0:
                continue
            m, c, f = building_progression_resources_v2(str(key), level)
            metal += m
            crystal += c
            fuel += f
    return score_from_resources(metal, crystal, fuel)


def _research_score_v2(player_id: int, *, conn) -> int:
    from .research import RESEARCH_TECHS

    metal = crystal = fuel = 0
    levels = get_research_levels(int(player_id), conn=conn)
    for key in RESEARCH_TECHS:
        level = int(levels.get(key, 0) or 0)
        if level <= 0:
            continue
        m, c, f = research_progression_resources_v2(str(key), level)
        metal += m
        crystal += c
        fuel += f
    return score_from_resources(metal, crystal, fuel)


def compute_player_v2_scores(player_id: int, *, conn) -> Dict[str, int]:
    """Compute V2 progression components without mutating cached/stored ranking rows."""
    from .ranking_core import compute_player_scores

    old = compute_player_scores(int(player_id), conn=conn)
    building = _building_score_v2(int(player_id), conn=conn)
    research = _research_score_v2(int(player_id), conn=conn)
    fleet = int(old.get("fleet_score", 0) or 0)
    defense = int(old.get("defense_score", 0) or 0)
    evolution = int(old.get("evolution_score", 0) or 0)
    return {
        "total_score": building + research + fleet + defense + evolution,
        "resource_score": int(old.get("resource_score", 0) or 0),
        "building_score": building,
        "research_score": research,
        "fleet_score": fleet,
        "defense_score": defense,
        "combat_score": int(old.get("combat_score", 0) or 0),
        "destroyed_score": int(old.get("destroyed_score", 0) or 0),
        "destroyed_raw": int(old.get("destroyed_raw", 0) or 0),
        "military_score": int(old.get("military_score", 0) or 0),
        "evolution_score": evolution,
    }


def _rank_map(rows: List[Dict[str, Any]], prefix: str) -> Dict[int, int]:
    ordered = sorted(
        rows,
        key=lambda row: (
            -int(row[f"{prefix}_total_score"]),
            -int(row[f"{prefix}_building_score"]),
            -int(row[f"{prefix}_research_score"]),
            int(row["player_id"]),
        ),
    )
    return {int(row["player_id"]): idx + 1 for idx, row in enumerate(ordered)}


def _corridor_allowed(attacker_score: int, defender_score: int, factor: int) -> bool:
    atk = max(0, int(attacker_score))
    deff = max(0, int(defender_score))
    fac = max(1, int(factor))
    if atk <= 0 or deff <= 0:
        return True
    min_def = (atk + fac - 1) // fac
    max_def = atk * fac
    return min_def <= deff <= max_def


def _noob_protection_allowed(
    attacker_score: int,
    defender_score: int,
    factor: int,
    *,
    defender_inactive: bool,
) -> bool:
    # Canonical gameplay exception: inactive defenders are always attackable.
    return bool(defender_inactive) or _corridor_allowed(attacker_score, defender_score, factor)


def _commander_milestone_delta(player_id: int, old_score: int, new_score: int, *, conn) -> Dict[str, Any]:
    try:
        from .commander_class_catalog import SP_MILESTONES
    except Exception:
        return {"claimed": [], "old_eligible_unclaimed": [], "new_eligible_unclaimed": []}
    claimed: set[str] = set()
    if table_exists(conn, "player_commander_sp_claims"):
        cur = conn.cursor()
        cur.execute(
            "SELECT milestone_key FROM player_commander_sp_claims WHERE player_id = ?;",
            (int(player_id),),
        )
        claimed = {str(row["milestone_key"]) for row in (cur.fetchall() or [])}
    old_eligible: List[str] = []
    new_eligible: List[str] = []
    for ms in SP_MILESTONES:
        key = str(ms["key"])
        if key in claimed:
            continue
        threshold = int(ms["min_score"])
        if int(old_score) >= threshold:
            old_eligible.append(key)
        if int(new_score) >= threshold:
            new_eligible.append(key)
    return {
        "claimed": sorted(claimed),
        "old_eligible_unclaimed": old_eligible,
        "new_eligible_unclaimed": new_eligible,
        "lost_unclaimed_eligibility": sorted(set(old_eligible) - set(new_eligible)),
        "gained_unclaimed_eligibility": sorted(set(new_eligible) - set(old_eligible)),
    }


def build_shadow_ranking_report(*, conn, noob_factor: int = 5, max_pair_examples: int = 250) -> Dict[str, Any]:
    """Compare current ranking with V2 without changing any live score row."""
    from .ranking_core import compute_player_scores, is_player_id_inactive

    cur = conn.cursor()
    cur.execute("SELECT id FROM players ORDER BY id ASC;")
    player_ids = [int(row["id"]) for row in (cur.fetchall() or [])]
    inactive_by_player = {
        int(player_id): bool(is_player_id_inactive(int(player_id), conn=conn))
        for player_id in player_ids
    }

    rows: List[Dict[str, Any]] = []
    for player_id in player_ids:
        old = compute_player_scores(player_id, conn=conn)
        new = compute_player_v2_scores(player_id, conn=conn)
        row: Dict[str, Any] = {
            "player_id": player_id,
            "inactive": bool(inactive_by_player[player_id]),
            "old_total_score": int(old["total_score"]),
            "new_total_score": int(new["total_score"]),
            "old_resource_score": int(old["resource_score"]),
            "new_resource_score": int(new["resource_score"]),
            "old_building_score": int(old["building_score"]),
            "new_building_score": int(new["building_score"]),
            "old_research_score": int(old["research_score"]),
            "new_research_score": int(new["research_score"]),
            "fleet_score": int(new["fleet_score"]),
            "defense_score": int(new["defense_score"]),
            "evolution_score": int(new["evolution_score"]),
        }
        row["commander_sp"] = _commander_milestone_delta(
            player_id,
            row["old_total_score"],
            row["new_total_score"],
            conn=conn,
        )
        rows.append(row)

    old_ranks = _rank_map(rows, "old")
    new_ranks = _rank_map(rows, "new")
    for row in rows:
        pid = int(row["player_id"])
        row["old_rank"] = old_ranks[pid]
        row["new_rank"] = new_ranks[pid]
        row["rank_delta"] = old_ranks[pid] - new_ranks[pid]
        row["score_delta"] = int(row["new_total_score"]) - int(row["old_total_score"])

    changed_pairs: List[Dict[str, Any]] = []
    changed_count = 0
    fac = max(1, int(noob_factor))
    for attacker in rows:
        for defender in rows:
            if attacker["player_id"] == defender["player_id"]:
                continue
            defender_inactive = bool(defender["inactive"])
            old_allowed = _noob_protection_allowed(
                attacker["old_total_score"],
                defender["old_total_score"],
                fac,
                defender_inactive=defender_inactive,
            )
            new_allowed = _noob_protection_allowed(
                attacker["new_total_score"],
                defender["new_total_score"],
                fac,
                defender_inactive=defender_inactive,
            )
            if old_allowed == new_allowed:
                continue
            changed_count += 1
            if len(changed_pairs) < max(0, int(max_pair_examples)):
                changed_pairs.append(
                    {
                        "attacker_id": int(attacker["player_id"]),
                        "defender_id": int(defender["player_id"]),
                        "defender_inactive": defender_inactive,
                        "old_allowed": old_allowed,
                        "new_allowed": new_allowed,
                        "old_attacker_score": int(attacker["old_total_score"]),
                        "old_defender_score": int(defender["old_total_score"]),
                        "new_attacker_score": int(attacker["new_total_score"]),
                        "new_defender_score": int(defender["new_total_score"]),
                    }
                )

    return {
        "valuation_version": VALUATION_VERSION,
        "player_count": len(rows),
        "noob_factor": fac,
        "players": rows,
        "pvp_pairing_changed_count": changed_count,
        "pvp_pairing_changed_examples": changed_pairs,
        # Backward-compatible aliases for early GC-ENDGAME-ECO-REBASE-002 tooling.
        "pvp_score_corridor_changed_count": changed_count,
        "pvp_score_corridor_changed_examples": changed_pairs,
        "notes": [
            "PvP comparison mirrors the 5x score corridor and the inactive-defender bypass.",
            "Claimed Commander SP milestones are reported separately and are never revoked by V2.",
            "No player_scores rows are mutated by this report.",
        ],
    }
