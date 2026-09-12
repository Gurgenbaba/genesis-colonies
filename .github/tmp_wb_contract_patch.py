from pathlib import Path

p = Path('tests/test_world_boss.py')
s = p.read_text(encoding='utf-8')
old = '''def test_world_boss_attack_response_uses_slim_post_mutation_state():
    """GC-PERF-WB-ACTION-001: instant strike must not rebuild full panel state."""
    src = Path("app.py").read_text(encoding="utf-8")
    block = src.split('def api_world_boss_attack():', 1)[1].split(
        '@app.route("/api/world-boss/auto-attack"', 1
    )[0]
    assert "include_panel=False" in block
    assert "action_slim=True" in block
    assert 'post_mutation_committed=bool(result.get("ok"))' in block
    assert "include_panel=True" not in block
    assert '"state": state' in block
'''
new = '''def test_world_boss_attack_response_uses_action_fastlane():
    """GC-PERF-WB-HOT-012: instant strike returns mutation payload without generic state rebuild."""
    src = Path("app.py").read_text(encoding="utf-8")
    block = src.split('def api_world_boss_attack():', 1)[1].split(
        '@app.route("/api/world-boss/auto-attack"', 1
    )[0]
    assert "_build_game_state_payload" not in block
    assert "include_panel=True" not in block
    assert '"state": state' not in block
'''
if s.count(old) != 1:
    raise SystemExit(f'expected one legacy static contract, got {s.count(old)}')
s = s.replace(old, new, 1)
old_body = '    assert "state" in body\n'
if s.count(old_body) < 1:
    raise SystemExit('legacy API state assertion missing')
s = s.replace(old_body, '    assert "state" not in body\n', 1)
p.write_text(s, encoding='utf-8')
