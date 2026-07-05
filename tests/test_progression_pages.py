"""
Smoke/regression tests for compact Buildings & Research progression UI.

Run: python -m pytest tests/test_progression_pages.py -v
"""

from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import BUILDING_ORDER
from game.models import create_user, init_db
from game.research import RESEARCH_TECHS

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "progression_pages.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    try:
        dbmod.db().close()
    except Exception:
        pass
    return db_file


def _create_player(username: str) -> tuple[int, str]:
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    try:
        dbmod.db().close()
    except Exception:
        pass
    return int(user["id"]), uname


def _login_client(temp_db, monkeypatch):
    import app as app_module

    monkeypatch.setattr(dbmod, "DB_PATH", temp_db)
    monkeypatch.setattr(models, "DB_PATH", temp_db)
    importlib.reload(app_module)
    _, uname = _create_player("prog_ui")
    client = app_module.app.test_client()
    login = client.post("/login", data={"username": uname, "password": "test-pass-123"})
    assert login.status_code in (200, 302)
    return client


def test_locale_mechanics_descriptions():
    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))

    for locale, label in ((de, "de"), (en, "en")):
        if label == "de":
            assert "5 %" in locale["desc_terraformer"] and "Lager" in locale["desc_terraformer"]
            assert "Infrastruktur" in locale["desc_terraformer"]
            assert "5 %" in locale["desc_academy"] and "Forschung" in locale["desc_academy"]
            assert "30 %" in locale["desc_nanofactory"] and "Bauzeit" in locale["desc_nanofactory"]
            assert "10 %" in locale["desc_mining_tech"] and "4 %" in locale["desc_mining_tech"]
            assert "33 %" in locale["desc_storage_tech"] and "Lager" in locale["desc_storage_tech"]
        else:
            assert "5%" in locale["desc_terraformer"] and "storage" in locale["desc_terraformer"].lower()
            assert "infrastructure" in locale["desc_terraformer"].lower()
            assert "5%" in locale["desc_academy"] and "research" in locale["desc_academy"].lower()
            assert "30%" in locale["desc_nanofactory"] and "build" in locale["desc_nanofactory"].lower()
            assert "10%" in locale["desc_mining_tech"] and "4%" in locale["desc_mining_tech"]
            assert "33%" in locale["desc_storage_tech"] and "storage" in locale["desc_storage_tech"].lower()

        for key in BUILDING_ORDER:
            desc_key = f"desc_{key}"
            assert desc_key in locale, f"missing {label} locale key {desc_key}"
            assert not locale[desc_key].startswith("desc_")

        for key in RESEARCH_TECHS:
            desc_key = f"desc_{key}"
            assert desc_key in locale, f"missing {label} locale key {desc_key}"
            assert not locale[desc_key].startswith("desc_")


def test_templates_import_progression_macros_with_context():
    buildings = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")
    research = (ROOT / "templates" / "research.html").read_text(encoding="utf-8")
    assert "with context" in buildings
    assert "data-building-tech-data" in buildings
    assert "render_info_popover_trigger" not in buildings
    assert "with context" in research
    assert "data-research-tech-data" in research
    assert "render_info_popover_trigger" not in research
    assert "render_research_head_action" in research
    assert "show_reqs" in research
    assert "render_hero_queue" in research
    assert "gc-bld-head-action-btn--busy" not in research
    assert "render_prog_identity" not in research
    assert "render_prog_effect" not in buildings
    assert "render_prog_effect" not in research


def test_buildings_page_renders(temp_db, monkeypatch):
    client = _login_client(temp_db, monkeypatch)
    res = client.get("/buildings")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "UndefinedError" not in html
    assert "buildings-prog-list" in html
    assert "gc-building-grid" in html
    assert "gc-bld-card-action" in html
    assert "gc-bld-head-action-btn" in html
    assert "gc-bld-head-action-btn--go" in html
    buildings_tpl = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")
    assert "data-hero-time-chip" in buildings_tpl
    assert "gc-bld-card-meta--costs-only" in buildings_tpl
    assert "gc-bld-card-time" not in buildings_tpl
    assert "gc-bld-effect-bundle" in html
    assert "gc-prog-effect" not in html
    assert "gc-prog-desc" not in html

    assert 'data-building-tech-data="' in html
    assert "gc-bld-card-title-btn" in html
    assert 'class="gc-prog-info' not in html

    assert "status-pill-icon-btn" in html or "⚠" in html or "gc-bld-head-action-btn--warn" in html

def test_research_page_renders(temp_db, monkeypatch):
    client = _login_client(temp_db, monkeypatch)
    res = client.get("/research")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "UndefinedError" not in html
    assert "research-prog-list" in html
    assert "gc-bld-card-hero" in html
    assert "gc-bld-card-head-action" in html
    assert "gc-bld-head-action-btn" in html
    assert "gc-prog-main" not in html
    assert "gc-prog-effect" not in html
    assert "gc-prog-desc" not in html

    assert 'data-research-tech-data="' in html
    assert "gc-bld-card-title-btn" in html
    assert 'class="gc-prog-info' not in html

    assert "status-pill-icon-btn" in html or "⚠" in html or "gc-bld-head-action-btn--warn" in html


def test_trait_effect_keys_en_complete():
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    trait_keys = [
        "ferronit_rich_crust",
        "crytite_veins",
        "unstable_mantle",
        "deep_core_pressure",
        "plasma_winds",
        "cryogenic_atmosphere",
        "aetherion_storms",
        "radioactive_ocean",
        "organic_subsurface_network",
        "high_gravity",
        "ancient_ruins",
        "dark_matter_residue",
        "quantum_echo_field",
        "subsurface_vault_hint",
    ]
    for key in trait_keys:
        assert f"trait_effect_{key}" in en, f"missing en trait_effect_{key}"


def test_queue_full_short_label_keys_exist():
    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "research_status_queue_full_short" in de
    assert "research_status_queue_full_short" in en
