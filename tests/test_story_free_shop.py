"""EPIC-25 — Ark-Token Free Shop redeem."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import begin_write_transaction, commit, db
from game.inventory import grant_inventory_item, inventory_amount
from game.inventory_catalog import is_known_item_key
from game.models import create_user
from game.story.free_shop import (
    ARK_TOKEN_KEY,
    FREE_SHOP_OFFERS,
    ark_token_balance,
    redeem_free_shop_offer,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def free_shop_db(tmp_path, monkeypatch):
    db_file = tmp_path / "story_free_shop.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    yield db_file


def _pid() -> int:
    ok, _r, user = create_user(f"free_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    return int(user["id"])


def test_ark_token_is_catalogued():
    assert is_known_item_key(ARK_TOKEN_KEY)
    assert ARK_TOKEN_KEY == "story_scrap_token"


def test_free_shop_redeem_spends_and_grants(free_shop_db):
    conn = db()
    try:
        pid = _pid()
        begin_write_transaction(conn)
        assert grant_inventory_item(pid, ARK_TOKEN_KEY, 20, conn=conn)
        res = redeem_free_shop_offer(pid, offer_id="free_build_5m", conn=conn)
        assert res["ok"]
        assert ark_token_balance(pid, conn=conn) == 12
        assert inventory_amount(pid, "booster_build_5m", conn=conn) == 1
        commit(conn)
    finally:
        conn.close()


def test_free_shop_redeem_insufficient(free_shop_db):
    conn = db()
    try:
        pid = _pid()
        begin_write_transaction(conn)
        grant_inventory_item(pid, ARK_TOKEN_KEY, 2, conn=conn)
        res = redeem_free_shop_offer(pid, offer_id="free_tk_45m", conn=conn)
        assert not res["ok"]
        assert res["error"] == "insufficient_tokens"
        assert ark_token_balance(pid, conn=conn) == 2
        commit(conn)
    finally:
        conn.close()


def test_free_shop_catalog_below_eur_tier():
    assert "free_shipyard_15m" in FREE_SHOP_OFFERS
    assert "free_container_wreckage" in FREE_SHOP_OFFERS
    assert FREE_SHOP_OFFERS["free_container_wreckage"]["cost"] >= 10
    for offer_id, spec in FREE_SHOP_OFFERS.items():
        assert not str(offer_id).startswith("scrap_")
        if spec.get("kind") == "inventory":
            assert is_known_item_key(str(spec["item_key"])), offer_id
        assert "title_key" in spec and "hint_key" in spec
