"""GC-RANKING-SCORE-WIDTH-001 — ranking summary must use free desktop width."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ranking_summary_reserves_real_width_for_exact_score():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    assert "GC-RANKING-SCORE-WIDTH-001" in css
    assert "grid-template-columns: minmax(220px, max-content) minmax(0, 1fr)" in css
    assert "grid-template-columns: minmax(130px, max-content) minmax(0, 1fr)" in css
    assert ".ranking-page .gc-ranking-my-strip > :last-child" in css
    assert "overflow-x: auto" in css
    assert "min-width: max-content" in css
    assert "text-overflow: clip" in css
    assert "white-space: nowrap" in css


def test_ranking_summary_keeps_mobile_fallback():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    assert "@media (max-width: 620px)" in css
    assert "grid-template-columns: 1fr" in css


def test_mando_scale_score_is_not_bound_to_a_fixed_pixel_width():
    score = "597.896.256.410.121.067.032"
    assert len(score) > 20
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    score_block = css.split(".ranking-page .gc-ranking-my-strip > :last-child", 1)[1].split("}", 1)[0]
    number_block = css.split(".ranking-page .gc-ranking-my-strip .gc-ranking-num-full", 1)[1].split("}", 1)[0]
    assert "min-width: 360px" not in score_block
    assert "max-width:" not in score_block
    assert "overflow-x: auto" in score_block
    assert "min-width: max-content" in number_block
