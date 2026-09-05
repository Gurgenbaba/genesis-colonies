"""Unbounded runtime arithmetic contract for pirate systems."""

from __future__ import annotations

from pathlib import Path

from game.exact_math import scale_int
from game.pirates.bases import (
    MAX_WAVE_HP_FRACTION,
    _row_to_base,
    _scale_stacks,
    compute_base_hp_damage,
)
from game.pirates.brain import _raid_fleet_from_hangar, _score_opportunity

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**400


def test_pirate_opportunity_handles_10_pow_400_values():
    balanced = _score_opportunity(
        metal=HUGE,
        crystal=0,
        fuel=0,
        fleet_score=HUGE,
        defense_score=HUGE,
        offline_hours=0.0,
        threat=50,
        turtle=0.0,
    )
    assert 0 <= balanced <= 100

    irresistible = _score_opportunity(
        metal=HUGE,
        crystal=HUGE,
        fuel=HUGE,
        fleet_score=0,
        defense_score=0,
        offline_hours=48.0,
        threat=80,
        bounty_credits=10_000,
        turtle=1.0,
    )
    assert irresistible == 100


def test_pirate_raid_fleet_slicing_is_exact_for_huge_hangars(monkeypatch):
    import game.fleet as fleet_module

    monkeypatch.setattr(
        fleet_module,
        "get_planet_ships",
        lambda planet_id, conn=None: {
            "spark_drone": HUGE,
            "veil_probe": HUGE,
        },
    )

    fleet = _raid_fleet_from_hangar(
        object(),
        planet_id=7,
        fraction=0.5,
        reserve_fraction=0.25,
    )

    # veil_probe is a protected reserve key. Of the combat stack, 25% stays
    # home and the raid receives half of the remaining 75%.
    assert fleet == {"spark_drone": (HUGE * 3) // 8}


def test_pirate_base_display_ratio_handles_huge_hp():
    row = {
        "id": 9,
        "faction_key": "crimson_corsairs",
        "status": "active",
        "galaxy": 1,
        "system": 2,
        "position": 3,
        "strength": 5,
        "activity": 80,
        "loot_tier": "high",
        "fleet_stacks_json": "{}",
        "max_hp": HUGE,
        "current_hp": HUGE // 4,
        "spawned_at": 1.0,
        "escalates_at": None,
        "destroyed_at": None,
        "expires_at": 2.0,
        "updated_at": 1.0,
    }
    base = _row_to_base(row)
    assert base["max_hp"] == HUGE
    assert base["current_hp"] == HUGE // 4
    assert base["hp_ratio"] == 0.25


def test_pirate_base_stack_scaling_handles_huge_amounts():
    scaled = _scale_stacks({"spark_drone": HUGE}, 3)
    assert scaled["spark_drone"] == HUGE * 2


def test_pirate_base_hp_damage_handles_10_pow_400():
    damage = compute_base_hp_damage(
        defender_ships_before={"spark_drone": HUGE},
        defender_losses={"spark_drone": HUGE // 2},
        max_hp=HUGE,
        attacker_ships_before={"spark_drone": HUGE * 2},
    )
    assert damage > 0
    assert damage <= scale_int(HUGE, MAX_WAVE_HP_FRACTION)


def test_pirate_runtime_sources_have_no_unbounded_float_roundtrips():
    brain = (ROOT / "game" / "pirates" / "brain.py").read_text(encoding="utf-8")
    bases = (ROOT / "game" / "pirates" / "bases.py").read_text(encoding="utf-8")
    threat = (ROOT / "game" / "pirates" / "threat.py").read_text(encoding="utf-8")

    for forbidden in (
        "float(loot) / float(risk)",
        "round(total * keep_ratio)",
        "round(available * float(fraction))",
    ):
        assert forbidden not in brain

    for forbidden in (
        "float(current_hp) / float(max_hp)",
        'float(row["current_hp"] or 0) / float(old_max)',
        "float(lost_score) / float(full_score)",
        "float(attacker_score) / float(max(full_score, 1))",
        "float(hp_budget) * float(WAVE_HP_FRACTION)",
        'float(row["damage"] or 0) / float(total_dmg)',
    ):
        assert forbidden not in bases

    assert 'boss_dmg = float(' not in threat
    assert "boss_dmg = max(0, int(" in threat
