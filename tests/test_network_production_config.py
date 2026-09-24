from __future__ import annotations

from game.config import _validate_network_runtime_config


def _set_network_base(monkeypatch, *, universe: str = "dev") -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setenv("GC_UNIVERSE_KEY", universe)
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_KEY", "dev")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_URL", "https://www.genesis-colonies.de")
    monkeypatch.setenv(
        "GC_NETWORK_UNI1_URL",
        "https://genesis-colonies-u2-production.up.railway.app",
    )
    monkeypatch.setenv("GC_NETWORK_AUTH_SECRET", "n" * 48)
    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", "1")




def _set_uni1_launch_contract(monkeypatch) -> None:
    monkeypatch.setenv("GC_UNIVERSE_SPEED_PROFILE", "x1")
    monkeypatch.setenv("GC_ENDGAME_ECONOMY_MODE", "active")
    monkeypatch.setenv("GC_ENDGAME_PRODUCTION_PIVOT", "120")
    monkeypatch.setenv("GC_ENDGAME_PRODUCTION_TAIL_POWER", "3")
    monkeypatch.setenv("GC_NETWORK_START_RESOURCE_MULTIPLIER", "10")
    monkeypatch.setenv("GC_NETWORK_START_TIMEKEEPER_SECONDS", "259200")
    monkeypatch.setenv("GC_INACTIVE_AUTOPLAY_ENABLED", "0")
    monkeypatch.setenv("GC_PIRATE_AI_ENABLED", "0")
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_MODE", "live")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "live-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "live-secret")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "live-webhook")
    monkeypatch.setattr("game.mine_evolution.ruleset.ASCENSION_RULESET", "nodebuster-v1")


def test_network_production_config_accepts_ready_authority(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    assert _validate_network_runtime_config() == []


def test_network_production_config_requires_explicit_universe(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.delenv("GC_UNIVERSE_KEY")
    errors = _validate_network_runtime_config()
    assert any("GC_UNIVERSE_KEY" in error for error in errors)


def test_network_production_config_rejects_short_handoff_secret(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.setenv("GC_NETWORK_AUTH_SECRET", "too-short")
    errors = _validate_network_runtime_config()
    assert any("GC_NETWORK_AUTH_SECRET" in error for error in errors)


def test_open_non_authority_requires_maintenance_path(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    _set_uni1_launch_contract(monkeypatch)
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "0")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    errors = _validate_network_runtime_config()
    assert any("maintenance" in error.lower() for error in errors)


def test_open_non_authority_accepts_maintenance_sidecar(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    _set_uni1_launch_contract(monkeypatch)
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    assert _validate_network_runtime_config() == []


def test_uni1_requires_https_public_url(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    _set_uni1_launch_contract(monkeypatch)
    monkeypatch.setenv("GC_NETWORK_UNI1_URL", "http://uni1.invalid")
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    errors = _validate_network_runtime_config()
    assert any("GC_NETWORK_UNI1_URL" in error for error in errors)



def test_uni1_launch_rejects_missing_x1_profile(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    _set_uni1_launch_contract(monkeypatch)
    monkeypatch.delenv("GC_UNIVERSE_SPEED_PROFILE")
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    errors = _validate_network_runtime_config()
    assert any("GC_UNIVERSE_SPEED_PROFILE=x1" in error for error in errors)


def test_uni1_launch_rejects_old_ascension_ruleset(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    _set_uni1_launch_contract(monkeypatch)
    monkeypatch.setattr("game.mine_evolution.ruleset.ASCENSION_RULESET", "phase1-no-reset")
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    errors = _validate_network_runtime_config()
    assert any("Nodebuster" in error for error in errors)


def test_x1_profile_overrides_all_universe_speed_domains(monkeypatch):
    from game.models import _apply_universe_speed_profile

    monkeypatch.setenv("GC_UNIVERSE_SPEED_PROFILE", "x1")
    raw = {
        "production_speed": "3",
        "build_speed": "8",
        "research_speed": "50",
        "fleet_speed_war": "3",
        "fleet_speed_holding": "2",
        "fleet_speed_peaceful": "5",
        "shipyard_speed": "4",
        "speed": "8",
        "queue_limit": "5",
    }
    resolved = _apply_universe_speed_profile(raw)
    for key in (
        "production_speed",
        "build_speed",
        "research_speed",
        "fleet_speed_war",
        "fleet_speed_holding",
        "fleet_speed_peaceful",
        "shipyard_speed",
        "speed",
    ):
        assert resolved[key] == "1.0"
    assert resolved["queue_limit"] == "5"
