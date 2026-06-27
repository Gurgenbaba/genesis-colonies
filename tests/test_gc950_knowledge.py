"""GC-950 — Genesis Codex knowledge pipeline."""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.codex import (
    build_codex_client_config,
    build_codex_panel_state,
    catalog_articles,
    codex_route_for_endpoint,
    is_codex_unlocked,
    load_catalog,
    primary_codex_for_route,
)
from game.knowledge_parser import load_player_articles_from_docs
from game.models import create_user, init_db

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "generated" / "codex" / "catalog.json"
DISCORD_EXPORT_DIR = ROOT / "docs" / "export" / "discord"
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc950_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc950.db"
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


def _create_player() -> tuple[int, str]:
    uname = f"gc950_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"]), uname


def _app_client(monkeypatch):
    import app as app_mod

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def _extract_codex_client_json(html: str) -> dict:
    match = re.search(
        r'<script id="gc-codex-client" type="application/json">\s*(\{.*?\})\s*</script>',
        html,
        re.DOTALL,
    )
    assert match, "gc-codex-client script block missing"
    return json.loads(match.group(1))


def test_player_articles_parsed_from_master_docs():
    articles = load_player_articles_from_docs()
    assert len(articles) >= 13
    ids = {str((a.get("meta") or {}).get("codex_id")) for a in articles}
    assert "game_rules" not in ids


def test_rules_panel_locale_keys_present():
    from game.game_rules_panel import all_rules_panel_locale_keys
    from game.i18n import SUPPORTED_LOCALES

    expected = set(all_rules_panel_locale_keys())
    for loc in sorted(SUPPORTED_LOCALES):
        path = ROOT / "locales" / f"{loc}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("rules_panel_intro"), loc
        assert data.get("rules_panel_push_title"), loc
        assert data.get("rules_panel_community_title"), loc
        assert data.get("rules_panel_faq_0_q"), loc
        assert data.get("rules_panel_version"), loc
        missing = expected - set(data.keys())
        assert not missing, f"missing in {loc}: {sorted(missing)[:8]}"
        stale = [k for k in data if k.startswith("codex_game_rules_")]
        assert not stale, f"stale codex keys in {loc}: {stale[:3]}"


def test_generated_catalog_matches_parser_count():
    assert CATALOG_PATH.is_file(), "run scripts/generate_knowledge.py"
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    parsed = load_player_articles_from_docs()
    assert len(catalog.get("articles") or {}) == len(parsed)


def test_codex_route_endpoints_match_catalog():
    catalog = load_catalog()
    routes = set((catalog.get("routes") or {}).keys())
    for endpoint in (
        "overview",
        "buildings_view",
        "research_view",
        "planet_evolution_view",
        "empire_view",
        "galaxy_view",
        "fleet_view",
        "shipyard_view",
        "defense_view",
        "trader_hub_view",
    ):
        assert codex_route_for_endpoint(endpoint) == endpoint
        assert endpoint in routes


def test_primary_codex_for_key_routes():
    assert primary_codex_for_route("overview") == "genesis_ark"
    assert primary_codex_for_route("buildings_view") == "buildings"
    assert primary_codex_for_route("research_view") == "research"
    assert primary_codex_for_route("trader_hub_view") == "trader"


def test_always_unlocked_codex_entries():
    for codex_id in ("genesis_ark", "buildings", "research", "resources"):
        assert is_codex_unlocked(0, codex_id) is True


def test_build_codex_client_config_resolved_content(gc950_db):
    uid, _ = _create_player()
    conn = dbmod.db()
    try:
        client = build_codex_client_config(uid, conn=conn)
        articles = client["articles"]
        assert set(articles.keys()) == set(catalog_articles().keys())
        buildings = articles["buildings"]
        assert buildings["title"]
        assert buildings["summary"]
        assert buildings["sections"]
        assert buildings["locked"] is False
        assert any(s.get("key") == "summary" for s in buildings["sections"])

        locked_id = next(
            cid
            for cid, meta in catalog_articles().items()
            if str((meta.get("unlock") or {}).get("type") or "") != "always"
        )
        locked = articles[locked_id]
        assert locked["locked"] is True
        assert locked["teaser"] or locked["unlock_label"]
        assert not locked["sections"]
    finally:
        conn.close()


def test_codex_panel_entries_have_content_or_teaser(gc950_db):
    uid, _ = _create_player()
    conn = dbmod.db()
    try:
        panel = build_codex_panel_state(uid, conn=conn)
        client = build_codex_client_config(uid, conn=conn)
        for band in panel["bands"]:
            for entry in band["articles"]:
                cid = entry["codex_id"]
                assert entry["title_key"]
                article = client["articles"][cid]
                if entry["unlocked"]:
                    assert article["title"]
                    assert article["summary"] or article["sections"]
                else:
                    assert article["teaser"] or article["unlock_label"] or entry.get("teaser_key")
    finally:
        conn.close()


def test_locked_codex_articles_have_preview_or_teaser(gc950_db):
    uid, _ = _create_player()
    conn = dbmod.db()
    try:
        client = build_codex_client_config(uid, conn=conn)
        for cid in ("combat", "trader", "ascension", "expansion"):
            art = client["articles"][cid]
            if art["locked"]:
                assert art["preview"] or art["teaser"] or art["unlock_label"]
                assert not art["sections"]
            else:
                assert art["summary"] or art["sections"]
    finally:
        conn.close()


def test_discord_exports_match_catalog():
    articles = catalog_articles()
    assert DISCORD_EXPORT_DIR.is_dir()
    exported = {p.stem for p in DISCORD_EXPORT_DIR.glob("*.md")}
    assert exported == set(articles.keys())


def test_overview_renders_codex_surfaces(gc950_db, monkeypatch):
    client = _app_client(monkeypatch)
    uid, _ = _create_player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    html = client.get("/overview").get_data(as_text=True)
    assert "data-special-window=\"codex\"" in html
    assert "data-codex-quick-help" in html or "gc-codex-quick-help" in html
    assert "gc-codex-client" in html
    assert "data-codex-context-open" in html
    assert "data-codex-article-body" in html

    client_json = _extract_codex_client_json(html)
    articles = client_json.get("articles") or {}
    assert articles
    assert "buildings" in articles
    assert articles["buildings"]["title"]
    assert articles["buildings"]["summary"]

    panel_ids = re.findall(r'data-codex-id="([^"]+)"', html)
    assert panel_ids
    for cid in panel_ids:
        assert cid in articles


def test_game_state_includes_codex(gc950_db, monkeypatch):
    client = _app_client(monkeypatch)
    uid, _ = _create_player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    payload = client.get("/api/game-state").get_json()
    assert payload.get("ok") is True
    codex = payload.get("codex") or {}
    assert codex.get("total_count") == len(catalog_articles())
    assert isinstance(codex.get("unlocked_ids"), list)
    assert codex.get("unlocked_count") == len(codex["unlocked_ids"])
    articles = codex.get("articles") or {}
    assert articles
    assert articles["buildings"]["title"]
    assert articles["buildings"]["summary"]


def test_options_renders_game_rules_panel_link(gc950_db, monkeypatch):
    client = _app_client(monkeypatch)
    uid, _ = _create_player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    html = client.get("/options").get_data(as_text=True)
    assert 'data-special-open-window="rules"' in html
    assert 'data-codex-open="game_rules"' not in html


def test_special_panel_rules_uses_i18n_sections():
    html = (ROOT / "templates/partials/special_panel.html").read_text(encoding="utf-8")
    assert "RULES_PANEL_SECTIONS" in html
    assert "RULES_PANEL_FAQ" in html
    assert "rules_panel_push_title" not in html  # uses dynamic keys
    assert "section.title_key" in html
    assert "gc-rules-panel-faq" in html
    assert 'data-special-open-window="support"' in html
    assert "Fairness steht ueber allem" not in html


def test_codex_route_visit_recorded_on_buildings(gc950_db, monkeypatch):
    client = _app_client(monkeypatch)
    uid, _ = _create_player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    client.get("/buildings")
    conn = dbmod.db()
    try:
        row = conn.execute(
            "SELECT 1 FROM player_unlocks WHERE user_id = ? AND unlock_key = ? LIMIT 1",
            (uid, "codex_visit:buildings_view"),
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_sidebar_right_excludes_commander_tip():
    sidebar = (ROOT / "templates/partials/sidebar_right.html").read_text(encoding="utf-8")
    assert "codex_commander_tip" not in sidebar
    assert "data-codex-commander-tip" not in sidebar


def test_overview_page_may_render_commander_tip():
    overview = (ROOT / "templates/overview.html").read_text(encoding="utf-8")
    assert "partials/codex_commander_tip.html" in overview
    assert "gc-codex-commander-tip-mobile" in overview


def test_game_state_codex_ok_without_sidebar_commander_tip(gc950_db, monkeypatch):
    client = _app_client(monkeypatch)
    uid, _ = _create_player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    html = client.get("/buildings").get_data(as_text=True)
    sidebar_right = html.split('id="gc-sidebar-nav-right"', 1)[1].split("</nav>", 1)[0]
    assert "data-codex-commander-tip" not in sidebar_right
    payload = client.get("/api/game-state").get_json()
    assert payload.get("ok") is True
    codex = payload.get("codex") or {}
    assert codex.get("articles")
    tip = codex.get("commander_tip")
    if tip:
        assert tip.get("text_key")


def test_apply_codex_commander_tip_noop_contract():
    src = (ROOT / "static/main.js").read_text(encoding="utf-8")
    tip_fn = src.split("function applyCommanderTipFromState")[1].split("function initCodex")[0]
    assert 'querySelectorAll("[data-codex-commander-tip]")' in tip_fn
    assert "if (!tipRoots.length) return" in tip_fn
    apply_fn = src.split("function applyCodexFromState")[1].split("function applyCommanderTipFromState")[0]
    assert "applyCommanderTipFromState(codexState.commander_tip)" in apply_fn
