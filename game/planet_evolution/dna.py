"""Deterministic planet DNA generation."""

from __future__ import annotations

import hashlib
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from ..models import get_game_settings
from .constants import AFFINITY_KEYS
from .definitions import get_traits

# SQLite INTEGER is signed 64-bit; keep seeds in [0, 2^63-1].
MAX_SQLITE_SIGNED_INT = (1 << 63) - 1


def _stable_seed(*parts: Any, server_salt: str = "") -> int:
    raw = "|".join(str(p) for p in parts) + "|" + str(server_salt)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) & MAX_SQLITE_SIGNED_INT


def _class_for_seed(rng: random.Random) -> str:
    weights = {
        "terrestrial": 40,
        "volcanic": 15,
        "ice": 15,
        "barren": 12,
        "oceanic": 10,
        "ruin": 5,
        "gas_giant_moon": 3,
    }
    keys = list(weights.keys())
    vals = [weights[k] for k in keys]
    return rng.choices(keys, weights=vals, k=1)[0]


def _draw_traits(
    rng: random.Random,
    category: str,
    count: int,
    planet_class: str,
    exclude: set[str],
) -> List[str]:
    pool = [
        (k, v)
        for k, v in get_traits().items()
        if v.get("category") == category and k not in exclude
    ]
    if not pool:
        return []
    picked: List[str] = []
    for _ in range(count):
        weighted: List[Tuple[str, float]] = []
        for key, trait in pool:
            if key in picked:
                continue
            w = float(trait.get("weight", 1.0) or 1.0)
            class_w = trait.get("planet_class_weights") or {}
            if isinstance(class_w, dict) and planet_class in class_w:
                w *= float(class_w[planet_class])
            if w > 0:
                weighted.append((key, w))
        if not weighted:
            break
        keys, weights = zip(*weighted)
        choice = rng.choices(list(keys), weights=list(weights), k=1)[0]
        picked.append(choice)
    return picked


def _compute_affinities(all_trait_keys: List[str]) -> Dict[str, int]:
    scores = {k: 30 for k in AFFINITY_KEYS}
    for key in all_trait_keys:
        trait = get_traits().get(key) or {}
        effects_raw = trait.get("effects_json") or trait.get("effects") or {}
        if isinstance(effects_raw, str):
            continue
        affinity = effects_raw.get("affinity") if isinstance(effects_raw, dict) else {}
        if isinstance(affinity, dict):
            for k, delta in affinity.items():
                if k in scores:
                    scores[k] = max(0, min(100, scores[k] + int(delta)))
    return scores


def _compute_risk_profile(all_trait_keys: List[str]) -> Dict[str, Any]:
    profile: Dict[str, Any] = {"event_rate_mult": 1.0, "failure_types": []}
    for key in all_trait_keys:
        trait = get_traits().get(key) or {}
        risk = trait.get("risk_json") or trait.get("risk") or {}
        if isinstance(risk, dict):
            if "event_rate_mult" in risk:
                profile["event_rate_mult"] *= float(risk["event_rate_mult"])
            for ft in risk.get("failure_types") or []:
                if ft not in profile["failure_types"]:
                    profile["failure_types"].append(ft)
    return profile


def _compute_resource_potential(all_trait_keys: List[str], planet_class: str) -> Dict[str, float]:
    pot = {"metal": 1.0, "crystal": 1.0, "special_bias": 0.0}
    if "ferronit_rich_crust" in all_trait_keys:
        pot["metal"] = 1.25
    if "crytite_veins" in all_trait_keys:
        pot["crystal"] = 1.20
    if planet_class == "barren":
        pot["metal"] *= 1.15
    if planet_class == "ice":
        pot["crystal"] *= 1.10
    return pot


def _compute_rarity_tier(anomaly: List[str], hidden: List[str], affinities: Dict[str, int]) -> str:
    score = 0
    if anomaly:
        score += 2
    if len(hidden) >= 2:
        score += 1
    if affinities and max(affinities.values()) >= 75:
        score += 1
    if any(k in anomaly for k in ("dark_matter_residue", "quantum_echo_field")):
        score += 2
    tiers = ["common", "uncommon", "rare", "epic", "legendary"]
    return tiers[min(len(tiers) - 1, score)]


def generate_planet_dna(
    *,
    galaxy: int = 1,
    system: Optional[int] = None,
    position: Optional[int] = None,
    planet_class: Optional[str] = None,
    is_homeworld: bool = False,
    server_salt: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        settings = get_game_settings()
        salt = server_salt or settings.get("planet_evolution_server_salt", "genesis_colonies_v1")
    except Exception:
        salt = server_salt or "genesis_colonies_v1"

    seed = _stable_seed(galaxy, system or 0, position or 0, salt)
    rng = random.Random(seed)

    if not planet_class:
        planet_class = _class_for_seed(rng)

    exclude: set[str] = set()
    geology = _draw_traits(rng, "geology", rng.randint(2, 3), planet_class, exclude)
    exclude.update(geology)
    atmosphere = _draw_traits(rng, "atmosphere", rng.randint(1, 2), planet_class, exclude)
    exclude.update(atmosphere)
    environment = _draw_traits(rng, "environment", rng.randint(0, 2), planet_class, exclude)
    exclude.update(environment)

    anomaly: List[str] = []
    if not is_homeworld and rng.random() < 0.35:
        anomaly = _draw_traits(rng, "anomaly", 1, planet_class, exclude)
        exclude.update(anomaly)
    elif is_homeworld and "ferronit_rich_crust" not in geology:
        geology.append("ferronit_rich_crust")

    hidden = _draw_traits(rng, "hidden", rng.randint(1, 2), planet_class, exclude)

    all_traits = geology + atmosphere + environment + anomaly + hidden
    affinities = _compute_affinities(all_traits)
    risk_profile = _compute_risk_profile(geology + atmosphere + environment + anomaly + hidden)
    resource_potential = _compute_resource_potential(geology + atmosphere + environment + anomaly, planet_class)
    rarity_tier = "uncommon" if is_homeworld else _compute_rarity_tier(anomaly, hidden, affinities)

    return {
        "dna_seed": seed,
        "planet_class": planet_class,
        "rarity_tier": rarity_tier,
        "geology_traits": geology,
        "atmosphere_traits": atmosphere,
        "environment_traits": environment,
        "anomaly_traits": anomaly,
        "hidden_traits": hidden,
        "affinity_scores": affinities,
        "risk_profile": risk_profile,
        "resource_potential": resource_potential,
        "generated_at": time.time(),
    }


def all_trait_keys(dna: Dict[str, Any], reveal_tier: int = 3) -> List[str]:
    keys = (
        list(dna.get("geology_traits") or [])
        + list(dna.get("atmosphere_traits") or [])
        + list(dna.get("environment_traits") or [])
        + list(dna.get("anomaly_traits") or [])
    )
    hidden = list(dna.get("hidden_traits") or [])
    if reveal_tier >= 1 and hidden:
        keys.append(hidden[0])
    if reveal_tier >= 2 and len(hidden) > 1:
        keys.extend(hidden[1:])
    return list(dict.fromkeys(keys))
