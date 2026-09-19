from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_landing_has_explicit_universe_selector():
    text = (ROOT / "templates" / "landing.html").read_text(encoding="utf-8")

    assert 'id="landing-universes"' in text
    assert "Development Universe" in text
    assert "Genesis Universe 1" in text
    assert "https://www.genesis-colonies.de" in text
    assert "https://genesis-colonies-u2-production.up.railway.app" in text


def test_uni1_is_visible_but_locked_until_release():
    text = (ROOT / "templates" / "landing.html").read_text(encoding="utf-8")

    assert "{% set uni1_open = false %}" in text
    assert "landing-server-disabled" in text
    assert "aria-disabled="true"" in text
    assert "Bald verfügbar" in text
    assert "Coming soon" in text


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
