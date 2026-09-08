"""GC-PERF-GALAXY-AST-029 — Galaxy asteroid bootstrap stays read-mostly."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_block(path: str, name: str) -> str:
    src = (ROOT / path).read_text(encoding="utf-8")
    start = src.index(f"def {name}(")
    end = src.index("\ndef ", start + 5)
    return src[start:end]


def test_galaxy_bootstrap_does_not_physically_expire_asteroids():
    ensure = _function_block("game/asteroids.py", "ensure_asteroids_present")
    active = _function_block("game/asteroids.py", "list_active_asteroids")
    worker = _function_block("game/asteroids.py", "tick_asteroid_schedule")

    assert "expire_due_asteroids(" not in ensure
    assert "expires_at > ?" in active
    assert "expire_due_asteroids(conn=conn" in worker


def test_galaxy_route_commits_asteroid_bootstrap_only_when_spawned():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    block = src.split("def galaxy_view():", 1)[1].split(
        '@app.route("/api/galaxy/system")',
        1,
    )[0]
    asteroid = block.split("from game.asteroids import ensure_asteroids_present", 1)[1].split(
        "system_data = list_system(",
        1,
    )[0]

    assert "asteroid_bootstrap = ensure_asteroids_present(conn=conn)" in asteroid
    assert 'if asteroid_bootstrap.get("spawned"):' in asteroid
    conditional = asteroid.split('if asteroid_bootstrap.get("spawned"):', 1)[1]
    assert "db_commit(conn)" in conditional
    assert asteroid.index('if asteroid_bootstrap.get("spawned"):') < asteroid.index("db_commit(conn)")


def test_asteroid_worker_remains_physical_expiry_owner():
    src = (ROOT / "game" / "fleet_worker.py").read_text(encoding="utf-8")
    block = src.split("def _asteroids() -> None:", 1)[1].split(
        "def _pirates() -> None:",
        1,
    )[0]
    assert "maybe_tick_asteroid_schedule(conn=conn)" in block
