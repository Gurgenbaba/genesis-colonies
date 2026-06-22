"""Server-side player / commander name moderation (GC-735)."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.request
from typing import Iterable, Tuple

logger = logging.getLogger(__name__)

FORBIDDEN_REASON = "name_policy_forbidden"

_LEET_MAP = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "@": "a",
        "$": "s",
    }
)

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\ufeff\u2060]")

# Extremist / NS / hate ideology tokens (normalized substring match).
_EXTREMIST_BLOCKLIST: tuple[str, ...] = (
    "adolf",
    "hitler",
    "hizzler",
    "nazi",
    "nsdap",
    "fuhrer",
    "fuehrer",
    "siegheil",
    "heilhitler",
    "holocaust",
    "gestapo",
    "auschwitz",
    "sscommander",
    "sswolf",
    "hitlerjugend",
    "thirdreich",
    "3rdreich",
    "bloodandhonor",
    "whitepower",
    "heil",
)

# Religious / ethnic group labels abused as usernames (context-free block).
_PROTECTED_CLASS_BLOCKLIST: tuple[str, ...] = (
    "jude",
    "juden",
    "judin",
    "jew",
    "jews",
    "jewish",
    "muslim",
    "muslims",
    "islam",
    "christian",
    "christians",
    "moslem",
    "zigeuner",
    "gypsy",
    "roma",
    "romani",
    "schwarzer",
    "weisser",
    "weiber",
    "kanake",
)

# Short protected tokens: exact normalized match only (avoid "romantic" → "roma").
_PROTECTED_CLASS_EXACT: frozenset[str] = frozenset(
    token for token in _PROTECTED_CLASS_BLOCKLIST if len(token) <= 4
)

# Slurs / profanity (local fallback).
_PROFANITY_BLOCKLIST: tuple[str, ...] = (
    "nigger",
    "nigga",
    "faggot",
    "kike",
    "neger",
    "hure",
    "fotze",
    "schlampe",
)

# Exact normalized numeric hate codes and short numeric-only names.
_NUMERIC_HATE_EXACT: frozenset[str] = frozenset(
    {
        "14",
        "18",
        "88",
        "1488",
        "8814",
    }
)

# Regex on normalized policy string (leet + punctuation already stripped).
_REGEX_BLOCKLIST: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"1488",
        r"n[a@4]zi",
        r"h[e3]+il",
        r"adolf.*hitt?ler",
        r"hitt?ler.*adolf",
        r"^ss[a-z0-9]{2,}",
        r"^hh$",
        r"nsdap",
        r"swastika",
        r"hakenkreuz",
    )
)


def _fold_unicode(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _normalize_base_for_policy(name: str) -> str:
    """Fold unicode and strip noise without leetspeak digit substitution (hate numbers)."""
    s = _fold_unicode(str(name or "").strip().lower())
    s = _ZERO_WIDTH_RE.sub("", s)
    return re.sub(r"[^a-z0-9]", "", s)


def normalize_player_name_for_policy(name: str) -> str:
    """Lowercase, fold umlauts, strip zero-width, reduce leetspeak, strip non-alphanumerics."""
    s = _fold_unicode(str(name or "").strip().lower())
    s = _ZERO_WIDTH_RE.sub("", s)
    s = s.translate(_LEET_MAP)
    return re.sub(r"[^a-z0-9]", "", s)


def _protected_class_variants(normalized_base: str, normalized_leet: str) -> frozenset[str]:
    """Vowel leet bypasses (e.g. J1de → jude) without treating 8 as b for numbers."""
    variants = {normalized_base, normalized_leet}
    if "1" in normalized_base:
        variants.add(normalized_base.replace("1", "u"))
        variants.add(normalized_base.replace("1", "i"))
    return frozenset(variants)


# Ticket alias
normalize_name_for_policy = normalize_player_name_for_policy


def _matches_substring_block(normalized: str, tokens: Iterable[str]) -> bool:
    return any(token in normalized for token in tokens)


def _matches_protected_class_block(normalized_base: str, normalized_leet: str) -> bool:
    for variant in _protected_class_variants(normalized_base, normalized_leet):
        if variant in _PROTECTED_CLASS_EXACT:
            return True
        for token in _PROTECTED_CLASS_BLOCKLIST:
            if len(token) <= 4:
                continue
            if token in variant:
                return True
    return False


def _matches_numeric_hate_codes(normalized: str) -> bool:
    if normalized in _NUMERIC_HATE_EXACT:
        return True
    if normalized.isdigit() and len(normalized) <= 4:
        return True
    if "1488" in normalized:
        return True
    if normalized.endswith("88") and len(normalized) <= 6:
        return True
    return False


def _matches_regex_blocklist(normalized_leet: str, normalized_base: str) -> bool:
    for candidate in {normalized_leet, normalized_base}:
        if any(pattern.search(candidate) for pattern in _REGEX_BLOCKLIST):
            return True
    return False


def _openai_moderation_enabled() -> bool:
    flag = str(os.environ.get("GC_NAME_POLICY_OPENAI", "")).strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    return bool(str(os.environ.get("OPENAI_API_KEY", "")).strip())


def _openai_moderation_blocks(name: str) -> bool:
    """
    Optional supplement — local policy remains authoritative.
    Returns False when disabled or on API errors (fail-open).
    """
    if not _openai_moderation_enabled():
        return False

    api_key = str(os.environ.get("OPENAI_API_KEY", "")).strip()
    payload = json.dumps({"model": "omni-moderation-latest", "input": str(name or "")}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/moderations",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("name_policy openai moderation skipped: %s", exc)
        return False

    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list) or not results:
        return False
    first = results[0] if isinstance(results[0], dict) else {}
    return bool(first.get("flagged"))


def validate_player_name(name: str) -> Tuple[bool, str]:
    """
    Return (ok, reason_key). reason_key is a locale key when blocked.
    Length/charset rules are enforced by callers (registration / options).
    """
    normalized_base = _normalize_base_for_policy(name)
    normalized = normalize_player_name_for_policy(name)
    if not normalized_base and not normalized:
        return True, ""

    if _matches_substring_block(normalized, _EXTREMIST_BLOCKLIST):
        return False, FORBIDDEN_REASON
    if _matches_protected_class_block(normalized_base, normalized):
        return False, FORBIDDEN_REASON
    if _matches_substring_block(normalized, _PROFANITY_BLOCKLIST):
        return False, FORBIDDEN_REASON
    if _matches_numeric_hate_codes(normalized_base):
        return False, FORBIDDEN_REASON
    if _matches_regex_blocklist(normalized, normalized_base):
        return False, FORBIDDEN_REASON

    if _openai_moderation_blocks(str(name or "")):
        return False, FORBIDDEN_REASON

    return True, ""
