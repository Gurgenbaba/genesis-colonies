from game import systemos


def test_systemos_uses_dedicated_service_token(monkeypatch):
    monkeypatch.setenv("MAIL_HUB_URL", "https://office.example")
    monkeypatch.setenv("SYSTEMOS_SERVICE_TOKEN", "sos_test_token")
    monkeypatch.setenv("GC_UNIVERSE_KEY", "uni1")
    assert systemos.configured() is True
    assert systemos.instance_key() == "uni1"
    assert systemos._base_url() == "https://office.example"


def test_systemos_event_payload_is_compact_and_versioned(monkeypatch):
    captured = {}

    def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return True, {"ok": True}

    monkeypatch.setenv("GC_UNIVERSE_KEY", "dev")
    monkeypatch.setattr(systemos, "_post", fake_post)

    ok, _ = systemos.emit_event(
        "deployment.succeeded",
        "Deploy ok",
        metadata={"commit": "abc123", "version": "1.0.0"},
        event_id="deploy:abc123",
    )

    assert ok is True
    assert captured["path"] == "/api/v1/events"
    assert captured["payload"]["event_id"] == "deploy:abc123"
    assert captured["payload"]["schema_version"] == 1
    assert captured["payload"]["metadata"] == {"commit": "abc123", "version": "1.0.0"}


def test_systemos_health_report_maps_genesis_readiness(monkeypatch):
    monkeypatch.setenv("GC_UNIVERSE_KEY", "uni1")

    from game import health

    monkeypatch.setattr(
        health,
        "build_health_report",
        lambda: {
            "status": "ok",
            "version": "1.2.3",
            "revision": "deadbeef",
            "total_ms": 12.5,
            "checks": {
                "database": {"backend": "postgres"},
                "migrations": {"current": True},
                "runtime": {"database_backend": "postgres"},
            },
        },
    )

    status, summary, metadata = systemos._compact_health_report()
    assert status == "healthy"
    assert "uni1" in summary
    assert metadata == {
        "version": "1.2.3",
        "commit": "deadbeef",
        "database_backend": "postgres",
        "migrations_current": True,
        "total_ms": 12.5,
    }


def test_systemos_health_interval_is_bounded(monkeypatch):
    monkeypatch.setenv("SYSTEMOS_HEALTH_INTERVAL_SEC", "1")
    assert systemos._health_interval_sec() == 60
    monkeypatch.setenv("SYSTEMOS_HEALTH_INTERVAL_SEC", "99999")
    assert systemos._health_interval_sec() == 3600
