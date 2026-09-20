from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bid_route_does_not_rebuild_generic_game_state():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    block = src.split("def api_auction_house_bid():", 1)[1].split(
        '@app.route("/vote-center")', 1
    )[0]
    assert "_build_game_state_payload" not in block
    assert "build_auction_house_state" in block
    assert "SELECT metal, crystal, fuel_cells" in block
    assert '"auction_house": auction_house' in block


def test_auction_balance_patch_preserves_live_resource_model():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    helper = src.split("function syncResourceMutationAmounts(snapshot)", 1)[1].split(
        "function monotonicResourceBaseline", 1
    )[0]
    assert "_resourceLive.metal =" in helper
    assert "_resourceLive.crystal =" in helper
    assert "_resourceLive.fuelCells =" in helper
    assert "_resourceLive.syncedAt = getApproxServerNow()" in helper
    assert "patchShellHudLiveResources(" in helper
    assert "_resourceLive.prodMetal =" not in helper
    assert "_resourceLive.prodCrystal =" not in helper
    assert "_resourceLive.prodFuelCells =" not in helper
    assert "_resourceLive.capMetal =" not in helper
    assert "_resourceLive.energyTotal =" not in helper

    panel = src.split("function patchAuctionHousePanel(ah)", 1)[1].split(
        "function formatAuctionRotationRemain", 1
    )[0]
    assert "syncResourceMutationAmounts({" in panel
    assert "metal: ah.balances.metal" in panel
    assert "crystal: ah.balances.crystal" in panel
    assert "fuelCells: ah.balances.fuel_cells" in panel


def test_auction_bid_client_does_not_require_action_state():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    start = src.index('page.querySelectorAll("[data-auction-bid-form]")')
    block = src[start : start + 20_000]
    assert "const ahPayload = res?.auction_house || res?.state?.auction_house;" in block
    assert "if (ahPayload) patchAuctionHousePanel(ahPayload);" in block
    assert "if (res?.state) applyActionState(res, \"auction_bid\");" in block
