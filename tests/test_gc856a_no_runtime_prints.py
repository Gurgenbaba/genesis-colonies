"""
GC-856A — no print() in hot-path game runtime modules.

Run: python -m pytest tests/test_gc856a_no_runtime_prints.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Startup/CLI/background-worker modules may still print — they run outside the
# per-request hot path and gunicorn is launched without a logging.basicConfig,
# so plain logger.info() calls have no visible handler; print(flush=True) is
# the only way their status reaches Railway's captured stdout (GC-STABILIZE-002:
# fleet_worker/internal_cron/ranking_worker all follow the same worker-log +
# CLI-entrypoint pattern as the already-allowed tick_runner.py).
ALLOWED_PRINT_FILES = {
    "game/bootstrap.py",
    "game/config.py",
    "game/tick_runner.py",
    "game/fleet_worker.py",
    "game/internal_cron.py",
    "game/ranking_worker.py",
}

# Individual guarded, off-by-default diagnostic prints inside otherwise
# hot-path modules — narrower than a file-level allowlist so the rest of the
# file stays fully covered (GC-STABILIZE-002).
ALLOWED_PRINT_LINES: dict[str, set[int]] = {
    # _pg_init_progress: Postgres cold-start progress reporter, only emits
    # when GC_PG_INIT_PROGRESS is explicitly set — off by default.
    "game/models.py": {194},
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
        allowed_lines = ALLOWED_PRINT_LINES.get(rel, set())
        hits = [line for line in _has_print_call(path) if line not in allowed_lines]
        if hits:
            offenders.append(f"{rel}: lines {hits}")
    assert not offenders, "print() in runtime game modules:\n" + "\n".join(offenders)


def test_gc856a_app_has_no_hot_path_prints():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'print("[TopG]' not in src
