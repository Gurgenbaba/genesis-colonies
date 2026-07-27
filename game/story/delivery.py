"""Story delivery — inbox + codex flag hooks (GC-2504)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..i18n import tr
from .flags import has_flag


def deliver_story_notify(
    player_id: int,
    *,
    subject_key: str,
    body_key: str,
    conn=None,
) -> Dict[str, Any]:
    from ..messages import notify_system

    subject = tr(str(subject_key or ""), str(subject_key or "Transmission"))
    body = tr(str(body_key or ""), str(body_key or ""))
    if not subject.strip() and not body.strip():
        return {"ok": False, "error": "empty"}
    return notify_system(
        int(player_id),
        subject or "Transmission",
        body or subject,
        metadata={"source": "story_ops", "subject_key": subject_key, "body_key": body_key},
        conn=conn,
    )


def player_has_codex_story_flag(
    player_id: int,
    flag: str,
    *,
    conn,
) -> bool:
    return has_flag(int(player_id), str(flag or "").strip(), conn=conn)


def story_unlock_label(flag: str) -> Optional[str]:
    key = str(flag or "").strip()
    if not key:
        return None
    return tr(f"story_codex_{key}_title", key)
