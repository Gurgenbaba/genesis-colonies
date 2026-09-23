"""File portfolio requests as tickets in a private GitHub repository.

Every request becomes an issue (the ticket, status via labels) and a folder
``auftraege/<issue>-<slug>/`` with ``AUFTRAG.md`` and the customer's
attachments, so a coding agent can pick the job up straight from the repo.

Environment:
    CONTACT_GITHUB_TOKEN  fine-grained token for that one repository only,
                          permissions: Issues read/write, Contents read/write
    CONTACT_GITHUB_REPO   owner/name, e.g. Gurgenbaba/auftraege

The token travels only in the Authorization header and is never logged.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from game.contact_brief import WorkOrder

logger = logging.getLogger(__name__)

API = "https://api.github.com"
TIMEOUT_SECONDS = 10
UPLOAD_BUDGET_SECONDS = 15  # stay well inside the Gunicorn worker timeout
_REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


@dataclass
class Ticket:
    number: int
    url: str
    folder: str
    folder_url: str


def github_config() -> tuple[str, str] | None:
    token = (os.environ.get("CONTACT_GITHUB_TOKEN") or "").strip()
    repo = (os.environ.get("CONTACT_GITHUB_REPO") or "").strip()
    if not token or not _REPO_RE.match(repo):
        return None
    return token, repo


def _api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "GenesisColoniesContact/1.0 (+https://genesis-colonies.com)",
    })
    with urlopen(req, timeout=TIMEOUT_SECONDS) as res:
        raw = res.read()
    return json.loads(raw) if raw else {}


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", name, flags=re.UNICODE).strip(" .") or "anhang"
    return cleaned[:100]


def _put_file(repo: str, token: str, path: str, data: bytes, message: str) -> None:
    body = {"message": message, "content": base64.b64encode(data).decode("ascii")}
    url = f"/repos/{repo}/contents/{quote(path)}"
    try:
        _api("PUT", url, token, body)
    except HTTPError as exc:
        if exc.code != 409:  # another request moved the branch at the same moment: retry once
            raise
        _api("PUT", url, token, body)


def file_ticket(order: WorkOrder, attachments: list[tuple[str, bytes, str]]) -> Ticket | None:
    """Create the issue and the job folder. None if the issue could not be created."""
    config = github_config()
    if not config:
        return None
    token, repo = config
    try:
        issue = _api("POST", f"/repos/{repo}/issues", token, {
            "title": order.subject[:256],
            "body": order.markdown[:60000],
            "labels": order.labels,
        })
    except Exception as exc:
        logger.warning("contact ticket failed: %s", type(exc).__name__)
        return None

    number = int(issue["number"])
    slug = re.sub(r"^(auftrag|anfrage)-", "", order.filename.removesuffix(".md"))
    folder = f"auftraege/{number:04d}-{slug}"
    branch_url = f"https://github.com/{repo}/blob/HEAD"
    ticket = Ticket(number, issue["html_url"], folder, f"https://github.com/{repo}/tree/HEAD/{quote(folder)}")

    header = f"<!-- Ticket #{number}: {ticket.url} -->\n"
    files = [("AUFTRAG.md", (header + order.markdown).encode("utf-8"))]
    used = {"AUFTRAG.md"}
    for name, data, _ in attachments:
        safe = _safe_filename(name)
        while safe in used:
            safe = "_" + safe
        used.add(safe)
        files.append((f"anhaenge/{safe}", data))

    started = time.monotonic()
    stored: list[str] = []
    for rel, data in files:
        if time.monotonic() - started > UPLOAD_BUDGET_SECONDS:
            break
        try:
            _put_file(repo, token, f"{folder}/{rel}", data, f"Auftrag #{number}: {rel}")
            stored.append(rel)
        except Exception as exc:
            logger.warning("contact ticket upload failed: %s", type(exc).__name__)
            break

    missing = [rel for rel, _ in files if rel not in stored]
    lines = ["", "---", "", f"**Ordner im Repo:** [`{folder}/`]({ticket.folder_url})", ""]
    lines += [f"- [{rel}]({branch_url}/{quote(folder)}/{quote(rel)})" for rel in stored]
    if missing:
        lines += ["", "⚠️ Nicht abgelegt (Upload fehlgeschlagen, siehe Discord/Mail): " + ", ".join(missing)]
    try:
        _api("PATCH", f"/repos/{repo}/issues/{number}", token,
             {"body": (order.markdown + "\n".join(lines) + "\n")[:65000]})
    except Exception as exc:
        logger.warning("contact ticket update failed: %s", type(exc).__name__)
    return ticket
