from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_autoplay_admin_reads_effective_presence():
    text = (ROOT / "game" / "inactive_autoplay_admin.py").read_text(encoding="utf-8")
    block = text[text.index("def build_admin_inactive_autoplay_payload"):text.index("def admin_set_inactive_autoplay")]

    assert "effective_last_seen_scalar_sql" in block
    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in block
    assert "AND {last_seen_expr} >= ?" in block
    assert "{last_seen_expr} AS last_seen" in block
    assert "WHERE id IN ({placeholders}) AND last_seen >= ?" not in block
    assert "p.last_seen AS last_seen" not in block
