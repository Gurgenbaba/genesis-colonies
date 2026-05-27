"""Culture drift and emergent archetype shifts."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional

from .constants import CULTURE_ARCHETYPES
from .definitions import get_policy, get_specialization
from .repository import ensure_planet_culture, get_planet_culture, get_planet_row, get_policies


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(val)))


def _archetype_drift_bias(archetype: str) -> Dict[str, float]:
    biases: Dict[str, Dict[str, float]] = {
        "frontier_settlers": {},
        "militarized_society": {"militarization": 0.15, "loyalty": 0.05},
        "scientific_collective": {"science_focus": 0.20, "prosperity": -0.05},
        "corporate_syndicate": {"prosperity": 0.15, "crime": 0.08},
        "ai_governance": {"loyalty": -0.05, "science_focus": 0.10},
        "criminal_underworld": {"crime": 0.20, "loyalty": -0.10},
        "industrial_union_state": {"industrial_pressure": 0.25, "stability": -0.05},
        "isolationists": {"prosperity": -0.05, "militarization": 0.05},
    }
    return dict(biases.get(archetype, {}))


def _policy_drift(planet_id: int, conn: sqlite3.Connection) -> Dict[str, float]:
    drift: Dict[str, float] = {}
    for pol in get_policies(planet_id, conn=conn):
        pdef = get_policy(str(pol["policy_key"])) or {}
        tradeoffs = pdef.get("tradeoffs") or {}
        for key, delta in tradeoffs.items():
            stat = key.replace("_drift", "")
            if stat in (
                "stability",
                "loyalty",
                "prosperity",
                "militarization",
                "science_focus",
                "crime",
                "industrial_pressure",
            ):
                drift[stat] = drift.get(stat, 0.0) + float(delta)
    return drift


def _spec_drift(planet_id: int, conn: sqlite3.Connection) -> Dict[str, float]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    spec_key = planet.get("specialization_key")
    tier = int(planet.get("specialization_tier") or 0)
    if not spec_key or tier <= 0:
        return {}
    spec = get_specialization(str(spec_key)) or {}
    bundle = (spec.get("tier_mechanics") or {}).get(f"tier_{tier}") or {}
    raw = bundle.get("culture_drift") or {}
    return {str(k): float(v) for k, v in raw.items()}


def pick_archetype_drift(culture: Dict[str, Any]) -> Optional[str]:
    """Pick emergent archetype when drift thresholds exceeded."""
    scores: Dict[str, float] = {a: 0.0 for a in CULTURE_ARCHETYPES}
    crime = float(culture.get("crime") or 0)
    mil = float(culture.get("militarization") or 0)
    sci = float(culture.get("science_focus") or 0)
    ind = float(culture.get("industrial_pressure") or 0)
    pro = float(culture.get("prosperity") or 0)

    if crime >= 55:
        scores["criminal_underworld"] += 2.0
    if mil >= 65:
        scores["militarized_society"] += 2.0
    if sci >= 70:
        scores["scientific_collective"] += 2.0
    if ind >= 70:
        scores["industrial_union_state"] += 2.0
    if pro >= 75 and crime >= 35:
        scores["corporate_syndicate"] += 1.5
    if float(culture.get("loyalty") or 0) >= 85 and sci >= 55:
        scores["ai_governance"] += 1.0

    current = str(culture.get("archetype_key") or "frontier_settlers")
    best_key = max(scores, key=lambda k: scores[k])
    if scores[best_key] >= 2.0 and best_key != current:
        return best_key
    return None


def apply_culture_drift(
    conn: sqlite3.Connection,
    planet_id: int,
    delta_hours: float,
) -> Dict[str, Any]:
    if delta_hours <= 0:
        return {"applied": False}

    ensure_planet_culture(planet_id, conn)
    culture = get_planet_culture(planet_id, conn=conn)
    archetype = str(culture.get("archetype_key") or "frontier_settlers")
    day_frac = float(delta_hours) / 24.0

    drift: Dict[str, float] = {}
    for stat, per_day in _archetype_drift_bias(archetype).items():
        drift[stat] = drift.get(stat, 0.0) + per_day * day_frac

    for stat, val in _policy_drift(planet_id, conn).items():
        drift[stat] = drift.get(stat, 0.0) + float(val) * day_frac

    for stat, val in _spec_drift(planet_id, conn).items():
        drift[stat] = drift.get(stat, 0.0) + float(val) * day_frac

    from .failures import active_failure_keys

    if "reactor_crisis" in active_failure_keys(planet_id, conn):
        drift["stability"] = drift.get("stability", 0.0) - 0.5 * day_frac
    if "stability_collapse" in active_failure_keys(planet_id, conn):
        drift["stability"] = drift.get("stability", 0.0) - 1.0 * day_frac

    updated = dict(culture)
    for stat in (
        "stability",
        "loyalty",
        "prosperity",
        "militarization",
        "science_focus",
        "crime",
        "industrial_pressure",
    ):
        updated[stat] = _clamp(float(updated.get(stat, 0) or 0) + drift.get(stat, 0.0))

    new_archetype = pick_archetype_drift(updated)
    if new_archetype:
        updated["archetype_key"] = new_archetype
        cur = conn.cursor()
        cur.execute(
            "UPDATE planets SET culture_archetype = ? WHERE id = ?;",
            (str(new_archetype), int(planet_id)),
        )

    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planet_culture SET
            archetype_key = ?,
            stability = ?,
            loyalty = ?,
            prosperity = ?,
            militarization = ?,
            science_focus = ?,
            crime = ?,
            industrial_pressure = ?,
            last_drift_at = ?
        WHERE planet_id = ?;
        """,
        (
            str(updated["archetype_key"]),
            float(updated["stability"]),
            float(updated["loyalty"]),
            float(updated["prosperity"]),
            float(updated["militarization"]),
            float(updated["science_focus"]),
            float(updated["crime"]),
            float(updated["industrial_pressure"]),
            time.time(),
            int(planet_id),
        ),
    )

    result: Dict[str, Any] = {
        "applied": True,
        "delta_hours": delta_hours,
        "drift": drift,
        "culture": updated,
        "archetype_changed": new_archetype,
    }

    if float(updated["stability"]) < 25 and float(updated["loyalty"]) < 40:
        from .failures import apply_failure

        apply_failure(planet_id, "stability_collapse", conn, duration_hours=72)

    return result
