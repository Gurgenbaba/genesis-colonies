"""Keep UNI1-only migration numbers (183/184) from being reused or copied to main.

See docs/MIGRATION_NUMBER_RESERVATIONS.md. Migrations are tracked by file name,
so a reused number does not fail by itself; this guard makes the intent explicit.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"

RESERVED_UNI1_ONLY = {
    183: "183_trader_hub_dev_parity.sql",
    184: "184_uni1_admin_speed_profile.sql",
}
# Numbers that already had two files before the reservation was introduced.
LEGACY_DUPLICATES = {65}


def _by_number() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for path in MIGRATIONS.glob("*.sql"):
        match = re.match(r"(\d+)_", path.name)
        assert match, f"migration without numeric prefix: {path.name}"
        out.setdefault(int(match.group(1)), []).append(path.name)
    return out


def _target_branch() -> str:
    # A PR checks out a detached merge ref, so use its BASE branch, not its
    # temporary GITHUB_REF_NAME. On push use the real pushed branch.
    for name in ("GC_MIGRATION_TEST_BRANCH", "GITHUB_BASE_REF", "GITHUB_REF_NAME"):
        value = os.environ.get(name, "").strip()
        if value:
            return value.removeprefix("refs/heads/")
    local = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # Fail closed on an unknown/detached local checkout: never allow the
    # UNI1-only migrations unless the target is explicitly UNI1.
    return local.stdout.strip() or "main"


def _check_reserved_numbers(numbers: dict[int, list[str]], *, is_uni1: bool) -> None:
    for number, name in RESERVED_UNI1_ONLY.items():
        present = set(numbers.get(number, []))
        if is_uni1:
            assert present == {name}, (
                f"UNI1 must keep its reserved migration {name}, found {sorted(present)}"
            )
        else:
            assert not present, (
                f"{name} is UNI1-only and must never be copied to main/DEV; "
                f"found {sorted(present)}. Use migration number 185+ instead"
            )


def test_reserved_numbers_only_hold_the_reserved_uni1_files():
    _check_reserved_numbers(
        _by_number(),
        is_uni1=_target_branch() == "u2/staging-runtime",
    )


def test_guard_rejects_copying_real_uni1_migrations_to_main():
    # A matching *filename* is dangerous on main as well; merely checking
    # that the reserved number holds the expected name cannot protect DEV.
    with pytest.raises(AssertionError):
        _check_reserved_numbers(
            {n: [name] for n, name in RESERVED_UNI1_ONLY.items()},
            is_uni1=False,
        )


def test_guard_accepts_reserved_files_only_on_uni1():
    _check_reserved_numbers(
        {n: [name] for n, name in RESERVED_UNI1_ONLY.items()},
        is_uni1=True,
    )


def test_no_new_duplicate_migration_numbers():
    duplicates = {n: names for n, names in _by_number().items() if len(names) > 1}
    assert set(duplicates) <= LEGACY_DUPLICATES, duplicates
