"""GC-TRAIT-R2C: transactional, paid DNA analysis and reveal boundaries."""

import json
import sqlite3
from pathlib import Path

import pytest

from game.planet_evolution import dna_analysis
from game.planet_evolution.planet_level import xp_threshold_for_level

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def conn(monkeypatch):
    c = sqlite3.connect(":memory:", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE planets (
          id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL,
          planet_level INTEGER NOT NULL DEFAULT 1, planet_xp INTEGER NOT NULL DEFAULT 0,
          dna_reveal_tier INTEGER NOT NULL DEFAULT 0, metal INTEGER NOT NULL DEFAULT 0,
          crystal INTEGER NOT NULL DEFAULT 0, galaxy INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE planet_legacy_tags (
          planet_id INTEGER NOT NULL, tag_key TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 1,
          first_at REAL NOT NULL, last_at REAL NOT NULL, PRIMARY KEY(planet_id, tag_key)
        );
        CREATE TABLE planet_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, planet_id INTEGER NOT NULL,
          event_type TEXT NOT NULL, history_tag TEXT, title_key TEXT NOT NULL,
          body_key TEXT, payload_json TEXT NOT NULL DEFAULT '{}',
          visibility TEXT NOT NULL DEFAULT 'owner', created_at REAL NOT NULL
        );
        """
    )
    sql = (ROOT / "migrations" / "188_planet_dna_analysis.sql").read_text(encoding="utf-8")
    c.executescript(sql)
    c.execute(
        "INSERT INTO planets (id, player_id, planet_level, planet_xp, dna_reveal_tier, metal, crystal) "
        "VALUES (5, 9, 9, ?, 1, 500000, 500000)",
        (xp_threshold_for_level(9),),
    )
    monkeypatch.setattr(dna_analysis, "invalidate_player_score_cache", lambda _: None)
    monkeypatch.setattr(dna_analysis, "compile_planet_mechanics", lambda *_: None)
    yield c
    c.close()


def test_analysis_spends_once_and_uses_canonical_planet_xp(conn):
    prior = dict(conn.execute("SELECT * FROM planets WHERE id=5").fetchone())
    ok, reason, data = dna_analysis.perform_scan(5, player_id=9, now=500000, conn=conn)
    assert (ok, reason) == (True, "ok")
    new = dict(conn.execute("SELECT * FROM planets WHERE id=5").fetchone())
    cost = dna_analysis.scan_cost(9)
    assert new["metal"] == prior["metal"] - cost["metal"]
    assert new["crystal"] == prior["crystal"] - cost["crystal"]
    assert new["planet_xp"] == prior["planet_xp"] + 120
    assert data["xp_gained"] == 120
    assert int(conn.execute("SELECT scan_count FROM planet_dna_analysis WHERE planet_id=5").fetchone()[0]) == 1

    again = dna_analysis.perform_scan(5, player_id=9, now=500001, conn=conn)
    assert (again[0], again[1]) == (False, "cooldown")
    still = dict(conn.execute("SELECT * FROM planets WHERE id=5").fetchone())
    assert still == new
    assert dna_analysis.scan_status(5, conn=conn, now=500001)["remaining_seconds"] == 86399


def test_analysis_rollover_after_24h_is_exact_and_not_double_credited(conn):
    assert dna_analysis.perform_scan(5, player_id=9, now=300000, conn=conn)[0]
    assert dna_analysis.perform_scan(5, player_id=9, now=386399.99, conn=conn)[1] == "cooldown"
    assert dna_analysis.perform_scan(5, player_id=9, now=386400, conn=conn)[0]
    assert conn.execute("SELECT scan_count FROM planet_dna_analysis WHERE planet_id=5").fetchone()[0] == 2


def test_analysis_wrong_owner_unestablished_and_insufficient_resources_do_not_mutate(conn):
    initial = dict(conn.execute("SELECT * FROM planets WHERE id=5").fetchone())
    assert dna_analysis.perform_scan(5, player_id=10, now=700000, conn=conn)[1] == "not_owner"
    conn.execute("UPDATE planets SET dna_reveal_tier=0 WHERE id=5")
    assert dna_analysis.perform_scan(5, player_id=9, now=700000, conn=conn)[1] == "dna_not_revealed"
    assert dna_analysis.scan_status(5, conn=conn)["visible"] is False
    conn.execute("UPDATE planets SET dna_reveal_tier=1, metal=0 WHERE id=5")
    assert dna_analysis.perform_scan(5, player_id=9, now=700000, conn=conn)[1] == "not_enough_resources"
    assert conn.execute("SELECT COUNT(*) FROM planet_dna_analysis").fetchone()[0] == 0
    assert conn.execute("SELECT planet_xp FROM planets WHERE id=5").fetchone()[0] == initial["planet_xp"]


def test_analysis_crosses_level15_via_existing_unlock_without_reroll(conn):
    conn.execute(
        "UPDATE planets SET planet_level=14, planet_xp=?, dna_reveal_tier=1 WHERE id=5",
        (xp_threshold_for_level(15) - 60,),
    )
    before = conn.execute("SELECT planet_xp FROM planets WHERE id=5").fetchone()[0]
    ok, reason, result = dna_analysis.perform_scan(5, player_id=9, now=900000, conn=conn)
    assert ok and reason == "ok"
    planet = conn.execute("SELECT planet_level, planet_xp, dna_reveal_tier FROM planets WHERE id=5").fetchone()
    assert planet["planet_level"] == 15
    assert planet["planet_xp"] == before + 120
    assert planet["dna_reveal_tier"] == 2
    assert conn.execute("SELECT COUNT(*) FROM planet_history WHERE event_type='level_up'").fetchone()[0] == 1


def test_scan_template_endpoint_and_locales_contract():
    tpl = (ROOT / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "js" / "core" / "gc.js").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'data-gc-dna-scan-planet="{{ ps.planet_id }}"' in tpl
    assert "if dna_scan.visible" in tpl and "if dna_scan.ready" in tpl
    assert "/api/planets/<int:planet_id>/dna-analysis" in app
    assert "perform_scan(int(planet_id), player_id=user_id)" in app
    assert "GC.reloadCurrentPage({ force: true })" in js
    assert 'button.dataset.scanBusy === "1"' in js
    for name in ("de", "en", "fr", "es", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{name}.json").read_text(encoding="utf-8"))
        assert set(("pe_dna_scan_title", "pe_dna_scan_hint", "pe_dna_scan_cost",
                    "pe_dna_scan_action", "pe_dna_scan_cooldown",
                    "pe_dna_scan_success", "pe_dna_scan_error")).issubset(data)
        assert data["pe_dna_scan_cost"].count("%(metal)s") == 1
        assert data["pe_dna_scan_cost"].count("%(crystal)s") == 1
        assert data["pe_dna_scan_cooldown"].count("%(hours)s") == 1
