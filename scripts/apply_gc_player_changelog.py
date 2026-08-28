#!/usr/bin/env python3
"""GC-CHANGELOG-001: install the full Git-backed player changelog surface."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PLAYER_CHANGELOG_PY = r'''"""Player-facing development changelog built from the public Git history.

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

_FALLBACK_MILESTONES = [
    {
        "date": "2026-08-13",
        "title": "v0.9.4 — Live Galaxy & Mega Belts",
        "items": [
            "Added rare server-wide Mega Belt asteroids with very large, storage-scaled resource pools and multi-fleet harvesting.",
            "Added live Galaxy updates so harvested asteroid fields disappear without waiting for a page reload.",
            "Improved asteroid cards with tier and remaining-pool information.",
        ],
    },
    {
        "date": "2026-08-05",
        "title": "v0.9.3 — Command Initiation, World Boss & Vault",
        "items": [
            "Added Command Initiation onboarding, World Boss cinematics and the Secret Vault / ground-troop layer.",
            "Improved building-stage interactions, Login Rewards, Battle Pass and Shop claim updates.",
            "Hardened Planet Evolution, Story Ops, locale coverage and live state synchronization.",
        ],
    },
    {
        "date": "2026-08-04",
        "title": "v0.9.2 — Knowledge, LiveOps & Colony Stage",
        "items": [
            "Expanded the Codex and player guidance across the major LiveOps systems.",
            "Added the interactive colony building stage with inline upgrades and per-planet layouts.",
            "Improved stage visuals, identity colors, layout persistence and Planet switching.",
        ],
    },
    {
        "date": "2026-08-01",
        "title": "v0.9.1 — Effective Stats & Polyglot Story",
        "items": [
            "Made effective ship, defense and research bonuses visible throughout the interface.",
            "Localized Story Ops and player patch notes across all supported game languages.",
            "Improved Titan progress, Commander bonuses and Timekeeper completion updates.",
        ],
    },
    {
        "date": "2026-07-31",
        "title": "v0.9 — LiveOps & World Events",
        "items": [
            "Introduced World Bosses, Titans, pirates, Login Rewards, Season Pass, Story Ops and Commander Classes.",
            "Expanded Alliance, Shop, Identity, Fleet Logistics, Combat Reports and Collector systems.",
            "Hardened live updates, queues, Planet switching and multiple World Boss / Tech Tree edge cases.",
        ],
    },
    {
        "date": "2026-06-30",
        "title": "v0.8 — UX Polish & Alpha Hardening",
        "items": [
            "Expanded empire overview, records, referrals, galactic directives, diplomacy and messages.",
            "Reworked navigation, building and research cards, mobile HUD and player profiles.",
            "Reduced background refresh storms, database lock pressure and rendering overhead.",
        ],
    },
    {
        "date": "2026-06-15",
        "title": "v0.7 — Command Map & Genesis 2.0",
        "items": [
            "Built the Command Map, regions, sectors, chokepoints, influence and expansion sites.",
            "Added strategic worlds, dynamic colonization and expedition-world progression.",
            "Moved Planet Evolution toward the central long-term progression role.",
        ],
    },
    {
        "date": "2026-06-10",
        "title": "v0.6 — Social, Ranking & LiveOps",
        "items": [
            "Added Vote Center, Auction House, Inventory, Lootboxes, Chat, Support, Ranking and Hall of Fame systems.",
            "Expanded player profiles, messages and social progression.",
            "Improved ranking safety, chat updates and vote cooldown handling.",
        ],
    },
    {
        "date": "2026-06-05",
        "title": "v0.5 — Combat & Defense",
        "items": [
            "Added planetary defenses, combat simulation, reports, debris, recycling and advanced espionage.",
            "Integrated research and effect bonuses into battle resolution.",
            "Fixed short-flight timers, coordinate navigation and combat-report consistency.",
        ],
    },
    {
        "date": "2026-06-01",
        "title": "v0.4 — Galaxy & Fleet",
        "items": [
            "Added Galaxy navigation, Shipyard queues, Fleet missions, Expeditions, Logistics and Trader Hub.",
            "Added fleet presets, tactical sending, fleet slots and planet landscapes.",
            "Hardened colonization, logistics cargo rules and concurrent Fleet / queue operations.",
        ],
    },
    {
        "date": "2026-05-30",
        "title": "v0.3 — Planet Scope & Colonies",
        "items": [
            "Added multi-colony Planet scope, colonization, Planet Evolution, Planet research and trade routes.",
            "Added planet management and colony-aware overview information.",
            "Made building, research and economy actions respect the active Planet consistently.",
        ],
    },
    {
        "date": "2026-05-27",
        "title": "v0.2 — Economy Core",
        "items": [
            "Added authentication, resources, buildings, research, queues, ranking and the first SPA navigation layer.",
            "Established the canonical effect and production systems plus the Brennzellen fuel depot.",
            "Added idempotent actions and live queue / research updates.",
        ],
    },
    {
        "date": "2026-05-25",
        "title": "v0.1 — Foundation",
        "items": [
            "Created the Flask game foundation, database migrations, persistence and Admin Control Center.",
            "Added the first research queue, SPA shell, deployment pipeline and health checks.",
            "Established automated tests and the project architecture documentation.",
        ],
    },
]


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
    for milestone in _FALLBACK_MILESTONES:
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
'''

DIALOG_HTML = r'''<link rel="stylesheet" href="{{ url_for('static', filename='css/player_changelog.css') }}?v={{ GC_ASSET_VERSION }}">

<dialog class="gc-player-changelog" data-gc-changelog-dialog
        data-label-loading="{{ T('changelog_loading', 'Loading complete development history…') }}"
        data-label-error="{{ T('changelog_load_error', 'The changelog could not be loaded.') }}"
        data-label-commits="{{ T('changelog_commits', 'commits') }}"
        data-label-technical="{{ T('changelog_technical_count', 'technical') }}"
        data-label-merges="{{ T('changelog_merges_collapsed', 'merge commits collapsed') }}"
        aria-labelledby="gc-player-changelog-title">
  <section class="gc-player-changelog-shell">
    <header class="gc-player-changelog-head">
      <div>
        <span class="gc-player-changelog-eyebrow">GENESIS COLONIES · GIT HISTORY</span>
        <h2 id="gc-player-changelog-title">{{ T('changelog_full_title', 'Full Development Changelog') }}</h2>
        <p>{{ T('changelog_full_intro', 'Every meaningful repository change, rewritten into readable English. Merge duplicates are collapsed; technical work remains available in the All commits view.') }}</p>
      </div>
      <button type="button" class="gc-btn gc-btn-ghost gc-btn-sm" data-gc-changelog-close aria-label="{{ T('close', 'Close') }}">✕</button>
    </header>

    <div class="gc-player-changelog-controls">
      <label class="gc-player-changelog-search">
        <span aria-hidden="true">⌕</span>
        <input type="search" data-gc-changelog-search placeholder="{{ T('changelog_search_placeholder', 'Search version, system or change…') }}" autocomplete="off">
      </label>
      <div class="gc-player-changelog-filters" role="group" aria-label="{{ T('changelog_filter_label', 'Changelog filter') }}">
        <button type="button" class="gc-btn gc-btn-primary gc-btn-xs is-active" data-gc-changelog-mode="player">{{ T('changelog_filter_player', 'Player changes') }}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-gc-changelog-mode="all">{{ T('changelog_filter_all', 'All commits') }}</button>
      </div>
    </div>

    <div class="gc-player-changelog-meta gc-mono" data-gc-changelog-meta></div>
    <div class="gc-player-changelog-status" data-gc-changelog-status aria-live="polite">{{ T('changelog_loading', 'Loading complete development history…') }}</div>
    <div class="gc-player-changelog-list" data-gc-changelog-list></div>
  </section>
</dialog>
<script src="{{ url_for('static', filename='js/player_changelog.js') }}?v={{ GC_ASSET_VERSION }}" defer></script>
'''

CHANGELOG_JS = r'''(() => {
  'use strict';

  const state = { payload: null, mode: 'player', query: '', loading: false };

  function dialog() { return document.querySelector('[data-gc-changelog-dialog]'); }
  function list() { const root = dialog(); return root ? root.querySelector('[data-gc-changelog-list]') : null; }
  function status() { const root = dialog(); return root ? root.querySelector('[data-gc-changelog-status]') : null; }
  function meta() { const root = dialog(); return root ? root.querySelector('[data-gc-changelog-meta]') : null; }

  function normalize(text) { return String(text || '').toLowerCase(); }

  function matches(entry) {
    if (state.mode !== 'all' && entry.technical) return false;
    const q = normalize(state.query).trim();
    if (!q) return true;
    return [entry.title, entry.detail, entry.category, entry.area, entry.date, entry.sha, entry.milestone]
      .some((part) => normalize(part).includes(q));
  }

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = String(text);
    return el;
  }

  function render() {
    const root = dialog();
    const target = list();
    if (!root || !target || !state.payload) return;
    target.replaceChildren();

    let visible = 0;
    let opened = 0;
    (state.payload.groups || []).forEach((group) => {
      const entries = (group.entries || []).filter(matches);
      if (!entries.length) return;
      visible += entries.length;

      const details = node('details', 'gc-player-changelog-day');
      if (opened < 3) details.open = true;
      opened += 1;
      const summary = node('summary', 'gc-player-changelog-day-head');
      summary.append(node('span', 'gc-player-changelog-date', group.label || group.date || 'Unknown date'));
      summary.append(node('span', 'gc-player-changelog-day-count gc-mono', `${entries.length}`));
      details.append(summary);

      const body = node('div', 'gc-player-changelog-day-body');
      entries.forEach((entry) => {
        const article = node('article', `gc-player-changelog-entry${entry.technical ? ' is-technical' : ''}`);
        const top = node('div', 'gc-player-changelog-entry-top');
        top.append(node('span', 'gc-player-changelog-category', entry.category || 'Update'));
        if (entry.area) top.append(node('span', 'gc-player-changelog-area', entry.area));
        if (entry.technical) top.append(node('span', 'gc-player-changelog-technical', 'TECH'));
        article.append(top);
        article.append(node('h3', 'gc-player-changelog-entry-title', entry.title || 'Update'));
        if (entry.detail) article.append(node('p', 'gc-player-changelog-entry-detail', entry.detail));
        if (entry.sha || entry.url) {
          const source = node('div', 'gc-player-changelog-source gc-mono');
          if (entry.url) {
            const link = node('a', '', entry.sha ? `source ${entry.sha}` : 'source');
            link.href = entry.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            source.append(link);
          } else if (entry.sha) {
            source.textContent = entry.sha;
          }
          article.append(source);
        }
        body.append(article);
      });
      details.append(body);
      target.append(details);
    });

    const stat = status();
    if (stat) {
      stat.hidden = visible > 0;
      stat.textContent = visible ? '' : 'No changelog entries match this filter.';
    }
  }

  function renderMeta() {
    const root = dialog();
    const el = meta();
    if (!root || !el || !state.payload) return;
    const commitsLabel = root.dataset.labelCommits || 'commits';
    const techLabel = root.dataset.labelTechnical || 'technical';
    const mergeLabel = root.dataset.labelMerges || 'merge commits collapsed';
    const bits = [];
    if (state.payload.total_commits_seen) bits.push(`${state.payload.total_commits_seen} ${commitsLabel}`);
    if (state.payload.technical_commits) bits.push(`${state.payload.technical_commits} ${techLabel}`);
    if (state.payload.merge_commits_collapsed) bits.push(`${state.payload.merge_commits_collapsed} ${mergeLabel}`);
    bits.push(`source: ${state.payload.source || 'unknown'}`);
    el.textContent = bits.join(' · ');
    if (state.payload.warning) el.title = state.payload.warning;
  }

  async function load() {
    if (state.payload || state.loading) return;
    state.loading = true;
    const root = dialog();
    const stat = status();
    if (stat) {
      stat.hidden = false;
      stat.textContent = root?.dataset.labelLoading || 'Loading complete development history…';
    }
    try {
      const response = await fetch('/api/changelog/history', { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      const payload = await response.json();
      if (!response.ok || !payload || payload.ok === false) throw new Error('changelog unavailable');
      state.payload = payload;
      renderMeta();
      render();
    } catch (error) {
      if (stat) stat.textContent = root?.dataset.labelError || 'The changelog could not be loaded.';
    } finally {
      state.loading = false;
    }
  }

  function open() {
    const root = dialog();
    if (!root) return;
    if (typeof root.showModal === 'function') {
      if (!root.open) root.showModal();
    } else {
      root.setAttribute('open', '');
    }
    load();
  }

  function close() {
    const root = dialog();
    if (!root) return;
    if (typeof root.close === 'function' && root.open) root.close();
    else root.removeAttribute('open');
  }

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-gc-changelog-open]');
    if (opener) {
      event.preventDefault();
      open();
      return;
    }
    if (event.target.closest('[data-gc-changelog-close]')) {
      event.preventDefault();
      close();
      return;
    }
    const mode = event.target.closest('[data-gc-changelog-mode]');
    if (mode) {
      state.mode = mode.dataset.gcChangelogMode || 'player';
      document.querySelectorAll('[data-gc-changelog-mode]').forEach((btn) => {
        const active = btn === mode;
        btn.classList.toggle('is-active', active);
        btn.classList.toggle('gc-btn-primary', active);
        btn.classList.toggle('gc-btn-outline', !active);
      });
      render();
    }
  });

  document.addEventListener('input', (event) => {
    if (!event.target.matches('[data-gc-changelog-search]')) return;
    state.query = event.target.value || '';
    render();
  });

  document.addEventListener('cancel', (event) => {
    if (event.target.matches('[data-gc-changelog-dialog]')) close();
  });

  document.addEventListener('click', (event) => {
    const root = dialog();
    if (root && event.target === root) close();
  });

  window.GC = window.GC || {};
  window.GC.openPlayerChangelog = open;
})();
'''

CHANGELOG_CSS = r'''.gc-player-changelog {
  width: min(1120px, calc(100vw - 2rem));
  max-width: 1120px;
  height: min(86vh, 920px);
  max-height: 920px;
  padding: 0;
  border: 1px solid rgba(var(--gc-id-rgb, 70, 229, 255), .5);
  background: #071019;
  color: var(--gc-text, #eaf6ff);
  box-shadow: 0 24px 80px rgba(0, 0, 0, .65), 0 0 36px rgba(var(--gc-id-rgb, 70, 229, 255), .12);
}
.gc-player-changelog::backdrop { background: rgba(0, 4, 10, .82); backdrop-filter: blur(5px); }
.gc-player-changelog-shell { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.gc-player-changelog-head { display: flex; justify-content: space-between; gap: 1rem; padding: 1rem 1.15rem .85rem; border-bottom: 1px solid rgba(var(--gc-id-rgb, 70, 229, 255), .22); background: linear-gradient(180deg, rgba(var(--gc-id-rgb, 70, 229, 255), .09), transparent); }
.gc-player-changelog-head h2 { margin: .2rem 0 .35rem; font-family: Orbitron, sans-serif; font-size: clamp(1.05rem, 2.4vw, 1.45rem); letter-spacing: .03em; }
.gc-player-changelog-head p { margin: 0; max-width: 780px; color: var(--gc-text-muted, #91a7b8); line-height: 1.45; font-size: .88rem; }
.gc-player-changelog-eyebrow { font: 700 .68rem/1 JetBrains Mono, monospace; letter-spacing: .16em; color: rgb(var(--gc-id-rgb, 70, 229, 255)); }
.gc-player-changelog-controls { display: flex; gap: .65rem; align-items: center; padding: .75rem 1.15rem; border-bottom: 1px solid rgba(255,255,255,.07); }
.gc-player-changelog-search { flex: 1 1 360px; display: flex; align-items: center; gap: .5rem; border: 1px solid rgba(255,255,255,.12); background: rgba(0,0,0,.22); padding: .5rem .7rem; }
.gc-player-changelog-search input { width: 100%; border: 0; outline: 0; background: transparent; color: inherit; font: inherit; }
.gc-player-changelog-filters { display: flex; gap: .35rem; }
.gc-player-changelog-meta { padding: .55rem 1.15rem; color: var(--gc-text-muted, #91a7b8); border-bottom: 1px solid rgba(255,255,255,.06); font-size: .72rem; }
.gc-player-changelog-status { padding: 1.2rem; color: var(--gc-text-muted, #91a7b8); }
.gc-player-changelog-list { overflow: auto; min-height: 0; padding: .7rem 1.15rem 1.2rem; scrollbar-gutter: stable; }
.gc-player-changelog-day { border: 1px solid rgba(255,255,255,.08); background: rgba(255,255,255,.025); margin-bottom: .55rem; }
.gc-player-changelog-day-head { display: flex; align-items: center; justify-content: space-between; gap: .75rem; padding: .7rem .8rem; cursor: pointer; user-select: none; }
.gc-player-changelog-day-head::marker { color: rgb(var(--gc-id-rgb, 70, 229, 255)); }
.gc-player-changelog-date { font: 700 .82rem/1.2 Orbitron, sans-serif; letter-spacing: .035em; }
.gc-player-changelog-day-count { min-width: 2rem; text-align: center; padding: .16rem .42rem; border: 1px solid rgba(var(--gc-id-rgb, 70, 229, 255), .25); color: rgb(var(--gc-id-rgb, 70, 229, 255)); font-size: .7rem; }
.gc-player-changelog-day-body { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .55rem; padding: 0 .65rem .65rem; }
.gc-player-changelog-entry { min-width: 0; border-left: 2px solid rgba(var(--gc-id-rgb, 70, 229, 255), .65); background: rgba(0,0,0,.18); padding: .7rem .75rem; }
.gc-player-changelog-entry.is-technical { border-left-color: rgba(160,170,185,.45); opacity: .84; }
.gc-player-changelog-entry-top { display: flex; flex-wrap: wrap; gap: .35rem; align-items: center; margin-bottom: .4rem; }
.gc-player-changelog-category, .gc-player-changelog-area, .gc-player-changelog-technical { font: 700 .62rem/1 JetBrains Mono, monospace; letter-spacing: .06em; padding: .18rem .35rem; border: 1px solid rgba(255,255,255,.1); color: var(--gc-text-muted, #91a7b8); }
.gc-player-changelog-category { color: rgb(var(--gc-id-rgb, 70, 229, 255)); border-color: rgba(var(--gc-id-rgb, 70, 229, 255), .25); }
.gc-player-changelog-entry-title { margin: 0; font-size: .9rem; line-height: 1.42; font-weight: 700; }
.gc-player-changelog-entry-detail { margin: .4rem 0 0; font-size: .78rem; line-height: 1.45; color: var(--gc-text-muted, #9db0bf); }
.gc-player-changelog-source { margin-top: .55rem; font-size: .66rem; }
.gc-player-changelog-source a { color: rgba(var(--gc-id-rgb, 70, 229, 255), .8); text-decoration: none; }
.gc-player-changelog-source a:hover { text-decoration: underline; }
.gc-bottom-util-version[data-gc-changelog-open] { appearance: none; border: 0; background: transparent; cursor: pointer; font: inherit; }
@media (max-width: 760px) {
  .gc-player-changelog { width: calc(100vw - .7rem); height: calc(100dvh - .7rem); max-height: none; }
  .gc-player-changelog-head { padding: .8rem; }
  .gc-player-changelog-controls { align-items: stretch; flex-direction: column; padding: .65rem .8rem; }
  .gc-player-changelog-search { flex: none; }
  .gc-player-changelog-filters { display: grid; grid-template-columns: 1fr 1fr; }
  .gc-player-changelog-meta { padding: .5rem .8rem; }
  .gc-player-changelog-list { padding: .55rem .8rem .9rem; }
  .gc-player-changelog-day-body { grid-template-columns: 1fr; }
}
'''

TEST_FILE = r'''from pathlib import Path

from game.player_changelog import build_changelog_payload_from_commits, humanize_commit

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _commit(sha: str, message: str, date: str = "2026-08-28T12:00:00Z"):
    return {
        "sha": sha,
        "html_url": f"https://github.com/Gurgenbaba/genesis-colonies/commit/{sha}",
        "commit": {"message": message, "author": {"date": date}},
    }


def test_humanizer_turns_gameplay_commit_into_readable_english():
    item = humanize_commit("feat: scale standard asteroid belts and preview harvest fuel")
    assert item is not None
    assert item["technical"] is False
    assert item["category"] == "New Features"
    assert "asteroid rewards" in item["title"].lower()
    assert "flight-time" in item["title"].lower()


def test_humanizer_keeps_internal_commits_available_but_marks_them_technical():
    item = humanize_commit("ci: rerun scoped World Boss raid gate")
    assert item is not None
    assert item["technical"] is True
    assert item["category"] == "Technical & Reliability"


def test_payload_represents_every_non_merge_commit_and_collapses_merges():
    commits = [
        _commit("a" * 40, "feat(fleet): add launch reason feedback"),
        _commit("b" * 40, "test: cover fleet reason feedback"),
        _commit("c" * 40, "Merge pull request #99 from feature/test"),
    ]
    payload = build_changelog_payload_from_commits(commits, source="test")
    assert payload["total_commits_seen"] == 3
    assert payload["represented_commits"] == 2
    assert payload["technical_commits"] == 1
    assert payload["merge_commits_collapsed"] == 1
    assert sum(len(group["entries"]) for group in payload["groups"]) == 2


def test_bottom_version_is_dialog_button_not_news_link():
    html = _read("templates/partials/bottom_utility_bar.html")
    assert "data-gc-changelog-open" in html
    version_block = html.split("gc-bottom-util-version", 1)[1]
    assert "news_view" not in version_block


def test_shell_has_persistent_changelog_dialog_assets():
    base = _read("templates/base.html")
    dialog = _read("templates/partials/player_changelog_dialog.html")
    assert 'partials/player_changelog_dialog.html' in base
    assert 'data-gc-changelog-dialog' in dialog
    assert 'js/player_changelog.js' in dialog
    assert 'css/player_changelog.css' in dialog


def test_community_changelog_opens_same_canonical_dialog():
    html = _read("templates/partials/special_panel.html")
    assert 'data-gc-changelog-open' in html
    assert 'data-special-window="changelog"' not in html
'''

LOCALE_VALUES = {
    "de": {
        "changelog_loading": "Vollständige Entwicklungshistorie wird geladen…",
        "changelog_load_error": "Der Changelog konnte nicht geladen werden.",
        "changelog_commits": "Commits",
        "changelog_technical_count": "technisch",
        "changelog_merges_collapsed": "Merge-Commits zusammengefasst",
        "changelog_full_title": "Vollständiger Entwicklungs-Changelog",
        "changelog_full_intro": "Jede relevante Repository-Änderung, verständlich auf Englisch aufbereitet. Doppelte Merge-Commits werden zusammengefasst; technische Änderungen bleiben unter Alle Commits sichtbar.",
        "changelog_search_placeholder": "Version, System oder Änderung suchen…",
        "changelog_filter_label": "Changelog-Filter",
        "changelog_filter_player": "Spieler-Änderungen",
        "changelog_filter_all": "Alle Commits",
    },
    "en": {
        "changelog_loading": "Loading complete development history…",
        "changelog_load_error": "The changelog could not be loaded.",
        "changelog_commits": "commits",
        "changelog_technical_count": "technical",
        "changelog_merges_collapsed": "merge commits collapsed",
        "changelog_full_title": "Full Development Changelog",
        "changelog_full_intro": "Every meaningful repository change, rewritten into readable English. Merge duplicates are collapsed; technical work remains available in the All commits view.",
        "changelog_search_placeholder": "Search version, system or change…",
        "changelog_filter_label": "Changelog filter",
        "changelog_filter_player": "Player changes",
        "changelog_filter_all": "All commits",
    },
    "fr": {
        "changelog_loading": "Chargement de l’historique complet du développement…",
        "changelog_load_error": "Le changelog n’a pas pu être chargé.",
        "changelog_commits": "commits",
        "changelog_technical_count": "techniques",
        "changelog_merges_collapsed": "commits de fusion regroupés",
        "changelog_full_title": "Changelog complet du développement",
        "changelog_full_intro": "Chaque changement important du dépôt est reformulé en anglais lisible. Les doublons de fusion sont regroupés et le travail technique reste disponible dans Tous les commits.",
        "changelog_search_placeholder": "Rechercher une version, un système ou un changement…",
        "changelog_filter_label": "Filtre du changelog",
        "changelog_filter_player": "Changements joueurs",
        "changelog_filter_all": "Tous les commits",
    },
    "es": {
        "changelog_loading": "Cargando el historial completo de desarrollo…",
        "changelog_load_error": "No se pudo cargar el changelog.",
        "changelog_commits": "commits",
        "changelog_technical_count": "técnicos",
        "changelog_merges_collapsed": "commits de merge agrupados",
        "changelog_full_title": "Changelog completo de desarrollo",
        "changelog_full_intro": "Cada cambio importante del repositorio se reescribe en inglés legible. Los merges duplicados se agrupan y el trabajo técnico sigue disponible en Todos los commits.",
        "changelog_search_placeholder": "Buscar versión, sistema o cambio…",
        "changelog_filter_label": "Filtro del changelog",
        "changelog_filter_player": "Cambios para jugadores",
        "changelog_filter_all": "Todos los commits",
    },
    "pl": {
        "changelog_loading": "Ładowanie pełnej historii rozwoju…",
        "changelog_load_error": "Nie udało się wczytać changelogu.",
        "changelog_commits": "commity",
        "changelog_technical_count": "techniczne",
        "changelog_merges_collapsed": "scalone commity merge",
        "changelog_full_title": "Pełny changelog rozwoju",
        "changelog_full_intro": "Każda istotna zmiana repozytorium jest opisana czytelnym angielskim. Duplikaty merge są scalane, a prace techniczne pozostają dostępne w widoku Wszystkie commity.",
        "changelog_search_placeholder": "Szukaj wersji, systemu lub zmiany…",
        "changelog_filter_label": "Filtr changelogu",
        "changelog_filter_player": "Zmiany dla graczy",
        "changelog_filter_all": "Wszystkie commity",
    },
    "tr": {
        "changelog_loading": "Tam geliştirme geçmişi yükleniyor…",
        "changelog_load_error": "Değişiklik günlüğü yüklenemedi.",
        "changelog_commits": "commit",
        "changelog_technical_count": "teknik",
        "changelog_merges_collapsed": "birleştirme commitleri toplandı",
        "changelog_full_title": "Tam Geliştirme Değişiklik Günlüğü",
        "changelog_full_intro": "Depodaki her önemli değişiklik anlaşılır İngilizce olarak yeniden yazılır. Yinelenen merge kayıtları birleştirilir; teknik çalışmalar Tüm commitler görünümünde kalır.",
        "changelog_search_placeholder": "Sürüm, sistem veya değişiklik ara…",
        "changelog_filter_label": "Değişiklik günlüğü filtresi",
        "changelog_filter_player": "Oyuncu değişiklikleri",
        "changelog_filter_all": "Tüm commitler",
    },
    "ru": {
        "changelog_loading": "Загрузка полной истории разработки…",
        "changelog_load_error": "Не удалось загрузить список изменений.",
        "changelog_commits": "коммитов",
        "changelog_technical_count": "технических",
        "changelog_merges_collapsed": "merge-коммиты объединены",
        "changelog_full_title": "Полный журнал разработки",
        "changelog_full_intro": "Каждое важное изменение репозитория переписывается понятным английским языком. Дубли merge объединяются, а технические работы доступны в режиме Все коммиты.",
        "changelog_search_placeholder": "Поиск версии, системы или изменения…",
        "changelog_filter_label": "Фильтр изменений",
        "changelog_filter_player": "Изменения для игроков",
        "changelog_filter_all": "Все коммиты",
    },
    "pt": {
        "changelog_loading": "A carregar o histórico completo de desenvolvimento…",
        "changelog_load_error": "Não foi possível carregar o changelog.",
        "changelog_commits": "commits",
        "changelog_technical_count": "técnicos",
        "changelog_merges_collapsed": "commits de merge agrupados",
        "changelog_full_title": "Changelog completo de desenvolvimento",
        "changelog_full_intro": "Cada alteração importante do repositório é reescrita em inglês legível. Duplicados de merge são agrupados e o trabalho técnico continua disponível em Todos os commits.",
        "changelog_search_placeholder": "Pesquisar versão, sistema ou alteração…",
        "changelog_filter_label": "Filtro do changelog",
        "changelog_filter_player": "Alterações para jogadores",
        "changelog_filter_all": "Todos os commits",
    },
}


def write(rel: str, content: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"anchor not found in {rel}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_regex(rel: str, pattern: str, repl: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"regex patch count={count} in {rel}: {pattern[:80]!r}")
    path.write_text(updated, encoding="utf-8")


def inject_locale_keys() -> None:
    for locale, values in LOCALE_VALUES.items():
        path = ROOT / "locales" / f"{locale}.json"
        text = path.read_text(encoding="utf-8")
        parsed = json.loads(text)
        missing = {k: v for k, v in values.items() if k not in parsed}
        if not missing:
            continue
        stripped = text.rstrip()
        if not stripped.endswith("}"):
            raise SystemExit(f"invalid locale json: {path}")
        body = stripped[:-1].rstrip()
        if not body.endswith(","):
            body += ","
        lines = []
        for idx, (key, value) in enumerate(missing.items()):
            suffix = "," if idx + 1 < len(missing) else ""
            lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}{suffix}")
        path.write_text(body + "\n" + "\n".join(lines) + "\n}\n", encoding="utf-8")
        json.loads(path.read_text(encoding="utf-8"))


def patch_bottom_bar() -> None:
    path = ROOT / "templates/partials/bottom_utility_bar.html"
    text = path.read_text(encoding="utf-8")
    if 'data-gc-changelog-open' in text:
        return
    pattern = r'''      <a href="\{\{ _release\.href \| default\(url_for\('news_view'\)\) \}\}"\n         class="gc-bottom-util-version gc-mono gc-nav-link"\n         data-pjax-link\n         title="\{\{ T\('sidebar_version_title', 'Genesis Timeline & Patchnotes'\) \}\}">\n        <span class="gc-bottom-util-version-label">\{\{ _release\.label \| default\('Genesis'\) \}\}</span>\n        <span class="gc-bottom-util-version-sep" aria-hidden="true">•</span>\n        <span class="gc-bottom-util-version-stage">\{\{ T\("release_stage_alpha", "Alpha"\) \}\}</span>\n      </a>'''
    replacement = '''      <button type="button"\n              class="gc-bottom-util-version gc-mono gc-nav-link"\n              data-gc-changelog-open\n              title="{{ T('changelog_full_title', 'Full Development Changelog') }}">\n        <span class="gc-bottom-util-version-label">{{ _release.label | default('Genesis') }}</span>\n        <span class="gc-bottom-util-version-sep" aria-hidden="true">•</span>\n        <span class="gc-bottom-util-version-stage">{{ T("release_stage_alpha", "Alpha") }}</span>\n      </button>'''
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise SystemExit("bottom version link anchor not found")
    path.write_text(updated, encoding="utf-8")


def patch_special_panel() -> None:
    path = ROOT / "templates/partials/special_panel.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace('data-community-open="changelog"', 'data-gc-changelog-open')
    text = re.sub(
        r'\n  <aside class="gc-special-window" data-special-window="changelog" hidden>.*?</aside>',
        "",
        text,
        count=1,
        flags=re.S,
    )
    path.write_text(text, encoding="utf-8")


def patch_community_tests() -> None:
    path = ROOT / "tests/test_community_hub.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '    for key in ("rules", "changelog", "events"):\n        assert f\'data-community-open="{key}"\' in html\n        assert f\'data-special-window="{key}"\' in html\n',
        '    for key in ("rules", "events"):\n        assert f\'data-community-open="{key}"\' in html\n        assert f\'data-special-window="{key}"\' in html\n    assert \'data-gc-changelog-open\' in html\n    assert \'data-special-window="changelog"\' not in html\n',
    )
    text = text.replace(
        '    for target in ("support", "my-tickets", "imprint", "rules", "changelog", "events"):\n        assert f\'data-special-window="{target}"\' in panel\n',
        '    for target in ("support", "my-tickets", "imprint", "rules", "events"):\n        assert f\'data-special-window="{target}"\' in panel\n    assert \'data-special-window="changelog"\' not in panel\n',
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    write("game/player_changelog.py", PLAYER_CHANGELOG_PY)
    write("templates/partials/player_changelog_dialog.html", DIALOG_HTML)
    write("static/js/player_changelog.js", CHANGELOG_JS)
    write("static/css/player_changelog.css", CHANGELOG_CSS)
    write("tests/test_player_changelog_surface.py", TEST_FILE)

    replace_once(
        "app.py",
        'bootstrap_application(skip_migration_check=_skip_mig)\n\ntry:\n',
        'bootstrap_application(skip_migration_check=_skip_mig)\n\nfrom game.player_changelog import register_player_changelog_routes\nregister_player_changelog_routes(app)\n\ntry:\n',
    )
    replace_once(
        "templates/base.html",
        '  {% include "partials/special_panel.html" %}\n  {% endif %}\n',
        '  {% include "partials/special_panel.html" %}\n  {% include "partials/player_changelog_dialog.html" %}\n  {% endif %}\n',
    )
    patch_bottom_bar()
    patch_special_panel()
    patch_community_tests()
    inject_locale_keys()

    print("GC-CHANGELOG-001 applied")


if __name__ == "__main__":
    main()
