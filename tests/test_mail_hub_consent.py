from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_register_update_opt_in_is_separate_and_optional():
    html = _read("templates/register.html")
    marker = 'data-register-mail-updates'
    assert marker in html
    pos = html.index(marker)
    field = html[max(0, pos - 220): pos + 220]
    assert 'name="mail_updates"' in field
    assert "required" not in field


def test_options_and_returning_player_prompt_expose_update_controls():
    options = _read("templates/options.html")
    base = _read("templates/base.html")
    prompt = _read("templates/partials/mail_updates_prompt.html")
    assert 'id="options-mail-updates"' in options
    assert 'id="options-mail-updates-enable"' in options
    assert 'id="options-mail-updates-disable"' in options
    assert "partials/mail_updates_prompt.html" in base
    assert "js/mail_updates_prompt.js" in base
    assert "Double-Opt-In" in options
    assert "data-mail-updates-enable" in prompt


def test_mail_hub_routes_are_login_protected_and_scoped():
    app_py = _read("app.py")
    for route in (
        "/api/options/mail-updates/status",
        "/api/options/mail-updates/enable",
        "/api/options/mail-updates/disable",
    ):
        assert route in app_py
    assert "mail_hub_logic.request_updates" in app_py
    assert "mail_hub_logic.revoke_updates" in app_py


def test_mail_hub_client_uses_universe_scoped_identity(monkeypatch):
    from game import mail_hub

    monkeypatch.setenv("GC_UNIVERSE_KEY", "uni-test")
    assert mail_hub._identity(42) == "uni-test:42"


def test_privacy_text_documents_double_opt_in_and_separation():
    from game.legal_panel import LEGAL_PANEL_STRINGS, LEGAL_TEXT_VERSION

    de = LEGAL_PANEL_STRINGS["de"]["legal_privacy_marketing_body"]
    assert "Double-Opt-In" in de
    assert "Account-Mails" in de
    assert "jederzeit" in de
    assert LEGAL_TEXT_VERSION == "v2.2"
