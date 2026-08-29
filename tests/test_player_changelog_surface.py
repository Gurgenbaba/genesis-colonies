from pathlib import Path

from game.player_changelog import build_changelog_payload_from_commits, humanize_commit

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _commit(sha: str, message: str, date: str = "2026-08-28T12:00:00Z"):
    return {
        "sha": sha,
        "html_url": f"https://github.com/Gurgenbaba/genesis-colonies/commit/{sha}",
        "commit": {"message": message, "author": {"date": date}},
    }


def test_humanizer_turns_gameplay_commit_into_readable_english():
    item = humanize_commit("feat: scale standard asteroid belts and preview harvest fuel")
    assert item is not None
    assert item["technical"] is False
    assert item["category"] == "New Features"
    assert "asteroid rewards" in item["title"].lower()
    assert "flight-time" in item["title"].lower()


def test_humanizer_keeps_internal_commits_available_but_marks_them_technical():
    item = humanize_commit("ci: rerun scoped World Boss raid gate")
    assert item is not None
    assert item["technical"] is True
    assert item["category"] == "Technical & Reliability"


def test_payload_represents_every_non_merge_commit_and_collapses_merges():
    commits = [
        _commit("a" * 40, "feat(fleet): add launch reason feedback"),
        _commit("b" * 40, "test: cover fleet reason feedback"),
        _commit("c" * 40, "Merge pull request #99 from feature/test"),
    ]
    payload = build_changelog_payload_from_commits(commits, source="test")
    assert payload["total_commits_seen"] == 3
    assert payload["represented_commits"] == 2
    assert payload["technical_commits"] == 1
    assert payload["merge_commits_collapsed"] == 1
    assert sum(len(group["entries"]) for group in payload["groups"]) == 2


def test_bottom_version_is_captured_by_changelog_controller():
    html = _read("templates/partials/bottom_utility_bar.html")
    js = _read("static/js/player_changelog.js")
    assert "gc-bottom-util-version" in html
    assert "event.stopImmediatePropagation()" in js
    assert "closest('.gc-bottom-util-version')" in js


def test_shell_has_persistent_changelog_dialog_assets():
    base = _read("templates/base.html")
    dialog = _read("templates/partials/player_changelog_dialog.html")
    assert 'partials/player_changelog_dialog.html' in base
    assert 'data-gc-changelog-dialog' in dialog
    assert 'js/player_changelog.js' in dialog
    assert 'css/player_changelog.css' in dialog


def test_community_changelog_opens_same_canonical_dialog():
    html = _read("templates/partials/special_panel.html")
    assert 'data-gc-changelog-open' in html
    assert 'data-special-window="changelog"' not in html


def test_bundled_fallback_history_is_data_driven():
    import json
    payload = json.loads(_read("data/player_changelog_fallback.json"))
    assert payload[0]["title"].startswith("v0.9.4")
    assert payload[-1]["title"].startswith("v0.1")
    backend = _read("game/player_changelog.py")
    assert "_FALLBACK_MILESTONES =" not in backend
    assert "player_changelog_fallback.json" in backend
