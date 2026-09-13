from __future__ import annotations

from scripts.run_game_worker import _queue_tick_has_retryable_db_conflict


def test_queue_worker_retries_postgres_deadlock_result():
    result = {
        "ok": False,
        "errors": [
            "build planet=292 player=2: deadlock detected\n"
            "DETAIL: Process 40072 waits for ShareLock"
        ],
    }
    assert _queue_tick_has_retryable_db_conflict(result) is True


def test_queue_worker_does_not_retry_ordinary_finish_errors():
    assert _queue_tick_has_retryable_db_conflict(
        {"ok": False, "errors": ["research user=7: invalid queue state"]}
    ) is False
    assert _queue_tick_has_retryable_db_conflict({"ok": True, "errors": []}) is False


def test_queue_worker_retry_contract_stays_single_and_bounded():
    src = __import__("pathlib").Path("scripts/run_game_worker.py").read_text(encoding="utf-8")
    assert "if args.queue_only and _queue_tick_has_retryable_db_conflict(result):" in src
    assert "time.sleep(0.075)" in src
    assert "retry_result = _tick()" in src
    # No loop around the recovery attempt: one deadlock -> at most one immediate rescan.
    retry_block = src.split(
        "if args.queue_only and _queue_tick_has_retryable_db_conflict(result):", 1
    )[1].split("heartbeat_persisted = False", 1)[0]
    assert retry_block.count("_tick()") == 1
