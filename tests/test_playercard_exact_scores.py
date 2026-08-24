from pathlib import Path

from game.number_format import fmt_int


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "partials" / "player_card_view.html"


def test_playercard_full_score_formatter_handles_live_scale_without_scientific_notation():
    value = 4_380_535_014_898_023
    rendered = fmt_int(value)
    assert rendered == "4.380.535.014.898.023"
    assert "e" not in rendered.lower()


def test_playercard_score_fields_render_full_exact_values_only():
    source = TEMPLATE.read_text(encoding="utf-8")
    score_keys = (
        "score_total",
        "score_buildings",
        "score_research",
        "score_fleet",
        "score_defense",
    )

    for key in score_keys:
        lines = [line for line in source.splitlines() if f"card.get('{key}')" in line]
        assert lines, key
        assert any("|fmt_int" in line and "|fmt_int_compact" not in line for line in lines), key
        assert all("gc-num-compact" not in line for line in lines), key


def test_playercard_score_layout_gives_exact_values_more_space():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "gc-player-card-stat--score" in source
    assert "gc-player-card-stat-value--exact" in source
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in source
    assert "font-variant-numeric: tabular-nums;" in source
    assert "white-space: nowrap;" in source
    assert "overflow-x: auto;" in source
    assert "grid-template-columns: 1fr;" in source
