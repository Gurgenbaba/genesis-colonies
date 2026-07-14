"""GC-TRADER-MAX-001 — Trader exchange MAX button contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_exchange_panel_has_max_button():
    tpl = _read("templates/partials/exchange_panel.html")
    assert "data-exchange-max" in tpl
    assert "gc-trader-amount-input-row" in tpl
    assert "data-balance-metal" in tpl
    assert "data-daily-remaining" in tpl


def test_init_exchange_panel_max_uses_min_balance_and_daily_remaining():
    src = _read("static/main.js")
    block = src.split("function initExchangePanel()")[1].split("function renderScrapyardRows")[0]
    assert "computeExchangeMaxInput" in block
    assert "readExchangeGiveBalance" in block
    assert "readExchangeDailyRemaining" in block
    assert "Math.min(balance, remaining)" in block
    assert "updateExchangeMaxBtn" in block
    assert "applyExchangeMaxAmount" in block
    assert 'panel.querySelector("[data-exchange-max]")' in block


def test_max_click_updates_input_without_fetch():
    src = _read("static/main.js")
    block = src.split("const applyExchangeMaxAmount = () => {")[1].split("const setDirection = (dir) => {")[0]
    assert "setNumberInputValue(amountInput, maxVal)" in block
    assert 'dispatchEvent(new Event("input"' in block
    assert "scheduleUpdatePreview()" in block
    assert "fetch(" not in block
    assert "GC.fetchGameAction" not in block


def test_max_disabled_when_below_minimum_or_zero():
    src = _read("static/main.js")
    block = src.split("const updateExchangeMaxBtn = () => {")[1].split("const applyExchangeMaxAmount = () => {")[0]
    assert "maxVal > 0" in block
    assert "maxVal >= minNow" in block
    assert "maxBtn.disabled = !enabled" in block


def test_max_reads_all_three_give_resources():
    src = _read("static/main.js")
    block = src.split("const readExchangeGiveBalance = (resource) => {")[1].split(
        "const readExchangeDailyRemaining = () => {"
    )[0]
    assert "balanceMetal" in block
    assert "balanceCrystal" in block
    assert "balanceFuelCells" in block
    assert "ex.balances" in block


def test_patch_exchange_state_refreshes_max_inputs():
    src = _read("static/main.js")
    block = src.split("const patchExchangeFromState = (exchange) => {")[1].split("if (!panel.dataset.exchangeBound)")[0]
    assert "panel.dataset.balanceMetal" in block
    assert "panel.dataset.dailyRemaining" in block
    assert "updateExchangeMaxBtn()" in block


def test_resource_switch_updates_max_button():
    src = _read("static/main.js")
    block = src.split("const setDirection = (dir) => {")[1].split("const setResourcePair = (give, receive) => {")[0]
    assert "updateExchangeMaxBtn()" in block


def test_trader_max_button_css_is_compact_row():
    css = _read("static/style.css")
    block = css.split(".trader-hub-page .gc-trader-amount-input-row{")[1].split(".trader-hub-page .gc-trader-field-label{")[0]
    assert "display: flex" in block
    assert "min-width: 0" in block
    assert ".gc-trader-max-btn" in css
