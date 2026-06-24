"""
GC-822 — live economy audit tests (synthetic profiles + DB integration).

Run: python -m pytest tests/test_gc822_live_economy_audit.py -v
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
from game.buildings import get_upgrade_cost
from game.db import db
from game.economy_balance import BENCHMARK_LEVELS, cumulative_upgrade_cost_sum
from game.economy_live_audit import (
    FLAG_ENERGY_STARVED,
    FLAG_STORAGE_NEAR_FULL,
    audit_player,
    migration_recommendations,
    player_audit_to_dict,
    synthetic_profile_audit,
)
from game.models import create_user, get_homeworld, init_db, save_planet_buildings
from game.ranking import compute_player_scores

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc822_audit.db"
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


def _create_player() -> int:
    uname = f"gc822_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    try:
        db().close()
    except Exception:
        pass
    return int(user["id"])


@pytest.fixture(autouse=True)
def _db_setup(temp_db):
    try:
        db().close()
    except Exception:
        pass
    init_db()
    try:
        db().close()
    except Exception:
        pass
    _run_migrate(temp_db)
    init_db()
    yield
    try:
        db().close()
    except Exception:
        pass


class TestSyntheticProfiles:
    @pytest.mark.parametrize("level", BENCHMARK_LEVELS)
    def test_benchmark_mine_production_positive(self, level):
        prof = synthetic_profile_audit(
            {"metal_mine": level, "crystal_mine": max(1, level - 2), "solar_plant": level},
            planet_position=9,
        )
        assert prof["production_per_hour"]["metal"] > 0

    def test_earlygame_upgrade_affordable(self):
        prof = synthetic_profile_audit({"metal_mine": 5, "solar_plant": 3}, planet_position=9)
        hours = prof["next_metal_upgrade_hours"]
        assert hours is not None
        assert hours < 24.0

    def test_endgame_not_legacy_exponential(self):
        """GC-821 next upgrade must be far below old exponential cost burden."""
        level = 90
        new_cost, _ = get_upgrade_cost("metal_mine", level)
        from game.buildings import BASE_COST, COST_FACTOR

        base = BASE_COST["metal_mine"]
        old_cost = int(base[0] * (COST_FACTOR["metal_mine"] ** level))
        assert new_cost < old_cost / 100


class TestPlayerAudit:
    def test_audit_early_player(self):
        pid = _create_player()
        planet = get_homeworld(player_id=pid)
        save_planet_buildings(
            int(planet["id"]),
            {"metal_mine": 8, "crystal_mine": 5, "solar_plant": 6},
        )
        conn = db()
        try:
            audit = audit_player(pid, conn=conn)
            payload = player_audit_to_dict(audit)
            assert payload["colony_count"] >= 1
            assert payload["empire_production_per_hour"]["metal"] > 0
            assert migration_recommendations(audit)
        finally:
            conn.close()

    def test_audit_storage_near_full_flag(self):
        pid = _create_player()
        planet = get_homeworld(player_id=pid)
        save_planet_buildings(int(planet["id"]), {"metal_mine": 10, "metal_storage": 1, "solar_plant": 8})
        conn = db()
        try:
            conn.execute(
                "UPDATE planets SET metal = 140000 WHERE id = ?;",
                (int(planet["id"]),),
            )
            conn.commit()
            audit = audit_player(pid, conn=conn)
            assert FLAG_STORAGE_NEAR_FULL in audit.flags or FLAG_STORAGE_OVERFLOW in audit.flags
        finally:
            conn.close()

    def test_ranking_uses_gc821_cumulative_costs(self):
        pid = _create_player()
        planet = get_homeworld(player_id=pid)
        save_planet_buildings(int(planet["id"]), {"metal_mine": 20, "crystal_mine": 15})
        conn = db()
        try:
            scores = compute_player_scores(pid, conn=conn)
            expected = cumulative_upgrade_cost_sum("metal_mine", 20) + cumulative_upgrade_cost_sum(
                "crystal_mine", 15
            )
            assert scores["building_score"] == expected
        finally:
            conn.close()
