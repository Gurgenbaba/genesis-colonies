#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Move bundled English milestone copy out of executable player-facing Python so
# the i18n raw-string gate only audits actual translatable UI chrome.
path = ROOT / "game/player_changelog.py"
text = path.read_text(encoding="utf-8")
start = text.find("_FALLBACK_MILESTONES = [")
end_marker = "\n\n\ndef _cache_path()"
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("fallback milestone block not found")
replacement = '''def _fallback_milestones() -> list[dict[str, Any]]:\n    path = Path(__file__).resolve().parent.parent / "data" / "player_changelog_fallback.json"\n    try:\n        payload = json.loads(path.read_text(encoding="utf-8"))\n    except (OSError, ValueError, TypeError):\n        return []\n    return payload if isinstance(payload, list) else []\n'''
text = text[:start] + replacement + text[end:]
text = text.replace("for milestone in _FALLBACK_MILESTONES:", "for milestone in _fallback_milestones():")
path.write_text(text, encoding="utf-8")

# Restore the bottom Version anchor byte-for-byte to the pre-feature markup.
# The changelog JS captures this stable class before PJAX and opens the dialog.
path = ROOT / "templates/partials/bottom_utility_bar.html"
text = path.read_text(encoding="utf-8")
old = '''      <button type="button"\n              class="gc-bottom-util-version gc-mono gc-nav-link"\n              data-gc-changelog-open\n              title="{{ T('changelog_full_title', 'Full Development Changelog') }}">\n        <span class="gc-bottom-util-version-label">{{ _release.label | default('Genesis') }}</span>\n        <span class="gc-bottom-util-version-sep" aria-hidden="true">•</span>\n        <span class="gc-bottom-util-version-stage">{{ T("release_stage_alpha", "Alpha") }}</span>\n      </button>'''
new = '''      <a href="{{ _release.href | default(url_for('news_view')) }}"\n         class="gc-bottom-util-version gc-mono gc-nav-link"\n         data-pjax-link\n         title="{{ T('sidebar_version_title', 'Genesis Timeline & Patchnotes') }}">\n        <span class="gc-bottom-util-version-label">{{ _release.label | default('Genesis') }}</span>\n        <span class="gc-bottom-util-version-sep" aria-hidden="true">•</span>\n        <span class="gc-bottom-util-version-stage">{{ T("release_stage_alpha", "Alpha") }}</span>\n      </a>'''
if old not in text:
    raise SystemExit("bottom Version trigger block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Capture the persistent Version link before generic PJAX navigation handlers.
path = ROOT / "static/js/player_changelog.js"
text = path.read_text(encoding="utf-8")
anchor = "  document.addEventListener('click', (event) => {\n    const opener = event.target.closest('[data-gc-changelog-open]');"
replacement = "  document.addEventListener('click', (event) => {\n    const versionOpener = event.target.closest('.gc-bottom-util-version');\n    if (versionOpener) {\n      event.preventDefault();\n      event.stopImmediatePropagation();\n      open();\n    }\n  }, true);\n\n  document.addEventListener('click', (event) => {\n    const opener = event.target.closest('[data-gc-changelog-open]');"
if anchor not in text:
    raise SystemExit("player changelog click handler anchor not found")
path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")

# Eyebrow uses an existing translated key instead of a new raw UI string.
path = ROOT / "templates/partials/player_changelog_dialog.html"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '<span class="gc-player-changelog-eyebrow">GENESIS COLONIES · GIT HISTORY</span>',
    '<span class="gc-player-changelog-eyebrow">{{ T(\'changelog_full_title\', \'Full Development Changelog\') }}</span>',
)
path.write_text(text, encoding="utf-8")

# Regressions: fallback data remains bundled and Version is intercepted by the
# persistent class instead of relying on the News destination.
path = ROOT / "tests/test_player_changelog_surface.py"
text = path.read_text(encoding="utf-8")
old_test = '''def test_bottom_version_is_dialog_button_not_news_link():\n    html = _read("templates/partials/bottom_utility_bar.html")\n    assert "data-gc-changelog-open" in html\n    version_block = html.split("gc-bottom-util-version", 1)[1]\n    assert "news_view" not in version_block\n'''
new_test = '''def test_bottom_version_is_captured_by_changelog_controller():\n    html = _read("templates/partials/bottom_utility_bar.html")\n    js = _read("static/js/player_changelog.js")\n    assert "gc-bottom-util-version" in html\n    assert "event.stopImmediatePropagation()" in js\n    assert "closest('.gc-bottom-util-version')" in js\n'''
if old_test not in text:
    raise SystemExit("bottom Version regression test anchor not found")
text = text.replace(old_test, new_test, 1)
if "test_bundled_fallback_history_is_data_driven" not in text:
    text += '''\n\ndef test_bundled_fallback_history_is_data_driven():\n    import json\n    payload = json.loads(_read("data/player_changelog_fallback.json"))\n    assert payload[0]["title"].startswith("v0.9.4")\n    assert payload[-1]["title"].startswith("v0.1")\n    backend = _read("game/player_changelog.py")\n    assert "_FALLBACK_MILESTONES =" not in backend\n    assert "player_changelog_fallback.json" in backend\n'''
path.write_text(text, encoding="utf-8")

print("player changelog i18n gate cleanup applied")
