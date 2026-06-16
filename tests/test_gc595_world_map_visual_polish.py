"""GC-595 — World Map visual polish (frontend contract + feed_id)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, ensure_player_and_homeworld, init_db, save_planet_buildings
from game.planet_evolution.command_center import build_colony_command_center

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"

GC595_LOCALE_KEYS = (
    "command_map_hover_level",
    "command_map_hover_production",
    "command_map_hover_queue_build",
    "command_map_hover_queue_research",
    "command_map_hover_queue_shipyard",
    "command_map_hover_queue_active",
    "command_map_hover_queue_free",
    "command_map_hover_fleets",
)


@pytest.fixture()
def gc595_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc595.db"
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


def test_gc595_locale_keys_present():
    for path in ("locales/en.json", "locales/de.json"):
        data = json.loads((ROOT / path).read_text(encoding="utf-8"))
        for key in GC595_LOCALE_KEYS:
            assert key in data, f"missing {key} in {path}"


def test_gc595_template_js_css_contract():
    tpl = (ROOT / "templates/partials/galaxy_command_map_panel.html").read_text(encoding="utf-8")
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    for needle in (
        "data-command-map-edge",
        "galaxy-command-map-edge-glow",
        "galaxy-command-map-node-activity-ring",
        "data-colony-hover-tooltip",
    ):
        assert needle in tpl, f"missing template marker: {needle}"
    for needle in (
        "function initCommandMapVisualPolish()",
        "initCommandMapVisualPolish();",
        "has-activity-build",
        "activityFeedId",
        "_activityFeedSeenIds",
        "buildColonyHoverHtml",
    ):
        assert needle in js, f"missing js marker: {needle}"
    for needle in (
        ".galaxy-command-map-edge-glow",
        ".has-activity-research",
        ".gc-command-center-activity-item.is-new",
        "@keyframes gc-map-edge-pulse-idle",
        ".galaxy-command-map-colony-hover-tooltip",
    ):
        assert needle in css, f"missing css rule: {needle}"


def test_activity_feed_includes_feed_id(gc595_db):
    from game.db import db
    from game.models import get_homeworld

    conn = db()
    try:
        ok, err, user = create_user(f"gc595_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok and user, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
        conn.commit()
        hw = get_homeworld(uid, conn=conn)
        planet_id = int(hw["id"])
        save_planet_buildings(planet_id, {"metal_mine": 1})
        conn.execute(
            """
            INSERT INTO build_queue (planet_id, building_type, start_time, finish_time)
            VALUES (?, 'metal_mine', ?, ?);
            """,
            (planet_id, 1_000_000.0, 1_000_600.0),
        )
        conn.commit()
        cc = build_colony_command_center(
            planet_id,
            uid,
            conn=conn,
            role_key="homeworld",
            is_homeworld=True,
        )
    finally:
        conn.close()

    feed = cc.get("activity_feed") or []
    assert feed
    assert all(row.get("feed_id") for row in feed)
