import game.server_events as server_events


def test_tick_schedules_counts_no_window_as_skip(monkeypatch):
    monkeypatch.setattr(server_events, "schedule_schema_ready", lambda conn: True)
    monkeypatch.setattr(
        server_events,
        "list_schedules",
        lambda conn=None: [
            {"id": 1, "enabled": True},
            {"id": 2, "enabled": False},
        ],
    )
    monkeypatch.setattr(
        server_events,
        "materialize_schedule",
        lambda schedule_id, **kwargs: (None, "no_window"),
    )

    out = server_events.tick_schedules(conn=object(), now=123456.0)

    assert out["ok"] is True
    assert out["materialized"] == []
    assert out["errors"] == []
    assert out["skipped"] == 1


def test_tick_schedules_keeps_real_errors_actionable(monkeypatch):
    monkeypatch.setattr(server_events, "schedule_schema_ready", lambda conn: True)
    monkeypatch.setattr(
        server_events,
        "list_schedules",
        lambda conn=None: [{"id": 7, "enabled": True}],
    )
    monkeypatch.setattr(
        server_events,
        "materialize_schedule",
        lambda schedule_id, **kwargs: (None, "broken_rule"),
    )

    out = server_events.tick_schedules(conn=object(), now=123456.0)

    assert out["skipped"] == 0
    assert out["errors"] == [{"schedule_id": 7, "error": "broken_rule"}]
