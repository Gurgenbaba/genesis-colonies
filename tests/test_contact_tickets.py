"""
Portfolio contact form: requests filed as tickets in a private GitHub repo.

Run: python -m pytest tests/test_contact_tickets.py -v
"""

from __future__ import annotations

import base64
import io
import json
import re
from urllib.error import HTTPError

import pytest
from flask import Flask

import game.contact_form as contact
import game.contact_tickets as tickets

ORIGIN = "https://gurgenbaba.github.io"
LETTER = "Hallo,\n\nich interessiere mich für einen Online-Shop.\n\nViele Grüße\nAnna"
BRIEF = json.dumps({"v": 1, "lang": "de", "type": "shop", "features": ["payments"], "timeline": "asap",
                    "budget": "lt500", "note": "Kerzen-Shop mit PayPal, bitte schnell.", "edited": False})
TOKEN = "github_pat_test"


class FakeGitHub:
    """Records GitHub API calls; answers like the real API for the calls we make."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.fail_issue = False
        self.conflicts = 0

    def __call__(self, req, timeout=None):
        url = req.full_url
        if url.startswith("https://discord.com/"):
            self.calls.append(("DISCORD", url, {"raw": req.data}))
            return _Resp(b"", 204)
        assert req.get_header("Authorization") == f"Bearer {TOKEN}"
        body = json.loads(req.data) if req.data else {}
        path = url.removeprefix(tickets.API)
        self.calls.append((req.get_method(), path, body))
        if req.get_method() == "POST" and path.endswith("/issues"):
            if self.fail_issue:
                raise HTTPError(url, 401, "Bad credentials", {}, None)
            return _Resp(json.dumps({"number": 7, "html_url": "https://github.com/Gurgenbaba/auftraege/issues/7"}).encode())
        if req.get_method() == "PUT" and self.conflicts:
            self.conflicts -= 1
            raise HTTPError(url, 409, "Conflict", {}, None)
        return _Resp(b"{}")


class _Resp:
    def __init__(self, data: bytes, status: int = 200):
        self.data, self.status = data, status

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setenv("CONTACT_GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("CONTACT_GITHUB_REPO", "Gurgenbaba/auftraege")
    monkeypatch.delenv("CONTACT_SMTP_USER", raising=False)
    monkeypatch.delenv("CONTACT_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("CONTACT_DISCORD_WEBHOOK", raising=False)
    monkeypatch.setattr(tickets, "urlopen", fake)
    monkeypatch.setattr(contact, "urlopen", fake)
    contact.reset_contact_state()
    app = Flask(__name__)
    contact.register_contact_routes(app)
    fake.client = app.test_client()
    yield fake
    contact.reset_contact_state()


def _post(fake, brief=BRIEF, files=None):
    data = {"name": "Anna Schmidt", "email": "anna@example.org", "subject": "Projektanfrage: Online-Shop",
            "message": LETTER, "elapsed_ms": "25000", "website": "", "brief": brief}
    if files:
        data["files"] = files
    return fake.client.post("/api/public/contact", data=data, content_type="multipart/form-data",
                            headers={"Origin": ORIGIN})


def test_request_becomes_issue_with_labels_and_job_folder(github):
    response = _post(github, files=[(io.BytesIO(b"%PDF-1.4"), "Briefing (final).pdf")])
    assert response.status_code == 200, response.get_json()

    method, path, issue = github.calls[0]
    assert (method, path) == ("POST", "/repos/Gurgenbaba/auftraege/issues")
    assert issue["title"] == "Auftrag: Online-Shop – Anna Schmidt"
    assert issue["labels"] == ["neu", "typ: Online-Shop", "budget: bis 500 €", "prüfen"]
    assert "### A1 Zahlungen" in issue["body"]

    puts = [(p, b) for m, p, b in github.calls if m == "PUT"]
    folder = "/repos/Gurgenbaba/auftraege/contents/auftraege/0007-2"
    assert puts[0][0].startswith(folder) and puts[0][0].endswith("-online-shop-anna-schmidt/AUFTRAG.md")
    auftrag = base64.b64decode(puts[0][1]["content"]).decode("utf-8")
    assert auftrag.startswith("<!-- Ticket #7: https://github.com/Gurgenbaba/auftraege/issues/7 -->")
    assert puts[1][0].endswith("/anhaenge/Briefing%20_final_.pdf")
    assert base64.b64decode(puts[1][1]["content"]) == b"%PDF-1.4"

    method, path, patch = github.calls[-1]
    assert (method, path) == ("PATCH", "/repos/Gurgenbaba/auftraege/issues/7")
    assert "**Ordner im Repo:**" in patch["body"] and "anhaenge/Briefing%20_final_.pdf" in patch["body"]


def test_request_without_brief_still_gets_a_ticket(github):
    _post(github, brief="")
    issue = github.calls[0][2]
    assert issue["title"] == "Projektanfrage: Online-Shop – Anna Schmidt"
    assert issue["labels"] == ["neu"]
    assert "> ich interessiere mich für einen Online-Shop." in issue["body"]


def test_ticket_alone_counts_as_delivered_and_failure_reports_send_failed(github):
    assert _post(github).status_code == 200
    github.fail_issue = True
    response = _post(github)
    assert response.status_code == 502
    assert response.get_json()["error"] == "send_failed"


def test_upload_conflict_is_retried_once(github):
    github.conflicts = 1
    _post(github)
    puts = [p for m, p, _ in github.calls if m == "PUT"]
    assert len(puts) == 2 and puts[0] == puts[1]
    assert "Nicht abgelegt" not in github.calls[-1][2]["body"]


def test_discord_links_the_ticket(github, monkeypatch):
    monkeypatch.setenv("CONTACT_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/1/x")
    _post(github)
    raw = next(c for c in github.calls if c[0] == "DISCORD")[2]["raw"].decode("utf-8", "replace")
    payload = json.loads(re.search(r"application/json\r\n\r\n(.*?)\r\n--", raw, re.S).group(1))
    embed = payload["embeds"][0]
    assert embed["url"] == "https://github.com/Gurgenbaba/auftraege/issues/7"
    assert any(f["name"] == "🎫 Ticket" and "#7" in f["value"] for f in embed["fields"])


@pytest.mark.parametrize("repo", ["", "no-slash", "a/b/c", "../etc/passwd"])
def test_bad_repo_setting_disables_tickets(monkeypatch, repo):
    monkeypatch.setenv("CONTACT_GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("CONTACT_GITHUB_REPO", repo)
    assert tickets.github_config() is None
