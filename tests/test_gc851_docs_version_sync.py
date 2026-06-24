"""GC-851 — Doc / VERSION / migration / pytest-count sync guards."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# P0 — VERSION file must match these canonical meta docs.
VERSION_SYNC_FILES = (
    ROOT / "README.md",
    ROOT / "docs" / "ROADMAP.md",
    ROOT / "docs" / "PROJECT_INVENTORY.md",
)

# P1 — highest SQL migration must match these docs.
MIGRATION_SYNC_FILES = (
    ROOT / "docs" / "ROADMAP.md",
    ROOT / "docs" / "ARCHITECTURE.md",
)

# P1 — documented pytest collection count must match runtime collect-only.
PYTEST_COUNT_SYNC_FILES = (
    ROOT / "README.md",
    ROOT / "docs" / "ROADMAP.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "CONTRIBUTING.md",
    ROOT / "docs" / "WORKFLOW.md",
)

# P2 — stale lies; scan master docs (exclude ticket/audit GC-* docs and CHANGELOG).
P2_DOC_EXCLUDE = re.compile(r"GC-\d", re.I)
P2_FORBIDDEN = (
    ("v1.5.3", re.compile(r"v1\.5\.3", re.I)),
    ("513 Tests", re.compile(r"513\s+Tests", re.I)),
    ("Storage 100k", re.compile(r"Storage\s+100k", re.I)),
    ("No Refund", re.compile(r"No\s+Refund", re.I)),
    ("prepared only", re.compile(r"prepared\s+only", re.I)),
)

VERSION_TOKEN_RE = re.compile(r"v?(?:\d+\.){2,3}\d+")
MIGRATION_RANGE_RE = re.compile(
    r"SQL-Migrationen\s*\([`(]?(\d{3})[`)]?\s*[-–]\s*[`(]?(\d{3})[`)]?\)",
    re.I,
)
MIGRATION_ARCH_RE = re.compile(
    r"migrations/\*\.sql\s*\((\d{3})[-–](\d{3})\)",
    re.I,
)

def _read_version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _migration_high_water() -> int:
    nums: list[int] = []
    for path in (ROOT / "migrations").glob("*.sql"):
        match = re.match(r"^(\d+)_", path.name)
        if match:
            nums.append(int(match.group(1)))
    assert nums, "no migrations/*.sql found"
    return max(nums)


def _pytest_collect_count() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    for line in reversed((result.stdout or "").splitlines()):
        match = re.search(r"(\d+)\s+tests?\s+collected", line, re.I)
        if match:
            return int(match.group(1))
    pytest.fail(f"could not parse pytest collect count:\n{result.stdout}")


def _file_contains_version(text: str, version: str) -> bool:
    return version in text or f"v{version}" in text


def _parse_migration_high(text: str) -> int | None:
    highs: list[int] = []
    for _low, high in MIGRATION_RANGE_RE.findall(text):
        highs.append(int(high))
    for _low, high in MIGRATION_ARCH_RE.findall(text):
        highs.append(int(high))
    return max(highs) if highs else None


def _parse_pytest_count(text: str) -> int | None:
    counts: list[int] = []
    for line in text.splitlines():
        lower = line.lower()
        if not any(token in lower for token in ("pytest", "tests", "gesamt")):
            continue
        for match in re.finditer(r"(\d{3,})\+?", line):
            counts.append(int(match.group(1)))
    return max(counts) if counts else None


def _p2_scan_paths() -> list[Path]:
    paths: list[Path] = [ROOT / "README.md"]
    for path in sorted((ROOT / "docs").glob("*.md")):
        if P2_DOC_EXCLUDE.search(path.name):
            continue
        paths.append(path)
    return paths


def test_gc851_p0_version_file_matches_canonical_docs():
    version = _read_version()
    assert VERSION_TOKEN_RE.fullmatch(version), f"unexpected VERSION format: {version!r}"
    missing = [path.name for path in VERSION_SYNC_FILES if not _file_contains_version(path.read_text(encoding="utf-8"), version)]
    assert not missing, f"VERSION {version!r} missing in: {', '.join(missing)}"


def test_gc851_p1_migration_high_water_matches_docs():
    high = _migration_high_water()
    mismatches: dict[str, int | None] = {}
    for path in MIGRATION_SYNC_FILES:
        documented = _parse_migration_high(path.read_text(encoding="utf-8"))
        if documented != high:
            mismatches[path.name] = documented
    assert not mismatches, f"migrations high-water {high}, doc drift: {mismatches}"


def test_gc851_p1_pytest_collect_count_matches_docs():
    actual = _pytest_collect_count()
    doc_counts = {
        path.name: _parse_pytest_count(path.read_text(encoding="utf-8"))
        for path in PYTEST_COUNT_SYNC_FILES
    }
    assert all(value is not None for value in doc_counts.values()), doc_counts
    unique = set(doc_counts.values())
    assert len(unique) == 1, f"pytest count mismatch across docs: {doc_counts}"
    documented = unique.pop()
    assert actual == documented, f"collect-only={actual}, docs={documented}"


@pytest.mark.parametrize("path", _p2_scan_paths(), ids=lambda p: p.name)
def test_gc851_p2_no_forbidden_legacy_strings(path: Path):
    text = path.read_text(encoding="utf-8")
    hits: list[str] = []
    for label, pattern in P2_FORBIDDEN:
        if pattern.search(text):
            hits.append(label)
    assert not hits, f"{path.relative_to(ROOT)} contains forbidden legacy values: {hits}"
