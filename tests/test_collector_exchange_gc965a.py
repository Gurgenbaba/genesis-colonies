"""GC-965A — Collector Exchange foundations (catalog, schema, read-only state)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.collector_catalog import (
    COLLECTOR_OFFERS,
    COLLECTOR_SPECIALISTS,
    PRESTIGE_ONLY_ITEM_KEYS,
    assert_collector_catalog_valid,
    is_prestige_only_item,
    validate_collector_catalog,
)
from game.collector_exchange import (
    build_collector_exchange_payload,
    build_offer_state,
    collector_schema_ready,
    compute_can_redeem,
    compute_progress_pct,
    get_offer_state,
    get_inventory_owned_map,
)
from game.db import db, table_exists
from game.inventory import grant_inventory_item, inventory_schema_ready
from game.models import create_user, ensure_player_and_homeworld, init_db

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture
def collector_db(tmp_path, monkeypatch):
    db_path = tmp_path / "collector_exchange_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)

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
    init_db()
    yield db_path


def _run_migrate_twice(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(MIGRATE_SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr or result.stdout


def _create_user_id() -> int:
    conn = db()
    uname = f"col_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    conn.close()
    return uid


def test_collector_catalog_loads_and_validates():
    assert_collector_catalog_valid()
    assert validate_collector_catalog() == []
    assert len(COLLECTOR_OFFERS) >= 20
    assert len(COLLECTOR_SPECIALISTS) == 4


def test_collector_offer_keys_unique():
    keys = list(COLLECTOR_OFFERS.keys())
    assert len(keys) == len(set(keys))


def test_collector_specialist_keys_valid():
    for offer_key, offer in COLLECTOR_OFFERS.items():
        spec = str(offer.get("specialist_key") or "")
        assert spec in COLLECTOR_SPECIALISTS, f"{offer_key} has invalid specialist {spec!r}"


def test_prestige_only_items_not_used_as_inputs():
    for offer_key, offer in COLLECTOR_OFFERS.items():
        input_key = str(offer.get("input_key") or "")
        assert input_key not in PRESTIGE_ONLY_ITEM_KEYS, f"{offer_key} uses prestige-only input"
        assert not is_prestige_only_item(input_key)


def test_prestige_only_items_not_redeemable_via_can_redeem():
    for prestige_key in PRESTIGE_ONLY_ITEM_KEYS:
        assert compute_can_redeem(
            9999,
            input_amount=1,
            enabled=True,
            input_key=prestige_key,
        ) is False


def test_progress_pct_computed_server_side():
    assert compute_progress_pct(0, 50) == 0
    assert compute_progress_pct(18, 50) == 36
    assert compute_progress_pct(25, 50) == 50
    assert compute_progress_pct(49, 50) == 98
    assert compute_progress_pct(50, 50) == 100
    assert compute_progress_pct(999, 50) == 100


def test_can_redeem_respects_inventory_balance():
    offer = COLLECTOR_OFFERS["xeno_dna_common_research_booster"]
    assert compute_can_redeem(49, input_amount=50, enabled=True, input_key="fragment_dna_common") is False
    assert compute_can_redeem(50, input_amount=50, enabled=True, input_key="fragment_dna_common") is True
    assert compute_can_redeem(50, input_amount=50, enabled=False, input_key="fragment_dna_common") is False

    state_low = build_offer_state("xeno_dna_common_research_booster", offer, owned=18)
    assert state_low["owned"] == 18
    assert state_low["progress_pct"] == 36
    assert state_low["can_redeem"] is False

    state_ok = build_offer_state("xeno_dna_common_research_booster", offer, owned=50)
    assert state_ok["can_redeem"] is True
    assert state_ok["progress_pct"] == 100


def test_build_collector_exchange_payload_with_inventory(collector_db):
    uid = _create_user_id()
    conn = db()
    assert collector_schema_ready(conn)
    assert inventory_schema_ready(conn)

    grant_inventory_item(uid, "fragment_dna_common", 18, conn=conn)
    grant_inventory_item(uid, "fragment_wreck_hull", 20, conn=conn)
    conn.commit()

    payload = build_collector_exchange_payload(uid, conn=conn)
    conn.close()

    assert payload["ready"] is True
    assert len(payload["specialists"]) == 4

    xeno = next(s for s in payload["specialists"] if s["specialist_key"] == "xenobiologist")
    dna_offer = next(o for o in xeno["offers"] if o["offer_key"] == "xeno_dna_common_research_booster")
    assert dna_offer["owned"] == 18
    assert dna_offer["progress_pct"] == 36
    assert dna_offer["can_redeem"] is False
    assert dna_offer["reward_preview"][0]["reward_key"] == "booster_research_30m"

    scrap = next(s for s in payload["specialists"] if s["specialist_key"] == "scrapmaster")
    hull_offer = next(o for o in scrap["offers"] if o["offer_key"] == "scrap_hull_shipyard_15m")
    assert hull_offer["owned"] == 20
    assert hull_offer["can_redeem"] is True


def test_get_offer_state_and_owned_map(collector_db):
    uid = _create_user_id()
    conn = db()
    grant_inventory_item(uid, "fleet_hyperdrive_module", 4, conn=conn)
    conn.commit()

    owned_map = get_inventory_owned_map(uid, conn=conn)
    assert owned_map.get("fleet_hyperdrive_module") == 4

    state = get_offer_state(uid, "hyper_fleet_speed_25", conn=conn)
    assert state is not None
    assert state["owned"] == 4
    assert state["can_redeem"] is False
    assert state["input_amount"] == 5
    conn.close()


def test_migration_082_idempotent(collector_db):
    _run_migrate_twice(collector_db)
    conn = db()
    assert table_exists(conn, "collector_lifetime_stats")
    assert table_exists(conn, "collector_exchange_log")
    assert table_exists(conn, "collector_exchange_redemptions")
    conn.close()


def test_collector_schema_ready_false_before_migration(tmp_path, monkeypatch):
    db_path = tmp_path / "no_collector.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)
    init_db()

    conn = db()
    assert collector_schema_ready(conn) is False
    uid = _create_user_id()
    payload = build_collector_exchange_payload(uid, conn=conn)
    assert payload["ready"] is False
    assert payload["specialists"] == []
    conn.close()
