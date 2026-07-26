"""
EPIC-23 / GC-2301–2302 — Shop catalog, orders, fulfillment.

Owner: shop catalog + order lifecycle. Providers live in payment_providers.py.
Grants use battle_pass.unlock_premium / grant_inventory_item / timekeeper.credit /
playercard.unlock_* only.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import table_exists

PROVIDERS = frozenset({"stripe", "paypal", "test"})
KIND_ENTITLEMENT = "entitlement"
KIND_TIMEKEEPER = "timekeeper"
KIND_INVENTORY_BUNDLE = "inventory_bundle"
KIND_COSMETIC_UNLOCK = "cosmetic_unlock"
ALLOWED_KINDS = frozenset(
    {KIND_ENTITLEMENT, KIND_TIMEKEEPER, KIND_INVENTORY_BUNDLE, KIND_COSMETIC_UNLOCK}
)

SKU_SEASON_PASS = "season_pass_current"

STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_FULFILLED = "fulfilled"
STATUS_FAILED = "failed"
STATUS_REFUNDED = "refunded"

# Bump when reseeding prices/payloads into existing DBs (upsert).
CATALOG_VERSION = 5

# Free-Baseline Value Balance (GC-2310…2313):
# Paid sells scarce flexible TK + dense high-tier packs; domain boosters must beat ~2× login-month skip.
# Static art under static/img/shop/ — relative path for url_for('static', …).
SHOP_SKU_IMAGES: Dict[str, str] = {
    SKU_SEASON_PASS: "img/pass/season_pass.webp",
    "tk_pack_s": "img/pass/timekeeper.webp",
    "tk_pack_m": "img/pass/timekeeper.webp",
    "tk_pack_l": "img/pass/timekeeper.webp",
    "booster_pack_starter": "img/pass/build_boost.webp",
    "container_pack_rare": "img/pass/rare_container.webp",
    "commander_supply_pack": "img/pass/relic_container.webp",
    "name_style_ash": "img/pass/premium.webp",
    "name_style_signal": "img/pass/premium.webp",
    "name_style_etched": "img/pass/premium.webp",
    "name_style_relic": "img/pass/premium.webp",
    "name_style_imperial": "img/pass/premium.webp",
    "name_style_plasma": "img/pass/premium.webp",
    "name_style_void": "img/pass/premium.webp",
    "identity_pack_signal": "img/pass/season_pass.webp",
}

DEFAULT_CATALOG: Tuple[Dict[str, Any], ...] = (
    {
        "sku": SKU_SEASON_PASS,
        "kind": KIND_ENTITLEMENT,
        "title_key": "shop_sku_season_pass",
        "hint_key": "shop_sku_season_pass_hint",
        "price_cents": 499,
        "currency": "eur",
        "sort_order": 10,
        "payload": {"entitlement": "battle_pass_premium"},
    },
    {
        "sku": "tk_pack_s",
        "kind": KIND_TIMEKEEPER,
        "title_key": "shop_sku_tk_s",
        "hint_key": "shop_sku_tk_s_hint",
        "price_cents": 99,
        "currency": "eur",
        "sort_order": 20,
        "payload": {"timekeeper_sec": 6 * 3600},
    },
    {
        "sku": "tk_pack_m",
        "kind": KIND_TIMEKEEPER,
        "title_key": "shop_sku_tk_m",
        "hint_key": "shop_sku_tk_m_hint",
        "price_cents": 299,
        "currency": "eur",
        "sort_order": 30,
        "payload": {"timekeeper_sec": 24 * 3600},
    },
    {
        "sku": "tk_pack_l",
        "kind": KIND_TIMEKEEPER,
        "title_key": "shop_sku_tk_l",
        "hint_key": "shop_sku_tk_l_hint",
        "price_cents": 599,
        "currency": "eur",
        "sort_order": 40,
        "payload": {"timekeeper_sec": 72 * 3600},
    },
    {
        "sku": "booster_pack_starter",
        "kind": KIND_INVENTORY_BUNDLE,
        "title_key": "shop_sku_booster_starter",
        "hint_key": "shop_sku_booster_starter_hint",
        "price_cents": 299,
        "currency": "eur",
        "sort_order": 50,
        "payload": {
            "items": [
                {"item_key": "booster_build_24h", "amount": 6},
                {"item_key": "booster_research_24h", "amount": 6},
                {"item_key": "booster_build_6h", "amount": 8},
                {"item_key": "booster_research_6h", "amount": 8},
                {"item_key": "booster_production_50", "amount": 4},
            ]
        },
    },
    {
        "sku": "container_pack_rare",
        "kind": KIND_INVENTORY_BUNDLE,
        "title_key": "shop_sku_container_rare",
        "hint_key": "shop_sku_container_rare_hint",
        "price_cents": 299,
        "currency": "eur",
        "sort_order": 60,
        "payload": {
            "items": [
                {"item_key": "container_rare", "amount": 8},
                {"item_key": "container_epic", "amount": 4},
                {"item_key": "container_mythic", "amount": 2},
                {"item_key": "container_relic", "amount": 1},
            ]
        },
    },
    {
        "sku": "commander_supply_pack",
        "kind": KIND_INVENTORY_BUNDLE,
        "title_key": "shop_sku_commander_supply",
        "hint_key": "shop_sku_commander_supply_hint",
        "price_cents": 999,
        "currency": "eur",
        "sort_order": 70,
        "payload": {
            "timekeeper_sec": 48 * 3600,
            "items": [
                {"item_key": "booster_build_24h", "amount": 6},
                {"item_key": "booster_research_24h", "amount": 6},
                {"item_key": "booster_production_100", "amount": 3},
                {"item_key": "container_epic", "amount": 4},
                {"item_key": "container_mythic", "amount": 3},
                {"item_key": "container_ancient_relic", "amount": 2},
                {"item_key": "container_relic", "amount": 2},
            ],
        },
    },
    {
        "sku": "name_style_ash",
        "kind": KIND_COSMETIC_UNLOCK,
        "title_key": "shop_sku_name_ash",
        "hint_key": "shop_sku_name_ash_hint",
        "price_cents": 99,
        "currency": "eur",
        "sort_order": 100,
        "payload": {
            "unlocks": [{"kind": "name_style", "key": "ash"}],
            "preview_style": "ash",
        },
    },
    {
        "sku": "name_style_signal",
        "kind": KIND_COSMETIC_UNLOCK,
        "title_key": "shop_sku_name_signal",
        "hint_key": "shop_sku_name_signal_hint",
        "price_cents": 99,
        "currency": "eur",
        "sort_order": 110,
        "payload": {
            "unlocks": [{"kind": "name_style", "key": "signal"}],
            "preview_style": "signal",
        },
    },
    {
        "sku": "name_style_etched",
        "kind": KIND_COSMETIC_UNLOCK,
        "title_key": "shop_sku_name_etched",
        "hint_key": "shop_sku_name_etched_hint",
        "price_cents": 99,
        "currency": "eur",
        "sort_order": 120,
        "payload": {
            "unlocks": [{"kind": "name_style", "key": "etched"}],
            "preview_style": "etched",
        },
    },
    {
        "sku": "name_style_relic",
        "kind": KIND_COSMETIC_UNLOCK,
        "title_key": "shop_sku_name_relic",
        "hint_key": "shop_sku_name_relic_hint",
        "price_cents": 149,
        "currency": "eur",
        "sort_order": 130,
        "payload": {
            "unlocks": [{"kind": "name_style", "key": "relic"}],
            "preview_style": "relic",
        },
    },
    {
        "sku": "name_style_imperial",
        "kind": KIND_COSMETIC_UNLOCK,
        "title_key": "shop_sku_name_imperial",
        "hint_key": "shop_sku_name_imperial_hint",
        "price_cents": 199,
        "currency": "eur",
        "sort_order": 140,
        "payload": {
            "unlocks": [{"kind": "name_style", "key": "imperial"}],
            "preview_style": "imperial",
        },
    },
    {
        "sku": "name_style_plasma",
        "kind": KIND_COSMETIC_UNLOCK,
        "title_key": "shop_sku_name_plasma",
        "hint_key": "shop_sku_name_plasma_hint",
        "price_cents": 199,
        "currency": "eur",
        "sort_order": 150,
        "payload": {
            "unlocks": [{"kind": "name_style", "key": "plasma"}],
            "preview_style": "plasma",
        },
    },
    {
        "sku": "name_style_void",
        "kind": KIND_COSMETIC_UNLOCK,
        "title_key": "shop_sku_name_void",
        "hint_key": "shop_sku_name_void_hint",
        "price_cents": 199,
        "currency": "eur",
        "sort_order": 160,
        "payload": {
            "unlocks": [{"kind": "name_style", "key": "void"}],
            "preview_style": "void",
        },
    },
    {
        "sku": "identity_pack_signal",
        "kind": KIND_COSMETIC_UNLOCK,
        "title_key": "shop_sku_identity_pack",
        "hint_key": "shop_sku_identity_pack_hint",
        "price_cents": 249,
        "currency": "eur",
        "sort_order": 170,
        "payload": {
            "unlocks": [
                {"kind": "name_style", "key": "signal"},
                {"kind": "name_style", "key": "etched"},
                {"kind": "title_flair", "key": "etched"},
            ],
            "preview_style": "signal",
        },
    },
)


def shop_image_for_sku(sku: str) -> Optional[str]:
    path = SHOP_SKU_IMAGES.get(str(sku or "").strip())
    return str(path) if path else None


def schema_ready(conn) -> bool:
    return (
        table_exists(conn, "shop_products")
        and table_exists(conn, "shop_orders")
        and table_exists(conn, "shop_payment_events")
    )


def _shop_products_allows_cosmetic_unlock(conn) -> bool:
    """True when shop_products.kind CHECK includes cosmetic_unlock (migration 115)."""
    from .db import get_db_backend

    if get_db_backend() == "postgres":
        # PG: try a savepoint probe instead of parsing pg_constraint.
        return True
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'shop_products' LIMIT 1;"
        ).fetchone()
    except Exception:
        return False
    if not row:
        return False
    sql = str(row["sql"] if hasattr(row, "keys") else row[0] or "")
    return "cosmetic_unlock" in sql.lower()


def ensure_shop_products_kind_schema(conn) -> bool:
    """
    Rebuild shop_products if kind CHECK predates cosmetic_unlock.
    Idempotent; needed when migration 115 was skipped/partial on a live DB.
    """
    if not table_exists(conn, "shop_products"):
        return False
    if _shop_products_allows_cosmetic_unlock(conn):
        return False
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_products__kind_v4 (
            sku TEXT NOT NULL PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('entitlement', 'timekeeper', 'inventory_bundle', 'cosmetic_unlock')),
            title_key TEXT NOT NULL DEFAULT '',
            hint_key TEXT NOT NULL DEFAULT '',
            price_cents INTEGER NOT NULL CHECK (price_cents > 0),
            currency TEXT NOT NULL DEFAULT 'eur',
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            payload_json TEXT NOT NULL DEFAULT '{}',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO shop_products__kind_v4
            (sku, kind, title_key, hint_key, price_cents, currency, active,
             payload_json, sort_order, created_at, updated_at)
        SELECT sku, kind, title_key, hint_key, price_cents, currency, active,
               payload_json, sort_order, created_at, updated_at
        FROM shop_products;
        """
    )
    conn.execute("DROP TABLE IF EXISTS shop_products;")
    conn.execute("ALTER TABLE shop_products__kind_v4 RENAME TO shop_products;")
    return True


def is_shop_enabled() -> bool:
    val = str(os.environ.get("SHOP_ENABLED", "0") or "0").strip().lower()
    return val in ("1", "true", "yes", "on")


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except Exception:
        return {}
    return dict(data) if isinstance(data, dict) else {}


def ensure_catalog_seeded(conn, *, now: Optional[float] = None) -> int:
    """Upsert default SKUs from code (server truth). Returns rows touched."""
    if not schema_ready(conn):
        return 0
    ensure_shop_products_kind_schema(conn)
    ts = float(now if now is not None else time.time())
    touched = 0
    for entry in DEFAULT_CATALOG:
        sku = str(entry["sku"])
        kind = str(entry["kind"])
        title_key = str(entry["title_key"])
        hint_key = str(entry["hint_key"])
        price_cents = int(entry["price_cents"])
        currency = str(entry.get("currency") or "eur")
        payload_json = _json_dumps(entry.get("payload") or {})
        sort_order = int(entry.get("sort_order") or 0)
        existing = conn.execute(
            "SELECT sku FROM shop_products WHERE sku = ? LIMIT 1;",
            (sku,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE shop_products
                SET kind = ?, title_key = ?, hint_key = ?, price_cents = ?,
                    currency = ?, active = 1, payload_json = ?, sort_order = ?,
                    updated_at = ?
                WHERE sku = ?;
                """,
                (
                    kind,
                    title_key,
                    hint_key,
                    price_cents,
                    currency,
                    payload_json,
                    sort_order,
                    ts,
                    sku,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO shop_products (
                    sku, kind, title_key, hint_key, price_cents, currency,
                    active, payload_json, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?);
                """,
                (
                    sku,
                    kind,
                    title_key,
                    hint_key,
                    price_cents,
                    currency,
                    payload_json,
                    sort_order,
                    ts,
                    ts,
                ),
            )
        touched += 1
    return touched


def get_product(sku: str, *, conn, active_only: bool = True) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn):
        return None
    ensure_catalog_seeded(conn)
    key = str(sku or "").strip()
    if not key:
        return None
    row = conn.execute(
        """
        SELECT sku, kind, title_key, hint_key, price_cents, currency,
               active, payload_json, sort_order
        FROM shop_products WHERE sku = ? LIMIT 1;
        """,
        (key,),
    ).fetchone()
    if not row:
        return None
    if active_only and not int(row["active"] or 0):
        return None
    return _product_from_row(row)


def list_catalog(*, conn, active_only: bool = True) -> List[Dict[str, Any]]:
    if not schema_ready(conn):
        return []
    ensure_catalog_seeded(conn)
    sql = """
        SELECT sku, kind, title_key, hint_key, price_cents, currency,
               active, payload_json, sort_order
        FROM shop_products
    """
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY sort_order ASC, sku ASC;"
    rows = conn.execute(sql).fetchall()
    return [_product_from_row(r) for r in rows]


def _product_from_row(row) -> Dict[str, Any]:
    return {
        "sku": str(row["sku"]),
        "kind": str(row["kind"]),
        "title_key": str(row["title_key"] or ""),
        "hint_key": str(row["hint_key"] or ""),
        "price_cents": int(row["price_cents"]),
        "currency": str(row["currency"] or "eur").lower(),
        "active": bool(int(row["active"] or 0)),
        "payload": _json_loads(row["payload_json"]),
        "sort_order": int(row["sort_order"] or 0),
        "price_label": _format_price(int(row["price_cents"]), str(row["currency"] or "eur")),
    }


def _format_price(cents: int, currency: str) -> str:
    cur = (currency or "eur").upper()
    amount = max(0, int(cents)) / 100.0
    if cur == "EUR":
        return f"{amount:.2f} €".replace(".", ",")
    return f"{amount:.2f} {cur}"


def get_order(order_id: int, *, conn) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn) or int(order_id) <= 0:
        return None
    row = conn.execute(
        """
        SELECT id, player_id, sku, provider, provider_session_id, provider_payment_id,
               amount_cents, currency, status, fulfill_reason, created_at, paid_at,
               fulfilled_at, metadata_json
        FROM shop_orders WHERE id = ? LIMIT 1;
        """,
        (int(order_id),),
    ).fetchone()
    if not row:
        return None
    return _order_from_row(row)


def find_order_by_session(
    provider: str, session_id: str, *, conn
) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn):
        return None
    row = conn.execute(
        """
        SELECT id, player_id, sku, provider, provider_session_id, provider_payment_id,
               amount_cents, currency, status, fulfill_reason, created_at, paid_at,
               fulfilled_at, metadata_json
        FROM shop_orders
        WHERE provider = ? AND provider_session_id = ?
        LIMIT 1;
        """,
        (str(provider), str(session_id)),
    ).fetchone()
    return _order_from_row(row) if row else None


def find_order_by_payment(
    provider: str, payment_id: str, *, conn
) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn) or not str(payment_id or "").strip():
        return None
    row = conn.execute(
        """
        SELECT id, player_id, sku, provider, provider_session_id, provider_payment_id,
               amount_cents, currency, status, fulfill_reason, created_at, paid_at,
               fulfilled_at, metadata_json
        FROM shop_orders
        WHERE provider = ? AND provider_payment_id = ?
        LIMIT 1;
        """,
        (str(provider), str(payment_id).strip()),
    ).fetchone()
    return _order_from_row(row) if row else None


def recover_paypal_return_for_player(
    player_id: int,
    paypal_order_id: str,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Idempotent recovery when PayPal charged but shop_orders row is missing
    (e.g. local checkout + production return URL).
    Creates a pending order for the logged-in player from the PayPal order,
    then mark_paid + fulfill.
    """
    from . import payment_providers as pp

    pid = int(player_id)
    token = str(paypal_order_id or "").strip()
    if pid <= 0 or not token:
        return False, "invalid_recover", None
    if not schema_ready(conn) or not is_shop_enabled():
        return False, "shop_unavailable", None

    existing = find_order_by_session("paypal", token, conn=conn)
    if existing and int(existing["player_id"]) != pid:
        return False, "order_owner_mismatch", None
    if existing and existing["status"] == STATUS_FULFILLED:
        return True, "already_fulfilled", existing

    ok_get, get_reason, pdata = pp.paypal_fetch_order(token)
    if not ok_get or not isinstance(pdata, dict):
        return False, get_reason or "paypal_fetch_failed", existing
    summary = pp.paypal_order_capture_summary(pdata)
    status = str(summary.get("status") or "")
    if status == "APPROVED":
        cok, creason, cap = pp.paypal_capture_order(token)
        if not cok:
            return False, creason or "paypal_capture_failed", existing
        if isinstance(cap, dict):
            summary = pp.paypal_order_capture_summary(cap)
            status = str(summary.get("status") or status)
    if status != "COMPLETED":
        return False, "paypal_not_paid", existing

    sku = str(summary.get("sku") or "").strip()
    amount_cents = int(summary.get("amount_cents") or 0)
    capture_id = str(summary.get("capture_id") or "").strip() or token
    if not sku:
        return False, "unknown_sku", existing

    by_pay = find_order_by_payment("paypal", capture_id, conn=conn)
    if by_pay:
        if int(by_pay["player_id"]) != pid:
            return False, "order_owner_mismatch", None
        if by_pay["status"] == STATUS_FULFILLED:
            return True, "already_fulfilled", by_pay
        existing = by_pay

    product = get_product(sku, conn=conn, active_only=False)
    if not product:
        return False, "unknown_sku", existing
    if int(product["price_cents"]) != amount_cents:
        return False, "amount_mismatch", existing
    if str(product.get("currency") or "eur").lower() != str(
        summary.get("currency") or "eur"
    ).lower():
        return False, "currency_mismatch", existing

    order = existing
    if order is None:
        ok_c, reason_c, created = create_pending_order(
            pid,
            sku,
            "paypal",
            conn=conn,
            now=now,
            metadata={"recovered_from": "paypal_return", "paypal_order_id": token},
            allow_owned=True,
        )
        if not ok_c or not created:
            return False, reason_c, None
        order = created["order"]
        attach_provider_session(
            int(order["id"]),
            token,
            conn=conn,
            metadata={"recovered_from": "paypal_return"},
        )

    return process_paid_event(
        provider="paypal",
        event_id=f"return_recover:{token}:{int(order['id'])}",
        order_id=int(order["id"]),
        provider_session_id=token,
        provider_payment_id=capture_id,
        conn=conn,
        payload={"source": "paypal_return_recover", "summary": summary},
        now=now,
    )


def _order_from_row(row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "player_id": int(row["player_id"]),
        "sku": str(row["sku"]),
        "provider": str(row["provider"]),
        "provider_session_id": row["provider_session_id"],
        "provider_payment_id": row["provider_payment_id"],
        "amount_cents": int(row["amount_cents"]),
        "currency": str(row["currency"] or "eur"),
        "status": str(row["status"]),
        "fulfill_reason": row["fulfill_reason"],
        "created_at": float(row["created_at"] or 0),
        "paid_at": float(row["paid_at"]) if row["paid_at"] is not None else None,
        "fulfilled_at": float(row["fulfilled_at"]) if row["fulfilled_at"] is not None else None,
        "metadata": _json_loads(row["metadata_json"]),
    }


def create_pending_order(
    player_id: int,
    sku: str,
    provider: str,
    *,
    conn,
    now: Optional[float] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    allow_owned: bool = False,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "shop_unavailable", None
    if not is_shop_enabled():
        return False, "shop_disabled", None
    pid = int(player_id)
    prov = str(provider or "").strip().lower()
    if pid <= 0:
        return False, "invalid_player", None
    if prov not in PROVIDERS:
        return False, "invalid_provider", None
    product = get_product(sku, conn=conn)
    if not product:
        return False, "unknown_sku", None
    if product["kind"] not in ALLOWED_KINDS:
        return False, "forbidden_sku", None

    if product["sku"] == SKU_SEASON_PASS and not allow_owned:
        owned, own_reason = _season_pass_owned(pid, conn=conn)
        if owned:
            return False, "already_owned", None
        if own_reason == "no_season":
            return False, "no_season", None

    if (
        str(product.get("kind")) == KIND_COSMETIC_UNLOCK
        and not allow_owned
        and _cosmetic_payload_owned(pid, product.get("payload") or {}, conn=conn)
    ):
        return False, "already_owned", None

    ts = float(now if now is not None else time.time())
    cur = conn.execute(
        """
        INSERT INTO shop_orders (
            player_id, sku, provider, amount_cents, currency, status,
            created_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            pid,
            product["sku"],
            prov,
            int(product["price_cents"]),
            str(product["currency"]),
            STATUS_PENDING,
            ts,
            _json_dumps(metadata or {}),
        ),
    )
    order_id = int(cur.lastrowid)
    order = get_order(order_id, conn=conn)
    return True, "ok", {"order": order, "product": product}


def attach_provider_session(
    order_id: int,
    session_id: str,
    *,
    conn,
    metadata: Optional[Mapping[str, Any]] = None,
) -> None:
    order = get_order(int(order_id), conn=conn)
    if not order:
        return
    meta = dict(order.get("metadata") or {})
    if metadata:
        meta.update(dict(metadata))
    conn.execute(
        """
        UPDATE shop_orders
        SET provider_session_id = ?, metadata_json = ?
        WHERE id = ?;
        """,
        (str(session_id), _json_dumps(meta), int(order_id)),
    )


def mark_paid(
    order_id: int,
    *,
    conn,
    provider_payment_id: Optional[str] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    order = get_order(int(order_id), conn=conn)
    if not order:
        return False, "order_not_found", None
    if order["status"] in (STATUS_FULFILLED, STATUS_PAID):
        return True, "already_paid", order
    if order["status"] not in (STATUS_PENDING, STATUS_FAILED):
        return False, "invalid_status", order
    ts = float(now if now is not None else time.time())
    payment_id = str(provider_payment_id or order.get("provider_payment_id") or "").strip() or None
    conn.execute(
        """
        UPDATE shop_orders
        SET status = ?, paid_at = ?, provider_payment_id = COALESCE(?, provider_payment_id)
        WHERE id = ?;
        """,
        (STATUS_PAID, ts, payment_id, int(order_id)),
    )
    return True, "ok", get_order(int(order_id), conn=conn)


def fulfill_order(
    order_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Idempotent fulfill: grants rewards once, then status=fulfilled."""
    order = get_order(int(order_id), conn=conn)
    if not order:
        return False, "order_not_found", None
    if order["status"] == STATUS_FULFILLED:
        return True, "already_fulfilled", order
    if order["status"] not in (STATUS_PAID, STATUS_PENDING):
        return False, "not_paid", order

    # Ensure paid timestamp even if called directly after mark_paid in same txn.
    if order["status"] == STATUS_PENDING:
        ok_paid, reason_paid, order = mark_paid(int(order_id), conn=conn, now=now)
        if not ok_paid:
            return False, reason_paid, order

    product = get_product(order["sku"], conn=conn, active_only=False)
    if not product:
        return False, "unknown_sku", order

    ts = float(now if now is not None else time.time())
    grant_reason = "ok"
    granted: Dict[str, Any] = {}

    kind = str(product["kind"])
    payload = product.get("payload") or {}
    pid = int(order["player_id"])
    source = f"shop:{order['provider']}:{order['id']}"

    if kind == KIND_ENTITLEMENT:
        from .battle_pass import unlock_premium

        owned, _ = _season_pass_owned(pid, conn=conn)
        if owned:
            grant_reason = "already_owned"
            granted = {"premium_unlocked": True, "skipped": True}
        else:
            ok, reason, result = unlock_premium(
                pid,
                conn=conn,
                source=str(order["provider"]),
                now=ts,
            )
            if not ok:
                conn.execute(
                    """
                    UPDATE shop_orders SET status = ?, fulfill_reason = ? WHERE id = ?;
                    """,
                    (STATUS_FAILED, str(reason), int(order_id)),
                )
                return False, reason, get_order(int(order_id), conn=conn)
            grant_reason = "ok"
            granted = result or {"premium_unlocked": True}
    elif kind == KIND_TIMEKEEPER:
        from .timekeeper import credit, get_balance

        sec = max(0, int(payload.get("timekeeper_sec") or 0))
        if sec <= 0:
            return False, "invalid_payload", order
        bal = credit(pid, sec, source, conn=conn)
        granted = {"timekeeper_sec": sec, "balance_sec": bal}
    elif kind == KIND_INVENTORY_BUNDLE:
        from .inventory import grant_inventory_item
        from .timekeeper import credit

        items = payload.get("items") or []
        tk_sec = max(0, int(payload.get("timekeeper_sec") or 0))
        if (not isinstance(items, list) or not items) and tk_sec <= 0:
            return False, "invalid_payload", order
        granted_items = []
        for entry in items if isinstance(items, list) else []:
            if not isinstance(entry, Mapping):
                continue
            key = str(entry.get("item_key") or "").strip()
            amt = max(0, int(entry.get("amount") or 0))
            if not key or amt <= 0:
                continue
            # Policy: never grant ships/defense/resources via shop payload.
            if key.startswith(("ship_", "defense_", "metal", "crystal", "fuel")):
                return False, "forbidden_grant", order
            ok_grant = grant_inventory_item(
                pid, key, amt, conn=conn, metadata={"source": source}
            )
            if not ok_grant:
                conn.execute(
                    """
                    UPDATE shop_orders SET status = ?, fulfill_reason = ? WHERE id = ?;
                    """,
                    (STATUS_FAILED, "grant_failed", int(order_id)),
                )
                return False, "grant_failed", get_order(int(order_id), conn=conn)
            granted_items.append({"item_key": key, "amount": amt})
        granted = {"items": granted_items}
        if tk_sec > 0:
            bal = credit(pid, tk_sec, source, conn=conn)
            granted["timekeeper_sec"] = tk_sec
            granted["balance_sec"] = bal
    elif kind == KIND_COSMETIC_UNLOCK:
        from .playercard import (
            COSMETIC_KIND_NAME_STYLE,
            COSMETIC_KIND_TITLE_FLAIR,
            player_has_name_style,
            player_has_title_flair,
            unlock_name_style,
            unlock_title_flair,
        )

        unlocks = payload.get("unlocks") or []
        if not isinstance(unlocks, list) or not unlocks:
            return False, "invalid_payload", order
        granted_unlocks: List[str] = []
        all_already = True
        for entry in unlocks:
            if not isinstance(entry, Mapping):
                continue
            ukind = str(entry.get("kind") or "").strip().lower()
            ukey = str(entry.get("key") or "").strip().lower()
            if not ukind or not ukey:
                continue
            if ukind == COSMETIC_KIND_NAME_STYLE:
                if player_has_name_style(pid, ukey, conn=conn):
                    granted_unlocks.append(f"name_style:{ukey}:owned")
                    continue
                all_already = False
                ok_u, reason_u = unlock_name_style(
                    pid, ukey, conn=conn, source=source, now=int(ts)
                )
                if not ok_u:
                    conn.execute(
                        """
                        UPDATE shop_orders SET status = ?, fulfill_reason = ? WHERE id = ?;
                        """,
                        (STATUS_FAILED, str(reason_u), int(order_id)),
                    )
                    return False, reason_u, get_order(int(order_id), conn=conn)
                granted_unlocks.append(f"name_style:{ukey}")
            elif ukind == COSMETIC_KIND_TITLE_FLAIR:
                if player_has_title_flair(pid, ukey, conn=conn):
                    granted_unlocks.append(f"title_flair:{ukey}:owned")
                    continue
                all_already = False
                ok_u, reason_u = unlock_title_flair(
                    pid, ukey, conn=conn, source=source, now=int(ts)
                )
                if not ok_u:
                    conn.execute(
                        """
                        UPDATE shop_orders SET status = ?, fulfill_reason = ? WHERE id = ?;
                        """,
                        (STATUS_FAILED, str(reason_u), int(order_id)),
                    )
                    return False, reason_u, get_order(int(order_id), conn=conn)
                granted_unlocks.append(f"title_flair:{ukey}")
            else:
                return False, "forbidden_grant", order
        if not granted_unlocks:
            return False, "invalid_payload", order
        grant_reason = "already_owned" if all_already else "ok"
        granted = {"unlocks": granted_unlocks}
    else:
        return False, "forbidden_sku", order

    conn.execute(
        """
        UPDATE shop_orders
        SET status = ?, fulfill_reason = ?, fulfilled_at = ?,
            paid_at = COALESCE(paid_at, ?)
        WHERE id = ?;
        """,
        (STATUS_FULFILLED, grant_reason, ts, ts, int(order_id)),
    )
    out = get_order(int(order_id), conn=conn)
    if out is not None:
        out["granted"] = granted
        out["fulfill_reason"] = grant_reason
    return True, grant_reason, out


def record_payment_event(
    provider: str,
    event_id: str,
    *,
    conn,
    order_id: Optional[int] = None,
    payload: Optional[Mapping[str, Any]] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str]:
    """Insert webhook event. Returns (True, 'ok') or (True, 'duplicate') or failure."""
    if not schema_ready(conn):
        return False, "shop_unavailable"
    eid = str(event_id or "").strip()
    prov = str(provider or "").strip().lower()
    if not eid or not prov:
        return False, "invalid_event"
    existing = conn.execute(
        """
        SELECT id FROM shop_payment_events
        WHERE provider = ? AND event_id = ?
        LIMIT 1;
        """,
        (prov, eid),
    ).fetchone()
    if existing:
        return True, "duplicate"
    ts = float(now if now is not None else time.time())
    conn.execute(
        """
        INSERT INTO shop_payment_events (provider, event_id, order_id, payload_json, processed_at)
        VALUES (?, ?, ?, ?, ?);
        """,
        (
            prov,
            eid,
            int(order_id) if order_id else None,
            _json_dumps(payload or {}),
            ts,
        ),
    )
    return True, "ok"


def process_paid_event(
    *,
    provider: str,
    event_id: str,
    order_id: Optional[int] = None,
    provider_session_id: Optional[str] = None,
    provider_payment_id: Optional[str] = None,
    conn,
    payload: Optional[Mapping[str, Any]] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Idempotent webhook handler path:
    record event → resolve order → mark_paid → fulfill_order.
    """
    ok_ev, ev_reason = record_payment_event(
        provider,
        event_id,
        conn=conn,
        order_id=order_id,
        payload=payload,
        now=now,
    )
    if not ok_ev:
        return False, ev_reason, None
    if ev_reason == "duplicate":
        # Still return current order if known.
        order = None
        if order_id:
            order = get_order(int(order_id), conn=conn)
        elif provider_session_id:
            order = find_order_by_session(provider, provider_session_id, conn=conn)
        return True, "duplicate", order

    order = None
    if order_id:
        order = get_order(int(order_id), conn=conn)
    if order is None and provider_session_id:
        order = find_order_by_session(provider, str(provider_session_id), conn=conn)
    if order is None:
        return False, "order_not_found", None

    ok_paid, paid_reason, order = mark_paid(
        int(order["id"]),
        conn=conn,
        provider_payment_id=provider_payment_id,
        now=now,
    )
    if not ok_paid and paid_reason not in ("already_paid",):
        return False, paid_reason, order

    return fulfill_order(int(order["id"]), conn=conn, now=now)


def _season_pass_owned(player_id: int, *, conn) -> Tuple[bool, str]:
    from .battle_pass import get_active_season, schema_ready as bp_ready

    if not bp_ready(conn):
        return False, "battle_pass_unavailable"
    season = get_active_season(conn)
    if not season:
        return False, "no_season"
    sid = int(season["id"])
    row = conn.execute(
        """
        SELECT premium_unlocked FROM player_battle_pass
        WHERE player_id = ? AND season_id = ?
        LIMIT 1;
        """,
        (int(player_id), sid),
    ).fetchone()
    if row and int(row["premium_unlocked"] or 0):
        return True, "ok"
    from .premium_entitlements import KIND_BATTLE_PASS_PREMIUM, has_entitlement

    if has_entitlement(
        int(player_id), KIND_BATTLE_PASS_PREMIUM, conn=conn, season_id=sid
    ):
        return True, "ok"
    return False, "ok"


def _cosmetic_payload_owned(player_id: int, payload: Mapping[str, Any], *, conn) -> bool:
    """True when every unlock in a cosmetic SKU payload is already owned."""
    from .playercard import (
        COSMETIC_KIND_NAME_STYLE,
        COSMETIC_KIND_TITLE_FLAIR,
        player_has_name_style,
        player_has_title_flair,
    )

    unlocks = payload.get("unlocks") or []
    if not isinstance(unlocks, list) or not unlocks:
        return False
    for entry in unlocks:
        if not isinstance(entry, Mapping):
            return False
        ukind = str(entry.get("kind") or "").strip().lower()
        ukey = str(entry.get("key") or "").strip().lower()
        if ukind == COSMETIC_KIND_NAME_STYLE:
            if not player_has_name_style(int(player_id), ukey, conn=conn):
                return False
        elif ukind == COSMETIC_KIND_TITLE_FLAIR:
            if not player_has_title_flair(int(player_id), ukey, conn=conn):
                return False
        else:
            return False
    return True


def serialize_catalog_for_client(*, conn, player_id: Optional[int] = None) -> Dict[str, Any]:
    products = list_catalog(conn=conn)
    season_owned = False
    if player_id:
        season_owned, _ = _season_pass_owned(int(player_id), conn=conn)
    out = []
    for p in products:
        entry = dict(p)
        payload = p.get("payload") or {}
        owned = False
        if p["sku"] == SKU_SEASON_PASS:
            owned = bool(season_owned)
        elif str(p.get("kind")) == KIND_COSMETIC_UNLOCK and player_id:
            owned = _cosmetic_payload_owned(int(player_id), payload, conn=conn)
        entry["owned"] = owned
        entry["image"] = shop_image_for_sku(str(p["sku"]))
        # Do not expose raw payload grant math beyond display-safe fields.
        unlocks_raw = payload.get("unlocks") or []
        unlocks_display: List[Dict[str, str]] = []
        if isinstance(unlocks_raw, list):
            for u in unlocks_raw:
                if not isinstance(u, Mapping):
                    continue
                ukind = str(u.get("kind") or "").strip().lower()
                ukey = str(u.get("key") or "").strip().lower()
                if not ukind or not ukey:
                    continue
                unlocks_display.append({"kind": ukind, "key": ukey})
        entry["display"] = {
            "timekeeper_sec": int(payload.get("timekeeper_sec") or 0),
            "item_count": len(payload.get("items") or [])
            if isinstance(payload.get("items"), list)
            else 0,
            "entitlement": str(payload.get("entitlement") or "") or None,
            "preview_style": str(payload.get("preview_style") or "") or None,
            "unlock_count": len(unlocks_display),
            "unlocks": unlocks_display,
        }
        entry.pop("payload", None)
        out.append(entry)
    return {
        "ready": schema_ready(conn),
        "enabled": is_shop_enabled(),
        "products": out,
        "providers": _available_providers(),
    }


def _available_providers() -> List[str]:
    """PayPal is the default live provider; Stripe only if SHOP_ENABLE_STRIPE=1 + keys."""
    from . import payment_providers as pp

    providers: List[str] = []
    if pp.paypal_configured():
        providers.append("paypal")
    stripe_on = str(os.environ.get("SHOP_ENABLE_STRIPE", "0") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if stripe_on and pp.stripe_configured():
        providers.append("stripe")
    if os.environ.get("SHOP_TEST_PROVIDER", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        providers.append("test")
    return providers


def start_checkout(
    player_id: int,
    sku: str,
    provider: str,
    *,
    conn,
    success_url: str,
    cancel_url: str,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Create pending order + provider checkout session."""
    from . import payment_providers as pp

    ok, reason, created = create_pending_order(
        int(player_id), sku, provider, conn=conn, now=now
    )
    if not ok or not created:
        return False, reason, None
    order = created["order"]
    product = created["product"]
    prov = str(provider).strip().lower()

    if prov == "test":
        if os.environ.get("SHOP_TEST_PROVIDER", "").strip().lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return False, "provider_unconfigured", None
        session_id = f"test_sess_{order['id']}"
        attach_provider_session(int(order["id"]), session_id, conn=conn)
        # Immediate fulfill path for automated tests / local sandbox.
        mark_paid(
            int(order["id"]),
            conn=conn,
            provider_payment_id=f"test_pay_{order['id']}",
            now=now,
        )
        fok, freason, fulfilled = fulfill_order(int(order["id"]), conn=conn, now=now)
        return fok, freason if fok else freason, {
            "order_id": int(order["id"]),
            "checkout_url": None,
            "fulfilled": True,
            "order": fulfilled,
            "product": product,
        }

    if prov == "stripe":
        sok, sreason, session = pp.stripe_create_checkout_session(
            order=order,
            product=product,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        if not sok or not session:
            return False, sreason, {"order_id": int(order["id"])}
        attach_provider_session(
            int(order["id"]),
            str(session["session_id"]),
            conn=conn,
            metadata={"stripe_session": session.get("session_id")},
        )
        return True, "ok", {
            "order_id": int(order["id"]),
            "checkout_url": session["checkout_url"],
            "fulfilled": False,
            "product": product,
        }

    if prov == "paypal":
        pok, preason, session = pp.paypal_create_checkout_order(
            order=order,
            product=product,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        if not pok or not session:
            return False, preason, {"order_id": int(order["id"])}
        attach_provider_session(
            int(order["id"]),
            str(session["session_id"]),
            conn=conn,
            metadata={"paypal_order": session.get("session_id")},
        )
        return True, "ok", {
            "order_id": int(order["id"]),
            "checkout_url": session["checkout_url"],
            "fulfilled": False,
            "product": product,
        }

    return False, "invalid_provider", None
