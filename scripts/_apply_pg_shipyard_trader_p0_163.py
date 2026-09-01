#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


app = ROOT / "app.py"
old_route = '''@app.route("/api/shipyard/build", methods=["POST"])
@require_login
def api_shipyard_build():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok
    from game.planet_evolution.repository import get_context_planet
    from game.shipyard import build_ship

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    data = request.get_json(silent=True) or {}
    ship_key = str(data.get("ship_key") or "").strip()
    from game.number_format import parse_int_number

    amount = parse_int_number(data.get("amount") or 1, default=0)

    conn = db()
    try:
        if not fleet_schema_ready(conn):
            return jsonify(fleet_err("fleet_unavailable")), 503
        from game.shipyard import resolve_owned_planet_id

        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            return jsonify(fleet_err(err)), 404
        ok, reason, result = build_ship(
            player_id=user_id,
            planet_id=int(planet_id),
            ship_key=ship_key,
            amount=amount,
            conn=conn,
        )
    finally:
        conn.close()

    if ok:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_shipyard_build")
        body = fleet_ok(result, message_key="shipyard_build_ok")
        body["state"] = state
        return jsonify(body)
    return jsonify(fleet_err(reason)), 400
'''
new_route = '''@app.route("/api/shipyard/build", methods=["POST"])
@require_login
def api_shipyard_build():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok
    from game.shipyard import build_ship

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    data = request.get_json(silent=True) or {}
    ship_key = str(data.get("ship_key") or "").strip()
    from game.number_format import parse_int_number

    amount = parse_int_number(data.get("amount") or 1, default=0)

    # PostgreSQL: even the ownership/schema SELECTs below start an implicit
    # transaction. The HTTP route therefore owns the whole short mutation.
    # build_ship/build_ships deliberately does not commit a caller-owned tx.
    conn = db()
    try:
        begin_write_transaction(conn)
        if not fleet_schema_ready(conn):
            rollback(conn)
            return jsonify(fleet_err("fleet_unavailable")), 503
        from game.shipyard import resolve_owned_planet_id

        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            rollback(conn)
            return jsonify(fleet_err(err)), 404
        ok, reason, result = build_ship(
            player_id=user_id,
            planet_id=int(planet_id),
            ship_key=ship_key,
            amount=amount,
            conn=conn,
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    # Build response state only after the enqueue commit. A later panel/state
    # read failure must never roll back a successfully queued ship job.
    if ok:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_shipyard_build")
        body = fleet_ok(result, message_key="shipyard_build_ok")
        body["state"] = state
        return jsonify(body)
    return jsonify(fleet_err(reason)), 400
'''
replace_once(app, old_route, new_route, "shipyard route")

main = ROOT / "static" / "main.js"
text = main.read_text(encoding="utf-8")
old_len = '    if (!inp.getAttribute("maxlength")) inp.maxLength = 20;\n'
new_len = '''    if (!inp.getAttribute("maxlength")) {
      // Trader values can legitimately exceed the old 20-character UI cap.
      // Keep other gameplay inputs unchanged; the server remains authoritative.
      inp.maxLength = inp.id === "gc-exchange-amount" ? 96 : 20;
    }
'''
if text.count(old_len) != 1:
    raise SystemExit(f"exchange maxlength anchor: expected 1, found {text.count(old_len)}")
text = text.replace(old_len, new_len, 1)
old_fmt = '''    let num = clampToNumberInputCap(inp, parseInt(digits, 10));
    const formatted = formatNumber(num);
    inp.value = formatted;
'''
new_fmt = '''    let formatted = "";
    if (inp.id === "gc-exchange-amount") {
      // Preserve every manually-entered digit. Number/parseInt rounds large
      // balances; BigInt is display/input-only and the API accepts the amount
      // as a decimal string before Python int validation.
      try {
        formatted = formatNumber(BigInt(digits));
      } catch (_) {
        formatted = digits;
      }
    } else {
      const num = clampToNumberInputCap(inp, parseInt(digits, 10));
      formatted = formatNumber(num);
    }
    inp.value = formatted;
'''
if text.count(old_fmt) != 1:
    raise SystemExit(f"exchange input formatting anchor: expected 1, found {text.count(old_fmt)}")
text = text.replace(old_fmt, new_fmt, 1)
old_submit = '''        const amount = readNumberInput(amountInput);
        const dir = selectedDirection();
'''
new_submit = '''        const amountDigits = String(amountInput.value || "").replace(/[^\\d]/g, "").replace(/^0+(?=\\d)/, "") || "0";
        const amount = readNumberInput(amountInput);
        const dir = selectedDirection();
'''
if text.count(old_submit) != 1:
    raise SystemExit(f"exchange submit anchor: expected 1, found {text.count(old_submit)}")
text = text.replace(old_submit, new_submit, 1)
old_body = '''            body: JSON.stringify({ direction: dir, from, to, amount }),
'''
new_body = '''            // Send the exact decimal string; Flask/Python int accepts it and
            // avoids JavaScript Number precision loss on very large empires.
            body: JSON.stringify({ direction: dir, from, to, amount: amountDigits }),
'''
if text.count(old_body) != 1:
    raise SystemExit(f"exchange POST body anchor: expected 1, found {text.count(old_body)}")
text = text.replace(old_body, new_body, 1)
main.write_text(text, encoding="utf-8")
