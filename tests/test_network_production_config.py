from __future__ import annotations

from pathlib import Path

from game.config import _validate_network_runtime_config, canonical_public_redirect_target


AUTHORITY_URL = "https://dev.genesis-colonies.com"
UNI1_URL = "https://uni1.genesis-colonies.com"
UNI2_URL = "https://uni2.genesis-colonies.com"


def _set_network_base(monkeypatch, *, universe: str = "dev") -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setenv("GC_UNIVERSE_KEY", universe)
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_KEY", "dev")
    monkeypatch.setenv("GC_NETWORK_DOMAIN", "genesis-colonies.com")
    monkeypatch.setenv("GC_NETWORK_UNIVERSES", "uni1")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_URL", AUTHORITY_URL)
    monkeypatch.setenv("GC_NETWORK_UNI1_URL", UNI1_URL)
    monkeypatch.setenv(
        "PUBLIC_BASE_URL",
        UNI1_URL if universe == "uni1" else AUTHORITY_URL,
    )
    monkeypatch.delenv("GC_PUBLIC_ALIAS_HOSTS", raising=False)
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


def test_authority_accepts_marketing_alias_without_session_split(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.setenv(
        "GC_PUBLIC_ALIAS_HOSTS",
        "www.genesis-colonies.de,genesis-colonies.com",
    )
    assert _validate_network_runtime_config() == []


def test_network_role_must_match_public_origin(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    _set_uni1_launch_contract(monkeypatch)
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    monkeypatch.setenv("PUBLIC_BASE_URL", AUTHORITY_URL)

    errors = _validate_network_runtime_config()

    assert any("PUBLIC_BASE_URL host must match" in error for error in errors)


def test_network_authority_and_uni1_hosts_must_be_distinct(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.setenv("GC_NETWORK_UNI1_URL", AUTHORITY_URL)

    errors = _validate_network_runtime_config()

    assert any("must be distinct" in error for error in errors)


def test_public_alias_must_not_repeat_canonical_host(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.setenv("GC_PUBLIC_ALIAS_HOSTS", "dev.genesis-colonies.com")

    errors = _validate_network_runtime_config()

    assert any("must not contain the PUBLIC_BASE_URL host" in error for error in errors)


def test_public_alias_redirect_preserves_path_and_query(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.setenv("GC_PUBLIC_ALIAS_HOSTS", "genesis-colonies.com")

    target = canonical_public_redirect_target(
        request_host="genesis-colonies.com",
        path="/login",
        query_string="network_target=uni1",
    )

    assert target == "https://dev.genesis-colonies.com/login?network_target=uni1"


def test_public_alias_does_not_redirect_machine_callbacks(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.setenv("GC_PUBLIC_ALIAS_HOSTS", "genesis-colonies.com")

    for path in (
        "/api/vote/topg/postback",
        "/api/vote/gtop100/pingback",
        "/api/webhooks/paypal",
        "/health",
        "/healthz",
    ):
        assert canonical_public_redirect_target(
            request_host="genesis-colonies.com",
            path=path,
        ) == ""



def test_future_universe_uses_domain_convention_without_code_change(monkeypatch):
    _set_network_base(monkeypatch, universe="uni2")
    monkeypatch.setenv("GC_NETWORK_UNIVERSES", "uni1,uni2")
    monkeypatch.setenv("GC_NETWORK_UNI2_OPEN", "0")
    monkeypatch.setenv("PUBLIC_BASE_URL", UNI2_URL)

    assert _validate_network_runtime_config() == []


def test_future_universe_role_must_be_registered(monkeypatch):
    _set_network_base(monkeypatch, universe="uni2")
    monkeypatch.setenv("GC_NETWORK_UNIVERSES", "uni1")
    monkeypatch.setenv("PUBLIC_BASE_URL", UNI2_URL)

    errors = _validate_network_runtime_config()

    assert any("GC_NETWORK_UNIVERSES" in error for error in errors)


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


def test_canonical_origin_hook_runs_before_network_auth():
    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    canonical_hook = app_source.index("def _canonical_public_origin_redirect")
    network_install = app_source.index("install_network_auth(app)")

    assert canonical_hook < network_install


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
