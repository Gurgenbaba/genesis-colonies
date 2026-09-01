from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOTE = ROOT / "game" / "vote_rewards.py"
TEST = ROOT / "tests" / "test_gc_pg_168_vote_presence.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


text = VOTE.read_text(encoding="utf-8")
stats_start = text.index("def build_admin_vote_stats")
search_start = text.index("def search_admin_vote_players", stats_start)
prefix = text[:stats_start]
stats = text[stats_start:search_start]
search = text[search_start:]

stats = replace_once(
    stats,
    "    from .ranking import RANKING_INACTIVE_AFTER_SEC, is_player_inactive\n\n",
    "    from .presence_store import effective_last_seen_scalar_sql\n"
    "    from .ranking import RANKING_INACTIVE_AFTER_SEC, is_player_inactive\n\n",
    "stats import",
)
stats = replace_once(
    stats,
    "    channel_expr = _admin_vote_channel_expr(conn)\n",
    "    channel_expr = _admin_vote_channel_expr(conn)\n"
    "    last_seen_expr = effective_last_seen_scalar_sql(player_alias=\"p\")\n",
    "stats expression",
)
stats = replace_once(
    stats,
    "        cur.execute(\n            \"\"\"\n            SELECT COUNT(DISTINCT vr.user_id) AS c\n            FROM vote_rewards vr\n            JOIN players p ON p.id = vr.user_id\n            WHERE vr.voted_at >= ?\n              AND COALESCE(vr.vote_channel, 'player') = 'player'\n              AND COALESCE(p.last_seen, 0) <= ?;\n            \"\"\",",
    "        cur.execute(\n            f\"\"\"\n            SELECT COUNT(DISTINCT vr.user_id) AS c\n            FROM vote_rewards vr\n            JOIN players p ON p.id = vr.user_id\n            WHERE vr.voted_at >= ?\n              AND COALESCE(vr.vote_channel, 'player') = 'player'\n              AND {last_seen_expr} <= ?;\n            \"\"\",",
    "stats channel inactive query",
)
stats = replace_once(
    stats,
    "        cur.execute(\n            \"\"\"\n            SELECT COUNT(DISTINCT vr.user_id) AS c\n            FROM vote_rewards vr\n            JOIN players p ON p.id = vr.user_id\n            WHERE vr.voted_at >= ?\n              AND COALESCE(p.last_seen, 0) <= ?;\n            \"\"\",",
    "        cur.execute(\n            f\"\"\"\n            SELECT COUNT(DISTINCT vr.user_id) AS c\n            FROM vote_rewards vr\n            JOIN players p ON p.id = vr.user_id\n            WHERE vr.voted_at >= ?\n              AND {last_seen_expr} <= ?;\n            \"\"\",",
    "stats legacy inactive query",
)
stats = replace_once(
    stats,
    "    cur.execute(\n        \"\"\"\n        SELECT p.id AS user_id, COALESCE(p.last_seen, 0) AS last_seen\n        FROM players p\n        JOIN users u ON u.id = p.id\n        WHERE COALESCE(p.banned_until, 0) <= ?;\n        \"\"\",",
    "    cur.execute(\n        f\"\"\"\n        SELECT p.id AS user_id, {last_seen_expr} AS last_seen\n        FROM players p\n        JOIN users u ON u.id = p.id\n        WHERE COALESCE(p.banned_until, 0) <= ?;\n        \"\"\",",
    "stats voteable roster query",
)

search = replace_once(
    search,
    "    from .ranking import RANKING_INACTIVE_AFTER_SEC, is_player_inactive\n\n",
    "    from .presence_store import effective_last_seen_scalar_sql\n"
    "    from .ranking import RANKING_INACTIVE_AFTER_SEC, is_player_inactive\n\n",
    "search import",
)
search = replace_once(
    search,
    "    channel_expr = _admin_vote_channel_expr(conn)\n",
    "    channel_expr = _admin_vote_channel_expr(conn)\n"
    "    last_seen_expr = effective_last_seen_scalar_sql(player_alias=\"p\")\n",
    "search expression",
)
search = replace_once(
    search,
    '        where.append("COALESCE(p.last_seen, 0) > ?")',
    '        where.append(f"{last_seen_expr} > ?")',
    "search active filter",
)
search = replace_once(
    search,
    '        where.append("(COALESCE(p.last_seen, 0) <= ? OR COALESCE(p.last_seen, 0) = 0)")',
    '        where.append(f"({last_seen_expr} <= ? OR {last_seen_expr} = 0)")',
    "search inactive filter",
)
search = replace_once(
    search,
    "        SELECT p.id AS user_id, u.username, p.name AS player_name,\n               COALESCE(p.last_seen, 0) AS last_seen",
    "        SELECT p.id AS user_id, u.username, p.name AS player_name,\n               {last_seen_expr} AS last_seen",
    "search select",
)
search = replace_once(
    search,
    "        ORDER BY p.last_seen DESC, p.id ASC",
    "        ORDER BY last_seen DESC, p.id ASC",
    "search ordering",
)

VOTE.write_text(prefix + stats + search, encoding="utf-8")

TEST.write_text(
    '''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_vote_admin_activity_reads_effective_presence():\n    text = (ROOT / "game" / "vote_rewards.py").read_text(encoding="utf-8")\n    stats_start = text.index("def build_admin_vote_stats")\n    search_start = text.index("def search_admin_vote_players", stats_start)\n    stats = text[stats_start:search_start]\n    search = text[search_start:]\n\n    assert "effective_last_seen_scalar_sql" in stats\n    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in stats\n    assert "{last_seen_expr} <= ?" in stats\n    assert "{last_seen_expr} AS last_seen" in stats\n    assert "COALESCE(p.last_seen, 0)" not in stats\n\n    assert "effective_last_seen_scalar_sql" in search\n    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in search\n    assert 'where.append(f"{last_seen_expr} > ?")' in search\n    assert "{last_seen_expr} AS last_seen" in search\n    assert "ORDER BY last_seen DESC" in search\n    assert "p.last_seen" not in search\n''',
    encoding="utf-8",
)

ci = CI.read_text(encoding="utf-8")
ci = replace_once(
    ci,
    "            tests/test_gc_pg_167_autoplay_admin_presence.py \\\n            tests/test_gc_pg_world_boss_readonly_payload.py \\\n",
    "            tests/test_gc_pg_167_autoplay_admin_presence.py \\\n            tests/test_gc_pg_168_vote_presence.py \\\n            tests/test_gc_pg_world_boss_readonly_payload.py \\\n",
    "ci smoke insertion",
)
CI.write_text(ci, encoding="utf-8")

print("GC-PG-168 vote activity reader cutover applied")
