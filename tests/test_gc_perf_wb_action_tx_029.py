from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _route_block(src: str, func: str) -> str:
    marker = f"def {func}():"
    block = src.split(marker, 1)[1]
    return block.split("\n@app.route(", 1)[0]


def test_wb_attack_route_requests_action_scoped_response():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    block = _route_block(src, "api_world_boss_attack")
    assert "action_response=True" in block
    assert '"recognition"' not in block
    assert '"event"' not in block


def test_action_response_skips_discarded_reads_but_preserves_default_contract():
    src = (ROOT / "game" / "world_boss.py").read_text(encoding="utf-8")
    signature = src.split("def execute_instant_attack(", 1)[1].split(") -> Dict[str, Any]:", 1)[0]
    assert "action_response: bool = False" in signature

    block = src.split("def execute_instant_attack(", 1)[1].split(
        "\ndef compute_world_boss_hp_damage(", 1
    )[0]
    assert "if updated is None and not action_response:" in block
    assert "if not action_response:" in block
    assert '"recognition": build_world_boss_recognition' in block
    assert '"hangar_unchanged": hangar_after == hangar' in block

    # Core interactive fields are built outside the optional extras block.
    extras = block.split("if not action_response:", 2)[-1]
    core = block.split("if not action_response:", 2)[0]
    assert '"attack": {' in core
    assert '"boss": {' in core
    assert '"player": {' in core
    assert '"recognition": build_world_boss_recognition' in extras
