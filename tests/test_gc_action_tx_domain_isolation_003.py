from __future__ import annotations

from game import queue_engine


class _Conn:
    in_transaction = True


def test_action_owned_tx_defaults_fleet_and_relocation_off(monkeypatch):
    conn = _Conn()

    # If the central default regresses, these explode immediately.
    import game.fleet as fleet
    import game.galaxy as galaxy

    monkeypatch.setattr(fleet, "fleet_schema_ready", lambda _conn: (_ for _ in ()).throw(AssertionError("fleet entered action tx")))
    monkeypatch.setattr(galaxy, "relocation_schema_ready", lambda _conn: (_ for _ in ()).throw(AssertionError("relocation entered action tx")))

    result = queue_engine.finish_due_work(
        player_id=123,
        conn=conn,
        source="action",
        manage_transaction=False,
        queue_domains=set(),
    )

    assert result["ok"] is True
    assert result["finished"]["fleet_arrivals"] == 0
    assert result["finished"]["fleet_returns"] == 0
    assert result["finished"]["planet_relocations"] == 0


def test_action_owned_tx_allows_explicit_cross_domain_opt_in(monkeypatch):
    conn = _Conn()
    calls = {"fleet": 0, "reloc": 0}

    import game.fleet as fleet
    import game.galaxy as galaxy

    monkeypatch.setattr(fleet, "fleet_schema_ready", lambda _conn: True)

    def _fleet_tick(**_kwargs):
        calls["fleet"] += 1
        return {"processed_arrivals": 0, "processed_returns": 0, "errors": []}

    monkeypatch.setattr(fleet, "process_fleet_tick", _fleet_tick)
    monkeypatch.setattr(galaxy, "relocation_schema_ready", lambda _conn: True)

    def _reloc(_conn, **_kwargs):
        calls["reloc"] += 1
        return 0

    monkeypatch.setattr(galaxy, "finish_due_relocations", _reloc)

    result = queue_engine.finish_due_work(
        player_id=123,
        conn=conn,
        source="action",
        manage_transaction=False,
        queue_domains=set(),
        include_fleet=True,
        include_relocations=True,
    )

    assert result["ok"] is True
    assert calls == {"fleet": 1, "reloc": 1}


def test_non_action_shared_tx_preserves_historical_defaults(monkeypatch):
    conn = _Conn()
    calls = {"fleet": 0, "reloc": 0}

    import game.fleet as fleet
    import game.galaxy as galaxy

    monkeypatch.setattr(fleet, "fleet_schema_ready", lambda _conn: True)
    monkeypatch.setattr(
        fleet,
        "process_fleet_tick",
        lambda **_kwargs: calls.__setitem__("fleet", calls["fleet"] + 1)
        or {"processed_arrivals": 0, "processed_returns": 0, "errors": []},
    )
    monkeypatch.setattr(galaxy, "relocation_schema_ready", lambda _conn: True)
    monkeypatch.setattr(
        galaxy,
        "finish_due_relocations",
        lambda _conn, **_kwargs: calls.__setitem__("reloc", calls["reloc"] + 1) or 0,
    )

    result = queue_engine.finish_due_work(
        player_id=123,
        conn=conn,
        source="system",
        manage_transaction=False,
        queue_domains=set(),
    )

    assert result["ok"] is True
    assert calls == {"fleet": 1, "reloc": 1}
