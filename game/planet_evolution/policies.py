"""Planet policy eligibility — unlock flags and tier gates from compiled mechanics."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from typing import Any, Dict, Optional, Set, Tuple

from .definitions import get_research_defs, get_specializations
from .mechanics import get_flag


@lru_cache(maxsize=1)
def policies_requiring_explicit_unlock() -> frozenset[str]:
    """Policy keys that must have policy_unlock:{key} in compiled planet mechanics."""
    keys: Set[str] = set()
    for rdef in get_research_defs().values():
        mech = rdef.get("mechanics") or {}
        if mech.get("enable_policy"):
            keys.add(str(mech["enable_policy"]))
        for token in mech.get("unlocks") or []:
            if isinstance(token, str) and token.startswith("policy:"):
                keys.add(token.split(":", 1)[1])
    for spec in get_specializations().values():
        for tier_bundle in (spec.get("tier_mechanics") or {}).values():
            for token in tier_bundle.get("unlocks") or []:
                if isinstance(token, str) and token.startswith("policy:"):
                    keys.add(token.split(":", 1)[1])
    return frozenset(keys)


def policy_explicitly_unlocked(planet_id: int, policy_key: str, conn: sqlite3.Connection) -> bool:
    if policy_key not in policies_requiring_explicit_unlock():
        return True
    return bool(get_flag(planet_id, f"policy_unlock:{policy_key}", False, conn=conn))


def mechanics_policy_tier_unlocked(planet_id: int, conn: sqlite3.Connection) -> Optional[int]:
    """
    Highest policy definition tier unlocked via compiled mechanics (unlock-only).

    None when the flag is absent — legacy: no mechanics-based tier gate for tier-1 policies.
    """
    raw = get_flag(planet_id, "policy_tier", None, conn=conn)
    if raw is None:
        return None
    return int(raw or 0)


def evaluate_policy_gate(
    planet_id: int,
    policy_key: str,
    *,
    policy_def: Dict[str, Any],
    slot: int,
    archetype_key: str,
    conn: sqlite3.Connection,
) -> Tuple[bool, Optional[str]]:
    """
    Returns (eligible, locked_reason_key).

    locked_reason_key is a locales key (pe_policy_*) when not eligible.
    """
    min_slot = int(policy_def.get("tier") or 1)
    if min_slot > int(slot):
        return False, "pe_policy_tier_locked"

    allowed = policy_def.get("archetype_allow") or []
    if allowed and str(archetype_key or "") not in [str(a) for a in allowed]:
        return False, "pe_policy_wrong_archetype"

    policy_def_tier = int(policy_def.get("tier") or 1)
    if policy_def_tier == 1:
        unlocked = mechanics_policy_tier_unlocked(planet_id, conn)
        if unlocked is not None and unlocked < 1:
            return False, "pe_policy_tier_locked"

    if not policy_explicitly_unlocked(planet_id, policy_key, conn):
        return False, "pe_policy_locked_by_research"

    return True, None


def activation_block_reason(locked_reason_key: Optional[str]) -> str:
    """Map dashboard locale key to API reason string."""
    if locked_reason_key == "pe_policy_locked_by_research":
        return "policy_locked"
    if locked_reason_key == "pe_policy_tier_locked":
        return "policy_tier_locked"
    if locked_reason_key == "pe_policy_wrong_archetype":
        return "archetype_not_allowed"
    return "policy_locked"
