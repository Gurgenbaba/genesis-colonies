"""Expedition-XP telemetry queries: they run on the real activity_xp_log schema, read only, and give the right numbers.  Sandbox only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import expedition_xp_telemetry as t

ROOT = Path(__file__).resolve().parent.parent
SINCE = 1_000.0


def build(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    schema = (ROOT / "migrations" / "085_activity_xp_log.sql").read_text(encoding="utf-8")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE planets (id INTEGER PRIMARY KEY, player_id INTEGER)")
    conn.executescript(schema)  # the real table definition, so the queries cannot drift from the migration
    for pid in (1, 2, 3):
        conn.execute("INSERT INTO users (id) VALUES (?)", (pid,))
    conn.executemany("INSERT INTO planets (id, player_id) VALUES (?, ?)", [(10, 1), (11, 1), (20, 2), (30, 3)])

    def xp(player, planet, src, amount, day, ts):
        conn.execute("INSERT INTO activity_xp_log (player_id, planet_id, source_key, amount, day_bucket, created_at) VALUES (?, ?, ?, ?, ?, ?)", (player, planet, src, amount, day, ts))

    for i in range(10):  # player 1 flies 10 expeditions on day 5 from the colony (planet 11): 150 XP + one +75 bonus
        xp(1, 11, "expedition", 15, 5, 2_000.0 + i)
    xp(1, 11, "expedition_bonus", 75, 5, 2_100.0)
    xp(1, 10, "building_finish", 3, 5, 2_200.0)
    xp(2, 20, "expedition", 15, 6, 2_300.0)  # player 2: one expedition from the first planet
    xp(2, 20, "building_finish", 3, 6, 2_301.0)
    xp(3, 30, "building_finish", 3, 7, 2_400.0)  # player 3 never flies
    xp(1, 11, "expedition", 15, 1, 100.0)  # before ``since``
    conn.commit()
    return conn


def test_queries_run_on_the_real_schema_and_summarize_correctly(tmp_path: Path):
    conn = build(str(tmp_path / "x.sqlite"))
    out = t.run(conn, SINCE)
    s = t.summarize(out)
    assert s["players"] == 3 and s["players_with_expedition_xp"] == 2
    assert s["expedition_share_of_activity_xp"] == pytest.approx((150 + 75 + 15) / (150 + 75 + 3 + 15 + 3 + 3))
    assert s["landing"]["later_planet"] == {"grants": 11, "xp": 225} and s["landing"]["first_planet"] == {"grants": 1, "xp": 15}
    assert s["share_of_expedition_xp_on_later_planets"] == pytest.approx(225 / 240)
    assert s["expeditions_per_active_day_median"] == 10 and s["expeditions_per_active_day_p90"] == 10  # two flying players: one flies 1/day, one 10/day
    conn.close()


def test_cli_prints_sql_and_reads_a_copy_read_only(tmp_path: Path, capsys):
    assert t.main(["--print-sql"]) == 0 and "FROM activity_xp_log" in capsys.readouterr().out
    path = tmp_path / "copy.sqlite"
    build(str(path)).close()
    assert t.main(["--db", str(path), "--days", "36500"]) == 0
    assert "players_with_expedition_xp: 2" in capsys.readouterr().out
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO users (id) VALUES (99)")  # the access mode the CLI uses cannot write
    ro.close()
