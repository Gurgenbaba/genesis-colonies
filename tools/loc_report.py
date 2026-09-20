#!/usr/bin/env python3
"""Deterministic Genesis Colonies LOC/SLOC report.

Counts physical, non-blank and comment-stripped source lines for source-controlled
text files. Generated assets, locale data, docs and binary files are intentionally
excluded from the code LOC total; tests are reported separately.

SLOC intentionally keeps Python docstrings and inline-comment code lines as code.
It removes blank lines plus lines that are comments only.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".py", ".js", ".css", ".html", ".sql", ".sh", ".ps1", ".yml", ".yaml", ".toml"}
SOURCE_ROOTS = ("game", "templates", "static", "scripts", "migrations", "tools", ".github")
ROOT_SOURCE_FILES = ("app.py", "migrate.py")
RUNTIME_ROOTS = {"game", "templates", "static", "migrations", "root"}
DEV_ROOTS = {"scripts", "tools", ".github"}
SKIP_PARTS = {"node_modules", "__pycache__", ".git", ".pytest_cache", ".venv", "venv"}


def _count(path: Path) -> tuple[int, int]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0, 0
    lines = text.splitlines()
    return len(lines), sum(1 for line in lines if line.strip())


def _line_has_code(stripped: str, *, ext: str, in_block: str | None) -> tuple[bool, str | None]:
    """Return whether a non-blank line contains code and updated block-comment state."""
    if not stripped:
        return False, in_block

    block_pairs: tuple[tuple[str, str], ...] = ()
    line_markers: tuple[str, ...] = ()
    if ext == ".py":
        line_markers = ("#",)
    elif ext in {".sh", ".ps1", ".yml", ".yaml", ".toml"}:
        line_markers = ("#",)
    elif ext in {".js", ".css"}:
        line_markers = ("//",) if ext == ".js" else ()
        block_pairs = (("/*", "*/"),)
    elif ext == ".sql":
        line_markers = ("--",)
        block_pairs = (("/*", "*/"),)
    elif ext == ".html":
        block_pairs = (("<!--", "-->"), ("{#", "#}"))

    remaining = stripped
    while True:
        if in_block:
            end = in_block
            pos = remaining.find(end)
            if pos < 0:
                return False, in_block
            remaining = remaining[pos + len(end) :].lstrip()
            in_block = None
            if not remaining:
                return False, None
            continue

        if any(remaining.startswith(marker) for marker in line_markers):
            return False, None

        started_block = False
        for start, end in block_pairs:
            if remaining.startswith(start):
                pos = remaining.find(end, len(start))
                if pos < 0:
                    return False, end
                remaining = remaining[pos + len(end) :].lstrip()
                started_block = True
                break
        if started_block:
            if not remaining:
                return False, None
            continue

        return True, None


def _count_sloc(path: Path) -> int:
    """Count non-blank lines that are not comment-only lines."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    ext = path.suffix.lower()
    sloc = 0
    in_block: str | None = None
    for line in text.splitlines():
        has_code, in_block = _line_has_code(line.lstrip(), ext=ext, in_block=in_block)
        if has_code:
            sloc += 1
    return sloc


def _iter_source_files():
    seen: set[Path] = set()
    for root_name in SOURCE_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            rel = path.relative_to(ROOT)
            if any(part in SKIP_PARTS for part in rel.parts):
                continue
            if rel.parts and rel.parts[0] == "static" and any(
                part in {"img", "audio", "fonts"} for part in rel.parts[1:]
            ):
                continue
            if path not in seen:
                seen.add(path)
                yield path
    for name in ROOT_SOURCE_FILES:
        path = ROOT / name
        if path.exists() and path not in seen:
            yield path


def _empty_bucket() -> dict[str, int]:
    return {"files": 0, "physical": 0, "nonblank": 0, "sloc": 0}


def _add(bucket: dict[str, int], *, physical: int, nonblank: int, sloc: int) -> None:
    bucket["files"] += 1
    bucket["physical"] += physical
    bucket["nonblank"] += nonblank
    bucket["sloc"] += sloc


def build_report() -> dict:
    categories = defaultdict(_empty_bucket)
    language = defaultdict(_empty_bucket)
    runtime = _empty_bucket()
    dev = _empty_bucket()
    files: list[dict[str, int | str]] = []

    for path in _iter_source_files():
        rel = path.relative_to(ROOT)
        physical, nonblank = _count(path)
        if physical <= 0:
            continue
        sloc = _count_sloc(path)
        category = rel.parts[0] if len(rel.parts) > 1 else "root"
        ext = path.suffix.lower().lstrip(".") or "other"
        _add(categories[category], physical=physical, nonblank=nonblank, sloc=sloc)
        _add(language[ext], physical=physical, nonblank=nonblank, sloc=sloc)
        target = runtime if category in RUNTIME_ROOTS else dev if category in DEV_ROOTS else None
        if target is not None:
            _add(target, physical=physical, nonblank=nonblank, sloc=sloc)
        files.append({"path": rel.as_posix(), "physical": physical, "nonblank": nonblank, "sloc": sloc})

    tests = _empty_bucket()
    test_root = ROOT / "tests"
    if test_root.exists():
        for path in test_root.rglob("*.py"):
            if any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts):
                continue
            physical, nonblank = _count(path)
            sloc = _count_sloc(path)
            _add(tests, physical=physical, nonblank=nonblank, sloc=sloc)

    code = _empty_bucket()
    for row in categories.values():
        for key in code:
            code[key] += row[key]

    top_runtime = sorted(
        (
            row
            for row in files
            if (row["path"].split("/", 1)[0] if "/" in row["path"] else "root") in RUNTIME_ROOTS
        ),
        key=lambda row: (-int(row["sloc"]), str(row["path"])),
    )[:25]

    return {
        "definition": "tracked source text; docs/locales/assets excluded; tests separate; sloc removes blank/comment-only lines",
        "code": code,
        "runtime": runtime,
        "dev_scripts": dev,
        "tests": tests,
        "code_plus_tests": {key: code[key] + tests[key] for key in code},
        "by_root": dict(sorted(categories.items())),
        "by_extension": dict(sorted(language.items())),
        "top_runtime_files": top_runtime,
    }


def main() -> None:
    report = build_report()
    print("GENESIS COLONIES LOC/SLOC")
    print(f"definition: {report['definition']}")
    for key in ("code", "runtime", "dev_scripts", "tests", "code_plus_tests"):
        row = report[key]
        print(
            f"{key}: files={row['files']} physical={row['physical']} "
            f"nonblank={row['nonblank']} sloc={row['sloc']}"
        )
    print("by_extension:")
    for ext, row in report["by_extension"].items():
        print(
            f"  {ext}: files={row['files']} physical={row['physical']} "
            f"nonblank={row['nonblank']} sloc={row['sloc']}"
        )
    print("top_runtime_files:")
    for row in report["top_runtime_files"][:10]:
        print(f"  {row['sloc']:>7} sloc  {row['physical']:>7} physical  {row['path']}")
    print("LOC_JSON=" + json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
