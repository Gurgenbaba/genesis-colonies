"""D1 — lossless Python/JSON/browser gameplay integer transport."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from flask import Flask

from game.json_transport import (
    JS_SAFE_INTEGER_MAX,
    GenesisJSONProvider,
    js_safe_json_value,
)

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**30 + 123_456_789


def test_js_safe_json_value_preserves_small_ints_and_stringifies_unsafe_ints():
    payload = {
        "safe_max": JS_SAFE_INTEGER_MAX,
        "unsafe": JS_SAFE_INTEGER_MAX + 1,
        "huge": HUGE,
        "negative": -(JS_SAFE_INTEGER_MAX + 7),
        "bool": True,
        "nested": [1, HUGE, {"value": HUGE + 1}],
    }
    got = js_safe_json_value(payload)

    assert got["safe_max"] == JS_SAFE_INTEGER_MAX
    assert isinstance(got["safe_max"], int)
    assert got["unsafe"] == str(JS_SAFE_INTEGER_MAX + 1)
    assert got["huge"] == str(HUGE)
    assert got["negative"] == str(-(JS_SAFE_INTEGER_MAX + 7))
    assert got["bool"] is True
    assert got["nested"][1] == str(HUGE)
    assert got["nested"][2]["value"] == str(HUGE + 1)


def test_genesis_json_provider_emits_unsafe_ints_as_decimal_strings():
    app = Flask(__name__)
    app.json = GenesisJSONProvider(app)

    encoded = app.json.dumps(
        {
            "safe": JS_SAFE_INTEGER_MAX,
            "unsafe": JS_SAFE_INTEGER_MAX + 1,
            "huge": HUGE,
        }
    )
    decoded = json.loads(encoded)

    assert decoded["safe"] == JS_SAFE_INTEGER_MAX
    assert decoded["unsafe"] == str(JS_SAFE_INTEGER_MAX + 1)
    assert decoded["huge"] == str(HUGE)


def test_real_app_installs_lossless_json_provider():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from game.json_transport import GenesisJSONProvider" in source
    assert "app.json = GenesisJSONProvider(app)" in source


def test_core_browser_contract_uses_bigint_and_no_20_digit_runtime_cap():
    core = (ROOT / "static" / "js" / "core" / "gc.js").read_text(encoding="utf-8")
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    for token in (
        "GC.normalizeGameplayInteger",
        "GC.gameplayBigInt",
        "GC.compareGameplayIntegers",
        "GC.readGameplayIntegerInput",
        "GC.setGameplayIntegerInput",
        "BigInt(",
    ):
        assert token in core or token in main

    exact_input_block = main.split("function formatNumberInputOnInput(inp)")[1].split(
        "function ensureFormattedNumberInput"
    )[0]
    assert "clampGameplayIntegerInput" in exact_input_block
    assert "parseInt(digits" not in exact_input_block
    assert 'inp.removeAttribute("maxlength")' in main
    assert "inp.maxLength = inp.id ===" not in main


def test_shipyard_defense_and_troops_submit_exact_decimal_strings():
    shipyard = (ROOT / "static" / "js" / "pages" / "shipyard.js").read_text(
        encoding="utf-8"
    )
    defense = (ROOT / "static" / "js" / "pages" / "defense.js").read_text(
        encoding="utf-8"
    )

    ship_build = shipyard.split('var buildBtn = e.target.closest("[data-shipyard-build]")')[1]
    assert "var amount = readGameplayIntegerInput(qtyInp);" in ship_build
    assert "amount: amount" in ship_build

    troop_start = defense.index('var trainBtn = e.target.closest("[data-troop-train]")')
    troop_end = defense.index('if (cancelBtn) {', troop_start)
    troop_train = defense[troop_start:troop_end]
    assert "var amount = readGameplayIntegerInput(amountInp);" in troop_train
    assert "amount: amount" in troop_train

    defense_build = defense.split(
        'var buildBtn = e.target.closest("[data-defense-build]")'
    )[1]
    assert "var amount = readGameplayIntegerInput(qtyInpBuild);" in defense_build
    assert "amount: amount" in defense_build


def test_resource_hud_and_live_ticker_keep_bigint_exactness():
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    hud_start = main.index("function patchShellHudLiveResources")
    hud_end = main.index("function resourceLiveRatesAreZero", hud_start)
    hud = main[hud_start:hud_end]
    assert "const m = gameplayBigInt(metal);" in hud
    assert "_resourceLive.capMetal = gameplayBigInt(snapshot.storageMetal || 0);" in hud
    assert "function monotonicResourceBaseline" in hud
    assert "const inc = gameplayBigInt(incoming);" in hud
    assert "_resourceLive.prodMetal = gameplayBigInt(snapshot.prodMetal || 0);" in hud
    assert "Math.floor(Number(metal)" not in hud

    projection_start = main.index("function projectLiveResourceAmount")
    projection_end = main.index("function tickLiveResourceBar", projection_start)
    projection = main[projection_start:projection_end]
    assert "const cur = gameplayBigInt(current);" in projection
    assert "const prod = gameplayBigInt(prodPerHour);" in projection
    assert "(prod * ms) / BigInt(3_600_000)" in projection
    assert "const hours = elapsed / 3600" not in projection

    capacity_start = main.index("function computeHudCapacityState")
    capacity_end = main.index("function syncHeaderVacationBanner", capacity_start)
    capacity = main[capacity_start:capacity_end]
    assert "const cur = gameplayBigInt(current);" in capacity
    assert "const cap = gameplayBigInt(max);" in capacity
    assert "v * BigInt(10) >= c * BigInt(9)" in capacity


def test_military_cost_preview_uses_exact_bigint_arithmetic():
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    start = main.index("function resolveUnitCardPreviewQty")
    end = main.index("function initMilitaryUnitCostPreviewDelegation", start)
    block = main[start:end]

    assert 'return readGameplayIntegerInput(qtyInp, "1");' in block
    assert "costWrap.dataset.unitCostMetal = normalizeGameplayInteger" in block
    assert "const qty = gameplayBigInt(amount);" in block
    assert "const unit = gameplayBigInt(unitCosts[costKey]);" in block
    assert "const need = unit * (qty > BigInt(0) ? qty : BigInt(1));" in block
    assert "const have = gameplayBigInt(resources[resKey]);" in block
    assert "Number(unitCosts[costKey])" not in block
    assert "Number(resources[resKey])" not in block


def test_alliance_donation_path_is_bigint_safe():
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    pool_start = main.index('["metal", "crystal", "fuel_cells"].forEach((res) => {')
    pool_end = main.index("const summary =", pool_start)
    pool_block = main[pool_start:pool_end]
    assert "gameplayBigInt(state.pool?.[res]" in pool_block
    assert "gameplayBigInt(state.pool_cap?.[res]" in pool_block
    assert "compareGameplayIntegers(readGameplayIntegerInput(input), maxVal)" in pool_block
    assert 'maxlength="20"' not in pool_block

    donate_start = main.index('const donateMaxBtn = ev.target.closest("[data-donate-max]")')
    donate_end = main.index('const startBtn = ev.target.closest("[data-start-project]")', donate_start)
    donate_block = main[donate_start:donate_end]
    assert 'normalizeGameplayInteger(input.dataset.inputMax || "0")' in donate_block
    assert 'const amount = readGameplayIntegerInput(input, "0");' in donate_block
    assert "if (!isPositiveGameplayInteger(amount)) return;" in donate_block
    assert "Number(input.dataset.inputMax" not in donate_block
    assert "readNumberInput(input)" not in donate_block


def test_no_max_quantity_templates_have_no_20_digit_cap():
    paths = (
        ROOT / "templates" / "shipyard.html",
        ROOT / "templates" / "defense.html",
        ROOT / "templates" / "partials" / "barracks_troops_panel.html",
        ROOT / "templates" / "alliance.html",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            if any(
                marker in line
                for marker in (
                    "data-shipyard-qty",
                    "data-defense-qty",
                    "data-troop-amount",
                    "data-donate-amount",
                )
            ):
                assert 'maxlength="20"' not in line


def test_auction_bid_path_is_bigint_safe():
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    state_start = main.index("const minEl = page.querySelector")
    state_end = main.index("const submitBtn =", state_start)
    state_block = main[state_start:state_end]
    assert "normalizeGameplayInteger(a.min_next_bid" in state_block
    assert "compareGameplayIntegers(readGameplayIntegerInput(input), minVal) < 0" in state_block
    assert "readNumberInput(input) < parseIntNumber(minVal)" not in state_block

    submit_start = main.index('page.querySelectorAll("[data-auction-bid-form]")')
    # Keep this assertion resilient to helper/function renames around the handler.
    # The auction submit contract itself is what matters.
    submit_block = main[submit_start : submit_start + 20_000]
    assert 'const amount = readGameplayIntegerInput(input, "0");' in submit_block
    assert "const minBid = normalizeGameplayInteger" in submit_block
    assert "const currentBid = normalizeGameplayInteger" in submit_block
    assert "compareGameplayIntegers(amount, minBid) < 0" in submit_block
    assert "compareGameplayIntegers(amount, currentBid) <= 0" in submit_block
    assert "const amount = readNumberInput(input);" not in submit_block
    assert "const minBid = parseInt(" not in submit_block
    assert "const currentBid = parseInt(" not in submit_block


def test_auction_state_never_reintroduces_resource_float_roundtrips():
    source = (ROOT / "app.py").read_text(encoding="utf-8")

    forbidden = (
        'metal=float(ctx["player_view"]["metal"])',
        'crystal=float(ctx["player_view"]["crystal"])',
        'fuel_cells=float(ctx["player_view"].get("fuel_cells") or 0)',
        'metal=float(player_view["metal"])',
        'crystal=float(player_view["crystal"])',
        'fuel_cells=float(player_view.get("fuel_cells") or 0)',
    )
    for token in forbidden:
        assert token not in source

    assert 'metal=int(ctx["player_view"]["metal"] or 0)' in source
    assert 'crystal=int(ctx["player_view"]["crystal"] or 0)' in source
    assert 'metal=int(player_view["metal"] or 0)' in source
    assert 'crystal=int(player_view["crystal"] or 0)' in source


def test_websocket_push_uses_same_js_safe_integer_transport():
    source = (ROOT / "game" / "ws_hub.py").read_text(encoding="utf-8")
    assert "from .json_transport import js_safe_json_value" in source
    assert "json.dumps(js_safe_json_value(payload)" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_browser_core_helper_roundtrips_10_pow_30_exactly():
    core_path = ROOT / "static" / "js" / "core" / "gc.js"
    script = f"""
require({json.dumps(str(core_path))});
const GC = globalThis.GC;
const huge = {json.dumps(str(HUGE))};
if (GC.normalizeGameplayInteger(huge) !== huge) process.exit(10);
if (GC.gameplayBigInt(huge).toString() !== huge) process.exit(11);
if (GC.compareGameplayIntegers(huge, (BigInt(huge) - 1n).toString()) !== 1) process.exit(12);
if (!GC.isPositiveGameplayInteger(huge)) process.exit(13);
if (GC.fmtGameplayInteger(huge).replace(/[^0-9]/g, "") !== huge) process.exit(14);
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
