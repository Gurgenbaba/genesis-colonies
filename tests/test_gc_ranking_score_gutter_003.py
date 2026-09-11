"""GC-RANKING-SCORE-GUTTER-003 — keep arbitrary-precision totals clear of the right edge."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_score_column_reserves_space_and_right_gutter():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    block = css.split("GC-RANKING-SCORE-GUTTER-003", 1)[1].split("}", 1)[0]
    assert "min-width: 380px" in block
    assert "padding-right: 28px" in block


def test_smaller_desktops_relax_the_score_column_without_truncation():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    assert "@media (max-width: 1180px)" in css
    assert "min-width: 300px" in css
    assert "padding-right: 18px" in css
    assert "white-space: nowrap" in css
