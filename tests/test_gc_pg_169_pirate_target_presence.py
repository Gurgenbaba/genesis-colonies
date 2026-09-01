from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_block(text: str, start: str, end: str) -> str:
    a = text.index(start)
    b = text.index(end, a)
    return text[a:b]


def test_pirate_target_candidates_read_effective_presence():
    text = (ROOT / "game" / "pirates" / "brain.py").read_text(encoding="utf-8")
    block = _function_block(text, "def _candidate_planets", "def _planet_military")

    assert "effective_last_seen_scalar_sql" in block
    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="pl")' in block
    assert "{last_seen_expr} AS last_seen" in block
    assert "pl.last_seen" not in block


def test_pirate_spy_intel_opportunity_reads_effective_presence():
    text = (ROOT / "game" / "pirates" / "brain.py").read_text(encoding="utf-8")
    block = _function_block(text, "def ingest_spy_report_for_intel", "def _pick_best_target")

    assert "get_effective_last_seen" in block
    assert "get_effective_last_seen(conn, target_player_id)" in block
    assert "SELECT COALESCE(last_seen, 0) AS last_seen FROM players" not in block
