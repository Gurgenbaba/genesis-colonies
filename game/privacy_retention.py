"""DSGVO retention purge — reduce stored PII over time (payment payloads, audit IP/UA).

Owner for scheduled privacy retention. Invoked from maintenance bag / embedded cron.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from .db import db, table_exists

logger = logging.getLogger(__name__)

PRIVACY_PURGE_WORKER_KEY = "privacy_retention_purge_last"
DEFAULT_PAYMENT_PAYLOAD_DAYS = 90
DEFAULT_AUDIT_IP_DAYS = 180
DEFAULT_AUDIT_DELETE_DAYS = 365
DEFAULT_ADMIN_AUDIT_DELETE_DAYS = 730


def _env_days(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return int(default)
    try:
        return max(1, int(raw))
    except ValueError:
        return int(default)


def payment_payload_days() -> int:
    return _env_days("GC_PRIVACY_PURGE_PAYMENT_DAYS", DEFAULT_PAYMENT_PAYLOAD_DAYS)


def audit_ip_days() -> int:
    return _env_days("GC_PRIVACY_PURGE_AUDIT_IP_DAYS", DEFAULT_AUDIT_IP_DAYS)


def audit_delete_days() -> int:
    return _env_days("GC_PRIVACY_PURGE_AUDIT_DAYS", DEFAULT_AUDIT_DELETE_DAYS)


def admin_audit_delete_days() -> int:
    return _env_days(
        "GC_PRIVACY_PURGE_ADMIN_AUDIT_DAYS", DEFAULT_ADMIN_AUDIT_DELETE_DAYS
    )


def run_privacy_retention_purge(
    *,
    conn=None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Idempotent purge. Logs counts only — no PII."""
    owns = conn is None
    c = conn or db()
    ts = float(now if now is not None else time.time())
    out: Dict[str, Any] = {
        "ok": True,
        "payment_payloads_cleared": 0,
        "account_audit_ip_nulled": 0,
        "account_audit_deleted": 0,
        "admin_audit_ip_nulled": 0,
        "admin_audit_deleted": 0,
    }
    try:
        pay_cut = ts - payment_payload_days() * 86400
        ip_cut = ts - audit_ip_days() * 86400
        del_cut = ts - audit_delete_days() * 86400
        admin_del_cut = ts - admin_audit_delete_days() * 86400

        if table_exists(c, "shop_payment_events"):
            # Prefer processed_at; fall back if schema differs (table_columns — PG-safe).
            from .db import table_columns

            cols = table_columns(c, "shop_payment_events")
            ts_col = "processed_at" if "processed_at" in cols else (
                "created_at" if "created_at" in cols else None
            )
            if ts_col:
                cur = c.execute(
                    f"""
                    UPDATE shop_payment_events
                    SET payload_json = '{{}}'
                    WHERE {ts_col} > 0
                      AND {ts_col} < ?
                      AND payload_json IS NOT NULL
                      AND payload_json != ''
                      AND payload_json != '{{}}';
                    """,
                    (pay_cut,),
                )
                out["payment_payloads_cleared"] = int(cur.rowcount or 0)

        if table_exists(c, "account_audit_log"):
            cur = c.execute(
                """
                UPDATE account_audit_log
                SET ip = NULL, user_agent = NULL
                WHERE created_at < ?
                  AND (ip IS NOT NULL OR user_agent IS NOT NULL);
                """,
                (ip_cut,),
            )
            out["account_audit_ip_nulled"] = int(cur.rowcount or 0)
            cur = c.execute(
                "DELETE FROM account_audit_log WHERE created_at < ?;",
                (del_cut,),
            )
            out["account_audit_deleted"] = int(cur.rowcount or 0)

        if table_exists(c, "admin_audit_log"):
            cur = c.execute(
                """
                UPDATE admin_audit_log
                SET ip = NULL, user_agent = NULL
                WHERE created_at < ?
                  AND (ip IS NOT NULL OR user_agent IS NOT NULL);
                """,
                (ip_cut,),
            )
            out["admin_audit_ip_nulled"] = int(cur.rowcount or 0)
            cur = c.execute(
                "DELETE FROM admin_audit_log WHERE created_at < ?;",
                (admin_del_cut,),
            )
            out["admin_audit_deleted"] = int(cur.rowcount or 0)

        if owns:
            c.commit()
        logger.info(
            "privacy retention purge payment=%s audit_ip=%s audit_del=%s admin_del=%s",
            out["payment_payloads_cleared"],
            out["account_audit_ip_nulled"],
            out["account_audit_deleted"],
            out["admin_audit_deleted"],
        )
        return out
    except Exception as exc:
        if owns:
            c.rollback()
        logger.exception("privacy retention purge failed")
        return {"ok": False, "error": str(exc)}
    finally:
        if owns:
            c.close()


def maybe_run_privacy_retention_purge(
    *,
    force: bool = False,
    source: str = "maintenance",
    conn=None,
) -> Dict[str, Any]:
    """Throttle to roughly once per day unless force."""
    from .runtime_state import get_runtime_value, set_runtime_value

    owns = conn is None
    c = conn or db()
    try:
        now = time.time()
        raw = get_runtime_value(PRIVACY_PURGE_WORKER_KEY, conn=c)
        last = 0.0
        try:
            last = float(raw or 0)
        except (TypeError, ValueError):
            last = 0.0
        if not force and last and (now - last) < 20 * 3600:
            return {"ok": True, "skipped": True, "reason": "interval", "source": source}
        result = run_privacy_retention_purge(conn=c, now=now)
        if result.get("ok"):
            set_runtime_value(PRIVACY_PURGE_WORKER_KEY, str(now), conn=c)
            if owns:
                c.commit()
        result["source"] = source
        return result
    except Exception as exc:
        if owns:
            c.rollback()
        return {"ok": False, "error": str(exc), "source": source}
    finally:
        if owns:
            c.close()
