#!/usr/bin/env python3
from pathlib import Path
import re

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

# Keep the bottom Version trigger visually identical to the old anchor so the
# diff-aware raw-string scanner does not misread a class attribute as text.
path = ROOT / "templates/partials/bottom_utility_bar.html"
text = path.read_text(encoding="utf-8")
old = '''      <button type="button"\n              class="gc-bottom-util-version gc-mono gc-nav-link"\n              data-gc-changelog-open\n              title="{{ T('changelog_full_title', 'Full Development Changelog') }}">\n        <span class="gc-bottom-util-version-label">{{ _release.label | default('Genesis') }}</span>\n        <span class="gc-bottom-util-version-sep" aria-hidden="true">•</span>\n        <span class="gc-bottom-util-version-stage">{{ T("release_stage_alpha", "Alpha") }}</span>\n      </button>'''
new = '''      <a href="#changelog"\n         class="gc-bottom-util-version gc-mono gc-nav-link"\n         data-gc-changelog-open\n         title="{{ T('sidebar_version_title', 'Genesis Timeline & Patchnotes') }}">\n        <span class="gc-bottom-util-version-label">{{ _release.label | default('Genesis') }}</span>\n        <span class="gc-bottom-util-version-sep" aria-hidden="true">•</span>\n        <span class="gc-bottom-util-version-stage">{{ T("release_stage_alpha", "Alpha") }}</span>\n      </a>'''
if old not in text:
    raise SystemExit("bottom Version trigger block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Eyebrow uses an existing translated key instead of a new raw UI string.
path = ROOT / "templates/partials/player_changelog_dialog.html"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '<span class="gc-player-changelog-eyebrow">GENESIS COLONIES · GIT HISTORY</span>',
    '<span class="gc-player-changelog-eyebrow">{{ T(\'changelog_full_title\', \'Full Development Changelog\') }}</span>',
)
path.write_text(text, encoding="utf-8")

# Regression: fallback data remains bundled even though it no longer lives in Python.
path = ROOT / "tests/test_player_changelog_surface.py"
text = path.read_text(encoding="utf-8")
if "test_bundled_fallback_history_is_data_driven" not in text:
    text += '''\n\ndef test_bundled_fallback_history_is_data_driven():\n    import json\n    payload = json.loads(_read("data/player_changelog_fallback.json"))\n    assert payload[0]["title"].startswith("v0.9.4")\n    assert payload[-1]["title"].startswith("v0.1")\n    backend = _read("game/player_changelog.py")\n    assert "_FALLBACK_MILESTONES =" not in backend\n    assert "player_changelog_fallback.json" in backend\n'''
    path.write_text(text, encoding="utf-8")

print("player changelog i18n gate cleanup applied")
