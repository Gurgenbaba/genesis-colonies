"""GC-DB-POSTGRES-001 Phase 1 — migrate wrapper TX detection regression."""

from __future__ import annotations

from migrate import _contains_explicit_transaction, _split_sql_statements


def test_committed_column_name_does_not_suppress_wrapper_tx() -> None:
    """Regression: forge_cores_committed must not match \\bCOMMIT\\b."""
    sql = """
    CREATE TABLE IF NOT EXISTS player_forge_cores (
        player_id INTEGER NOT NULL PRIMARY KEY,
        forge_cores_committed INTEGER NOT NULL DEFAULT 0
    );
    """
    stmts = [s.strip() for s in _split_sql_statements(sql) if s.strip()]
    assert _contains_explicit_transaction(stmts) is False


def test_explicit_commit_still_detected() -> None:
    sql = "BEGIN;\nUPDATE t SET x=1;\nCOMMIT;"
    stmts = [s.strip() for s in _split_sql_statements(sql) if s.strip()]
    assert _contains_explicit_transaction(stmts) is True
