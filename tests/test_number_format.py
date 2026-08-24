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


def test_fmt_int_compact_billions_one_decimal():
    assert fmt_int_compact(149539413840) == "149,5 Mrd."
    assert fmt_int_compact(149_000_000_000) == "149 Mrd."


def test_fmt_int_compact_does_not_strip_integer_trailing_zero():
    assert fmt_int_compact(150_000_000_000) == "150 Mrd."
    assert fmt_int_compact(15_000_000_000) == "15 Mrd."


def test_fmt_int_compact_below_threshold_uses_full():
    assert fmt_int_compact(9_999_999) == "9.999.999"


def test_fmt_int_parts_matches_full_for_tooltip():
    parts = fmt_int_parts(149539413840)
    assert parts["full"] == "149.539.413.840"
    assert parts["display"] == "149,5 Mrd."


def test_ranking_score_example_not_fifteen_billion():
    compact = fmt_int_compact(149539413840)
    assert compact != "15 Mrd."
    assert compact.startswith("149")


def test_million_and_trillion_tiers():
    assert fmt_int_compact(12_345_678) == "12,3 Mio."
    assert fmt_int_compact(2_500_000_000_000) == "2,5 Bio."


def test_compact_high_tiers_are_human_readable_never_scientific():
    cases = (
        (2_658_735_763_000_000, "P"),
        (2_500_000_000_000_000_000, "E"),
        (2_500_000_000_000_000_000_000, "Z"),
        (2_500_000_000_000_000_000_000_000, "Y"),
        (2_500_000_000_000_000_000_000_000_000, "R"),
        (2_500_000_000_000_000_000_000_000_000_000, "Q"),
    )
    scientific = re.compile(r"\d[,.]?\d*e[+-]?\d+", re.IGNORECASE)
    for value, suffix in cases:
        rendered = fmt_int_compact(value)
        assert rendered.endswith(f" {suffix}"), (value, rendered)
        assert not scientific.search(rendered), (value, rendered)
        assert "∞" not in rendered


def test_huge_integer_falls_back_to_full_grouped_digits_not_scientific():
    huge = 10**50 + 123456789
    full = fmt_int(huge)
    compact = fmt_int_compact(huge)
    assert full.replace(".", "") == str(huge)
    assert compact == full
    assert "∞" not in compact
    assert not re.search(r"\d[,.]?\d*e[+-]?\d+", compact, re.IGNORECASE)


def test_frontend_compact_formatter_never_uses_scientific_notation():
    """The JS mirror must keep suffix tiers and fall back to grouped full digits."""
    source = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    assert "_scientificBigInt" not in source
    assert "toExponential(" not in source
    assert "toPrecision(" not in source

    full_fallback = (
        "if (abs >= 1_000_000_000_000_000_000_000_000_000_000_000n) "
        "return _deIntFormatter.format(exact);"
    )
    assert full_fallback in source

    suffixes = (
        ("1_000_000_000_000_000_000_000_000_000_000n", "Q"),
        ("1_000_000_000_000_000_000_000_000_000n", "R"),
        ("1_000_000_000_000_000_000_000_000n", "Y"),
        ("1_000_000_000_000_000_000_000n", "Z"),
        ("1_000_000_000_000_000_000n", "E"),
        ("1_000_000_000_000_000n", "P"),
    )
    previous = source.index(full_fallback)
    for value, suffix in suffixes:
        branch = f"if (abs >= {value})"
        pos = source.index(branch)
        assert pos > previous
        fragment = source[pos : pos + 220]
        assert f"_compactBigIntBody(abs, {value})" in fragment
        assert f"}} {suffix}`;" in fragment
        previous = pos


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
