from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_special_panel_has_community_hub_with_discord_link():
    html = _read("templates/partials/special_panel.html")
    assert 'data-community-hub' in html
    assert 'https://discord.gg/CYP8qWE7VM' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert 'class="discord-icon"' in html
    assert 'data-nav-badge="community"' in html
    assert 'data-special-open-window="rules"' not in html


def test_special_panel_community_menu_entries():
    html = _read("templates/partials/special_panel.html")
    for key in ("rules", "changelog", "events"):
        assert f'data-community-open="{key}"' in html
        assert f'data-special-window="{key}"' in html


def test_main_js_init_community_hub():
    src = _read("static/main.js")
    assert "function initCommunityHub()" in src
    assert "initCommunityHub();" in src
    assert "GC.openSpecialWindow = openSpecialWindow" in src


def test_community_hub_locale_keys():
    for name in ("locales/de.json", "locales/en.json"):
        text = _read(name)
        assert '"community_discord_title"' in text
        assert '"community_menu_discord"' in text
        assert '"nav_badge_community_aria"' in text
