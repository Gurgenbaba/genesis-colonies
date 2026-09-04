"""D1 — lossless Python/JSON/browser gameplay integer transport."""

from __future__ import annotations

import json
from pathlib import Path

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

    troop_train = defense.split('if (trainBtn) {')[1].split('if (cancelBtn) {')[0]
    assert "var amount = readGameplayIntegerInput(amountInp);" in troop_train
    assert "amount: amount" in troop_train

    defense_build = defense.split(
        'var buildBtn = e.target.closest("[data-defense-build]")'
    )[1]
    assert "var amount = readGameplayIntegerInput(qtyInpBuild);" in defense_build
    assert "amount: amount" in defense_build


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
