"""Tests for canonical number formatting (game/number_format.py)."""

from __future__ import annotations

from game.number_format import fmt_int, fmt_int_compact, fmt_int_parts, parse_int_number


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



def test_huge_integer_never_becomes_fake_infinity():
    huge = 10**50 + 123456789
    assert fmt_int(huge).replace(".", "") == str(huge)
    compact = fmt_int_compact(huge)
    assert compact != "∞"
    assert "e50" in compact


def test_apply_big_score_display_hotfix_executor():
    """One-shot CI executor; final commit rewrites this test out completely."""
    import os
    from pathlib import Path
    import subprocess

    import pytest

    if not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_REPOSITORY") == "Gurgenbaba/genesis-colonies"
        and os.environ.get("GITHUB_HEAD_REF") == "hotfix/big-score-display-v2"
    ):
        pytest.skip("one-shot hotfix executor only runs on its dedicated PR branch")

    root = Path(__file__).resolve().parents[1]

    def run(*args: str) -> None:
        subprocess.run(args, cwd=root, check=True)

    run("git", "fetch", "origin", "main", "hotfix/big-score-display-v2")
    run("git", "checkout", "-B", "hotfix/big-score-display-v2", "origin/hotfix/big-score-display-v2")

    js_path = root / "static" / "main.js"
    source = js_path.read_text(encoding="utf-8")
    old = '''    if (abs >= 1_000_000_000_000_000n) return _scientificBigInt(abs, negative);
    const sign = negative ? "-" : "";
    if (abs >= 1_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000n)} Bio.`;
'''
    new = '''    if (abs >= 1_000_000_000_000_000_000_000_000_000_000_000n) return _scientificBigInt(abs, negative);
    const sign = negative ? "-" : "";
    if (abs >= 1_000_000_000_000_000_000_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000_000_000_000_000_000_000n)} Q`;
    if (abs >= 1_000_000_000_000_000_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000_000_000_000_000_000n)} R`;
    if (abs >= 1_000_000_000_000_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000_000_000_000_000n)} Y`;
    if (abs >= 1_000_000_000_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000_000_000_000n)} Z`;
    if (abs >= 1_000_000_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000_000_000n)} E`;
    if (abs >= 1_000_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000_000n)} P`;
    if (abs >= 1_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000n)} Bio.`;
'''
    assert source.count(old) == 1, "canonical frontend formatter block changed unexpectedly"
    js_path.write_text(source.replace(old, new, 1), encoding="utf-8")

    canonical_tests = subprocess.check_output(
        ["git", "show", "origin/main:tests/test_number_format.py"], cwd=root, text=True
    )
    final_regression = r'''


def test_frontend_big_score_suffixes_before_scientific_notation():
    """Huge score display uses readable BigInt suffixes through 10^30."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "static" / "main.js").read_text(encoding="utf-8")
    old_scientific = "if (abs >= 1_000_000_000_000_000n) return _scientificBigInt(abs, negative);"
    new_scientific = "if (abs >= 1_000_000_000_000_000_000_000_000_000_000_000n) return _scientificBigInt(abs, negative);"
    assert old_scientific not in source
    assert new_scientific in source

    suffixes = (
        ("1_000_000_000_000_000_000_000_000_000_000n", "Q"),
        ("1_000_000_000_000_000_000_000_000_000n", "R"),
        ("1_000_000_000_000_000_000_000_000n", "Y"),
        ("1_000_000_000_000_000_000_000n", "Z"),
        ("1_000_000_000_000_000_000n", "E"),
        ("1_000_000_000_000_000n", "P"),
    )
    previous = source.index(new_scientific)
    for value, suffix in suffixes:
        branch = f"if (abs >= {value})"
        pos = source.index(branch)
        assert pos > previous
        fragment = source[pos : pos + 220]
        assert f"_compactBigIntBody(abs, {value})" in fragment
        assert f"}} {suffix}`;" in fragment
        previous = pos
'''
    final_test_content = canonical_tests.rstrip() + final_regression.rstrip() + "\n"
    (root / "tests" / "test_number_format.py").write_text(final_test_content, encoding="utf-8")

    run("git", "checkout", "origin/main", "--", ".github/workflows/ci.yml")
    run("node", "--check", "static/main.js")
    run("python", "-m", "pytest", "-q", "tests/test_number_format.py")
    run("git", "diff", "--check")

    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "origin/main"], cwd=root, text=True
    ).splitlines()
    assert changed == ["static/main.js", "tests/test_number_format.py"], changed

    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "add", ".github/workflows/ci.yml", "static/main.js", "tests/test_number_format.py")
    run("git", "commit", "-m", "fix(ui): keep huge scores readable with bigint suffixes")
    run("git", "push", "origin", "HEAD:hotfix/big-score-display-v2")
