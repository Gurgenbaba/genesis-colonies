"""Secret Vault Raid — vault snapshot + steal (ground resolve lives in combat.py)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .inventory_catalog import CONTAINER_KEYS

logger = logging.getLogger(__name__)

VAULT_TK_CAP_SEC = 6 * 60 * 60  # 6h
VAULT_BOX_CAP = 5
VAULT_RAID_BLOCKED_CONTAINERS = frozenset({"container_event_special"})

RARITY_RANK = {
    "common": 1,
    "uncommon": 2,
    "rare": 3,
    "epic": 4,
    "legendary": 5,
    "mythic": 6,
}


def vault_raidable_container_keys() -> frozenset:
    return frozenset(k for k in CONTAINER_KEYS if k not in VAULT_RAID_BLOCKED_CONTAINERS)


def list_vault_boxes(defender_id: int, *, conn, limit: int = VAULT_BOX_CAP) -> List[Dict[str, Any]]:
    """Pick up to `limit` meta containers from account inventory for vault exposure."""
    from .inventory_catalog import ITEM_CATALOG, item_catalog_entry

    if not table_ready_inventory(conn):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT item_key, amount, id
        FROM player_inventory_items
        WHERE user_id = ? AND planet_id IS NULL AND amount > 0
        ORDER BY id DESC;
        """,
        (int(defender_id),),
    )
    rows = cur.fetchall() or []
    candidates: List[Dict[str, Any]] = []
    allowed = vault_raidable_container_keys()
    for row in rows:
        key = str(row["item_key"] or "")
        if key not in allowed:
            continue
        spec = ITEM_CATALOG.get(key) or item_catalog_entry(key) or {}
        if str(spec.get("item_type") or "") != "container":
            continue
        rarity = str(spec.get("rarity") or "common")
        amount = max(0, int(row["amount"] or 0))
        for _ in range(amount):
            candidates.append(
                {
                    "item_key": key,
                    "rarity": rarity,
                    "rarity_rank": int(RARITY_RANK.get(rarity, 0)),
                    "row_id": int(row["id"]),
                }
            )
    candidates.sort(key=lambda c: (-int(c["rarity_rank"]), -int(c["row_id"])))
    return candidates[: max(0, int(limit))]


def table_ready_inventory(conn) -> bool:
    from .db import table_exists

    return table_exists(conn, "player_inventory_items")


def vault_snapshot(defender_id: int, *, conn) -> Dict[str, Any]:
    from .timekeeper import get_balance

    tk = max(0, int(get_balance(int(defender_id), conn=conn) or 0))
    exposed_tk = min(tk, VAULT_TK_CAP_SEC)
    boxes = list_vault_boxes(int(defender_id), conn=conn, limit=VAULT_BOX_CAP)
    return {
        "timekeeper_sec": exposed_tk,
        "boxes": [{"item_key": b["item_key"], "rarity": b["rarity"]} for b in boxes],
        "box_count": len(boxes),
    }


def build_vault_panel_state(player_id: int, *, conn) -> Dict[str, Any]:
    """Player-facing Secret Vault exposure (what a successful ground raid can steal)."""
    from .inventory_catalog import ITEM_CATALOG, item_catalog_entry
    from .timekeeper import format_balance_label, get_balance

    pid = int(player_id)
    tk_balance = max(0, int(get_balance(pid, conn=conn) or 0))
    snap = vault_snapshot(pid, conn=conn)
    exposed_tk = max(0, int(snap.get("timekeeper_sec") or 0))

    grouped: Dict[str, Dict[str, Any]] = {}
    for box in snap.get("boxes") or []:
        key = str(box.get("item_key") or "")
        if not key:
            continue
        rarity = str(box.get("rarity") or "common")
        if key not in grouped:
            spec = ITEM_CATALOG.get(key) or item_catalog_entry(key) or {}
            grouped[key] = {
                "item_key": key,
                "rarity": rarity,
                "name_key": str(spec.get("name_key") or f"item_{key}"),
                "image": str(spec.get("image") or ""),
                "amount": 0,
            }
        grouped[key]["amount"] = int(grouped[key]["amount"]) + 1

    boxes_out = sorted(
        grouped.values(),
        key=lambda b: (-int(RARITY_RANK.get(str(b.get("rarity") or ""), 0)), str(b.get("item_key") or "")),
    )
    protected_tk = max(0, tk_balance - exposed_tk)
    box_count = sum(int(b.get("amount") or 0) for b in boxes_out)
    return {
        "ready": True,
        "tk_cap_sec": int(VAULT_TK_CAP_SEC),
        "tk_cap_label": format_balance_label(VAULT_TK_CAP_SEC),
        "box_cap": int(VAULT_BOX_CAP),
        "tk_balance_sec": tk_balance,
        "tk_balance_label": format_balance_label(tk_balance),
        "tk_exposed_sec": exposed_tk,
        "tk_exposed_label": format_balance_label(exposed_tk),
        "tk_protected_sec": protected_tk,
        "tk_protected_label": format_balance_label(protected_tk),
        "tk_fill_pct": int(round(100.0 * exposed_tk / max(1, VAULT_TK_CAP_SEC))),
        "box_fill_pct": int(round(100.0 * box_count / max(1, VAULT_BOX_CAP))),
        "boxes_exposed": boxes_out,
        "box_count": box_count,
        "empty": exposed_tk <= 0 and box_count <= 0,
        "account_scope": True,
    }


def apply_vault_steal(
    *,
    attacker_id: int,
    defender_id: int,
    conn,
) -> Dict[str, Any]:
    """
    Atomically steal capped TK + containers from defender to attacker.
    Uses timekeeper + inventory owners only.
    """
    from .inventory import consume_inventory_item, grant_inventory_item
    from .timekeeper import credit, debit, get_balance

    empty = {
        "ok": True,
        "timekeeper_stolen": 0,
        "boxes_stolen": [],
        "empty_vault": True,
    }
    if int(attacker_id) <= 0 or int(defender_id) <= 0 or int(attacker_id) == int(defender_id):
        return dict(empty)

    snap = vault_snapshot(int(defender_id), conn=conn)
    stolen_tk = 0
    want_tk = int(snap.get("timekeeper_sec") or 0)
    if want_tk > 0:
        from .timekeeper import InsufficientTimekeeperBalance

        bal = get_balance(int(defender_id), conn=conn)
        take = min(want_tk, max(0, int(bal or 0)), VAULT_TK_CAP_SEC)
        if take > 0:
            try:
                debit(int(defender_id), take, "vault_raid", conn=conn)
                credit(int(attacker_id), take, "vault_raid", conn=conn)
                stolen_tk = take
            except InsufficientTimekeeperBalance:
                stolen_tk = 0
            except Exception:
                logger.exception("vault_raid TK steal failed")
                stolen_tk = 0

    stolen_boxes: List[str] = []
    for box in list_vault_boxes(int(defender_id), conn=conn, limit=VAULT_BOX_CAP):
        key = str(box["item_key"])
        if consume_inventory_item(int(defender_id), key, 1, conn=conn):
            grant_inventory_item(int(attacker_id), key, 1, conn=conn)
            stolen_boxes.append(key)
        if len(stolen_boxes) >= VAULT_BOX_CAP:
            break

    return {
        "ok": True,
        "timekeeper_stolen": int(stolen_tk),
        "boxes_stolen": stolen_boxes,
        "empty_vault": stolen_tk <= 0 and not stolen_boxes,
    }
