from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RANKING = ROOT / "game" / "ranking.py"
THREAT = ROOT / "game" / "pirates" / "threat.py"
TEST_RANKING = ROOT / "tests" / "test_ranking.py"
TEST_GC622 = ROOT / "tests" / "test_gc622_integer_overflow.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def patch_ranking() -> None:
    source = RANKING.read_text(encoding="utf-8")

    source = replace_once(
        source,
        '''def _all_score_rows_exact(conn) -> List[Dict[str, Any]]:\n    return _fetch_all_score_rows(conn)\n''',
        '''def _all_score_rows_exact(conn) -> List[Dict[str, Any]]:\n    """Pure read of every score row; ranking GET paths must never seed/write rows."""\n    resources_sel = _resources_score_select(conn)\n    fleet_defense_sel = _fleet_defense_select(conn)\n    evolution_sel = _evolution_score_select(conn)\n    combat_sel = _combat_ranking_select(conn)\n    destroyed_raw_sel = (\n        "COALESCE(ps.score_destroyed_raw, 0) AS score_destroyed_raw"\n        if column_exists(conn, "player_scores", "score_destroyed_raw")\n        else "0 AS score_destroyed_raw"\n    )\n    rows = conn.execute(\n        f"""\n        SELECT\n            p.id AS player_id,\n            p.name AS commander_name,\n            COALESCE(ps.score_total, '0') AS score_total,\n            {resources_sel},\n            COALESCE(ps.score_buildings, '0') AS score_buildings,\n            COALESCE(ps.score_research, '0') AS score_research,\n            {fleet_defense_sel},\n            {evolution_sel},\n            {combat_sel},\n            {destroyed_raw_sel}\n        FROM players p\n        LEFT JOIN player_scores ps ON ps.player_id = p.id\n        ORDER BY p.id ASC\n        """\n    ).fetchall()\n    out: List[Dict[str, Any]] = []\n    for raw in rows:\n        d = dict(raw)\n        normalized = _normalize_db_row(d)\n        out.append({\n            "player_id": int(d["player_id"]),\n            "commander_name": d.get("commander_name") or "—",\n            **normalized,\n        })\n    return out\n''',
        "pure-read exact score rows",
    )

    old_select = '''            SELECT\n                COALESCE(ps.score_total, 0) AS score_total,\n                COALESCE(ps.score_buildings, 0) AS score_buildings,\n                COALESCE(ps.score_research, 0) AS score_research,\n                {_fleet_defense_select(conn)},\n                {_evolution_score_select(conn)}\n            FROM players p\n'''
    new_select = '''            SELECT\n                COALESCE(ps.score_total, '0') AS score_total,\n                {_resources_score_select(conn)},\n                COALESCE(ps.score_buildings, '0') AS score_buildings,\n                COALESCE(ps.score_research, '0') AS score_research,\n                {_fleet_defense_select(conn)},\n                {_evolution_score_select(conn)},\n                {_combat_ranking_select(conn)},\n                {("COALESCE(ps.score_destroyed_raw, 0) AS score_destroyed_raw" if column_exists(conn, "player_scores", "score_destroyed_raw") else "0 AS score_destroyed_raw")}\n            FROM players p\n'''
    source = replace_once(source, old_select, new_select, "read_player_scores full score projection")

    compile(source, str(RANKING), "exec")
    RANKING.write_text(source, encoding="utf-8")


def patch_threat() -> None:
    source = THREAT.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''        total = float(row["score_total"] or 0)\n        fleet = float(row["score_fleet"] or 0)\n        defense = float(row["score_defense"] or 0)\n        destroyed = float(row["score_destroyed"] or 0)\n        # Soft log scales so midgame players climb without instantly hitting 100.\n        import math\n\n        components["empire"] = min(35.0, math.log10(max(1.0, total)) * 8.0)\n        components["fleet"] = min(25.0, math.log10(max(1.0, fleet)) * 6.0)\n        components["defense"] = min(15.0, math.log10(max(1.0, defense)) * 4.0)\n        components["combat"] = min(25.0, math.log10(max(1.0, destroyed)) * 5.0)\n''',
        '''        # Ranking values are decimal TEXT and may be far beyond IEEE-754.\n        # Keep them as Python ints; math.log10 accepts arbitrary-size ints and the\n        # resulting threat components are immediately capped to small floats.\n        total = max(0, int(row["score_total"] or 0))\n        fleet = max(0, int(row["score_fleet"] or 0))\n        defense = max(0, int(row["score_defense"] or 0))\n        destroyed = max(0, int(row["score_destroyed"] or 0))\n        import math\n\n        components["empire"] = min(35.0, math.log10(max(1, total)) * 8.0)\n        components["fleet"] = min(25.0, math.log10(max(1, fleet)) * 6.0)\n        components["defense"] = min(15.0, math.log10(max(1, defense)) * 4.0)\n        components["combat"] = min(25.0, math.log10(max(1, destroyed)) * 5.0)\n''',
        "pirate threat bigint conversion",
    )
    compile(source, str(THREAT), "exec")
    THREAT.write_text(source, encoding="utf-8")


def patch_ranking_tests() -> None:
    source = TEST_RANKING.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        assert normalized["total_score"] == normalized["resource_score"]\n',
        '        assert normalized["total_score"] == (normalized["building_score"] + normalized["research_score"] + normalized["fleet_score"] + normalized["defense_score"] + normalized["evolution_score"])\n',
        "combat test progression total expectation",
    )

    marker = "# GC-SCORE-BIGNUM live hardening coverage\n"
    if marker not in source:
        source += '''\n\n# GC-SCORE-BIGNUM live hardening coverage\n\ndef test_big_score_rank_reads_never_seed_score_rows(temp_db):\n    from game.ranking import get_player_category_ranks, get_player_rank_from_snapshot\n\n    _run_migrate(temp_db)\n    init_db()\n    _close_db()\n    pid = _create_player("rank_read_only")\n    conn = db()\n    conn.execute("DELETE FROM player_scores WHERE player_id = ?", (pid,))\n    conn.commit()\n    conn.close()\n\n    with patch("game.ranking._ensure_score_rows") as ensure_rows:\n        rank, total = get_player_rank_from_snapshot(pid)\n        ranks = get_player_category_ranks(pid)\n        ensure_rows.assert_not_called()\n    assert rank is not None\n    assert total >= 1\n    assert ranks["total_players"] >= 1\n\n    conn = db()\n    persisted = conn.execute("SELECT 1 FROM player_scores WHERE player_id = ?", (pid,)).fetchone()\n    conn.close()\n    assert persisted is None\n\n\ndef test_read_player_scores_preserves_combat_and_destroyed_fields(temp_db):\n    from game.ranking import read_player_scores\n\n    _run_migrate(temp_db)\n    init_db()\n    _close_db()\n    pid = _create_player("score_projection")\n    upsert_player_scores(pid, {\n        "building_score": 10,\n        "research_score": 20,\n        "fleet_score": 30,\n        "defense_score": 40,\n        "destroyed_raw": 123456789,\n        "destroyed_score": 123456789,\n    })\n    scores = read_player_scores(pid)\n    assert scores["total_score"] == 100\n    assert scores["combat_score"] == 70\n    assert scores["destroyed_score"] == 123456789\n    assert scores["destroyed_raw"] == 123456789\n\n\ndef test_pirate_threat_accepts_scores_far_beyond_float(temp_db):\n    from game.pirates.threat import recompute_player_threat, threat_schema_ready\n\n    _run_migrate(temp_db)\n    init_db()\n    _close_db()\n    pid = _create_player("huge_threat")\n    conn = db()\n    if not threat_schema_ready(conn):\n        conn.close()\n        pytest.skip("pirate threat schema unavailable")\n    huge = 10**500\n    upsert_player_scores(pid, {\n        "building_score": huge,\n        "fleet_score": huge,\n        "defense_score": huge,\n        "destroyed_score": huge,\n        "destroyed_raw": huge,\n    }, conn=conn)\n    result = recompute_player_threat(pid, conn=conn)\n    conn.commit()\n    conn.close()\n    assert 0 <= result["threat"] <= 100\n'''
    TEST_RANKING.write_text(source, encoding="utf-8")


def patch_gc622_tests() -> None:
    source = TEST_GC622.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''    def test_player_scores_use_integer(self, gc622_db):\n        for col in (\n            "score_total",\n            "score_buildings",\n            "score_research",\n            "score_fleet",\n            "score_defense",\n        ):\n            assert _column_type("player_scores", col) == "INTEGER"\n''',
        '''    def test_player_scores_use_decimal_text(self, gc622_db):\n        for col in (\n            "score_total",\n            "score_resources",\n            "score_buildings",\n            "score_research",\n            "score_fleet",\n            "score_defense",\n            "score_planet_evolution",\n            "score_destroyed_raw",\n            "score_combat",\n            "score_destroyed",\n        ):\n            assert _column_type("player_scores", col) == "TEXT"\n''',
        "GC622 score schema expectation",
    )
    marker = "    def test_ranking_above_int64_roundtrips_as_decimal_text"
    if marker not in source:
        anchor = '''    def test_ranking_above_int32_max_not_clamped_to_int32(self, gc622_db):\n        uid = _player()\n        target = INT32_MAX + 1\n        upsert_player_scores(\n            uid,\n            {"total_score": target, "building_score": target, "research_score": 0},\n        )\n        row = get_player_score_row(uid)\n        assert int(row["score_buildings"]) == target\n'''
        addition = anchor + '''\n    def test_ranking_above_int64_roundtrips_as_decimal_text(self, gc622_db):\n        uid = _player()\n        target = 10**50 + 987654321\n        upsert_player_scores(uid, {"building_score": target, "research_score": 7})\n        row = get_player_score_row(uid)\n        assert row["score_buildings"] == str(target)\n        assert row["score_total"] == str(target + 7)\n'''
        source = replace_once(source, anchor, addition, "GC622 >int64 regression")
    TEST_GC622.write_text(source, encoding="utf-8")


def verify() -> None:
    ranking = RANKING.read_text(encoding="utf-8")
    assert "return _fetch_all_score_rows(conn)" not in ranking
    assert "from . import _ranking_core" not in ranking
    assert "MAX_SCORE =" not in ranking
    assert 'float(row["score_total"]' not in THREAT.read_text(encoding="utf-8")
    compile(ranking, str(RANKING), "exec")


if __name__ == "__main__":
    patch_ranking()
    patch_threat()
    patch_ranking_tests()
    patch_gc622_tests()
    verify()
    print("GC-SCORE-BIGNUM live hardening applied successfully")
