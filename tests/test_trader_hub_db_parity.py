"""UNI1 Trader Hub DB parity regression.

Production UNI1 carried historical game_settings (0.8/0.8 and 20/14) even
though the migration ledger was current. The parity migration must overwrite
those values and runtime must fail safe if DB drift ever reappears.
"""

from __future__ import annotations

import pytest

from game.exchange import get_exchange_config
from game.models import db, init_db


@pytest.fixture
def trader_parity_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trader_parity.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    from game import db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def test_parity_migration_pins_current_dev_trader_values(trader_parity_db):
    conn = db()
    keys = (
        "exchange_enabled",
        "exchange_rate_metal_to_crystal",
        "exchange_rate_crystal_to_metal",
        "exchange_daily_limit",
        "exchange_daily_limit_pct",
        "exchange_daily_limit_min",
        "exchange_daily_limit_max",
        "exchange_min_amount",
        "fuel_exchange_enabled",
        "fuel_exchange_metal_per_unit",
        "fuel_exchange_crystal_per_unit",
        "fuel_exchange_min_units",
    )
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"SELECT key, value FROM game_settings WHERE key IN ({placeholders})",
        keys,
    ).fetchall()
    values = {str(row["key"]): str(row["value"]) for row in rows}
    conn.close()

    assert values == {
        "exchange_enabled": "1",
        "exchange_rate_metal_to_crystal": "1.5",
        "exchange_rate_crystal_to_metal": "1",
        "exchange_daily_limit": "50000000000",
        "exchange_daily_limit_pct": "80",
        "exchange_daily_limit_min": "25000000",
        "exchange_daily_limit_max": "50000000000",
        "exchange_min_amount": "100",
        "fuel_exchange_enabled": "1",
        "fuel_exchange_metal_per_unit": "3",
        "fuel_exchange_crystal_per_unit": "2",
        "fuel_exchange_min_units": "10",
    }


def test_runtime_fails_safe_if_historical_rates_reappear(trader_parity_db):
    conn = db()
    stale = {
        "exchange_rate_metal_to_crystal": "0.8",
        "exchange_rate_crystal_to_metal": "0.8",
        "fuel_exchange_metal_per_unit": "20",
        "fuel_exchange_crystal_per_unit": "14",
    }
    for key, value in stale.items():
        conn.execute("UPDATE game_settings SET value = ? WHERE key = ?", (value, key))
    conn.commit()

    cfg = get_exchange_config(conn=conn)
    conn.close()

    assert cfg["rate_metal_to_crystal"] == 1.5
    assert cfg["rate_crystal_to_metal"] == 1.0
    assert cfg["fuel_metal_per_unit"] == 3.0
    assert cfg["fuel_crystal_per_unit"] == 2.0
    assert cfg["rates_corrected"] is True
    assert cfg["fuel_rates_corrected"] is True
    assert cfg["score_neutral"] is True
