"""Universe news / Genesis Timeline (GC-642 / GC-650 / GC-651)."""

from __future__ import annotations

import re
import sqlite3
import subprocess
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .db import table_exists, with_transaction
from .models import db, get_game_settings

NEWS_CATEGORIES: Tuple[str, ...] = (
    "FEATURE",
    "BUGFIX",
    "BALANCE",
    "DEVBLOG",
    "EVENT",
    "ALPHA",
    "COMMUNITY",
)

NEWS_BADGES: Tuple[str, ...] = (
    "NEW",
    "HOT",
    "ALPHA",
    "BALANCE",
    "BREAKING",
    "DEV",
    "EVENT",
)

_CHANGELOG_SECTION_CATEGORY = {
    "added": "FEATURE",
    "changed": "FEATURE",
    "fixed": "BUGFIX",
    "removed": "DEVBLOG",
    "technical": "DEVBLOG",
}

_SELECT_COLS = """
    id, title, body, published_at, is_banner, created_by, created_at,
    version_tag, category, badge, image_url, is_major_release, is_draft,
    source_ref, audience, entry_section
"""

AUDIENCE_PLAYER = "player"
AUDIENCE_DEV = "dev"

_DEVELOPMENT_VERSION_TAGS = frozenset({"development", "dev", "ongoing"})
_GC_TICKET_RE = re.compile(r"\bGC-\d+[A-Za-z]?\b")
_DEV_CONTENT_RE = re.compile(
    r"tests/|test_|docs/|\.py\b|\.md\b|\.sql\b|\.js\b|migration|canonical|regression guard|"
    r"pytest|GC-000|fleet_calc|pjax|sqlite|compositor|overflow audit|live-state|poll storm|"
    r"master doc|changed files|root cause|backfill|static live|idempotent api|queue engine|"
    r"effect resolver|bootstrap|hardcod|refactor|regression guard|viewport-aware|"
    r"specs?|EPIC-\d|master docs",
    re.I,
)

_PLAYER_SECTIONS: Tuple[Tuple[str, str, str], ...] = (
    ("added", "news_section_new", "Neu"),
    ("changed", "news_section_improved", "Verbessert"),
    ("fixed", "news_section_fixed", "Behoben"),
)

_CHANGELOG_SECTION_TO_ENTRY = {
    "added": "added",
    "changed": "changed",
    "fixed": "fixed",
    "removed": "changed",
    "technical": "technical",
}


def _normalize_audience(raw: str | None) -> str:
    val = str(raw or "").strip().lower()
    return AUDIENCE_DEV if val == AUDIENCE_DEV else AUDIENCE_PLAYER


def _sanitize_player_text(text: str) -> str:
    s = str(text or "").strip()
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`[^`]+`", "", s)
    s = re.sub(r"\s*[—–-]\s*GC-[\dA-Za-z./,&\s]+$", "", s)
    s = re.sub(r"\s*\((GC-[^)]+)\)", "", s)
    s = re.sub(r"\s*\(GC-[^)]+\)", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" —–-")


def _looks_like_dev_content(text: str) -> bool:
    return bool(_DEV_CONTENT_RE.search(str(text or "")))


def _resolve_audience(
    *,
    title: str = "",
    body: str = "",
    version_tag: str = "",
    category: str = "",
    source_ref: str = "",
    entry_section: str = "",
    is_major_release: bool = False,
) -> str:
    if str(source_ref or "").startswith("git:"):
        return AUDIENCE_DEV
    if str(version_tag or "").strip().lower() in _DEVELOPMENT_VERSION_TAGS:
        return AUDIENCE_DEV
    if str(entry_section or "").strip().lower() == "technical":
        return AUDIENCE_DEV
    if _normalize_category(category) == "DEVBLOG" and not is_major_release:
        return AUDIENCE_DEV
    blob = f"{title} {body}"
    if _looks_like_dev_content(blob):
        return AUDIENCE_DEV
    return AUDIENCE_PLAYER


def _infer_entry_section(entry: Dict[str, Any]) -> str:
    explicit = str(entry.get("entry_section") or "").strip().lower()
    if explicit and explicit != "technical":
        return explicit
    cat = _normalize_category(entry.get("category"))
    if cat == "BUGFIX":
        return "fixed"
    if cat in ("BALANCE",):
        return "changed"
    return "added"


def _major_release_intro(version_label: str, *, locale: str | None = None) -> str:
    from game.i18n import tr

    label = str(version_label or "").lower()
    loc = locale
    if any(x in label for x in ("polish", "hardening", "alpha")):
        return tr("news_intro_polish", "Genesis Colonies was polished and improved.", locale=loc)
    if any(x in label for x in ("genesis 2", "command map", "2.0")):
        return tr("news_intro_genesis2", "The universe of Genesis Colonies was expanded.", locale=loc)
    if any(x in label for x in ("liveops", "community", "ranking", "wettbewerb")):
        return tr("news_intro_liveops", "More community features and competition.", locale=loc)
    if any(x in label for x in ("combat", "defense")):
        return tr("news_intro_combat", "Combat and planetary defense evolved.", locale=loc)
    if any(x in label for x in ("galaxy", "fleet")):
        return tr("news_intro_fleet", "Galaxy travel and fleets took shape.", locale=loc)
    if any(x in label for x in ("planet scope", "colon", "kolonie")):
        return tr("news_intro_colonies", "Colonies and planet scope opened up.", locale=loc)
    if any(x in label for x in ("economy", "foundation", "core")):
        return tr("news_intro_economy", "The economic foundation of Genesis Colonies grew.", locale=loc)
    clean = _sanitize_player_text(version_label.split("*")[0])
    if clean:
        return tr(
            "news_intro_generic_named",
            "A new chapter in Genesis Colonies — %(name)s.",
            locale=loc,
            name=clean,
        )
    return tr("news_intro_generic", "A new chapter in Genesis Colonies.", locale=loc)


def _month_anchor_ts(year: int, month: int, day: int = 1) -> int:
    try:
        return int(datetime(year, month, max(1, min(int(day), 28)), tzinfo=timezone.utc).timestamp())
    except Exception:
        return _now_ts()


def _extract_release_hint_ts(version_label: str) -> int | None:
    label = str(version_label or "")
    match = re.search(r"\*\((\d{4}-\d{2}-\d{2})\)\*", label)
    if match:
        return _date_to_ts(match.group(1))
    match = re.search(r"\*\(\s*(\d{4}-\d{2})\s*[—–-]\s*(\d{4}-\d{2})\s*\)\*", label)
    if match:
        end = match.group(2)
        year, month = end.split("-", 1)
        return _month_anchor_ts(int(year), int(month), 1)
    match = re.search(r"\*\((\d{4}-\d{2})\)\*", label)
    if match:
        year, month = match.group(1).split("-", 1)
        return _month_anchor_ts(int(year), int(month), 1)
    return None


def _changelog_release_dates(
    text: str,
    *,
    repo_root: Path | None = None,
) -> Dict[str, int]:
    """Map version_tag → release timestamp from CHANGELOG hints (monotonic, oldest→newest)."""
    version_header_re = re.compile(r"^##\s+(v\d+\.\d+)\s*(?:[—–-]\s*(.+))?\s*$", re.I | re.M)
    versions: List[Tuple[str, str, Tuple[int, int, str]]] = []
    for match in version_header_re.finditer(text):
        tag = match.group(1).strip()
        if not tag.lower().startswith("v"):
            tag = f"v{tag}"
        label = str(match.group(2) or "").strip()
        versions.append((tag, label, _version_sort_key(tag)))
    versions.sort(key=lambda row: row[2])

    dates: Dict[str, int] = {}
    prev_ts = 0
    for idx, (tag, label, _) in enumerate(versions):
        hinted = _extract_release_hint_ts(label)
        if hinted:
            ts = hinted
        elif prev_ts:
            ts = prev_ts + 3 * 86400
        else:
            ts = _date_to_ts("2026-05-25")

        if prev_ts and ts <= prev_ts:
            ts = prev_ts + 3 * 86400

        if idx == len(versions) - 1 and re.search(r"\(2026-06\)", label):
            ts = _date_to_ts("2026-06-10")

        dates[tag] = ts
        prev_ts = ts

    for tag, tag_ts in _git_tag_dates(repo_root).items():
        norm = tag if tag.startswith("v") else f"v{tag}"
        if norm in dates and tag_ts:
            dates[norm] = tag_ts
    return dates


def _git_tag_dates(repo_root: Path | None = None) -> Dict[str, int]:
    root = repo_root or _repo_root()
    try:
        proc = subprocess.run(
            ["git", "for-each-ref", "refs/tags", "--format=%(refname:short)|%(creatordate:short)"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    out: Dict[str, int] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        tag, date_str = parts[0].strip(), parts[1].strip()
        if tag and date_str:
            out[tag] = _date_to_ts(date_str)
    return out


def sync_release_dates(
    *,
    path: Path | None = None,
    repo_root: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    """Apply CHANGELOG/git release dates to all rows per version_tag."""
    changelog_path = path or (_repo_root() / "CHANGELOG.md")
    text = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""
    date_map = _changelog_release_dates(text, repo_root=repo_root or _repo_root())
    own = conn is None
    if own:
        conn = db()
    updated = 0
    try:
        cur = conn.cursor()
        for version_tag, ts in date_map.items():
            cur.execute(
                """
                UPDATE universe_news
                SET published_at = ?, created_at = CASE WHEN created_at > 0 THEN ? ELSE created_at END
                WHERE version_tag = ? AND is_draft = 0;
                """,
                (int(ts), int(ts), version_tag),
            )
            updated += int(cur.rowcount or 0)
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return {"ok": True, "updated": updated, "release_dates": date_map}


def _git_simple(repo_root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return proc.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def repository_history_audit(*, repo_root: Path | None = None) -> Dict[str, Any]:
    """Summarize git repository history for admin diagnostics (GC-653)."""
    root = repo_root or _repo_root()
    changelog_path = _changelog_path()
    git_ok = _git_available(root)
    commits = _collect_git_log(root, all_refs=True)
    count_raw = _git_simple(root, "rev-list", "--count", "HEAD")
    try:
        commit_count = int(count_raw or "0")
    except ValueError:
        commit_count = len(commits)

    branches = [b for b in _git_simple(root, "branch", "-a").splitlines() if b.strip()]
    tags = [t for t in _git_simple(root, "tag", "-l").splitlines() if t.strip()]
    remotes = [r for r in _git_simple(root, "remote", "-v").splitlines() if r.strip()]

    first = commits[0] if commits else None
    latest = commits[-1] if commits else None
    changelog_text = changelog_path.read_text(encoding="utf-8") if changelog_path.is_file() else ""
    release_dates = _changelog_release_dates(changelog_text, repo_root=root)
    current_release = _latest_changelog_version(changelog_path) if changelog_path.is_file() else ""
    release_ts = int(release_dates.get(current_release) or 0)
    dev_commits = 0
    if release_ts:
        for commit in commits:
            if _date_to_ts(commit.get("date") or "") > release_ts:
                dev_commits += 1

    return {
        "ok": True,
        "repo_root": str(root),
        "git_available": git_ok,
        "changelog_path": str(changelog_path),
        "changelog_exists": changelog_path.is_file(),
        "commit_count": commit_count,
        "branch_count": len(branches),
        "tag_count": len(tags),
        "branches": branches[:20],
        "tags": tags[:20],
        "remotes": remotes[:10],
        "first_commit_date": first.get("date") if first else "",
        "latest_commit_date": latest.get("date") if latest else "",
        "current_release": current_release,
        "current_release_date": _format_published(release_ts) if release_ts else "",
        "development_commits_since_release": dev_commits,
        "release_dates": {k: _format_published(v) for k, v in release_dates.items()},
    }


def _parse_changelog_month_ts(header_tail: str, fallback_ts: int) -> int:
    hinted = _extract_release_hint_ts(header_tail)
    return hinted if hinted else fallback_ts


def _decorate_player_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(entry)
    out["display_title"] = _sanitize_player_text(entry.get("title") or "")
    out["display_body"] = _sanitize_player_text(entry.get("body") or "")
    if not out["display_title"] and out["display_body"]:
        out["display_title"] = out["display_body"][:200]
    return out


def _is_live_event_entry(entry: Dict[str, Any]) -> bool:
    """World Boss / pirate live ops — banner-eligible, not patchnotes."""
    if _normalize_category(entry.get("category")) == "EVENT":
        return True
    ref = str(entry.get("source_ref") or "").strip().lower()
    if ref.startswith("world_boss:") or ref.startswith("pirate"):
        return True
    return False


def _is_player_visible_entry(entry: Dict[str, Any]) -> bool:
    if entry.get("is_draft"):
        return False
    if _normalize_audience(entry.get("audience")) != AUDIENCE_PLAYER:
        return False
    if _is_live_event_entry(entry):
        return False
    if str(entry.get("version_tag") or "").strip().lower() in _DEVELOPMENT_VERSION_TAGS:
        return False
    blob = f"{entry.get('title') or ''} {entry.get('body') or ''}"
    if _looks_like_dev_content(blob):
        return False
    title = _sanitize_player_text(entry.get("title") or "")
    return bool(title)


def _now_ts() -> int:
    return int(time.time())


def _format_published(ts: int) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d.%m.%Y")
    except Exception:
        return ""


def _normalize_category(raw: str | None) -> str:
    val = str(raw or "").strip().upper()
    return val if val in NEWS_CATEGORIES else ""


def _normalize_badge(raw: str | None) -> str:
    val = str(raw or "").strip().upper()
    return val if val in NEWS_BADGES else ""


def _version_sort_key(version_tag: str) -> Tuple[int, int, str]:
    tag = str(version_tag or "").strip().lower()
    if tag in _DEVELOPMENT_VERSION_TAGS:
        return (999, 999, tag)
    match = re.match(r"^v?(\d+)\.(\d+)", tag)
    if match:
        return (int(match.group(1)), int(match.group(2)), tag)
    return (-1, -1, tag)


def _parse_version_header(line: str) -> Tuple[str, str]:
    text = str(line or "").strip()
    match = re.match(r"^v(\d+\.\d+)\s*(?:[—–-]\s*(.+))?$", text, re.I)
    if not match:
        return ("", text)
    return (f"v{match.group(1)}", str(match.group(2) or "").strip())


def _row_get(row: sqlite3.Row | Dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        if key in row.keys():
            return row[key]
    except Exception:
        pass
    return default


def _row_to_entry(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    published_at = int(row["published_at"] or 0)
    version_tag = str(_row_get(row, "version_tag") or "").strip()
    category = _normalize_category(_row_get(row, "category"))
    badge = _normalize_badge(_row_get(row, "badge"))
    return {
        "id": int(row["id"]),
        "title": str(row["title"] or "").strip(),
        "body": str(row["body"] or "").strip(),
        "published_at": published_at,
        "published_label": _format_published(published_at),
        "published_year": datetime.fromtimestamp(published_at, tz=timezone.utc).year if published_at else None,
        "is_banner": bool(int(row["is_banner"] or 0)),
        "is_draft": bool(int(_row_get(row, "is_draft") or 0)),
        "is_major_release": bool(int(_row_get(row, "is_major_release") or 0)),
        "version_tag": version_tag,
        "category": category,
        "badge": badge,
        "image_url": str(_row_get(row, "image_url") or "").strip(),
        "created_by": int(row["created_by"]) if row["created_by"] is not None else None,
        "created_at": int(row["created_at"] or 0),
        "source_ref": str(_row_get(row, "source_ref") or "").strip(),
        "audience": _normalize_audience(_row_get(row, "audience")),
        "entry_section": str(_row_get(row, "entry_section") or "").strip().lower(),
    }


def ensure_legacy_motd_migrated(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        if not table_exists(conn, "universe_news"):
            return
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM universe_news;")
        if int(cur.fetchone()["c"]) > 0:
            return
        settings = get_game_settings(conn=conn) or {}
        body = str(settings.get("motd_text") or "").strip()
        if not body:
            return
        title = "Update"
        if body.startswith("Update"):
            first_line = body.split("\n", 1)[0].strip()
            if first_line:
                title = first_line[:120]
        ts = _now_ts()
        cur.execute(
            f"""
            INSERT INTO universe_news (
                title, body, published_at, is_banner, created_at,
                version_tag, category, badge, image_url, is_major_release, is_draft
            )
            VALUES (?, ?, ?, 1, ?, '', 'ALPHA', 'ALPHA', '', 0, 0);
            """,
            (title, body, ts, ts),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def list_news(
    *,
    limit: int = 200,
    include_drafts: bool = False,
    audience: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_legacy_motd_migrated(conn)
        cur = conn.cursor()
        clauses: List[str] = []
        params: List[Any] = []
        if not include_drafts:
            clauses.append("is_draft = 0")
        if audience in (AUDIENCE_PLAYER, AUDIENCE_DEV):
            clauses.append("audience = ?")
            params.append(audience)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        cur.execute(
            f"""
            SELECT {_SELECT_COLS}
            FROM universe_news
            {where}
            ORDER BY published_at DESC, id DESC
            LIMIT ?;
            """,
            tuple(params),
        )
        return [_maybe_localize_entry(_row_to_entry(row), conn=conn) for row in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_news_entry(news_id: int, *, conn: sqlite3.Connection | None = None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT {_SELECT_COLS}
            FROM universe_news
            WHERE id = ? LIMIT 1;
            """,
            (int(news_id),),
        )
        row = cur.fetchone()
        return _maybe_localize_entry(_row_to_entry(row), conn=conn) if row else None
    finally:
        if own:
            conn.close()


def _maybe_localize_entry(
    entry: Optional[Dict[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
) -> Optional[Dict[str, Any]]:
    if not entry:
        return entry
    ref = str(entry.get("source_ref") or "")
    if not ref.startswith("world_boss:"):
        return entry
    try:
        from game.world_boss import localize_world_boss_news_entry

        return localize_world_boss_news_entry(entry, conn=conn)
    except Exception:
        return entry


def get_banner_entry(*, conn: sqlite3.Connection | None = None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_legacy_motd_migrated(conn)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT {_SELECT_COLS}
            FROM universe_news
            WHERE is_banner = 1 AND is_draft = 0 AND audience = '{AUDIENCE_PLAYER}'
            ORDER BY published_at DESC, id DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        if row:
            return _maybe_localize_entry(_row_to_entry(row), conn=conn)
        cur.execute(
            f"""
            SELECT {_SELECT_COLS}
            FROM universe_news
            WHERE is_draft = 0
            ORDER BY published_at DESC, id DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        return _maybe_localize_entry(_row_to_entry(row), conn=conn) if row else None
    finally:
        if own:
            conn.close()


def _clear_banner(cur: sqlite3.Cursor) -> None:
    cur.execute("UPDATE universe_news SET is_banner = 0 WHERE is_banner = 1;")


def create_news(
    *,
    title: str,
    body: str,
    set_banner: bool = False,
    is_draft: bool = False,
    version_tag: str = "",
    category: str = "",
    badge: str = "",
    image_url: str = "",
    is_major_release: bool = False,
    created_by: int | None = None,
    source_ref: str = "",
    published_at: int | None = None,
    entry_section: str = "",
    audience: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    clean_title = str(title or "").strip() or "Update"
    clean_body = str(body or "").strip()
    if not clean_body and not is_draft:
        raise ValueError("body_required")

    section = str(entry_section or "").strip().lower()
    if section and section not in ("added", "changed", "fixed", "technical", ""):
        section = ""

    own = conn is None
    if own:
        conn = db()
    try:
        ts = int(published_at) if published_at else (_now_ts() if not is_draft else 0)
        cur = conn.cursor()
        if set_banner and not is_draft:
            _clear_banner(cur)
        resolved_audience = (
            _normalize_audience(audience)
            if audience is not None
            else _resolve_audience(
                title=clean_title,
                body=clean_body,
                version_tag=version_tag,
                category=category,
                source_ref=source_ref,
                entry_section=section,
                is_major_release=is_major_release,
            )
        )
        cur.execute(
            f"""
            INSERT INTO universe_news (
                title, body, published_at, is_banner, created_by, created_at,
                version_tag, category, badge, image_url, is_major_release, is_draft,
                source_ref, audience, entry_section
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                clean_title[:200],
                clean_body,
                ts,
                1 if set_banner and not is_draft else 0,
                int(created_by) if created_by is not None else None,
                ts or _now_ts(),
                str(version_tag or "").strip()[:32],
                _normalize_category(category),
                _normalize_badge(badge),
                str(image_url or "").strip()[:500],
                1 if is_major_release else 0,
                1 if is_draft else 0,
                str(source_ref or "").strip()[:120],
                resolved_audience,
                section,
            ),
        )
        news_id = int(cur.lastrowid)
        if own:
            conn.commit()
        entry = get_news_entry(news_id, conn=conn)
        assert entry is not None
        return entry
    finally:
        if own:
            conn.close()


def update_news(
    news_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    set_banner: bool | None = None,
    is_draft: bool | None = None,
    version_tag: str | None = None,
    category: str | None = None,
    badge: str | None = None,
    image_url: str | None = None,
    is_major_release: bool | None = None,
    publish: bool = False,
    conn: sqlite3.Connection | None = None,
) -> Optional[Dict[str, Any]]:
    existing = get_news_entry(news_id, conn=conn)
    if not existing:
        return None

    own = conn is None
    if own:
        conn = db()
    try:
        fields: Dict[str, Any] = {}
        if title is not None:
            fields["title"] = str(title).strip()[:200] or "Update"
        if body is not None:
            fields["body"] = str(body).strip()
        if version_tag is not None:
            fields["version_tag"] = str(version_tag).strip()[:32]
        if category is not None:
            fields["category"] = _normalize_category(category)
        if badge is not None:
            fields["badge"] = _normalize_badge(badge)
        if image_url is not None:
            fields["image_url"] = str(image_url).strip()[:500]
        if is_major_release is not None:
            fields["is_major_release"] = 1 if is_major_release else 0
        if is_draft is not None:
            fields["is_draft"] = 1 if is_draft else 0
        if publish:
            fields["is_draft"] = 0
            fields["published_at"] = _now_ts()
        if set_banner is True and (publish or not existing.get("is_draft")):
            cur = conn.cursor()
            _clear_banner(cur)
            fields["is_banner"] = 1
        elif set_banner is False:
            fields["is_banner"] = 0

        if not fields:
            return existing

        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [int(news_id)]
        cur = conn.cursor()
        cur.execute(f"UPDATE universe_news SET {assignments} WHERE id = ?;", values)
        if own:
            conn.commit()
        return get_news_entry(news_id, conn=conn)
    finally:
        if own:
            conn.close()


def set_banner(news_id: int, *, conn: sqlite3.Connection | None = None) -> Optional[Dict[str, Any]]:
    return update_news(news_id, set_banner=True, publish=False, conn=conn)


def delete_news(news_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM universe_news WHERE id = ?;", (int(news_id),))
        deleted = cur.rowcount > 0
        if own:
            conn.commit()
        return deleted
    finally:
        if own:
            conn.close()


def _version_label_from_entries(version_tag: str, entries: List[Dict[str, Any]]) -> str:
    if str(version_tag or "").strip().lower() in _DEVELOPMENT_VERSION_TAGS:
        return "Ongoing Development"
    for entry in entries:
        if entry.get("is_major_release") and entry.get("title"):
            title = str(entry["title"])
            if version_tag and title.lower().startswith(version_tag.lower()):
                parts = re.split(r"[—–-]", title, maxsplit=1)
                if len(parts) == 2:
                    return parts[1].strip()
            return title
    return ""


def build_timeline(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group published entries by year → version_tag."""
    published = [e for e in entries if not e.get("is_draft")]
    by_year: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}

    for entry in published:
        year = int(entry.get("published_year") or 0)
        if year <= 1970:
            year = datetime.now(tz=timezone.utc).year
        version = str(entry.get("version_tag") or "").strip() or "_general"
        by_year.setdefault(year, {}).setdefault(version, []).append(entry)

    timeline: List[Dict[str, Any]] = []
    for year in sorted(by_year.keys(), reverse=True):
        versions_raw = by_year[year]
        version_keys = sorted(
            versions_raw.keys(),
            key=lambda key: _version_sort_key("" if key == "_general" else key),
            reverse=True,
        )
        version_blocks: List[Dict[str, Any]] = []
        for key in version_keys:
            rows = sorted(
                versions_raw[key],
                key=lambda row: (0 if row.get("is_major_release") else 1, -int(row.get("published_at") or 0)),
            )
            version_tag = "" if key == "_general" else key
            version_blocks.append(
                {
                    "version_tag": version_tag,
                    "version_label": _version_label_from_entries(version_tag, rows),
                    "is_major_release": any(bool(r.get("is_major_release")) for r in rows),
                    "badge": next((r.get("badge") for r in rows if r.get("badge")), ""),
                    "category": next((r.get("category") for r in rows if r.get("category")), ""),
                    "anchor_id": f"version-{version_tag.replace('.', '-')}" if version_tag else "version-general",
                    "entries": rows,
                }
            )
        timeline.append({"year": year, "versions": version_blocks})
    return timeline


def _player_sections_for_version(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    visible = [_decorate_player_entry(e) for e in entries if _is_player_visible_entry(e)]
    non_major = [e for e in visible if not e.get("is_major_release")]
    sections: List[Dict[str, Any]] = []
    for section_key, label_key, default_label in _PLAYER_SECTIONS:
        rows = [
            e
            for e in non_major
            if (e.get("entry_section") or _infer_entry_section(e)) == section_key
        ]
        if rows:
            sections.append(
                {
                    "key": section_key,
                    "label_key": label_key,
                    "label": default_label,
                    "entries": rows,
                }
            )
    return sections


def _version_block_recency(version: Dict[str, Any]) -> Tuple[int, int, int, str]:
    """Newest-first key: major published_at, then version number, then tag."""
    rows = version.get("entries") or []
    major_ts = 0
    any_ts = 0
    for row in rows:
        ts = int(row.get("published_at") or 0)
        if ts > any_ts:
            any_ts = ts
        if row.get("is_major_release") and ts > major_ts:
            major_ts = ts
    tag = str(version.get("version_tag") or "").strip()
    major, minor, _ = _version_sort_key(tag)
    return (major_ts or any_ts, major, minor, tag)


def build_player_timeline(
    entries: List[Dict[str, Any]],
    *,
    locale: str | None = None,
) -> List[Dict[str, Any]]:
    """Player patchnotes only — newest major/version first. No git/dev stream."""
    player_entries = [e for e in entries if _is_player_visible_entry(e)]
    timeline = build_timeline(player_entries)
    cleaned: List[Dict[str, Any]] = []

    for year_block in timeline:
        versions: List[Dict[str, Any]] = []
        for version in year_block.get("versions") or []:
            tag = str(version.get("version_tag") or "").strip().lower()
            if tag in _DEVELOPMENT_VERSION_TAGS:
                continue
            rows = version.get("entries") or []
            major = next((r for r in rows if r.get("is_major_release")), None)
            version_label = str(version.get("version_label") or "").strip()
            clean_label = _sanitize_player_text(version_label.split("*")[0])
            intro = ""
            release_date = ""
            if major:
                release_date = str(major.get("published_label") or "")
                intro = _sanitize_player_text(major.get("body") or "")
                if not intro or intro == _sanitize_player_text(major.get("title") or ""):
                    intro = _major_release_intro(clean_label or version_label, locale=locale)
            sections = _player_sections_for_version(rows)
            if not sections and not major:
                continue
            version = dict(version)
            version["version_label"] = clean_label or version_label
            version["release_date"] = release_date
            version["intro"] = intro
            version["sections"] = sections
            versions.append(version)
        versions.sort(key=_version_block_recency, reverse=True)
        if versions:
            cleaned.append({"year": year_block["year"], "versions": versions})
    return cleaned


def build_dev_timeline(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    dev_entries = [
        e
        for e in entries
        if not e.get("is_draft")
        and (
            _normalize_audience(e.get("audience")) == AUDIENCE_DEV
            or str(e.get("version_tag") or "").lower() in _DEVELOPMENT_VERSION_TAGS
            or _looks_like_dev_content(f"{e.get('title')} {e.get('body')}")
        )
    ]
    return build_timeline(dev_entries)


def reclassify_news_audience(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    """Recompute audience/entry_section for existing rows (idempotent)."""
    own = conn is None
    if own:
        conn = db()
    updated = 0
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, title, body, version_tag, category, source_ref, entry_section, is_major_release
            FROM universe_news;
            """
        )
        for row in cur.fetchall():
            entry_section = str(row["entry_section"] or "").strip().lower()
            if not entry_section or entry_section == "technical":
                inferred = _infer_entry_section(
                    {
                        "entry_section": entry_section,
                        "category": row["category"],
                    }
                )
            else:
                inferred = entry_section
            audience = _resolve_audience(
                title=str(row["title"] or ""),
                body=str(row["body"] or ""),
                version_tag=str(row["version_tag"] or ""),
                category=str(row["category"] or ""),
                source_ref=str(row["source_ref"] or ""),
                entry_section=inferred,
                is_major_release=bool(int(row["is_major_release"] or 0)),
            )
            if inferred == "technical":
                audience = AUDIENCE_DEV
            cur.execute(
                "UPDATE universe_news SET audience = ?, entry_section = ? WHERE id = ?;",
                (audience, inferred if inferred != "technical" else "technical", int(row["id"])),
            )
            updated += 1
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return {"ok": True, "updated": updated}


def news_page_payload(*, locale: str | None = None, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    from game.i18n import current_locale, normalize_locale

    loc = normalize_locale(locale or current_locale())
    all_entries = list_news(limit=800, conn=conn)
    player_entries = [
        e
        for e in all_entries
        if _normalize_audience(e.get("audience")) == AUDIENCE_PLAYER and _is_player_visible_entry(e)
    ]
    timeline = build_player_timeline(player_entries, locale=loc)
    release = sidebar_release_nav(conn=conn)
    return {
        "ok": True,
        "entries": player_entries,
        "timeline": timeline,
        "audience": AUDIENCE_PLAYER,
        "locale": loc,
        "current_release": {
            "label": release.get("label") or "",
            "version_tag": release.get("version_tag") or "",
            "anchor_id": release.get("anchor_id") or "",
            "href": release.get("href") or "/news",
        },
    }


def devlog_page_payload(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    entries = list_news(limit=800, conn=conn)
    timeline = build_dev_timeline(entries)
    return {"ok": True, "entries": entries, "timeline": timeline, "audience": AUDIENCE_DEV}


def whats_new_payload(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    payload = news_page_payload(conn=conn)
    timeline = payload.get("timeline") or []
    if not timeline:
        return {"ok": True, "show": False}

    latest = None
    for year_block in timeline:
        for version in year_block.get("versions") or []:
            if version.get("is_development_stream"):
                continue
            tag = str(version.get("version_tag") or "").strip().lower()
            if tag in _DEVELOPMENT_VERSION_TAGS:
                continue
            if not version.get("is_major_release"):
                continue
            latest = version
            break
        if latest:
            break
    if not latest:
        return {"ok": True, "show": False}

    highlights = []
    for section in latest.get("sections") or []:
        highlights.extend(section.get("entries") or [])
        if len(highlights) >= 6:
            break
    highlights = highlights[:6]
    if not highlights:
        highlights = [
            row
            for row in (latest.get("entries") or [])
            if not row.get("is_major_release")
        ][:6]
    if not highlights:
        return {"ok": True, "show": False}

    version_tag = str(latest.get("version_tag") or "").strip()
    return {
        "ok": True,
        "show": True,
        "version_tag": version_tag,
        "version_label": str(latest.get("version_label") or "").strip(),
        "badge": str(latest.get("badge") or "").strip(),
        "is_major_release": bool(latest.get("is_major_release")),
        "anchor_id": latest.get("anchor_id") or "",
        "highlights": [
            {
                "id": row["id"],
                "title": row.get("display_title") or _sanitize_player_text(row.get("title") or ""),
                "body": row.get("display_body") or _sanitize_player_text(row.get("body") or ""),
                "category": row.get("category") or "",
            }
            for row in highlights
        ],
        "news_url": "/news",
    }


def import_changelog_markdown(
    *,
    path: Path | None = None,
    created_by: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    """Parse CHANGELOG.md version sections into universe_news rows (idempotent per version)."""
    changelog_path = _changelog_path(path)
    if not changelog_path.is_file():
        return {
            "ok": False,
            "error": "changelog_not_found",
            "path": str(changelog_path),
            "inserted": 0,
            "skipped_versions": [],
        }
    text = changelog_path.read_text(encoding="utf-8")
    own = conn is None
    if own:
        conn = db()
    try:
        inserted = 0
        skipped_versions: List[str] = []

        version_header_re = re.compile(r"^##\s+(v\d+\.\d+)\s*(?:[—–-]\s*(.+))?\s*$", re.I | re.M)
        matches = list(version_header_re.finditer(text))
        if not matches:
            return {"ok": True, "inserted": 0, "skipped_versions": []}

        cur = conn.cursor()
        release_dates = _changelog_release_dates(text, repo_root=_repo_root())
        for idx, match in enumerate(matches):
            version_tag = match.group(1).strip()
            if not version_tag.lower().startswith("v"):
                version_tag = f"v{version_tag}"
            version_label = str(match.group(2) or "").strip()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            block = text[start:end]

            cur.execute(
                "SELECT COUNT(*) AS c FROM universe_news WHERE version_tag = ? AND is_draft = 0;",
                (version_tag,),
            )
            if int(cur.fetchone()["c"]) > 0:
                skipped_versions.append(version_tag)
                continue

            ts = int(release_dates.get(version_tag) or _extract_release_hint_ts(version_label) or _now_ts())
            clean_label = _sanitize_player_text(version_label.split("*")[0])
            major_title = f"{version_tag} — {clean_label}".strip(" —")
            intro = _major_release_intro(clean_label or version_label)
            badge = "ALPHA" if "alpha" in version_label.lower() else "NEW"
            cur.execute(
                f"""
                INSERT INTO universe_news (
                    title, body, published_at, is_banner, created_by, created_at,
                    version_tag, category, badge, image_url, is_major_release, is_draft,
                    source_ref, audience, entry_section
                )
                VALUES (?, ?, ?, 0, ?, ?, ?, 'FEATURE', ?, '', 1, 0, ?, ?, '');
                """,
                (
                    major_title[:200],
                    intro,
                    ts,
                    int(created_by) if created_by is not None else None,
                    ts,
                    version_tag,
                    badge,
                    f"changelog:{version_tag}",
                    AUDIENCE_PLAYER,
                ),
            )
            inserted += 1

            section_re = re.compile(r"^###\s+(Added|Changed|Fixed|Removed|Technical)\s*$", re.I | re.M)
            section_matches = list(section_re.finditer(block))
            for sidx, sec in enumerate(section_matches):
                cat_key = sec.group(1).lower()
                entry_section = _CHANGELOG_SECTION_TO_ENTRY.get(cat_key, "added")
                if entry_section == "technical":
                    continue
                category = _CHANGELOG_SECTION_CATEGORY.get(cat_key, "FEATURE")
                sec_start = sec.end()
                sec_end = section_matches[sidx + 1].start() if sidx + 1 < len(section_matches) else len(block)
                sec_body = block[sec_start:sec_end]
                for line in sec_body.splitlines():
                    bullet = line.strip()
                    if not bullet.startswith("- "):
                        continue
                    item = bullet[2:].strip()
                    if not item:
                        continue
                    item = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
                    title = _sanitize_player_text(item)[:200]
                    if not title:
                        continue
                    audience = _resolve_audience(
                        title=title,
                        body=item,
                        version_tag=version_tag,
                        category=category,
                        entry_section=entry_section,
                    )
                    if audience != AUDIENCE_PLAYER:
                        continue
                    cur.execute(
                        f"""
                        INSERT INTO universe_news (
                            title, body, published_at, is_banner, created_by, created_at,
                            version_tag, category, badge, image_url, is_major_release, is_draft,
                            source_ref, audience, entry_section
                        )
                        VALUES (?, ?, ?, 0, ?, ?, ?, ?, '', '', 0, 0, ?, ?, ?);
                        """,
                        (
                            title,
                            title,
                            ts,
                            int(created_by) if created_by is not None else None,
                            ts,
                            version_tag,
                            category,
                            f"changelog:{version_tag}:{title[:80]}",
                            AUDIENCE_PLAYER,
                            entry_section,
                        ),
                    )
                    inserted += 1

        if own:
            conn.commit()
        return {
            "ok": True,
            "inserted": inserted,
            "skipped_versions": skipped_versions,
            "changelog_path": str(changelog_path),
        }
    finally:
        if own:
            conn.close()


def _repo_root() -> Path:
    """Repository root for CHANGELOG + git history imports (Docker/VPS/git clone safe)."""
    env = os.environ.get("GC_REPO_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()

    code_root = Path(__file__).resolve().parent.parent
    git_top = _git_simple(code_root, "rev-parse", "--show-toplevel")
    if git_top:
        return Path(git_top).resolve()

    cur = code_root
    for _ in range(8):
        if (cur / ".git").exists():
            return cur.resolve()
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return code_root.resolve()


def _git_available(repo_root: Path | None = None) -> bool:
    root = repo_root or _repo_root()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def _changelog_path(path: Path | None = None) -> Path:
    return path or (_repo_root() / "CHANGELOG.md")


def _parse_changelog_version_tags(text: str) -> List[str]:
    version_header_re = re.compile(r"^##\s+(v\d+\.\d+)\s", re.I | re.M)
    tags: List[str] = []
    for match in version_header_re.finditer(text):
        tag = match.group(1).strip()
        if not tag.lower().startswith("v"):
            tag = f"v{tag}"
        tags.append(tag)
    return tags


def _latest_changelog_version(path: Path | None = None) -> str:
    changelog_path = path or (_repo_root() / "CHANGELOG.md")
    if not changelog_path.exists():
        return ""
    tags = _parse_changelog_version_tags(changelog_path.read_text(encoding="utf-8"))
    if not tags:
        return ""
    return max(tags, key=_version_sort_key)


def _release_cutoff_ts(
    version_tag: str,
    *,
    conn: sqlite3.Connection,
) -> int:
    if version_tag:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT MAX(published_at) AS ts
            FROM universe_news
            WHERE version_tag = ? AND is_major_release = 1 AND is_draft = 0;
            """,
            (version_tag,),
        )
        row = cur.fetchone()
        if row and row["ts"]:
            return int(row["ts"])
    return 0


def _date_to_ts(date_str: str) -> int:
    try:
        dt = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return _now_ts()


def _infer_category_from_commit(subject: str) -> str:
    text = str(subject or "").lower()
    if any(word in text for word in ("fix", "bug", "regression", "hotfix")):
        return "BUGFIX"
    if any(word in text for word in ("balance", "nerf", "buff")):
        return "BALANCE"
    if _GC_TICKET_RE.search(subject or ""):
        return "FEATURE"
    return "DEVBLOG"


def _collect_git_log(repo_root: Path | None = None, *, all_refs: bool = False) -> List[Dict[str, str]]:
    root = repo_root or _repo_root()
    if not _git_available(root):
        return []
    cmd = ["git", "log", "--reverse", "--date=short", "--pretty=format:%H|%ad|%s"]
    if all_refs:
        cmd.insert(2, "--all")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []

    commits: List[Dict[str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        commit_hash, date_str, subject = parts
        subject = subject.strip()
        if not subject or subject.lower().startswith("merge "):
            continue
        commits.append({"hash": commit_hash.strip(), "date": date_str.strip(), "subject": subject})
    return commits


def _existing_source_refs(conn: sqlite3.Connection) -> set[str]:
    cur = conn.cursor()
    cur.execute("SELECT source_ref FROM universe_news WHERE source_ref != '';")
    return {str(row["source_ref"]) for row in cur.fetchall()}


def import_git_history(
    *,
    repo_root: Path | None = None,
    commits: List[Dict[str, str]] | None = None,
    after_version: str | None = None,
    created_by: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    """Import post-release git commits as development stream entries (idempotent via source_ref)."""
    root = repo_root or _repo_root()
    last_release = str(after_version or _latest_changelog_version(_changelog_path())).strip()
    version_tag = "development"
    git_ok = _git_available(root)
    all_commits = commits if commits is not None else _collect_git_log(root)
    if commits is None and not git_ok:
        return {
            "ok": False,
            "error": "git_unavailable",
            "inserted": 0,
            "skipped": 0,
            "after_version": last_release,
            "version_tag": version_tag,
            "repo_root": str(root),
            "git_available": False,
        }

    own = conn is None
    if own:
        conn = db()
    try:
        cutoff_ts = _release_cutoff_ts(last_release, conn=conn) if last_release else 0
        inserted = 0
        skipped = 0
        cur = conn.cursor()
        known_refs = _existing_source_refs(conn)

        for commit in all_commits:
            source_ref = f"git:{commit['hash']}"
            if source_ref in known_refs:
                skipped += 1
                continue

            subject = str(commit.get("subject") or "").strip()
            if not subject:
                skipped += 1
                continue

            ts = _date_to_ts(commit.get("date") or "")
            if cutoff_ts and ts <= cutoff_ts:
                skipped += 1
                continue
            category = _infer_category_from_commit(subject)
            cur.execute(
                f"""
                INSERT INTO universe_news (
                    title, body, published_at, is_banner, created_by, created_at,
                    version_tag, category, badge, image_url, is_major_release, is_draft,
                    source_ref, audience, entry_section
                )
                VALUES (?, ?, ?, 0, ?, ?, ?, ?, 'DEV', '', 0, 0, ?, ?, 'technical');
                """,
                (
                    subject[:200],
                    subject,
                    ts,
                    int(created_by) if created_by is not None else None,
                    ts,
                    version_tag,
                    category,
                    source_ref,
                    AUDIENCE_DEV,
                ),
            )
            known_refs.add(source_ref)
            inserted += 1

        if own:
            conn.commit()
        return {
            "ok": True,
            "inserted": inserted,
            "skipped": skipped,
            "after_version": last_release,
            "version_tag": version_tag,
            "repo_root": str(root),
            "git_available": git_ok,
            "commits_seen": len(all_commits),
        }
    finally:
        if own:
            conn.close()


def import_full_history(
    *,
    path: Path | None = None,
    repo_root: Path | None = None,
    created_by: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    """Import CHANGELOG.md releases plus post-release git commits."""
    own = conn is None
    with with_transaction(conn=conn, close=own) as tx:
        changelog = import_changelog_markdown(path=path, created_by=created_by, conn=tx)
        if not changelog.get("ok"):
            return changelog
        git = import_git_history(repo_root=repo_root, created_by=created_by, conn=tx)
        reclassified = reclassify_news_audience(conn=tx)
        synced = sync_release_dates(path=path, repo_root=repo_root, conn=tx)
        git_inserted = int(git.get("inserted") or 0) if git.get("ok") else 0
        return {
            "ok": True,
            "changelog": changelog,
            "git": git,
            "reclassified": reclassified,
            "release_dates": synced,
            "inserted": int(changelog.get("inserted") or 0) + git_inserted,
            "git_available": bool(git.get("git_available")),
            "git_error": git.get("error") if not git.get("ok") else "",
        }


def news_metadata() -> Dict[str, Any]:
    return {
        "categories": list(NEWS_CATEGORIES),
        "badges": list(NEWS_BADGES),
    }


def _format_sidebar_version_label(version_tag: str) -> str:
    tag = str(version_tag or "").strip()
    if not tag:
        return ""
    lowered = tag.lower()
    if lowered in _DEVELOPMENT_VERSION_TAGS:
        return "Dev"
    if lowered.startswith("v"):
        return tag
    return f"v{tag}"


def _player_release_fallback_label() -> str:
    """Player-facing fallback when DB has no timeline — never use build VERSION (0.x.y.z internal)."""
    latest = str(_latest_changelog_version() or "").strip()
    if latest:
        return _format_sidebar_version_label(latest)
    return "Genesis"


def _normalize_version_tag(raw: str) -> str:
    tag = str(raw or "").strip()
    if not tag:
        return ""
    if not tag.lower().startswith("v") and re.match(r"^\d", tag):
        tag = f"v{tag}"
    return tag[:32]


def _parse_release_date_ts(raw: str | None) -> int:
    text = str(raw or "").strip()
    if not text:
        return _now_ts()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return _now_ts()


def _normalize_bullet_list(items: Any) -> List[str]:
    if items is None:
        return []
    if isinstance(items, str):
        lines = items.replace("\r\n", "\n").split("\n")
    elif isinstance(items, (list, tuple)):
        lines = [str(x) for x in items]
    else:
        return []
    out: List[str] = []
    for line in lines:
        bullet = str(line or "").strip()
        if not bullet:
            continue
        if bullet.startswith(("- ", "* ", "• ")):
            bullet = bullet[2:].strip()
        bullet = _sanitize_player_text(bullet)
        if bullet:
            out.append(bullet[:200])
    return out


def version_has_player_rows(version_tag: str, *, conn) -> bool:
    tag = _normalize_version_tag(version_tag)
    if not tag:
        return False
    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM universe_news
        WHERE version_tag = ? AND is_draft = 0 AND audience = ?;
        """,
        (tag, AUDIENCE_PLAYER),
    ).fetchone()
    return int(row["c"] or 0) > 0


def publish_release_pack(
    *,
    version_tag: str,
    version_label: str = "",
    intro: str = "",
    release_date: str = "",
    badge: str = "ALPHA",
    is_major_release: bool = True,
    added: Any = None,
    changed: Any = None,
    fixed: Any = None,
    set_banner: bool = False,
    created_by: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    """Publish a curated player release (Neu / Verbessert / Behoben). Rejects if version exists."""
    tag = _normalize_version_tag(version_tag)
    if not tag:
        return {"ok": False, "error": "version_required"}

    added_list = _normalize_bullet_list(added)
    changed_list = _normalize_bullet_list(changed)
    fixed_list = _normalize_bullet_list(fixed)
    if not (added_list or changed_list or fixed_list or str(intro or "").strip()):
        return {"ok": False, "error": "empty_release"}

    label = _sanitize_player_text(version_label) or tag
    intro_body = str(intro or "").strip() or _major_release_intro(label)
    ts = _parse_release_date_ts(release_date)
    major_title = f"{tag} — {label}".strip(" —")[:200]

    own = conn is None
    if own:
        conn = db()
    try:
        if version_has_player_rows(tag, conn=conn):
            return {"ok": False, "error": "version_exists", "version_tag": tag}

        inserted: List[Dict[str, Any]] = []
        intro_entry = create_news(
            title=major_title,
            body=intro_body,
            set_banner=bool(set_banner),
            version_tag=tag,
            category="ALPHA" if str(badge).upper() == "ALPHA" else "FEATURE",
            badge=badge or "NEW",
            is_major_release=bool(is_major_release),
            created_by=created_by,
            source_ref=f"release:{tag}",
            published_at=ts,
            entry_section="",
            audience=AUDIENCE_PLAYER,
            conn=conn,
        )
        inserted.append(intro_entry)

        section_specs = (
            ("added", added_list, "FEATURE"),
            ("changed", changed_list, "FEATURE"),
            ("fixed", fixed_list, "BUGFIX"),
        )
        for section_key, bullets, category in section_specs:
            for bullet in bullets:
                entry = create_news(
                    title=bullet[:200],
                    body=bullet,
                    version_tag=tag,
                    category=category,
                    badge="",
                    is_major_release=False,
                    created_by=created_by,
                    source_ref=f"release:{tag}:{section_key}",
                    published_at=ts,
                    entry_section=section_key,
                    audience=AUDIENCE_PLAYER,
                    conn=conn,
                )
                inserted.append(entry)

        if own:
            conn.commit()
        return {
            "ok": True,
            "version_tag": tag,
            "inserted": len(inserted),
            "entries": inserted,
        }
    finally:
        if own:
            conn.close()


V09_RELEASE_PACK: Dict[str, Any] = {
    "version_tag": "v0.9",
    "version_label": "LiveOps & World Events",
    "release_date": "2026-07-31",
    "badge": "ALPHA",
    "intro": (
        "Genesis Colonies lebt: World Bosses, Titanen-Missionen, Piraten, "
        "Login/Battle Pass, Allianz-Hub und mehr — Patchnotes für Commander."
    ),
    "added": [
        "World Boss Events mit Encounter-Stage, Sofort-Angriff und Auto-Angriff",
        "Zähmen in Phase 3 (10 % Chance, 10h Timekeeper, 1h Cooldown)",
        "Titanen auf der Übersicht mit Titan-Link Popover",
        "Ark-Token-Missionen: Patrouille, Schlag und Void-Run mit Fail-Risiko",
        "Titan-Slots: Start 1, im Shop erweiterbar bis 4",
        "Piraten-Ökosystem als lebendige Bedrohung",
        "Login-Kalender und Battle Pass",
        "Allianz-Hub mit Spenden, Projekten, Tech und Boni",
        "Convenience-Shop (Stripe / PayPal)",
        "Story Ops / Lore Sidequests mit Free-Shop Ark-Token Loop",
    ],
    "changed": [
        "Titanen größer und mit Aura — lesbar auf hellen und dunklen Landscapes",
        "World Boss: Angriff, Auto und Zähmen in einer Action-Bar",
        "Performance und Live-Updates weiter gehärtet",
        "UI-Feinschliff über Overview, Fleet und News",
    ],
    "fixed": [
        "Diverse Sync- und PJAX-Themen",
        "Timer- und Queue-Stabilität",
        "Viele kleine Darstellungsfehler aus dem Alpha-Feedback",
    ],
}


def ensure_v09_release_seeded(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    """Idempotent curated v0.9 player pack (not git)."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not table_exists(conn, "universe_news"):
            return {"ok": False, "error": "schema_missing", "seeded": False}
        if version_has_player_rows("v0.9", conn=conn):
            return {"ok": True, "seeded": False, "reason": "v0.9_exists"}
        result = publish_release_pack(
            version_tag=V09_RELEASE_PACK["version_tag"],
            version_label=V09_RELEASE_PACK["version_label"],
            intro=V09_RELEASE_PACK["intro"],
            release_date=V09_RELEASE_PACK["release_date"],
            badge=V09_RELEASE_PACK["badge"],
            is_major_release=True,
            added=V09_RELEASE_PACK["added"],
            changed=V09_RELEASE_PACK["changed"],
            fixed=V09_RELEASE_PACK["fixed"],
            set_banner=False,
            conn=conn,
        )
        if own and result.get("ok"):
            conn.commit()
        return {
            "ok": bool(result.get("ok")),
            "seeded": bool(result.get("ok")),
            "publish": result,
        }
    finally:
        if own:
            conn.close()


def ensure_player_news_seeded(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    """Boot helper: CHANGELOG majors if empty, then curated v0.9 pack."""
    own = conn is None
    if own:
        conn = db()
    try:
        changelog = ensure_changelog_seeded(conn=conn)
        v09 = ensure_v09_release_seeded(conn=conn)
        if own:
            conn.commit()
        return {"ok": True, "changelog": changelog, "v09": v09}
    finally:
        if own:
            conn.close()


def ensure_changelog_seeded(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    """Import CHANGELOG.md major releases when the player timeline has none (e.g. fresh prod DB)."""
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM universe_news
            WHERE is_major_release = 1 AND is_draft = 0;
            """
        )
        if int(cur.fetchone()["c"]) > 0:
            return {"ok": True, "seeded": False, "reason": "already_has_major_releases"}

        result = import_changelog_markdown(conn=conn)
        if own:
            conn.commit()
        return {
            "ok": bool(result.get("ok")),
            "seeded": bool(result.get("ok")),
            "import": result,
        }
    finally:
        if own:
            conn.close()


def sidebar_release_nav(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    """Label + deep-link for sidebar version chip → Genesis Timeline (/news)."""
    entries = list_news(limit=500, audience=AUDIENCE_PLAYER, conn=conn)
    published = [row for row in entries if not row.get("is_draft")]
    has_dev_stream = False

    major_tags: List[Tuple[Tuple[int, int, str], str]] = []
    for row in published:
        version_tag = str(row.get("version_tag") or "").strip()
        if row.get("is_major_release") and version_tag:
            major_tags.append((_version_sort_key(version_tag), version_tag))

    label = ""
    anchor_id = ""
    version_tag = ""

    if major_tags:
        major_tags.sort(key=lambda item: item[0], reverse=True)
        version_tag = major_tags[0][1]
        label = _format_sidebar_version_label(version_tag)
        anchor_id = f"version-{version_tag.replace('.', '-')}"
    elif published:
        version_tags = sorted(
            {str(row.get("version_tag") or "").strip() for row in published if row.get("version_tag")},
            key=_version_sort_key,
            reverse=True,
        )
        if version_tags:
            version_tag = version_tags[0]
            label = _format_sidebar_version_label(version_tag)
            if version_tag:
                anchor_id = f"version-{version_tag.replace('.', '-')}"

    if not label:
        label = _player_release_fallback_label()
        fallback_tag = str(_latest_changelog_version() or "").strip()
        if fallback_tag:
            version_tag = fallback_tag
            anchor_id = f"version-{fallback_tag.replace('.', '-')}"

    news_url = "/news"
    href = f"{news_url}#{anchor_id}" if anchor_id else news_url
    return {
        "label": label,
        "version_tag": version_tag,
        "url": news_url,
        "href": href,
        "anchor_id": anchor_id,
        "has_dev_stream": has_dev_stream,
    }
