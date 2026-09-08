from __future__ import annotations

from pathlib import Path

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parent.parent


def test_pjax_shell_context_skips_redundant_auth_and_settings_checkouts(game_client, monkeypatch):
    import app as app_module

    client, _uid = game_client

    def forbidden(*_args, **_kwargs):
        raise AssertionError("PJAX context processor must reuse the login guard and persistent shell")

    # These aliases are owned by inject_globals(). Domain modules may still read
    # settings through the request-owned connection when their page data needs it.
    monkeypatch.setattr(app_module, "get_current_user", forbidden)
    monkeypatch.setattr(app_module, "get_game_settings", forbidden)

    response = client.get("/buildings", headers={"X-PJAX": "1"})
    assert response.status_code == 200
    assert b'id="main-content"' in response.data


def test_pjax_shell_context_contract_is_guarded_in_source():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    block = src.split("def inject_globals():", 1)[1].split(
        "# --------------------------------------------------------------------------\n# BOOTSTRAP",
        1,
    )[0]

    assert "pjax_layout = _is_pjax_request()" in block
    assert 'getattr(_flask_g, "player", None)' in block
    assert 'settings = {} if pjax_layout else (get_game_settings() or {})' in block
