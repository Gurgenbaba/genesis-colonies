#!/usr/bin/env python3
from pathlib import Path

src_path = Path("game/economy_balance.py")
src = src_path.read_text(encoding="utf-8")
old_constants = '''NANOFACTORY_METAL_BASE = 10_000.0
NANOFACTORY_CRYSTAL_BASE = 5_000.0
NANOFACTORY_COST_GROWTH = 2.0  # Alpha: doubles per target level (OGame-style steep investment)
'''
new_constants = '''NANOFACTORY_METAL_BASE = 10_000.0
NANOFACTORY_CRYSTAL_BASE = 5_000.0
NANOFACTORY_COST_GROWTH = 2.0  # Alpha: doubles per target level (OGame-style steep investment)
# Queue cost snapshots are persisted as signed 64-bit integers on both supported DB paths.
# L50 metal would otherwise exceed BIGINT/SQLite INTEGER while L49 remains valid.
NANOFACTORY_PERSISTED_COST_MAX = 9_000_000_000_000_000_000
'''
old_fn = '''def nanofactory_upgrade_cost(target_level: int) -> Tuple[int, int]:
    """GC-863 — Ferronit/Crytite = base × 1.33^target_level."""
    lvl = max(1, int(target_level))
    metal = max(1, int(math.ceil(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** lvl))))
    crystal = max(0, int(math.ceil(NANOFACTORY_CRYSTAL_BASE * (NANOFACTORY_COST_GROWTH ** lvl))))
    return metal, crystal
'''
new_fn = '''def nanofactory_upgrade_cost(target_level: int) -> Tuple[int, int]:
    """GC-863 — steep Alpha curve, capped only at the DB-safe persisted snapshot ceiling."""
    lvl = max(1, int(target_level))
    raw_metal = max(1, int(math.ceil(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** lvl))))
    raw_crystal = max(0, int(math.ceil(NANOFACTORY_CRYSTAL_BASE * (NANOFACTORY_COST_GROWTH ** lvl))))
    return (
        min(raw_metal, NANOFACTORY_PERSISTED_COST_MAX),
        min(raw_crystal, NANOFACTORY_PERSISTED_COST_MAX),
    )
'''
if old_constants not in src or old_fn not in src:
    raise SystemExit("nanofactory source targets not found")
src = src.replace(old_constants, new_constants, 1).replace(old_fn, new_fn, 1)
src_path.write_text(src, encoding="utf-8")

test_path = Path("tests/test_gc863a_building_balance_hardening.py")
test_src = test_path.read_text(encoding="utf-8")
test_src = test_src.replace(
    '''    NANOFACTORY_METAL_BASE,\n''',
    '''    NANOFACTORY_METAL_BASE,\n    NANOFACTORY_PERSISTED_COST_MAX,\n''',
    1,
)
old_test = '''    @pytest.mark.parametrize("level", (1, 10, 25, 50))
    def test_formula_unchanged(self, level: int) -> None:
        metal, crystal = nanofactory_upgrade_cost(level)
        assert metal == max(1, int(math.ceil(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** level))))
        assert crystal == max(0, int(math.ceil(NANOFACTORY_CRYSTAL_BASE * (NANOFACTORY_COST_GROWTH ** level))))

    def test_level_50_stays_in_billions(self) -> None:
        metal, crystal = nanofactory_upgrade_cost(50)
        assert metal >= 20_000_000_000
        assert crystal >= 10_000_000_000
'''
new_test = '''    @pytest.mark.parametrize("level", (1, 10, 25, 49))
    def test_formula_unchanged_below_persistence_ceiling(self, level: int) -> None:
        metal, crystal = nanofactory_upgrade_cost(level)
        assert metal == max(1, int(math.ceil(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** level))))
        assert crystal == max(0, int(math.ceil(NANOFACTORY_CRYSTAL_BASE * (NANOFACTORY_COST_GROWTH ** level))))

    def test_level_50_fits_persisted_queue_cost_columns(self) -> None:
        metal, crystal = nanofactory_upgrade_cost(50)
        assert metal == NANOFACTORY_PERSISTED_COST_MAX
        assert metal <= 9_000_000_000_000_000_000
        assert crystal < NANOFACTORY_PERSISTED_COST_MAX
        assert crystal >= 10_000_000_000
'''
if old_test not in test_src:
    raise SystemExit("nanofactory test target not found")
test_path.write_text(test_src.replace(old_test, new_test, 1), encoding="utf-8")
