from __future__ import annotations

from flask import Flask, g

import game.db as dbmod
import game.db_pg as dbpg
import game.models as models


class _Cursor:
    def __init__(self, owner):
        self.owner = owner
        self._rows = []

    def execute(self, sql, params=()):
        self.owner.exec_count += 1
        assert "FROM research_levels" in str(sql)
        uid = int(tuple(params)[0])
        self._rows = [
            {"tech_key": "energy_tech", "level": uid + 1},
            {"tech_key": "navigation_tech", "level": uid + 2},
        ]
        return self

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self):
        self.exec_count = 0

    def cursor(self):
        return _Cursor(self)


def test_pg_research_levels_are_loaded_once_per_request(monkeypatch):
    monkeypatch.setattr(dbmod, "get_db_backend", lambda: "postgres")
    app = Flask(__name__)
    conn = _Conn()

    with app.test_request_context("/api/game-state"):
        first = models.get_research_levels(7, conn=conn)
        second = models.get_research_levels(7, conn=conn)

        assert first == second == {
            "energy_tech": 8,
            "navigation_tech": 9,
        }
        assert conn.exec_count == 1
        assert g.gc_research_levels_cache[7] == first


def test_pg_research_write_invalidates_request_cache():
    app = Flask(__name__)

    with app.test_request_context("/api/research/start"):
        g.gc_research_levels_cache = {7: {"energy_tech": 8}}
        dbpg._invalidate_request_hot_read_caches_for_sql(
            "UPDATE research_levels SET level = ? WHERE user_id = ? AND tech_key = ?;"
        )
        assert g.gc_research_levels_cache == {}


def test_non_postgres_path_does_not_request_cache(monkeypatch):
    monkeypatch.setattr(dbmod, "get_db_backend", lambda: "sqlite")
    app = Flask(__name__)
    conn = _Conn()

    with app.test_request_context("/api/game-state"):
        models.get_research_levels(7, conn=conn)
        models.get_research_levels(7, conn=conn)
        assert conn.exec_count == 2
