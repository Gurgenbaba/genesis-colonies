"""GC-PERF-INVENTORY-OPEN-009 — client race/partial-state regression guards."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _main_js() -> str:
    return (ROOT / "static" / "main.js").read_text(encoding="utf-8")


def test_inventory_open_clock_only_state_never_enters_full_action_state_pipeline():
    src = _main_js()
    open_success = src.split('request_id: `inv-open-', 1)[1].split(
        "showLootOpeningModal({", 1
    )[0]
    assert 'syncServerClockFromState(res.state)' in open_success
    assert "applyActionState(" not in open_success

    reveal = src.split("function revealLootRewards(modal, payload)", 1)[1].split(
        "function computeLootRollTarget", 1
    )[0]
    assert "applyActionState(" not in reveal
    assert "_deferredState" not in reveal


def test_inventory_open_full_refresh_wins_over_click_snapshot_at_reveal():
    src = _main_js()
    can_again = src.split("function canOpenContainerAgain(payload)", 1)[1].split(
        "function closeLootModal", 1
    )[0]
    assert "_inventoryLastState || payload.inventory" in can_again

    reveal = src.split("function revealLootRewards(modal, payload)", 1)[1].split(
        "function computeLootRollTarget", 1
    )[0]
    assert "applyInventoryActionResult(" not in reveal
    assert "_deferredInventory" not in reveal

    open_success = src.split('request_id: `inv-open-', 1)[1].split(
        "showLootOpeningModal({", 1
    )[0]
    assert "void refreshInventoryFromServer();" in open_success
