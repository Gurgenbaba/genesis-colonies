from __future__ import annotations

from flask import Flask, g


def test_planet_buildings_pg_request_cache_collapses_repeat_reads(monkeypatch):
    from game import db as db_module
    from game import models

    app = Flask(__name__)
    monkeypatch.setattr(db_module, "get_db_backend", lambda: "postgres")

    class Cursor:
        def __init__(self):
            self.calls = 0

        def execute(self, sql, params=()):
            assert "SELECT * FROM planet_buildings" in str(sql)
            self.calls += 1
            return self

        def fetchone(self):
            return {"planet_id": 7, "metal_mine": 33, "crystal_mine": 21}

    class Conn:
        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

    conn = Conn()
    with app.test_request_context("/api/game-state"):
        a = models.get_planet_buildings(7, conn=conn)
        a["metal_mine"] = 999
        b = models.get_planet_buildings(7, conn=conn)

    assert conn.cur.calls == 1
    assert b["metal_mine"] == 33


def test_planet_row_pg_request_cache_collapses_repeat_reads(monkeypatch):
    from game import db as db_module
    from game.planet_evolution import repository

    app = Flask(__name__)
    monkeypatch.setattr(db_module, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(repository, "get_db_backend", lambda: "postgres")

    class Cursor:
        def __init__(self):
            self.calls = 0

        def execute(self, sql, params=()):
            assert "SELECT * FROM planets WHERE id = ?" in str(sql)
            self.calls += 1
            return self

        def fetchone(self):
            return {"id": 44, "player_id": 3, "metal": 123}

    class Conn:
        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

    conn = Conn()
    with app.test_request_context("/overview"):
        a = repository.get_planet_row(44, conn=conn)
        a["metal"] = 999
        b = repository.get_planet_row(44, conn=conn)

    assert conn.cur.calls == 1
    assert b["metal"] == 123


def test_active_planet_id_pg_request_cache_collapses_context_checks(monkeypatch):
    from game import db as db_module
    from game.planet_evolution import repository

    app = Flask(__name__)
    monkeypatch.setattr(db_module, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(repository, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(repository, "table_exists", lambda _conn, table: table == "player_context")
    monkeypatch.setattr(repository, "column_exists", lambda *_args, **_kwargs: False)

    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=()):
            self.calls.append(str(sql))
            return self

        def fetchone(self):
            sql = self.calls[-1]
            if "FROM player_context" in sql:
                return {"active_planet_id": 44}
            if "FROM planets WHERE id" in sql:
                return {"id": 44}
            return None

    class Conn:
        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

    conn = Conn()
    with app.test_request_context("/api/game-state"):
        assert repository.get_active_planet_id(3, conn=conn) == 44
        assert repository.get_active_planet_id(3, conn=conn) == 44

    assert len(conn.cur.calls) == 2


def test_commander_pg_request_cache_collapses_row_and_skill_reads(monkeypatch):
    from game import db as db_module
    from game import commander_classes as commander

    app = Flask(__name__)
    monkeypatch.setattr(db_module, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(commander, "schema_ready", lambda _conn: True)

    class Cursor:
        def __init__(self):
            self.sql = ""
            self.row_calls = 0
            self.skill_calls = 0

        def execute(self, sql, params=()):
            self.sql = str(sql)
            if "FROM player_commander WHERE" in self.sql:
                self.row_calls += 1
            if "FROM player_commander_skills WHERE" in self.sql:
                self.skill_calls += 1
            return self

        def fetchone(self):
            return {
                "player_id": 5,
                "class_key": "vanguard",
                "chosen_at": 1,
                "swap_count": 0,
                "skill_points_unspent": 2,
                "skill_points_earned": 2,
                "updated_at": 1,
            }

        def fetchall(self):
            return [{"skill_key": "vanguard_armor", "rank": 2}]

    class Conn:
        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

    conn = Conn()
    with app.test_request_context("/api/game-state"):
        assert commander._read_commander_row(5, conn=conn)["class_key"] == "vanguard"
        assert commander._read_commander_row(5, conn=conn)["class_key"] == "vanguard"
        assert commander.get_skill_ranks(5, conn=conn)["vanguard_armor"] == 2
        assert commander.get_skill_ranks(5, conn=conn)["vanguard_armor"] == 2

    assert conn.cur.row_calls == 1
    assert conn.cur.skill_calls == 1


def test_directive_catalog_connection_does_not_force_reload(monkeypatch):
    from game.galactic_directives import definitions

    previous = dict(definitions._CACHE)
    calls = {"n": 0}

    def fake_reload(conn=None):
        calls["n"] += 1
        definitions._CACHE["directives"] = {}
        definitions._CACHE["loaded"] = True

    try:
        definitions._CACHE["directives"] = {}
        definitions._CACHE["loaded"] = False
        monkeypatch.setattr(definitions, "reload_definitions", fake_reload)
        definitions._ensure_loaded(conn=object())
        definitions._ensure_loaded(conn=object())
        assert calls["n"] == 1
    finally:
        definitions._CACHE.clear()
        definitions._CACHE.update(previous)


def test_pg_write_invalidator_clears_entity_request_memos():
    from game.db_pg import _invalidate_request_hot_read_caches_for_sql

    app = Flask(__name__)
    with app.test_request_context("/api/action"):
        g.gc_planet_buildings_cache = {7: {"metal_mine": 3}}
        g.gc_planet_row_cache = {7: {"id": 7}}
        g.gc_context_planet_cache = {3: {"id": 7}}
        g.gc_active_planet_id_cache = {3: 7}
        g.gc_commander_row_cache = {3: {"class_key": "vanguard"}}
        g.gc_commander_skills_cache = {3: {"vanguard_armor": 2}}

        _invalidate_request_hot_read_caches_for_sql(
            "UPDATE planet_buildings SET metal_mine = ? WHERE planet_id = ?"
        )
        assert g.gc_planet_buildings_cache == {}

        _invalidate_request_hot_read_caches_for_sql(
            "UPDATE planets SET metal = ? WHERE id = ?"
        )
        assert g.gc_planet_row_cache == {}
        assert g.gc_context_planet_cache == {}
        assert g.gc_active_planet_id_cache == {}

        g.gc_context_planet_cache = {3: {"id": 7}}
        g.gc_active_planet_id_cache = {3: 7}
        _invalidate_request_hot_read_caches_for_sql(
            "UPDATE player_context SET active_planet_id = ? WHERE player_id = ?"
        )
        assert g.gc_context_planet_cache == {}
        assert g.gc_active_planet_id_cache == {}

        _invalidate_request_hot_read_caches_for_sql(
            "UPDATE player_commander_skills SET rank = ? WHERE player_id = ?"
        )
        assert g.gc_commander_row_cache == {}
        assert g.gc_commander_skills_cache == {}


def test_battle_pass_op_success_skips_expensive_hud_live_state():
    src = open("app.py", "r", encoding="utf-8").read()
    block = src.split("def api_battle_pass_claim_op():", 1)[1].split(
        '@app.route("/api/admin/battle-pass/unlock-premium"',
        1,
    )[0]
    success = block.split("if ok:", 2)[2].split("else:", 1)[0]
    assert "state = {}" in success
    assert "_hud_only_game_state" not in success
    assert "conn2 = db()" not in success
    assert '(claim_result or {}).get("battle_pass")' in success


def test_mine_evolution_pg_request_cache_batches_rank_reads(monkeypatch):
    from game import db as db_module
    from game.mine_evolution import service

    app = Flask(__name__)
    monkeypatch.setattr(db_module, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(service, "schema_ready", lambda _conn: True)

    class Cursor:
        def __init__(self):
            self.calls = 0

        def execute(self, sql, params=()):
            assert "SELECT building_type, evolution_rank FROM planet_mine_evolution" in str(sql)
            self.calls += 1
            return self

        def fetchall(self):
            return [
                {"building_type": "metal_mine", "evolution_rank": 2},
                {"building_type": "crystal_mine", "evolution_rank": 1},
            ]

    class Conn:
        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

    conn = Conn()
    with app.test_request_context("/overview"):
        assert service.get_evolution_rank(7, "metal_mine", conn=conn) == 2
        assert service.get_evolution_rank(7, "crystal_mine", conn=conn) == 1
        assert service.get_evolution_rank(7, "fuel_cell_plant", conn=conn) == 0

    assert conn.cur.calls == 1


def test_pg_write_invalidator_clears_mine_rank_memo():
    from game.db_pg import _invalidate_request_hot_read_caches_for_sql

    app = Flask(__name__)
    with app.test_request_context("/api/buildings/mine-evolve"):
        g.gc_mine_evolution_ranks_cache = {7: {"metal_mine": 2}}
        _invalidate_request_hot_read_caches_for_sql(
            "UPDATE planet_mine_evolution SET evolution_rank = ? WHERE planet_id = ?"
        )
        assert g.gc_mine_evolution_ranks_cache == {}
