"""Thin heat-event hooks for other owners (EPIC-21). Fail-soft."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def safe_record_heat(
    conn,
    galaxy_id: Optional[int],
    kind: str,
    amount: Optional[int] = None,
) -> None:
    if conn is None or galaxy_id is None:
        return
    try:
        gid = int(galaxy_id)
    except (TypeError, ValueError):
        return
    if gid < 1:
        return
    try:
        from .heat import record_heat_event

        record_heat_event(conn, gid, kind, amount)
    except Exception:
        logger.exception("pirate heat hook failed galaxy=%s kind=%s", galaxy_id, kind)
