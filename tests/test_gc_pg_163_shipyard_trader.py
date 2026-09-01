from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _block(text: str, start: str, end: str) -> str:
    tail = text.split(start, 1)[1]
    return tail.split(end, 1)[0]


def test_shipyard_http_route_owns_and_commits_pg_transaction_before_state_refresh():
    src = _read("app.py")
    block = _block(
        src,
        '@app.route("/api/shipyard/build", methods=["POST"])',
        '\n\n@app.route(',
    )
    begin_at = block.index("begin_write_transaction(conn)")
    schema_at = block.index("fleet_schema_ready(conn)")
    build_at = block.index("build_ship(")
    commit_at = block.index("commit(conn)")
    state_at = block.index('_build_game_state_payload(include_panel=True, finish_source="api_shipyard_build")')
    assert begin_at < schema_at < build_at < commit_at < state_at
    assert "rollback(conn)" in block
    assert "finally:\n        conn.close()" in block


def test_shipyard_service_keeps_caller_owned_transaction_contract():
    src = _read("game/shipyard.py")
    block = _block(src, "def build_ships(", "\n\ndef get_ship_inventory")
    assert "if not in_transaction(conn):" in block
    assert "began_tx = True" in block
    assert "if own or began_tx:\n            commit(conn)" in block
    assert "if own or began_tx:\n                rollback(conn)" in block


def test_trader_exchange_input_preserves_large_decimal_amount_exactly():
    src = _read("static/main.js")
    assert 'inp.maxLength = inp.id === "gc-exchange-amount" ? 96 : 20;' in src
    assert 'if (inp.id === "gc-exchange-amount") {' in src
    assert "formatNumber(BigInt(digits))" in src
    assert 'const amountDigits = String(amountInput.value || "")' in src
    assert "amount: amountDigits" in src


def test_exchange_server_accepts_decimal_string_via_python_int_contract():
    src = _read("app.py")
    block = _block(src, '@app.route("/api/exchange", methods=["POST"])', "\n\n@app.route(")
    assert 'amount = int(data.get("amount") or 0)' in block
