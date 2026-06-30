"""Compile planet mechanics from DNA, research, spec, policies, discoveries."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Set

from .constants import MECHANICS_COMPILE_VERSION
from .definitions import get_chain, get_discovery_def, get_policy, get_research_defs, get_specialization, get_ascension
from .dna import all_trait_keys
from .repository import (
    get_discoveries,
    get_locked_choices,
    get_planet_dna,
    get_planet_mechanics,
    get_planet_research_levels,
    get_planet_row,
    get_policies,
    save_planet_mechanics,
)


def _merge_mechanics_bundle(bundle: Dict[str, Any], target: Dict[str, Any]) -> None:
    for unlock in bundle.get("unlocks") or []:
        if unlock not in target["unlocks"]:
            target["unlocks"].append(unlock)
    for k, v in (bundle.get("flags") or {}).items():
        target["flags"][k] = v
    for export in bundle.get("export_slots") or []:
        if export not in target["export_slots"]:
            target["export_slots"].append(export)
    for k, v in (bundle.get("queue_limits") or {}).items():
        prev = int(target["queue_limits"].get(k, 0))
        target["queue_limits"][k] = max(prev, int(v))
    for k, v in (bundle.get("risk_modifiers") or {}).items():
        target["risk_modifiers"][k] = v


def _apply_unlock_token(token: str, out: Dict[str, Any]) -> None:
    raw = str(token or "").strip()
    if not raw:
        return
    if raw.startswith("export:"):
        out["export_slots"].append(raw.split(":", 1)[1])
        return
    if raw.startswith("chain:"):
        out["unlocks"].append(raw)
        out["unlocks"].append(f"required_unlock:{raw}")
        return
    if raw.startswith("policy:"):
        out["flags"][f"policy_unlock:{raw.split(':', 1)[1]}"] = True
        return
    if raw.startswith("enable_event_pool:"):
        out["flags"][f"event_pool:{raw.split(':', 1)[1]}"] = True
        return
    if raw.startswith("trade_route_bonus:"):
        try:
            out["flags"]["trade_route_bonus"] = float(raw.split(":", 1)[1])
        except ValueError:
            out["flags"]["trade_route_bonus"] = 0.15
        return
    if raw.startswith("trade_route_max:"):
        try:
            out["flags"]["trade_route_max"] = int(raw.split(":", 1)[1])
        except ValueError:
            out["flags"]["trade_route_max"] = 6
        return
    if raw.startswith("discovery_roll_bonus:"):
        try:
            out["flags"]["discovery_roll_bonus"] = float(raw.split(":", 1)[1])
        except ValueError:
            pass
        return
    if raw.startswith("experimental_slot:"):
        try:
            out["flags"]["experimental_slot"] = int(out["flags"].get("experimental_slot", 0)) + int(raw.split(":", 1)[1])
        except ValueError:
            pass
        return
    if raw.startswith("conversion_queue:"):
        try:
            out["queue_limits"]["conversion"] = int(out["queue_limits"].get("conversion", 0)) + int(raw.split(":", 1)[1])
        except ValueError:
            pass
        return
    if raw.startswith("auto_conversion:"):
        try:
            out["flags"]["auto_conversion"] = int(out["flags"].get("auto_conversion", 0)) + int(raw.split(":", 1)[1])
        except ValueError:
            pass
        return
    if raw.startswith("risk:"):
        out["flags"][raw] = True
        return
    if raw in ("enable_experimental", "defense_mechanic", "deep_core_auto", "crime_sweet_spot_mechanic", "market_fee_mechanic", "stability_risk_mechanic", "loyalty_mechanic_bypass"):
        out["flags"][raw] = True
        return
    out["unlocks"].append(raw)


def _parse_mechanics_json(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {"unlocks": [], "flags": {}, "export_slots": [], "queue_limits": {}, "risk_modifiers": {}}
    if raw.get("unlock_chain"):
        ck = str(raw["unlock_chain"])
        out["unlocks"].append(f"chain:{ck}")
        out["unlocks"].append(f"required_unlock:chain:{ck}")
    if raw.get("required_unlock"):
        out["unlocks"].append(str(raw["required_unlock"]))
    if raw.get("unlock_export"):
        out["export_slots"].append(str(raw["unlock_export"]))
    for u in raw.get("unlocks") or []:
        if not isinstance(u, str):
            continue
        _apply_unlock_token(u, out)
    if raw.get("enable_experimental"):
        out["flags"]["experimental_enabled"] = True
    if raw.get("enable_event_pool"):
        pool = str(raw["enable_event_pool"]).strip()
        if pool:
            out["flags"][f"event_pool:{pool}"] = True
    if raw.get("enable_policy"):
        out["flags"][f"policy_unlock:{raw['enable_policy']}"] = True
    if raw.get("unlock_policy_tier"):
        out["flags"]["policy_tier"] = max(int(out["flags"].get("policy_tier", 0)), int(raw["unlock_policy_tier"]))
    if raw.get("unlock_queue"):
        for k, v in (raw["unlock_queue"] or {}).items():
            out["queue_limits"][k] = int(v)
    if raw.get("conversion_queue"):
        out["queue_limits"]["conversion"] = int(out["queue_limits"].get("conversion", 0)) + int(raw["conversion_queue"])
    if raw.get("planet_research_speed_flag"):
        out["flags"]["planet_research_speed_bonus"] = float(out["flags"].get("planet_research_speed_bonus", 0)) + float(raw["planet_research_speed_flag"])
    if raw.get("chain_output_bonus"):
        out["flags"]["chain_output_bonus"] = raw["chain_output_bonus"]
    if raw.get("chain_output_mult"):
        out["flags"]["chain_output_mult"] = float(raw["chain_output_mult"])
    if raw.get("auto_conversion"):
        out["flags"]["auto_conversion"] = int(out["flags"].get("auto_conversion", 0)) + int(raw["auto_conversion"])
    if raw.get("trade_route_bonus"):
        out["flags"]["trade_route_bonus"] = float(raw["trade_route_bonus"])
    if raw.get("discovery_roll_bonus"):
        out["flags"]["discovery_roll_bonus"] = float(raw["discovery_roll_bonus"])
    if raw.get("experimental_slot"):
        out["flags"]["experimental_slot"] = int(out["flags"].get("experimental_slot", 0)) + int(raw["experimental_slot"])
    if raw.get("export_slots"):
        out["flags"]["export_slots_bonus"] = int(out["flags"].get("export_slots_bonus", 0)) + int(raw["export_slots"])
    if raw.get("stability_penalty"):
        out["flags"]["stability_penalty"] = float(raw["stability_penalty"])
    if raw.get("permanent_flag"):
        out["flags"][str(raw["permanent_flag"])] = True
    if raw.get("auto_research_weekly"):
        out["flags"]["auto_research_weekly"] = int(raw["auto_research_weekly"])
    return out


def compile_planet_mechanics(planet_id: int, conn: sqlite3.Connection) -> Dict[str, Any]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    dna = get_planet_dna(planet_id, conn=conn) or {}
    reveal = int(planet.get("dna_reveal_tier") or 0)
    traits = all_trait_keys(dna, reveal_tier=max(reveal, 1))
    research_levels = get_planet_research_levels(planet_id, conn=conn)

    compiled: Dict[str, Any] = {
        "unlocks": [],
        "flags": {"trait_keys": traits, "locked_choices": get_locked_choices(planet_id, conn=conn)},
        "export_slots": [],
        "queue_limits": {"planet_research": 2, "conversion": 0},
        "risk_modifiers": {},
        "compile_version": MECHANICS_COMPILE_VERSION,
    }

    spec_key = planet.get("specialization_key")
    spec_tier = int(planet.get("specialization_tier") or 0)
    if spec_key:
        spec = get_specialization(spec_key) or {}
        for tier in range(1, spec_tier + 1):
            bundle = (spec.get("tier_mechanics") or {}).get(f"tier_{tier}") or {}
            _merge_mechanics_bundle(_parse_mechanics_json(bundle), compiled)

    for tech_key, level in research_levels.items():
        if level <= 0:
            continue
        mech = (get_research_defs().get(tech_key) or {}).get("mechanics") or {}
        _merge_mechanics_bundle(_parse_mechanics_json(mech), compiled)

    for pol in get_policies(planet_id, conn=conn):
        pdef = get_policy(str(pol["policy_key"])) or {}
        _merge_mechanics_bundle(_parse_mechanics_json(pdef.get("mechanics") or {}), compiled)

    for disc in get_discoveries(planet_id, conn=conn):
        ddef = get_discovery_def(str(disc["discovery_key"])) or {}
        _merge_mechanics_bundle(_parse_mechanics_json(ddef.get("mechanics") or {}), compiled)

    if planet.get("ascension_key"):
        adef = get_ascension(str(planet["ascension_key"])) or {}
        _merge_mechanics_bundle(_parse_mechanics_json(adef.get("permanent_mechanics") or {}), compiled)

    save_planet_mechanics(planet_id, compiled, conn)
    _sync_production_chains(planet_id, compiled, conn)
    _sync_import_demands(planet_id, spec_key, spec_tier, conn)
    return compiled


def _sync_production_chains(planet_id: int, mechanics: Dict[str, Any], conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    active: Set[str] = set()
    for u in mechanics.get("unlocks") or []:
        if u.startswith("chain:"):
            active.add(u.split(":", 1)[1])
        elif u.startswith("required_unlock:chain:"):
            active.add(u.split(":", 2)[2])
    cur.execute("UPDATE planet_production_chains SET is_active = 0 WHERE planet_id = ?;", (int(planet_id),))
    for chain_key in active:
        chain = get_chain(chain_key)
        if not chain:
            continue
        cur.execute(
            """
            INSERT INTO planet_production_chains (planet_id, chain_key, building_key, is_active, efficiency, last_tick_at)
            VALUES (?, ?, ?, 1, 1.0, strftime('%s','now'))
            ON CONFLICT(planet_id, chain_key) DO UPDATE SET is_active = 1;
            """,
            (int(planet_id), chain_key, str(chain.get("required_building", "virtual"))),
        )


def _sync_import_demands(planet_id: int, spec_key: str | None, spec_tier: int, conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM planet_import_demands WHERE planet_id = ?;", (int(planet_id),))
    if not spec_key or spec_tier < 1:
        return
    spec = get_specialization(spec_key) or {}
    seen = set()
    for tier in range(1, max(1, spec_tier) + 1):
        tier_bundle = (spec.get("tier_mechanics") or {}).get(f"tier_{tier}") or {}
        demands = tier_bundle.get("import_demands") or []
        if tier == 1 and not demands:
            demands = spec.get("import_demands") or []
        for d in demands:
            if not isinstance(d, dict):
                continue
            res = str(d.get("resource_key"))
            if res in seen:
                continue
            seen.add(res)
            cur.execute(
                "INSERT INTO planet_import_demands (planet_id, resource_key, required_per_hour, deficit_penalty_key) VALUES (?, ?, ?, ?);",
                (int(planet_id), res, float(d.get("required_per_hour", 0)), str(d.get("deficit_penalty_key", "chain_efficiency_halved"))),
            )


def get_flag(planet_id: int, flag: str, default: Any = None, conn: sqlite3.Connection | None = None) -> Any:
    mech = get_planet_mechanics(planet_id, conn=conn)
    return (mech.get("flags") or {}).get(flag, default)
