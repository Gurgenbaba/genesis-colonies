"""GC-596 — First Discovery Moment (presentation orchestration)."""

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
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.command_center import _feed_entry, build_colony_command_center

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"

GC596_LOCALE_KEYS = (
    "command_map_discovery_feed_title",
    "command_map_discovery_feed_subtitle",
    "command_map_expedition_feed_title",
)


@pytest.fixture()
def gc596_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc596.db"
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


def test_gc596_locale_keys_present():
    for path in ("locales/en.json", "locales/de.json"):
        data = json.loads((ROOT / path).read_text(encoding="utf-8"))
        for key in GC596_LOCALE_KEYS:
            assert key in data, f"missing {key} in {path}"


def test_gc596_template_js_css_contract():
    tpl = (ROOT / "templates/partials/galaxy_command_map_panel.html").read_text(encoding="utf-8")
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    for needle in (
        "data-command-map-discovery-banner",
        "galaxy-command-map-node-discovery-ring",
        "data-expedition-status",
    ):
        assert needle in tpl, f"missing template marker: {needle}"
    for needle in (
        "function initFirstDiscoveryMoment()",
        "initFirstDiscoveryMoment();",
        "GC.focusCommandMapWorld",
        "is-discovery-reveal",
        "is-expedition-route",
        "presentation === \"discovery\"",
        "gc_discovery_modal_auto",
        "openWorldInspectorFromNode",
        "GC.debugWorldInspector",
    ):
        assert needle in js, f"missing js marker: {needle}"
    for needle in (
        ".galaxy-command-map-discovery-banner",
        ".is-discovery-reveal",
        ".is-expedition-route",
        ".gc-command-center-activity-item.is-discovery",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert needle in css, f"missing css rule: {needle}"


def test_feed_entry_presentation_hints():
    discovery = _feed_entry("expedition", text="Report", presentation="discovery")
    launch = _feed_entry("fleet", detail_key="fleet_mission_expedition|Helios", presentation="expedition_launch")
    assert discovery.get("presentation") == "discovery"
    assert launch.get("presentation") == "expedition_launch"


def test_colony_feed_can_include_expedition_presentation(gc596_db):
    from game.db import db
    from game.models import get_homeworld

    conn = db()
    try:
        ok, err, user = create_user(f"gc596_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok and user, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
        conn.commit()
        hw = get_homeworld(uid, conn=conn)
        planet_id = int(hw["id"])
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
    assert isinstance(feed, list)
    for row in feed:
        if row.get("presentation"):
            assert row["presentation"] in {"discovery", "expedition_launch"}
