"""Story reward grants (meta only)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Sequence

from .flags import set_flag

logger = logging.getLogger(__name__)


def apply_grants(
    player_id: int,
    grants: Sequence[Mapping[str, Any]],
    *,
    conn,
    now: float | None = None,
) -> List[Dict[str, Any]]:
    applied: List[Dict[str, Any]] = []
    for grant in grants or []:
        if not grant:
            continue
        kind = str(grant.get("kind") or "").strip().lower()
        try:
            if kind == "inventory":
                from ..inventory import grant_inventory_item

                item_key = str(grant.get("item_key") or "").strip()
                amount = max(1, int(grant.get("amount") or 1))
                if not item_key:
                    continue
                grant_inventory_item(int(player_id), item_key, amount, conn=conn)
                applied.append({"kind": "inventory", "item_key": item_key, "amount": amount})
            elif kind == "flag":
                flag = str(grant.get("flag") or "").strip()
                if flag and set_flag(int(player_id), flag, conn=conn, now=now):
                    applied.append({"kind": "flag", "flag": flag})
            elif kind == "codex_flag":
                flag = str(grant.get("flag") or "").strip()
                if flag and set_flag(int(player_id), flag, conn=conn, now=now):
                    applied.append({"kind": "codex_flag", "flag": flag})
            elif kind == "notify":
                from .delivery import deliver_story_notify

                res = deliver_story_notify(
                    int(player_id),
                    subject_key=str(grant.get("subject_key") or ""),
                    body_key=str(grant.get("body_key") or ""),
                    conn=conn,
                )
                if res.get("ok"):
                    applied.append({"kind": "notify", "ok": True})
        except Exception:
            logger.exception(
                "story grant failed player=%s kind=%s",
                player_id,
                kind,
            )
    return applied
