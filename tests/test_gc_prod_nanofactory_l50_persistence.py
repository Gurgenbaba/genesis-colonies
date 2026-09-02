"""Production regression: nanofactory L50 cost snapshots must fit persisted integer columns."""

from __future__ import annotations


def test_nanofactory_l49_l50_crosses_raw_i64_boundary_but_live_cost_is_safe():
    from game.economy_balance import (
        NANOFACTORY_COST_GROWTH,
        NANOFACTORY_METAL_BASE,
        NANOFACTORY_PERSISTED_COST_MAX,
        nanofactory_upgrade_cost,
    )

    raw_l49 = int(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** 49))
    raw_l50 = int(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** 50))
    signed_i64_max = (1 << 63) - 1

    assert raw_l49 < signed_i64_max
    assert raw_l50 > signed_i64_max

    metal49, _ = nanofactory_upgrade_cost(49)
    metal50, crystal50 = nanofactory_upgrade_cost(50)
    assert metal49 == raw_l49
    assert metal50 == NANOFACTORY_PERSISTED_COST_MAX
    assert metal50 < signed_i64_max
    assert crystal50 < signed_i64_max


def test_nanofactory_alpha_growth_rate_remains_two_x():
    from game.economy_balance import NANOFACTORY_COST_GROWTH

    assert NANOFACTORY_COST_GROWTH == 2.0
