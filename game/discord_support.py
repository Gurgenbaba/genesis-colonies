"""
Discord support notifications (GC-656 / GC-656B).

Primary: forum thread in #tickets via Bot API (POST /channels/{id}/threads).
Fallback: optional webhook embed for a separate #ticket-feed text channel.
Never raises — ticket creation must always succeed.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_REQUEST_TIMEOUT_SEC = 3
FORUM_THREAD_NAME_MAX = 100
FORUM_MESSAGE_MAX = 1900

# Ingame category -> forum tag env key (DISCORD_SUPPORT_TAG_*)
_CATEGORY_FORUM_TAG_KEY: dict[str, str] = {
    "report": "cheater",
    "account": "payments",
    "balance": "payments",
    "bug": "anything",
    "general": "anything",
}

# Ingame category -> thread title prefix
_CATEGORY_THREAD_PREFIX: dict[str, str] = {
    "report": "CHEATER",
    "bug": "BUG",
    "account": "ACCOUNT",
    "balance": "BALANCE",
    "general": "SUPPORT",
}

_CATEGORY_LABEL: dict[str, str] = {
    "general": "Allgemein",
    "bug": "Bug",
    "account": "Account",
    "balance": "Balance",
    "report": "Meldung / Cheater",
}


def discord_support_forum_configured() -> bool:
    from .config import get_discord_bot_token, get_discord_support_forum_channel_id

    return bool(get_discord_bot_token() and get_discord_support_forum_channel_id())


def discord_support_webhook_configured() -> bool:
    from .config import get_discord_support_webhook_url

    return bool(get_discord_support_webhook_url())


def _discord_user_agent() -> str:
    from .config import get_discord_user_agent

    return get_discord_user_agent()


def _truncate_text(text: str, max_len: int) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(raw) <= max_len:
        return raw or "–"
    if max_len <= 1:
        return raw[:max_len]
    return raw[: max_len - 1] + "…"


def _format_timestamp(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def _sanitize_thread_name(text: str) -> str:
    cleaned = re.sub(r"[\n\r\t]+", " ", str(text or "")).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or "Support-Ticket"


def build_forum_thread_title(category: str, subject: str) -> str:
    prefix = _CATEGORY_THREAD_PREFIX.get(str(category or "general").lower(), "SUPPORT")
    title = f"[{prefix}] {_sanitize_thread_name(subject)}"
    return _truncate_text(title, FORUM_THREAD_NAME_MAX)


def _forum_tag_id_for_category(category: str) -> str | None:
    from .config import get_discord_support_forum_tag_id

    tag_key = _CATEGORY_FORUM_TAG_KEY.get(str(category or "general").lower(), "anything")
    tag_id = get_discord_support_forum_tag_id(tag_key)
    return tag_id or None


def _forum_tag_id_for_status(status: str) -> str | None:
    from .config import get_discord_support_forum_tag_id

    normalized = str(status or "open").strip().lower()
    if normalized == "in_progress":
        return get_discord_support_forum_tag_id("in_progress") or None
    if normalized in {"closed", "done"}:
        return get_discord_support_forum_tag_id("done") or None
    return None


def build_forum_applied_tags(category: str, status: str) -> list[str]:
    """Category tag + optional status tag (In-Progress / Done). Status tags replace each other."""
    tags: list[str] = []
    cat_tag = _forum_tag_id_for_category(category)
    if cat_tag:
        tags.append(cat_tag)
    status_tag = _forum_tag_id_for_status(status)
    if status_tag and status_tag not in tags:
        tags.append(status_tag)
    return tags


def _player_coordinates_line(player_id: int) -> str | None:
    try:
        from .galaxy import get_planet_coordinates
        from .planet_evolution.repository import get_context_planet

        planet = get_context_planet(int(player_id))
        if not planet:
            return None
        coords = get_planet_coordinates(planet)
        return str(coords.get("formatted") or "").strip() or None
    except Exception:
        return None


def _admin_panel_url() -> str | None:
    from .config import get_public_base_url

    base = get_public_base_url()
    if not base:
        return None
    return f"{base}/admin"


def build_forum_thread_message(
    *,
    ticket_id: int,
    player_id: int,
    player_name: str,
    subject: str,
    category: str,
    message: str,
    created_at: int,
    coordinates: str | None = None,
) -> str:
    lines = [
        f"**Spieler:** {_truncate_text(player_name, 120)}",
        f"**Spieler-ID:** {int(player_id)}",
        f"**Ticket-ID:** {int(ticket_id)}",
        f"**Kategorie:** {_CATEGORY_LABEL.get(str(category or 'general').lower(), category)}",
        "",
        "**Beschreibung:**",
        _truncate_text(message, FORUM_MESSAGE_MAX - 400),
    ]
    if coordinates:
        lines.extend(["", "**Koordinaten:**", coordinates])
    lines.extend(["", "**Erstellt:**", _format_timestamp(created_at)])
    admin_url = _admin_panel_url()
    if admin_url:
        lines.extend(["", f"[Ticket im Admin-Panel öffnen]({admin_url})"])
    return _truncate_text("\n".join(lines), FORUM_MESSAGE_MAX)


def build_webhook_embed(
    *,
    ticket_id: int,
    player_id: int,
    player_name: str,
    subject: str,
    category: str,
    message: str,
    created_at: int,
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"name": "Spielername", "value": _truncate_text(player_name, 256), "inline": True},
        {"name": "Spieler-ID", "value": str(int(player_id)), "inline": True},
        {"name": "Ticket-ID", "value": str(int(ticket_id)), "inline": True},
        {"name": "Kategorie", "value": _CATEGORY_LABEL.get(str(category or "general").lower(), category), "inline": True},
        {"name": "Betreff", "value": _truncate_text(subject, 256), "inline": False},
        {"name": "Nachricht", "value": _truncate_text(message, 800), "inline": False},
        {"name": "Zeitpunkt", "value": _format_timestamp(created_at), "inline": False},
    ]
    admin_url = _admin_panel_url()
    if admin_url:
        fields.append(
            {
                "name": "Admin",
                "value": f"[Ticket im Admin-Panel öffnen]({admin_url})",
                "inline": False,
            }
        )
    return {
        "title": "🎫 Neues Support-Ticket",
        "color": 5793266,
        "fields": fields,
        "timestamp": datetime.fromtimestamp(int(created_at), tz=timezone.utc).isoformat(),
    }


def _discord_bot_request(method: str, path: str, payload: dict[str, Any] | None = None) -> str:
    from .config import get_discord_bot_token

    token = get_discord_bot_token()
    if not token:
        raise RuntimeError("discord bot token missing")
    data = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": _discord_user_agent(),
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{DISCORD_API_BASE}{path}",
        data=data,
        method=method,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=DISCORD_REQUEST_TIMEOUT_SEC) as resp:
        return resp.read().decode("utf-8")


def _discord_bot_post_json(path: str, payload: dict[str, Any]) -> str:
    return _discord_bot_request("POST", path, payload)


def _discord_bot_patch_json(path: str, payload: dict[str, Any]) -> str:
    return _discord_bot_request("PATCH", path, payload)


def _post_webhook_embed(embed: dict[str, Any]) -> None:
    from .config import get_discord_support_webhook_url

    url = get_discord_support_webhook_url()
    if not url:
        return
    payload = {"embeds": [embed]}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": _discord_user_agent(),
        },
    )
    with urllib.request.urlopen(req, timeout=DISCORD_REQUEST_TIMEOUT_SEC) as resp:
        resp.read()


def create_support_forum_thread(
    *,
    ticket_id: int,
    player_id: int,
    player_name: str,
    subject: str,
    category: str,
    message: str,
    created_at: int,
) -> str | None:
    from .config import get_discord_support_forum_channel_id

    channel_id = get_discord_support_forum_channel_id()
    if not channel_id:
        raise RuntimeError("forum channel id missing")

    thread_name = build_forum_thread_title(category, subject)
    content = build_forum_thread_message(
        ticket_id=ticket_id,
        player_id=player_id,
        player_name=player_name,
        subject=subject,
        category=category,
        message=message,
        created_at=created_at,
        coordinates=_player_coordinates_line(player_id),
    )
    payload: dict[str, Any] = {
        "name": thread_name,
        "auto_archive_duration": 10080,
        "message": {"content": content},
        "applied_tags": build_forum_applied_tags(category, "open"),
    }
    payload["applied_tags"] = [t for t in payload["applied_tags"] if t]

    raw = _discord_bot_post_json(f"/channels/{channel_id}/threads", payload)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    thread_id = str(data.get("id") or "").strip()
    return thread_id or None


def sync_discord_thread_tags(*, thread_id: str, category: str, status: str) -> None:
    """Update forum thread tags after ticket status change. Never raises."""
    tid = str(thread_id or "").strip()
    if not tid or not discord_support_forum_configured():
        return
    applied = [t for t in build_forum_applied_tags(category, status) if t]
    try:
        _discord_bot_patch_json(f"/channels/{tid}", {"applied_tags": applied})
    except Exception as exc:
        logger.warning(
            "Discord support tag sync failed thread_id=%s status=%s: %s",
            tid,
            status,
            exc,
        )


def notify_discord_support_ticket(
    *,
    ticket_id: int,
    player_id: int,
    player_name: str,
    subject: str,
    category: str,
    message: str,
    created_at: int,
) -> str | None:
    """Forum thread (preferred) or webhook feed (fallback). Never raises."""
    try:
        if discord_support_forum_configured():
            return create_support_forum_thread(
                ticket_id=int(ticket_id),
                player_id=int(player_id),
                player_name=player_name,
                subject=subject,
                category=category,
                message=message,
                created_at=int(created_at),
            )
        if discord_support_webhook_configured():
            _post_webhook_embed(
                build_webhook_embed(
                    ticket_id=int(ticket_id),
                    player_id=int(player_id),
                    player_name=player_name,
                    subject=subject,
                    category=category,
                    message=message,
                    created_at=int(created_at),
                )
            )
    except Exception as exc:
        logger.warning(
            "Discord support notify failed ticket_id=%s player_id=%s: %s",
            ticket_id,
            player_id,
            exc,
        )
    return None
