"""/news returned HTTP 500 on PostgreSQL: a literal ``%`` inside a query that also has
bound parameters is read by psycopg as a placeholder. Bind LIKE patterns instead.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.pg_fixtures import requires_postgres

ROOT = Path(__file__).resolve().parents[1]
# SQLite-only statement without bound parameters.
ALLOWED = {("game/schema_bootstrap.py", "sqlite_%")}
LITERAL_LIKE = re.compile(r"""LIKE\s+'([^'?]*%[^']*)'""", re.IGNORECASE)


def test_no_inline_percent_like_literals_in_sql():
    offenders = []
    files = [ROOT / "app.py", *sorted((ROOT / "game").rglob("*.py"))]
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        for match in LITERAL_LIKE.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            if (rel, match.group(1)) not in ALLOWED:
                offenders.append((rel, match.group(1)))
    assert not offenders, (
        "Inline LIKE '...%...' literals break on PostgreSQL when the query has bound "
        f"parameters; pass the pattern as a parameter: {offenders}"
    )


@requires_postgres
def test_news_page_and_sidebar_release_run_on_postgres(pg_parity_db):
    from game.universe_news import news_page_payload, sidebar_release_nav

    nav = sidebar_release_nav()
    assert isinstance(nav, dict) and nav.get("href")
    payload = news_page_payload(locale="de")
    assert isinstance(payload, dict)
