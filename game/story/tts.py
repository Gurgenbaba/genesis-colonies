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
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TTS_CACHE = _APP_ROOT / "static" / "uploads" / "story_tts"

# Cache/prosody revision — bump to invalidate broken caches (v5 smileys on G:S:P).
_STYLE_VERSION = "v6"

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

# Railway / cold Microsoft endpoints can exceed 18s on longer beats.
_SYNTH_TIMEOUT_S = float(os.environ.get("STORY_TTS_TIMEOUT_S") or "45")
_SYNTH_RETRIES = max(1, int(os.environ.get("STORY_TTS_RETRIES") or "2"))
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

# Edge voices treat ":P" / ":S:" as smileys — expand coordinate notation for speech.
_GSP_SPEAK = {
    "de": "Galaxie System Position",
    "en": "galaxy system position",
    "fr": "galaxie système position",
    "es": "galaxia sistema posición",
    "pl": "galaktyka układ pozycja",
    "pt": "galáxia sistema posição",
    "ru": "галактика система позиция",
    "tr": "galaksi sistem pozisyon",
}

_RE_GSP_LETTER = re.compile(
    r"\[?\s*[GgГг]\s*:\s*[SsСс]\s*:\s*[PpПп]\s*\]?",
)
_RE_GSP_NUMERIC_BRACKET = re.compile(r"\[(\d{1,4}):(\d{1,4}):(\d{1,4})\]")
_RE_GSP_NUMERIC_BARE = re.compile(r"\b(\d{1,4}):(\d{1,4}):(\d{1,4})\b")


def _speak_numeric_coord(g: str, s: str, p: str, *, lang: str) -> str:
    if lang == "de":
        return f"{g} zu {s} zu {p}"
    return f"{g}, {s}, {p}"


def _expand_coords_for_speech(body: str, *, lang: str) -> str:
    """Rewrite [G:S:P] / numeric coords so TTS does not read colon-emoticons."""
    gsp = _GSP_SPEAK.get(lang) or _GSP_SPEAK["en"]
    out = _RE_GSP_LETTER.sub(gsp, body)

    def _num(m: re.Match[str]) -> str:
        return _speak_numeric_coord(m.group(1), m.group(2), m.group(3), lang=lang)

    out = _RE_GSP_NUMERIC_BRACKET.sub(_num, out)
    out = _RE_GSP_NUMERIC_BARE.sub(_num, out)
    return out


def tts_cache_dir() -> Path:
    """Prefer durable volume cache on Railway (`GC_DB_PATH` parent) over image FS."""
    override = str(os.environ.get("GC_TTS_CACHE_DIR") or "").strip()
    if override:
        return Path(override)
    db_path = str(os.environ.get("GC_DB_PATH") or "").strip()
    if db_path:
        try:
            return Path(db_path).expanduser().resolve().parent / "story_tts"
        except OSError:
            pass
    return _DEFAULT_TTS_CACHE


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

    # Preserve numeric ranges (1–15) before dash→comma; else TTS says "1, 15".
    lang_early = str(locale or "de").strip().lower().split("-")[0]
    range_word = "bis" if lang_early == "de" else "to"
    raw = re.sub(
        rf"(\d+)\s*[—–-]\s*(\d+)",
        rf"\1 {range_word} \2",
        raw,
    )

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
    body = _expand_coords_for_speech(body, lang=lang)
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
    return tts_cache_dir() / f"{digest}.mp3"


def synthesize_mp3(
    text: str,
    *,
    locale: str | None = None,
    voice: str | None = None,
) -> Tuple[Optional[bytes], str, Optional[str]]:
    """
    Return (mp3_bytes, mime, error).
    Uses on-disk cache (volume-backed when GC_DB_PATH is set).
    Synthesis runs in a worker thread with timeout + one retry so Flask is not wedged.
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

    last_err = "tts_failed"
    audio: Optional[bytes] = None
    for attempt in range(1, _SYNTH_RETRIES + 1):
        try:
            fut = _executor.submit(_edge_synthesize_sync, body, chosen, rate, pitch, volume)
            audio = fut.result(timeout=_SYNTH_TIMEOUT_S)
            if audio:
                break
            last_err = "empty_audio"
        except concurrent.futures.TimeoutError:
            last_err = "tts_timeout"
            logger.warning(
                "story tts timeout voice=%s attempt=%s/%s",
                chosen,
                attempt,
                _SYNTH_RETRIES,
            )
        except Exception as exc:
            last_err = f"tts_failed:{exc.__class__.__name__}"
            logger.exception(
                "story tts failed voice=%s attempt=%s/%s",
                chosen,
                attempt,
                _SYNTH_RETRIES,
            )
        if attempt < _SYNTH_RETRIES:
            time.sleep(0.35 * attempt)

    if not audio:
        return None, "audio/mpeg", last_err

    try:
        with _synth_lock:
            cache_dir = tts_cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                path.write_bytes(audio)
    except OSError:
        logger.exception("story tts cache write failed dir=%s", tts_cache_dir())

    return audio, "audio/mpeg", None


def _edge_synthesize_sync(text: str, voice: str, rate: str, pitch: str, volume: str) -> bytes:
    """Run edge-tts on a fresh event loop (safe under gunicorn worker threads)."""
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

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_run())
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass
