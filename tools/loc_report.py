#!/usr/bin/env python3
"""Deterministic Genesis Colonies LOC report.

Counts physical and non-blank lines for source-controlled text files. Generated
assets, locale data, docs and binary files are intentionally excluded from the
code LOC total; tests are reported separately.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".py", ".js", ".css", ".html", ".sql", ".sh", ".ps1", ".yml", ".yaml", ".toml"}
SOURCE_ROOTS = ("game", "templates", "static", "scripts", "migrations", "tools", ".github")
ROOT_SOURCE_FILES = ("app.py", "migrate.py")
SKIP_PARTS = {"node_modules", "__pycache__", ".git", ".pytest_cache", ".venv", "venv"}


def _count(path: Path) -> tuple[int, int]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0, 0
    lines = text.splitlines()
    return len(lines), sum(1 for line in lines if line.strip())


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


def build_report() -> dict:
    categories = defaultdict(lambda: {"files": 0, "physical": 0, "nonblank": 0})
    language = defaultdict(lambda: {"files": 0, "physical": 0, "nonblank": 0})

    for path in _iter_source_files():
        rel = path.relative_to(ROOT)
        physical, nonblank = _count(path)
        if physical <= 0:
            continue
        category = rel.parts[0] if len(rel.parts) > 1 else "root"
        ext = path.suffix.lower().lstrip(".") or "other"
        for bucket in (categories[category], language[ext]):
            bucket["files"] += 1
            bucket["physical"] += physical
            bucket["nonblank"] += nonblank

    tests = {"files": 0, "physical": 0, "nonblank": 0}
    test_root = ROOT / "tests"
    if test_root.exists():
        for path in test_root.rglob("*.py"):
            if any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts):
                continue
            physical, nonblank = _count(path)
            tests["files"] += 1
            tests["physical"] += physical
            tests["nonblank"] += nonblank

    code = {
        "files": sum(v["files"] for v in categories.values()),
        "physical": sum(v["physical"] for v in categories.values()),
        "nonblank": sum(v["nonblank"] for v in categories.values()),
    }
    return {
        "definition": "tracked source text; docs/locales/assets excluded; tests separate",
        "code": code,
        "tests": tests,
        "code_plus_tests": {
            "files": code["files"] + tests["files"],
            "physical": code["physical"] + tests["physical"],
            "nonblank": code["nonblank"] + tests["nonblank"],
        },
        "by_root": dict(sorted(categories.items())),
        "by_extension": dict(sorted(language.items())),
    }


def main() -> None:
    report = build_report()
    print("GENESIS COLONIES LOC")
    print(f"definition: {report['definition']}")
    for key in ("code", "tests", "code_plus_tests"):
        row = report[key]
        print(f"{key}: files={row['files']} physical={row['physical']} nonblank={row['nonblank']}")
    print("by_extension:")
    for ext, row in report["by_extension"].items():
        print(f"  {ext}: files={row['files']} physical={row['physical']} nonblank={row['nonblank']}")
    print("LOC_JSON=" + json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
