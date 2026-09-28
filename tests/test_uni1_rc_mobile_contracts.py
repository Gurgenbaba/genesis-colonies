"""UNI1 launch contracts for rendered mobile shell and canonical storage copy."""

import json
from pathlib import Path

from tests.test_gc_p0_mobile_nav_drawer import _app_client, _create_player


ROOT = Path(__file__).resolve().parents[1]


def test_uni1_rendered_shell_has_single_landscape_preload(gc_p0_mobile_db, monkeypatch):
    _, uname = _create_player()
    client = _app_client(monkeypatch)
    login = client.post("/login", data={"username": uname, "password": "test-pass-123"})
    assert login.status_code in (200, 302)
    html = client.get("/overview").get_data(as_text=True)
    assert html.count('id="gc-planet-landscape-preload"') <= 1


def test_uni1_storage_copy_matches_current_10pct_rule():
    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "10 %" in de["desc_storage_tech"]
    assert "Lager" in de["desc_storage_tech"]
    assert "10%" in en["desc_storage_tech"]
    assert "storage" in en["desc_storage_tech"].lower()
