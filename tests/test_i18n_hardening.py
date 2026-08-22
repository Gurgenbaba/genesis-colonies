"""GC-I18N-HARDENING regression guards."""

from __future__ import annotations

from pathlib import Path

from scripts.audit_visible_i18n import (
    ROOT,
    _js_findings,
    _placeholder_signature,
    _python_findings,
    _template_findings,
    audit_locale_parity,
)


def test_i18n_all_supported_locales_have_exact_key_and_placeholder_parity():
    failures = audit_locale_parity()
    assert not failures, "\n".join(failures[:30])


def test_i18n_placeholder_signature_tracks_percent_and_brace_names():
    assert _placeholder_signature("%(name)s — {count}") == (("name",), ("count",))
    assert _placeholder_signature("{count} / {count} · %(name)s") == (("name",), ("count",))


def test_i18n_template_scanner_flags_visible_literal_text_and_attributes():
    path = ROOT / "templates" / "_i18n_scanner_fixture.html"
    findings = _template_findings(
        path,
        [
            '<button aria-label="Send fleet">Attack now</button>',
            '<button aria-label="{{ T(\'fleet_send\', \'Senden\') }}">{{ T("fleet_attack", "Angreifen") }}</button>',
        ],
        None,
    )
    rendered = [f.render() for f in findings]
    assert any("Send fleet" in item for item in rendered)
    assert any("Attack now" in item for item in rendered)
    assert not any("fleet_send" in item or "fleet_attack" in item for item in rendered)


def test_i18n_js_scanner_flags_direct_player_copy_but_not_translation_calls():
    path = ROOT / "static" / "_i18n_scanner_fixture.js"
    findings = _js_findings(
        path,
        [
            'button.textContent = "Send fleet";',
            'button.textContent = t("fleet_send");',
            'node.setAttribute("aria-label", "Open research details");',
        ],
        None,
    )
    rendered = [f.render() for f in findings]
    assert any("Send fleet" in item for item in rendered)
    assert any("Open research details" in item for item in rendered)
    assert len(rendered) == 2


def test_i18n_python_scanner_flags_literal_ui_payload_copy():
    path = ROOT / "game" / "_i18n_scanner_fixture.py"
    findings = _python_findings(
        path,
        [
            'payload = {"title": "Planet Evolution", "label_key": "planet_evolution_title"}',
            'payload = {"title_key": "planet_evolution_title"}',
        ],
        None,
    )
    assert len(findings) == 1
    assert findings[0].text == "Planet Evolution"
