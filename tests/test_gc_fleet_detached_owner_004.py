from __future__ import annotations

import inspect

from flask import Flask, g

from game import admin_api
from game import db as dbmod
from game import fleet


class _Conn:
    pass


def test_db_detached_bypasses_request_pinned_postgres_checkout(monkeypatch):
    import game.db_pg as db_pg

    app = Flask(__name__)
    pinned = _Conn()
    fresh = _Conn()
    monkeypatch.setattr(dbmod, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(db_pg, "connect_postgres", lambda: fresh)

    with app.test_request_context("/"):
        g.gc_pg_request_connection = pinned
        out = dbmod.db_detached()
        assert out is fresh
        assert g.gc_pg_request_connection is pinned


def test_online_fleet_safety_net_uses_detached_owner():
    source = inspect.getsource(fleet.process_player_due_fleets_now)
    assert "db_detached" in source
    assert "conn = db_detached()" in source
    assert "conn=conn" in source
    assert "manage_transaction=True" in source


def test_admin_force_advance_is_selected_short_tx_not_generic_tick():
    source = inspect.getsource(fleet.admin_advance_fleet_movement)
    assert "_run_one_movement_short_tx(" in source
    assert "process_fleet_tick(" not in source
    assert "UPDATE fleet_movements SET arrival_at" not in source


def test_admin_api_does_not_wrap_fleet_owner_in_request_transaction():
    source = inspect.getsource(admin_api.advance_admin_fleet)
    assert "admin_advance_fleet_movement_owned" in source
    assert "begin_write_transaction" not in source
    assert "commit(" not in source
    assert "rollback(" not in source
