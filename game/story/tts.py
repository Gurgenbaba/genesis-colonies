"""Neural story TTS via Microsoft Edge voices (edge-tts).

Contact-channel narration: preserve paragraph rhythm, light cinematic prosody,
modern neural voices (plain text — no SSML wrapping that mangled Killian).
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[2]
_TTS_CACHE = _APP_ROOT / "static" / "uploads" / "story_tts"

# Cache/prosody revision — bump to invalidate broken v4 SSML caches.
_STYLE_VERSION = "v5"

# Modern contact voices — clear, cinematic; avoid over-slow/deep mud.
_VOICE_BY_LANG = {
    "de": "de-DE-KillianNeural",
    "en": "en-US-ChristopherNeural",
    "fr": "fr-FR-HenriNeural",
    "es": "es-ES-AlvaroNeural",
    "pl": "pl-PL-MarekNeural",
    "pt": "pt-BR-AntonioNeural",
    "ru": "ru-RU-DmitryNeural",
    "tr": "tr-TR-AhmetNeural",
}

_DEFAULT_VOICE = "de-DE-KillianNeural"

# Proven Killian settings (v3) — plain Communicate rate/pitch, no SSML.
_DEFAULT_RATE = "-6%"
_DEFAULT_PITCH = "-3Hz"
_DEFAULT_VOLUME = "+0%"

_SYNTH_TIMEOUT_S = 18.0
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="story-tts")
_synth_lock = threading.Lock()

# Lore terms German TTS often mangles — longer phrases first.
_DE_PRONUNCE = (
    (re.compile(r"\bSeed[\s-]?Ark\b", re.I), "Seed-Ark"),
    (re.compile(r"\bGenesis[\s-]?Ark\b", re.I), "Genesis-Ark"),
    (re.compile(r"\bLiving[\s-]?Lattice\b", re.I), "Living Lättis"),
    (re.compile(r"\bFree[\s-]?Shop\b", re.I), "Free Shop"),
    (re.compile(r"\bStory[\s-]?Ops\b", re.I), "Story Ops"),
    (re.compile(r"\bLattice\b", re.I), "Lättis"),
    (re.compile(r"\bArk\b"), "Ark"),
    (re.compile(r"\bAndrogyn\b", re.I), "Androgyn"),
    (re.compile(r"\bImperium\b", re.I), "Imperium"),
    (re.compile(r"\bTimekeeper\b", re.I), "Timekeeper"),
    (re.compile(r"\bDNA\b"), "D N A"),
    (re.compile(r"\bPE\b"), "Planet Evolution"),
    (re.compile(r"\bROI\b"), "R O I"),
)


def tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401

        return True
    except Exception:
        return False


def resolve_voice(locale: str | None = None) -> str:
    override = str(os.environ.get("STORY_TTS_VOICE") or "").strip()
    if override:
        return override
    lang = str(locale or "de").strip().lower().split("-")[0]
    return _VOICE_BY_LANG.get(lang, _DEFAULT_VOICE)


def _prosody_params() -> tuple[str, str, str]:
    rate = str(os.environ.get("STORY_TTS_RATE") or _DEFAULT_RATE).strip() or _DEFAULT_RATE
    pitch = str(os.environ.get("STORY_TTS_PITCH") or _DEFAULT_PITCH).strip() or _DEFAULT_PITCH
    volume = str(os.environ.get("STORY_TTS_VOLUME") or _DEFAULT_VOLUME).strip() or _DEFAULT_VOLUME
    return rate, pitch, volume


def prepare_contact_script(text: str, *, locale: str | None = None) -> str:
    """Shape lore text for natural neural narration (pauses, pronunciation)."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ""

    # Normalize fancy dashes / bullets — keep as short pause via spaced en-dash,
    # which Killian handles better than reading "Gedankenstrich".
    raw = raw.replace("—", ", ").replace("–", ", ").replace("•", "")
    raw = re.sub(r"[ \t]+", " ", raw)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    chunks: list[str] = []
    for para in paragraphs:
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        joined = " ".join(lines)
        joined = re.sub(r"\s{2,}", " ", joined).strip()
        if joined:
            chunks.append(joined)

    # Paragraph pause: ellipsis works reliably with plain edge-tts (no SSML).
    body = " … ".join(chunks)
    body = re.sub(r"\s+([,.;:!?])", r"\1", body)
    body = re.sub(r"([.!?])\s*\1+", r"\1", body)
    body = re.sub(r"\s{2,}", " ", body).strip()

    lang = str(locale or "de").strip().lower().split("-")[0]
    if lang == "de":
        for pattern, repl in _DE_PRONUNCE:
            body = pattern.sub(repl, body)

    if len(body) > 2500:
        cut = body[:2500]
        m = re.search(r"^(.*[.!?…])\s", cut)
        body = (m.group(1) if m else cut).rstrip() + " …"

    return body


def _cache_path(voice: str, text: str, rate: str, pitch: str, volume: str) -> Path:
    digest = hashlib.sha256(
        f"{_STYLE_VERSION}|{voice}|{rate}|{pitch}|{volume}\n{text}".encode("utf-8")
    ).hexdigest()
    return _TTS_CACHE / f"{digest}.mp3"


def synthesize_mp3(
    text: str,
    *,
    locale: str | None = None,
    voice: str | None = None,
) -> Tuple[Optional[bytes], str, Optional[str]]:
    """
    Return (mp3_bytes, mime, error).
    Uses on-disk cache under static/uploads/story_tts/.
    Synthesis runs in a worker thread with timeout so Flask is not wedged.
    """
    body = prepare_contact_script(text, locale=locale)
    if not body:
        return None, "audio/mpeg", "empty"

    if not tts_available():
        return None, "audio/mpeg", "edge_tts_missing"

    chosen = str(voice or "").strip() or resolve_voice(locale)
    rate, pitch, volume = _prosody_params()
    path = _cache_path(chosen, body, rate, pitch, volume)
    try:
        if path.is_file() and path.stat().st_size > 64:
            return path.read_bytes(), "audio/mpeg", None
    except OSError:
        pass

    try:
        fut = _executor.submit(_edge_synthesize_sync, body, chosen, rate, pitch, volume)
        audio = fut.result(timeout=_SYNTH_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        logger.warning("story tts timeout voice=%s", chosen)
        return None, "audio/mpeg", "tts_timeout"
    except Exception as exc:
        logger.exception("story tts failed voice=%s", chosen)
        return None, "audio/mpeg", f"tts_failed:{exc.__class__.__name__}"

    if not audio:
        return None, "audio/mpeg", "empty_audio"

    try:
        with _synth_lock:
            _TTS_CACHE.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                path.write_bytes(audio)
    except OSError:
        logger.exception("story tts cache write failed")

    return audio, "audio/mpeg", None


def _edge_synthesize_sync(text: str, voice: str, rate: str, pitch: str, volume: str) -> bytes:
    import asyncio

    async def _run() -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(
            text,
            voice=voice,
            rate=rate,
            pitch=pitch,
            volume=volume,
        )
        chunks: list[bytes] = []
        async for item in communicate.stream():
            if item.get("type") == "audio" and item.get("data"):
                chunks.append(item["data"])
        return b"".join(chunks)

    return asyncio.run(_run())
