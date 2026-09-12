from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _route_block(src: str, func: str) -> str:
    marker = f"def {func}():"
    block = src.split(marker, 1)[1]
    return block.split("\n@app.route(", 1)[0]


def test_world_boss_mutations_do_not_gate_on_generic_game_state():
    src = _read("app.py")
    for func in (
        "api_world_boss_attack",
        "api_world_boss_auto_attack",
        "api_world_boss_claim",
        "api_world_boss_catch",
        "api_world_boss_companion_mission",
    ):
        block = _route_block(src, func)
        assert "_build_game_state_payload" not in block, func
        assert '"state": state' not in block, func


def test_world_boss_frontend_accepts_fastlane_without_generic_state():
    src = _read("static/main.js")
    assert 'if (res && res.state && typeof GC.applyActionState === "function")' in src
    assert "hit_mult: hitMult" in src
    assert "if (hitMult !== 5) hitMult = 1" in src
    assert "/api/world-boss/attack" in src
    assert "/api/world-boss/auto-attack" in src


def test_world_boss_galaxy_cta_is_removed():
    template = _read("templates/world_boss.html")
    assert "world_boss_btn_galaxy" not in template
    assert "boss.galaxy_href" not in template
