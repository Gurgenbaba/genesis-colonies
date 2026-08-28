"""
GC-622 — Integer overflow audit for game-relevant numeric fields.

Verifies that values well above signed 32-bit INT_MAX (2_147_483_647) round-trip
correctly through SQLite, Python int, ranking, exchange, and fleet cargo paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from game import db as gdb
from game.db import db
from game.exchange import (
    _preview_receive,
    execute_exchange,
    get_exchange_config,
    resolve_exchange_daily_limit,
)
from game.fleet_calc import calculate_loaded_resources, validate_departure_balances
from game.models import (
    create_user,
    ensure_player_and_homeworld,
    get_homeworld,
    get_planets_by_player,
    init_db,
    save_planet,
    try_spend_resources_conn,
)
from game.number_format import fmt_int, parse_int_number
from game.ranking import get_player_score_row, upsert_player_scores

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"

# Ticket thresholds (German Mrd. = 10^9, Bio. = 10^12).
RESOURCE_LEVELS = (
    2_000_000_000,
    5_000_000_000,
    50_000_000_000,
    1_000_000_000_000,
)

INT32_MAX = 2_147_483_647


@pytest.fixture()
def gc622_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gc622_overflow.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
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
    yield
    gdb._DB_PATH = None


def _player(conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"gc622_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _column_type(table: str, column: str) -> str:
    conn = db()
    try:
        rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
        for row in rows:
            if row["name"] == column:
                return str(row["type"]).upper()
        raise AssertionError(f"{table}.{column} not found")
    finally:
        conn.close()


class TestGC622SchemaTypes:
    """SQLite column types for audited fields."""

    def test_planet_resources_use_real_not_int32(self, gc622_db):
        # REAL (IEEE-754) — not 32-bit capped; precision limit ~9e15, not 2.1e9.
        assert _column_type("planets", "metal") == "REAL"
        assert _column_type("planets", "crystal") == "REAL"
        assert _column_type("planets", "fuel_cells") == "REAL"

    def test_planet_energy_uses_integer(self, gc622_db):
        assert _column_type("planets", "energy_total") == "INTEGER"
        assert _column_type("planets", "energy_used") == "INTEGER"

    def test_player_scores_use_decimal_text(self, gc622_db):
        for col in (
            "score_total",
            "score_resources",
            "score_buildings",
            "score_research",
            "score_fleet",
            "score_defense",
            "score_planet_evolution",
            "score_destroyed_raw",
            "score_combat",
            "score_destroyed",
        ):
            assert _column_type("player_scores", col) == "TEXT"

    def test_exchange_log_amounts_use_real(self, gc622_db):
        assert _column_type("exchange_log", "give_amount") == "REAL"
        assert _column_type("exchange_log", "receive_amount") == "REAL"

    def test_fleet_and_defense_amounts_use_integer(self, gc622_db):
        assert _column_type("planet_ships", "amount") == "INTEGER"
        assert _column_type("planet_defense", "amount") == "INTEGER"


class TestGC622ResourceRoundTrip:
    """planets.metal/crystal/fuel_cells save + reload above INT32_MAX."""

    @pytest.mark.parametrize("amount", RESOURCE_LEVELS)
    def test_resource_persist_and_reload(self, gc622_db, amount):
        conn = db()
        uid = _player(conn=conn)
        planet = get_homeworld(player_id=uid, conn=conn)
        pid = int(planet["id"])
        planet = dict(planet)
        planet["metal"] = amount
        planet["crystal"] = amount // 2
        planet["fuel_cells"] = amount // 4
        save_planet(planet, conn=conn)
        conn.commit()

        row = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        conn.close()

        assert int(row["metal"]) == amount
        assert int(row["crystal"]) == amount // 2
        assert int(row["fuel_cells"]) == amount // 4

    @pytest.mark.parametrize("amount", RESOURCE_LEVELS)
    def test_atomic_spend_above_int32_max(self, gc622_db, amount):
        conn = db()
        uid = _player(conn=conn)
        planet = get_homeworld(player_id=uid, conn=conn)
        pid = int(planet["id"])
        spend = min(1_000_000_000, amount // 10)
        conn.execute(
            "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
            (float(amount), float(amount), pid),
        )
        conn.commit()

        from game.db import begin_write_transaction

        begin_write_transaction(conn)
        ok = try_spend_resources_conn(conn, pid, spend, spend)
        conn.commit()

        row = conn.execute(
            "SELECT metal, crystal FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        conn.close()

        assert ok is True
        assert int(row["metal"]) == amount - spend
        assert int(row["crystal"]) == amount - spend


class TestGC622Ranking:
    """player_scores above INT32_MAX."""

    @pytest.mark.parametrize("building_score", (2_000_000_000, 50_000_000_000, 1_000_000_000_000))
    def test_ranking_upsert_and_read(self, gc622_db, building_score):
        uid = _player()
        research_score = building_score // 2
        upsert_player_scores(
            uid,
            {
                "total_score": building_score + research_score,
                "building_score": building_score,
                "research_score": research_score,
            },
        )
        row = get_player_score_row(uid)
        assert int(row["score_buildings"]) == building_score
        assert int(row["score_research"]) == research_score
        assert int(row["score_total"]) == building_score + research_score

    def test_ranking_above_int32_max_not_clamped_to_int32(self, gc622_db):
        uid = _player()
        target = INT32_MAX + 1
        upsert_player_scores(
            uid,
            {"total_score": target, "building_score": target, "research_score": 0},
        )
        row = get_player_score_row(uid)
        assert int(row["score_buildings"]) == target

    def test_ranking_above_int64_roundtrips_as_decimal_text(self, gc622_db):
        uid = _player()
        target = 10**50 + 987654321
        upsert_player_scores(uid, {"building_score": target, "research_score": 7})
        row = get_player_score_row(uid)
        assert row["score_buildings"] == str(target)
        assert row["score_total"] == str(target + 7)


class TestGC622Exchange:
    """Trader daily limit (unbounded pct-of-production scaling) and large trades."""

    def test_daily_limit_scales_past_int32_max_without_admin_cap(self, gc622_db, monkeypatch):
        # GC-731D deliberately removed the fixed admin ceiling (previously 50
        # Mrd.) so late-game empire production scales the daily limit without
        # an artificial cutoff; see tests/test_exchange.py::
        # test_exchange_daily_limit_ignores_legacy_admin_cap and
        # test_exchange_daily_limit_scales_to_82_billion for the canonical
        # coverage (GC-STABILIZE-002). The GC-622 concern — large values must
        # round-trip past INT32_MAX without overflow/clamping — still holds,
        # just without a hardcoded cap.
        cfg = get_exchange_config()
        assert "daily_limit_admin" not in cfg
        assert "daily_limit_max" not in cfg

        conn = db()
        uid = _player(conn=conn)
        conn.execute(
            "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('exchange_daily_limit_min', '0');"
        )
        conn.commit()
        total_per_day = 100_000_000_000  # 100 Mrd/day — well above INT32_MAX
        monkeypatch.setattr(
            "game.empire_page.get_empire_production_aggregate",
            lambda *_a, **_k: {
                "metal_per_day": total_per_day,
                "crystal_per_day": 0,
                "fuel_cells_per_day": 0,
                "total_per_day": total_per_day,
            },
        )
        block = resolve_exchange_daily_limit(uid, conn=conn)
        conn.close()
        expected = int(total_per_day * float(cfg["daily_limit_pct"]) / 100.0)
        assert expected > INT32_MAX
        assert block["daily_limit"] == expected

    def test_exchange_trade_with_5_billion_balance(self, gc622_db):
        """Large planet balance + trade within daily limit (25M floor for new empires)."""
        conn = db()
        uid = _player(conn=conn)
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        balance = 5_000_000_000
        trade_amount = 20_000_000  # under default 25M daily floor
        conn.execute(
            "UPDATE planets SET metal = ?, crystal = 0, fuel_cells = 0 WHERE id = ?;",
            (float(balance), pid),
        )
        conn.execute(
            "UPDATE players SET exchange_daily_used = 0, exchange_daily_reset_at = 0 WHERE id = ?;",
            (uid,),
        )
        conn.commit()

        ok, reason, result = execute_exchange(
            player_id=uid,
            planet_id=pid,
            from_resource="metal",
            to_resource="crystal",
            amount=trade_amount,
            conn=conn,
        )
        assert ok, reason
        assert int(result["give_amount"]) == trade_amount

        row = conn.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,)).fetchone()
        conn.close()
        assert int(row["metal"]) == balance - trade_amount
        # Score-neutral exchange (GC-SCORE-F) uses rate_metal_to_crystal=1.5,
        # not the old flat 0.85; derive expectation from the canonical preview
        # helper instead of a hardcoded rate (GC-STABILIZE-002).
        cfg = get_exchange_config()
        expected_crystal = _preview_receive("metal", "crystal", trade_amount, cfg)
        assert int(row["crystal"]) == expected_crystal


class TestGC622FleetCargo:
    """Fleet resource JSON amounts above INT32_MAX."""

    def test_fleet_cargo_load_and_balance_2_billion(self, gc622_db):
        cargo_amount = 2_000_000_000
        loaded = calculate_loaded_resources({"metal": cargo_amount, "crystal": 0, "fuel_cells": 0})
        assert loaded["metal"] == cargo_amount

        ok, reason = validate_departure_balances(
            metal_have=float(cargo_amount + 1_000_000),
            crystal_have=0.0,
            fuel_cells_have=0.0,
            resources=loaded,
            fuel_cost=0,
        )
        assert ok, reason


class TestGC622Serialization:
    """JSON + display formatting for audited magnitudes."""

    @pytest.mark.parametrize("amount", RESOURCE_LEVELS)
    def test_json_roundtrip_python(self, amount):
        payload = json.loads(json.dumps({"metal": amount, "score": amount}))
        assert payload["metal"] == amount
        assert payload["score"] == amount

    @pytest.mark.parametrize("amount", RESOURCE_LEVELS)
    def test_number_format_roundtrip(self, amount):
        assert parse_int_number(fmt_int(amount)) == amount

    def test_no_int32_ceiling_in_gameplay_path(self, gc622_db):
        """Values one above INT32_MAX must not silently wrap or clamp."""
        conn = db()
        uid = _player(conn=conn)
        pid = int(get_homeworld(player_id=uid, conn=conn)["id"])
        over = INT32_MAX + 50_000_000
        conn.execute("UPDATE planets SET metal = ? WHERE id = ?;", (float(over), pid))
        conn.commit()
        row = conn.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()
        conn.close()
        assert int(row["metal"]) == over
        assert int(row["metal"]) > INT32_MAX


# GC-INT64-RESOURCE-BIND-001 — Python sqlite3 binds Python int as SQLite
# INTEGER before column affinity is considered. Resource columns are REAL, so
# balances above signed INT64 must be bound as float rather than clamped.
def test_resource_save_above_sqlite_int64_binds_as_real(gc622_db):
    amount = 10**20  # safely above SQLite signed INT64 max (~9.22e18)
    conn = db()
    uid = _player(conn=conn)
    planet = dict(get_homeworld(player_id=uid, conn=conn))
    pid = int(planet["id"])

    # Reproduce the failing late-game shape: gameplay math can turn a REAL
    # balance into a Python int before save_planet writes the row back.
    planet["metal"] = amount
    planet["crystal"] = amount // 2
    planet["fuel_cells"] = amount // 4

    save_planet(planet, conn=conn)
    conn.commit()
    row = conn.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
        (pid,),
    ).fetchone()
    conn.close()

    assert float(row["metal"]) == pytest.approx(float(amount))
    assert float(row["crystal"]) == pytest.approx(float(amount // 2))
    assert float(row["fuel_cells"]) == pytest.approx(float(amount // 4))
