"""Production regression: duplicate paid events must recover unfulfilled shop orders."""

from __future__ import annotations


def test_duplicate_paid_event_retries_failed_fulfillment(monkeypatch):
    import game.shop as shop

    failed_order = {"id": 42, "status": shop.STATUS_FAILED}
    paid_order = {"id": 42, "status": shop.STATUS_PAID}
    fulfilled_order = {"id": 42, "status": shop.STATUS_FULFILLED}
    calls = {"mark_paid": 0, "fulfill": 0}

    monkeypatch.setattr(shop, "record_payment_event", lambda *a, **k: (True, "duplicate"))
    monkeypatch.setattr(shop, "get_order", lambda *a, **k: dict(failed_order))

    def fake_mark_paid(*args, **kwargs):
        calls["mark_paid"] += 1
        return True, "ok", dict(paid_order)

    def fake_fulfill(*args, **kwargs):
        calls["fulfill"] += 1
        return True, "ok", dict(fulfilled_order)

    monkeypatch.setattr(shop, "mark_paid", fake_mark_paid)
    monkeypatch.setattr(shop, "fulfill_order", fake_fulfill)

    ok, reason, order = shop.process_paid_event(
        provider="paypal",
        event_id="evt-retry",
        order_id=42,
        conn=object(),
    )

    assert ok is True
    assert reason == "ok"
    assert order["status"] == shop.STATUS_FULFILLED
    assert calls == {"mark_paid": 1, "fulfill": 1}


def test_duplicate_paid_event_does_not_regrant_fulfilled_order(monkeypatch):
    import game.shop as shop

    fulfilled_order = {"id": 42, "status": shop.STATUS_FULFILLED}
    monkeypatch.setattr(shop, "record_payment_event", lambda *a, **k: (True, "duplicate"))
    monkeypatch.setattr(shop, "get_order", lambda *a, **k: dict(fulfilled_order))

    def should_not_run(*args, **kwargs):
        raise AssertionError("fulfilled duplicate must not re-enter grant path")

    monkeypatch.setattr(shop, "mark_paid", should_not_run)
    monkeypatch.setattr(shop, "fulfill_order", should_not_run)

    ok, reason, order = shop.process_paid_event(
        provider="paypal",
        event_id="evt-done",
        order_id=42,
        conn=object(),
    )

    assert ok is True
    assert reason == "duplicate"
    assert order["status"] == shop.STATUS_FULFILLED


def test_process_paid_event_source_contains_duplicate_recovery_guard():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "game/shop.py").read_text(encoding="utf-8")
    block = src.split("def process_paid_event(", 1)[1].split("\ndef _season_pass_owned", 1)[0]
    assert "duplicate_event = ev_reason == \"duplicate\"" in block
    assert "STATUS_FAILED" in block
    assert "return fulfill_order" in block
