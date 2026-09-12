from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _route_block(src: str, marker: str, next_marker: str) -> str:
    return src.split(marker, 1)[1].split(next_marker, 1)[0]


def _assert_post_mutation_slim(block: str) -> None:
    assert "include_panel=False" in block
    assert "action_slim=True" in block
    assert 'post_mutation_committed=bool(result.get("ok"))' in block
    assert "include_panel=True" not in block
    assert 'panel_page="overview"' not in block


def test_world_boss_auto_attack_uses_post_mutation_slim_state():
    src = _read("app.py")
    block = _route_block(src, "def api_world_boss_auto_attack():", "def api_world_boss_claim():")
    _assert_post_mutation_slim(block)


def test_world_boss_claim_uses_post_mutation_slim_state():
    src = _read("app.py")
    block = _route_block(src, "def api_world_boss_claim():", "def api_world_boss_catch():")
    _assert_post_mutation_slim(block)


def test_world_boss_catch_uses_post_mutation_slim_state():
    src = _read("app.py")
    block = _route_block(
        src,
        "def api_world_boss_catch():",
        "def api_world_boss_companion_mission():",
    )
    _assert_post_mutation_slim(block)


def test_world_boss_companion_mission_uses_post_mutation_slim_state():
    src = _read("app.py")
    block = _route_block(
        src,
        "def api_world_boss_companion_mission():",
        "def api_admin_world_boss():",
    )
    _assert_post_mutation_slim(block)


def test_sidebar_release_nav_never_localizes_500_liveops_rows():
    src = _read("game/universe_news.py")
    block = src.split("def sidebar_release_nav(", 1)[1]
    assert "list_news(" not in block
    assert "SELECT version_tag, is_major_release" in block
    assert "world_boss:%" in block
    assert "pirate%" in block
    assert "LIMIT 500" in block
