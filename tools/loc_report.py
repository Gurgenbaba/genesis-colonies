#!/usr/bin/env python3
"""Deterministic Genesis Colonies LOC/SLOC report.

Counts physical, non-blank and comment-aware source lines for source-controlled
text files. Generated assets, locale data, docs and binary files are excluded
from the code total; tests are reported separately.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from pygments import lex
from pygments.lexers import HtmlDjangoLexer, get_lexer_for_filename
from pygments.util import ClassNotFound
from pygments.token import Comment

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".py", ".js", ".css", ".html", ".sql", ".sh", ".ps1", ".yml", ".yaml", ".toml"}
SOURCE_ROOTS = ("game", "templates", "static", "scripts", "migrations", "tools", ".github")
ROOT_SOURCE_FILES = ("app.py", "migrate.py")
SKIP_PARTS = {"node_modules", "__pycache__", ".git", ".pytest_cache", ".venv", "venv"}


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _lexer_for(path: Path, text: str):
    rel = path.relative_to(ROOT)
    if rel.parts and rel.parts[0] == "templates" and path.suffix.lower() == ".html":
        return HtmlDjangoLexer()
    try:
        return get_lexer_for_filename(path.name, text)
    except ClassNotFound:
        return None


def _count(path: Path) -> dict[str, int]:
    text = _read(path)
    if text is None:
        return {"physical": 0, "nonblank": 0, "sloc": 0, "comments": 0, "blanks": 0}
    lines = text.splitlines()
    physical = len(lines)
    nonblank = sum(1 for line in lines if line.strip())
    if not text or physical == 0:
        return {"physical": physical, "nonblank": nonblank, "sloc": 0, "comments": 0, "blanks": physical}

    lexer = _lexer_for(path, text)
    if lexer is None:
        return {
            "physical": physical,
            "nonblank": nonblank,
            "sloc": nonblank,
            "comments": 0,
            "blanks": physical - nonblank,
        }

    code_lines: set[int] = set()
    comment_lines: set[int] = set()
    line_no = 1
    for token_type, value in lex(text, lexer):
        for piece in value.splitlines(keepends=True):
            body = piece.rstrip("\r\n")
            if body.strip():
                if token_type in Comment:
                    comment_lines.add(line_no)
                else:
                    code_lines.add(line_no)
            if piece.endswith(("\n", "\r")):
                line_no += 1

    comment_only = comment_lines - code_lines
    classified = code_lines | comment_lines
    blanks = max(0, physical - len(classified))
    return {
        "physical": physical,
        "nonblank": nonblank,
        "sloc": len(code_lines),
        "comments": len(comment_only),
        "blanks": blanks,
    }


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
    return {"files": 0, "physical": 0, "nonblank": 0, "sloc": 0, "comments": 0, "blanks": 0}


def _add(bucket: dict[str, int], counts: dict[str, int]) -> None:
    bucket["files"] += 1
    for key in ("physical", "nonblank", "sloc", "comments", "blanks"):
        bucket[key] += counts[key]


def build_report() -> dict:
    categories = defaultdict(_empty_bucket)
    language = defaultdict(_empty_bucket)
    source_files: list[dict] = []

    for path in _iter_source_files():
        rel = path.relative_to(ROOT)
        counts = _count(path)
        if counts["physical"] <= 0:
            continue
        category = rel.parts[0] if len(rel.parts) > 1 else "root"
        ext = path.suffix.lower().lstrip(".") or "other"
        _add(categories[category], counts)
        _add(language[ext], counts)
        source_files.append({"path": str(rel).replace("\\", "/"), "ext": ext, **counts})

    tests = _empty_bucket()
    test_files: list[dict] = []
    test_root = ROOT / "tests"
    if test_root.exists():
        for path in test_root.rglob("*.py"):
            if any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts):
                continue
            counts = _count(path)
            _add(tests, counts)
            test_files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "ext": "py", **counts})

    code = _empty_bucket()
    for bucket in categories.values():
        code["files"] += bucket["files"]
        for key in ("physical", "nonblank", "sloc", "comments", "blanks"):
            code[key] += bucket[key]

    plus = _empty_bucket()
    for key in plus:
        plus[key] = code[key] + tests[key]

    return {
        "definition": "tracked source text; docs/locales/assets excluded; tests separate; SLOC excludes blank and comment-only lines",
        "code": code,
        "tests": tests,
        "code_plus_tests": plus,
        "by_root": dict(sorted(categories.items())),
        "by_extension": dict(sorted(language.items())),
        "top_code_files": sorted(source_files, key=lambda row: row["sloc"], reverse=True)[:40],
        "top_test_files": sorted(test_files, key=lambda row: row["sloc"], reverse=True)[:25],
    }


def _print_row(prefix: str, row: dict) -> None:
    print(
        f"{prefix}: files={row['files']} physical={row['physical']} "
        f"nonblank={row['nonblank']} sloc={row['sloc']} "
        f"comments={row['comments']} blanks={row['blanks']}"
    )


def main() -> None:
    report = build_report()
    print("GENESIS COLONIES LOC/SLOC")
    print(f"definition: {report['definition']}")
    for key in ("code", "tests", "code_plus_tests"):
        _print_row(key, report[key])
    print("by_extension:")
    for ext, row in report["by_extension"].items():
        _print_row(f"  {ext}", row)
    print("by_root:")
    for root, row in report["by_root"].items():
        _print_row(f"  {root}", row)
    print("top_code_files_by_sloc:")
    for row in report["top_code_files"]:
        print(f"  {row['sloc']:6d} sloc | {row['physical']:6d} lines | {row['path']}")
    print("top_test_files_by_sloc:")
    for row in report["top_test_files"]:
        print(f"  {row['sloc']:6d} sloc | {row['physical']:6d} lines | {row['path']}")
    print("LOC_JSON=" + json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
