"""GC-PG-177 — message trade filter must be safe for psycopg placeholders."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_trade_category_uses_bound_like_patterns():
    from game.messages import _category_clause

    sql, params = _category_clause("trade")
    assert "category = 'system'" in sql
    assert sql.count("metadata_json LIKE ?") == 5
    assert "%" not in sql
    assert params == [
        '%"mission_type":"transport"%',
        '%"mission_type":"collect"%',
        '%"mission_type":"deploy"%',
        '%"mission_type":"recycle"%',
        '%"report_phase"%',
    ]


def test_trade_category_pg_rewrite_contains_only_psycopg_placeholders():
    from game.db_pg import rewrite_sqlite_placeholders
    from game.messages import _category_clause

    sql, params = _category_clause("trade")
    rewritten = rewrite_sqlite_placeholders(sql)
    assert rewritten.count("%s") == 5
    assert rewritten.count("%") == 5
    assert len(params) == 5


def test_source_has_no_literal_trade_like_wildcards_in_sql():
    src = (ROOT / "game/messages.py").read_text(encoding="utf-8")
    block = src.split('if cat == "trade":', 1)[1].split('if cat in VALID_CATEGORIES:', 1)[0]
    assert 'metadata_json LIKE \'%"' not in block
    assert '" OR ".join("metadata_json LIKE ?" for _ in patterns)' in block
