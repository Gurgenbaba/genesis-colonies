"""One-shot GC-FLEET-PG-ABORT-001 production hotfix."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 1) Timekeeper/inventory queue settling must not process unrelated fleet work.
inv_path = ROOT / "game" / "inventory_use.py"
inv = inv_path.read_text(encoding="utf-8")
old_inv = '''    from .queue_engine import finish_due_work_once
    from .queue_poll import player_has_due_queue_work

    uid = int(user_id)
    pid = int(planet_id) if planet_id is not None else None
    last_result: Dict[str, Any] = {"ok": True, "errors": []}
    for pass_idx in range(_INVENTORY_FINISH_PASSES):
        result = finish_due_work_once(
            uid,
            pid,
            conn=conn,
            source=source if pass_idx == 0 else f"{source}_retry",
            dedup=False,
            recalc_ranks=False,
            update_scores=False,
            manage_transaction=False,
        )
'''
new_inv = '''    from .queue_engine import finish_due_work
    from .queue_poll import player_has_due_queue_work

    uid = int(user_id)
    pid = int(planet_id) if planet_id is not None else None
    last_result: Dict[str, Any] = {"ok": True, "errors": []}
    for pass_idx in range(_INVENTORY_FINISH_PASSES):
        # GC-FLEET-PG-ABORT-001: inventory/Timekeeper settles economy queues
        # only. Fleet movement completion belongs to the dedicated Fleet owner;
        # running it here widens the planet lock and races expedition holding.
        result = finish_due_work(
            uid,
            pid,
            conn=conn,
            source=source if pass_idx == 0 else f"{source}_retry",
            recalc_ranks=False,
            update_scores=False,
            manage_transaction=False,
            include_fleet=False,
            include_relocations=False,
        )
'''
if inv.count(old_inv) != 1:
    raise SystemExit("inventory queue-finisher anchor mismatch")
inv_path.write_text(inv.replace(old_inv, new_inv), encoding="utf-8")

# 2) Shared fleet processing must recover the caller transaction after every
# movement failure. PostgreSQL marks a transaction aborted after lock timeout;
# catching Python exceptions alone is not sufficient.
fleet_path = ROOT / "game" / "fleet.py"
fleet = fleet_path.read_text(encoding="utf-8")
anchor = '''def _process_fleet_tick_shared_tx(
    conn,
    *,
    player_id: Optional[int],
    now: float,
    result: Dict[str, Any],
) -> None:
    """Legacy path: all due work on the caller's open write transaction."""
'''
helper = '''def _run_shared_fleet_step(conn, *, phase: str, movement_id: int, fn):
    """Isolate one movement inside a caller-owned transaction.

    PostgreSQL leaves the whole transaction aborted after a statement timeout or
    lock timeout. A movement-level SAVEPOINT lets the shared fallback recover
    only that movement and continue processing later fleets safely.
    """
    safe_phase = str(phase or "movement").replace("-", "_")
    savepoint = f"gc_fleet_{safe_phase}_{int(movement_id)}"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        out = fn()
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return out
    except Exception:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            logger.exception(
                "fleet shared savepoint recovery failed phase=%s fleet=%s",
                phase,
                movement_id,
            )
        raise


''' + anchor
if fleet.count(anchor) != 1:
    raise SystemExit("fleet shared-tx anchor mismatch")
fleet = fleet.replace(anchor, helper, 1)
replacements = {
    '''            if _handle_arrival(mv, conn=conn, now=now):
                result["processed_arrivals"] += 1
''': '''            if _run_shared_fleet_step(
                conn,
                phase="arrival",
                movement_id=int(mv["id"]),
                fn=lambda: _handle_arrival(mv, conn=conn, now=now),
            ):
                result["processed_arrivals"] += 1
''',
    '''            if _handle_holding_end(mv, conn=conn, now=now):
                result["processed_holding"] += 1
''': '''            if _run_shared_fleet_step(
                conn,
                phase="holding",
                movement_id=int(mv["id"]),
                fn=lambda: _handle_holding_end(mv, conn=conn, now=now),
            ):
                result["processed_holding"] += 1
''',
    '''            if _handle_return(mv, conn=conn, now=now):
                result["processed_returns"] += 1
''': '''            if _run_shared_fleet_step(
                conn,
                phase="return",
                movement_id=int(mv["id"]),
                fn=lambda: _handle_return(mv, conn=conn, now=now),
            ):
                result["processed_returns"] += 1
''',
}
for old, new in replacements.items():
    if fleet.count(old) != 1:
        raise SystemExit(f"fleet movement anchor mismatch: {old.splitlines()[0]!r}")
    fleet = fleet.replace(old, new, 1)
fleet_path.write_text(fleet, encoding="utf-8")

# 3) Put the regression in the fast deploy smoke gate.
ci_path = ROOT / ".github" / "workflows" / "ci.yml"
ci = ci_path.read_text(encoding="utf-8")
old_ci = "tests/test_fleet_worker.py tests/test_gc_perf_tk_005.py tests/test_gc_tk_atomic_delivery_001.py tests/test_gc_perf_fleet_write_001.py"
new_ci = "tests/test_fleet_worker.py tests/test_gc_fleet_pg_abort_001.py tests/test_gc_perf_tk_005.py tests/test_gc_tk_atomic_delivery_001.py tests/test_gc_perf_fleet_write_001.py"
if ci.count(old_ci) != 1:
    raise SystemExit("CI smoke anchor mismatch")
ci_path.write_text(ci.replace(old_ci, new_ci, 1), encoding="utf-8")
