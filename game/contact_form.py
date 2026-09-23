"""Contact form backend for the developer portfolio (gurgenbaba.github.io).

The portfolio is a static site, so it posts the finished project request here.
The request is forwarded, attachments included, and nothing is stored. Two
channels, used together when both are configured:

- Discord webhook (``CONTACT_DISCORD_WEBHOOK``): an embed plus the files in a
  private channel. No spam filter involved, push notification on the phone.
- Mail through the owner's own mailbox (``CONTACT_SMTP_USER``, Gmail by
  default) to that same mailbox, with the customer as Reply-To. A message a
  mailbox sends to itself through its own authenticated SMTP does not get
  flagged as spam.

The request counts as delivered when at least one channel accepted it.

When the portfolio sends its answers as a ``brief`` (see game.contact_brief),
both channels carry a work order instead of the plain letter: requirements with
acceptance criteria, open questions and a Markdown file for a coding agent. The
customer's letter stays in the order, quoted.

Environment:
    CONTACT_DISCORD_WEBHOOK  https://discord.com/api/webhooks/<id>/<token>
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

import json
import logging
import mimetypes
import os
import re
import smtplib
import uuid
from urllib.request import Request, urlopen
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from game.contact_brief import WorkOrder, build_work_order, parse_brief

logger = logging.getLogger(__name__)

MAX_FILES = 5
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024  # Discord's upload cap for webhooks without boosts
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


def mail_configured() -> bool:
    return bool(_env("CONTACT_SMTP_USER") and _env("CONTACT_SMTP_PASSWORD"))


def discord_webhook_url() -> str:
    url = _env("CONTACT_DISCORD_WEBHOOK")
    ok = url.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/"))
    return url if ok else ""


def contact_configured() -> bool:
    return mail_configured() or bool(discord_webhook_url())


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
                  *, sender: str, recipient: str, order: WorkOrder | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = order.subject if order else fields["subject"]
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
    msg.set_content((order.markdown if order else fields["message"]) + footer)
    if order:
        msg.add_attachment(order.markdown.encode("utf-8"), maintype="text", subtype="markdown", filename=order.filename)
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


DISCORD_DESCRIPTION_LIMIT = 3900


def build_discord_payload(fields: dict[str, str], attachments: list[tuple[str, bytes, str]],
                          order: WorkOrder | None = None) -> tuple[dict, list[tuple[str, bytes, str]]]:
    """Embed JSON plus the files to upload. Long letters go along as a .txt file."""
    files = list(attachments)
    if order:
        embed = dict(order.embed)
        data = order.markdown.encode("utf-8")
        if sum(len(d) for _, d, _ in files) + len(data) <= MAX_TOTAL_BYTES:
            files.insert(0, (order.filename, data, "text/markdown"))
        else:
            embed["footer"] = {"text": "Auftragsdatei passte nicht mehr ins Upload-Limit, sie steht in der Mail."}
        return {"username": "Portfolio-Auftrag", "allowed_mentions": {"parse": []}, "embeds": [embed]}, files
    text = fields["message"]
    if len(text) > DISCORD_DESCRIPTION_LIMIT:
        files.append(("anfrage.txt", text.encode("utf-8"), "text/plain"))
        text = text[:DISCORD_DESCRIPTION_LIMIT] + "\n\n… (vollständig in anfrage.txt)"
    names = ", ".join(name for name, _, _ in attachments) or "keine"
    payload = {
        "username": "Portfolio-Anfrage",
        # Customer text must never ping anyone in the channel.
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": fields["subject"][:256],
            "description": text,
            "color": 0xC6F04A,
            "fields": [
                {"name": "Name", "value": (fields["name"] or "–")[:1024], "inline": True},
                {"name": "E-Mail", "value": fields["email"][:1024], "inline": True},
                {"name": "Anhänge", "value": names[:1024], "inline": False},
            ],
            "footer": {"text": "gurgenbaba.github.io · Antwort per E-Mail an den Absender"},
        }],
    }
    return payload, files


def _multipart(payload: dict, files: list[tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
        "Content-Type: application/json\r\n\r\n".encode() + json.dumps(payload).encode("utf-8") + b"\r\n"
    ]
    for i, (name, data, mime) in enumerate(files):
        safe = re.sub(r'[\r\n"]+', "_", name)
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; filename=\"{safe}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
        parts.append(head + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send_discord(fields: dict[str, str], attachments: list[tuple[str, bytes, str]],
                 order: WorkOrder | None = None) -> bool:
    url = discord_webhook_url()
    if not url:
        return False
    payload, files = build_discord_payload(fields, attachments, order)
    body, content_type = _multipart(payload, files)
    req = Request(url, data=body, method="POST", headers={
        "Content-Type": content_type,
        # Discord's edge rejects the default Python user agent.
        "User-Agent": "GenesisColoniesContact/1.0 (+https://genesis-colonies.com)",
    })
    try:
        with urlopen(req, timeout=20) as res:
            return 200 <= res.status < 300
    except Exception as exc:
        # Never log the URL: it contains the webhook token.
        logger.warning("contact discord webhook failed: %s", type(exc).__name__)
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
        brief = parse_brief(form.get("brief"))
        order = build_work_order(brief, fields, [name for name, _, _ in attachments]) if brief else None
        delivered = []
        if discord_webhook_url() and send_discord(fields, attachments, order):
            delivered.append("discord")
        if mail_configured():
            sender = _env("CONTACT_SMTP_USER")
            recipient = _env("CONTACT_MAIL_TO") or sender
            if send_contact_mail(build_message(fields, attachments, sender=sender, recipient=recipient, order=order)):
                delivered.append("mail")
        if not delivered:
            return _reply({"ok": False, "error": "send_failed"}, 502)
        logger.info("contact request delivered via=%s attachments=%s work_order=%s",
                    ",".join(delivered), len(attachments), bool(order))
        return _reply({"ok": True})
