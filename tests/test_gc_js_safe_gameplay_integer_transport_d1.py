"""P0-D1 lossless gameplay integer transport contract."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from flask import Flask, jsonify

from game.json_transport import (
    JS_SAFE_INTEGER_MAX,
    GenesisJSONProvider,
    js_safe_json_value,
)

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**30 + 123_456_789


def test_json_transport_stringifies_only_js_unsafe_ints():
    payload = {
        "safe_pos": JS_SAFE_INTEGER_MAX,
        "safe_neg": -JS_SAFE_INTEGER_MAX,
        "unsafe_pos": JS_SAFE_INTEGER_MAX + 1,
        "unsafe_neg": -(JS_SAFE_INTEGER_MAX + 1),
        "huge": HUGE,
        "bool": True,
        "nested": [{"amount": HUGE + 1}, (HUGE + 2, 7)],
    }

    got = js_safe_json_value(payload)

    assert got["safe_pos"] == JS_SAFE_INTEGER_MAX
    assert isinstance(got["safe_pos"], int)
    assert got["safe_neg"] == -JS_SAFE_INTEGER_MAX
    assert isinstance(got["safe_neg"], int)

    assert got["unsafe_pos"] == str(JS_SAFE_INTEGER_MAX + 1)
    assert got["unsafe_neg"] == str(-(JS_SAFE_INTEGER_MAX + 1))
    assert got["huge"] == str(HUGE)
    assert got["bool"] is True
    assert got["nested"][0]["amount"] == str(HUGE + 1)
    assert got["nested"][1] == [str(HUGE + 2), 7]


def test_flask_json_provider_preserves_browser_integer_exactness():
    app = Flask(__name__)
    app.json = GenesisJSONProvider(app)

    @app.get("/numeric-probe")
    def numeric_probe():
        return jsonify(
            {
                "small": 42,
                "safe": JS_SAFE_INTEGER_MAX,
                "unsafe": JS_SAFE_INTEGER_MAX + 1,
                "huge": HUGE,
            }
        )

    response = app.test_client().get("/numeric-probe")
    assert response.status_code == 200
    data = json.loads(response.get_data(as_text=True))

    assert data["small"] == 42
    assert data["safe"] == JS_SAFE_INTEGER_MAX
    assert data["unsafe"] == str(JS_SAFE_INTEGER_MAX + 1)
    assert data["huge"] == str(HUGE)


def test_application_installs_lossless_json_provider():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from game.json_transport import GenesisJSONProvider" in app_source
    assert "app.json = GenesisJSONProvider(app)" in app_source


def test_unbounded_frontend_domains_use_exact_integer_submit_paths():
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    core = (ROOT / "static" / "js" / "core" / "gc.js").read_text(encoding="utf-8")
    shipyard = (ROOT / "static" / "js" / "pages" / "shipyard.js").read_text(
        encoding="utf-8"
    )
    defense = (ROOT / "static" / "js" / "pages" / "defense.js").read_text(
        encoding="utf-8"
    )

    for token in (
        "GC.normalizeGameplayInteger",
        "GC.gameplayBigInt",
        "GC.compareGameplayIntegers",
        "GC.readGameplayIntegerInput",
        "GC.setGameplayIntegerInput",
    ):
        assert token in core

    # Monolith owner: Alliance + Auction.
    assert 'const val = gameplayBigInt(state.pool?.[res] ?? 0);' in main
    assert 'const amount = readGameplayIntegerInput(input, "0");' in main
    assert '"/api/alliance/donate"' in main
    assert 'compareGameplayIntegers(amount, minBid) < 0' in main
    assert 'compareGameplayIntegers(amount, currentBid) <= 0' in main

    auction_submit = main.split(
        'page.querySelectorAll("[data-auction-bid-form]")'
    )[1].split("function bindAuctionHouse")[0]
    assert "const amount = readNumberInput(input);" not in auction_submit
    assert "const minBid = parseInt(" not in auction_submit
    assert "const currentBid = parseInt(" not in auction_submit

    # Split page owners: Shipyard + Defense + Troops.
    assert "var amount = readGameplayIntegerInput(qtyInp);" in shipyard
    assert "var amount = readGameplayIntegerInput(qtyInpBuild);" in defense
    assert "var amount = readGameplayIntegerInput(amountInp);" in defense

    for source in (shipyard, defense):
        assert "normalizeGameplayInteger" in source
        assert "isPositiveGameplayInteger" in source

    assert 'maxlength="20"' not in (
        (ROOT / "templates" / "shipyard.html").read_text(encoding="utf-8")
    )
    assert 'maxlength="20"' not in (
        (ROOT / "templates" / "defense.html").read_text(encoding="utf-8")
    )
    assert 'maxlength="20"' not in (
        ROOT / "templates" / "partials" / "barracks_troops_panel.html"
    ).read_text(encoding="utf-8")


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
