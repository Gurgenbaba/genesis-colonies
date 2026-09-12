#!/usr/bin/env python3
"""Read-only maintainability audit for Genesis Colonies.

This tool intentionally does not delete, rewrite, or label code as dead. It reports
high-confidence structural signals that are useful before a targeted refactor:
large runtime files, exact duplicate Python function bodies, and explicit legacy /
SQLite compatibility markers.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import loc_report

ROOT = loc_report.ROOT
RUNTIME_PREFIXES = ("game/", "templates/", "static/", "migrations/")
ROOT_RUNTIME = {"app.py", "migrate.py"}
LEGACY_PATTERNS = {
    "sqlite": re.compile(r"\bsqlite(?:3)?\b", re.IGNORECASE),
    "legacy": re.compile(r"\blegacy\b", re.IGNORECASE),
    "deprecated": re.compile(r"\bdeprecated\b", re.IGNORECASE),
    "compat": re.compile(r"\b(?:compat|compatibility|backward-compatible|backwards-compatible)\b", re.IGNORECASE),
    "fallback": re.compile(r"\bfallback\b", re.IGNORECASE),
}


def _is_runtime_path(rel: str) -> bool:
    return rel in ROOT_RUNTIME or rel.startswith(RUNTIME_PREFIXES)


def _runtime_files() -> list[Path]:
    result = []
    for path in loc_report._iter_source_files():
        rel = path.relative_to(ROOT).as_posix()
        if _is_runtime_path(rel):
            result.append(path)
    return result


def _node_sloc(node: ast.AST) -> int:
    start = int(getattr(node, "lineno", 0) or 0)
    end = int(getattr(node, "end_lineno", start) or start)
    return max(0, end - start + 1)


def exact_python_duplicate_functions(paths: Iterable[Path], *, min_lines: int = 8) -> list[dict]:
    """Find exact AST-identical function bodies; candidates only, not deletion claims."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for path in paths:
        if path.suffix.lower() != ".py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue

        def walk(body: list[ast.stmt], scope: list[str]) -> None:
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    line_count = _node_sloc(node)
                    if line_count >= min_lines and node.body:
                        body_dump = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
                        digest = hashlib.sha256(body_dump.encode("utf-8")).hexdigest()
                        groups[digest].append(
                            {
                                "path": path.relative_to(ROOT).as_posix(),
                                "qualname": ".".join([*scope, node.name]),
                                "line": int(node.lineno),
                                "lines": line_count,
                            }
                        )
                    walk(node.body, [*scope, node.name])
                elif isinstance(node, ast.ClassDef):
                    walk(node.body, [*scope, node.name])

        walk(tree.body, [])

    candidates = []
    for digest, items in groups.items():
        unique_sites = {(item["path"], item["qualname"], item["line"]) for item in items}
        if len(unique_sites) < 2:
            continue
        candidates.append(
            {
                "fingerprint": digest[:12],
                "copies": len(items),
                "lines_each": max(int(item["lines"]) for item in items),
                "sites": sorted(items, key=lambda item: (item["path"], item["line"])),
            }
        )
    return sorted(candidates, key=lambda row: (-row["lines_each"] * row["copies"], row["fingerprint"]))


def marker_hits(paths: Iterable[Path], *, max_examples_per_marker: int = 30) -> dict[str, dict]:
    totals = {key: {"count": 0, "files": set(), "examples": []} for key in LEGACY_PATTERNS}
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for line_no, line in enumerate(lines, start=1):
            for key, pattern in LEGACY_PATTERNS.items():
                if not pattern.search(line):
                    continue
                row = totals[key]
                row["count"] += 1
                row["files"].add(rel)
                if len(row["examples"]) < max_examples_per_marker:
                    row["examples"].append({"path": rel, "line": line_no, "text": line.strip()[:220]})
    return {
        key: {"count": row["count"], "files": len(row["files"]), "examples": row["examples"]}
        for key, row in totals.items()
    }


def build_audit(*, top_n: int = 25) -> dict:
    files = _runtime_files()
    metrics = []
    for path in files:
        physical, nonblank = loc_report._count(path)
        sloc = loc_report._count_sloc(path)
        metrics.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "physical": physical,
                "nonblank": nonblank,
                "sloc": sloc,
            }
        )
    metrics.sort(key=lambda row: (-row["sloc"], row["path"]))
    py_paths = [path for path in files if path.suffix.lower() == ".py"]
    return {
        "definition": (
            "read-only candidate audit; exact Python duplicate bodies are structural matches only; "
            "marker hits require human review; no dead-code claim is made"
        ),
        "runtime_files": len(files),
        "top_runtime_files": metrics[:top_n],
        "exact_python_duplicate_bodies": exact_python_duplicate_functions(py_paths),
        "legacy_markers": marker_hits(files),
    }


def main() -> None:
    report = build_audit()
    print("GENESIS COLONIES CODE DIET AUDIT")
    print(report["definition"])
    print("largest runtime files:")
    for row in report["top_runtime_files"][:15]:
        print(f"  {row['sloc']:>7} sloc  {row['physical']:>7} physical  {row['path']}")
    dupes = report["exact_python_duplicate_bodies"]
    print(f"exact Python duplicate-body groups (>=8 lines): {len(dupes)}")
    for group in dupes[:10]:
        sites = ", ".join(f"{site['path']}:{site['line']}:{site['qualname']}" for site in group["sites"])
        print(f"  {group['copies']}x ~{group['lines_each']} lines [{group['fingerprint']}] {sites}")
    print("legacy/compatibility markers:")
    for key, row in report["legacy_markers"].items():
        print(f"  {key}: hits={row['count']} files={row['files']}")
    print("CODE_DIET_JSON=" + json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
