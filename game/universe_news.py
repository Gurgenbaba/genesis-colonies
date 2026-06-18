"""Universe news / Genesis Timeline (GC-642 / GC-650 / GC-651)."""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .db import table_exists
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
    version_tag, category, badge, image_url, is_major_release, is_draft
"""


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
    conn: sqlite3.Connection | None = None,
) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_legacy_motd_migrated(conn)
        cur = conn.cursor()
        draft_clause = "" if include_drafts else "WHERE is_draft = 0"
        cur.execute(
            f"""
            SELECT {_SELECT_COLS}
            FROM universe_news
            {draft_clause}
            ORDER BY published_at DESC, id DESC
            LIMIT ?;
            """,
            (max(1, int(limit)),),
        )
        return [_row_to_entry(row) for row in cur.fetchall()]
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
        return _row_to_entry(row) if row else None
    finally:
        if own:
            conn.close()


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
            WHERE is_banner = 1 AND is_draft = 0
            ORDER BY published_at DESC, id DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        if row:
            return _row_to_entry(row)
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
        return _row_to_entry(row) if row else None
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
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    clean_title = str(title or "").strip() or "Update"
    clean_body = str(body or "").strip()
    if not clean_body and not is_draft:
        raise ValueError("body_required")

    own = conn is None
    if own:
        conn = db()
    try:
        ts = _now_ts() if not is_draft else 0
        cur = conn.cursor()
        if set_banner and not is_draft:
            _clear_banner(cur)
        cur.execute(
            f"""
            INSERT INTO universe_news (
                title, body, published_at, is_banner, created_by, created_at,
                version_tag, category, badge, image_url, is_major_release, is_draft
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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


def news_page_payload(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    entries = list_news(limit=500, conn=conn)
    timeline = build_timeline(entries)
    return {"ok": True, "entries": entries, "timeline": timeline}


def whats_new_payload(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    payload = news_page_payload(conn=conn)
    timeline = payload.get("timeline") or []
    if not timeline:
        return {"ok": True, "show": False}

    latest_year = timeline[0]
    versions = latest_year.get("versions") or []
    if not versions:
        return {"ok": True, "show": False}

    latest = versions[0]
    highlights = [
        row
        for row in (latest.get("entries") or [])
        if not row.get("is_major_release")
    ][:6]
    if not highlights:
        highlights = (latest.get("entries") or [])[:6]
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
            {"id": row["id"], "title": row["title"], "body": row.get("body") or "", "category": row.get("category") or ""}
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
    changelog_path = path or (Path(__file__).resolve().parent.parent / "CHANGELOG.md")
    text = changelog_path.read_text(encoding="utf-8")
    own = conn is None
    if own:
        conn = db()
    inserted = 0
    skipped_versions: List[str] = []

    version_header_re = re.compile(r"^##\s+(v\d+\.\d+)\s*(?:[—–-]\s*(.+))?\s*$", re.I | re.M)
    matches = list(version_header_re.finditer(text))
    if not matches:
        return {"ok": True, "inserted": 0, "skipped_versions": []}

    cur = conn.cursor()
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

        ts = _now_ts() - (len(matches) - idx) * 86400
        major_title = f"{version_tag} — {version_label}".strip(" —")
        badge = "ALPHA" if "alpha" in version_label.lower() else "NEW"
        cur.execute(
            f"""
            INSERT INTO universe_news (
                title, body, published_at, is_banner, created_by, created_at,
                version_tag, category, badge, image_url, is_major_release, is_draft
            )
            VALUES (?, ?, ?, 0, ?, ?, ?, 'FEATURE', ?, '', 1, 0);
            """,
            (
                major_title[:200],
                major_title,
                ts,
                int(created_by) if created_by is not None else None,
                ts,
                version_tag,
                badge,
            ),
        )
        inserted += 1

        section_re = re.compile(r"^###\s+(Added|Changed|Fixed|Removed|Technical)\s*$", re.I | re.M)
        section_matches = list(section_re.finditer(block))
        for sidx, sec in enumerate(section_matches):
            cat_key = sec.group(1).lower()
            category = _CHANGELOG_SECTION_CATEGORY.get(cat_key, "FEATURE")
            sec_start = sec.end()
            sec_end = section_matches[sidx + 1].start() if sidx + 1 < len(section_matches) else len(block)
            sec_body = block[sec_start:sec_end]
            for line in sec_body.splitlines():
                bullet = line.strip()
                if not bullet.startswith("- "):
                    continue
                item = bullet[2:].strip()
                if not item or item.startswith("**"):
                    continue
                item = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
                title = item[:200]
                cur.execute(
                    f"""
                    INSERT INTO universe_news (
                        title, body, published_at, is_banner, created_by, created_at,
                        version_tag, category, badge, image_url, is_major_release, is_draft
                    )
                    VALUES (?, ?, ?, 0, ?, ?, ?, ?, '', '', 0, 0);
                    """,
                    (
                        title,
                        item,
                        ts,
                        int(created_by) if created_by is not None else None,
                        ts,
                        version_tag,
                        category,
                    ),
                )
                inserted += 1

    if own:
        conn.commit()
    return {"ok": True, "inserted": inserted, "skipped_versions": skipped_versions}


def news_metadata() -> Dict[str, Any]:
    return {
        "categories": list(NEWS_CATEGORIES),
        "badges": list(NEWS_BADGES),
    }
