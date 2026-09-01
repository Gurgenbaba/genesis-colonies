"""Creator promo codes — pricing, ledger, funnel, payouts (PAYMENT_SHOP owner)."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import column_exists, table_exists

PARTNER_TERMS_VERSION = "v1"
DEFAULT_DISCOUNT_BPS = 1000
DEFAULT_COMMISSION_BPS = 1000
MIN_PAID_CENTS = 50
SESSION_PROMO_KEY = "shop_promo_code"
SESSION_PROMO_TTL_SEC = 7 * 24 * 3600

LEDGER_HELD = "held"
LEDGER_AVAILABLE = "available"
LEDGER_PAID = "paid"
LEDGER_REVERSED = "reversed"

EVENT_CLICK = "click"
EVENT_REGISTER = "register"
EVENT_PURCHASE = "purchase"
EVENT_HELD = "commission_held"
EVENT_AVAILABLE = "commission_available"
EVENT_PAYOUT = "payout"

_CODE_RE = re.compile(r"^[A-Z0-9_-]{3,32}$")


def commission_hold_sec() -> int:
    raw = os.environ.get("CREATOR_COMMISSION_HOLD_SEC")
    if raw is None or str(raw).strip() == "":
        return 7 * 24 * 3600
    try:
        return max(0, int(raw))
    except Exception:
        return 7 * 24 * 3600


def min_payout_cents() -> int:
    raw = os.environ.get("CREATOR_MIN_PAYOUT_CENTS")
    if raw is None or str(raw).strip() == "":
        return 2500
    try:
        return max(0, int(raw))
    except Exception:
        return 2500


def min_buyer_score() -> int:
    """Minimum player_scores.score_total before commission becomes available."""
    raw = os.environ.get("CREATOR_MIN_BUYER_SCORE")
    if raw is None or str(raw).strip() == "":
        return 100
    try:
        return max(0, int(raw))
    except Exception:
        return 100


def buyer_recent_active_sec() -> int:
    """Buyer must have last_seen within this window (default 7d) to release commission."""
    raw = os.environ.get("CREATOR_BUYER_ACTIVE_WINDOW_SEC")
    if raw is None or str(raw).strip() == "":
        return 7 * 24 * 3600
    try:
        return max(0, int(raw))
    except Exception:
        return 7 * 24 * 3600


def velocity_cap_24h() -> int:
    raw = os.environ.get("CREATOR_VELOCITY_CAP_24H")
    if raw is None or str(raw).strip() == "":
        return 5
    try:
        return max(1, int(raw))
    except Exception:
        return 5


KIND_CREATOR = "creator"
KIND_CAMPAIGN = "campaign"


def schema_ready(conn) -> bool:
    return (
        table_exists(conn, "shop_creators")
        and table_exists(conn, "shop_promo_codes")
        and table_exists(conn, "shop_creator_ledger")
        and table_exists(conn, "shop_promo_events")
        and column_exists(conn, "shop_orders", "promo_code_id")
    )


def campaign_schema_ready(conn) -> bool:
    return schema_ready(conn) and column_exists(conn, "shop_promo_codes", "kind")


def normalize_code(code: str) -> str:
    return str(code or "").strip().upper()


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj if obj is not None else {}, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _now(now: Optional[float] = None) -> float:
    return float(now if now is not None else time.time())


def price_breakdown(list_cents: int, discount_bps: int, commission_bps: int) -> Dict[str, int]:
    lst = max(0, int(list_cents))
    dbps = max(0, min(9000, int(discount_bps)))
    cbps = max(0, min(5000, int(commission_bps)))
    discount = int(lst * dbps // 10000)
    paid = max(MIN_PAID_CENTS, lst - discount) if lst > 0 else 0
    if paid > lst:
        paid = lst
    commission = int(lst * cbps // 10000)
    return {
        "list_cents": lst,
        "discount_cents": max(0, lst - paid),
        "paid_cents": paid,
        "commission_cents": commission,
        "discount_bps": dbps,
        "commission_bps": cbps,
    }


def get_creator(creator_id: int, *, conn) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn) or int(creator_id) <= 0:
        return None
    row = conn.execute(
        """
        SELECT id, display_name, player_id, paypal_email, payout_note, active,
               terms_acked_at, terms_version, created_at, updated_at
        FROM shop_creators WHERE id = ? LIMIT 1;
        """,
        (int(creator_id),),
    ).fetchone()
    return _creator_from_row(row) if row else None


def get_creator_by_player(player_id: int, *, conn) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn) or int(player_id) <= 0:
        return None
    row = conn.execute(
        """
        SELECT id, display_name, player_id, paypal_email, payout_note, active,
               terms_acked_at, terms_version, created_at, updated_at
        FROM shop_creators WHERE player_id = ? LIMIT 1;
        """,
        (int(player_id),),
    ).fetchone()
    return _creator_from_row(row) if row else None


def _creator_from_row(row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "display_name": str(row["display_name"] or ""),
        "player_id": int(row["player_id"]),
        "paypal_email": row["paypal_email"],
        "payout_note": str(row["payout_note"] or ""),
        "active": int(row["active"] or 0) == 1,
        "terms_acked_at": float(row["terms_acked_at"]) if row["terms_acked_at"] is not None else None,
        "terms_version": row["terms_version"],
        "created_at": float(row["created_at"] or 0),
        "updated_at": float(row["updated_at"] or 0),
    }


def get_promo_by_code(code: str, *, conn, active_only: bool = True) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn):
        return None
    normalized = normalize_code(code)
    if not normalized:
        return None
    has_kind = column_exists(conn, "shop_promo_codes", "kind")
    kind_sel = "p.kind," if has_kind else "'creator' AS kind,"
    row = conn.execute(
        f"""
        SELECT p.id, p.code, {kind_sel} p.creator_id, p.discount_bps, p.commission_bps,
               p.max_redemptions, p.active, p.notes, p.created_at, p.updated_at,
               c.display_name, c.player_id AS creator_player_id, c.active AS creator_active
        FROM shop_promo_codes p
        LEFT JOIN shop_creators c ON c.id = p.creator_id
        WHERE p.code = ?
        LIMIT 1;
        """,
        (normalized,),
    ).fetchone()
    if not row:
        return None
    promo = _promo_from_row(row)
    if active_only and not promo["active"]:
        return None
    if active_only and promo["kind"] == KIND_CREATOR and not promo["creator_active"]:
        return None
    return promo


def get_promo_by_id(promo_id: int, *, conn, active_only: bool = False) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn) or int(promo_id) <= 0:
        return None
    has_kind = column_exists(conn, "shop_promo_codes", "kind")
    kind_sel = "p.kind," if has_kind else "'creator' AS kind,"
    row = conn.execute(
        f"""
        SELECT p.id, p.code, {kind_sel} p.creator_id, p.discount_bps, p.commission_bps,
               p.max_redemptions, p.active, p.notes, p.created_at, p.updated_at,
               c.display_name, c.player_id AS creator_player_id, c.active AS creator_active
        FROM shop_promo_codes p
        LEFT JOIN shop_creators c ON c.id = p.creator_id
        WHERE p.id = ?
        LIMIT 1;
        """,
        (int(promo_id),),
    ).fetchone()
    if not row:
        return None
    promo = _promo_from_row(row)
    if active_only and not promo["active"]:
        return None
    if active_only and promo["kind"] == KIND_CREATOR and not promo["creator_active"]:
        return None
    return promo


def _promo_from_row(row) -> Dict[str, Any]:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    creator_id = row["creator_id"] if "creator_id" in keys else None
    creator_player_id = row["creator_player_id"] if "creator_player_id" in keys else None
    creator_active_raw = row["creator_active"] if "creator_active" in keys else None
    kind = str(row["kind"] if "kind" in keys and row["kind"] is not None else KIND_CREATOR)
    return {
        "id": int(row["id"]),
        "code": str(row["code"]),
        "kind": kind,
        "creator_id": int(creator_id) if creator_id is not None else None,
        "discount_bps": int(row["discount_bps"] or 0),
        "commission_bps": int(row["commission_bps"] or 0),
        "max_redemptions": int(row["max_redemptions"]) if row["max_redemptions"] is not None else None,
        "active": int(row["active"] or 0) == 1,
        "notes": str(row["notes"] or ""),
        "created_at": float(row["created_at"] or 0),
        "updated_at": float(row["updated_at"] or 0),
        "display_name": str(row["display_name"] or "") if row["display_name"] is not None else "",
        "creator_player_id": int(creator_player_id) if creator_player_id is not None else None,
        "creator_active": (
            int(creator_active_raw or 0) == 1 if creator_active_raw is not None else kind == KIND_CAMPAIGN
        ),
    }


def resolve_referrer_player_id(code: str, *, conn) -> Optional[int]:
    """Referral bridge: active creator promo code → creator player_id."""
    promo = get_promo_by_code(code, conn=conn, active_only=True)
    if not promo or promo.get("kind") != KIND_CREATOR:
        return None
    pid = promo.get("creator_player_id")
    return int(pid) if pid else None


def _redemption_count(promo_id: int, *, conn) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM shop_orders
        WHERE promo_code_id = ?
          AND status IN ('paid', 'fulfilled');
        """,
        (int(promo_id),),
    ).fetchone()
    return int(row["c"] or 0) if row else 0


def validate_promo_for_buyer(
    code: str,
    buyer_player_id: int,
    *,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "promo_unavailable", None
    promo = get_promo_by_code(code, conn=conn, active_only=True)
    if not promo:
        return False, "promo_not_found", None
    creator_pid = promo.get("creator_player_id")
    if creator_pid is not None and int(creator_pid) == int(buyer_player_id):
        return False, "promo_self_not_allowed", None
    max_r = promo.get("max_redemptions")
    if max_r is not None and _redemption_count(int(promo["id"]), conn=conn) >= int(max_r):
        return False, "promo_max_redemptions", None
    return True, "ok", promo


def preview_pricing(
    code: str,
    *,
    conn,
    buyer_player_id: Optional[int] = None,
    sku: Optional[str] = None,
    products: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if buyer_player_id is not None:
        ok, reason, promo = validate_promo_for_buyer(code, int(buyer_player_id), conn=conn)
    else:
        promo = get_promo_by_code(code, conn=conn, active_only=True)
        ok, reason = (True, "ok") if promo else (False, "promo_not_found")
    if not ok or not promo:
        return False, reason, None

    from .shop import get_product, list_catalog

    catalog: List[Mapping[str, Any]]
    if products is not None:
        catalog = list(products)
    elif sku:
        product = get_product(str(sku), conn=conn)
        catalog = [product] if product else []
        if not catalog:
            return False, "unknown_sku", None
    else:
        catalog = list_catalog(conn=conn)

    priced = []
    for p in catalog:
        br = price_breakdown(
            int(p.get("price_cents") or 0),
            int(promo["discount_bps"]),
            int(promo["commission_bps"]),
        )
        priced.append(
            {
                "sku": str(p.get("sku") or ""),
                "list_cents": br["list_cents"],
                "paid_cents": br["paid_cents"],
                "discount_cents": br["discount_cents"],
                "commission_cents": br["commission_cents"],
                "currency": str(p.get("currency") or "eur"),
            }
        )
    return True, "ok", {
        "code": promo["code"],
        "kind": promo.get("kind") or KIND_CREATOR,
        "promo_code_id": int(promo["id"]),
        "creator_id": int(promo["creator_id"]) if promo.get("creator_id") is not None else None,
        "display_name": promo["display_name"],
        "discount_bps": int(promo["discount_bps"]),
        "commission_bps": int(promo["commission_bps"]),
        "priced": priced,
    }


def record_event(
    *,
    conn,
    creator_id: Optional[int],
    event_type: str,
    promo_code_id: Optional[int] = None,
    actor_player_id: Optional[int] = None,
    order_id: Optional[int] = None,
    meta: Optional[Mapping[str, Any]] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str]:
    if not schema_ready(conn):
        return False, "promo_unavailable"
    ts = _now(now)
    try:
        conn.execute(
            """
            INSERT INTO shop_promo_events (
                creator_id, promo_code_id, event_type, actor_player_id,
                order_id, meta_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(creator_id) if creator_id else None,
                int(promo_code_id) if promo_code_id else None,
                str(event_type),
                int(actor_player_id) if actor_player_id else None,
                int(order_id) if order_id else None,
                _json_dumps(meta or {}),
                ts,
            ),
        )
        return True, "ok"
    except Exception:
        # Unique constraints → idempotent success
        return True, "duplicate"


def record_click(code: str, *, conn, actor_player_id: Optional[int] = None, now: Optional[float] = None) -> Tuple[bool, str]:
    promo = get_promo_by_code(code, conn=conn, active_only=True)
    if not promo:
        return False, "promo_not_found"
    return record_event(
        conn=conn,
        creator_id=promo.get("creator_id"),
        event_type=EVENT_CLICK,
        promo_code_id=int(promo["id"]),
        actor_player_id=actor_player_id,
        now=now,
    )


def record_register_attribution(
    code: str,
    referred_player_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, str]:
    promo = get_promo_by_code(code, conn=conn, active_only=False)
    if not promo or promo.get("kind") != KIND_CREATOR or not promo.get("creator_id"):
        # Vanity may only exist on referral table; skip funnel
        return False, "promo_not_found"
    return record_event(
        conn=conn,
        creator_id=int(promo["creator_id"]),
        event_type=EVENT_REGISTER,
        promo_code_id=int(promo["id"]),
        actor_player_id=int(referred_player_id),
        now=now,
    )


def _buyer_account_age_sec(player_id: int, *, conn, now: float) -> int:
    from .referrals import _account_age_sec

    return int(_account_age_sec(int(player_id), conn=conn, now=int(now)))


def _buyer_score_total(player_id: int, *, conn) -> int:
    if not table_exists(conn, "player_scores"):
        return 0
    row = conn.execute(
        "SELECT COALESCE(score_total, '0') AS s FROM player_scores WHERE player_id = ? LIMIT 1;",
        (int(player_id),),
    ).fetchone()
    return int(row["s"] or 0) if row else 0


def _buyer_last_seen(player_id: int, *, conn) -> float:
    if not column_exists(conn, "players", "last_seen"):
        return 0.0
    from .presence_store import get_effective_last_seen

    return float(get_effective_last_seen(conn, int(player_id)))


def _buyer_is_banned(player_id: int, *, conn) -> bool:
    if not column_exists(conn, "players", "banned_until"):
        return False
    row = conn.execute(
        "SELECT banned_until FROM players WHERE id = ? LIMIT 1;",
        (int(player_id),),
    ).fetchone()
    if not row or row["banned_until"] is None:
        return False
    try:
        return int(row["banned_until"]) > int(time.time())
    except (TypeError, ValueError):
        return False


def buyer_qualifies_for_commission(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, str]:
    """Anti-abuse gate before commission becomes available for payout."""
    ts = _now(now)
    pid = int(player_id)
    if pid <= 0:
        return False, "invalid_buyer"
    if _buyer_is_banned(pid, conn=conn):
        return False, "buyer_banned"
    hold = commission_hold_sec()
    if hold > 0:
        age = _buyer_account_age_sec(pid, conn=conn, now=ts)
        if age < hold:
            return False, "buyer_too_young"
    active_window = buyer_recent_active_sec()
    if active_window > 0:
        last_seen = _buyer_last_seen(pid, conn=conn)
        if last_seen <= 0 or (ts - last_seen) > active_window:
            return False, "buyer_inactive"
    min_score = min_buyer_score()
    if min_score > 0 and _buyer_score_total(pid, conn=conn) < min_score:
        return False, "buyer_low_score"
    return True, "ok"


def creator_performance_stats(creator_id: int, *, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Professional partner KPIs: regs, active windows, donations, revenue, balance."""
    ts = _now(now)
    creator = get_creator(int(creator_id), conn=conn)
    if not creator:
        return {
            "registrations": 0,
            "active_7d": 0,
            "active_30d": 0,
            "donations": 0,
            "revenue_cents": 0,
            "balance": {"held": 0, "available": 0, "paid": 0, "reversed": 0},
            "status": "inactive",
            "code": None,
        }
    referrer_id = int(creator["player_id"])
    registrations = 0
    active_7d = 0
    active_30d = 0
    if table_exists(conn, "player_referrals"):
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM player_referrals
            WHERE referrer_player_id = ?;
            """,
            (referrer_id,),
        ).fetchone()
        registrations = int(row["c"] or 0) if row else 0
        if column_exists(conn, "players", "last_seen"):
            from .presence_store import effective_last_seen_scalar_sql

            last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")
            row7 = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM player_referrals r
                JOIN players p ON p.id = r.referred_player_id
                WHERE r.referrer_player_id = ?
                  AND {last_seen_expr} >= ?;
                """,
                (referrer_id, ts - 7 * 24 * 3600),
            ).fetchone()
            active_7d = int(row7["c"] or 0) if row7 else 0
            row30 = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM player_referrals r
                JOIN players p ON p.id = r.referred_player_id
                WHERE r.referrer_player_id = ?
                  AND {last_seen_expr} >= ?;
                """,
                (referrer_id, ts - 30 * 24 * 3600),
            ).fetchone()
            active_30d = int(row30["c"] or 0) if row30 else 0

    donations = 0
    revenue_cents = 0
    if column_exists(conn, "shop_orders", "promo_code_id"):
        row = conn.execute(
            """
            SELECT COUNT(*) AS c, COALESCE(SUM(o.amount_cents), 0) AS revenue
            FROM shop_orders o
            JOIN shop_promo_codes p ON p.id = o.promo_code_id
            WHERE p.creator_id = ?
              AND o.status IN ('paid', 'fulfilled');
            """,
            (int(creator_id),),
        ).fetchone()
        if row:
            donations = int(row["c"] or 0)
            revenue_cents = int(row["revenue"] or 0)

    promo = conn.execute(
        """
        SELECT code FROM shop_promo_codes
        WHERE creator_id = ? AND active = 1
        ORDER BY id ASC LIMIT 1;
        """,
        (int(creator_id),),
    ).fetchone()
    bal = ledger_balance(int(creator_id), conn=conn)
    return {
        "registrations": registrations,
        "active_7d": active_7d,
        "active_30d": active_30d,
        "donations": donations,
        "revenue_cents": revenue_cents,
        "balance": bal,
        "status": "active" if creator.get("active") else "inactive",
        "code": str(promo["code"]) if promo else None,
    }


def credit_commission_for_order(order: Mapping[str, Any], *, conn, now: Optional[float] = None) -> Tuple[bool, str]:
    if not schema_ready(conn):
        return False, "promo_unavailable"
    promo_id = order.get("promo_code_id")
    if not promo_id:
        return True, "no_promo"
    commission = int(order.get("commission_cents") or 0)
    if commission <= 0:
        # Campaign / zero-commission codes: still record purchase event, no ledger.
        promo = get_promo_by_id(int(promo_id), conn=conn, active_only=False)
        if promo:
            record_event(
                conn=conn,
                creator_id=promo.get("creator_id"),
                event_type=EVENT_PURCHASE,
                promo_code_id=int(promo_id),
                actor_player_id=int(order["player_id"]),
                order_id=int(order["id"]),
                meta={
                    "sku": order.get("sku"),
                    "amount_cents": order.get("amount_cents"),
                    "kind": promo.get("kind"),
                },
                now=now,
            )
        return True, "no_commission"
    promo = get_promo_by_id(int(promo_id), conn=conn, active_only=False)
    if not promo:
        return False, "promo_not_found"
    if not promo.get("creator_id") or promo.get("kind") == KIND_CAMPAIGN:
        return True, "no_commission"

    existing = conn.execute(
        "SELECT id, status FROM shop_creator_ledger WHERE order_id = ? LIMIT 1;",
        (int(order["id"]),),
    ).fetchone()
    if existing:
        return True, "already_credited"

    ts = _now(now)
    buyer_id = int(order["player_id"])
    ok_q, reason_q = buyer_qualifies_for_commission(buyer_id, conn=conn, now=ts)
    if ok_q:
        status = LEDGER_AVAILABLE
        available_at = ts
    else:
        status = LEDGER_HELD
        available_at = None

    # Velocity flag (soft): count recent held/available for this buyer
    since = ts - 86400
    vel = conn.execute(
        """
        SELECT COUNT(*) AS c FROM shop_creator_ledger
        WHERE buyer_player_id = ? AND created_at >= ?
          AND status IN ('held', 'available', 'paid');
        """,
        (buyer_id, since),
    ).fetchone()
    velocity_hit = int(vel["c"] or 0) >= velocity_cap_24h()

    conn.execute(
        """
        INSERT INTO shop_creator_ledger (
            creator_id, order_id, buyer_player_id, promo_code_id,
            gross_cents, commission_cents, status, available_at,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            int(promo["creator_id"]),
            int(order["id"]),
            buyer_id,
            int(promo_id),
            int(order.get("list_amount_cents") or order.get("amount_cents") or 0),
            commission,
            status,
            available_at,
            ts,
            ts,
        ),
    )
    record_event(
        conn=conn,
        creator_id=int(promo["creator_id"]),
        event_type=EVENT_PURCHASE,
        promo_code_id=int(promo_id),
        actor_player_id=buyer_id,
        order_id=int(order["id"]),
        meta={"sku": order.get("sku"), "amount_cents": order.get("amount_cents")},
        now=ts,
    )
    record_event(
        conn=conn,
        creator_id=int(promo["creator_id"]),
        event_type=EVENT_HELD if status == LEDGER_HELD else EVENT_AVAILABLE,
        promo_code_id=int(promo_id),
        actor_player_id=buyer_id,
        order_id=int(order["id"]),
        meta={
            "commission_cents": commission,
            "velocity_flag": velocity_hit,
            "qualify_reason": reason_q if not ok_q else "ok",
        },
        now=ts,
    )
    if status == LEDGER_AVAILABLE:
        _notify_creator(
            int(promo["creator_player_id"]),
            subject="Creator commission available",
            body=(
                f"Commission of {commission} cents is now available "
                f"for order #{int(order['id'])}."
            ),
            conn=conn,
        )
    return True, "ok"


def release_held_commissions(*, conn, now: Optional[float] = None, creator_id: Optional[int] = None) -> int:
    if not schema_ready(conn):
        return 0
    ts = _now(now)
    rows = conn.execute(
        """
        SELECT l.id, l.creator_id, l.order_id, l.buyer_player_id, l.promo_code_id,
               l.commission_cents, c.player_id AS creator_player_id
        FROM shop_creator_ledger l
        JOIN shop_creators c ON c.id = l.creator_id
        WHERE l.status = 'held'
          AND (? IS NULL OR l.creator_id = ?);
        """,
        (int(creator_id) if creator_id else None, int(creator_id) if creator_id else None),
    ).fetchall()
    released = 0
    for row in rows:
        ok_q, reason_q = buyer_qualifies_for_commission(
            int(row["buyer_player_id"]), conn=conn, now=ts
        )
        if not ok_q:
            continue
        conn.execute(
            """
            UPDATE shop_creator_ledger
            SET status = ?, available_at = ?, updated_at = ?
            WHERE id = ? AND status = 'held';
            """,
            (LEDGER_AVAILABLE, ts, ts, int(row["id"])),
        )
        record_event(
            conn=conn,
            creator_id=int(row["creator_id"]),
            event_type=EVENT_AVAILABLE,
            promo_code_id=int(row["promo_code_id"]) if row["promo_code_id"] else None,
            actor_player_id=int(row["buyer_player_id"]),
            order_id=int(row["order_id"]),
            meta={
                "commission_cents": int(row["commission_cents"]),
                "qualify_reason": reason_q,
            },
            now=ts,
        )
        _notify_creator(
            int(row["creator_player_id"]),
            subject="Creator commission available",
            body=(
                f"Commission of {int(row['commission_cents'])} cents is now available "
                f"for order #{int(row['order_id'])}."
            ),
            conn=conn,
        )
        released += 1
    return released


def reverse_commission_for_order(order_id: int, *, conn, now: Optional[float] = None) -> Tuple[bool, str]:
    if not schema_ready(conn):
        return False, "promo_unavailable"
    row = conn.execute(
        "SELECT id, status FROM shop_creator_ledger WHERE order_id = ? LIMIT 1;",
        (int(order_id),),
    ).fetchone()
    if not row:
        return True, "no_ledger"
    if str(row["status"]) == LEDGER_PAID:
        return False, "already_paid_reconcile"
    if str(row["status"]) == LEDGER_REVERSED:
        return True, "already_reversed"
    ts = _now(now)
    conn.execute(
        """
        UPDATE shop_creator_ledger
        SET status = ?, updated_at = ?
        WHERE id = ?;
        """,
        (LEDGER_REVERSED, ts, int(row["id"])),
    )
    return True, "ok"


def create_creator(
    *,
    conn,
    display_name: str,
    player_id: int,
    paypal_email: Optional[str] = None,
    payout_note: str = "",
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "promo_unavailable", None
    name = str(display_name or "").strip()[:80]
    pid = int(player_id)
    if not name or pid <= 0:
        return False, "invalid_creator", None
    exists = conn.execute("SELECT 1 FROM players WHERE id = ? LIMIT 1;", (pid,)).fetchone()
    if not exists:
        return False, "invalid_player", None
    if get_creator_by_player(pid, conn=conn):
        return False, "creator_exists", None
    ts = _now(now)
    cur = conn.execute(
        """
        INSERT INTO shop_creators (
            display_name, player_id, paypal_email, payout_note, active,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, ?, ?);
        """,
        (name, pid, (str(paypal_email).strip()[:120] or None) if paypal_email else None, str(payout_note or "")[:500], ts, ts),
    )
    return True, "ok", get_creator(int(cur.lastrowid), conn=conn)


def sync_vanity_referral_code(player_id: int, code: str, *, conn, now: Optional[float] = None) -> Tuple[bool, str]:
    """Set player_referral_codes.code to vanity promo (unique)."""
    from .referrals import ensure_referral_code, referrals_schema_ready

    if not referrals_schema_ready(conn):
        return False, "referrals_unavailable"
    normalized = normalize_code(code)
    if not _CODE_RE.match(normalized):
        return False, "invalid_code"
    ensure_referral_code(int(player_id), conn=conn, now=int(_now(now)))
    clash = conn.execute(
        """
        SELECT player_id FROM player_referral_codes
        WHERE UPPER(code) = ? AND player_id != ?
        LIMIT 1;
        """,
        (normalized, int(player_id)),
    ).fetchone()
    if clash:
        return False, "code_taken"
    # Also clash with other promo codes owned by someone else
    other = conn.execute(
        """
        SELECT p.id FROM shop_promo_codes p
        JOIN shop_creators c ON c.id = p.creator_id
        WHERE p.code = ? AND c.player_id != ?
        LIMIT 1;
        """,
        (normalized, int(player_id)),
    ).fetchone()
    if other:
        return False, "code_taken"
    conn.execute(
        "UPDATE player_referral_codes SET code = ? WHERE player_id = ?;",
        (normalized, int(player_id)),
    )
    return True, "ok"


def create_promo_code(
    *,
    conn,
    creator_id: int,
    code: str,
    discount_bps: int = DEFAULT_DISCOUNT_BPS,
    commission_bps: int = DEFAULT_COMMISSION_BPS,
    max_redemptions: Optional[int] = None,
    notes: str = "",
    sync_referral: bool = True,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "promo_unavailable", None
    creator = get_creator(int(creator_id), conn=conn)
    if not creator:
        return False, "creator_not_found", None
    normalized = normalize_code(code)
    if not _CODE_RE.match(normalized):
        return False, "invalid_code", None
    if get_promo_by_code(normalized, conn=conn, active_only=False):
        return False, "code_taken", None
    if sync_referral:
        ok_s, reason_s = sync_vanity_referral_code(
            int(creator["player_id"]), normalized, conn=conn, now=now
        )
        if not ok_s:
            return False, reason_s, None
    ts = _now(now)
    has_kind = column_exists(conn, "shop_promo_codes", "kind")
    if has_kind:
        cur = conn.execute(
            """
            INSERT INTO shop_promo_codes (
                code, kind, creator_id, discount_bps, commission_bps, max_redemptions,
                active, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?);
            """,
            (
                normalized,
                KIND_CREATOR,
                int(creator_id),
                max(0, min(9000, int(discount_bps))),
                max(0, min(5000, int(commission_bps))),
                int(max_redemptions) if max_redemptions is not None else None,
                str(notes or "")[:500],
                ts,
                ts,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO shop_promo_codes (
                code, creator_id, discount_bps, commission_bps, max_redemptions,
                active, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?);
            """,
            (
                normalized,
                int(creator_id),
                max(0, min(9000, int(discount_bps))),
                max(0, min(5000, int(commission_bps))),
                int(max_redemptions) if max_redemptions is not None else None,
                str(notes or "")[:500],
                ts,
                ts,
            ),
        )
    return True, "ok", get_promo_by_id(int(cur.lastrowid), conn=conn)


def create_campaign_code(
    *,
    conn,
    code: str,
    discount_bps: int = DEFAULT_DISCOUNT_BPS,
    max_redemptions: Optional[int] = None,
    notes: str = "",
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Event/giveaway discount code — shop redeem only, no commission/referral."""
    if not schema_ready(conn) or not campaign_schema_ready(conn):
        return False, "promo_unavailable", None
    normalized = normalize_code(code)
    if not _CODE_RE.match(normalized):
        return False, "invalid_code", None
    if get_promo_by_code(normalized, conn=conn, active_only=False):
        return False, "code_taken", None
    # Also clash with referral vanity codes
    if table_exists(conn, "player_referral_codes"):
        clash = conn.execute(
            "SELECT 1 FROM player_referral_codes WHERE UPPER(code) = ? LIMIT 1;",
            (normalized,),
        ).fetchone()
        if clash:
            return False, "code_taken", None
    ts = _now(now)
    dbps = max(0, min(9000, int(discount_bps)))
    if dbps <= 0:
        return False, "invalid_discount", None
    cur = conn.execute(
        """
        INSERT INTO shop_promo_codes (
            code, kind, creator_id, discount_bps, commission_bps, max_redemptions,
            active, notes, created_at, updated_at
        ) VALUES (?, ?, NULL, ?, 0, ?, 1, ?, ?, ?);
        """,
        (
            normalized,
            KIND_CAMPAIGN,
            dbps,
            int(max_redemptions) if max_redemptions is not None else None,
            str(notes or "")[:500],
            ts,
            ts,
        ),
    )
    return True, "ok", get_promo_by_id(int(cur.lastrowid), conn=conn)


def list_campaign_codes_admin(*, conn) -> List[Dict[str, Any]]:
    if not schema_ready(conn) or not campaign_schema_ready(conn):
        return []
    rows = conn.execute(
        """
        SELECT id, code, kind, discount_bps, commission_bps, max_redemptions,
               active, notes, created_at, updated_at
        FROM shop_promo_codes
        WHERE kind = 'campaign'
        ORDER BY id DESC;
        """
    ).fetchall()
    out = []
    for r in rows:
        pid = int(r["id"])
        out.append(
            {
                "id": pid,
                "code": str(r["code"]),
                "kind": KIND_CAMPAIGN,
                "discount_bps": int(r["discount_bps"] or 0),
                "max_redemptions": int(r["max_redemptions"]) if r["max_redemptions"] is not None else None,
                "redemptions": _redemption_count(pid, conn=conn),
                "active": int(r["active"] or 0) == 1,
                "notes": str(r["notes"] or ""),
                "created_at": float(r["created_at"] or 0),
            }
        )
    return out


def set_promo_active(promo_id: int, active: bool, *, conn, now: Optional[float] = None) -> Tuple[bool, str]:
    if not schema_ready(conn):
        return False, "promo_unavailable"
    ts = _now(now)
    conn.execute(
        "UPDATE shop_promo_codes SET active = ?, updated_at = ? WHERE id = ?;",
        (1 if active else 0, ts, int(promo_id)),
    )
    return True, "ok"


def set_creator_active(creator_id: int, active: bool, *, conn, now: Optional[float] = None) -> Tuple[bool, str]:
    if not schema_ready(conn):
        return False, "promo_unavailable"
    ts = _now(now)
    conn.execute(
        "UPDATE shop_creators SET active = ?, updated_at = ? WHERE id = ?;",
        (1 if active else 0, ts, int(creator_id)),
    )
    return True, "ok"


def ack_partner_terms(player_id: int, *, conn, now: Optional[float] = None) -> Tuple[bool, str]:
    creator = get_creator_by_player(int(player_id), conn=conn)
    if not creator or not creator["active"]:
        return False, "not_creator"
    ts = _now(now)
    conn.execute(
        """
        UPDATE shop_creators
        SET terms_acked_at = ?, terms_version = ?, updated_at = ?
        WHERE id = ?;
        """,
        (ts, PARTNER_TERMS_VERSION, ts, int(creator["id"])),
    )
    return True, "ok"


def ledger_balance(creator_id: int, *, conn) -> Dict[str, int]:
    rows = conn.execute(
        """
        SELECT status, COALESCE(SUM(commission_cents), 0) AS s
        FROM shop_creator_ledger
        WHERE creator_id = ?
        GROUP BY status;
        """,
        (int(creator_id),),
    ).fetchall()
    out = {"held": 0, "available": 0, "paid": 0, "reversed": 0}
    for row in rows:
        key = str(row["status"] or "")
        if key in out:
            out[key] = int(row["s"] or 0)
    return out


def create_payout_batch(
    *,
    conn,
    creator_id: int,
    ledger_ids: Sequence[int],
    note: str = "",
    marked_by: Optional[int] = None,
    allow_below_min: bool = False,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "promo_unavailable", None
    release_held_commissions(conn=conn, now=now, creator_id=int(creator_id))
    ids = [int(x) for x in ledger_ids if int(x) > 0]
    if not ids:
        return False, "empty_batch", None
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT id, commission_cents, status FROM shop_creator_ledger
        WHERE creator_id = ? AND id IN ({placeholders});
        """,
        (int(creator_id), *ids),
    ).fetchall()
    if len(rows) != len(ids):
        return False, "ledger_mismatch", None
    total = 0
    for row in rows:
        if str(row["status"]) != LEDGER_AVAILABLE:
            return False, "not_available", None
        total += int(row["commission_cents"] or 0)
    if total < min_payout_cents() and not allow_below_min:
        return False, "below_min_payout", None
    ts = _now(now)
    snap = [{"ledger_id": int(r["id"]), "commission_cents": int(r["commission_cents"])} for r in rows]
    cur = conn.execute(
        """
        INSERT INTO shop_creator_payouts (
            creator_id, total_cents, note, marked_by, created_at, csv_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        (
            int(creator_id),
            total,
            str(note or "")[:500],
            int(marked_by) if marked_by else None,
            ts,
            _json_dumps(snap),
        ),
    )
    batch_id = int(cur.lastrowid)
    conn.execute(
        f"""
        UPDATE shop_creator_ledger
        SET status = ?, payout_batch_id = ?, updated_at = ?
        WHERE creator_id = ? AND id IN ({placeholders}) AND status = ?;
        """,
        (LEDGER_PAID, batch_id, ts, int(creator_id), *ids, LEDGER_AVAILABLE),
    )
    creator = get_creator(int(creator_id), conn=conn)
    record_event(
        conn=conn,
        creator_id=int(creator_id),
        event_type=EVENT_PAYOUT,
        meta={"batch_id": batch_id, "total_cents": total},
        now=ts,
    )
    if creator:
        _notify_creator(
            int(creator["player_id"]),
            subject="Creator payout recorded",
            body=f"A payout batch of {total} cents was marked as paid (batch #{batch_id}).",
            conn=conn,
        )
    return True, "ok", {"batch_id": batch_id, "total_cents": total}


def funnel_counts(creator_id: int, *, conn) -> Dict[str, int]:
    rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS c
        FROM shop_promo_events
        WHERE creator_id = ?
        GROUP BY event_type;
        """,
        (int(creator_id),),
    ).fetchall()
    out = {
        "click": 0,
        "register": 0,
        "purchase": 0,
        "commission_held": 0,
        "commission_available": 0,
        "payout": 0,
    }
    for row in rows:
        key = str(row["event_type"] or "")
        if key in out:
            out[key] = int(row["c"] or 0)
    return out


def referral_counts_for_creator(creator_id: int, *, conn) -> Dict[str, int]:
    creator = get_creator(int(creator_id), conn=conn)
    if not creator:
        return {"pending": 0, "qualified": 0}
    from .referrals import count_successful_referrals, referrals_schema_ready

    if not referrals_schema_ready(conn):
        return {"pending": 0, "qualified": 0}
    qualified = count_successful_referrals(int(creator["player_id"]), conn=conn)
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM player_referrals
        WHERE referrer_player_id = ? AND status = 'pending';
        """,
        (int(creator["player_id"]),),
    ).fetchone()
    return {"pending": int(row["c"] or 0) if row else 0, "qualified": int(qualified)}


def list_ledger(
    creator_id: int,
    *,
    conn,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    lim = max(1, min(500, int(limit)))
    if status:
        rows = conn.execute(
            """
            SELECT id, creator_id, order_id, buyer_player_id, promo_code_id,
                   gross_cents, commission_cents, status, available_at,
                   payout_batch_id, created_at, updated_at
            FROM shop_creator_ledger
            WHERE creator_id = ? AND status = ?
            ORDER BY created_at DESC LIMIT ?;
            """,
            (int(creator_id), str(status), lim),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, creator_id, order_id, buyer_player_id, promo_code_id,
                   gross_cents, commission_cents, status, available_at,
                   payout_batch_id, created_at, updated_at
            FROM shop_creator_ledger
            WHERE creator_id = ?
            ORDER BY created_at DESC LIMIT ?;
            """,
            (int(creator_id), lim),
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "creator_id": int(r["creator_id"]),
            "order_id": int(r["order_id"]),
            "buyer_player_id": int(r["buyer_player_id"]),
            "promo_code_id": int(r["promo_code_id"]) if r["promo_code_id"] is not None else None,
            "gross_cents": int(r["gross_cents"] or 0),
            "commission_cents": int(r["commission_cents"] or 0),
            "status": str(r["status"]),
            "available_at": float(r["available_at"]) if r["available_at"] is not None else None,
            "payout_batch_id": int(r["payout_batch_id"]) if r["payout_batch_id"] is not None else None,
            "created_at": float(r["created_at"] or 0),
            "updated_at": float(r["updated_at"] or 0),
        }
        for r in rows
    ]


def ledger_csv(creator_id: int, *, conn) -> str:
    rows = list_ledger(int(creator_id), conn=conn, limit=500)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "id",
            "order_id",
            "buyer_player_id",
            "gross_cents",
            "commission_cents",
            "status",
            "available_at",
            "payout_batch_id",
            "created_at",
        ],
    )
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k) for k in writer.fieldnames})
    return buf.getvalue()


def creator_overview(player_id: int, *, conn) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "promo_unavailable", None
    creator = get_creator_by_player(int(player_id), conn=conn)
    if not creator or not creator["active"]:
        return False, "not_creator", None
    release_held_commissions(conn=conn, creator_id=int(creator["id"]))
    promo = conn.execute(
        """
        SELECT id, code, discount_bps, commission_bps, active
        FROM shop_promo_codes
        WHERE creator_id = ? AND active = 1
        ORDER BY id ASC LIMIT 1;
        """,
        (int(creator["id"]),),
    ).fetchone()
    bal = ledger_balance(int(creator["id"]), conn=conn)
    perf = creator_performance_stats(int(creator["id"]), conn=conn)
    return True, "ok", {
        "creator": creator,
        "terms_required": creator.get("terms_acked_at") is None
        or str(creator.get("terms_version") or "") != PARTNER_TERMS_VERSION,
        "terms_version": PARTNER_TERMS_VERSION,
        "promo": {
            "id": int(promo["id"]),
            "code": str(promo["code"]),
            "discount_bps": int(promo["discount_bps"]),
            "commission_bps": int(promo["commission_bps"]),
        }
        if promo
        else None,
        "funnel": funnel_counts(int(creator["id"]), conn=conn),
        "referrals": referral_counts_for_creator(int(creator["id"]), conn=conn),
        "performance": perf,
        "balance": bal,
        "min_payout_cents": min_payout_cents(),
        "hold_sec": commission_hold_sec(),
        "min_buyer_score": min_buyer_score(),
        "ledger": list_ledger(int(creator["id"]), conn=conn, limit=50),
    }


def list_creators_admin(*, conn) -> List[Dict[str, Any]]:
    if not schema_ready(conn):
        return []
    rows = conn.execute(
        """
        SELECT id, display_name, player_id, paypal_email, payout_note, active,
               terms_acked_at, terms_version, created_at, updated_at
        FROM shop_creators
        ORDER BY id DESC;
        """
    ).fetchall()
    out = []
    for row in rows:
        c = _creator_from_row(row)
        c["balance"] = ledger_balance(int(c["id"]), conn=conn)
        c["funnel"] = funnel_counts(int(c["id"]), conn=conn)
        c["referrals"] = referral_counts_for_creator(int(c["id"]), conn=conn)
        c["performance"] = creator_performance_stats(int(c["id"]), conn=conn)
        codes = conn.execute(
            """
            SELECT id, code, discount_bps, commission_bps, active, max_redemptions
            FROM shop_promo_codes WHERE creator_id = ? ORDER BY id ASC;
            """,
            (int(c["id"]),),
        ).fetchall()
        c["codes"] = [
            {
                "id": int(r["id"]),
                "code": str(r["code"]),
                "discount_bps": int(r["discount_bps"]),
                "commission_bps": int(r["commission_bps"]),
                "active": int(r["active"] or 0) == 1,
                "max_redemptions": int(r["max_redemptions"]) if r["max_redemptions"] is not None else None,
            }
            for r in codes
        ]
        out.append(c)
    return out


def _notify_creator(player_id: int, *, subject: str, body: str, conn) -> None:
    try:
        from .messages import create_message

        create_message(
            int(player_id),
            subject,
            body,
            category="system",
            sender_name="Genesis Colonies",
            metadata={"source": "shop_promos"},
            conn=conn,
        )
    except Exception:
        pass
