"""GC-RANKING-SCORE-WIDTH-001 — ranking summary must use free desktop width."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ranking_summary_reserves_real_width_for_exact_score():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    assert "GC-RANKING-SCORE-WIDTH-001" in css
    assert "grid-template-columns: minmax(220px, 0.8fr) minmax(520px, 1.6fr)" in css
    assert "grid-template-columns: minmax(130px, max-content) minmax(360px, 1fr)" in css
    assert ".ranking-page .gc-ranking-my-strip > :last-child" in css
    assert "min-width: 360px" in css
    assert "text-overflow: clip" in css
    assert "white-space: nowrap" in css


def test_ranking_summary_keeps_mobile_fallback():
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")
    assert "@media (max-width: 620px)" in css
    assert "grid-template-columns: 1fr" in css
