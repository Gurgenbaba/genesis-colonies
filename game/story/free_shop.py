"""Story Ops Free Shop — Ark-Token redeem for shop-like convenience meta (EPIC-25).

Owner: game/story/. Storage key remains story_scrap_token (no inventory migration).
Display currency: Ark-Token. Not a payment catalog — see game/shop.py for EUR shop.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..i18n import tr
from ..inventory import consume_inventory_item, grant_inventory_item, inventory_amount
from ..inventory_catalog import ITEM_CATALOG, PASS_BOOSTER_IMAGES, is_known_item_key
from ..timekeeper import credit as timekeeper_credit

# Internal inventory key (stable). UI label = Ark-Token.
ARK_TOKEN_KEY = "story_scrap_token"
STORY_SCRAP_TOKEN_KEY = ARK_TOKEN_KEY  # legacy alias for packs/tests during rename

TK_IMAGE = "img/pass/timekeeper.webp"
SHIPYARD_IMAGE = PASS_BOOSTER_IMAGES.get("build", "img/pass/build_boost.webp")

# Convenience meta clearly below EUR shop packs — same grants, Free Shop framing.
FREE_SHOP_OFFERS: Dict[str, Dict[str, Any]] = {
    "free_tk_45m": {
        "cost": 12,
        "kind": "timekeeper",
        "seconds": 45 * 60,
        "title_key": "free_shop_offer_tk_title",
        "title_fallback": "Timekeeper (45 Min)",
        "hint_key": "free_shop_offer_tk_hint",
        "hint_fallback": "Flexibles Timekeeper — unter den EUR-Packs.",
        "image": TK_IMAGE,
    },
    "free_build_5m": {
        "cost": 8,
        "kind": "inventory",
        "item_key": "booster_build_5m",
        "amount": 1,
        "title_key": "free_shop_offer_build5_title",
        "title_fallback": "Bau-Booster 5 Min",
        "hint_key": "free_shop_offer_build5_hint",
        "hint_fallback": "Kurzer Bau-Skip für die aktive Queue.",
        "image": PASS_BOOSTER_IMAGES["build"],
    },
    "free_research_5m": {
        "cost": 8,
        "kind": "inventory",
        "item_key": "booster_research_5m",
        "amount": 1,
        "title_key": "free_shop_offer_res5_title",
        "title_fallback": "Forschungs-Booster 5 Min",
        "hint_key": "free_shop_offer_res5_hint",
        "hint_fallback": "Kurzer Forschungs-Skip.",
        "image": PASS_BOOSTER_IMAGES["research"],
    },
    "free_container_basic": {
        "cost": 10,
        "kind": "inventory",
        "item_key": "container_basic",
        "amount": 1,
        "title_key": "free_shop_offer_box_title",
        "title_fallback": "Basic Container",
        "hint_key": "free_shop_offer_box_hint",
        "hint_fallback": "Meta-Container — kein Combat-P2W.",
        "image": "img/lootboxes/Basic_Container.png",
    },
    "free_shipyard_15m": {
        "cost": 14,
        "kind": "inventory",
        "item_key": "booster_shipyard_15m",
        "amount": 1,
        "title_key": "free_shop_offer_yard15_title",
        "title_fallback": "Werft-Booster 15 Min",
        "hint_key": "free_shop_offer_yard15_hint",
        "hint_fallback": "Werft-Queue beschleunigen.",
        "image": SHIPYARD_IMAGE,
    },
    "free_research_15m": {
        "cost": 14,
        "kind": "inventory",
        "item_key": "booster_research_15m",
        "amount": 1,
        "title_key": "free_shop_offer_res15_title",
        "title_fallback": "Forschungs-Booster 15 Min",
        "hint_key": "free_shop_offer_res15_hint",
        "hint_fallback": "Mittlerer Forschungs-Skip.",
        "image": PASS_BOOSTER_IMAGES["research"],
    },
    "free_container_wreckage": {
        "cost": 18,
        "kind": "inventory",
        "item_key": "container_wreckage",
        "amount": 1,
        "title_key": "free_shop_offer_wreck_title",
        "title_fallback": "Wreckage Container",
        "hint_key": "free_shop_offer_wreck_hint",
        "hint_fallback": "Wrack-Container aus dem Lore-Free-Shop.",
        "image": "img/lootboxes/Wreckage_Container.png",
    },
}


def _t(key: str, fallback: str) -> str:
    k = str(key or "").strip()
    fb = str(fallback or "").strip() or "—"
    if not k:
        return fb
    val = tr(k, fb)
    if not val or val == k:
        return fb
    return str(val)


def _offer_image(spec: Dict[str, Any]) -> str:
    img = str(spec.get("image") or "").strip()
    if img:
        return img
    item_key = str(spec.get("item_key") or "").strip()
    if item_key:
        entry = ITEM_CATALOG.get(item_key) or {}
        return str(entry.get("image") or "").strip()
    return ""


def ark_token_balance(player_id: int, *, conn) -> int:
    return int(inventory_amount(int(player_id), ARK_TOKEN_KEY, conn=conn) or 0)


def list_free_shop_offers(player_id: int, *, conn) -> List[Dict[str, Any]]:
    bal = ark_token_balance(player_id, conn=conn)
    out: List[Dict[str, Any]] = []
    for offer_id, spec in FREE_SHOP_OFFERS.items():
        cost = int(spec["cost"])
        kind = str(spec.get("kind") or "inventory")
        out.append(
            {
                "offer_id": offer_id,
                "kind": kind,
                "cost": cost,
                "title": _t(str(spec["title_key"]), str(spec["title_fallback"])),
                "hint": _t(str(spec["hint_key"]), str(spec.get("hint_fallback") or "")),
                "image": _offer_image(spec),
                "affordable": bal >= cost,
            }
        )
    return out


def get_free_shop_state(player_id: int, *, conn) -> Dict[str, Any]:
    bal = ark_token_balance(player_id, conn=conn)
    return {
        "balance": bal,
        "token_key": ARK_TOKEN_KEY,
        "label": _t("inv_ark_token", "Ark-Token"),
        "offers": list_free_shop_offers(player_id, conn=conn),
    }


def redeem_free_shop_offer(
    player_id: int,
    *,
    offer_id: str,
    conn,
    request_id: str | None = None,
) -> Dict[str, Any]:
    """Spend Ark-Tokens for Free Shop convenience meta."""
    oid = str(offer_id or "").strip()
    spec = FREE_SHOP_OFFERS.get(oid)
    if not spec:
        return {"ok": False, "error": "unknown_offer"}

    cost = int(spec["cost"])
    pid = int(player_id)
    if ark_token_balance(pid, conn=conn) < cost:
        return {"ok": False, "error": "insufficient_tokens"}

    if not consume_inventory_item(pid, ARK_TOKEN_KEY, cost, conn=conn):
        return {"ok": False, "error": "insufficient_tokens"}

    kind = str(spec.get("kind") or "")
    if kind == "timekeeper":
        timekeeper_credit(
            pid,
            int(spec["seconds"]),
            source=f"story_free_shop:{oid}",
            conn=conn,
        )
    elif kind == "inventory":
        item_key = str(spec.get("item_key") or "")
        amount = max(1, int(spec.get("amount") or 1))
        if not is_known_item_key(item_key):
            grant_inventory_item(pid, ARK_TOKEN_KEY, cost, conn=conn)
            return {"ok": False, "error": "offer_misconfigured"}
        if not grant_inventory_item(pid, item_key, amount, conn=conn):
            grant_inventory_item(pid, ARK_TOKEN_KEY, cost, conn=conn)
            return {"ok": False, "error": "grant_failed"}
    else:
        grant_inventory_item(pid, ARK_TOKEN_KEY, cost, conn=conn)
        return {"ok": False, "error": "unknown_kind"}

    return {
        "ok": True,
        "offer_id": oid,
        "cost": cost,
        "balance": ark_token_balance(pid, conn=conn),
        "request_id": str(request_id or ""),
    }
