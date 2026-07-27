"""Neural story TTS via Microsoft Edge voices (edge-tts)."""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import threading
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[2]
_TTS_CACHE = _APP_ROOT / "static" / "uploads" / "story_tts"

# Neural voices — deep / cinematic contact feel (not browser robotic TTS).
_VOICE_BY_LANG = {
    "de": "de-DE-ConradNeural",
    "en": "en-US-GuyNeural",
    "fr": "fr-FR-HenriNeural",
    "es": "es-ES-AlvaroNeural",
    "pl": "pl-PL-MarekNeural",
    "pt": "pt-BR-AntonioNeural",
    "ru": "ru-RU-DmitryNeural",
    "tr": "tr-TR-AhmetNeural",
}

_DEFAULT_VOICE = "de-DE-ConradNeural"
_SYNTH_TIMEOUT_S = 12.0
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="story-tts")
_synth_lock = threading.Lock()


def tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401

        return True
    except Exception:
        return False


def resolve_voice(locale: str | None = None) -> str:
    lang = str(locale or "de").strip().lower().split("-")[0]
    return _VOICE_BY_LANG.get(lang, _DEFAULT_VOICE)


def _cache_path(voice: str, text: str) -> Path:
    digest = hashlib.sha256(f"{voice}\n{text}".encode("utf-8")).hexdigest()
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
    body = " ".join(str(text or "").split()).strip()
    if not body:
        return None, "audio/mpeg", "empty"
    if len(body) > 2500:
        body = body[:2500]

    if not tts_available():
        return None, "audio/mpeg", "edge_tts_missing"

    chosen = str(voice or "").strip() or resolve_voice(locale)
    path = _cache_path(chosen, body)
    try:
        if path.is_file() and path.stat().st_size > 64:
            return path.read_bytes(), "audio/mpeg", None
    except OSError:
        pass

    try:
        fut = _executor.submit(_edge_synthesize_sync, body, chosen)
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


def _edge_synthesize_sync(text: str, voice: str) -> bytes:
    import asyncio

    async def _run() -> bytes:
        import edge_tts

        # Deep, cinematic contact timbre — slower + lower than default neural.
        communicate = edge_tts.Communicate(
            text,
            voice=voice,
            rate="-14%",
            pitch="-10Hz",
            volume="+12%",
        )
        chunks: list[bytes] = []
        async for item in communicate.stream():
            if item.get("type") == "audio" and item.get("data"):
                chunks.append(item["data"])
        return b"".join(chunks)

    return asyncio.run(_run())
