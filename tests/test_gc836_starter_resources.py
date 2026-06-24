"""GC-836 — Alpha starter resources & first-hour progression."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import game.db as dbmod  # noqa: E402
import game.models as models  # noqa: E402
from game.models import DEFAULT_GAME_SETTINGS, create_user, db, get_homeworld, init_db  # noqa: E402
import fresh_account_progression_sim as sim  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc836.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def test_default_start_resources_gc836():
    assert int(float(DEFAULT_GAME_SETTINGS["start_metal"])) == 150_000
    assert int(float(DEFAULT_GAME_SETTINGS["start_crystal"])) == 100_000
    assert int(float(DEFAULT_GAME_SETTINGS["start_fuel_cells"])) == 25_000


def test_fresh_account_sim_first_hour_gc836_acceptance():
    _, cps = sim.run_simulation(sim.PRESETS["alpha_current"], horizon_sec=3600)
    h1 = cps["1h"]

    assert h1["metal_mine"] >= 6
    assert h1["crystal_mine"] >= 6
    assert h1["solar_plant"] >= 5
    assert h1["research_lab"] >= 1
    assert h1["build_completions"] >= 8
    assert h1["build_completions"] <= 40


def test_fresh_account_sim_24h_not_stalled():
    _, cps = sim.run_simulation(sim.PRESETS["alpha_current"], horizon_sec=86400)
    d1 = cps["24h"]

    assert d1["metal_mine"] >= 10
    assert d1["research_completions"] >= 1
    assert d1["build_completions"] > 20
    assert d1["build_completions"] > cps["1h"]["build_completions"]


def test_homeworld_gets_configured_start_resources(temp_db):
    init_db()
    try:
        db().close()
    except Exception:
        pass

    uname = f"gc836_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    try:
        db().close()
    except Exception:
        pass

    planet = get_homeworld(player_id=int(user["id"]))
    assert int(planet["metal"]) == 150_000
    assert int(planet["crystal"]) == 100_000
    assert int(planet["fuel_cells"]) == 25_000
