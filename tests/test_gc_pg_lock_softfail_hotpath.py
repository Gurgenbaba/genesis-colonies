"""Guards for PG lock soft-fail + initiation SAVEPOINT + schema cache."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_db_lock_error_covers_postgres_lock_timeout():
    source = (ROOT / "game" / "db.py").read_text(encoding="utf-8")
    assert "def is_db_lock_error" in source
    assert "LockNotAvailable" in source
    assert "canceling statement due to lock timeout" in source


def test_touch_player_online_uses_short_local_lock_timeout():
    source = (ROOT / "game" / "models.py").read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout = '250ms'" in source


def test_initiation_visit_uses_savepoint():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "SAVEPOINT gc_initiation_visit" in source
    assert "initiation page visit skipped (aborted TX)" in source


def test_postgres_table_exists_is_cached():
    source = (ROOT / "game" / "db_pg.py").read_text(encoding="utf-8")
    assert "_PG_TABLE_EXISTS_CACHE" in source


def test_galaxy_max_cached_and_list_system_passes_conn():
    source = (ROOT / "game" / "galaxy.py").read_text(encoding="utf-8")
    assert "_GALAXY_MAX_CACHE" in source
    assert "validate_coordinates(galaxy, system, POSITION_MIN, conn=conn)" in source


def test_page_live_context_soft_fallback_covers_pg_locks_on_ssr():
    """SSR/PJAX (e.g. /galaxy) must not 500 on PG LockNotAvailable — read-only fallback."""
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    block = source.split("def _load_page_live_context(")[1].split(
        "\ndef _stash_shell_boot_for_inject(", 1
    )[0]
    assert "is_db_lock_error(live_exc)" in block
    assert "page live context locked, using read-only fallback" in block
    # Must not re-raise locks for full page loads (that caused live Galaxy PJAX 500s).
    assert "if not use_poll_live_path and not use_planet_switch_live_path:\n                raise" not in block


def test_galaxy_view_asteroid_ensure_soft_skips_on_lock():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    block = source.split("def galaxy_view()")[1].split("@app.route", 1)[0]
    assert "ensure_asteroids_present(conn=conn)" in block
    assert "is_db_lock_error(asteroid_exc)" in block
    assert "galaxy asteroid ensure skipped (database locked)" in block


def test_poll_due_claim_soft_skips_db_lock():
    source = (ROOT / "game" / "queue_poll.py").read_text(encoding="utf-8")
    block = source.split("def try_claim_poll_due_finish(")[1].split(
        "\ndef clear_poll_due_claim_for_tests(", 1
    )[0]
    assert "is_db_lock_error(claim_exc)" in block
    assert "return False" in block


def test_runtime_state_upsert_soft_skips_lock():
    source = (ROOT / "game" / "runtime_state.py").read_text(encoding="utf-8")
    block = source.split("def set_runtime_value(")[1].split("\ndef record_queue_tick_result(", 1)[0]
    assert "is_db_lock_error(exc)" in block
    assert "runtime_state upsert skipped (lock)" in block


def test_resolve_directive_cycle_pg_safe_primary_since_case():
    """PG rejects WHEN ? IS NOT NULL with NULL binds (IndeterminateDatatype $3)."""
    source = (ROOT / "game" / "galactic_directives" / "voting.py").read_text(
        encoding="utf-8"
    )
    block = source.split("def resolve_directive_cycle(")[1].split(
        "\ndef _refresh_galaxy_personality_from_history(", 1
    )[0]
    assert "CASE WHEN ? = 1 THEN ?" in block
    assert "CASE WHEN ? IS NOT NULL THEN ?" not in block
    assert "1 if primary else 0" in block
