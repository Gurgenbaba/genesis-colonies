"""GC-912A — Imperial Directives economy/science progress tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import queue_build_for_planet
from game.db import db
from game.directives.balancing import directive_hard_cap
from game.directives.definitions import CADENCE_DAILY
from game.directives.generator import daily_expires_at, daily_period_key, ensure_player_directives
from game.directives.progress import apply_directive_events
from game.directives.service import get_imperial_directives_state
from game.models import (
    add_build_job,
    create_user,
    get_planet_buildings,
    get_planets_by_player,
)
from game.queue_engine import finish_planet_build_jobs
from game.research import queue_research

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def id_db(tmp_path, monkeypatch):
    db_file = tmp_path / "imperial_directives_progress.db"
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


def _create_player(conn) -> int:
    ok, _reason, user = create_user(f"id_prog_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    return int(user["id"])


def _set_daily_directives(conn, player_id: int, keys: list[str], *, fixed_now: float | None = None):
    ts = float(fixed_now if fixed_now is not None else time.time())
    conn.execute("DELETE FROM player_directives WHERE player_id = ?;", (int(player_id),))
    ensure_player_directives(player_id, conn=conn, now=ts)
    period_key = daily_period_key(ts)
    expires_at = int(daily_expires_at(ts))
    created_at = int(ts)

    rows = conn.execute(
        """
        SELECT id, cadence FROM player_directives
        WHERE player_id = ?
        ORDER BY cadence ASC, id ASC;
        """,
        (int(player_id),),
    ).fetchall()

    while len(rows) < len(keys):
        conn.execute(
            """
            INSERT INTO player_directives (
                player_id, cadence, period_key, definition_key, rarity,
                target_value, progress_value, status, expires_at, created_at
            ) VALUES (?, 'daily', ?, 'upgrade_buildings', 'common', 5, 0, 'active', ?, ?);
            """,
            (int(player_id), period_key, expires_at, created_at),
        )
        rows = conn.execute(
            """
            SELECT id, cadence FROM player_directives
            WHERE player_id = ?
            ORDER BY cadence ASC, id ASC;
            """,
            (int(player_id),),
        ).fetchall()

    for idx, key in enumerate(keys):
        if idx >= len(rows):
            break
        cadence = str(rows[idx]["cadence"] or CADENCE_DAILY)
        cap = directive_hard_cap(key, cadence=cadence)
        target_value = max(2, int(cap)) if cap and cap > 0 else 50
        conn.execute(
            """
            UPDATE player_directives
            SET definition_key = ?, target_value = ?, progress_value = 0, status = 'active'
            WHERE id = ?;
            """,
            (key, target_value, int(rows[idx]["id"])),
        )
    conn.commit()
    return ts


def test_build_finish_increments_upgrade_buildings(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        planets = get_planets_by_player(player_id, conn=conn)
        planet_id = int(planets[0]["id"])
        now = time.time()
        _set_daily_directives(conn, player_id, ["upgrade_buildings"], fixed_now=now)

        add_build_job(planet_id, "metal_mine", now - 30, now - 1, conn=conn)
        finished = finish_planet_build_jobs(conn, planet_id, player_id, now)
        conn.commit()
        assert finished == 1

        row = conn.execute(
            "SELECT progress_value, status FROM player_directives WHERE player_id = ? AND definition_key = ?;",
            (player_id, "upgrade_buildings"),
        ).fetchone()
        assert int(row["progress_value"]) == 1
        assert row["status"] == "active"
    finally:
        conn.close()


def test_build_finish_completes_directive(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        planets = get_planets_by_player(player_id, conn=conn)
        planet_id = int(planets[0]["id"])
        now = time.time()
        _set_daily_directives(conn, player_id, ["upgrade_buildings"], fixed_now=now)
        conn.execute(
            "UPDATE player_directives SET target_value = 1 WHERE player_id = ?;",
            (player_id,),
        )
        conn.commit()

        add_build_job(planet_id, "metal_mine", now - 30, now - 1, conn=conn)
        finish_planet_build_jobs(conn, planet_id, player_id, now)
        conn.commit()

        row = conn.execute(
            "SELECT progress_value, status FROM player_directives WHERE definition_key = ? AND player_id = ?;",
            ("upgrade_buildings", player_id),
        ).fetchone()
        assert int(row["progress_value"]) == 1
        assert row["status"] == "completed"
    finally:
        conn.close()


def test_progress_event_is_idempotent(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        now = time.time()
        _set_daily_directives(conn, player_id, ["upgrade_buildings"], fixed_now=now)
        event = {
            "kind": "build_complete",
            "building_type": "metal_mine",
            "amount": 1,
            "source_event_id": "build_finish:test:1",
        }
        first = apply_directive_events(player_id, [event], conn=conn, now=now)
        second = apply_directive_events(player_id, [event], conn=conn, now=now)
        conn.commit()
        assert int(first["updated"]) == 1
        assert int(second["updated"]) == 0
        row = conn.execute(
            "SELECT progress_value FROM player_directives WHERE player_id = ? AND definition_key = ?;",
            (player_id, "upgrade_buildings"),
        ).fetchone()
        assert int(row["progress_value"]) == 1
    finally:
        conn.close()


def test_filtered_storage_upgrade_only(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        now = time.time()
        _set_daily_directives(conn, player_id, ["upgrade_storages"], fixed_now=now)

        apply_directive_events(
            player_id,
            [
                {
                    "kind": "build_complete",
                    "building_type": "metal_mine",
                    "amount": 1,
                    "source_event_id": "build_finish:ignore:1",
                },
                {
                    "kind": "build_complete",
                    "building_type": "metal_storage",
                    "amount": 1,
                    "source_event_id": "build_finish:storage:1",
                },
            ],
            conn=conn,
            now=now,
        )
        conn.commit()

        row = conn.execute(
            "SELECT progress_value FROM player_directives WHERE player_id = ? AND definition_key = ?;",
            (player_id, "upgrade_storages"),
        ).fetchone()
        assert int(row["progress_value"]) == 1
    finally:
        conn.close()


def test_research_complete_updates_directive(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        now = time.time()
        _set_daily_directives(conn, player_id, ["complete_research"], fixed_now=now)

        from game.models import add_research_job
        from game.queue_engine import finish_player_research_jobs

        add_research_job(
            player_id,
            "energy_tech",
            now - 120,
            now - 1,
            conn=conn,
        )
        finished = finish_player_research_jobs(conn, player_id, now)
        conn.commit()
        assert finished == 1

        row = conn.execute(
            "SELECT progress_value, status FROM player_directives WHERE player_id = ? AND definition_key = ?;",
            (player_id, "complete_research"),
        ).fetchone()
        assert int(row["progress_value"]) == 1
    finally:
        conn.close()


def test_queue_build_and_research_emit_progress(id_db, monkeypatch):
    conn = db()
    try:
        player_id = _create_player(conn)
        planets = get_planets_by_player(player_id, conn=conn)
        planet = dict(planets[0])
        planet_id = int(planet["id"])

        now = time.time()
        _set_daily_directives(conn, player_id, ["spend_resources", "start_research"], fixed_now=now)

        conn.execute(
            "UPDATE planets SET metal = 5000000, crystal = 5000000 WHERE id = ?;",
            (planet_id,),
        )
        conn.execute(
            """
            UPDATE planet_buildings SET research_lab = 1, metal_mine = 1, crystal_mine = 1
            WHERE planet_id = ?;
            """,
            (planet_id,),
        )
        conn.commit()

        buildings = get_planet_buildings(planet_id, conn=conn)
        ok, reason, _payload = queue_build_for_planet(
            planet,
            buildings,
            "metal_mine",
            user_id=player_id,
        )
        assert ok, reason

        conn2 = db()
        try:
            state = get_imperial_directives_state(player_id, conn=conn2, now=now)
            spend_row = next(
                d for d in state["directives"] if d["definition_key"] == "spend_resources"
            )
            assert spend_row["progress"] > 0
        finally:
            conn2.close()

        player = {"id": player_id}
        ok_r, reason_r, _payload_r = queue_research(player, "energy_tech", user_id=player_id)
        assert ok_r, reason_r

        conn3 = db()
        try:
            state2 = get_imperial_directives_state(player_id, conn=conn3, now=now)
            start_row = next(
                d for d in state2["directives"] if d["definition_key"] == "start_research"
            )
            assert start_row["progress"] >= 1
        finally:
            conn3.close()
    finally:
        conn.close()


def test_fleet_build_and_combat_events_update_directives(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        now = time.time()
        keys = [
            "send_fleet_missions",
            "build_ships",
            "build_combat_ships",
            "win_battles",
        ]
        _set_daily_directives(conn, player_id, keys, fixed_now=now)

        from game.combat import WINNER_ATTACKER
        from game.directives.progress import (
            emit_combat_directive_events,
            emit_fleet_mission_sent,
            emit_ship_built_events,
        )

        emit_fleet_mission_sent(
            player_id,
            mission="transport",
            fleet_id=101,
            conn=conn,
            now=now,
        )
        emit_ship_built_events(
            player_id,
            ship_key="spark_drone",
            amount=2,
            job_id=55,
            delivered_before=10,
            conn=conn,
            now=now,
        )
        emit_ship_built_events(
            player_id,
            ship_key="falcon_interceptor",
            amount=1,
            job_id=56,
            delivered_before=5,
            conn=conn,
            now=now,
        )
        emit_combat_directive_events(
            player_id,
            movement_id=202,
            winner=WINNER_ATTACKER,
            defender_losses={"spark_drone": 3, "sentinel_turret": 2},
            conn=conn,
            now=now,
        )
        conn.commit()

        progress = {
            row["definition_key"]: int(row["progress_value"])
            for row in conn.execute(
                """
                SELECT definition_key, progress_value FROM player_directives
                WHERE player_id = ? AND definition_key IN ({});
                """.format(",".join("?" * len(keys))),
                (player_id, *keys),
            ).fetchall()
        }
        assert progress["send_fleet_missions"] == 1
        assert progress["build_ships"] == 3
        assert progress["build_combat_ships"] == 1
        assert progress["win_battles"] == 1
    finally:
        conn.close()


def test_defense_and_expedition_events_update_directives(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        now = time.time()
        keys = ["destroy_enemy_ships", "build_defense", "complete_expeditions"]
        _set_daily_directives(conn, player_id, keys, fixed_now=now)

        from game.directives.progress import (
            emit_combat_directive_events,
            emit_defense_built_events,
            emit_expedition_complete_event,
        )
        from game.combat import WINNER_ATTACKER

        emit_combat_directive_events(
            player_id,
            movement_id=203,
            winner=WINNER_ATTACKER,
            defender_losses={"spark_drone": 3},
            conn=conn,
            now=now,
        )
        emit_defense_built_events(
            player_id,
            defense_key="sentinel_turret",
            amount=4,
            job_id=77,
            delivered_before=6,
            conn=conn,
            now=now,
        )
        emit_expedition_complete_event(
            player_id,
            movement_id=303,
            outcome={"event_key": "debris_field", "severity": "normal"},
            conn=conn,
            now=now,
        )
        conn.commit()

        progress = {
            row["definition_key"]: int(row["progress_value"])
            for row in conn.execute(
                """
                SELECT definition_key, progress_value FROM player_directives
                WHERE player_id = ? AND definition_key IN ({});
                """.format(",".join("?" * len(keys))),
                (player_id, *keys),
            ).fetchall()
        }
        assert progress["destroy_enemy_ships"] == 3
        assert progress["build_defense"] == 4
        assert progress["complete_expeditions"] == 1
    finally:
        conn.close()
