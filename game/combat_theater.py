"""Combat Encounter Theater — timeline + projectile signature contract (GC-CT)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

# Unit key → CSS bolt suffix ``gc-ct-bolt--{signature}`` (signature usually == unit key).
SHIP_SIGNATURES: Dict[str, str] = {
    "spark_drone": "spark_drone",
    "veil_probe": "veil_probe",
    "falcon_interceptor": "falcon_interceptor",
    "solar_skiff": "solar_skiff",
    "mule_courier": "mule_courier",
    "atlas_hauler": "atlas_hauler",
    "ironclad_frigate": "ironclad_frigate",
    "eclipse_runner": "eclipse_runner",
    "harvest_reclaimer": "harvest_reclaimer",
    "seed_ark": "seed_ark",
    "deep_vault_ark": "deep_vault_ark",
    "planet_breaker": "planet_breaker",
}

DEFENSE_SIGNATURES: Dict[str, str] = {
    "slug_launcher": "slug_launcher",
    "sentinel_turret": "sentinel_turret",
    "plasma_arc": "plasma_arc",
    "ion_bastion": "ion_bastion",
    "flak_array": "flak_array",
    "pulse_barrier": "pulse_barrier",
    "orbital_shield": "orbital_shield",
}

# Legacy family map (docs / fallbacks)
SHIP_PROFILES: Dict[str, str] = {
    "spark_drone": "kinetic_light",
    "veil_probe": "kinetic_light",
    "falcon_interceptor": "laser_mid",
    "solar_skiff": "laser_mid",
    "mule_courier": "kinetic_light",
    "atlas_hauler": "kinetic_light",
    "ironclad_frigate": "laser_mid",
    "eclipse_runner": "plasma_heavy",
    "harvest_reclaimer": "laser_mid",
    "seed_ark": "missile",
    "deep_vault_ark": "missile",
    "planet_breaker": "plasma_heavy",
}

DEFENSE_PROFILES: Dict[str, str] = {
    "slug_launcher": "kinetic_light",
    "sentinel_turret": "laser_mid",
    "plasma_arc": "plasma_heavy",
    "ion_bastion": "plasma_heavy",
    "flak_array": "flak",
    "pulse_barrier": "laser_mid",
    "orbital_shield": "missile",
}

# Burst intensity hints for fireSalvo (cosmetic)
BOLT_BURST: Dict[str, Tuple[int, int]] = {
    # key: (min_bolts, max_bolts) per slot per salvo
    "spark_drone": (3, 5),
    "veil_probe": (1, 2),
    "falcon_interceptor": (2, 4),
    "solar_skiff": (2, 3),
    "mule_courier": (1, 2),
    "atlas_hauler": (1, 2),
    "ironclad_frigate": (2, 3),
    "eclipse_runner": (2, 3),
    "harvest_reclaimer": (2, 3),
    "seed_ark": (1, 2),
    "deep_vault_ark": (1, 2),
    "planet_breaker": (1, 2),
    "slug_launcher": (2, 3),
    "sentinel_turret": (2, 3),
    "plasma_arc": (2, 3),
    "ion_bastion": (1, 2),
    "flak_array": (4, 6),
    "pulse_barrier": (1, 2),
    "orbital_shield": (1, 2),
}

# Must match ``BEAT`` in static/js/combat_theater.js
BEAT = {
    "intro": 650,
    "round_announce": 500,
    "salvo_gap": 820,
    "side_switch": 420,
    "resolve_hold": 1100,
    "round_gap": 450,
}

DEFAULT_SIGNATURE = "laser_mid"


def projectile_signature(key: str, kind: str = "ship") -> str:
    """Return CSS bolt signature id for a unit key (ship or defense)."""
    k = str(key or "").strip()
    if str(kind or "").strip().lower() == "defense":
        return DEFENSE_SIGNATURES.get(k) or DEFAULT_SIGNATURE
    if k in DEFENSE_SIGNATURES and k not in SHIP_SIGNATURES:
        return DEFENSE_SIGNATURES[k]
    return SHIP_SIGNATURES.get(k) or DEFAULT_SIGNATURE


def bolt_burst_range(key: str) -> Tuple[int, int]:
    lo, hi = BOLT_BURST.get(str(key or "").strip(), (2, 3))
    return int(lo), int(hi)


def profile_for_ship(key: str) -> str:
    return SHIP_PROFILES.get(str(key or "").strip(), "laser_mid")


def profile_for_defense(key: str) -> str:
    return DEFENSE_PROFILES.get(str(key or "").strip(), "laser_mid")


def _hash_seed(s: str) -> int:
    h = 2166136261
    for ch in str(s or ""):
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def unit_count_total(stock: Mapping[str, Any] | None) -> int:
    return sum(max(0, int(v or 0)) for v in dict(stock or {}).values())


def salvo_count_for_round(seed: str, round_index: int, loss_total: int) -> int:
    if loss_total >= 40:
        return 3
    return 2 if _hash_seed(f"{seed}:r{round_index}") % 2 == 0 else 3


def build_theater_timeline(meta: Mapping[str, Any] | None) -> List[Dict[str, Any]]:
    """Deterministic cue sheet mirroring ``GC.combatTheater.buildTimeline``."""
    safe = dict(meta or {})
    seed = str(safe.get("fleet_id") or safe.get("target_coords") or safe.get("attacker_id") or "combat")
    rounds = list(safe.get("rounds") or [])
    events: List[Dict[str, Any]] = []
    t_ms = 0
    events.append({"type": "intro", "at": t_ms})
    t_ms += BEAT["intro"]
    if not rounds:
        events.append({"type": "finale", "at": t_ms, "winner": safe.get("winner") or safe.get("result") or "undecided"})
        return events
    for idx, rnd in enumerate(rounds):
        rnd = dict(rnd or {})
        n = max(1, int(rnd.get("number") or idx + 1))
        atk_loss = unit_count_total(rnd.get("attacker_losses"))
        def_loss = unit_count_total(rnd.get("defender_losses"))
        salvos = salvo_count_for_round(seed, n, atk_loss + def_loss)
        events.append({"type": "round_start", "at": t_ms, "round": n, "salvos": salvos})
        t_ms += BEAT["round_announce"]
        for s in range(salvos):
            events.append({"type": "salvo", "at": t_ms, "side": "attacker", "index": s, "salvos": salvos, "round": n})
            t_ms += BEAT["salvo_gap"]
        t_ms += BEAT["side_switch"]
        for s in range(salvos):
            events.append({"type": "salvo", "at": t_ms, "side": "defender", "index": s, "salvos": salvos, "round": n})
            t_ms += BEAT["salvo_gap"]
        events.append(
            {
                "type": "resolve",
                "at": t_ms,
                "round": n,
                "attacker_losses": dict(rnd.get("attacker_losses") or {}),
                "defender_losses": dict(rnd.get("defender_losses") or {}),
                "heavy": (atk_loss + def_loss) >= 40,
            }
        )
        t_ms += BEAT["resolve_hold"] + BEAT["round_gap"]
    events.append({"type": "finale", "at": t_ms, "winner": safe.get("winner") or safe.get("result") or "undecided"})
    return events
