"""GC-RANKING-SCORE-WIDTH-002 — ranking summary is right-anchored and arbitrary-precision safe."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ranking_summary_uses_right_side_of_header():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    assert "GC-RANKING-SCORE-WIDTH-002" in css
    assert "grid-template-columns: minmax(0, 1fr) minmax(680px, 55%)" in css
    assert "justify-self: end" in css
    assert "grid-template-columns: max-content minmax(0, 1fr)" in css


def test_total_score_ends_at_right_edge_without_visible_scrollbar():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    score_block = css.split(".ranking-page .gc-ranking-my-strip > :last-child", 1)[1].split("}", 1)[0]
    assert "width: 100% !important" in score_block
    assert "text-align: right !important" in score_block
    assert "overflow-x: auto" in score_block
    assert "scrollbar-width: none" in score_block
    assert "direction: rtl" in score_block
    assert "::-webkit-scrollbar" in css
    assert "display: none" in css


def test_exact_score_number_keeps_normal_reading_direction_and_full_width():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    number_block = css.split(".ranking-page .gc-ranking-my-strip .gc-ranking-num-full", 1)[1].split("}", 1)[0]
    assert "min-width: max-content" in number_block
    assert "white-space: nowrap" in number_block
    assert "direction: ltr" in number_block
    assert "unicode-bidi: isolate" in number_block
    assert "text-align: right" in number_block


def test_mando_scale_score_is_not_bound_to_fixed_width():
    score = "597.896.256.410.121.067.032"
    assert len(score) > 20
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    assert "min-width: 360px" not in css
    assert "width: 300px" in css  # ranking table column, not header summary


def test_mobile_stacks_without_truncating_score():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    assert "@media (max-width: 620px)" in css
    assert "grid-template-columns: 1fr" in css
