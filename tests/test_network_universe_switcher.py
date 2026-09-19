from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_universe_switcher_is_mounted_in_global_header():
    base = _read("templates/base.html")
    assert 'partials/header_universe_switcher.html' in base


def test_universe_switcher_uses_server_owned_network_targets():
    partial = _read("templates/partials/header_universe_switcher.html")
    assert "GC_NETWORK_UNIVERSE_KEY" in partial
    assert "GC_NETWORK_UNI1_OPEN" in partial
    assert "network_universe_enter" in partial
    assert "GC_NETWORK_AUTHORITY_URL" in partial
    assert "window.location.assign(target)" in partial


def test_network_auth_exposes_shell_context():
    owner = _read("game/network_auth.py")
    for key in (
        "GC_NETWORK_ENABLED",
        "GC_NETWORK_UNIVERSE_KEY",
        "GC_NETWORK_AUTHORITY_URL",
        "GC_NETWORK_UNI1_URL",
        "GC_NETWORK_UNI1_OPEN",
    ):
        assert f'app.jinja_env.globals["{key}"]' in owner
