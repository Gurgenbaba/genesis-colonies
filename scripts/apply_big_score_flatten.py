from __future__ import annotations

from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "game" / "_ranking_core.py"
RANKING = ROOT / "game" / "ranking.py"
MAIN_JS = ROOT / "static" / "main.js"
TEST_RANKING = ROOT / "tests" / "test_ranking.py"
TEST_NUMBER = ROOT / "tests" / "test_number_format.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def flatten_ranking() -> None:
    if not CORE.exists():
        raise RuntimeError("game/_ranking_core.py missing; refusing non-deterministic apply")
    source = CORE.read_text(encoding="utf-8")

    source = replace_once(
        source,
        "Wealth score (``total_score``) = resources + buildings + research + fleet + defense + evolution\n(computed via ``game.resource_score`` — canonical 1500/1000/500 divisors).",
        "Progression score (``total_score``) = buildings + research + fleet + defense + evolution.\nLiquid resources remain a separate ``resource_score`` wealth dimension and never increase progression rank.",
        "ranking module contract",
    )
    source = re.sub(
        r"\n# Max stored score \(JSON / int64-safe for clients\)\.\nMAX_SCORE = 9_000_000_000_000_000\n",
        "\n",
        source,
        count=1,
    )
    if "MAX_SCORE =" in source:
        raise RuntimeError("legacy MAX_SCORE assignment survived flatten")

    source = replace_once(
        source,
        "def get_sorted_ranking_entries(\n",
        "def _get_sorted_ranking_entries_enriched_sql(\n",
        "legacy enriched ranking function rename",
    )
    source = replace_once(
        source,
        "def build_ranking_api_payload(\n",
        "def _build_ranking_api_payload_raw(\n",
        "raw API payload function rename",
    )

    overrides = r'''

# ============================================================================
# GC-SCORE-BIGNUM — canonical arbitrary-precision score semantics
# Keep this in the single ranking owner so every legacy call resolves these
# globals dynamically; do not split score semantics into a parallel module.
# ============================================================================
JS_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_SQL_ALL_ROWS_LIMIT = 2_147_483_647


def _safe_int(value: Any, *, default: int = 0) -> int:
    """Parse a non-negative score with no gameplay ceiling."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, n)


def _sanitize_scores(scores: Dict[str, Any]) -> Dict[str, int]:
    """Normalize components and derive progression-only total score."""
    resources = _safe_int(scores.get("resource_score", scores.get("score_resources", 0)))
    building = _safe_int(scores.get("building_score", scores.get("score_buildings", 0)))
    research = _safe_int(scores.get("research_score", scores.get("score_research", 0)))
    fleet = _safe_int(scores.get("fleet_score", scores.get("score_fleet", 0)))
    defense = _safe_int(scores.get("defense_score", scores.get("score_defense", 0)))
    destroyed = _safe_int(scores.get("destroyed_score", scores.get("score_destroyed", 0)))
    evolution = _safe_int(scores.get("evolution_score", scores.get("score_planet_evolution", 0)))
    from .scoring import compute_combat_score, compute_military_score

    combat = _safe_int(
        scores.get("combat_score", scores.get("score_combat", compute_combat_score(fleet, defense)))
    )
    destroyed_raw = _safe_int(scores.get("destroyed_raw", scores.get("score_destroyed_raw", 0)))
    total = building + research + fleet + defense + evolution
    return {
        "total_score": total,
        "resource_score": resources,
        "building_score": building,
        "research_score": research,
        "fleet_score": fleet,
        "defense_score": defense,
        "combat_score": combat,
        "destroyed_score": destroyed,
        "destroyed_raw": destroyed_raw,
        "military_score": compute_military_score(fleet, defense, destroyed),
        "evolution_score": evolution,
    }


def _score_db_value(value: Any) -> str:
    return str(_safe_int(value))


def _score_json_value(value: Any) -> int | str:
    n = _safe_int(value)
    return n if n <= JS_MAX_SAFE_INTEGER else str(n)


def _json_safe_bigints(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value if -JS_MAX_SAFE_INTEGER <= value <= JS_MAX_SAFE_INTEGER else str(value)
    if isinstance(value, list):
        return [_json_safe_bigints(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_json_safe_bigints(v) for v in value)
    if isinstance(value, dict):
        return {k: _json_safe_bigints(v) for k, v in value.items()}
    return value


def format_scores_for_playercard(normalized: Dict[str, int]) -> Dict[str, Any]:
    values = {
        "score_total": normalized.get("total_score", 0),
        "score_resources": normalized.get("resource_score", 0),
        "score_buildings": normalized.get("building_score", 0),
        "score_research": normalized.get("research_score", 0),
        "score_fleet": normalized.get("fleet_score", 0),
        "score_defense": normalized.get("defense_score", 0),
        "score_combat": normalized.get("combat_score", 0),
        "score_destroyed": normalized.get("destroyed_score", 0),
        "score_military": normalized.get("military_score", 0),
        "score_planet_evolution": normalized.get("evolution_score", 0),
        "total_score": normalized.get("total_score", 0),
        "resource_score": normalized.get("resource_score", 0),
        "building_score": normalized.get("building_score", 0),
        "research_score": normalized.get("research_score", 0),
        "fleet_score": normalized.get("fleet_score", 0),
        "defense_score": normalized.get("defense_score", 0),
        "combat_score": normalized.get("combat_score", 0),
        "destroyed_score": normalized.get("destroyed_score", 0),
        "military_score": normalized.get("military_score", 0),
        "evolution_score": normalized.get("evolution_score", 0),
    }
    return {key: _score_json_value(value) for key, value in values.items()}


def _total_score_sql(conn) -> str:
    """Select persisted total only; never coerce decimal score TEXT in SQL."""
    return "COALESCE(ps.score_total, '0')"


def upsert_player_scores(player_id: int, scores: Dict[str, int], conn=None) -> None:
    """Persist score fields as decimal TEXT without sqlite3 int64 bindings."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        clean = _sanitize_scores(scores)
        stored = {key: _score_db_value(value) for key, value in clean.items()}
        field_map = [
            ("score_total", "total_score"),
            ("score_resources", "resource_score"),
            ("score_buildings", "building_score"),
            ("score_research", "research_score"),
            ("score_fleet", "fleet_score"),
            ("score_defense", "defense_score"),
            ("score_planet_evolution", "evolution_score"),
            ("score_destroyed_raw", "destroyed_raw"),
            ("score_combat", "combat_score"),
            ("score_destroyed", "destroyed_score"),
        ]
        active = [(column, key) for column, key in field_map if column_exists(conn, "player_scores", column)]
        columns = [column for column, _ in active]
        params = [int(player_id)] + [stored[key] for _, key in active]
        insert_columns = ", ".join(["player_id", *columns, "updated_at"])
        placeholders = ", ".join(["?"] * (1 + len(columns)) + ["strftime('%s','now')"])
        updates = ", ".join([f"{column}=excluded.{column}" for column in columns] + ["updated_at=excluded.updated_at"])
        conn.execute(
            f"INSERT INTO player_scores ({insert_columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(player_id) DO UPDATE SET {updates}",
            tuple(params),
        )
        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


def _all_score_rows_exact(conn) -> List[Dict[str, Any]]:
    return _fetch_all_score_rows(conn)


def get_sorted_ranking_entries(limit: int = 100, offset: int = 0, conn=None) -> List[Dict[str, Any]]:
    """Reuse mature enrichment, then sort the complete set with Python ints."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        rows = _get_sorted_ranking_entries_enriched_sql(limit=_SQL_ALL_ROWS_LIMIT, offset=0, conn=conn)
        rows.sort(key=lambda r: (
            -_safe_int(r.get("total_score")),
            -_safe_int(r.get("building_score")),
            -_safe_int(r.get("research_score")),
            int(r.get("player_id") or 0),
        ))
        for idx, row in enumerate(rows, start=1):
            row["rank"] = idx
        start = max(0, int(offset))
        return rows[start:start + max(0, int(limit))]
    finally:
        if owns_conn:
            conn.close()


def get_player_rank_from_snapshot(player_id: int, conn=None) -> Tuple[Optional[int], int]:
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        rows = _all_score_rows_exact(conn)
        rows.sort(key=lambda r: (-r["total_score"], -r["building_score"], -r["research_score"], r["player_id"]))
        pid = int(player_id)
        for idx, row in enumerate(rows, start=1):
            if row["player_id"] == pid:
                return idx, len(rows)
        return None, len(rows)
    finally:
        if owns_conn:
            conn.close()


def get_player_category_ranks(player_id: int, conn=None, *, skip_live_total: bool = False) -> Dict[str, Any]:
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        rows = _all_score_rows_exact(conn)
        pid = int(player_id)
        ranks: Dict[str, Any] = {"total_players": len(rows)}
        if not any(row["player_id"] == pid for row in rows):
            return ranks

        def assign(name: str, key) -> None:
            for idx, row in enumerate(sorted(rows, key=key), start=1):
                if row["player_id"] == pid:
                    ranks[name] = idx
                    return

        assign("building", lambda r: (-r["building_score"], -r["research_score"], r["player_id"]))
        assign("research", lambda r: (-r["research_score"], -r["building_score"], r["player_id"]))
        assign("fleet", lambda r: (-r["fleet_score"], -r["building_score"], r["player_id"]))
        assign("defense", lambda r: (-r["defense_score"], r["player_id"]))
        assign("combat", lambda r: (-r.get("combat_score", 0), -r["fleet_score"], r["player_id"]))
        assign("destroyed", lambda r: (-r.get("destroyed_score", 0), -r["fleet_score"], r["player_id"]))
        assign("military", lambda r: (-r.get("military_score", 0), -r["fleet_score"], r["player_id"]))
        assign("evolution", lambda r: (-r.get("evolution_score", 0), r["player_id"]))
        if not skip_live_total:
            assign("total", lambda r: (-r["total_score"], -r["building_score"], -r["research_score"], r["player_id"]))
        return ranks
    finally:
        if owns_conn:
            conn.close()


def get_sorted_alliance_ranking_entries(limit: int = 100, offset: int = 0, conn=None) -> List[Dict[str, Any]]:
    """Aggregate member score TEXT in Python; SQLite never SUMs huge scores."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        if not (table_exists(conn, "alliances") and table_exists(conn, "alliance_members") and table_exists(conn, "player_scores")):
            return []
        rows = conn.execute(
            """
            SELECT a.id AS alliance_id, a.tag AS alliance_tag, a.name AS alliance_name,
                   am.player_id AS player_id, COALESCE(ps.score_total, '0') AS score_total
            FROM alliances a
            INNER JOIN alliance_members am ON am.alliance_id = a.id
            LEFT JOIN player_scores ps ON ps.player_id = am.player_id
            ORDER BY a.id ASC, am.player_id ASC
            """
        ).fetchall()
        grouped: Dict[int, Dict[str, Any]] = {}
        for raw in rows:
            d = dict(raw)
            aid = int(d["alliance_id"])
            item = grouped.setdefault(aid, {
                "alliance_id": aid,
                "alliance_tag": str(d.get("alliance_tag") or "").strip(),
                "alliance_name": str(d.get("alliance_name") or "").strip(),
                "member_count": 0,
                "alliance_score": 0,
                "is_current_alliance": False,
            })
            item["member_count"] += 1
            item["alliance_score"] += _safe_int(d.get("score_total"))
        ordered = sorted(grouped.values(), key=lambda r: (-r["alliance_score"], r["alliance_id"]))
        for idx, row in enumerate(ordered, start=1):
            row["rank"] = idx
        start = max(0, int(offset))
        return ordered[start:start + max(0, int(limit))]
    finally:
        if owns_conn:
            conn.close()


def get_player_alliance_ranking_snapshot(player_id: int, conn=None) -> Dict[str, Any]:
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        empty = {"alliance_id": None, "alliance_tag": "", "alliance_name": "", "alliance_score": 0,
                 "alliance_rank": None, "total_alliances": 0, "member_count": 0}
        if not (table_exists(conn, "alliances") and table_exists(conn, "alliance_members")):
            return empty
        mine = conn.execute(
            """SELECT a.id AS alliance_id, a.tag AS alliance_tag, a.name AS alliance_name
               FROM alliance_members am INNER JOIN alliances a ON a.id = am.alliance_id
               WHERE am.player_id = ? LIMIT 1""",
            (int(player_id),),
        ).fetchone()
        all_rows = get_sorted_alliance_ranking_entries(limit=_SQL_ALL_ROWS_LIMIT, offset=0, conn=conn)
        if not mine:
            return {**empty, "total_alliances": len(all_rows)}
        aid = int(mine["alliance_id"])
        row = next((r for r in all_rows if int(r["alliance_id"]) == aid), None)
        if row is None:
            return {**empty, "alliance_id": aid, "alliance_tag": str(mine["alliance_tag"] or ""),
                    "alliance_name": str(mine["alliance_name"] or ""), "total_alliances": len(all_rows)}
        return {
            "alliance_id": aid,
            "alliance_tag": row["alliance_tag"],
            "alliance_name": row["alliance_name"],
            "alliance_score": row["alliance_score"],
            "alliance_rank": row["rank"],
            "total_alliances": len(all_rows),
            "member_count": row["member_count"],
        }
    finally:
        if owns_conn:
            conn.close()


def build_ranking_api_payload(current_player_id: int, *, limit: int = 100, refresh: bool = False) -> Dict[str, Any]:
    """Lossless JSON transport: JS-unsafe Python ints become decimal strings."""
    return _json_safe_bigints(
        _build_ranking_api_payload_raw(int(current_player_id), limit=limit, refresh=refresh)
    )
'''
    source = source.rstrip() + "\n" + textwrap.dedent(overrides).lstrip()
    compile(source, str(RANKING), "exec")
    RANKING.write_text(source, encoding="utf-8")
    CORE.unlink()


def patch_frontend() -> None:
    source = MAIN_JS.read_text(encoding="utf-8")
    start_marker = '  const _deIntFormatter = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });\n'
    end_marker = '  const GC_NUM_INPUT_SELECTOR = [\n'
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    block = r'''  const _deIntFormatter = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

  function parseIntNumber(n) {
    if (typeof n === "number" && Number.isFinite(n)) return Math.trunc(n);
    const raw = String(n ?? "").trim();
    if (!raw) return 0;
    if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
    let cleaned = raw.replace(/\s/g, "");
    if (/^-?\d{1,3}(\.\d{3})+$/.test(cleaned)) return parseInt(cleaned.replace(/\./g, ""), 10);
    if (/^-?\d{1,3}(,\d{3})+$/.test(cleaned)) return parseInt(cleaned.replace(/,/g, ""), 10);
    if (/[.,\s]/.test(raw)) {
      const digitsOnly = cleaned.replace(/[^\d-]/g, "");
      if (/^-?\d+$/.test(digitsOnly)) return parseInt(digitsOnly, 10);
    }
    if (cleaned.includes(",") && cleaned.includes(".")) cleaned = cleaned.replace(/\./g, "").replace(",", ".");
    else if ((cleaned.match(/\./g) || []).length > 1) cleaned = cleaned.replace(/\./g, "");
    else if (cleaned.includes(",")) cleaned = cleaned.replace(",", ".");
    const num = Number(cleaned);
    return Number.isFinite(num) ? Math.trunc(num) : 0;
  }

  // Display-only exact integer parser. Gameplay arithmetic intentionally remains Number-based.
  function parseDisplayBigInt(value) {
    if (typeof value === "bigint") return value;
    if (typeof value === "number") return Number.isSafeInteger(value) ? BigInt(value) : null;
    if (typeof value !== "string") return null;
    const raw = value.trim().replace(/\s+/g, "");
    if (/^-?\d+$/.test(raw)) return BigInt(raw);
    if (/^-?\d{1,3}(\.\d{3})+$/.test(raw)) return BigInt(raw.replace(/\./g, ""));
    if (/^-?\d{1,3}(,\d{3})+$/.test(raw)) return BigInt(raw.replace(/,/g, ""));
    return null;
  }

  function formatNumber(n) {
    const exact = parseDisplayBigInt(n);
    if (exact !== null) return _deIntFormatter.format(exact);
    return _deIntFormatter.format(parseIntNumber(n));
  }

  const COMPACT_THRESHOLD = 10_000_000n;

  function _compactBigIntBody(abs, div) {
    const whole = abs / div;
    const tenth = ((abs % div) * 10n) / div;
    return tenth === 0n ? String(whole) : `${whole},${tenth}`;
  }

  function _scientificBigInt(abs, negative) {
    const digits = abs.toString();
    let fraction = digits.slice(1, 3).replace(/0+$/, "");
    const mantissa = fraction ? `${digits[0]},${fraction}` : digits[0];
    return `${negative ? "-" : ""}${mantissa}e${digits.length - 1}`;
  }

  function formatNumberCompact(n) {
    const exact = parseDisplayBigInt(n);
    if (exact === null) {
      const num = parseIntNumber(n);
      if (Math.abs(num) < Number(COMPACT_THRESHOLD)) return formatNumber(num);
      return formatNumberCompact(String(Math.trunc(num)));
    }
    const negative = exact < 0n;
    const abs = negative ? -exact : exact;
    if (abs < COMPACT_THRESHOLD) return _deIntFormatter.format(exact);
    if (abs >= 1_000_000_000_000_000n) return _scientificBigInt(abs, negative);
    const sign = negative ? "-" : "";
    if (abs >= 1_000_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000_000n)} Bio.`;
    if (abs >= 1_000_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000_000n)} Mrd.`;
    if (abs >= 1_000_000n) return `${sign}${_compactBigIntBody(abs, 1_000_000n)} Mio.`;
    return `${sign}${_compactBigIntBody(abs, 1_000n)} Tsd.`;
  }

  function formatScore(n) { return formatNumberCompact(n); }
  function fmtNumber(n) { return formatNumber(n); }
  function fmtIntFull(n) { return formatNumber(n); }
  function fmtIntParts(n) {
    const full = formatNumber(n);
    const display = formatNumberCompact(n);
    return { display, full };
  }

'''
    source = source[:start] + block + source[end:]
    if "COMPACT_INFINITY" in source:
        raise RuntimeError("frontend COMPACT_INFINITY survived")
    MAIN_JS.write_text(source, encoding="utf-8")


def patch_tests() -> None:
    source = TEST_RANKING.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '    assert scores["total_score"] == expected_resources\n',
        '    assert scores["total_score"] == 0\n',
        "starter liquid wealth expectation",
    )
    marker = "# GC-SCORE-BIGNUM regression coverage\n"
    if marker not in source:
        source += r'''

# GC-SCORE-BIGNUM regression coverage

def test_big_score_has_no_ceiling_and_excludes_liquid_wealth():
    from game.ranking import _sanitize_scores

    huge = 10**50 + 123456789
    clean = _sanitize_scores({
        "resource_score": huge * 9,
        "building_score": huge,
        "research_score": 7,
        "fleet_score": 11,
        "defense_score": 13,
        "evolution_score": 17,
    })
    assert clean["resource_score"] == huge * 9
    assert clean["total_score"] == huge + 48


def test_big_score_text_roundtrip_exact_order_and_js_transport(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()
    low = _create_player("big_low")
    high = _create_player("big_high")
    base = 10**40
    _seed_scores(low, base, 1)
    _seed_scores(high, base + 1, 1)

    conn = db()
    row = conn.execute("SELECT score_total, typeof(score_total) AS kind FROM player_scores WHERE player_id = ?", (high,)).fetchone()
    conn.close()
    assert row["kind"] == "text"
    assert row["score_total"] == str(base + 2)

    payload = build_ranking_api_payload(high, limit=10, refresh=False)
    rows = [r for r in payload["top_players"] if r["player_id"] in (low, high)]
    assert [r["player_id"] for r in rows] == [high, low]
    assert rows[0]["total_score"] == str(base + 2)
    assert rows[1]["total_score"] == str(base + 1)
    assert payload["current_player"]["total_score"] == str(base + 2)


def test_big_score_schema_is_decimal_text(temp_db):
    _run_migrate(temp_db)
    init_db()
    conn = db()
    types = {row["name"]: str(row["type"]).upper() for row in conn.execute("PRAGMA table_info(player_scores)").fetchall()}
    conn.close()
    for column in (
        "score_total", "score_resources", "score_buildings", "score_research", "score_fleet",
        "score_defense", "score_planet_evolution", "score_destroyed_raw", "score_combat", "score_destroyed",
    ):
        assert types[column] == "TEXT"


def test_big_score_exact_order_with_122_players(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()
    base = 10**35
    created = []
    for idx in range(122):
        pid = _create_player(f"live_scale_{idx}")
        created.append(pid)
        _seed_scores(pid, base + idx, idx % 3)
    rows = get_sorted_ranking_entries(limit=122, offset=0)
    ranked = [r for r in rows if r["player_id"] in set(created)]
    expected = sorted(created, key=lambda pid: -(base + created.index(pid) + (created.index(pid) % 3)))
    assert [r["player_id"] for r in ranked] == expected
'''
    TEST_RANKING.write_text(source, encoding="utf-8")

    num = TEST_NUMBER.read_text(encoding="utf-8")
    if "test_huge_integer_never_becomes_fake_infinity" not in num:
        num += r'''


def test_huge_integer_never_becomes_fake_infinity():
    huge = 10**50 + 123456789
    assert fmt_int(huge).replace(".", "") == str(huge)
    compact = fmt_int_compact(huge)
    assert compact != "∞"
    assert "e50" in compact
'''
        TEST_NUMBER.write_text(num, encoding="utf-8")


def verify() -> None:
    ranking = RANKING.read_text(encoding="utf-8")
    assert "from . import _ranking_core" not in ranking
    assert "MAX_SCORE =" not in ranking
    assert not CORE.exists()
    assert "COMPACT_INFINITY" not in MAIN_JS.read_text(encoding="utf-8")
    compile(ranking, str(RANKING), "exec")


if __name__ == "__main__":
    flatten_ranking()
    patch_frontend()
    patch_tests()
    verify()
    print("GC-SCORE-BIGNUM flatten applied successfully")
