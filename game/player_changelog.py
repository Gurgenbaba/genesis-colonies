"""Player-facing development changelog built from the public Git history.

The Version surface is intentionally independent from Universe News and from the
universe_news database. GitHub is queried lazily and cached; production never
executes git. Every non-merge commit is represented. Merge commits are counted
but collapsed because they duplicate their child commits.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY = "Gurgenbaba/genesis-colonies"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}/commits"
CACHE_TTL_SECONDS = max(900, int(os.environ.get("GC_PLAYER_CHANGELOG_CACHE_TTL", "21600") or 21600))
MAX_PAGES = max(1, min(30, int(os.environ.get("GC_PLAYER_CHANGELOG_MAX_PAGES", "20") or 20)))
PER_PAGE = 100

_CACHE_LOCK = threading.Lock()
_MEMORY_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}

_PREFIX_RE = re.compile(
    r"^(feat|feature|fix|perf|performance|balance|refactor|improve|docs|test|ci|chore|build|style)"
    r"(?:\(([^)]+)\))?:\s*(.+)$",
    re.I,
)
_ISSUE_SUFFIX_RE = re.compile(r"\s*\(#\d+\)\s*$")
_GC_TOKEN_RE = re.compile(r"\bGC-[A-Z0-9.-]+\b", re.I)
_WHITESPACE_RE = re.compile(r"\s+")

_TECH_PREFIXES = frozenset({"docs", "test", "ci", "chore", "build", "style"})
_CATEGORY_BY_PREFIX = {
    "feat": "New Features",
    "feature": "New Features",
    "fix": "Fixes",
    "perf": "Performance",
    "performance": "Performance",
    "balance": "Balance",
    "refactor": "Improvements",
    "improve": "Improvements",
    "docs": "Technical & Reliability",
    "test": "Technical & Reliability",
    "ci": "Technical & Reliability",
    "chore": "Technical & Reliability",
    "build": "Technical & Reliability",
    "style": "UI & UX",
}
_SCOPE_NAMES = {
    "wb": "World Boss",
    "world-boss": "World Boss",
    "world_boss": "World Boss",
    "pe": "Planet Evolution",
    "planet-evolution": "Planet Evolution",
    "planet_evolution": "Planet Evolution",
    "fleet": "Fleet",
    "galaxy": "Galaxy",
    "i18n": "Localization",
    "news": "News",
    "ranking": "Ranking",
    "ui": "UI",
    "ux": "UX",
    "migrations": "Database",
    "migration": "Database",
    "admin": "Administration",
    "alliance": "Alliance",
    "shop": "Shop",
    "combat": "Combat",
    "research": "Research",
    "buildings": "Buildings",
    "asteroid": "Asteroids",
    "asteroids": "Asteroids",
}

_TERM_REPLACEMENTS = (
    (re.compile(r"\bPJAX\b", re.I), "in-page navigation"),
    (re.compile(r"\bi18n\b", re.I), "localization"),
    (re.compile(r"\bSSR\b", re.I), "server-rendered pages"),
    (re.compile(r"\bSQLite\b", re.I), "database"),
    (re.compile(r"\bN\+1\b", re.I), "repeated database queries"),
    (re.compile(r"\bcodemod\b", re.I), "automated update"),
    (re.compile(r"\bfixtures?\b", re.I), "test data"),
    (re.compile(r"\bpolling\b", re.I), "background refresh"),
    (re.compile(r"\bpoll\b", re.I), "background refresh"),
    (re.compile(r"\bhot path\b", re.I), "frequently used path"),
    (re.compile(r"\bRTT\b", re.I), "response time"),
)

_GERMAN_WORDS = {
    "behebe": "fix",
    "beheben": "fix",
    "verbessere": "improve",
    "verbessern": "improve",
    "aktualisiere": "update",
    "aktualisieren": "update",
    "entferne": "remove",
    "entfernen": "remove",
    "füge": "add",
    "hinzu": "",
    "flotte": "fleet",
    "flotten": "fleets",
    "forschung": "research",
    "gebäude": "buildings",
    "übersicht": "overview",
    "anzeige": "display",
    "fehler": "issue",
    "spieler": "players",
    "ressourcen": "resources",
    "sprache": "language",
    "sprachen": "languages",
    "galaxie": "galaxy",
    "kampf": "combat",
}

def _fallback_milestones() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parent.parent / "data" / "player_changelog_fallback.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return payload if isinstance(payload, list) else []



def _cache_path() -> Path:
    configured = os.environ.get("GC_PLAYER_CHANGELOG_CACHE_PATH", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([Path("/data/player_changelog_cache.json"), Path("/tmp/player_changelog_cache.json")])
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            test = candidate.parent / ".gc-changelog-write-test"
            test.write_text("1", encoding="utf-8")
            test.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    return Path("/tmp/player_changelog_cache.json")


def _current_deploy_sha() -> str:
    for key in ("RAILWAY_GIT_COMMIT_SHA", "GC_GIT_SHA", "SOURCE_COMMIT", "GIT_COMMIT"):
        value = str(os.environ.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _read_disk_cache() -> dict[str, Any] | None:
    path = _cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _write_disk_cache(payload: dict[str, Any]) -> None:
    path = _cache_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Genesis-Colonies-Player-Changelog/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = str(os.environ.get("GC_GITHUB_PUBLIC_TOKEN", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_github_history() -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    headers = _github_headers()
    for page in range(1, MAX_PAGES + 1):
        query = urlencode({"sha": "main", "per_page": PER_PAGE, "page": page})
        req = Request(f"{API_ROOT}?{query}", headers=headers)
        try:
            with urlopen(req, timeout=6.0) as resp:  # nosec B310 - fixed GitHub host
                chunk = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            if commits:
                break
            raise RuntimeError(f"github_history_unavailable:{exc.__class__.__name__}") from exc
        if not isinstance(chunk, list):
            break
        commits.extend(row for row in chunk if isinstance(row, dict))
        if len(chunk) < PER_PAGE:
            break
    return commits


def _clean_text(text: str) -> str:
    value = str(text or "").replace("`", "")
    value = _ISSUE_SUFFIX_RE.sub("", value)
    value = _GC_TOKEN_RE.sub("", value)
    for pattern, replacement in _TERM_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    words = []
    for token in value.split():
        key = token.lower().strip(".,:;!?()[]{}")
        replacement = _GERMAN_WORDS.get(key)
        if replacement is None:
            words.append(token)
            continue
        prefix = token[: len(token) - len(token.lstrip("([{"))]
        suffix = token[len(token.rstrip(".,:;!?)]}")) :]
        if replacement:
            words.append(f"{prefix}{replacement}{suffix}")
    value = " ".join(words)
    value = _WHITESPACE_RE.sub(" ", value).strip(" -—–:;.")
    return value


def _friendly_area(scope: str, text: str) -> str:
    scope_key = str(scope or "").strip().lower()
    if scope_key in _SCOPE_NAMES:
        return _SCOPE_NAMES[scope_key]
    lowered = text.lower()
    checks = (
        ("world boss", "World Boss"),
        ("asteroid", "Asteroids"),
        ("planet evolution", "Planet Evolution"),
        ("fleet", "Fleet"),
        ("galaxy", "Galaxy"),
        ("alliance", "Alliance"),
        ("ranking", "Ranking"),
        ("research", "Research"),
        ("building", "Buildings"),
        ("shop", "Shop"),
        ("combat", "Combat"),
        ("localization", "Localization"),
        ("locale", "Localization"),
        ("mobile", "Mobile"),
        ("ui", "UI"),
        ("ux", "UX"),
    )
    for needle, label in checks:
        if needle in lowered:
            return label
    return "Game"


def _specific_player_summary(text: str) -> str | None:
    low = text.lower()
    if "asteroid" in low and "fuel" in low:
        return "Increased standard asteroid rewards and added fuel, Harvester count and flight-time previews before harvesting."
    if "world boss" in low and "raid" in low:
        return "Expanded World Bosses into a server-wide community raid with shared progression, phase mechanics and stronger anti-solo scaling."
    if "fleet" in low and ("failure" in low or "reason" in low or "shortcut" in low):
        return "Fleet shortcuts now explain clearly why a launch is blocked instead of failing without useful feedback."
    if "planet evolution" in low and ("locked" in low or "guidance" in low):
        return "Planet Evolution now explains what is still required to unlock the next research step."
    if "late-game resource" in low and "overflow" in low:
        return "Fixed late-game resource balances that could exceed the database integer range and break authenticated pages."
    if "sentinel" in low and "browser" in low:
        return "Added automated browser journeys that verify important player flows and catch interface regressions before release."
    if "fleet" in low and ("deadline" in low or "due probe" in low or "background refresh" in low):
        return "Reduced background Fleet arrival checks so active fleets create less server load while keeping exact arrival times authoritative."
    return None


def _first_body_paragraph(message: str) -> str:
    lines = str(message or "").splitlines()[1:]
    parts: list[str] = []
    for line in lines:
        raw = line.strip()
        if not raw:
            if parts:
                break
            continue
        if raw.lower().startswith(("co-authored-by:", "signed-off-by:", "---------")):
            continue
        if raw.startswith("* chore:") or raw.startswith("* test:") or raw.startswith("* ci:"):
            continue
        parts.append(raw.lstrip("-* "))
    detail = _clean_text(" ".join(parts))
    if len(detail) > 420:
        detail = detail[:417].rsplit(" ", 1)[0] + "…"
    return detail


def humanize_commit(message: str) -> dict[str, Any] | None:
    raw_message = str(message or "").strip()
    if not raw_message:
        return None
    subject = raw_message.splitlines()[0].strip()
    if subject.lower().startswith(("merge pull request", "merge pr #", "merge branch", "merge remote", "merge ")):
        return None

    prefix = ""
    scope = ""
    core = subject
    match = _PREFIX_RE.match(subject)
    if match:
        prefix = match.group(1).lower()
        scope = str(match.group(2) or "").strip()
        core = match.group(3).strip()

    technical = prefix in _TECH_PREFIXES
    category = _CATEGORY_BY_PREFIX.get(prefix, "Improvements")
    cleaned = _clean_text(core)
    area = _friendly_area(scope, cleaned or subject)
    specific = None if technical else _specific_player_summary(f"{scope} {cleaned}")
    if specific:
        title = specific
        technical = False
        if "fixed" in specific.lower():
            category = "Fixes"
        elif "reduced" in specific.lower():
            category = "Performance"
        else:
            category = _CATEGORY_BY_PREFIX.get(prefix, "Improvements")
    else:
        if not cleaned:
            cleaned = f"Updated {area} behavior"
        title = cleaned[0].upper() + cleaned[1:] if cleaned else f"Updated {area} behavior"
        if not title.endswith((".", "!", "?")):
            title += "."

    detail = _first_body_paragraph(raw_message)
    if detail and detail.rstrip(".").lower() == title.rstrip(".").lower():
        detail = ""
    if technical and not detail:
        detail = "Internal development, quality or deployment maintenance supporting the live game."

    return {
        "category": category,
        "area": area,
        "title": title,
        "detail": detail,
        "technical": technical,
    }


def _normalize_commit_row(row: dict[str, Any]) -> dict[str, Any] | None:
    commit = row.get("commit") if isinstance(row.get("commit"), dict) else {}
    message = str(commit.get("message") or "").strip()
    human = humanize_commit(message)
    if human is None:
        return None
    author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
    date_raw = str(author.get("date") or "")
    date = date_raw[:10] if len(date_raw) >= 10 else "Unknown"
    sha = str(row.get("sha") or "")
    url = str(row.get("html_url") or "")
    human.update({"date": date, "sha": sha[:8], "source_sha": sha, "url": url})
    return human


def build_changelog_payload_from_commits(commits: list[dict[str, Any]], *, source: str = "github") -> dict[str, Any]:
    days: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
    merge_count = 0
    represented = 0
    technical_count = 0
    for row in commits:
        commit = row.get("commit") if isinstance(row.get("commit"), dict) else {}
        message = str(commit.get("message") or "")
        subject = message.splitlines()[0].strip().lower() if message else ""
        if subject.startswith(("merge pull request", "merge pr #", "merge branch", "merge remote", "merge ")):
            merge_count += 1
            continue
        item = _normalize_commit_row(row)
        if item is None:
            continue
        represented += 1
        if item.get("technical"):
            technical_count += 1
        days.setdefault(item["date"], []).append(item)

    groups = [{"date": date, "entries": entries} for date, entries in days.items()]
    head_sha = str(commits[0].get("sha") or "") if commits else ""
    return {
        "ok": True,
        "source": source,
        "repository": REPOSITORY,
        "language": "en",
        "generated_at": int(time.time()),
        "head_sha": head_sha,
        "total_commits_seen": len(commits),
        "represented_commits": represented,
        "technical_commits": technical_count,
        "merge_commits_collapsed": merge_count,
        "groups": groups,
    }


def _fallback_payload() -> dict[str, Any]:
    groups = []
    represented = 0
    for milestone in _fallback_milestones():
        entries = []
        for item in milestone["items"]:
            entries.append(
                {
                    "category": "Milestone",
                    "area": "Game",
                    "title": item,
                    "detail": "",
                    "technical": False,
                    "date": milestone["date"],
                    "sha": "",
                    "source_sha": "",
                    "url": "",
                    "milestone": milestone["title"],
                }
            )
            represented += 1
        groups.append({"date": milestone["date"], "label": milestone["title"], "entries": entries})
    return {
        "ok": True,
        "source": "bundled-fallback",
        "repository": REPOSITORY,
        "language": "en",
        "generated_at": int(time.time()),
        "head_sha": "",
        "total_commits_seen": 0,
        "represented_commits": represented,
        "technical_commits": 0,
        "merge_commits_collapsed": 0,
        "groups": groups,
        "warning": "Live Git history was unavailable; showing the bundled milestone history.",
    }


def get_player_changelog(*, force_refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    current_sha = _current_deploy_sha()
    with _CACHE_LOCK:
        payload = _MEMORY_CACHE.get("payload")
        if (
            not force_refresh
            and isinstance(payload, dict)
            and float(_MEMORY_CACHE.get("expires_at") or 0) > now
            and (not current_sha or not payload.get("head_sha") or str(payload.get("head_sha")).startswith(current_sha[:8]))
        ):
            return payload

        disk = _read_disk_cache()
        if not force_refresh and isinstance(disk, dict):
            fetched_at = int(disk.get("generated_at") or 0)
            same_head = not current_sha or not disk.get("head_sha") or str(disk.get("head_sha")).startswith(current_sha[:8])
            if same_head and fetched_at and now - fetched_at < CACHE_TTL_SECONDS:
                _MEMORY_CACHE["payload"] = disk
                _MEMORY_CACHE["expires_at"] = now + CACHE_TTL_SECONDS
                return disk

        try:
            commits = _fetch_github_history()
            fresh = build_changelog_payload_from_commits(commits)
            if len(commits) >= MAX_PAGES * PER_PAGE:
                fresh["warning"] = f"History reached the configured {MAX_PAGES * PER_PAGE}-commit safety limit."
            _write_disk_cache(fresh)
            _MEMORY_CACHE["payload"] = fresh
            _MEMORY_CACHE["expires_at"] = now + CACHE_TTL_SECONDS
            return fresh
        except RuntimeError as exc:
            if isinstance(disk, dict) and disk.get("groups"):
                stale = dict(disk)
                stale["warning"] = "GitHub is temporarily unavailable; showing the last cached complete history."
                stale["stale"] = True
                _MEMORY_CACHE["payload"] = stale
                _MEMORY_CACHE["expires_at"] = now + 900
                return stale
            fallback = _fallback_payload()
            fallback["warning"] = str(fallback.get("warning") or "")
            fallback["error_code"] = str(exc).split(":", 1)[0]
            _MEMORY_CACHE["payload"] = fallback
            _MEMORY_CACHE["expires_at"] = now + 900
            return fallback


def register_player_changelog_routes(app) -> None:
    from flask import jsonify
    from game.auth import require_login_api

    endpoint = "api_player_changelog_history"
    if endpoint in app.view_functions:
        return

    @app.get("/api/changelog/history", endpoint=endpoint)
    @require_login_api
    def _player_changelog_history():
        return jsonify(get_player_changelog())
