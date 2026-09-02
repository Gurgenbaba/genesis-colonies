#!/usr/bin/env python3
"""One-shot deterministic codemod for GC-PERF-QUEUE-TELEMETRY-001."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "game" / "queue_engine.py"

OLD_CONST = "_MAX_FINISH_PASSES = 8\n_SAVEPOINT_SEQ = 0\n"
NEW_CONST = "_MAX_FINISH_PASSES = 8\n_SAVEPOINT_SEQ = 0\n_SLOW_STEP_LOG_MS = 250\n"

OLD_FN = '''def _run_finish_step(conn: sqlite3.Connection, label: str, fn) -> Any:\n    \"\"\"\n    Run one finish subsection. On Postgres, wrap in SAVEPOINT so a failure\n    does not abort the whole finish transaction (GC-PERF-PG-PARITY-001).\n    \"\"\"\n    global _SAVEPOINT_SEQ\n    use_sp = get_db_backend() == \"postgres\"\n    sp = None\n    if use_sp:\n        _SAVEPOINT_SEQ = (_SAVEPOINT_SEQ + 1) % 1_000_000\n        sp = f\"qe_{_SAVEPOINT_SEQ}\"\n        conn.execute(f\"SAVEPOINT {sp}\")\n    try:\n        out = fn()\n        if use_sp and sp is not None:\n            try:\n                conn.execute(f\"RELEASE SAVEPOINT {sp}\")\n            except Exception:\n                # Nested code may have left TX aborted; undo this step and re-raise.\n                try:\n                    conn.execute(f\"ROLLBACK TO SAVEPOINT {sp}\")\n                    conn.execute(f\"RELEASE SAVEPOINT {sp}\")\n                except Exception:\n                    logger.exception(\n                        \"queue_engine savepoint recover-after-release failed (%s)\", label\n                    )\n                raise\n        return out\n    except Exception:\n        if use_sp and sp is not None:\n            try:\n                conn.execute(f\"ROLLBACK TO SAVEPOINT {sp}\")\n                conn.execute(f\"RELEASE SAVEPOINT {sp}\")\n            except Exception:\n                logger.exception(\"queue_engine savepoint rollback failed (%s)\", label)\n        raise\n'''

NEW_FN = '''def _run_finish_step(conn: sqlite3.Connection, label: str, fn) -> Any:\n    \"\"\"\n    Run one finish subsection. On Postgres, wrap in SAVEPOINT so a failure\n    does not abort the whole finish transaction (GC-PERF-PG-PARITY-001).\n\n    GC-PERF-QUEUE-TELEMETRY-001 logs only genuinely slow queue subsections so\n    production completion spikes can be attributed without adding idle noise.\n    \"\"\"\n    global _SAVEPOINT_SEQ\n    step_started = time.perf_counter()\n    use_sp = get_db_backend() == \"postgres\"\n    sp = None\n    if use_sp:\n        _SAVEPOINT_SEQ = (_SAVEPOINT_SEQ + 1) % 1_000_000\n        sp = f\"qe_{_SAVEPOINT_SEQ}\"\n        conn.execute(f\"SAVEPOINT {sp}\")\n    try:\n        out = fn()\n        if use_sp and sp is not None:\n            try:\n                conn.execute(f\"RELEASE SAVEPOINT {sp}\")\n            except Exception:\n                # Nested code may have left TX aborted; undo this step and re-raise.\n                try:\n                    conn.execute(f\"ROLLBACK TO SAVEPOINT {sp}\")\n                    conn.execute(f\"RELEASE SAVEPOINT {sp}\")\n                except Exception:\n                    logger.exception(\n                        \"queue_engine savepoint recover-after-release failed (%s)\", label\n                    )\n                raise\n        return out\n    except Exception:\n        if use_sp and sp is not None:\n            try:\n                conn.execute(f\"ROLLBACK TO SAVEPOINT {sp}\")\n                conn.execute(f\"RELEASE SAVEPOINT {sp}\")\n            except Exception:\n                logger.exception(\"queue_engine savepoint rollback failed (%s)\", label)\n        raise\n    finally:\n        elapsed_ms = int((time.perf_counter() - step_started) * 1000)\n        if elapsed_ms >= int(_SLOW_STEP_LOG_MS):\n            logger.info(\n                \"queue_engine slow-step label=%s duration_ms=%s backend=%s\",\n                label,\n                elapsed_ms,\n                get_db_backend(),\n            )\n'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")
    source = replace_once(source, OLD_CONST, NEW_CONST, "constants")
    source = replace_once(source, OLD_FN, NEW_FN, "_run_finish_step")
    TARGET.write_text(source, encoding="utf-8")
    print("GC-PERF-QUEUE-TELEMETRY-001 applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
