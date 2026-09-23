"""
Portfolio contact form: validation, abuse protection and the outgoing mail.

Run: python -m pytest tests/test_contact_form.py -v
"""

from __future__ import annotations

import io

import pytest
from flask import Flask

import game.contact_form as contact

ORIGIN = "https://gurgenbaba.github.io"
LETTER = "Hallo,\n\nich interessiere mich für einen Online-Shop.\n\nViele Grüße\nAnna"


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise OSError("smtp down")
        FakeSMTP.sent.append(msg)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CONTACT_SMTP_USER", "owner@example.com")
    monkeypatch.setenv("CONTACT_SMTP_PASSWORD", "app-password")
    monkeypatch.delenv("CONTACT_MAIL_TO", raising=False)
    monkeypatch.setattr(contact.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent = []
    FakeSMTP.fail = False
    contact.reset_contact_state()
    app = Flask(__name__)
    contact.register_contact_routes(app)
    yield app.test_client()
    contact.reset_contact_state()


def _post(client, fields=None, files=None):
    data = {
        "name": "Anna Schmidt",
        "email": "anna@example.org",
        "subject": "Projektanfrage: Online-Shop",
        "message": LETTER,
        "elapsed_ms": "25000",
        "website": "",
    }
    data.update(fields or {})
    if files:
        data["files"] = files
    return client.post("/api/public/contact", data=data, content_type="multipart/form-data",
                       headers={"Origin": ORIGIN})


def test_sends_mail_to_owner_with_reply_to_and_attachments(client):
    files = [(io.BytesIO(b"%PDF-1.4 test"), "Briefing.pdf"), (io.BytesIO(b"\x89PNG"), "logo.png")]
    response = _post(client, files=files)
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"ok": True}
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN

    assert len(FakeSMTP.sent) == 1
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "owner@example.com"
    assert "owner@example.com" in msg["From"]
    assert msg["Reply-To"] == "Anna Schmidt <anna@example.org>"
    assert msg["Subject"] == "Projektanfrage: Online-Shop"
    names = [part.get_filename() for part in msg.iter_attachments()]
    assert names == ["Briefing.pdf", "logo.png"]
    assert "ich interessiere mich für einen Online-Shop" in msg.get_body(("plain",)).get_content()


def test_honeypot_and_too_fast_submissions_are_silently_dropped(client):
    assert _post(client, {"website": "http://spam"}).get_json() == {"ok": True}
    assert _post(client, {"elapsed_ms": "900"}).get_json() == {"ok": True}
    assert FakeSMTP.sent == []


@pytest.mark.parametrize(
    "fields, error",
    [
        ({"email": "not-an-email"}, "bad_email"),
        ({"message": "zu kurz"}, "message_too_short"),
        ({"message": "x" * 6001}, "message_too_long"),
    ],
)
def test_invalid_fields_are_rejected(client, fields, error):
    response = _post(client, fields)
    assert response.status_code == 400
    assert response.get_json()["error"] == error
    assert FakeSMTP.sent == []


def test_header_injection_in_subject_is_flattened(client):
    _post(client, {"subject": "Hallo\r\nBcc: victim@example.com"})
    msg = FakeSMTP.sent[0]
    assert msg["Bcc"] is None
    assert "\n" not in msg["Subject"]


def test_disallowed_and_oversized_attachments(client):
    bad = _post(client, files=[(io.BytesIO(b"MZ"), "tool.exe")])
    assert bad.get_json()["error"] == "file_type_not_allowed"
    many = _post(client, files=[(io.BytesIO(b"a"), f"f{i}.txt") for i in range(contact.MAX_FILES + 1)])
    assert many.get_json()["error"] == "too_many_files"
    big = _post(client, files=[(io.BytesIO(b"0" * (contact.MAX_FILE_BYTES + 1)), "big.pdf")])
    assert big.status_code == 413
    assert FakeSMTP.sent == []


def test_smtp_failure_reports_send_failed(client):
    FakeSMTP.fail = True
    response = _post(client)
    assert response.status_code == 502
    assert response.get_json()["error"] == "send_failed"


def test_unconfigured_mailbox_reports_unavailable(client, monkeypatch):
    monkeypatch.delenv("CONTACT_SMTP_PASSWORD")
    response = _post(client)
    assert response.status_code == 503
    assert response.get_json()["error"] == "contact_unavailable"


def test_rate_limit_per_ip(client):
    for _ in range(contact.SUBMIT_RATE[0]):
        assert _post(client).status_code == 200
    assert _post(client).status_code == 429


def test_explicit_recipient_overrides_sender(client, monkeypatch):
    monkeypatch.setenv("CONTACT_MAIL_TO", "inbox@example.com")
    _post(client)
    assert FakeSMTP.sent[0]["To"] == "inbox@example.com"


# --- Discord webhook -------------------------------------------------------

import json
import re

WEBHOOK = "https://discord.com/api/webhooks/123/test-token"


class FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def discord(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        if getattr(fake_urlopen, "fail", False):
            raise OSError("discord down")
        calls.append(req)
        return FakeResponse()

    monkeypatch.setattr(contact, "urlopen", fake_urlopen)
    monkeypatch.setenv("CONTACT_DISCORD_WEBHOOK", WEBHOOK)
    fake_urlopen.calls = calls
    return fake_urlopen


def _payload(req):
    body = req.data.decode("utf-8", "replace")
    match = re.search(r'name="payload_json"\r\nContent-Type: application/json\r\n\r\n(.*?)\r\n--', body, re.S)
    return json.loads(match.group(1)), body


def test_discord_only_delivers_embed_and_files(client, discord, monkeypatch):
    monkeypatch.delenv("CONTACT_SMTP_PASSWORD")
    files = [(io.BytesIO(b"%PDF-1.4"), "Briefing.pdf")]
    response = _post(client, {"message": LETTER + "\n\n@everyone schaut her"}, files=files)
    assert response.status_code == 200, response.get_json()
    assert FakeSMTP.sent == []

    req = discord.calls[0]
    assert req.full_url == WEBHOOK
    assert req.get_header("User-agent").startswith("GenesisColoniesContact")
    payload, body = _payload(req)
    assert payload["allowed_mentions"] == {"parse": []}
    embed = payload["embeds"][0]
    assert embed["title"] == "Projektanfrage: Online-Shop"
    assert "Online-Shop" in embed["description"]
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["E-Mail"] == "anna@example.org"
    assert fields["Anhänge"] == "Briefing.pdf"
    assert 'name="files[0]"; filename="Briefing.pdf"' in body


def test_long_letter_is_attached_as_text_file(client, discord):
    long_letter = "Hallo,\n\n" + ("Sehr ausführliche Beschreibung. " * 180)
    _post(client, {"message": long_letter[:5900]})
    payload, body = _payload(discord.calls[0])
    assert len(payload["embeds"][0]["description"]) < 4096
    assert 'filename="anfrage.txt"' in body


def test_both_channels_are_used_and_one_success_is_enough(client, discord):
    assert _post(client).status_code == 200
    assert len(discord.calls) == 1 and len(FakeSMTP.sent) == 1

    discord.fail = True
    assert _post(client).status_code == 200  # mail still went out
    FakeSMTP.fail = True
    response = _post(client)
    assert response.status_code == 502
    assert response.get_json()["error"] == "send_failed"


def test_invalid_webhook_url_is_ignored(client, monkeypatch):
    monkeypatch.setenv("CONTACT_DISCORD_WEBHOOK", "https://evil.example/hook")
    monkeypatch.delenv("CONTACT_SMTP_PASSWORD")
    assert _post(client).status_code == 503


def test_total_attachment_cap_matches_discord_limit(client, discord):
    chunk = b"0" * (6 * 1024 * 1024)
    files = [(io.BytesIO(chunk), "a.pdf"), (io.BytesIO(chunk), "b.pdf")]
    response = _post(client, files=files)
    assert response.status_code == 413
    assert response.get_json()["error"] in ("request_too_large", "files_too_large")
