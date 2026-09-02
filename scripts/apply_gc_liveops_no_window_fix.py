from pathlib import Path

server = Path('game/server_events.py')
s = server.read_text(encoding='utf-8')
old = '''        result, err = materialize_schedule(int(rule["id"]), conn=conn, now=ts)\n        if err:\n            errors.append({"schedule_id": rule["id"], "error": err})\n            continue\n        if not result:\n            continue\n'''
new = '''        result, err = materialize_schedule(int(rule["id"]), conn=conn, now=ts)\n        # No window inside the scheduler lookahead is the normal idle state, not\n        # an operational failure. Treat it like an ordinary skipped rule so the\n        # maintenance logs only report actionable LiveOps errors.\n        if err == "no_window":\n            skipped += 1\n            continue\n        if err:\n            errors.append({"schedule_id": rule["id"], "error": err})\n            continue\n        if not result:\n            continue\n'''
if old not in s:
    raise SystemExit('tick_schedules error block not found')
server.write_text(s.replace(old, new, 1), encoding='utf-8')

fleet = Path('game/fleet_worker.py')
f = fleet.read_text(encoding='utf-8')
old = '''            mats = sev.get("materialized") or []\n            if mats or sev.get("errors"):\n                _worker_log(\n                    f"liveops_schedules materialized={len(mats)} "\n                    f"skipped={sev.get('skipped')} errors={len(sev.get('errors') or [])}"\n                )\n'''
new = '''            mats = sev.get("materialized") or []\n            errs = sev.get("errors") or []\n            if mats or errs:\n                error_summary = ",".join(\n                    f"{int(item.get('schedule_id') or 0)}:{str(item.get('error') or 'unknown')}"\n                    for item in errs[:5]\n                    if isinstance(item, dict)\n                )\n                suffix = f" error_reasons={error_summary}" if error_summary else ""\n                _worker_log(\n                    f"liveops_schedules materialized={len(mats)} "\n                    f"skipped={sev.get('skipped')} errors={len(errs)}{suffix}"\n                )\n'''
if old not in f:
    raise SystemExit('fleet LiveOps logging block not found')
fleet.write_text(f.replace(old, new, 1), encoding='utf-8')

Path('tests/test_gc_liveops_schedule_idle_contract.py').write_text('''import game.server_events as server_events\n\n\ndef test_tick_schedules_counts_no_window_as_skip(monkeypatch):\n    monkeypatch.setattr(server_events, "schedule_schema_ready", lambda conn: True)\n    monkeypatch.setattr(\n        server_events,\n        "list_schedules",\n        lambda conn=None: [\n            {"id": 1, "enabled": True},\n            {"id": 2, "enabled": False},\n        ],\n    )\n    monkeypatch.setattr(\n        server_events,\n        "materialize_schedule",\n        lambda schedule_id, **kwargs: (None, "no_window"),\n    )\n\n    out = server_events.tick_schedules(conn=object(), now=123456.0)\n\n    assert out["ok"] is True\n    assert out["materialized"] == []\n    assert out["errors"] == []\n    assert out["skipped"] == 1\n\n\ndef test_tick_schedules_keeps_real_errors_actionable(monkeypatch):\n    monkeypatch.setattr(server_events, "schedule_schema_ready", lambda conn: True)\n    monkeypatch.setattr(\n        server_events,\n        "list_schedules",\n        lambda conn=None: [{"id": 7, "enabled": True}],\n    )\n    monkeypatch.setattr(\n        server_events,\n        "materialize_schedule",\n        lambda schedule_id, **kwargs: (None, "broken_rule"),\n    )\n\n    out = server_events.tick_schedules(conn=object(), now=123456.0)\n\n    assert out["skipped"] == 0\n    assert out["errors"] == [{"schedule_id": 7, "error": "broken_rule"}]\n''', encoding='utf-8')
