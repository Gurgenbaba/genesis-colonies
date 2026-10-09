"""Keep UNI1-only migration numbers (183/184) from being reused or copied to main.

See docs/MIGRATION_NUMBER_RESERVATIONS.md. Migrations are tracked by file name,
so a reused number does not fail by itself; this guard makes the intent explicit.
"""
from __future__ import annotations

import re
from pathlib import Path

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


def test_reserved_numbers_only_hold_the_reserved_uni1_files():
    numbers = _by_number()
    for number, name in RESERVED_UNI1_ONLY.items():
        assert set(numbers.get(number, [])) <= {name}, (
            f"migration number {number} is reserved for {name} (UNI1 only); "
            "use 185 or higher for new migrations"
        )


def test_no_new_duplicate_migration_numbers():
    duplicates = {n: names for n, names in _by_number().items() if len(names) > 1}
    assert set(duplicates) <= LEGACY_DUPLICATES, duplicates
