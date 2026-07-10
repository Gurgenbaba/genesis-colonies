"""
GC-SCORE-F — trader rates aligned with canonical resource_score.

Run: python -m pytest tests/test_gc_score_f_exchange.py -v
"""

from __future__ import annotations

import pytest

from game.exchange import (
    _EXCHANGE_SETTING_DEFAULTS,
    exchange_trade_score_delta,
    execute_exchange,
    get_exchange_config,
    score_neutral_exchange_reference,
    trade_would_increase_score,
    validate_score_neutral_exchange_config,
    validate_score_neutral_metal_crystal_buy,
)
from game.models import db, ensure_player_and_homeworld, create_user, get_planets_by_player
from game.resource_score import score_neutral_exchange_rates


@pytest.fixture
def exchange_db(tmp_path, monkeypatch):
    db_path = tmp_path / "score_f_exchange.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    from game import db as gdb

    gdb._DB_PATH = None
    from game.models import init_db

    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def test_exchange_defaults_match_score_neutral_reference():
    ref = score_neutral_exchange_reference()
    assert ref["ferronite_cost_per_crytite_buy"] == pytest.approx(1.5)
    assert ref["fuel_metal_per_unit"] == pytest.approx(3.0)
    assert ref["fuel_crystal_per_unit"] == pytest.approx(2.0)
    assert float(_EXCHANGE_SETTING_DEFAULTS["exchange_rate_metal_to_crystal"]) == pytest.approx(
        ref["ferronite_cost_per_crytite_buy"]
    )
    assert float(_EXCHANGE_SETTING_DEFAULTS["fuel_exchange_metal_per_unit"]) == pytest.approx(
        ref["fuel_metal_per_unit"]
    )
    assert float(_EXCHANGE_SETTING_DEFAULTS["fuel_exchange_crystal_per_unit"]) == pytest.approx(
        ref["fuel_crystal_per_unit"]
    )


def test_validate_score_neutral_rejects_legacy_rates():
    ok, err = validate_score_neutral_metal_crystal_buy(2.0)
    assert ok is False
    assert err == "exchange_score_neutral_buy_mismatch"


def test_get_exchange_config_reports_score_neutral(exchange_db):
    cfg = get_exchange_config()
    assert cfg["score_neutral"] is True
    assert cfg["score_neutral_block_reason"] == ""
    assert validate_score_neutral_exchange_config(cfg)[0] is True


def test_score_neutral_metal_to_crystal_trade_preserves_score():
    delta = exchange_trade_score_delta(
        metal=10_000,
        crystal=0,
        fuel_cells=0,
        give_resource="metal",
        give_amount=1500,
        receive_resource="crystal",
        receive_amount=1000,
    )
    assert delta == 0
    assert trade_would_increase_score(
        metal=10_000,
        crystal=0,
        fuel_cells=0,
        give_resource="metal",
        give_amount=1500,
        receive_resource="crystal",
        receive_amount=1000,
    ) is False


def test_cheap_buy_rate_would_increase_score():
    assert trade_would_increase_score(
        metal=10_000,
        crystal=0,
        fuel_cells=0,
        give_resource="metal",
        give_amount=1000,
        receive_resource="crystal",
        receive_amount=1000,
    ) is True


def test_execute_blocks_score_exploit_with_misconfigured_buy_rate(exchange_db, monkeypatch):
    conn = db()
    ok, _, user = create_user("score_f_exploit", "test-pass-123")
    assert ok
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Trader", conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    conn.execute("UPDATE planets SET metal = 10000, crystal = 0 WHERE id = ?;", (pid,))
    conn.commit()

    def _cheap_buy_cfg(conn=None):
        base = get_exchange_config(conn=conn)
        base = dict(base)
        base["rate_metal_to_crystal"] = 1.0
        base["rate_crystal_to_metal"] = 0.5
        base["ferronite_cost_per_crytite_buy"] = 1.0
        base["ferronite_return_per_crytite_sell"] = 0.5
        base["score_neutral"] = False
        return base

    monkeypatch.setattr("game.exchange.get_exchange_config", _cheap_buy_cfg)

    ok_trade, reason, _ = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="metal",
        to_resource="crystal",
        amount=1000,
        conn=conn,
    )
    assert not ok_trade
    assert reason == "exchange_score_exploit"
    conn.close()


def test_reference_matches_resource_score_helper():
    ref = score_neutral_exchange_reference()
    rates = score_neutral_exchange_rates()
    assert ref["ferronite_cost_per_crytite_buy"] == rates["metal_per_crystal"]
    assert ref["fuel_metal_per_unit"] == rates["metal_per_fuel_cell"]
    assert ref["fuel_crystal_per_unit"] == rates["crystal_per_fuel_cell"]
