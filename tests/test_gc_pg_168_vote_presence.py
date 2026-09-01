from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_vote_admin_activity_reads_effective_presence():
    text = (ROOT / "game" / "vote_rewards.py").read_text(encoding="utf-8")
    stats_start = text.index("def build_admin_vote_stats")
    search_start = text.index("def search_admin_vote_players", stats_start)
    stats = text[stats_start:search_start]
    search = text[search_start:]

    assert "effective_last_seen_scalar_sql" in stats
    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in stats
    assert "{last_seen_expr} <= ?" in stats
    assert "{last_seen_expr} AS last_seen" in stats
    assert "COALESCE(p.last_seen, 0)" not in stats

    assert "effective_last_seen_scalar_sql" in search
    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in search
    assert 'where.append(f"{last_seen_expr} > ?")' in search
    assert "{last_seen_expr} AS last_seen" in search
    assert "ORDER BY last_seen DESC" in search
    assert "p.last_seen" not in search
