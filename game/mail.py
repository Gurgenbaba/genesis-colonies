"""
SMTP mail helper – logs and no-ops when SMTP is not configured.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)


def humanize_identifier_key(key: str) -> str:
    """Title-case fallback for internal keys in player-facing notification text."""
    return " ".join(part.capitalize() for part in str(key or "").split("_") if part)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def smtp_configured() -> bool:
    return bool(_env("SMTP_HOST"))


def mail_from_address() -> str:
    return _env("MAIL_FROM") or _env("SMTP_USER") or "noreply@genesis-colonies.local"


def send_mail(
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
    *,
    kind: str = "account_security",
) -> bool:
    """
    Send an email. Returns True on success, False if SMTP missing or send failed.
    Never raises to callers.
    """
    recipient = str(to or "").strip()
    if not recipient:
        logger.warning("send_mail skipped: empty recipient")
        return False

    # Canonical path: ABBES Mail Hub owns transactional delivery/SMTP secrets.
    try:
        from . import mail_hub

        if mail_hub.configured():
            ok, data = mail_hub.send_transactional_mail(
                recipient,
                subject,
                text,
                html_body=html,
                kind=kind,
            )
            if ok:
                logger.info("send_mail ok via mail_hub subject=%s", subject)
                return True
            logger.warning(
                "send_mail mail_hub failed subject=%s error=%s; trying SMTP fallback",
                subject,
                data.get("error") if isinstance(data, dict) else "unknown",
            )
    except Exception as exc:
        logger.warning("send_mail mail_hub exception subject=%s error=%s", subject, exc)

    host = _env("SMTP_HOST")
    if not host:
        logger.warning(
            "send_mail skipped: SMTP_HOST not set (to=%s subject=%s)",
            recipient,
            subject,
        )
        return False

    port = int(_env("SMTP_PORT", "587") or "587")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    use_tls = _env("SMTP_TLS", "1").lower() in ("1", "true", "yes", "on")
    sender = mail_from_address()

    msg = EmailMessage()
    msg["Subject"] = str(subject or "")[:200]
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(str(text or ""))
    if html:
        msg.add_alternative(str(html), subtype="html")

    try:
        if use_tls:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.ehlo()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
        logger.info("send_mail ok to=%s subject=%s", recipient, subject)
        return True
    except Exception as exc:
        logger.warning("send_mail failed to=%s: %s", recipient, exc)
        return False
