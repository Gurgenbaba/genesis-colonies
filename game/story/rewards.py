"""Story reward grants (meta only) + engine-owned Ark-Token chapter drip."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .flags import has_flag, set_flag

logger = logging.getLogger(__name__)

# Defaults — pack may override via chapter_token_reward / finale_token_reward / side_token_reward.
DEFAULT_MAIN_CHAPTER_TOKENS = 2
DEFAULT_MAIN_FINALE_TOKENS = 6
DEFAULT_SIDE_CHAPTER_TOKENS = 4


def chapter_receipt_flag(pack_id: str, arc_id: str, chapter_index: int) -> str:
    return f"ark_ch:{pack_id}:{arc_id}:{int(chapter_index)}"


def chapter_ark_token_amount(
    arc_def: Mapping[str, Any],
    chapter_index: int,
    *,
    pack: Mapping[str, Any] | None = None,
) -> int:
    """Tokens for completing chapter_index (0-based) of this arc."""
    chapters = list(arc_def.get("chapters") or [])
    if not chapters or chapter_index < 0 or chapter_index >= len(chapters):
        return 0
    kind = str(arc_def.get("kind") or "side").strip().lower()
    pack = pack or {}
    if kind == "side":
        return max(0, int(pack.get("side_token_reward") or DEFAULT_SIDE_CHAPTER_TOKENS))
    is_finale = chapter_index >= len(chapters) - 1
    if is_finale:
        return max(0, int(pack.get("finale_token_reward") or DEFAULT_MAIN_FINALE_TOKENS))
    return max(0, int(pack.get("chapter_token_reward") or DEFAULT_MAIN_CHAPTER_TOKENS))


def grant_chapter_ark_tokens(
    player_id: int,
    *,
    pack_id: str,
    arc_id: str,
    chapter_index: int,
    arc_def: Mapping[str, Any],
    conn,
    now: float | None = None,
    pack: Mapping[str, Any] | None = None,
    notify: bool = True,
) -> Dict[str, Any]:
    """
    Idempotent Ark-Token drip for one completed chapter.
    Receipt flag: ark_ch:{pack}:{arc}:{chapter_index}
    """
    pid = int(player_id)
    cid = int(chapter_index)
    flag = chapter_receipt_flag(str(pack_id), str(arc_id), cid)
    if has_flag(pid, flag, conn=conn):
        return {"ok": True, "granted": 0, "already": True, "flag": flag}

    amount = chapter_ark_token_amount(arc_def, cid, pack=pack)
    if amount <= 0:
        set_flag(pid, flag, conn=conn, now=now)
        return {"ok": True, "granted": 0, "already": False, "flag": flag, "skipped": True}

    from ..inventory import grant_inventory_item
    from .free_shop import ARK_TOKEN_KEY

    if not grant_inventory_item(pid, ARK_TOKEN_KEY, amount, conn=conn):
        logger.warning(
            "story chapter ark token grant failed player=%s pack=%s arc=%s ch=%s",
            pid,
            pack_id,
            arc_id,
            cid,
        )
        return {"ok": False, "granted": 0, "error": "grant_failed", "flag": flag}

    set_flag(pid, flag, conn=conn, now=now)

    if notify:
        try:
            from ..i18n import tr
            from ..messages import notify_system

            subject = tr("story_ark_token_chapter_subj", "Ark-Token")
            body_tmpl = tr(
                "story_ark_token_chapter_body",
                "+%(amount)s Ark-Token — Kapitel abgeschlossen.",
            )
            try:
                body = body_tmpl % {"amount": amount}
            except Exception:
                body = f"+{amount} Ark-Token — Kapitel abgeschlossen."
            notify_system(
                pid,
                subject,
                body,
                metadata={
                    "source": "story_ops",
                    "kind": "ark_chapter_token",
                    "amount": amount,
                    "pack_id": str(pack_id),
                    "arc_id": str(arc_id),
                    "chapter_index": cid,
                },
            )
        except Exception:
            logger.exception("story chapter ark notify failed player=%s", pid)

    return {
        "ok": True,
        "granted": amount,
        "already": False,
        "flag": flag,
        "item_key": ARK_TOKEN_KEY,
    }


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
                from .free_shop import ARK_TOKEN_KEY

                item_key = str(grant.get("item_key") or "").strip()
                amount = max(1, int(grant.get("amount") or 1))
                if not item_key:
                    continue
                # Chapter drip owns Ark-Tokens — ignore leftover pack scrap grants.
                if item_key == ARK_TOKEN_KEY:
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
