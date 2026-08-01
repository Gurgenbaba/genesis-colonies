"""Contract tests for public legal notices + imprint panel (digital shop compliance)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "locales"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture
def shop_db(tmp_path, monkeypatch):
    db_path = tmp_path / "legal_shop.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    import game.db as gdb
    from game.models import init_db
    import migrate

    gdb._DB_PATH = None
    init_db()
    migrate.main()
    yield
    gdb._DB_PATH = None


def test_legal_panel_locale_keys_present():
    from game.legal_panel import all_legal_panel_locale_keys

    expected = set(all_legal_panel_locale_keys())
    assert "legal_imprint_provider_body" in expected
    assert "legal_ack_digital_label" in expected
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((LOCALES / f"{loc}.json").read_text(encoding="utf-8"))
        missing = sorted(k for k in expected if not data.get(k))
        assert not missing, f"{loc} missing {missing[:5]}"


def test_special_panel_has_legal_hub_not_hobby_claim():
    html = _read("templates/partials/special_panel.html")
    assert "data-legal-panel" in html
    assert "data-legal-tab=" in html
    assert "data-legal-doc=" in html
    assert "LEGAL_DOCS" in html
    assert "LEGAL_OPERATOR_NAME" in html
    assert "nicht kommerziell" not in html
    assert "Hobbyprojekt" not in html
    assert 'value="billing"' in html
    assert "legal_contact_form_cta" in html


def test_auth_and_landing_link_public_legal():
    for rel in (
        "templates/landing.html",
        "templates/login.html",
        "templates/register.html",
    ):
        html = _read(rel)
        assert "legal_view" in html
        assert "legal_tab_imprint" in html or "legal_view" in html


def test_shop_has_legal_ack_partial():
    shop = _read("templates/shop.html")
    assert "partials/legal_ack.html" in shop or "data-legal-ack-root" in shop
    assert "legal_view" in shop
    ack = _read("templates/partials/legal_ack.html")
    assert "data-legal-ack-agb" in ack
    assert "data-legal-ack-digital" in ack


def test_public_legal_route_renders_provider(client_anon=None):
    from app import app
    from game.legal_panel import (
        OPERATOR_EMAIL,
        OPERATOR_NAME,
        OPERATOR_STREET,
        OPERATOR_POSTAL,
        OPERATOR_CITY,
        forbidden_hobby_phrases,
    )

    app.config["TESTING"] = True
    client = app.test_client()
    for path in ("/legal", "/legal/privacy", "/legal/terms", "/legal/withdrawal"):
        res = client.get(path)
        assert res.status_code == 200, path
        body = res.get_data(as_text=True)
        assert OPERATOR_NAME in body
        assert OPERATOR_STREET in body
        assert OPERATOR_POSTAL in body
        assert OPERATOR_CITY in body
        assert OPERATOR_EMAIL in body
        assert "mailto:" in body
        assert "](mailto:" not in body
        low = body.lower()
        for phrase in forbidden_hobby_phrases():
            assert phrase.lower() not in low, phrase
        if path.endswith("terms") or path.endswith("withdrawal"):
            assert "356" in body or "Widerruf" in body or "withdrawal" in body.lower()


def test_legal_keeps_identity_theme_when_logged_in(shop_db, monkeypatch):
    """Logged-in /legal must stay on the ingame shell with equipped identity theme."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    from game.battle_pass import ensure_default_season
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld
    from game.playercard import ensure_player_card
    from app import app

    conn = db()
    ok_u, err, user = create_user(f"skin_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok_u, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="SkinTester", conn=conn)
    ensure_default_season(conn)
    ensure_player_card(uid, conn=conn)
    conn.execute(
        "UPDATE player_cards SET theme = ? WHERE player_id = ?;",
        ("amber", uid),
    )
    conn.commit()
    conn.close()

    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    res = client.get("/legal")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'data-identity-theme="amber"' in body
    assert "gc-body-ingame" in body
    assert "gc-body-simple" not in body


def test_checkout_requires_legal_ack(shop_db, monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    from game.battle_pass import ensure_default_season
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld
    from game.shop import start_checkout

    conn = db()
    ok_u, err, user = create_user(f"legal_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok_u, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="LegalTester", conn=conn)
    ensure_default_season(conn)
    conn.commit()

    ok, reason, result = start_checkout(
        uid,
        "tk_pack_s",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
        legal_ack=False,
    )
    assert ok is False
    assert reason == "legal_ack_required"
    assert result is None

    ok2, reason2, result2 = start_checkout(
        uid,
        "tk_pack_s",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
        legal_ack=True,
    )
    assert ok2, reason2
    meta = (result2.get("order") or {}).get("metadata") or {}
    assert meta.get("legal_ack") is True
    assert meta.get("legal_text_version")
    conn.close()


def test_support_accepts_billing_category():
    from game.support import _category_label

    assert "Billing" in _category_label("billing") or "Zahlung" in _category_label("billing")
