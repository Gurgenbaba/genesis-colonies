"""
Player card service – public profiles, editing, badges.

Tables: player_cards, player_card_badges, player_card_unlocked_badges
"""

from __future__ import annotations

import io
import logging
import re
import time
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

from .db import begin_write_transaction, commit, db, rollback, table_exists
from .models import (
    get_homeworld,
    load_player,
)

from .ranking import get_playercard_ranking_snapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits & validation
# ---------------------------------------------------------------------------

TITLE_MAX = 64
BIO_MAX = 400
AVATAR_URL_MAX = 512
AVATAR_UPLOAD_MAX_BYTES = 2 * 1024 * 1024
AVATAR_OUTPUT_SIZE = 256
AVATAR_WEBP_QUALITY = 80
AVATAR_MIN_FILE_BYTES = 64
SAVE_COOLDOWN_SEC = 2

# In-process save throttle (per player_id); complements DB updated_at check
_LAST_SAVE_TS: Dict[int, int] = {}

ALLOWED_THEMES = frozenset({"cyan", "violet", "amber", "emerald", "rose"})

# badge_key → static/img/badges/<stem>.png (central asset mapping)
BADGE_IMAGE_BY_KEY: Dict[str, str] = {
    "founder": "founder",
    "builder_1k": "builder",
    "builder_10k": "architect",
    "researcher_1k": "researcher",
    "researcher_10k": "scientist",
    "commander_5k": "commander",
    "commander_50k": "legend",
    "bug_hunter": "bughunter",
    "community_hero": "community",
    "galactic_legend": "galactic_legend",
    "genesis": "genesis",
}
BADGE_IMAGE_DEFAULT = "default"
_BADGE_IMAGE_DIR = Path("static") / "img" / "badges"

BADGE_RARITY_ORDER: Dict[str, int] = {
    "mythic": 0,
    "legendary": 1,
    "epic": 2,
    "rare": 3,
    "uncommon": 4,
    "common": 5,
}

BADGE_KEY_TIER_ORDER: Dict[str, int] = {
    "genesis": 0,
    "galactic_legend": 1,
    "founder": 2,
    "commander_50k": 3,
    "researcher_10k": 4,
    "builder_10k": 5,
    "bug_hunter": 6,
    "community_hero": 7,
    "commander_5k": 8,
    "researcher_1k": 9,
    "builder_1k": 10,
}

_AVATAR_SCHEMES = frozenset({"http", "https"})
_LOCAL_AVATAR_RE = re.compile(r"^/static/uploads/avatars/avatar_(\d+)\.webp$")
_PERSISTENT_AVATAR_RE = re.compile(r"^/api/player-avatar/(\d+)$")
_ALLOWED_AVATAR_MIME = frozenset({"image/png", "image/jpeg", "image/webp"})
_AVATAR_STORAGE_REL = Path("static") / "uploads" / "avatars"
_AVATAR_BLOB_MIME = "image/webp"


def badge_image_asset_stem(badge_key: str) -> str:
    key = str(badge_key or "").strip()
    return BADGE_IMAGE_BY_KEY.get(key, BADGE_IMAGE_DEFAULT)


def badge_image_default_path() -> str:
    return f"/static/img/badges/{BADGE_IMAGE_DEFAULT}.png"


def badge_image_static_path(badge_key: str) -> str:
    """Public badge art under static/img/badges/ with default.png fallback."""
    stem = badge_image_asset_stem(badge_key)
    rel = _BADGE_IMAGE_DIR / f"{stem}.png"
    if not (_project_root() / rel).is_file():
        return badge_image_default_path()
    return f"/static/img/badges/{stem}.png"


def _badge_sort_key(badge: Dict[str, Any]) -> Tuple[int, int, int]:
    rarity = str(badge.get("rarity") or "common").lower()
    rarity_rank = BADGE_RARITY_ORDER.get(rarity, 99)
    key = str(badge.get("badge_key") or "")
    key_rank = BADGE_KEY_TIER_ORDER.get(key, 50)
    req_val = int(badge.get("requirement_value") or 0)
    return (rarity_rank, key_rank, -req_val)


def sort_badges_by_priority(badges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(badges, key=_badge_sort_key)


def _enrich_badge_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    out["image_url"] = badge_image_static_path(out.get("badge_key"))
    out.pop("icon", None)
    return out


def _now_ts() -> int:
    return int(time.time())


def ensure_player_card_tables(conn=None) -> None:
    """Idempotent schema for fresh init_db() and tests."""
    own = conn is None
    c = conn or db()
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS player_cards (
            player_id          INTEGER PRIMARY KEY,
            avatar_url         TEXT NOT NULL DEFAULT '',
            title              TEXT NOT NULL DEFAULT '',
            bio                TEXT NOT NULL DEFAULT '',
            theme              TEXT NOT NULL DEFAULT 'cyan',
            is_public          INTEGER NOT NULL DEFAULT 1,
            selected_badge_1   INTEGER,
            selected_badge_2   INTEGER,
            selected_badge_3   INTEGER,
            created_at         INTEGER NOT NULL,
            updated_at         INTEGER NOT NULL,
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS player_card_badges (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            badge_key           TEXT NOT NULL UNIQUE,
            icon                TEXT NOT NULL DEFAULT '★',
            rarity              TEXT NOT NULL DEFAULT 'common',
            name_i18n_key       TEXT NOT NULL,
            description_i18n_key TEXT NOT NULL,
            requirement_type    TEXT,
            requirement_value   INTEGER,
            is_active           INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS player_card_unlocked_badges (
            player_id   INTEGER NOT NULL,
            badge_id    INTEGER NOT NULL,
            unlocked_at INTEGER NOT NULL,
            PRIMARY KEY (player_id, badge_id),
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
            FOREIGN KEY(badge_id) REFERENCES player_card_badges(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_pc_unlocked_player "
        "ON player_card_unlocked_badges(player_id, unlocked_at DESC);"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS player_avatars (
            player_id   INTEGER PRIMARY KEY,
            image_blob  BLOB NOT NULL,
            mime_type   TEXT NOT NULL,
            updated_at  INTEGER NOT NULL,
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
        );
        """
    )
    _seed_default_badges(cur)
    if own:
        c.close()


def _seed_default_badges(cur) -> None:
    seeds = [
        ("founder", "", "legendary", "playercard_badge_founder", "playercard_badge_founder_desc", None, None),
        ("builder_1k", "", "common", "playercard_badge_builder_1k", "playercard_badge_builder_1k_desc", "score_buildings", 1000),
        ("builder_10k", "", "rare", "playercard_badge_builder_10k", "playercard_badge_builder_10k_desc", "score_buildings", 10000),
        ("researcher_1k", "", "common", "playercard_badge_researcher_1k", "playercard_badge_researcher_1k_desc", "score_research", 1000),
        ("researcher_10k", "", "rare", "playercard_badge_researcher_10k", "playercard_badge_researcher_10k_desc", "score_research", 10000),
        ("commander_5k", "", "uncommon", "playercard_badge_commander_5k", "playercard_badge_commander_5k_desc", "score_total", 5000),
        ("commander_50k", "", "epic", "playercard_badge_commander_50k", "playercard_badge_commander_50k_desc", "score_total", 50000),
        ("genesis", "", "mythic", "playercard_badge_genesis", "playercard_badge_genesis_desc", "score_planet_evolution", 10000),
        ("galactic_legend", "", "mythic", "playercard_badge_galactic_legend", "playercard_badge_galactic_legend_desc", "score_total", 100000),
        ("bug_hunter", "", "epic", "playercard_badge_bug_hunter", "playercard_badge_bug_hunter_desc", "score_defense", 25000),
        ("community_hero", "", "rare", "playercard_badge_community_hero", "playercard_badge_community_hero_desc", "score_fleet", 15000),
    ]
    for row in seeds:
        cur.execute(
            """
            INSERT OR IGNORE INTO player_card_badges
                (badge_key, icon, rarity, name_i18n_key, description_i18n_key,
                 requirement_type, requirement_value, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1);
            """,
            row,
        )
    cur.execute(
        """
        UPDATE player_card_badges
        SET icon = ''
        WHERE icon IS NOT NULL AND TRIM(icon) != '';
        """
    )
    for badge_key, req_type, req_val in (
        ("genesis", "score_planet_evolution", 10000),
        ("galactic_legend", "score_total", 100000),
        ("bug_hunter", "score_defense", 25000),
        ("community_hero", "score_fleet", 15000),
    ):
        cur.execute(
            """
            UPDATE player_card_badges
            SET requirement_type = ?, requirement_value = ?
            WHERE badge_key = ?;
            """,
            (req_type, req_val, badge_key),
        )


def _tables_ready(conn=None) -> bool:
    own = conn is None
    c = conn or db()
    try:
        return (
            table_exists(c, "player_cards")
            and table_exists(c, "player_card_badges")
            and table_exists(c, "player_card_unlocked_badges")
        )
    finally:
        if own:
            c.close()


def _strip_control(text: str) -> str:
    return "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)


def sanitize_text_field(value: Any, max_len: int) -> str:
    s = _strip_control(str(value or "").strip())
    s = s.replace("<", "").replace(">", "")
    if len(s) > max_len:
        s = s[:max_len]
    return s


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def avatar_storage_dir() -> Path:
    return _project_root() / _AVATAR_STORAGE_REL


def avatar_public_path(player_id: int) -> str:
    """Legacy static path (pre-GC-808). Prefer avatar_api_path for new uploads."""
    return f"/static/uploads/avatars/avatar_{int(player_id)}.webp"


def avatar_api_path(player_id: int) -> str:
    return f"/api/player-avatar/{int(player_id)}"


def avatar_storage_path(player_id: int) -> Path:
    return avatar_storage_dir() / f"avatar_{int(player_id)}.webp"


def local_avatar_path_from_url(url: str) -> Optional[Path]:
    m = _LOCAL_AVATAR_RE.match(str(url or "").strip())
    if not m:
        return None
    return avatar_storage_path(int(m.group(1)))


def local_avatar_file_usable(url: str, *, player_id: Optional[int] = None) -> bool:
    path = local_avatar_path_from_url(url)
    if path is None:
        return False
    if player_id is not None:
        m = _LOCAL_AVATAR_RE.match(str(url or "").strip())
        if not m or int(m.group(1)) != int(player_id):
            return False
    try:
        return path.is_file() and path.stat().st_size >= AVATAR_MIN_FILE_BYTES
    except OSError:
        return False


def player_avatar_exists(player_id: int, *, conn=None) -> bool:
    own = conn is None
    c = conn or db()
    try:
        if not table_exists(c, "player_avatars"):
            return False
        row = c.execute(
            "SELECT 1 FROM player_avatars WHERE player_id = ? LIMIT 1;",
            (int(player_id),),
        ).fetchone()
        return row is not None
    finally:
        if own:
            c.close()


def get_player_avatar_row(player_id: int, *, conn=None) -> Optional[Dict[str, Any]]:
    own = conn is None
    c = conn or db()
    try:
        if not table_exists(c, "player_avatars"):
            return None
        row = c.execute(
            """
            SELECT player_id, image_blob, mime_type, updated_at
            FROM player_avatars
            WHERE player_id = ?;
            """,
            (int(player_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def save_player_avatar_blob(
    player_id: int,
    blob: bytes,
    mime_type: str,
    *,
    conn=None,
    updated_at: Optional[int] = None,
) -> int:
    pid = int(player_id)
    ts = int(updated_at or _now_ts())
    mime = str(mime_type or _AVATAR_BLOB_MIME).split(";")[0].strip().lower()
    if mime not in _ALLOWED_AVATAR_MIME and mime != _AVATAR_BLOB_MIME:
        mime = _AVATAR_BLOB_MIME
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO player_avatars (player_id, image_blob, mime_type, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                image_blob = excluded.image_blob,
                mime_type = excluded.mime_type,
                updated_at = excluded.updated_at;
            """,
            (pid, blob, mime, ts),
        )
        if own:
            commit(c)
        return ts
    finally:
        if own:
            c.close()


def can_serve_player_avatar(
    player_id: int,
    *,
    viewer_id: Optional[int] = None,
    conn=None,
) -> bool:
    """Avatar bytes are only served for public profiles or the owner."""
    own = conn is None
    c = conn or db()
    try:
        if viewer_id is not None and int(viewer_id) == int(player_id):
            return True
        card = get_player_card_row(player_id, conn=c)
        if not card:
            return False
        return bool(int(card.get("is_public", 1) or 0))
    finally:
        if own:
            c.close()


def resolve_avatar_display(
    url: Any,
    version: Any = None,
    *,
    player_id: Optional[int] = None,
    conn=None,
) -> Tuple[str, bool]:
    """Return client avatar URL only when validation passes and storage exists."""
    ok, validated = validate_avatar_url(url, player_id=player_id)
    if not ok or not validated:
        return "", False

    pid = player_id
    if pid is None:
        m_api = _PERSISTENT_AVATAR_RE.match(validated)
        m_local = _LOCAL_AVATAR_RE.match(validated)
        if m_api:
            pid = int(m_api.group(1))
        elif m_local:
            pid = int(m_local.group(1))

    if validated.startswith("/api/player-avatar/"):
        if pid is None or not player_avatar_exists(pid, conn=conn):
            return "", False
        return avatar_url_for_client(validated, version), True

    if validated.startswith("/static/uploads/avatars/"):
        if pid is not None and player_avatar_exists(pid, conn=conn):
            api_url = avatar_api_path(pid)
            return avatar_url_for_client(api_url, version), True
        if not local_avatar_file_usable(validated, player_id=player_id):
            return "", False
        return avatar_url_for_client(validated, version), True

    return avatar_url_for_client(validated, version), True


def avatar_url_for_client(url: str, version: Any = None) -> str:
    """Append cache-busting query param for avatar URLs (http(s) or local static)."""
    s = str(url or "").strip()
    if not s:
        return ""
    try:
        v = int(version or 0)
    except (TypeError, ValueError):
        v = 0
    if v <= 0:
        return s
    if s.startswith("/"):
        sep = "&" if "?" in s else "?"
        return f"{s}{sep}v={v}"
    try:
        parsed = urlparse(s)
    except Exception:
        return s
    if parsed.scheme not in _AVATAR_SCHEMES:
        return s
    sep = "&" if parsed.query else "?"
    return f"{s}{sep}v={v}"


def validate_avatar_url(url: Any, *, player_id: Optional[int] = None) -> Tuple[bool, str]:
    s = _strip_control(str(url or "").strip())
    if len(s) > AVATAR_URL_MAX:
        s = s[:AVATAR_URL_MAX]
    if not s:
        return True, ""
    if s.startswith("/static/uploads/avatars/"):
        m = _LOCAL_AVATAR_RE.match(s)
        if not m:
            return False, "playercard_invalid_avatar"
        if player_id is not None and int(m.group(1)) != int(player_id):
            return False, "playercard_invalid_avatar"
        return True, s
    if s.startswith("/api/player-avatar/"):
        m = _PERSISTENT_AVATAR_RE.match(s)
        if not m:
            return False, "playercard_invalid_avatar"
        if player_id is not None and int(m.group(1)) != int(player_id):
            return False, "playercard_invalid_avatar"
        return True, s
    try:
        parsed = urlparse(s)
    except Exception:
        return False, "playercard_invalid_avatar"
    if parsed.scheme not in _AVATAR_SCHEMES:
        return False, "playercard_invalid_avatar"
    if not parsed.netloc:
        return False, "playercard_invalid_avatar"
    if re.search(r"[\s<>\"']", s):
        return False, "playercard_invalid_avatar"
    return True, s


def _process_avatar_image(src: Image.Image) -> Image.Image:
    im = ImageOps.exif_transpose(src)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
    else:
        im = im.convert("RGB")
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    im = im.crop((left, top, left + side, top + side))
    return im.resize((AVATAR_OUTPUT_SIZE, AVATAR_OUTPUT_SIZE), Image.Resampling.LANCZOS)


def _avatar_webp_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    has_alpha = im.mode in ("RGBA", "LA") or "A" in im.getbands()
    if has_alpha:
        im.save(buf, "WEBP", quality=AVATAR_WEBP_QUALITY, method=6, lossless=False)
    else:
        im.convert("RGB").save(buf, "WEBP", quality=AVATAR_WEBP_QUALITY, method=6)
    data = buf.getvalue()
    if len(data) < AVATAR_MIN_FILE_BYTES:
        raise ValueError("avatar_output_too_small")
    return data


def _save_avatar_webp(im: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_avatar_webp_bytes(im))


def _read_upload_bytes(file_storage: Any) -> Tuple[Optional[bytes], str]:
    if file_storage is None:
        return None, "playercard_avatar_missing"
    raw = file_storage.read()
    if not raw:
        return None, "playercard_avatar_missing"
    if len(raw) > AVATAR_UPLOAD_MAX_BYTES:
        return None, "playercard_avatar_too_large"
    return raw, ""


def _validate_upload_image(file_storage: Any, raw: bytes) -> Tuple[bool, str]:
    """Accept declared MIME or sniff PNG/JPEG/WebP (e.g. application/octet-stream on mobile)."""
    mime = str(getattr(file_storage, "mimetype", "") or "").split(";")[0].strip().lower()
    if mime in _ALLOWED_AVATAR_MIME:
        return True, mime
    try:
        with Image.open(io.BytesIO(raw)) as src:
            fmt = str(src.format or "").upper()
    except Exception:
        return False, "playercard_avatar_invalid_type"
    sniffed = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "WEBP": "image/webp",
    }.get(fmt)
    if sniffed:
        return True, sniffed
    return False, "playercard_avatar_invalid_type"


def _avatar_blob_from_upload(file_storage: Any) -> Tuple[Optional[bytes], str]:
    raw, err = _read_upload_bytes(file_storage)
    if raw is None:
        return None, err

    ok_mime, mime_err = _validate_upload_image(file_storage, raw)
    if not ok_mime:
        return None, mime_err

    try:
        with Image.open(io.BytesIO(raw)) as src:
            fmt = str(src.format or "").upper()
            if fmt in ("GIF", "SVG", "MPO"):
                return None, "playercard_avatar_invalid_type"
            im = _process_avatar_image(src)
        return _avatar_webp_bytes(im), ""
    except UnidentifiedImageError:
        return None, "playercard_avatar_invalid_type"
    except Exception:
        logger.exception("avatar image decode failed")
        return None, "playercard_avatar_invalid_type"


def process_avatar_upload(player_id: int, file_storage: Any) -> Tuple[bool, str]:
    """Validate, resize, and persist avatar as WEBP blob. Returns (ok, path_or_reason)."""
    pid = int(player_id)
    blob, err = _avatar_blob_from_upload(file_storage)
    if blob is None:
        return False, err

    public_path = avatar_api_path(pid)
    c = db()
    try:
        begin_write_transaction(c)
        save_player_avatar_blob(pid, blob, _AVATAR_BLOB_MIME, conn=c)
        commit(c)
    except Exception:
        rollback(c)
        logger.exception("avatar blob save failed player_id=%s", pid)
        return False, "playercard_avatar_save_failed"
    finally:
        c.close()

    return True, public_path


def backfill_legacy_avatar_blobs(conn=None) -> int:
    """
    Import legacy static/uploads avatars into player_avatars and normalize URLs.
    Safe on every boot (Railway: run before ephemeral static files are lost).
    """
    own = conn is None
    c = conn or db()
    updated = 0
    try:
        if not table_exists(c, "player_avatars") or not table_exists(c, "player_cards"):
            return 0

        if own:
            begin_write_transaction(c)

        rows = c.execute(
            "SELECT player_id, avatar_url FROM player_cards WHERE TRIM(avatar_url) != '';"
        ).fetchall()
        now = _now_ts()
        for row in rows:
            pid = int(row["player_id"])
            url = str(row["avatar_url"] or "").strip()
            api_url = avatar_api_path(pid)

            if player_avatar_exists(pid, conn=c):
                if url != api_url and (
                    url.startswith("/static/uploads/avatars/")
                    or url.startswith("/api/player-avatar/")
                ):
                    c.execute(
                        "UPDATE player_cards SET avatar_url = ? WHERE player_id = ?;",
                        (api_url, pid),
                    )
                    updated += 1
                continue

            path = local_avatar_path_from_url(url)
            if path is None or not path.is_file():
                continue

            try:
                raw = path.read_bytes()
                if len(raw) < AVATAR_MIN_FILE_BYTES:
                    continue
                with Image.open(io.BytesIO(raw)) as src:
                    im = _process_avatar_image(src)
                blob = _avatar_webp_bytes(im)
                save_player_avatar_blob(pid, blob, _AVATAR_BLOB_MIME, conn=c, updated_at=now)
                c.execute(
                    "UPDATE player_cards SET avatar_url = ?, updated_at = ? WHERE player_id = ?;",
                    (api_url, now, pid),
                )
                updated += 1
            except Exception:
                logger.exception("legacy avatar backfill failed player_id=%s", pid)
                continue

        if own:
            commit(c)
    except Exception:
        if own:
            rollback(c)
        raise
    finally:
        if own:
            c.close()
    return updated


def upload_own_avatar(
    player_id: int,
    file_storage: Any,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    pid = int(player_id)
    card = ensure_player_card(pid)
    now = _now_ts()
    last_upd = int(card.get("updated_at") or 0)
    last_mem = int(_LAST_SAVE_TS.get(pid, 0) or 0)
    if last_mem and (now - last_mem) < SAVE_COOLDOWN_SEC:
        return False, "playercard_rate_limited", None
    if last_upd and (now - last_upd) < SAVE_COOLDOWN_SEC and last_mem:
        return False, "playercard_rate_limited", None

    blob, err = _avatar_blob_from_upload(file_storage)
    if blob is None:
        return False, err, None

    public_path = avatar_api_path(pid)
    c = db()
    try:
        begin_write_transaction(c)
        save_player_avatar_blob(pid, blob, _AVATAR_BLOB_MIME, conn=c, updated_at=now)
        cur = c.cursor()
        cur.execute(
            """
            UPDATE player_cards SET avatar_url = ?, updated_at = ?
            WHERE player_id = ?;
            """,
            (public_path, now, pid),
        )
        commit(c)
    except Exception:
        rollback(c)
        logger.exception("avatar upload transaction failed player_id=%s", pid)
        return False, "playercard_avatar_save_failed", None
    finally:
        c.close()

    _LAST_SAVE_TS[pid] = now
    view, _ = build_public_card(pid, viewer_id=pid, sync_badges=True)
    return True, "playercard_avatar_upload_success", view


def validate_theme(theme: Any) -> str:
    t = sanitize_text_field(theme, 24).lower()
    if t not in ALLOWED_THEMES:
        return "cyan"
    return t


def get_player_card_row(player_id: int, conn=None) -> Optional[Dict[str, Any]]:
    if not _tables_ready(conn):
        return None
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute("SELECT * FROM player_cards WHERE player_id = ?", (int(player_id),))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def _synthetic_player_card(player_id: int) -> Dict[str, Any]:
    """In-memory defaults for read-only display (no INSERT)."""
    now = _now_ts()
    return {
        "player_id": int(player_id),
        "avatar_url": "",
        "title": "",
        "bio": "",
        "theme": "cyan",
        "is_public": 1,
        "selected_badge_1": None,
        "selected_badge_2": None,
        "selected_badge_3": None,
        "created_at": now,
        "updated_at": now,
    }


def get_player_card_for_display(player_id: int, conn=None) -> Dict[str, Any]:
    """Read-only card row for GET /api/player-card (never INSERT)."""
    row = get_player_card_row(player_id, conn=conn)
    return row if row else _synthetic_player_card(player_id)


def ensure_player_card(player_id: int, conn=None) -> Dict[str, Any]:
    existing = get_player_card_row(player_id, conn=conn)
    if existing:
        return existing
    now = _now_ts()
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO player_cards
                (player_id, avatar_url, title, bio, theme, is_public,
                 selected_badge_1, selected_badge_2, selected_badge_3,
                 created_at, updated_at)
            VALUES (?, '', '', '', 'cyan', 1, NULL, NULL, NULL, ?, ?);
            """,
            (int(player_id), now, now),
        )
        if own:
            commit(c)
        return get_player_card_row(player_id, conn=c) or {}
    finally:
        if own:
            c.close()


def _count_colonies(player_id: int, conn=None) -> int:
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM planets WHERE player_id = ?", (int(player_id),))
        row = cur.fetchone()
        return int(row["c"] if row else 0)
    finally:
        if own:
            c.close()


def _activity_label(last_seen: int, is_self: bool) -> str:
    """Privacy-friendly activity string key."""
    now = _now_ts()
    delta = max(0, now - int(last_seen or 0))
    if is_self:
        if delta < 300:
            return "playercard_active_now"
        if delta < 86400:
            return "playercard_recently_active"
        return "playercard_active_earlier"
    if delta < 86400:
        return "playercard_recently_active"
    if delta < 604800:
        return "playercard_active_this_week"
    return "playercard_active_earlier"


def _read_player_score(player_id: int, conn) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM player_scores WHERE player_id = ?", (int(player_id),))
    row = cur.fetchone()
    return dict(row) if row else {}


def _sync_badge_unlocks(player_id: int, conn=None) -> None:
    if not _tables_ready(conn):
        return
    c = conn or db()
    own = conn is None
    score = _read_player_score(player_id, c) or {}
    metrics = {
        "score_total": int(score.get("score_total", 0) or 0),
        "score_buildings": int(score.get("score_buildings", 0) or 0),
        "score_research": int(score.get("score_research", 0) or 0),
        "score_fleet": int(score.get("score_fleet", 0) or 0),
        "score_defense": int(score.get("score_defense", 0) or 0),
        "score_planet_evolution": int(score.get("score_planet_evolution", 0) or 0),
    }
    cur = c.cursor()
    cur.execute(
        """
        SELECT id, badge_key, requirement_type, requirement_value
        FROM player_card_badges
        WHERE is_active = 1 AND requirement_type IS NOT NULL;
        """
    )
    badges = cur.fetchall()
    now = _now_ts()
    for b in badges:
        req_type = b["requirement_type"]
        req_val = int(b["requirement_value"] or 0)
        if metrics.get(req_type, 0) < req_val:
            continue
        cur.execute(
            """
            INSERT OR IGNORE INTO player_card_unlocked_badges (player_id, badge_id, unlocked_at)
            VALUES (?, ?, ?);
            """,
            (int(player_id), int(b["id"]), now),
        )
    # Founder badge for all existing players (one-time unlock)
    cur.execute("SELECT id FROM player_card_badges WHERE badge_key = 'founder' LIMIT 1;")
    founder = cur.fetchone()
    if founder:
        cur.execute(
            """
            INSERT OR IGNORE INTO player_card_unlocked_badges (player_id, badge_id, unlocked_at)
            VALUES (?, ?, ?);
            """,
            (int(player_id), int(founder["id"]), now),
        )
    if own:
        c.close()


def _list_unlocked_badges(player_id: int, conn=None) -> List[Dict[str, Any]]:
    if not _tables_ready(conn):
        return []
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute(
            """
            SELECT b.id, b.badge_key, b.rarity, b.name_i18n_key, b.description_i18n_key,
                   b.requirement_type, b.requirement_value, u.unlocked_at
            FROM player_card_unlocked_badges u
            JOIN player_card_badges b ON b.id = u.badge_id
            WHERE u.player_id = ? AND b.is_active = 1;
            """,
            (int(player_id),),
        )
        return sort_badges_by_priority([_enrich_badge_row(dict(r)) for r in cur.fetchall()])
    finally:
        if own:
            c.close()


def _selected_badges(card: Dict[str, Any], unlocked: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unlocked_by_id = {int(b["id"]): b for b in unlocked}
    out: List[Dict[str, Any]] = []
    for key in ("selected_badge_1", "selected_badge_2", "selected_badge_3"):
        bid = card.get(key)
        if bid is None:
            continue
        b = unlocked_by_id.get(int(bid))
        if b:
            out.append(b)
    return out


def player_exists(player_id: int, conn=None) -> bool:
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute("SELECT 1 FROM players WHERE id = ? LIMIT 1;", (int(player_id),))
        return cur.fetchone() is not None
    finally:
        if own:
            c.close()


def build_public_card(
    target_id: int,
    viewer_id: Optional[int] = None,
    conn=None,
    *,
    sync_badges: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Returns (card_payload, error_key).
    error_key: playercard_not_found, playercard_private, etc.
    """
    tid = int(target_id)
    own_conn = conn is None
    c = conn or db()

    try:
        if not player_exists(tid, conn=c):
            return None, "playercard_not_found"

        player = load_player(tid, conn=c)
        if not player:
            return None, "playercard_not_found"

        is_self = viewer_id is not None and int(viewer_id) == tid
        card = get_player_card_for_display(tid, conn=c)
        if sync_badges:
            card = ensure_player_card(tid, conn=c)
            _sync_badge_unlocks(tid, conn=c)
        unlocked = _list_unlocked_badges(tid, conn=c)
        return _build_public_card_payload(tid, player, is_self, card, unlocked, c)
    finally:
        if own_conn:
            c.close()


def _commander_fields(player: Dict[str, Any]) -> Dict[str, str]:
    raw = str(player.get("name") or "").strip() or "—"
    return {
        "commander_name": raw,
        "commander_name_lookup": raw,
        "commander_name_raw": raw,
    }


def _build_public_card_payload(
    tid: int,
    player: Dict[str, Any],
    is_self: bool,
    card: Dict[str, Any],
    unlocked: List[Dict[str, Any]],
    conn,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:

    is_public = bool(int(card.get("is_public", 1) or 0))
    if not is_public and not is_self:
        names = _commander_fields(player)
        return {
            "player_id": tid,
            "commander_name": escape(names["commander_name"]),
            "commander_name_lookup": names["commander_name_lookup"],
            "is_private": True,
            "is_self": False,
            "can_edit": False,
        }, None

    ranking = get_playercard_ranking_snapshot(tid, conn=conn)
    homeworld = get_homeworld(tid, conn=conn)
    colonies = _count_colonies(tid, conn=conn)
    last_seen = int(player.get("last_seen") or 0)

    names = _commander_fields(player)
    card_updated = int(card.get("updated_at") or 0)
    avatar_display, _ = resolve_avatar_display(
        card.get("avatar_url"),
        card_updated,
        player_id=tid,
    )
    rank = ranking.get("rank")
    total_players = ranking.get("total_players")
    payload: Dict[str, Any] = {
        "player_id": tid,
        "commander_name": escape(names["commander_name"]),
        "commander_name_lookup": names["commander_name_lookup"],
        "commander_name_raw": names["commander_name_raw"],
        "avatar_url": escape(avatar_display),
        "avatar_url_client": avatar_display,
        "avatar_version": card_updated,
        "title": escape(sanitize_text_field(card.get("title"), TITLE_MAX)),
        "bio": escape(sanitize_text_field(card.get("bio"), BIO_MAX)),
        "theme": validate_theme(card.get("theme")),
        "is_public": is_public,
        "is_private": False,
        "is_self": is_self,
        "can_edit": is_self,
        "alliance": None,
        "alliance_label": "",
        "rank": int(rank) if rank is not None and int(rank) >= 1 else None,
        "total_players": int(total_players) if total_players else None,
        "score_total": int(ranking.get("score_total", 0) or 0),
        "score_buildings": int(ranking.get("score_buildings", 0) or 0),
        "score_research": int(ranking.get("score_research", 0) or 0),
        "score_fleet": int(ranking.get("score_fleet", 0) or 0),
        "score_defense": int(ranking.get("score_defense", 0) or 0),
        "score_military": int(ranking.get("score_military", 0) or 0),
        "score_planet_evolution": int(ranking.get("score_planet_evolution", 0) or 0),
        "rank_defense": ranking.get("rank_defense"),
        "rank_fleet": ranking.get("rank_fleet"),
        "rank_military": ranking.get("rank_military"),
        "home_planet": escape(str(homeworld.get("name") or "—")),
        "colonies": colonies,
        "badges": _selected_badges(card, unlocked),
        "unlocked_badges": unlocked,
        "activity_key": _activity_label(last_seen, is_self),
        "stats": {
            "score_total": int(ranking.get("score_total", 0) or 0),
            "score_buildings": int(ranking.get("score_buildings", 0) or 0),
            "score_research": int(ranking.get("score_research", 0) or 0),
            "score_fleet": int(ranking.get("score_fleet", 0) or 0),
            "score_defense": int(ranking.get("score_defense", 0) or 0),
            "score_planet_evolution": int(ranking.get("score_planet_evolution", 0) or 0),
            "colonies": colonies,
        },
    }
    return payload, None


def build_edit_card(player_id: int, conn=None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    view, err = build_public_card(player_id, viewer_id=player_id, conn=conn)
    if err or not view:
        return view, err
    if not view.get("is_self"):
        return None, "playercard_forbidden"
    card = get_player_card_row(player_id, conn=conn) or {}
    raw_url = str(card.get("avatar_url") or "")
    card_updated = int(card.get("updated_at") or 0)
    ok_av, validated_url = validate_avatar_url(raw_url, player_id=player_id)
    avatar_display, _ = resolve_avatar_display(
        raw_url,
        card_updated,
        player_id=player_id,
    )
    view["form"] = {
        "avatar_url": validated_url if ok_av else "",
        "avatar_url_display": avatar_display,
        "title": sanitize_text_field(card.get("title"), TITLE_MAX),
        "bio": sanitize_text_field(card.get("bio"), BIO_MAX),
        "theme": validate_theme(card.get("theme")),
        "is_public": bool(int(card.get("is_public", 1) or 0)),
        "selected_badge_1": card.get("selected_badge_1"),
        "selected_badge_2": card.get("selected_badge_2"),
        "selected_badge_3": card.get("selected_badge_3"),
    }
    view["themes"] = sorted(ALLOWED_THEMES)
    return view, None


def save_own_card(player_id: int, data: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    pid = int(player_id)
    card = ensure_player_card(pid)
    now = _now_ts()
    last_upd = int(card.get("updated_at") or 0)
    last_mem = int(_LAST_SAVE_TS.get(pid, 0) or 0)
    if last_mem and (now - last_mem) < SAVE_COOLDOWN_SEC:
        return False, "playercard_rate_limited", None
    if last_upd and (now - last_upd) < SAVE_COOLDOWN_SEC and last_mem:
        return False, "playercard_rate_limited", None

    title = sanitize_text_field(data.get("title"), TITLE_MAX)
    bio = sanitize_text_field(data.get("bio"), BIO_MAX)
    if not title and data.get("title"):
        return False, "playercard_invalid_title", None
    if len(sanitize_text_field(data.get("bio"), BIO_MAX)) != len(_strip_control(str(data.get("bio") or "").strip())):
        pass  # already truncated

    ok_av, avatar_url = validate_avatar_url(data.get("avatar_url"), player_id=pid)
    if not ok_av:
        return False, avatar_url, None
    if not avatar_url:
        existing = str(card.get("avatar_url") or "").strip()
        ok_ex, existing_url = validate_avatar_url(existing, player_id=pid)
        if ok_ex and existing_url:
            if existing_url.startswith("/api/player-avatar/") and player_avatar_exists(pid):
                avatar_url = existing_url
            elif existing_url.startswith("/static/uploads/avatars/"):
                if player_avatar_exists(pid):
                    avatar_url = avatar_api_path(pid)
                elif local_avatar_file_usable(existing_url, player_id=pid):
                    avatar_url = existing_url
            elif existing_url.startswith(("http://", "https://")):
                avatar_url = existing_url

    theme = validate_theme(data.get("theme"))
    is_public = 1 if str(data.get("is_public", "1")).lower() in ("1", "true", "yes", "on") else 0

    selected: List[Optional[int]] = [None, None, None]
    raw_slots = [
        data.get("selected_badge_1"),
        data.get("selected_badge_2"),
        data.get("selected_badge_3"),
    ]

    c = db()
    try:
        begin_write_transaction(c)
        _sync_badge_unlocks(pid, conn=c)
        unlocked_ids = {int(b["id"]) for b in _list_unlocked_badges(pid, conn=c)}
        seen: set[int] = set()
        for i, raw in enumerate(raw_slots):
            if raw in (None, "", "null", "none"):
                continue
            try:
                bid = int(raw)
            except (TypeError, ValueError):
                continue
            if bid not in unlocked_ids or bid in seen:
                continue
            seen.add(bid)
            selected[i] = bid
        cur = c.cursor()
        cur.execute(
            """
            UPDATE player_cards SET
                avatar_url = ?,
                title = ?,
                bio = ?,
                theme = ?,
                is_public = ?,
                selected_badge_1 = ?,
                selected_badge_2 = ?,
                selected_badge_3 = ?,
                updated_at = ?
            WHERE player_id = ?;
            """,
            (
                avatar_url,
                title,
                bio,
                theme,
                is_public,
                selected[0],
                selected[1],
                selected[2],
                now,
                pid,
            ),
        )
        commit(c)
    except Exception:
        rollback(c)
        raise
    finally:
        c.close()

    _LAST_SAVE_TS[pid] = now

    view, _ = build_public_card(pid, viewer_id=pid, sync_badges=True)
    return True, "playercard_save_success", view
