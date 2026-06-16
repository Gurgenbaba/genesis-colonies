"""GC-597 — World Inspector Modal (map stage + full-map layout)."""



from __future__ import annotations



import importlib

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



ROOT = Path(__file__).resolve().parent.parent

MIGRATE_SCRIPT = ROOT / "migrate.py"



GC597_LOCALE_KEYS = (

    "world_inspector_close",

    "world_inspector_open_colony",

    "world_inspector_explore",

    "world_inspector_level",

    "world_inspector_status",

    "command_center_hud_idle",

    "world_inspector_foreign_dev_body",

    "world_inspector_foreign_dev_classic_cta",

    "world_inspector_foreign_dev_fleet_cta",

    "world_inspector_type",

)





@pytest.fixture()

def gc597_db(tmp_path, monkeypatch):

    db_file = tmp_path / "gc597.db"

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





def test_gc597_locale_keys_present():

    for path in ("locales/en.json", "locales/de.json"):

        data = json.loads((ROOT / path).read_text(encoding="utf-8"))

        for key in GC597_LOCALE_KEYS:

            assert key in data, f"missing {key} in {path}"





def test_gc597_template_js_css_contract():

    tpl = (ROOT / "templates/partials/galaxy_command_map_panel.html").read_text(encoding="utf-8")

    js = (ROOT / "static/main.js").read_text(encoding="utf-8")

    css = (ROOT / "static/style.css").read_text(encoding="utf-8")

    for needle in (

        "data-colony-location-inspect",

        "data-world-field-inspect",

        "data-expansion-site-inspect",

        "data-landmark-inspect",

        "galaxy-command-map-graph--fullmap",

        "galaxy-command-map-legacy-shell",

        "gc-world-inspector-modal",

        "data-world-inspector-modal",

        "data-world-inspector-content",

    ):

        assert needle in tpl, f"missing template marker: {needle}"

    assert "map_inspector_title" not in tpl or "galaxy-command-map-legacy-shell" in tpl

    assert "gc-command-center-hud-body" not in tpl

    for needle in (

        "function initWorldInspectorModal()",

        "initWorldInspectorModal();",

        "GC.openWorldInspectorModal",

        "GC.openWorldInspectorFromNode",

        "GC.debugWorldInspector",

        "function onInspectorNodeClick",

        'graph.addEventListener("click", onInspectorNodeClick)',

        "root.classList.add(\"is-open\")",

        "mergeColonyPayload",

        "mergeWorldFieldPayload",

        "shouldShowForeignDevPreview",

        "renderForeignDevPreviewModal",

        "world_inspector_foreign_dev_body",

    ):

        assert needle in js, f"missing js marker: {needle}"

    show_colony = js.split("GC.showCommandMapColonyPanel = function showCommandMapColonyPanel")[1].split(

        "GC.showCommandMapStrategicWorldPanel = function"

    )[0]

    assert "openWorldInspectorFromNode" in show_colony

    assert "renderSidebarHud" not in show_colony

    assert "setCommandMapSidePanelState(colonyPanel" not in show_colony

    for needle in (

        ".gc-world-inspector-modal",

        ".gc-world-inspector-modal.is-open",

        ".galaxy-command-map-graph--fullmap",

        ".galaxy-command-map-legacy-shell",

        ".gc-world-inspector-flavor",

        ".gc-world-inspector-shell--foreign-dev",

        ".gc-world-inspector-actions--stacked",

    ):

        assert needle in css, f"missing css rule: {needle}"

    assert "grid-template-columns: minmax(0, 1fr) minmax(220px" not in css.split(

        ".galaxy-command-map-graph{"

    )[1].split("}")[0]





def test_gc597_galaxy_renders_fullmap_and_modal(gc597_db, monkeypatch):

    import app as app_module



    dbmod.DB_PATH = gc597_db

    models.DB_PATH = gc597_db

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")

    importlib.reload(app_module)



    uname = f"gc597_ui_{uuid.uuid4().hex[:8]}"

    ok, err, user = create_user(uname, "test-pass-123")

    assert ok and user, err

    ensure_player_and_homeworld(int(user["id"]), player_name="Commander")



    client = app_module.app.test_client()

    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    body = client.get("/galaxy?view=command_map").get_data(as_text=True)



    assert "galaxy-command-map-graph--fullmap" in body

    assert "gc-world-inspector-modal" in body

    assert "galaxy-command-map-legacy-shell" in body

    assert "data-command-center" in body

    assert "gc-command-center-hud" not in body
    assert "galaxy-command-map-site-inspector-title" not in body

