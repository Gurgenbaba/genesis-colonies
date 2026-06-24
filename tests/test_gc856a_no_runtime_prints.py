"""
GC-856A — no print() in hot-path game runtime modules.

Run: python -m pytest tests/test_gc856a_no_runtime_prints.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Startup/CLI modules may still print to stderr.
ALLOWED_PRINT_FILES = {
    "game/bootstrap.py",
    "game/config.py",
    "game/tick_runner.py",
}


def _iter_game_py_files():
    game_dir = ROOT / "game"
    for path in sorted(game_dir.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED_PRINT_FILES:
            continue
        yield rel, path


def _has_print_call(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(getattr(node.func, "id", None), str):
            if node.func.id == "print":
                lines.append(int(node.lineno))
    return lines


def test_gc856a_no_print_in_hot_path_game_modules():
    offenders: list[str] = []
    for rel, path in _iter_game_py_files():
        hits = _has_print_call(path)
        if hits:
            offenders.append(f"{rel}: lines {hits}")
    assert not offenders, "print() in runtime game modules:\n" + "\n".join(offenders)


def test_gc856a_app_has_no_hot_path_prints():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'print("[TopG]' not in src
