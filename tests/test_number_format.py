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
