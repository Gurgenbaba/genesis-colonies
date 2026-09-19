from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_landing_has_explicit_universe_selector():
    text = (ROOT / "templates" / "landing.html").read_text(encoding="utf-8")

    assert 'id="landing-universes"' in text
    assert "landing_server_dev_name" in text
    assert "landing_server_uni1_name" in text
    assert "https://www.genesis-colonies.de" in text
    assert "https://genesis-colonies-u2-production.up.railway.app" in text


def test_uni1_is_visible_but_locked_until_release():
    text = (ROOT / "templates" / "landing.html").read_text(encoding="utf-8")

    assert "{% set uni1_open = false %}" in text
    assert "landing-server-disabled" in text
    assert 'aria-disabled="true"' in text
    assert "landing_server_soon" in text


def test_unauthenticated_primary_cta_routes_to_server_selector():
    text = (ROOT / "templates" / "landing.html").read_text(encoding="utf-8")

    assert text.count('href="#landing-universes"') >= 2


def test_selector_styles_are_isolated_from_legacy_bundle():
    template = (ROOT / "templates" / "landing.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "landing-universe-selector.css").read_text(
        encoding="utf-8"
    )

    assert "css/landing-universe-selector.css" in template
    assert ".landing-server-grid" in css
    assert ".landing-server-card--live" in css
    assert ".landing-server-card--uni1" in css
    assert "@media (max-width: 760px)" in css


def test_auth_pages_keep_universe_identity_visible():
    for rel in ("templates/login.html", "templates/register.html"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "auth-universe-badge" in text
        assert "landing_server_dev_name" in text
        assert "landing_server_uni1_name" in text
        assert "genesis-colonies-u2" in text
        assert "uni1." in text


def test_universe_selector_copy_is_present_in_all_locales():
    import json

    required = {
        "landing_server_kicker",
        "landing_server_select_title",
        "landing_server_select_sub",
        "landing_server_live",
        "landing_server_preparing",
        "landing_server_dev_code",
        "landing_server_dev_name",
        "landing_server_dev_desc",
        "landing_server_dev_meta",
        "landing_server_uni1_code",
        "landing_server_uni1_name",
        "landing_server_uni1_desc",
        "landing_server_uni1_meta",
        "landing_server_register",
        "landing_server_login",
        "landing_server_soon",
        "landing_server_choose",
        "auth_universe_dev_note",
        "auth_universe_uni1_note",
    }
    for lang in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        payload = json.loads((ROOT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        assert required <= payload.keys()
        assert all(str(payload[key]).strip() for key in required)
