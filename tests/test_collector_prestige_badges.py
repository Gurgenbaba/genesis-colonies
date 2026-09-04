"""GC-969 — Collector lifetime prestige badges + inventory hints."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.collector_catalog import PRESTIGE_ONLY_ITEM_KEYS, is_prestige_only_item
from game.collector_exchange import record_lifetime_acquired
from game.db import begin_write_transaction, commit, db
from game.inventory_classification import classify_inventory_item
from game.inventory_use import _use_fail_reason, use_inventory_item
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.playercard import (
    _list_unlocked_badges,
    _sync_badge_unlocks,
    ensure_player_card_tables,
)
from game.planet_evolution.repository import get_context_planet

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture
def prestige_db(tmp_path, monkeypatch):
    db_path = tmp_path / "collector_prestige_test.db"
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
    ensure_player_card_tables()
    yield db_path


def _create_player(name: str | None = None) -> int:
    uname = name or f"cp_{uuid.uuid4().hex[:8]}"
    conn = db()
    try:
        ok, err, user = create_user(uname, "test-pass-123")
        assert ok, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, conn=conn)
        return uid
    finally:
        conn.close()


def test_orphan_collectibles_are_prestige_only():
    assert "expo_alien_relic" in PRESTIGE_ONLY_ITEM_KEYS
    assert "placeholder_special_item" in PRESTIGE_ONLY_ITEM_KEYS
    assert is_prestige_only_item("expo_alien_relic")
    assert is_prestige_only_item("placeholder_special_item")
    assert is_prestige_only_item("mythic_genesis_core")


def test_prestige_and_ark_token_inventory_hints():
    genesis = classify_inventory_item("mythic_genesis_core")
    assert genesis["prestige_only"] is True
    assert genesis["use_hint_key"] == "inv_hint_collector_prestige"

    relic = classify_inventory_item("expo_alien_relic")
    assert relic["prestige_only"] is True
    assert relic["use_hint_key"] == "inv_hint_collector_prestige"

    ark = classify_inventory_item("story_scrap_token")
    assert ark["use_hint_key"] == "inv_hint_free_shop"


def test_research_instant_fail_reason_is_no_research_queue():
    assert _use_fail_reason("research_instant_level") == "no_research_queue"


def test_research_instant_use_without_queue(prestige_db):
    uid = _create_player()
    conn = db()
    try:
        begin_write_transaction(conn)
        from game.inventory import grant_inventory_item

        assert grant_inventory_item(uid, "research_instant_level", 1, conn=conn)
        planet = get_context_planet(uid, conn=conn)
        ok, reason, _payload = use_inventory_item(
            uid,
            int(planet["id"]),
            "research_instant_level",
            1,
            conn=conn,
        )
        commit(conn)
        assert ok is False
        assert reason == "no_research_queue"
    finally:
        conn.close()


def test_collector_lifetime_badge_unlocks_at_threshold(prestige_db):
    uid = _create_player()
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_card_tables(conn)
        record_lifetime_acquired(uid, "fragment_genesis", 24, conn=conn)
        _sync_badge_unlocks(uid, conn=conn)
        unlocked = {b["badge_key"] for b in _list_unlocked_badges(uid, conn=conn)}
        assert "genesis_curator" not in unlocked

        record_lifetime_acquired(uid, "fragment_genesis", 1, conn=conn)
        _sync_badge_unlocks(uid, conn=conn)
        unlocked = {b["badge_key"] for b in _list_unlocked_badges(uid, conn=conn)}
        assert "genesis_curator" in unlocked
        commit(conn)
    finally:
        conn.close()


def test_alien_relic_badge_unlocks(prestige_db):
    uid = _create_player()
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_card_tables(conn)
        record_lifetime_acquired(uid, "expo_alien_relic", 15, conn=conn)
        _sync_badge_unlocks(uid, conn=conn)
        unlocked = {b["badge_key"] for b in _list_unlocked_badges(uid, conn=conn)}
        assert "alien_relic_archivist" in unlocked
        commit(conn)
    finally:
        conn.close()


def test_prestige_unlock_grants_one_time_reward(prestige_db):
    from game.inventory import grant_inventory_item, inventory_amount
    from game.inventory_use import enrich_inventory_item_row

    uid = _create_player()
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_card_tables(conn)
        # Grant exactly to threshold via inventory path (sync + reward).
        assert grant_inventory_item(uid, "fragment_genesis", 25, conn=conn)
        unlocked = {b["badge_key"] for b in _list_unlocked_badges(uid, conn=conn)}
        assert "genesis_curator" in unlocked
        assert inventory_amount(uid, "container_void_artifact", conn=conn) == 1

        # Second sync / extra grants must not duplicate unlock loot.
        assert grant_inventory_item(uid, "fragment_genesis", 5, conn=conn)
        _sync_badge_unlocks(uid, conn=conn)
        assert inventory_amount(uid, "container_void_artifact", conn=conn) == 1

        row = enrich_inventory_item_row(
            {"item_key": "fragment_genesis", "amount": 30},
            user_id=uid,
            conn=conn,
        )
        assert row["prestige_progress"]["unlocked"] is True
        assert row["prestige_progress"]["owned"] >= 25
        assert row["prestige_progress"]["reward_key"] == "container_void_artifact"
        commit(conn)
    finally:
        conn.close()


def test_prestige_progress_before_threshold(prestige_db):
    from game.inventory import grant_inventory_item
    from game.inventory_use import enrich_inventory_item_row

    uid = _create_player()
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_card_tables(conn)
        assert grant_inventory_item(uid, "fragment_quantum", 2, conn=conn)
        row = enrich_inventory_item_row(
            {"item_key": "fragment_quantum", "amount": 2},
            user_id=uid,
            conn=conn,
        )
        pp = row["prestige_progress"]
        assert pp["unlocked"] is False
        assert pp["owned"] == 2
        assert pp["required"] == 5
        assert pp["reward_key"] == "booster_research_24h"
        commit(conn)
    finally:
        conn.close()


def test_badge_sync_bulk_reads_unlock_state_once(prestige_db):
    """GC-PERF-PLAYERCARD-003: self-card sync must not SELECT unlock state per badge."""
    uid = _create_player()
    conn = db()
    statements: list[str] = []
    try:
        begin_write_transaction(conn)
        ensure_player_card_tables(conn)
        # Make ordinary score badges eligible so the legacy implementation would
        # execute its per-badge existence SELECT repeatedly.
        conn.execute(
            """
            UPDATE player_scores
            SET score_total = ?, score_buildings = ?, score_research = ?,
                score_fleet = ?, score_defense = ?, score_planet_evolution = ?
            WHERE player_id = ?;
            """,
            (10**12, 10**12, 10**12, 10**12, 10**12, 10**12, uid),
        )
        conn.set_trace_callback(statements.append)
        _sync_badge_unlocks(uid, conn=conn)
        conn.set_trace_callback(None)
        commit(conn)

        normalized = [" ".join(str(sql).upper().split()) for sql in statements]
        per_badge_reads = [
            sql
            for sql in normalized
            if sql.startswith("SELECT 1 FROM PLAYER_CARD_UNLOCKED_BADGES")
        ]
        assert per_badge_reads == []
        assert any(
            "LEFT JOIN PLAYER_CARD_UNLOCKED_BADGES" in sql
            and "ALREADY_UNLOCKED" in sql
            for sql in normalized
        )
    finally:
        try:
            conn.set_trace_callback(None)
        except Exception:
            pass
        conn.close()
