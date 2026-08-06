"""
EPIC-23 — Stripe + PayPal checkout adapters (thin).

Owner: provider session create + webhook signature verify.
Order lifecycle / fulfill lives in game.shop.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def stripe_configured() -> bool:
    return bool(_env("STRIPE_SECRET_KEY"))


def paypal_configured() -> bool:
    return bool(_env("PAYPAL_CLIENT_ID") and _env("PAYPAL_CLIENT_SECRET"))


def stripe_webhook_secret() -> str:
    return _env("STRIPE_WEBHOOK_SECRET")


def paypal_mode() -> str:
    mode = _env("PAYPAL_MODE").lower() or "sandbox"
    return "live" if mode == "live" else "sandbox"


def paypal_api_base() -> str:
    if paypal_mode() == "live":
        return "https://api-m.paypal.com"
    return "https://api-m.sandbox.paypal.com"


def stripe_create_checkout_session(
    *,
    order: Mapping[str, Any],
    product: Mapping[str, Any],
    success_url: str,
    cancel_url: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not stripe_configured():
        return False, "provider_unconfigured", None
    try:
        import stripe  # type: ignore
    except ImportError:
        return False, "stripe_sdk_missing", None

    stripe.api_key = _env("STRIPE_SECRET_KEY")
    currency = str(
        order.get("currency") or product.get("currency") or "eur"
    ).lower()
    amount = int(order.get("amount_cents") or product.get("price_cents") or 0)
    if amount <= 0:
        return False, "invalid_amount", None

    success = str(success_url)
    cancel = str(cancel_url)
    if not success.startswith("http://") and not success.startswith("https://"):
        return False, "invalid_return_url", None
    if not cancel.startswith("http://") and not cancel.startswith("https://"):
        return False, "invalid_return_url", None
    if "{CHECKOUT_SESSION_ID}" not in success:
        sep = "&" if "?" in success else "?"
        success = f"{success}{sep}session_id={{CHECKOUT_SESSION_ID}}"

    display_name = str(product.get("sku") or "Genesis Colonies")
    title_key = str(product.get("title_key") or "").strip()
    if title_key:
        display_name = title_key.replace("shop_sku_", "").replace("_", " ").title()
    items = order.get("items") if isinstance(order.get("items"), list) else []
    if len(items) > 1:
        skus = [str(i.get("sku") or "") for i in items if isinstance(i, dict)]
        skus = [s for s in skus if s][:6]
        display_name = f"Cart ({len(items)} items)"
        if skus:
            display_name = f"Cart: {', '.join(skus)}"
            if len(display_name) > 120:
                display_name = display_name[:117] + "..."

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=success,
            cancel_url=cancel,
            client_reference_id=str(order["id"]),
            metadata={
                "order_id": str(order["id"]),
                "player_id": str(order["player_id"]),
                "sku": str(order["sku"]),
                "line_count": str(len(items) if items else 1),
            },
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount,
                        "product_data": {
                            "name": f"Genesis Colonies — {display_name}",
                            "metadata": {"sku": str(order.get("sku") or product.get("sku") or "")},
                        },
                    },
                }
            ],
        )
    except Exception:
        return False, "stripe_session_failed", None

    return True, "ok", {
        "session_id": str(session.get("id") or ""),
        "checkout_url": str(session.get("url") or ""),
    }


def stripe_verify_and_parse_event(
    payload: bytes,
    sig_header: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    secret = stripe_webhook_secret()
    if not secret:
        return False, "webhook_unconfigured", None
    try:
        import stripe  # type: ignore
    except ImportError:
        return False, "stripe_sdk_missing", None

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception:
        return False, "invalid_signature", None

    if hasattr(event, "to_dict"):
        data = event.to_dict()
    elif isinstance(event, dict):
        data = event
    else:
        data = {
            "id": getattr(event, "id", None),
            "type": getattr(event, "type", None),
            "data": {"object": getattr(getattr(event, "data", None), "object", None)},
        }
    return True, "ok", data


def stripe_extract_checkout_completed(
    event: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    if str(event.get("type") or "") != "checkout.session.completed":
        return None
    obj = (event.get("data") or {}).get("object") or {}
    if not isinstance(obj, dict):
        return None
    meta = obj.get("metadata") or {}
    order_id = None
    try:
        order_id = int(meta.get("order_id") or obj.get("client_reference_id") or 0) or None
    except Exception:
        order_id = None
    return {
        "event_id": str(event.get("id") or ""),
        "order_id": order_id,
        "provider_session_id": str(obj.get("id") or "") or None,
        "provider_payment_id": str(obj.get("payment_intent") or obj.get("id") or "") or None,
    }


def paypal_create_checkout_order(
    *,
    order: Mapping[str, Any],
    product: Mapping[str, Any],
    success_url: str,
    cancel_url: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not paypal_configured():
        return False, "provider_unconfigured", None
    success = str(success_url)
    cancel = str(cancel_url)
    if not success.startswith("http://") and not success.startswith("https://"):
        return False, "invalid_return_url", None
    if not cancel.startswith("http://") and not cancel.startswith("https://"):
        return False, "invalid_return_url", None
    # Ensure return URL carries our shop order id for reliable lookup.
    oid = int(order.get("id") or 0)
    if oid > 0 and "order_id=" not in success:
        sep = "&" if "?" in success else "?"
        success = f"{success}{sep}order_id={oid}"
    token = _paypal_access_token()
    if not token:
        return False, "paypal_auth_failed", None

    currency = str(
        order.get("currency") or product.get("currency") or "eur"
    ).upper()
    amount = max(0, int(order.get("amount_cents") or product.get("price_cents") or 0)) / 100.0
    value = f"{amount:.2f}"
    desc = str(product.get("sku") or "Genesis Colonies")
    items = order.get("items") if isinstance(order.get("items"), list) else []
    if len(items) > 1:
        skus = [str(i.get("sku") or "") for i in items if isinstance(i, dict)]
        skus = [s for s in skus if s]
        if skus:
            desc = f"cart:{'+'.join(skus[:8])}"
            if len(desc) > 127:
                desc = desc[:124] + "..."
    body = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": str(order["id"]),
                "custom_id": str(order["id"]),
                "amount": {
                    "currency_code": currency,
                    "value": value,
                },
                "description": desc,
            }
        ],
        "application_context": {
            "return_url": success,
            "cancel_url": cancel,
            "user_action": "PAY_NOW",
            "shipping_preference": "NO_SHIPPING",
        },
    }
    try:
        data = _paypal_request(
            "POST",
            "/v2/checkout/orders",
            token=token,
            body=body,
        )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read() or b"").decode("utf-8", errors="replace")[:800]
        except Exception:
            detail = ""
        logger.warning(
            "paypal create order HTTP %s order_id=%s detail=%s",
            getattr(exc, "code", "?"),
            order.get("id"),
            detail,
        )
        return False, "paypal_session_failed", None
    except Exception:
        logger.exception("paypal create order failed order_id=%s", order.get("id"))
        return False, "paypal_session_failed", None

    order_id = str(data.get("id") or "")
    approve = None
    for link in data.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == "approve":
            approve = link.get("href")
            break
    if not order_id or not approve:
        logger.warning(
            "paypal create order missing approve link order_id=%s keys=%s",
            order_id or order.get("id"),
            list(data.keys()) if isinstance(data, dict) else type(data),
        )
        return False, "paypal_session_failed", None
    return True, "ok", {
        "session_id": order_id,
        "checkout_url": str(approve),
    }


def paypal_fetch_order(
    paypal_order_id: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """GET /v2/checkout/orders/{id} — used for return recovery after capture."""
    token = _paypal_access_token()
    if not token:
        return False, "paypal_auth_failed", None
    oid = urllib.parse.quote(str(paypal_order_id or "").strip())
    if not oid:
        return False, "invalid_paypal_order", None
    try:
        data = _paypal_request("GET", f"/v2/checkout/orders/{oid}", token=token)
    except urllib.error.HTTPError as exc:
        return False, f"paypal_http_{int(exc.code)}", None
    except Exception:
        return False, "paypal_fetch_failed", None
    if not isinstance(data, dict) or not data.get("id"):
        return False, "paypal_fetch_failed", None
    return True, "ok", data


def paypal_order_capture_summary(
    data: Mapping[str, Any],
) -> Dict[str, Any]:
    """Normalize PayPal order payload for shop recovery (sku, cents, capture id)."""
    status = str(data.get("status") or "").upper()
    sku = ""
    currency = "eur"
    amount_cents = 0
    capture_id = ""
    units = data.get("purchase_units") or []
    if units and isinstance(units[0], dict):
        pu = units[0]
        sku = str(pu.get("description") or "").strip()
        amount = pu.get("amount") or {}
        if isinstance(amount, dict):
            currency = str(amount.get("currency_code") or "eur").lower()
            try:
                amount_cents = int(round(float(amount.get("value") or 0) * 100))
            except (TypeError, ValueError):
                amount_cents = 0
        caps = ((pu.get("payments") or {}).get("captures")) or []
        if caps and isinstance(caps[0], dict):
            capture_id = str(caps[0].get("id") or "").strip()
    return {
        "status": status,
        "sku": sku,
        "currency": currency,
        "amount_cents": amount_cents,
        "capture_id": capture_id,
        "paypal_order_id": str(data.get("id") or ""),
    }


def paypal_capture_order(paypal_order_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    token = _paypal_access_token()
    if not token:
        return False, "paypal_auth_failed", None
    oid = str(paypal_order_id or "").strip()
    # Already captured (browser return after webhook / orphaned local checkout).
    ok_get, _, existing = paypal_fetch_order(oid)
    if ok_get and isinstance(existing, dict):
        summary = paypal_order_capture_summary(existing)
        if summary.get("status") == "COMPLETED":
            return True, "already_captured", existing
    try:
        data = _paypal_request(
            "POST",
            f"/v2/checkout/orders/{urllib.parse.quote(oid)}/capture",
            token=token,
            body={},
        )
    except urllib.error.HTTPError as exc:
        # Race: capture completed between GET and POST.
        if int(exc.code) in (422, 400):
            ok2, _, again = paypal_fetch_order(oid)
            if ok2 and isinstance(again, dict):
                summary = paypal_order_capture_summary(again)
                if summary.get("status") == "COMPLETED":
                    return True, "already_captured", again
        return False, "paypal_capture_failed", None
    except Exception:
        return False, "paypal_capture_failed", None
    return True, "ok", data


def paypal_verify_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Verify PayPal webhook signature via PayPal verify-webhook-signature API.
    """
    webhook_id = _env("PAYPAL_WEBHOOK_ID")
    if not webhook_id:
        return False, "webhook_unconfigured", None
    token = _paypal_access_token()
    if not token:
        return False, "paypal_auth_failed", None

    try:
        event = json.loads(body.decode("utf-8"))
    except Exception:
        return False, "invalid_payload", None

    transmission_id = _header(headers, "PAYPAL-TRANSMISSION-ID")
    timestamp = _header(headers, "PAYPAL-TRANSMISSION-TIME")
    cert_url = _header(headers, "PAYPAL-CERT-URL")
    auth_algo = _header(headers, "PAYPAL-AUTH-ALGO")
    transmission_sig = _header(headers, "PAYPAL-TRANSMISSION-SIG")
    if not all([transmission_id, timestamp, cert_url, auth_algo, transmission_sig]):
        return False, "invalid_signature", None

    verify_body = {
        "transmission_id": transmission_id,
        "transmission_time": timestamp,
        "cert_url": cert_url,
        "auth_algo": auth_algo,
        "transmission_sig": transmission_sig,
        "webhook_id": webhook_id,
        "webhook_event": event,
    }
    try:
        result = _paypal_request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            token=token,
            body=verify_body,
        )
    except Exception:
        return False, "invalid_signature", None

    status = str(result.get("verification_status") or "").upper()
    if status != "SUCCESS":
        return False, "invalid_signature", None
    return True, "ok", event


def paypal_extract_payment_completed(
    event: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    etype = str(event.get("event_type") or "")
    resource = event.get("resource") or {}
    if not isinstance(resource, dict):
        return None

    if etype in ("CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED"):
        custom = resource.get("purchase_units") or []
        order_id = None
        if custom and isinstance(custom[0], dict):
            try:
                order_id = int(custom[0].get("custom_id") or custom[0].get("reference_id") or 0) or None
            except Exception:
                order_id = None
        if order_id is None:
            try:
                order_id = int(resource.get("custom_id") or 0) or None
            except Exception:
                order_id = None
        return {
            "event_id": str(event.get("id") or ""),
            "order_id": order_id,
            "provider_session_id": str(resource.get("id") or "") or None,
            "provider_payment_id": str(resource.get("id") or "") or None,
            "needs_capture": etype == "CHECKOUT.ORDER.APPROVED",
        }

    if etype == "PAYMENT.CAPTURE.COMPLETED":
        custom_id = resource.get("custom_id")
        order_id = None
        try:
            order_id = int(custom_id or 0) or None
        except Exception:
            order_id = None
        supplementary = resource.get("supplementary_data") or {}
        related = supplementary.get("related_ids") or {}
        session_id = related.get("order_id")
        return {
            "event_id": str(event.get("id") or ""),
            "order_id": order_id,
            "provider_session_id": str(session_id or "") or None,
            "provider_payment_id": str(resource.get("id") or "") or None,
            "needs_capture": False,
        }
    return None


def _header(headers: Mapping[str, str], name: str) -> str:
    # Case-insensitive header lookup
    want = name.lower()
    for k, v in headers.items():
        if str(k).lower() == want:
            return str(v or "").strip()
    return ""


def _paypal_access_token() -> Optional[str]:
    client_id = _env("PAYPAL_CLIENT_ID")
    secret = _env("PAYPAL_CLIENT_SECRET")
    if not client_id or not secret:
        return None
    basic = base64.b64encode(f"{client_id}:{secret}".encode("utf-8")).decode("ascii")
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    req = urllib.request.Request(
        f"{paypal_api_base()}/v1/oauth2/token",
        data=data,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read() or b"").decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = ""
        logger.warning("paypal oauth HTTP %s detail=%s", getattr(exc, "code", "?"), detail)
        return None
    except (urllib.error.URLError, TimeoutError, ValueError):
        logger.exception("paypal oauth failed")
        return None
    token = str(payload.get("access_token") or "").strip()
    return token or None


def _paypal_request(
    method: str,
    path: str,
    *,
    token: str,
    body: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    raw = json.dumps(body if body is not None else {}).encode("utf-8")
    req = urllib.request.Request(
        f"{paypal_api_base()}{path}",
        data=raw if method.upper() != "GET" else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method.upper(),
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    if not text:
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def fake_stripe_signature_for_tests(payload: bytes, secret: str) -> str:
    """Test helper: Stripe-compatible signed header (t=…,v1=…)."""
    ts = str(int(__import__("time").time()))
    signed = f"{ts}.".encode("utf-8") + payload
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"
