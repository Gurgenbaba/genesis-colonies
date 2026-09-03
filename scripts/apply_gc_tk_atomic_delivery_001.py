"""One-shot GC-TK-ATOMIC-DELIVERY-001 patch helper."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 1) Make inventory due-finisher surface queue-engine status to callers.
inv_path = ROOT / "game" / "inventory_use.py"
inv = inv_path.read_text(encoding="utf-8")
old = '''def _finish_inventory_due_work(
    conn,
    user_id: int,
    *,
    planet_id: Optional[int] = None,
    source: str = "inventory_use",
) -> None:
    """Finish due queue work on the passed connection — never opens a second conn."""
    from .queue_engine import finish_due_work_once
    from .queue_poll import player_has_due_queue_work

    uid = int(user_id)
    pid = int(planet_id) if planet_id is not None else None
    for pass_idx in range(_INVENTORY_FINISH_PASSES):
        finish_due_work_once(
            uid,
            pid,
            conn=conn,
            source=source if pass_idx == 0 else f"{source}_retry",
            dedup=False,
            recalc_ranks=False,
            update_scores=False,
            manage_transaction=False,
        )
        if pid is not None:
            if not player_has_due_queue_work(uid, conn=conn, planet_id=pid):
                break
        elif not player_has_due_queue_work(uid, conn=conn):
            break
'''
new = '''def _finish_inventory_due_work(
    conn,
    user_id: int,
    *,
    planet_id: Optional[int] = None,
    source: str = "inventory_use",
) -> Dict[str, Any]:
    """Finish due queue work and surface the final queue-engine result.

    Existing inventory callers may ignore the return value. Mutation paths such
    as Timekeeper use it to prevent consuming value when a due delivery failed.
    """
    from .queue_engine import finish_due_work_once
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
        if isinstance(result, dict):
            last_result = result
        if pid is not None:
            if not player_has_due_queue_work(uid, conn=conn, planet_id=pid):
                break
        elif not player_has_due_queue_work(uid, conn=conn):
            break
    return last_result
'''
if inv.count(old) != 1:
    raise SystemExit("inventory finisher anchor mismatch")
inv = inv.replace(old, new)
inv_path.write_text(inv, encoding="utf-8")

# 2) Serialize planet-scoped TK with queue worker + rollback shift/debit/delivery atomically.
tk_path = ROOT / "game" / "timekeeper.py"
tk = tk_path.read_text(encoding="utf-8")
if "from .db import table_exists" not in tk:
    raise SystemExit("timekeeper db import anchor mismatch")
tk = tk.replace(
    "from .db import table_exists",
    "from .db import lock_planet_for_update, table_exists",
    1,
)

finish_old = '''def _finish_before_apply(conn, user_id: int, planet_id: Optional[int]) -> None:
    from .inventory_use import _finish_inventory_due_work

    uid = int(user_id)
    if planet_id is not None:
        _finish_inventory_due_work(conn, uid, planet_id=int(planet_id), source="timekeeper_apply")
    else:
        _finish_inventory_due_work(conn, uid, source="timekeeper_apply")
'''
finish_new = '''def _finish_before_apply(conn, user_id: int, planet_id: Optional[int]) -> Dict[str, Any]:
    from .inventory_use import _finish_inventory_due_work

    uid = int(user_id)
    if planet_id is not None:
        result = _finish_inventory_due_work(
            conn, uid, planet_id=int(planet_id), source="timekeeper_apply"
        )
    else:
        result = _finish_inventory_due_work(conn, uid, source="timekeeper_apply")
    return dict(result or {"ok": True, "errors": []})


def _tk_savepoint_begin(conn) -> None:
    conn.execute("SAVEPOINT gc_tk_apply")


def _tk_savepoint_release(conn) -> None:
    conn.execute("RELEASE SAVEPOINT gc_tk_apply")


def _tk_savepoint_rollback(conn) -> None:
    conn.execute("ROLLBACK TO SAVEPOINT gc_tk_apply")
    conn.execute("RELEASE SAVEPOINT gc_tk_apply")
'''
if tk.count(finish_old) != 1:
    raise SystemExit("timekeeper finish helper anchor mismatch")
tk = tk.replace(finish_old, finish_new)

balance_old = '''    balance = get_balance(uid, conn=conn)
    if balance <= 0:
        return False, "insufficient_timekeeper", {"timekeeper": serialize_for_client(uid, conn=conn)}

    now = float(time.time())
    _finish_before_apply(conn, uid, pid if pid > 0 else None)
    rows, finish_col = _load_domain_rows(dom, uid, pid, conn=conn, now=now)
'''
balance_new = '''    # GC-TK-ATOMIC-DELIVERY-001: every planet-scoped TK mutation takes the
    # canonical planet lock before touching queue rows. Shipyard/worker actions
    # use the same lock, so the background worker can SKIP LOCKED instead of
    # racing a boost and timing out later on queue/inventory rows.
    if pid > 0:
        lock_planet_for_update(conn, pid)

    balance = get_balance(uid, conn=conn)
    if balance <= 0:
        return False, "insufficient_timekeeper", {"timekeeper": serialize_for_client(uid, conn=conn)}

    now = float(time.time())
    pre_finish = _finish_before_apply(conn, uid, pid if pid > 0 else None)
    if pre_finish.get("ok") is False:
        return False, "queue_finish_failed", {
            "errors": list(pre_finish.get("errors") or [])[:5],
            "timekeeper": serialize_for_client(uid, conn=conn),
        }
    rows, finish_col = _load_domain_rows(dom, uid, pid, conn=conn, now=now)
'''
if tk.count(balance_old) != 1:
    raise SystemExit("timekeeper pre-apply anchor mismatch")
tk = tk.replace(balance_old, balance_new)

mutation_old = '''    effect = _apply_domain_shift(
        dom,
        uid,
        pid,
        boost_seconds,
        conn=conn,
        now=now,
        rows=rows,
        finish_col_override=finish_col,
    )

    if not effect:
        return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

    shifted = int(effect.get("seconds_shifted") or 0)
    if shifted <= 0:
        return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

    try:
        new_bal = debit(uid, shifted, f"apply:{dom}", conn=conn)
    except InsufficientTimekeeperBalance:
        return False, "insufficient_timekeeper", {"timekeeper": serialize_for_client(uid, conn=conn)}

    _finish_before_apply(conn, uid, pid if pid > 0 else None)

    # GC-TK-PANEL-REFRESH-001: detect real head completion (not rem/shift rounding).
    now_after = float(time.time())
    rows_after, _ = _load_domain_rows(dom, uid, pid, conn=conn, now=now_after)
    head_id_after = _row_field(rows_after[0], "id") if rows_after else None
    jobs_finished = head_id_before is not None and head_id_before != head_id_after

    return True, "ok", {
        "timekeeper": serialize_for_client(uid, conn=conn),
        "domain": dom,
        "seconds_applied": shifted,
        "seconds_requested": boost_seconds,
        "mode": str(mode or "partial"),
        "jobs_finished": bool(jobs_finished),
    }
'''
mutation_new = '''    # Queue shift, resulting due delivery, and TK debit form one savepoint.
    # Even if the outer caller later commits after a handled failure, the player
    # can never receive a free shift or lose TK without the authoritative finish.
    _tk_savepoint_begin(conn)
    try:
        effect = _apply_domain_shift(
            dom,
            uid,
            pid,
            boost_seconds,
            conn=conn,
            now=now,
            rows=rows,
            finish_col_override=finish_col,
        )

        if not effect:
            _tk_savepoint_rollback(conn)
            return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

        shifted = int(effect.get("seconds_shifted") or 0)
        if shifted <= 0:
            _tk_savepoint_rollback(conn)
            return False, "no_effect", {"timekeeper": serialize_for_client(uid, conn=conn)}

        post_finish = _finish_before_apply(conn, uid, pid if pid > 0 else None)
        if post_finish.get("ok") is False:
            _tk_savepoint_rollback(conn)
            return False, "queue_finish_failed", {
                "errors": list(post_finish.get("errors") or [])[:5],
                "timekeeper": serialize_for_client(uid, conn=conn),
            }

        try:
            new_bal = debit(uid, shifted, f"apply:{dom}", conn=conn)
        except InsufficientTimekeeperBalance:
            _tk_savepoint_rollback(conn)
            return False, "insufficient_timekeeper", {
                "timekeeper": serialize_for_client(uid, conn=conn)
            }

        # GC-TK-PANEL-REFRESH-001: detect real head completion (not rem/shift rounding).
        now_after = float(time.time())
        rows_after, _ = _load_domain_rows(dom, uid, pid, conn=conn, now=now_after)
        head_id_after = _row_field(rows_after[0], "id") if rows_after else None
        jobs_finished = head_id_before is not None and head_id_before != head_id_after
        _tk_savepoint_release(conn)
    except Exception:
        try:
            _tk_savepoint_rollback(conn)
        except Exception:
            pass
        raise

    return True, "ok", {
        "timekeeper": serialize_for_client(uid, conn=conn),
        "domain": dom,
        "seconds_applied": shifted,
        "seconds_requested": boost_seconds,
        "mode": str(mode or "partial"),
        "jobs_finished": bool(jobs_finished),
    }
'''
if tk.count(mutation_old) != 1:
    raise SystemExit("timekeeper mutation anchor mismatch")
tk = tk.replace(mutation_old, mutation_new)
tk_path.write_text(tk, encoding="utf-8")
