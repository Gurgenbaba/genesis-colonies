"""Big-number compatibility for Imperial Directive progress audit rows.

Directive gameplay progress is bounded by each objective target, but the optional
``directive_progress.delta`` audit/idempotency row historically stores the raw
source-event delta in an INTEGER/BIGINT column. Endgame upgrade spends can exceed
signed i64 even though Python and the authoritative economy support them exactly.

For the audit row we only need a stable source_event_id plus a positive diagnostic
delta. Saturating that diagnostic value at signed i64 keeps SQLite/PostgreSQL safe
without changing the authoritative event amount, objective progress, completion,
or deduplication semantics.
"""

from __future__ import annotations

from typing import Any

SIGNED_I64_MAX = (1 << 63) - 1


def install_directive_progress_big_number_guard(progress_module: Any) -> None:
    """Install the audit-delta saturation guard exactly once."""
    if bool(getattr(progress_module, "_gc_big_number_guard_installed", False)):
        return

    original = progress_module._record_progress_delta

    def _record_progress_delta_i64_safe(
        player_directive_id: int,
        *,
        source_event_id: str,
        delta: int,
        conn,
        now: int,
    ) -> bool:
        audit_delta = min(SIGNED_I64_MAX, max(0, int(delta)))
        return original(
            int(player_directive_id),
            source_event_id=str(source_event_id),
            delta=audit_delta,
            conn=conn,
            now=int(now),
        )

    progress_module._record_progress_delta = _record_progress_delta_i64_safe
    progress_module._gc_big_number_guard_installed = True
