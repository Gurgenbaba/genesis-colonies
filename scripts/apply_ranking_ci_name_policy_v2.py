from pathlib import Path

path = Path("tests/test_ranking.py")
src = path.read_text(encoding="utf-8")
old = '        pid = _create_player(f"join_{i}")\n'
new = '        pid = _create_player(f"rankingrow_{i}")\n'
assert old in src, "ranking join-query test anchor missing"
src = src.replace(old, new, 1)
path.write_text(src, encoding="utf-8")
