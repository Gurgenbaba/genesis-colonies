"""World Boss large-hangar and player-feedback hotfix regression checks."""
from pathlib import Path

from game import combat, world_boss


def test_world_boss_auto_pick_8000_aegis_without_simulate_battle(monkeypatch):
    def fail_if_battle_called(*args, **kwargs):
        raise AssertionError("World Boss instant picker must not simulate full battles")

    monkeypatch.setattr(combat, "simulate_battle", fail_if_battle_called)
    defender = {"falcon_interceptor": 200}
    hangar = {"ironclad_frigate": 8000, "mule_courier": 50}
    selected, meta = world_boss.select_world_boss_auto_attack_ships(
        hangar,
        defender_ships=defender,
        max_hp=5_000_000,
        event_id=42,
    )
    expected_full = world_boss.compute_instant_hp_damage(
        ships={"ironclad_frigate": 8000},
        defender_ships=defender,
        max_hp=5_000_000,
    )
    assert expected_full > 0
    assert meta["damage_full"] == expected_full
    assert 0 < selected.get("ironclad_frigate", 0) <= 8000
    assert "mule_courier" not in selected
    assert meta["damage_estimate"] == world_boss.compute_instant_hp_damage(
        ships=selected, defender_ships=defender, max_hp=5_000_000
    )


def test_world_boss_failure_feedback_is_persistent_and_bound():
    src = Path("static/main.js").read_text(encoding="utf-8")
    assert "const wbShowAttackFeedback =" in src
    attack = src.split("const wbPostInstantAttack = async", 1)[1].split(
        "// GC-WB-ATTACK-002 / COMBAT-FX-003", 1
    )[0]
    assert 'wbShowAttackFeedback(card, errorMessage, "error")' in attack
    assert 'wbShowAttackFeedback(card, "", "success")' in attack
    assert 'wbShowAttackFeedback(card, t("wb_attack", "Attack") + "…", "pending")' in attack
    assert 'root.querySelectorAll("[data-wb-instant-attack]")' in src
