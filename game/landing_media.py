"""Landing marketing media manifest (static/img/landing/).

Resolves optional hero video, screenshot gallery, and moment loops from disk.
Missing files → empty lists / None so the landing page falls back to CSS FX.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LANDING_DIR = ROOT / "static" / "img" / "landing"

SHOT_SPECS: list[tuple[str, str]] = [
    ("shot-01-overview", "landing_shot_overview"),
    ("shot-02-galaxy", "landing_shot_galaxy"),
    ("shot-03-world-boss", "landing_shot_world_boss"),
    ("shot-04-fleet", "landing_shot_fleet"),
    ("shot-05-inventory", "landing_shot_inventory"),
    ("shot-06-empire", "landing_shot_empire"),
    ("shot-07-story", "landing_shot_story"),
    ("shot-08-politics", "landing_shot_politics"),
    ("shot-09-titans", "landing_shot_titans"),
    ("shot-10-auctions", "landing_shot_auctions"),
    ("shot-11-research", "landing_shot_research"),
    ("shot-12-commander", "landing_shot_commander"),
]

MOMENT_SPECS: list[tuple[str, str]] = [
    ("moment-01-resources", "landing_moment_resources"),
    ("moment-02-build", "landing_moment_build"),
    ("moment-03-fleet", "landing_moment_fleet"),
    ("moment-04-boss", "landing_moment_boss"),
    ("moment-05-loot", "landing_moment_loot"),
]

_IMAGE_EXTS = (".webp", ".png", ".jpg", ".jpeg")
_VIDEO_EXTS = (".webm", ".mp4")


def _static_rel(path: Path, landing_dir: Path) -> str:
    """Path relative to static/ for url_for('static', filename=...).

    When resolving a custom landing_dir (tests), map files as if they lived under
    static/img/landing/ so templates keep working without copying fixtures.
    """
    static_root = ROOT / "static"
    try:
        return path.relative_to(static_root).as_posix()
    except ValueError:
        rel = path.relative_to(landing_dir).as_posix()
        return f"img/landing/{rel}"


def _first_existing(directory: Path, stem: str, exts: tuple[str, ...]) -> Path | None:
    for ext in exts:
        candidate = directory / f"{stem}{ext}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _collect_sources(
    directory: Path, stem: str, exts: tuple[str, ...], landing_dir: Path
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for ext in exts:
        candidate = directory / f"{stem}{ext}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            mime = "video/webm" if ext == ".webm" else "video/mp4"
            out.append({"src": _static_rel(candidate, landing_dir), "type": mime})
    return out


def resolve_landing_media(landing_dir: Path | None = None) -> dict[str, Any]:
    """Build template-ready media dict. Safe if the folder is missing."""
    base = Path(landing_dir) if landing_dir is not None else LANDING_DIR
    shots_dir = base / "shots"
    moments_dir = base / "moments"

    hero_sources = _collect_sources(base, "hero", _VIDEO_EXTS, base)
    poster = _first_existing(base, "hero-poster", _IMAGE_EXTS)
    trailer_sources = _collect_sources(base, "trailer", _VIDEO_EXTS, base)

    shots: list[dict[str, str]] = []
    for stem, label_key in SHOT_SPECS:
        img = _first_existing(shots_dir, stem, _IMAGE_EXTS)
        if img is None:
            continue
        shots.append(
            {
                "stem": stem,
                "src": _static_rel(img, base),
                "label_key": label_key,
            }
        )

    moments: list[dict[str, Any]] = []
    for stem, label_key in MOMENT_SPECS:
        sources = _collect_sources(moments_dir, stem, _VIDEO_EXTS, base)
        gif = _first_existing(moments_dir, stem, (".gif",) + _IMAGE_EXTS)
        if not sources and gif is None:
            continue
        entry: dict[str, Any] = {"stem": stem, "label_key": label_key, "sources": sources}
        if gif is not None:
            entry["img"] = _static_rel(gif, base)
        moments.append(entry)

    return {
        "hero": {
            "sources": hero_sources,
            "poster": _static_rel(poster, base) if poster else None,
            "has_video": bool(hero_sources),
        },
        "trailer": {
            "sources": trailer_sources,
            "has_video": bool(trailer_sources),
        },
        "shots": shots,
        "shot_by_stem": {s["stem"]: s for s in shots},
        "moments": moments,
        "has_shots": bool(shots),
        "has_moments": bool(moments),
    }
