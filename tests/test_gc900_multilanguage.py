"""GC-900C — Multilanguage foundation guards."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
MIGRATE_SCRIPT = ROOT / "migrate.py"

import game.db as dbmod  # noqa: E402
import game.models as models  # noqa: E402
from game.i18n import (  # noqa: E402
    DEFAULT_LOCALE,
    FALLBACK_LOCALE,
    SUPPORTED_LANGUAGES,
    SUPPORTED_LOCALES,
    get_locale_dict,
    normalize_locale,
    tr,
)

_GERMAN_CHARS = re.compile(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]")


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "multilang_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


@pytest.fixture()
def app_client(temp_db, monkeypatch):
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(temp_db)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    models.init_db()
    try:
        models.db().close()
    except Exception:
        pass

    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


@pytest.fixture
def de_data():
    return json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))


def test_gc900c_supported_languages_have_locale_files():
    for code in SUPPORTED_LOCALES:
        path = LOCALES / f"{code}.json"
        assert path.exists(), f"missing {path.name}"


def test_gc900c_all_locales_match_de_keyset(de_data):
    de_keys = set(de_data)
    for code in SUPPORTED_LOCALES:
        data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        missing = sorted(de_keys - set(data))
        assert not missing, f"{code}.json missing {len(missing)} keys: {missing[:5]}"


def test_gc900c_no_missing_keys_vs_de(de_data):
    for code in SUPPORTED_LOCALES:
        data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        assert len(data) >= len(de_data)


def test_gc900c_non_de_no_abbau_pfad():
    for code in SUPPORTED_LOCALES:
        if code == "de":
            continue
        data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        hits = [k for k, v in data.items() if isinstance(v, str) and "Abbau-Pfad" in v]
        assert not hits, hits[:5]


def test_gc900c_en_no_ferronit():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    bad = [k for k, v in en.items() if isinstance(v, str) and re.search(r"Ferronit(?!e)", v)]
    assert not bad, bad[:5]


def test_gc900c_non_de_no_german_chars():
    bad_locales: dict[str, list[str]] = {}
    german_words = re.compile(
        r"\b(und|der|die|das|nicht|für|Sie|Ihr|Spieler|Gebäude|Forschung|Allianz|Kolonie|Schiff|Flotte|Werft|Stufe)\b",
        re.I,
    )
    for code in SUPPORTED_LOCALES:
        if code == "de":
            continue
        data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        hits = []
        for k, v in data.items():
            if k.startswith("language_name_") or not isinstance(v, str):
                continue
            if "ß" in v or (german_words.search(v) and _GERMAN_CHARS.search(v)):
                hits.append(k)
        if hits:
            bad_locales[code] = hits[:5]
    assert not bad_locales, bad_locales


def test_gc900c_language_switcher_renders_flags(app_client):
    res = app_client.get("/login")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'id="gc-language-switcher"' in html
    assert 'data-gc-hud-select' in html
    assert 'id="gc-language-select"' in html
    assert "🇩🇪" in html
    assert ">DE</button>" not in html
    assert ">EN</button>" not in html
    assert 'class="gc-hud-select-trigger"' in html or 'data-gc-hud-select' in html


def test_gc900c_language_switcher_has_aria_labels(app_client):
    res = app_client.get("/login")
    html = res.get_data(as_text=True)
    assert 'aria-label="Sprache"' in html
    assert 'data-lang-label="Deutsch"' in html or 'data-lang-label="German"' in html
    assert 'value="fr"' in html
    assert ">Französisch</" not in html
    assert ">Deutsch</" not in html


def test_gc900c_invalid_locale_falls_back_to_de():
    assert normalize_locale("xx") == DEFAULT_LOCALE
    assert normalize_locale("") == DEFAULT_LOCALE
    assert normalize_locale(None) == DEFAULT_LOCALE


def test_gc900c_tr_works_for_each_supported_language():
    sample_key = "buildings_title"
    for code in SUPPORTED_LOCALES:
        text = tr(sample_key, locale=code)
        assert text
        assert text != sample_key


def test_gc900c_non_de_fallback_chain_uses_en():
    fr = get_locale_dict("fr")
    en = get_locale_dict("en")
    assert fr["buildings_title"] == en["buildings_title"]
    assert FALLBACK_LOCALE == "en"


def test_gc900c_api_accepts_french_guest(app_client):
    res = app_client.post(
        "/api/locale",
        json={"locale": "fr"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    assert res.get_json()["data"]["locale"] == "fr"


def test_gc900c_non_de_locales_differ_from_en_for_ui_sample():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    sample_keys = ("buildings_title", "research_title", "fleet_send", "defense_hint", "overview_hint")
    for code in ("fr", "es", "pl", "tr", "ru", "pt"):
        data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        diffs = [k for k in sample_keys if k in en and k in data and data[k] != en[k]]
        assert diffs, f"{code}.json still identical to EN for sample keys"
