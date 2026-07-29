"""GC-594 — World Map activity feed in Command Center."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, ensure_player_and_homeworld, init_db, save_planet_buildings
from game.planet_evolution.command_center import build_colony_command_center

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"

GC594_LOCALE_KEYS = (
    "command_center_section_activity",
    "command_center_feed_empty",
    "command_center_feed_build_active",
    "command_center_feed_research_active",
    "command_center_feed_shipyard_active",
    "command_center_feed_fleet_active",
    "command_center_feed_combat_report",
    "command_center_feed_expedition_report",
)


@pytest.fixture()
def gc594_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc594.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
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
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def _player(conn):
    ok, err, user = create_user(f"gc594_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    conn.commit()
    return uid


def test_gc594_locale_keys_present():
    for path in ("locales/en.json", "locales/de.json"):
        data = json.loads((ROOT / path).read_text(encoding="utf-8"))
        for key in GC594_LOCALE_KEYS:
            assert key in data, f"missing {key} in {path}"


def test_gc594_template_and_js_contract():
    tpl = (ROOT / "templates" / "partials" / "galaxy_command_map_panel.html").read_text(encoding="utf-8")
    # world_inspector_modal was extracted into its own included partial
    # (game/templates/partials/world_inspector_modal.html); check both files
    # combined (GC-STABILIZE-002).
    modal_tpl = (ROOT / "templates" / "partials" / "world_inspector_modal.html").read_text(encoding="utf-8")
    tpl_combined = tpl + "\n" + modal_tpl
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "gc-world-inspector-modal" in tpl_combined
    assert "data-world-inspector-content" in tpl_combined
    assert "renderActivityFeed" in js
    assert "activity_feed" in js
    assert "command_center_section_activity" in js or "command_center_feed_" in js
    assert ".gc-command-center-activity-feed" in css
    assert ".gc-command-center-activity-link" in css


def test_activity_feed_payload_shape(gc594_db):
    from game.db import db
    from game.models import get_homeworld

    conn = db()
    try:
        player_id = _player(conn)
        hw = get_homeworld(player_id, conn=conn)
        planet_id = int(hw["id"])
        cc = build_colony_command_center(
            planet_id,
            player_id,
            conn=conn,
            role_key="homeworld",
            is_homeworld=True,
        )
    finally:
        conn.close()

    feed = cc.get("activity_feed")
    assert isinstance(feed, list)
    assert len(feed) <= 5
    for row in feed:
        assert row.get("kind")
        assert row.get("label_key")
        assert row.get("href")
        assert row.get("icon")


def test_build_queue_appears_in_activity_feed(gc594_db):
    from game.db import db
    from game.models import get_homeworld

    conn = db()
    try:
        player_id = _player(conn)
        hw = get_homeworld(player_id, conn=conn)
        planet_id = int(hw["id"])
        save_planet_buildings(planet_id, {"metal_mine": 1})
        now = time.time()
        conn.execute(
            """
            INSERT INTO build_queue (planet_id, building_type, start_time, finish_time)
            VALUES (?, 'metal_mine', ?, ?);
            """,
            (planet_id, now, now + 600.0),
        )
        conn.commit()
        cc = build_colony_command_center(
            planet_id,
            player_id,
            conn=conn,
            role_key="homeworld",
            is_homeworld=True,
        )
        kinds = {row.get("kind") for row in cc.get("activity_feed") or []}
    finally:
        conn.close()

    assert "build" in kinds
    build_row = next(row for row in cc["activity_feed"] if row["kind"] == "build")
    assert build_row.get("countdown_at")
    assert build_row.get("href") == "/buildings"


def test_activity_feed_empty_when_idle(gc594_db):
    from game.db import db
    from game.models import get_homeworld

    conn = db()
    cc = {}
    try:
        player_id = _player(conn)
        hw = get_homeworld(player_id, conn=conn)
        planet_id = int(hw["id"])
        conn.execute("DELETE FROM player_messages WHERE recipient_player_id = ?;", (player_id,))
        conn.commit()
        cc = build_colony_command_center(
            planet_id,
            player_id,
            conn=conn,
            role_key="homeworld",
            is_homeworld=True,
        )
    finally:
        conn.close()

    assert cc.get("activity_feed") == []
