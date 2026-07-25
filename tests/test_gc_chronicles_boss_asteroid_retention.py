"""Chronicles boss/asteroid archive, full stats, inbox retention."""

from __future__ import annotations

import time
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.chronicle_entries import (
    ENTRY_TYPE_ASTEROID,
    ENTRY_TYPE_WORLD_BOSS,
    record_chronicle_for_fleet_report,
)
from game.chronicles import (
    CHRONICLES_SECTION_ASTEROIDS,
    CHRONICLES_SECTION_PVP,
    CHRONICLES_SECTION_WORLD_BOSS,
    build_chronicles_api_payload,
    build_pvp_stats,
    build_world_boss_stats,
)
from game.combat import build_combat_report
from game.combat_models import CombatResult, CombatRound
from game.db import db
from game.messages import (
    INBOX_RETENTION_DAYS,
    dispatch_combat_reports,
    normalize_combat_metadata,
    purge_expired_inbox_messages,
)
from game.models import create_user


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "chron_boss_ret.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    import migrate

    migrate.ensure_db_exists()
    migrate.main()
    yield
    dbmod._DB_PATH = None


def _create_player(prefix: str) -> tuple[int, str]:
    uname = f"{prefix}_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    return int(user["id"]), uname


def test_world_boss_combat_goes_to_boss_chronicle_not_pvp(temp_db):
    attacker_id, _ = _create_player("wb_atk")
    combat_result = CombatResult(
        winner="attacker",
        rounds=(CombatRound(1, {}, {"sentinel_turret": 1}),),
        attacker_losses={},
        defender_losses={"sentinel_turret": 1},
    )
    body, meta = build_combat_report(
        attacker_id=attacker_id,
        attacker_name="Attacker",
        defender_id=0,
        defender_name="Void Leviathan",
        coords="1:2:3",
        attacking_ships={"falcon_interceptor": 5},
        defending_ships={"sentinel_turret": 2},
        defending_defense={},
        combat_result=combat_result,
    )
    meta = normalize_combat_metadata(meta)
    meta["combat_kind"] = "world_boss"
    meta["fleet_id"] = 9001
    meta["world_boss_damage"] = 12500
    sent = dispatch_combat_reports(
        attacker_id=attacker_id,
        defender_id=0,
        coords="1:2:3",
        body=body,
        metadata=meta,
    )
    assert sent["attacker"]["ok"]

    conn = db()
    try:
        row = conn.execute(
            "SELECT entry_type, score_value FROM chronicle_entries WHERE player_id = ?;",
            (attacker_id,),
        ).fetchone()
        assert row is not None
        assert str(row["entry_type"]) == ENTRY_TYPE_WORLD_BOSS
        assert int(row["score_value"]) == 12500

        pvp = build_chronicles_api_payload(
            player_id=attacker_id,
            section=CHRONICLES_SECTION_PVP,
            tab="overview",
            conn=conn,
        )
        assert int(pvp["pvp"]["stats"]["total_battles"]) == 0

        boss = build_chronicles_api_payload(
            player_id=attacker_id,
            section=CHRONICLES_SECTION_WORLD_BOSS,
            tab="recent",
            conn=conn,
        )
        assert int(boss["world_boss"]["stats"]["total_hits"]) == 1
        assert int(boss["world_boss"]["stats"]["damage_total"]) == 12500
        assert len(boss["world_boss"]["hits"]) == 1
    finally:
        conn.close()


def test_asteroid_chronicle_entry_and_section(temp_db):
    pid, _ = _create_player("ast")
    conn = db()
    try:
        ok = record_chronicle_for_fleet_report(
            player_id=pid,
            entry_type=ENTRY_TYPE_ASTEROID,
            subject="Asteroid 1:2:8",
            metadata={
                "fleet_id": 42,
                "target_coords": "1:2:8",
                "asteroid_harvested": True,
                "collected": {"metal": 5000, "crystal": 2500, "fuel_cells": 0},
            },
            occurred_at=int(time.time()),
            conn=conn,
        )
        assert ok
        conn.commit()

        payload = build_chronicles_api_payload(
            player_id=pid,
            section=CHRONICLES_SECTION_ASTEROIDS,
            tab="recent",
            conn=conn,
        )
        assert int(payload["asteroids"]["stats"]["total_runs"]) == 1
        assert int(payload["asteroids"]["stats"]["loot_total"]) == 7500
        assert payload["asteroids"]["runs"][0]["status"] == "harvested"
    finally:
        conn.close()


def test_pvp_stats_uncapped_beyond_500(temp_db):
    attacker_id, _ = _create_player("cap_atk")
    defender_id, _ = _create_player("cap_def")
    conn = db()
    try:
        now = int(time.time())
        for i in range(520):
            meta = {
                "perspective": "attacker",
                "attacker_id": attacker_id,
                "defender_id": defender_id,
                "attacker_name": "A",
                "defender_name": "D",
                "result": "attacker",
                "fleet_id": 10000 + i,
                "attacker_losses": {},
                "defender_losses": {"falcon_interceptor": 1},
                "loot": {},
                "debris": {},
            }
            record_chronicle_for_fleet_report(
                player_id=attacker_id,
                entry_type="combat",
                subject=f"Battle {i}",
                metadata=meta,
                occurred_at=now - i,
                conn=conn,
            )
        conn.commit()
        stats = build_pvp_stats(attacker_id, conn=conn)
        assert int(stats["total_battles"]) == 520
    finally:
        conn.close()


def test_inbox_retention_keeps_player_mail_and_chronicles(temp_db):
    a_id, _a_name = _create_player("ret_a")
    b_id, b_name = _create_player("ret_b")
    now = int(time.time())
    old = now - ((INBOX_RETENTION_DAYS + 1) * 86400)

    conn = db()
    try:
        for cat, subject in (
            ("expedition", "Old expo"),
            ("combat", "Old combat"),
            ("system", "Old system"),
        ):
            conn.execute(
                """
                INSERT INTO player_messages (
                    recipient_player_id, sender_player_id, sender_name,
                    category, subject, body, is_read, is_archived,
                    metadata_json, created_at
                ) VALUES (?, NULL, 'System', ?, ?, 'body', 0, 0, '{}', ?);
                """,
                (a_id, cat, subject, old),
            )
        conn.execute(
            """
            INSERT INTO player_messages (
                recipient_player_id, sender_player_id, sender_name,
                category, subject, body, is_read, is_archived,
                metadata_json, created_at
            ) VALUES (?, ?, ?, 'player', 'Keep me', 'hello', 0, 0, '{}', ?);
            """,
            (a_id, b_id, b_name, old),
        )
        record_chronicle_for_fleet_report(
            player_id=a_id,
            entry_type="expedition",
            subject="Expo chron",
            metadata={"fleet_id": 77, "rewards": {"metal": 10}},
            occurred_at=old,
            conn=conn,
        )
        conn.commit()

        purged = purge_expired_inbox_messages(now=now, conn=conn)
        conn.commit()
        assert purged >= 3

        rows = conn.execute(
            """
            SELECT category, deleted_at FROM player_messages
            WHERE recipient_player_id = ?
            ORDER BY category;
            """,
            (a_id,),
        ).fetchall()
        by_cat = {str(r["category"]): r["deleted_at"] for r in rows}
        assert by_cat.get("player") in (None, 0)
        assert by_cat["expedition"] and int(by_cat["expedition"]) > 0
        assert by_cat["combat"] and int(by_cat["combat"]) > 0
        assert by_cat["system"] and int(by_cat["system"]) > 0

        chron = conn.execute(
            "SELECT COUNT(*) AS c FROM chronicle_entries WHERE player_id = ?;",
            (a_id,),
        ).fetchone()
        assert int(chron["c"]) >= 1
    finally:
        conn.close()


def test_static_chronicles_sections_include_boss_asteroid():
    from pathlib import Path

    html = Path("templates/chronicles.html").read_text(encoding="utf-8")
    assert 'data-chronicles-section="world_boss"' in html
    assert 'data-chronicles-section="asteroids"' in html
    src = Path("game/chronicles.py").read_text(encoding="utf-8")
    assert "PVP_STATS_SCAN_LIMIT" not in src
    assert "EXPEDITION_STATS_SCAN_LIMIT" not in src
    assert "CHRONICLES_SECTION_WORLD_BOSS" in src
