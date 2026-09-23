"""Contact form backend for the developer portfolio (gurgenbaba.github.io).

The portfolio is a static site, so it posts the finished project request here.
The request is forwarded by mail, attachments included, and nothing is stored.

Deliverability: the mail is sent through the owner's own mailbox
(``CONTACT_SMTP_USER``, Gmail by default) to that same mailbox, with the
customer as Reply-To. A message a mailbox sends to itself through its own
authenticated SMTP does not get flagged as spam, unlike mail from an unknown
customer address or a fresh sender domain.

Environment:
    CONTACT_SMTP_USER      mailbox that sends and (by default) receives
    CONTACT_SMTP_PASSWORD  app password for that mailbox
    CONTACT_SMTP_HOST      default smtp.gmail.com
    CONTACT_SMTP_PORT      default 587 (STARTTLS)
    CONTACT_MAIL_TO        recipient, default CONTACT_SMTP_USER

Abuse protection: per-IP rate limit (memory only), a honeypot field, a minimum
fill time, size caps and an attachment type allowlist. Bot hits get a normal
"ok" so they learn nothing.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

logger = logging.getLogger(__name__)

MAX_FILES = 5
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_TOTAL_BYTES + 256 * 1024
MIN_FILL_MS = 4000
SUBMIT_RATE = (5, 3600.0)  # 5 requests per hour per IP
ALLOWED_EXTENSIONS = frozenset({
    "pdf", "png", "jpg", "jpeg", "webp", "gif", "heic",
    "txt", "md", "csv", "rtf",
    "doc", "docx", "odt", "xls", "xlsx", "ods", "ppt", "pptx", "odp",
    "fig", "sketch", "psd", "ai",
})

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
_SUBMIT_BUCKETS: dict[str, list] = {}


class ContactError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def reset_contact_state() -> None:
    _SUBMIT_BUCKETS.clear()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def contact_configured() -> bool:
    return bool(_env("CONTACT_SMTP_USER") and _env("CONTACT_SMTP_PASSWORD"))


def _one_line(value: Any, limit: int) -> str:
    return re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()[:limit]


def validate_fields(form: Any) -> dict[str, str]:
    """Check the text fields. Raises ContactError on invalid input."""
    email = _one_line(form.get("email"), 254)
    if not _EMAIL_RE.match(email):
        raise ContactError("bad_email")
    message = str(form.get("message") or "").replace("\r\n", "\n").strip()
    if len(message) < 20:
        raise ContactError("message_too_short")
    if len(message) > 6000:
        raise ContactError("message_too_long")
    subject = _one_line(form.get("subject"), 150) or "Projektanfrage"
    return {
        "name": _one_line(form.get("name"), 80),
        "email": email,
        "subject": subject,
        "message": message,
    }


def is_probably_bot(form: Any) -> bool:
    if str(form.get("website") or "").strip():
        return True
    try:
        elapsed = int(form.get("elapsed_ms") or 0)
    except (TypeError, ValueError):
        return True
    return elapsed < MIN_FILL_MS


def read_attachments(files: list) -> list[tuple[str, bytes, str]]:
    """Return (filename, data, mime) for each upload. Raises ContactError on bad files."""
    picked = [f for f in files if f and getattr(f, "filename", "")]
    if len(picked) > MAX_FILES:
        raise ContactError("too_many_files")
    out: list[tuple[str, bytes, str]] = []
    total = 0
    for f in picked:
        name = os.path.basename(str(f.filename).replace("\\", "/"))[:120] or "anhang"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise ContactError("file_type_not_allowed")
        data = f.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ContactError("file_too_large", 413)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ContactError("files_too_large", 413)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        out.append((name, data, mime))
    return out


def build_message(fields: dict[str, str], attachments: list[tuple[str, bytes, str]],
                  *, sender: str, recipient: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = fields["subject"]
    msg["From"] = formataddr(("Portfolio-Anfrage", sender))
    msg["To"] = recipient
    msg["Reply-To"] = formataddr((fields["name"], fields["email"])) if fields["name"] else fields["email"]
    footer = (
        "\n\n--\n"
        f"Absender: {fields['name'] or '(ohne Namen)'} <{fields['email']}>\n"
        f"Anhänge: {len(attachments)}\n"
        "Gesendet über das Kontaktformular auf gurgenbaba.github.io. "
        "\"Antworten\" geht direkt an den Absender."
    )
    msg.set_content(fields["message"] + footer)
    for name, data, mime in attachments:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    return msg


def send_contact_mail(msg: EmailMessage) -> bool:
    host = _env("CONTACT_SMTP_HOST", "smtp.gmail.com")
    port = int(_env("CONTACT_SMTP_PORT", "587") or "587")
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(_env("CONTACT_SMTP_USER"), _env("CONTACT_SMTP_PASSWORD"))
            smtp.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("contact mail failed: %s", exc)
        return False


def register_contact_routes(app) -> None:
    from flask import jsonify, request

    from game.public_stats import allowed_origins
    from game.security import _rate_ok, client_ip

    if "api_public_contact" in app.view_functions:
        return

    def _reply(payload: dict, status: int = 200):
        response = jsonify(payload)
        response.status_code = status
        origin = (request.headers.get("Origin") or "").rstrip("/")
        if origin and origin in allowed_origins():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/public/contact", endpoint="api_public_contact")
    def _contact():
        length = request.content_length
        if length is None or length > MAX_REQUEST_BYTES:
            return _reply({"ok": False, "error": "request_too_large"}, 413)
        if not contact_configured():
            return _reply({"ok": False, "error": "contact_unavailable"}, 503)
        if not _rate_ok(_SUBMIT_BUCKETS, client_ip(request), SUBMIT_RATE[1], SUBMIT_RATE[0]):
            return _reply({"ok": False, "error": "rate_limited"}, 429)
        form = request.form
        if is_probably_bot(form):
            return _reply({"ok": True})
        try:
            fields = validate_fields(form)
            attachments = read_attachments(request.files.getlist("files"))
        except ContactError as err:
            return _reply({"ok": False, "error": err.code}, err.status)
        sender = _env("CONTACT_SMTP_USER")
        recipient = _env("CONTACT_MAIL_TO") or sender
        msg = build_message(fields, attachments, sender=sender, recipient=recipient)
        if not send_contact_mail(msg):
            return _reply({"ok": False, "error": "send_failed"}, 502)
        logger.info("contact mail sent attachments=%s", len(attachments))
        return _reply({"ok": True})
