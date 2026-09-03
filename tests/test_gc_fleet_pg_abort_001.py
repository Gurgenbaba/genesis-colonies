"""GC-FLEET-PG-ABORT-001 regression gates."""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from game import fleet
from game import inventory_use


class _PgAbortProbe:
    """Tiny state machine matching PostgreSQL's aborted-TX behavior."""

    def __init__(self) -> None:
        self.aborted = False
        self.commands: list[str] = []

    def execute(self, sql: str):
        command = str(sql).strip()
        self.commands.append(command)
        upper = command.upper()
        if self.aborted:
            if upper.startswith("ROLLBACK TO SAVEPOINT"):
                self.aborted = False
                return self
            raise RuntimeError("current transaction is aborted")
        return self

    def poison_with_lock_timeout(self) -> None:
        self.aborted = True
        raise RuntimeError("canceling statement due to lock timeout")


def test_shared_fleet_step_recovers_postgres_aborted_transaction():
    conn = _PgAbortProbe()

    with pytest.raises(RuntimeError, match="lock timeout"):
        fleet._run_shared_fleet_step(
            conn,
            phase="holding",
            movement_id=43344,
            fn=conn.poison_with_lock_timeout,
        )

    assert conn.aborted is False
    assert conn.commands == [
        "SAVEPOINT gc_fleet_holding_43344",
        "ROLLBACK TO SAVEPOINT gc_fleet_holding_43344",
        "RELEASE SAVEPOINT gc_fleet_holding_43344",
    ]

    # This is the exact property missing in production: the next fleet/query
    # must run on a healthy transaction instead of InFailedSqlTransaction.
    conn.execute("SELECT 1")


def test_shared_fleet_step_rolls_back_partial_movement_changes_sqlite():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE probe (value INTEGER NOT NULL)")
    conn.commit()
    conn.execute("BEGIN")

    def _partial_then_fail():
        conn.execute("INSERT INTO probe(value) VALUES (1)")
        raise RuntimeError("movement failed")

    with pytest.raises(RuntimeError, match="movement failed"):
        fleet._run_shared_fleet_step(
            conn,
            phase="return",
            movement_id=7,
            fn=_partial_then_fail,
        )

    assert conn.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == 0
    conn.execute("INSERT INTO probe(value) VALUES (2)")
    conn.commit()
    assert conn.execute("SELECT value FROM probe").fetchall() == [(2,)]
    conn.close()


def test_inventory_timekeeper_finish_does_not_process_fleet_side_effects():
    source = inspect.getsource(inventory_use._finish_inventory_due_work)
    assert "from .queue_engine import finish_due_work" in source
    assert "include_fleet=False" in source
    assert "include_relocations=False" in source
    assert "finish_due_work_once" not in source


def test_shared_fleet_path_isolates_all_three_movement_phases():
    source = inspect.getsource(fleet._process_fleet_tick_shared_tx)
    assert source.count("_run_shared_fleet_step(") == 3
    assert 'phase="arrival"' in source
    assert 'phase="holding"' in source
    assert 'phase="return"' in source
