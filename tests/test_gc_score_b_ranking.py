"""
GC-SCORE-B — ranking integration with canonical resource_score.

Run: python -m pytest tests/test_gc_score_b_ranking.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import DEFAULT_GAME_SETTINGS, create_user, init_db
from game.ranking import _sanitize_scores, compute_player_scores, refresh_player_score
from game.resource_score import score_from_resources
from game.scoring import compute_destroyed_raw_from_losses, record_combat_outcome

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc_score_b.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _close_db() -> None:
    try:
        db().close()
    except Exception:
        pass


def _create_player(username: str) -> int:
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    _close_db()
    return int(user["id"])


@pytest.fixture(autouse=True)
def _db_ready(temp_db):
    _close_db()
    init_db()
    _close_db()
    _run_migrate(temp_db)
    yield
    _close_db()


def _starter_resource_score() -> int:
    return score_from_resources(
        int(DEFAULT_GAME_SETTINGS["start_metal"]),
        int(DEFAULT_GAME_SETTINGS["start_crystal"]),
        int(DEFAULT_GAME_SETTINGS["start_fuel_cells"]),
    )


def test_sanitize_total_excludes_destroyed_includes_resources():
    clean = _sanitize_scores(
        {
            "resource_score": 100,
            "building_score": 1000,
            "research_score": 500,
            "fleet_score": 200,
            "defense_score": 50,
            "destroyed_score": 999,
            "evolution_score": 25,
        }
    )
    assert clean["total_score"] == 100 + 1000 + 500 + 200 + 50 + 25
    assert clean["destroyed_score"] == 999
    assert clean["military_score"] == clean["combat_score"] + 999


def test_new_player_scores_include_starter_storage():
    pid = _create_player("starter_storage")
    scores = compute_player_scores(pid)
    expected_resources = _starter_resource_score()
    assert scores["resource_score"] == expected_resources
    assert scores["total_score"] == expected_resources
    assert scores["building_score"] == 0
    assert scores["fleet_score"] == 0


def test_compute_player_scores_fleet_uses_resource_score():
    pid = _create_player("fleet_owner")
    conn = db()
    planet = conn.execute(
        "SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
        (pid,),
    ).fetchone()
    assert planet
    conn.execute(
        """
        INSERT INTO planet_ships (player_id, planet_id, ship_key, amount, created_at, updated_at)
        VALUES (?, ?, 'mule_courier', 10, CAST(strftime('%s','now') AS INTEGER), CAST(strftime('%s','now') AS INTEGER))
        ON CONFLICT DO NOTHING;
        """,
        (pid, int(planet["id"])),
    )
    conn.commit()
    conn.close()
    _close_db()

    scores = compute_player_scores(pid)
    # mule_courier: 2500/2500/0 -> 1 + 2 = 3 points per hull
    assert scores["fleet_score"] == 30
    assert scores["total_score"] == _starter_resource_score() + 30


def test_destroyed_prestige_not_in_total_score():
    attacker = _create_player("combat_atk")
    defender = _create_player("combat_def")
    conn = db()
    try:
        record_combat_outcome(
            attacker_id=attacker,
            defender_id=defender,
            attacker_losses={},
            defender_losses={"plasma_arc": 4},
            conn=conn,
        )
        conn.commit()
        prestige = compute_destroyed_raw_from_losses({"plasma_arc": 4})
        assert prestige == 8

        scores = refresh_player_score(attacker, conn=conn)
        conn.commit()
        assert scores["destroyed_score"] == prestige
        assert scores["destroyed_score"] > 0
        assert scores["destroyed_score"] not in (
            scores["total_score"],
            scores["total_score"] - scores["resource_score"],
        )
        assert scores["total_score"] == scores["resource_score"]
    finally:
        conn.close()
    _close_db()
