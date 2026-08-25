"""Tests for canonical number formatting (game/number_format.py)."""

from __future__ import annotations

from pathlib import Path
import re

from game.number_format import fmt_int, fmt_int_compact, fmt_int_parts, parse_int_number


ROOT = Path(__file__).resolve().parents[1]


def test_fmt_int_full_grouping():
    assert fmt_int(149539413840) == "149.539.413.840"
    assert fmt_int("149539413840") == "149.539.413.840"


def test_parse_int_number_accepts_de_grouped_strings():
    assert parse_int_number("149.539.413.840") == 149539413840
    assert parse_int_number(149539413840) == 149539413840
    assert parse_int_number("999.999") == 999999
    assert parse_int_number("1.000") == 1000
    assert parse_int_number("10.000.000") == 10_000_000
    assert parse_int_number("1000000") == 1_000_000


def test_fmt_int_compact_is_exact_compatibility_alias():
    values = (
        9_999_999,
        12_345_678,
        149_539_413_840,
        2_500_000_000_000,
        2_658_735_763_000_000,
        4_322_745_658_911_545_655,
        10**50 + 123456789,
        -4_322_745_658_911_545_655,
    )
    for value in values:
        assert fmt_int_compact(value) == fmt_int(value)


def test_fmt_int_parts_never_abbreviates_player_values():
    value = 4_322_745_658_911_545_655
    parts = fmt_int_parts(value)
    assert parts["full"] == "4.322.745.658.911.545.655"
    assert parts["display"] == parts["full"]


def test_frontend_compat_formatter_returns_full_grouped_number():
    source = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "function formatNumberCompact(n) {\n    return formatNumber(n);\n  }" in source
    assert "_compactBigIntBody" not in source
    assert "COMPACT_THRESHOLD" not in source
    assert "_scientificBigInt" not in source
    assert "toExponential(" not in source
    assert "toPrecision(" not in source


def test_exact_number_layout_contract_for_costs_and_empire():
    progression = (ROOT / "templates" / "partials" / "progression_cards.html").read_text(encoding="utf-8")
    empire = (ROOT / "templates" / "empire.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert "compact_val =" not in progression
    assert 'title="{{ full_val }}">{{ full_val }}</span>' in progression
    assert 'title="-{{ full_val }}">-{{ full_val }}</span>' in progression
    assert "fmt_int_compact" not in empire
    assert empire.count("empire-prod-card-value gc-mono gc-num-compact") == 3
    assert "GC-EXACT-NUMBERS-001" in css
    assert "text-overflow: ellipsis" in css


def test_backend_has_no_abbreviation_tiers():
    source = (ROOT / "game" / "number_format.py").read_text(encoding="utf-8")
    assert "_COMPACT_TIERS" not in source
    assert "_format_compact_body" not in source
    assert 'return fmt_int(value)' in source


def test_player_facing_js_has_no_explicit_scientific_formatters():
    """Prevent future UI modules from reintroducing browser scientific notation helpers."""
    banned = ("toExponential(", "toPrecision(", "_scientificBigInt")
    offenders = []
    for path in sorted((ROOT / "static").rglob("*.js")):
        source = path.read_text(encoding="utf-8", errors="ignore")
        for token in banned:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")
    assert not offenders, "Scientific UI formatters are forbidden:\n" + "\n".join(offenders)


def test_backend_canonical_formatter_has_no_scientific_helper():
    source = (ROOT / "game" / "number_format.py").read_text(encoding="utf-8")
    assert "_format_scientific_int" not in source


def test_ranking_uses_fullwidth_exact_score_layer():
    """Ranking focus assets must survive PJAX shell navigation and expand exact scores."""
    template = (ROOT / "templates" / "ranking.html").read_text(encoding="utf-8")
    shell = (ROOT / "templates" / "partials" / "bottom_utility_bar.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "ranking_page.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")

    assert "filename='ranking.css'" in template
    assert "filename='ranking.css'" in shell
    assert "filename='js/ranking_page.js'" in shell
    assert "filename='js/ranking_page.js'" not in template
    assert '.gc-ranking-score [title]' in script
    assert '.gc-ranking-mobile-score-inline [title]' in script
    assert '.gc-ranking-my-strip [title]' in script
    assert 'node.getAttribute("title")' in script
    assert "node.textContent = full" in script
    assert 'node.classList.remove("gc-num-compact", "num-compact")' in script
    assert 'node.classList.add("gc-ranking-num-full")' in script
    assert 'focusClass = "gc-ranking-focus"' in script
    assert 'function syncRankingPage()' in script
    assert 'const shellObserver = new MutationObserver(queueSync);' in script
    assert 'shellObserver.observe(shellHost, { childList: true, subtree: true });' in script
    assert 'if (!root) return;' not in script
    assert 'body[data-endpoint="ranking_view"] .gc-layout--dual' in css
    assert ".ranking-page .ranking-table-wrapper" in css
    assert "min-width: 300px" in css
    assert "overflow-x: auto" in css


def test_ranking_client_score_path_uses_bigint_exactly():
    """Ranking must preserve exact decimal score strings and sort them descending."""
    source = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    assert "return parseDisplayBigInt(row[tab.scoreKey]);" in source
    assert "return parseDisplayBigInt(cur[tab.scoreKey]);" in source
    assert "return parseIntNumber(row[tab.scoreKey]);" not in source
    assert "return parseIntNumber(cur[tab.scoreKey]);" not in source
    assert "rankingScoreValue(b, tabId) - rankingScoreValue(a, tabId)" not in source
    wrong = "if (scoreB !== scoreA) return scoreB > scoreA ? -1 : 1;"
    correct = "if (scoreA !== scoreB) return scoreA > scoreB ? -1 : 1;"
    assert wrong not in source
    assert source.count(correct) == 2
