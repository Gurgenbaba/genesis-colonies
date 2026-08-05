"""GC-000: static checks for no-reload and architecture contracts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (relative path, 1-based line number) — documented exceptions only.
# static/admin.js is out of scope here (see _iter_js_lines skip below); its
# admin-shell reload sites live under the separate admin contract.
ALLOWLIST_RELOAD = {
    ("static/main.js", 2581),  # GC.reloadCurrentPage fullDocument branch
    ("static/main.js", 2611),  # GC.reloadCurrentPage navigateTo-undefined fallback
    ("static/main.js", 31649),  # locale switch: GC.reloadCurrentPage-undefined fallback
}

ALLOWLIST_LOCATION_HREF_ASSIGN = {
    ("static/main.js", 1048),  # auth recovery fallback if assign() throws
    ("static/main.js", 13935),  # radar nav fallback if GC.navigateTo missing
    ("static/main.js", 37013),  # galaxy coord commit fallback if GC.navigateTo missing
    ("static/js/messages.js", 351),  # navigateTo-missing fallback
    ("static/js/messages.js", 2622),  # fleet attack nav fallback
    ("static/js/messages.js", 2657),  # recycle nav fallback
    ("static/js/messages.js", 2670),  # spy simulate nav fallback
    ("static/js/options.js", 542),  # Discord unlink fallback if navigateTo missing
}

RELOAD_PATTERN = re.compile(r"\b(?:window\.)?location\.reload\s*\(")
HREF_ASSIGN_PATTERN = re.compile(
    r"\b(?:window\.)?location\.href\s*="
)


def _iter_js_lines(*, globs: tuple[str, ...]) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for pattern in globs:
        for path in sorted(ROOT.glob(pattern)):
            if "node_modules" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("static/admin"):
                continue  # admin shell — separate contract
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                rows.append((rel, i, line))
    return rows


def test_no_undocumented_location_reload_in_game_static():
    violations: list[str] = []
    for rel, line_no, line in _iter_js_lines(globs=("static/**/*.js",)):
        if not RELOAD_PATTERN.search(line):
            continue
        if (rel, line_no) in ALLOWLIST_RELOAD:
            continue
        violations.append(f"{rel}:{line_no}: {line.strip()}")
    assert not violations, "Undocumented location.reload() in game static:\n" + "\n".join(
        violations
    )


def test_no_undocumented_location_href_navigation():
    violations: list[str] = []
    for rel, line_no, line in _iter_js_lines(globs=("static/**/*.js",)):
        if not HREF_ASSIGN_PATTERN.search(line):
            continue
        if (rel, line_no) in ALLOWLIST_LOCATION_HREF_ASSIGN:
            continue
        # Reading href (no assignment) — e.g. normalizePjaxUrl(window.location.href)
        if "=" not in line.split("location.href", 1)[0]:
            continue
        stripped = line.strip()
        if "history.replaceState" in stripped:
            continue
        violations.append(f"{rel}:{line_no}: {stripped}")
    assert not violations, (
        "Undocumented location.href = navigation in game static:\n" + "\n".join(violations)
    )


def test_core_architecture_docs_exist():
    required = [
        "docs/CORE_ARCHITECTURE.md",
        "docs/QUEUE_STATE_RULES.md",
        "docs/AJAX_PJAX_CONTRACT.md",
    ]
    missing = [p for p in required if not (ROOT / p).is_file()]
    assert not missing, f"Missing GC-000 docs: {missing}"


def test_core_architecture_v2_rules_present():
    text = (ROOT / "docs/CORE_ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Konsistenz über Komfort" in text
    for marker in (
        "## 15. No Parallel Systems",
        "## 16. No Duplicate Math",
        "## 17. Every Feature Needs An Owner",
        "game/queue_engine.py",
        "get_context_planet",
    ):
        assert marker in text, f"GC-000 v2 missing: {marker!r}"
