from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, got {count}")
    return text.replace(old, new, 1)


def replace_function(text: str, name: str, replacement: str) -> str:
    pattern = re.compile(
        rf"(?ms)^def {re.escape(name)}\([^\n]*(?:\n(?:    .*|\s*)*)?)(?=^def |\Z)"
    )
    match = pattern.search(text)
    if not match:
        # Signatures in ranking.py are often multiline. Use a safer next-top-level-def scan.
        start = re.search(rf"(?m)^def {re.escape(name)}\(", text)
        if not start:
            raise RuntimeError(f"function {name} not found")
        nxt = re.search(r"(?m)^def [A-Za-z_]\w*\(", text[start.end():])
        end = len(text) if nxt is None else start.end() + nxt.start()
        return text[: start.start()] + replacement.rstrip() + "\n\n" + text[end:]
    return text[: match.start()] + replacement.rstrip() + "\n\n" + text[match.end():]


def patch_ranking() -> None:
    path = "game/ranking.py"
    text = read(path)
    text = replace_once(
        text,
        "Wealth score (``total_score``) = resources + buildings + research + fleet + defense + evolution\n(computed via ``game.resource_score`` — canonical 1500/1000/500 divisors).",
        "Progression score (``total_score``) = buildings + research + fleet + defense + evolution.\nLiquid resources remain available as ``resource_score`` but do not increase progression rank.",
        label="ranking docstring",
    )
    text = replace_once(
        text,
        "# Max stored score (JSON / int64-safe for clients).\nMAX_SCORE = 9_000_000_000_000_000\n\n\n",
        "# JSON numbers above this point are serialized as decimal strings for lossless JS transport.\nJS_MAX_SAFE_INTEGER = 9_007_199_254_740_991\n\n\n",
        label="MAX_SCORE removal",
    )
    text = replace_once(
        text,
        "    if n > MAX_SCORE:\n        return MAX_SCORE\n",
        "",
        label="safe int clamp",
    )
    text = replace_once(
        text,
        "    total = _safe_int(resources + building + research + fleet + defense + evolution)\n",
        "    total = _safe_int(building + research + fleet + defense + evolution)\n",
        label="progression total",
    )

    marker = "def _sanitize_scores(scores: Dict[str, Any]) -> Dict[str, int]:\n"
    helper = '''def _score_db_value(value: Any) -> str:\n    \"\"\"Canonical arbitrary-precision score persistence: non-negative decimal TEXT.\"\"\"\n    return str(_safe_int(value))\n\n\ndef _score_json_value(value: Any) -> int | str:\n    \"\"\"Keep small scores ergonomic; stringify unsafe JS integers losslessly.\"\"\"\n    n = _safe_int(value)\n    return n if n <= JS_MAX_SAFE_INTEGER else str(n)\n\n\ndef _json_safe_bigints(value: Any) -> Any:\n    if isinstance(value, bool) or value is None:\n        return value\n    if isinstance(value, int):\n        return value if -JS_MAX_SAFE_INTEGER <= value <= JS_MAX_SAFE_INTEGER else str(value)\n    if isinstance(value, list):\n        return [_json_safe_bigints(item) for item in value]\n    if isinstance(value, tuple):\n        return tuple(_json_safe_bigints(item) for item in value)\n    if isinstance(value, dict):\n        return {key: _json_safe_bigints(item) for key, item in value.items()}\n    return value\n\n\n'''
    text = replace_once(text, marker, helper + marker, label="score helpers")

    # Store all score values as decimal text. SQLite INTEGER/REAL cannot preserve arbitrary precision.
    upsert_start = text.index("def upsert_player_scores(")
    upsert_end = text.index("\ndef refresh_player_score(", upsert_start)
    block = text[upsert_start:upsert_end]
    block = replace_once(
        block,
        "    clean = _sanitize_scores(scores)\n",
        "    clean = _sanitize_scores(scores)\n    stored = {key: _score_db_value(value) for key, value in clean.items()}\n",
        label="upsert stored map",
    )
    block = block.replace('clean["', 'stored["').replace('clean.get("', 'stored.get("')
    text = text[:upsert_start] + block + text[upsert_end:]

    # Public PlayerCard score fields must not become lossy JS Numbers.
    start = text.index("def format_scores_for_playercard(")
    end = text.index("\ndef _normalize_payload(", start)
    block = text[start:end]
    block = re.sub(r'int\(normalized\.get\(("[^"]+"), 0\) or 0\)', r'_score_json_value(normalized.get(\1, 0))', block)
    # locals can be int|string now; do not cast them back.
    block = block.replace('    fleet = int(normalized.get("fleet_score", 0) or 0)\n', '    fleet = _score_json_value(normalized.get("fleet_score", 0))\n')
    block = block.replace('    defense = int(normalized.get("defense_score", 0) or 0)\n', '    defense = _score_json_value(normalized.get("defense_score", 0))\n')
    block = block.replace('    destroyed = int(normalized.get("destroyed_score", 0) or 0)\n', '    destroyed = _score_json_value(normalized.get("destroyed_score", 0))\n')
    block = block.replace('    combat = int(normalized.get("combat_score", 0) or 0)\n', '    combat = _score_json_value(normalized.get("combat_score", 0))\n')
    block = block.replace('    military = int(normalized.get("military_score", 0) or 0)\n', '    military = _score_json_value(normalized.get("military_score", 0))\n')
    block = block.replace('def format_scores_for_playercard(normalized: Dict[str, int]) -> Dict[str, int]:', 'def format_scores_for_playercard(normalized: Dict[str, int]) -> Dict[str, Any]:')
    text = text[:start] + block + text[end:]

    # _fetch_all_score_rows is also used for read-only exact ranking paths. Seeding belongs to writers.
    text = replace_once(
        text,
        "def _fetch_all_score_rows(conn) -> List[Dict[str, Any]]:\n    _ensure_score_rows(conn)\n",
        "def _fetch_all_score_rows(conn) -> List[Dict[str, Any]]:\n",
        label="read-only score rows",
    )
    text = replace_once(
        text,
        "    def _apply() -> int:\n        rows = _fetch_all_score_rows(conn)\n",
        "    def _apply() -> int:\n        _ensure_score_rows(conn)\n        rows = _fetch_all_score_rows(conn)\n",
        label="rank writer ensure",
    )

    text = replace_function(text, "_total_score_sql", '''def _total_score_sql(conn) -> str:\n    \"\"\"Legacy SQL selector only. Never sort/add TEXT scores in SQL.\"\"\"\n    return \"COALESCE(ps.score_total, '0')\"''')

    text = replace_function(text, "get_sorted_alliance_ranking_entries", '''def get_sorted_alliance_ranking_entries(\n    limit: int = 100,\n    offset: int = 0,\n    conn=None,\n) -> List[Dict[str, Any]]:\n    \"\"\"Alliance ranking with arbitrary-precision member score aggregation in Python.\"\"\"\n    owns_conn = False\n    if conn is None:\n        conn = db()\n        owns_conn = True\n    try:\n        if not (\n            table_exists(conn, \"alliances\")\n            and table_exists(conn, \"alliance_members\")\n            and table_exists(conn, \"player_scores\")\n        ):\n            return []\n        rows = conn.execute(\n            \"\"\"\n            SELECT a.id AS alliance_id, a.tag AS alliance_tag, a.name AS alliance_name,\n                   am.player_id AS player_id, COALESCE(ps.score_total, '0') AS score_total\n            FROM alliances a\n            INNER JOIN alliance_members am ON am.alliance_id = a.id\n            LEFT JOIN player_scores ps ON ps.player_id = am.player_id\n            ORDER BY a.id ASC, am.player_id ASC\n            \"\"\"\n        ).fetchall()\n        grouped: Dict[int, Dict[str, Any]] = {}\n        for raw in rows:\n            d = dict(raw)\n            aid = int(d[\"alliance_id\"])\n            item = grouped.setdefault(\n                aid,\n                {\n                    \"alliance_id\": aid,\n                    \"alliance_tag\": str(d.get(\"alliance_tag\") or \"\").strip(),\n                    \"alliance_name\": str(d.get(\"alliance_name\") or \"\").strip(),\n                    \"member_count\": 0,\n                    \"alliance_score\": 0,\n                    \"is_current_alliance\": False,\n                },\n            )\n            item[\"member_count\"] += 1\n            item[\"alliance_score\"] += _safe_int(d.get(\"score_total\"))\n        ordered = sorted(grouped.values(), key=lambda r: (-r[\"alliance_score\"], r[\"alliance_id\"]))\n        page = ordered[max(0, int(offset)) : max(0, int(offset)) + max(0, int(limit))]\n        for idx, item in enumerate(page, start=max(0, int(offset)) + 1):\n            item[\"rank\"] = idx\n        return page\n    finally:\n        if owns_conn:\n            conn.close()''')

    text = replace_function(text, "get_player_alliance_ranking_snapshot", '''def get_player_alliance_ranking_snapshot(\n    player_id: int,\n    conn=None,\n) -> Dict[str, Any]:\n    \"\"\"Current player's alliance snapshot using exact Python big-int aggregation.\"\"\"\n    owns_conn = False\n    if conn is None:\n        conn = db()\n        owns_conn = True\n    try:\n        empty = {\n            \"alliance_id\": None, \"alliance_tag\": \"\", \"alliance_name\": \"\",\n            \"alliance_score\": 0, \"alliance_rank\": None, \"total_alliances\": 0,\n            \"member_count\": 0,\n        }\n        if not (table_exists(conn, \"alliances\") and table_exists(conn, \"alliance_members\")):\n            return empty\n        mine = conn.execute(\n            \"\"\"SELECT a.id AS alliance_id, a.tag AS alliance_tag, a.name AS alliance_name\n               FROM alliance_members am JOIN alliances a ON a.id = am.alliance_id\n               WHERE am.player_id = ? ORDER BY a.id ASC LIMIT 1\"\"\",\n            (int(player_id),),\n        ).fetchone()\n        if not mine:\n            return empty\n        aid = int(mine[\"alliance_id\"])\n        all_rows = get_sorted_alliance_ranking_entries(limit=1_000_000_000, offset=0, conn=conn)\n        match = next((r for r in all_rows if int(r[\"alliance_id\"]) == aid), None)\n        if match is None:\n            return {**empty, \"alliance_id\": aid, \"alliance_tag\": str(mine[\"alliance_tag\"] or \"\"), \"alliance_name\": str(mine[\"alliance_name\"] or \"\")}\n        return {\n            \"alliance_id\": aid,\n            \"alliance_tag\": str(match.get(\"alliance_tag\") or \"\"),\n            \"alliance_name\": str(match.get(\"alliance_name\") or \"\"),\n            \"alliance_score\": int(match.get(\"alliance_score\") or 0),\n            \"alliance_rank\": int(match[\"rank\"]),\n            \"total_alliances\": len(all_rows),\n            \"member_count\": int(match.get(\"member_count\") or 0),\n        }\n    finally:\n        if owns_conn:\n            conn.close()''')

    text = replace_function(text, "get_sorted_ranking_entries", '''def get_sorted_ranking_entries(\n    limit: int = 100,\n    offset: int = 0,\n    conn=None,\n) -> List[Dict[str, Any]]:\n    \"\"\"Exact ranking order for arbitrary-size decimal score storage.\"\"\"\n    owns_conn = False\n    if conn is None:\n        conn = db()\n        owns_conn = True\n    try:\n        cur = conn.cursor()\n        extra = _fleet_defense_select(conn)\n        resources_sel = _resources_score_select(conn)\n        evo = _evolution_score_select(conn)\n        combat_sel = _combat_ranking_select(conn)\n        vacation_sel = _vacation_mode_select(conn)\n        last_seen_sel = _last_seen_select(conn)\n        wb_sel = _world_boss_damage_select(conn)\n        social_select, social_join = _ranking_social_select_and_join(conn)\n        rank_select = \"\"\n        if column_exists(conn, \"player_scores\", \"rank_total\"):\n            rank_select = \", ps.rank_total, ps.rank_building, ps.rank_research\"\n            if column_exists(conn, \"player_scores\", \"rank_fleet\"):\n                rank_select += \", ps.rank_fleet\"\n        cur.execute(\n            f\"\"\"\n            SELECT p.id AS player_id, p.name AS commander_name,\n                   COALESCE(ps.score_total, '0') AS score_total, {resources_sel},\n                   COALESCE(ps.score_buildings, '0') AS score_buildings,\n                   COALESCE(ps.score_research, '0') AS score_research,\n                   {extra}, {evo}, {combat_sel}, {vacation_sel}, {last_seen_sel}, {wb_sel},\n                   COALESCE(ps.updated_at, 0) AS score_updated_at{rank_select},\n                   {social_select}\n            FROM players p\n            LEFT JOIN player_scores ps ON ps.player_id = p.id\n            {social_join}\n            WHERE NOT EXISTS (\n                SELECT 1 FROM users u WHERE u.id = p.id\n                  AND u.username IN ('gc_combat_bot_alpha', 'gc_combat_bot_beta')\n            )\n            \"\"\"\n        )\n        prepared: List[tuple[Dict[str, Any], Dict[str, int]]] = []\n        for raw in cur.fetchall():\n            d = dict(raw)\n            prepared.append((d, _normalize_db_row(d)))\n        prepared.sort(key=lambda pair: (\n            -pair[1][\"total_score\"], -pair[1][\"building_score\"],\n            -pair[1][\"research_score\"], int(pair[0][\"player_id\"]),\n        ))\n        start = max(0, int(offset))\n        page = prepared[start : start + max(0, int(limit))]\n        out: List[Dict[str, Any]] = []\n        now_i = int(time.time())\n        for idx, (d, scores) in enumerate(page, start=start + 1):\n            social = enrich_ranking_social_fields(d)\n            from .player_display import commander_display_name, commander_lookup_name\n            raw_name = d.get(\"commander_name\") or \"—\"\n            last_seen = int(d.get(\"last_seen\") or 0)\n            out.append({\n                \"rank\": idx, \"player_id\": int(d[\"player_id\"]),\n                \"commander_name\": commander_lookup_name(raw_name),\n                \"commander_display\": commander_display_name(raw_name),\n                \"is_current_player\": False,\n                \"rank_total\": int(d[\"rank_total\"]) if d.get(\"rank_total\") is not None else None,\n                \"rank_building\": int(d[\"rank_building\"]) if d.get(\"rank_building\") is not None else None,\n                \"rank_research\": int(d[\"rank_research\"]) if d.get(\"rank_research\") is not None else None,\n                \"rank_fleet\": int(d[\"rank_fleet\"]) if d.get(\"rank_fleet\") is not None else None,\n                \"vacation_active\": bool(int(d.get(\"vacation_mode_active\") or 0)),\n                \"last_seen\": last_seen,\n                \"inactive\": ranking_inactive_from_last_seen(last_seen, now=now_i),\n                \"world_boss_damage\": _safe_int(d.get(\"world_boss_damage\")),\n                **scores, **social,\n            })\n        try:\n            from .pirates.accounts import pirate_ai_profiles_by_ids\n            profiles = pirate_ai_profiles_by_ids([e[\"player_id\"] for e in out], conn=conn)\n        except Exception:\n            profiles = {}\n        for e in out:\n            ai = profiles.get(int(e[\"player_id\"]))\n            if not ai:\n                e[\"is_ai\"] = False\n                continue\n            e.update({\n                \"is_ai\": True, \"inactive\": False, \"player_mode\": ai.get(\"player_mode\"),\n                \"ai_kind\": ai.get(\"ai_kind\"), \"ai_faction_key\": ai.get(\"faction_key\"),\n                \"ai_personality\": ai.get(\"personality\"), \"ai_mode_key\": ai.get(\"mode_key\"),\n                \"ai_badge_key\": ai.get(\"badge_key\"), \"ai_badge_title_key\": ai.get(\"badge_title_key\"),\n            })\n            e[\"title\"] = e.get(\"title\") or \"AI\"\n        return out\n    finally:\n        if owns_conn:\n            conn.close()''')

    text = replace_function(text, "get_player_rank_from_snapshot", '''def get_player_rank_from_snapshot(player_id: int, conn=None) -> Tuple[Optional[int], int]:\n    \"\"\"Exact arbitrary-precision total-rank lookup in Python.\"\"\"\n    owns_conn = False\n    if conn is None:\n        conn = db()\n        owns_conn = True\n    try:\n        rows = _fetch_all_score_rows(conn)\n        ordered = sorted(rows, key=lambda r: (\n            -r[\"total_score\"], -r[\"building_score\"], -r[\"research_score\"], r[\"player_id\"]\n        ))\n        pid = int(player_id)\n        for idx, row in enumerate(ordered, start=1):\n            if int(row[\"player_id\"]) == pid:\n                return idx, len(ordered)\n        return None, len(ordered)\n    finally:\n        if owns_conn:\n            conn.close()''')

    text = replace_function(text, "get_player_category_ranks", '''def get_player_category_ranks(\n    player_id: int,\n    conn=None,\n    *,\n    skip_live_total: bool = False,\n) -> Dict[str, Any]:\n    \"\"\"Exact per-category ranks without SQL numeric coercion of score TEXT.\"\"\"\n    owns_conn = False\n    if conn is None:\n        conn = db()\n        owns_conn = True\n    try:\n        rows = _fetch_all_score_rows(conn)\n        pid = int(player_id)\n        if not any(int(r[\"player_id\"]) == pid for r in rows):\n            return {\"total_players\": len(rows)}\n        ranks: Dict[str, Any] = {\"total_players\": len(rows)}\n\n        def assign(name: str, key):\n            ordered = sorted(rows, key=key)\n            for idx, row in enumerate(ordered, start=1):\n                if int(row[\"player_id\"]) == pid:\n                    ranks[name] = idx\n                    return\n\n        assign(\"building\", lambda r: (-r[\"building_score\"], -r[\"research_score\"], r[\"player_id\"]))\n        assign(\"research\", lambda r: (-r[\"research_score\"], -r[\"building_score\"], r[\"player_id\"]))\n        assign(\"fleet\", lambda r: (-r[\"fleet_score\"], -r[\"building_score\"], r[\"player_id\"]))\n        assign(\"defense\", lambda r: (-r[\"defense_score\"], r[\"player_id\"]))\n        assign(\"combat\", lambda r: (-r.get(\"combat_score\", 0), -r[\"fleet_score\"], r[\"player_id\"]))\n        assign(\"destroyed\", lambda r: (-r.get(\"destroyed_score\", 0), -r[\"fleet_score\"], r[\"player_id\"]))\n        assign(\"military\", lambda r: (-r.get(\"military_score\", 0), -r[\"fleet_score\"], r[\"player_id\"]))\n        assign(\"evolution\", lambda r: (-r.get(\"evolution_score\", 0), r[\"player_id\"]))\n        if not skip_live_total:\n            assign(\"total\", lambda r: (-r[\"total_score\"], -r[\"building_score\"], -r[\"research_score\"], r[\"player_id\"]))\n        return ranks\n    finally:\n        if owns_conn:\n            conn.close()''')

    # Final ranking API transport: any unsafe integer becomes a decimal string recursively.
    old_return = '''    return {\n        \"ok\": True,\n        \"current_player\": current,\n        \"top_players\": top,\n        \"top_alliances\": top_alliances,\n        \"server_time\": int(time.time()),\n    }\n'''
    new_return = '''    return _json_safe_bigints({\n        \"ok\": True,\n        \"current_player\": current,\n        \"top_players\": top,\n        \"top_alliances\": top_alliances,\n        \"server_time\": int(time.time()),\n    })\n'''
    text = replace_once(text, old_return, new_return, label="ranking API bigint transport")
    write(path, text)


def patch_scoring() -> None:
    path = "game/scoring.py"
    text = read(path)
    text = replace_function(text, "increment_destroyed_raw", '''def increment_destroyed_raw(player_id: int, delta: int, *, conn) -> None:\n    \"\"\"Add combat destruction credit with arbitrary-precision Python arithmetic.\"\"\"\n    from .db import column_exists\n    from .ranking import backfill_player_score_rows\n\n    add = max(0, int(delta))\n    if add <= 0 or not column_exists(conn, \"player_scores\", \"score_destroyed_raw\"):\n        return\n    backfill_player_score_rows(conn=conn)\n    row = conn.execute(\n        \"SELECT score_destroyed_raw FROM player_scores WHERE player_id = ? LIMIT 1;\",\n        (int(player_id),),\n    ).fetchone()\n    current = max(0, int(row[\"score_destroyed_raw\"] or 0)) if row else 0\n    new_value = str(current + add)\n    cur = conn.cursor()\n    cur.execute(\n        \"UPDATE player_scores SET score_destroyed_raw = ? WHERE player_id = ?;\",\n        (new_value, int(player_id)),\n    )\n    if cur.rowcount <= 0:\n        cur.execute(\n            \"\"\"INSERT INTO player_scores (\n                player_id, score_total, score_buildings, score_research, score_destroyed_raw, updated_at\n            ) VALUES (?, '0', '0', '0', ?, strftime('%s','now'));\"\"\",\n            (int(player_id), new_value),\n        )''')
    write(path, text)


def patch_python_formatter() -> None:
    path = "game/number_format.py"
    text = read(path)
    text = text.replace("COMPACT_INFINITY = 10**18\n", "")
    old = '''def fmt_int_compact(value: object) -> str:\n    \"\"\"Compact German display: 149,5 Mrd.\"\"\"\n    n = parse_int_number(value)\n    abs_n = abs(n)\n    if abs_n < COMPACT_THRESHOLD:\n        return fmt_int(n)\n    if abs_n >= COMPACT_INFINITY:\n        return \"∞\"\n\n    sign = \"-\" if n < 0 else \"\"\n    if abs_n >= 10**12:\n        suffix, div = \"Bio.\", 10**12\n    elif abs_n >= 10**9:\n        suffix, div = \"Mrd.\", 10**9\n    elif abs_n >= 10**6:\n        suffix, div = \"Mio.\", 10**6\n    else:\n        suffix, div = \"Tsd.\", 10**3\n\n    val = abs_n / div\n    body = _format_compact_mantissa(val)\n    return f\"{sign}{body} {suffix}\"\n'''
    new = '''def _format_scientific_int(value: int, *, significant_digits: int = 3) -> str:\n    sign = \"-\" if value < 0 else \"\"\n    digits = str(abs(int(value)))\n    if len(digits) <= 1:\n        return f\"{sign}{digits}\"\n    take = max(1, int(significant_digits))\n    head = digits[:take].ljust(take, \"0\")\n    fraction = head[1:].rstrip(\"0\")\n    mantissa = head[0] + ((\",\" + fraction) if fraction else \"\")\n    return f\"{sign}{mantissa}e{len(digits) - 1}\"\n\n\ndef fmt_int_compact(value: object) -> str:\n    \"\"\"Compact arbitrary-precision German display; never invents an infinity cap.\"\"\"\n    n = parse_int_number(value)\n    abs_n = abs(n)\n    if abs_n < COMPACT_THRESHOLD:\n        return fmt_int(n)\n    if abs_n >= 10**15:\n        return _format_scientific_int(n)\n\n    sign = \"-\" if n < 0 else \"\"\n    if abs_n >= 10**12:\n        suffix, div = \"Bio.\", 10**12\n    elif abs_n >= 10**9:\n        suffix, div = \"Mrd.\", 10**9\n    elif abs_n >= 10**6:\n        suffix, div = \"Mio.\", 10**6\n    else:\n        suffix, div = \"Tsd.\", 10**3\n\n    val = abs_n / div\n    body = _format_compact_mantissa(val)\n    return f\"{sign}{body} {suffix}\"\n'''
    text = replace_once(text, old, new, label="python bigint compact formatter")
    write(path, text)


def patch_js_formatter() -> None:
    path = "static/main.js"
    text = read(path)
    text = text.replace("  const COMPACT_INFINITY = 1e18;\n", "")
    marker = "  function formatNumber(value) {\n"
    helper = '''  function parseDisplayBigInt(value) {\n    if (typeof value === \"bigint\") return value;\n    if (typeof value === \"number\") {\n      if (!Number.isFinite(value) || !Number.isInteger(value) || !Number.isSafeInteger(value)) return null;\n      return BigInt(value);\n    }\n    if (typeof value !== \"string\") return null;\n    let raw = value.trim().replace(/\\s+/g, \"\");\n    if (!raw) return null;\n    if (/^-?\\d+$/.test(raw)) {\n      try { return BigInt(raw); } catch (_) { return null; }\n    }\n    if (/^-?\\d{1,3}(?:\\.\\d{3})+$/.test(raw)) {\n      try { return BigInt(raw.replace(/\\./g, \"\")); } catch (_) { return null; }\n    }\n    return null;\n  }\n\n  function formatBigIntScientific(value) {\n    const sign = value < 0n ? \"-\" : \"\";\n    const digits = (value < 0n ? -value : value).toString();\n    const head = digits.slice(0, 3).padEnd(3, \"0\");\n    const fraction = head.slice(1).replace(/0+$/, \"\");\n    const mantissa = head[0] + (fraction ? `,${fraction}` : \"\");\n    return `${sign}${mantissa}e${digits.length - 1}`;\n  }\n\n  function formatBigIntCompact(value) {\n    const abs = value < 0n ? -value : value;\n    if (abs < 10000000n) return new Intl.NumberFormat(\"de-DE\", { maximumFractionDigits: 0 }).format(value);\n    if (abs >= 1000000000000000n) return formatBigIntScientific(value);\n    const sign = value < 0n ? \"-\" : \"\";\n    let div = 1000n;\n    let suffix = \"Tsd.\";\n    if (abs >= 1000000000000n) { div = 1000000000000n; suffix = \"Bio.\"; }\n    else if (abs >= 1000000000n) { div = 1000000000n; suffix = \"Mrd.\"; }\n    else if (abs >= 1000000n) { div = 1000000n; suffix = \"Mio.\"; }\n    const whole = abs / div;\n    const tenth = (abs % div) * 10n / div;\n    const body = tenth > 0n ? `${whole},${tenth}` : `${whole}`;\n    return `${sign}${body} ${suffix}`;\n  }\n\n'''
    text = replace_once(text, marker, helper + marker, label="JS bigint helpers")

    # Insert exact BigInt fast-paths while preserving Number behavior for gameplay decimals/timers.
    text = replace_once(
        text,
        '''  function formatNumber(value) {\n    const n = parseIntNumber(value);\n''',
        '''  function formatNumber(value) {\n    const big = parseDisplayBigInt(value);\n    if (big !== null) return new Intl.NumberFormat(\"de-DE\", { maximumFractionDigits: 0 }).format(big);\n    const n = parseIntNumber(value);\n''',
        label="formatNumber bigint path",
    )
    # Replace compact formatter wholesale by finding its top-level function block.
    start = text.index("  function formatNumberCompact(value) {")
    end = text.index("\n  function ", start + 5)
    replacement = '''  function formatNumberCompact(value) {\n    const big = parseDisplayBigInt(value);\n    if (big !== null) return formatBigIntCompact(big);\n    const n = parseIntNumber(value);\n    const abs = Math.abs(n);\n    if (abs < 10000000) return formatNumber(n);\n    if (abs >= 1e15) return `${n.toExponential(2).replace(\".\", \",\")}`;\n    let suffix = \"Tsd.\";\n    let div = 1e3;\n    if (abs >= 1e12) { suffix = \"Bio.\"; div = 1e12; }\n    else if (abs >= 1e9) { suffix = \"Mrd.\"; div = 1e9; }\n    else if (abs >= 1e6) { suffix = \"Mio.\"; div = 1e6; }\n    const val = n / div;\n    const digits = Math.abs(val) >= 1000 ? 0 : (Math.abs(val) >= 1 ? 1 : 2);\n    return `${val.toLocaleString(\"de-DE\", { minimumFractionDigits: 0, maximumFractionDigits: digits })} ${suffix}`;\n  }\n'''
    text = text[:start] + replacement + text[end:]
    write(path, text)


def patch_tests() -> None:
    path = "tests/test_ranking.py"
    text = read(path)
    text = text.replace('    assert scores["total_score"] == expected_resources\n', '    assert scores["total_score"] == 0\n')
    if "test_big_scores_are_not_clamped" not in text:
        text += '''\n\ndef test_big_scores_are_not_clamped_and_resources_do_not_raise_progression_total():\n    from game.ranking import _sanitize_scores\n\n    huge = 10**50 + 123456789\n    clean = _sanitize_scores({\n        \"resource_score\": huge * 7,\n        \"building_score\": huge,\n        \"research_score\": 5,\n        \"fleet_score\": 7,\n        \"defense_score\": 11,\n        \"evolution_score\": 13,\n    })\n    assert clean[\"building_score\"] == huge\n    assert clean[\"resource_score\"] == huge * 7\n    assert clean[\"total_score\"] == huge + 5 + 7 + 11 + 13\n\n\ndef test_big_score_text_roundtrip_and_exact_order(temp_db):\n    _run_migrate(temp_db)\n    init_db()\n    _close_db()\n    p1 = _create_player(\"bigscore_a\")\n    p2 = _create_player(\"bigscore_b\")\n    a = 10**40 + 111\n    b = 10**40 + 222\n    upsert_player_scores(p1, {\"building_score\": a, \"research_score\": 0})\n    upsert_player_scores(p2, {\"building_score\": b, \"research_score\": 0})\n    _close_db()\n    row = get_player_score_row(p2)\n    assert int(row[\"score_buildings\"]) == b\n    entries = get_sorted_ranking_entries(limit=10, offset=0)\n    ids = [e[\"player_id\"] for e in entries if e[\"player_id\"] in {p1, p2}]\n    assert ids == [p2, p1]\n\n\ndef test_ranking_api_stringifies_only_js_unsafe_scores(temp_db):\n    _run_migrate(temp_db)\n    init_db()\n    _close_db()\n    pid = _create_player(\"bigscore_json\")\n    huge = 10**30 + 7\n    upsert_player_scores(pid, {\"building_score\": huge, \"research_score\": 0})\n    recalculate_ranks()\n    payload = build_ranking_api_payload(pid, limit=10, refresh=False)\n    current = payload[\"current_player\"]\n    assert current[\"total_score\"] == str(huge)\n    assert current[\"building_score\"] == str(huge)\n'''
    write(path, text)

    path = "tests/test_gc622_integer_overflow.py"
    text = read(path)
    text = text.replace('    def test_player_scores_use_integer(self, gc622_db):', '    def test_player_scores_use_decimal_text(self, gc622_db):')
    text = text.replace('            assert _column_type("player_scores", col) == "INTEGER"', '            assert _column_type("player_scores", col) == "TEXT"')
    if "test_ranking_arbitrary_precision_text_roundtrip" not in text:
        anchor = "class TestGC622Exchange:"
        insert = '''    def test_ranking_arbitrary_precision_text_roundtrip(self, gc622_db):\n        uid = _player()\n        huge = 10**50 + 987654321\n        upsert_player_scores(uid, {\n            \"building_score\": huge,\n            \"research_score\": 1,\n        })\n        row = get_player_score_row(uid)\n        assert int(row[\"score_buildings\"]) == huge\n        assert int(row[\"score_total\"]) == huge + 1\n\n\n'''
        text = replace_once(text, anchor, insert + anchor, label="gc622 bigint test")
    write(path, text)

    path = "tests/test_number_format.py"
    text = read(path)
    text = text.replace('assert fmt_int_compact(10**18) == "∞"', 'assert fmt_int_compact(10**18) == "1e18"')
    text = text.replace('assert fmt_int_compact(10**19) == "∞"', 'assert fmt_int_compact(10**19) == "1e19"')
    if "test_compact_arbitrary_precision_never_infinity" not in text:
        text += '''\n\ndef test_compact_arbitrary_precision_never_infinity():\n    huge = 10**50 + 123456789\n    compact = fmt_int_compact(huge)\n    assert compact.startswith(\"1e50\")\n    assert \"∞\" not in compact\n    assert fmt_int(huge).replace(\".\", \"\") == str(huge)\n'''
    write(path, text)


def write_migration() -> None:
    write("migrations/154_big_score_ranking.sql", '''-- 154_big_score_ranking.sql\n-- GC-SCORE-BIGNUM: arbitrary-precision ranking persistence.\n-- Scores are canonical non-negative decimal TEXT; arithmetic/sorting happens in Python int.\n\nDROP INDEX IF EXISTS idx_player_scores_total;\nDROP INDEX IF EXISTS idx_player_scores_updated;\nDROP INDEX IF EXISTS idx_player_scores_rank_total;\nDROP INDEX IF EXISTS idx_player_scores_rank_fleet;\n\nCREATE TABLE player_scores_bigint (\n    player_id INTEGER PRIMARY KEY,\n    score_total TEXT NOT NULL DEFAULT '0',\n    score_resources TEXT NOT NULL DEFAULT '0',\n    score_buildings TEXT NOT NULL DEFAULT '0',\n    score_research TEXT NOT NULL DEFAULT '0',\n    score_fleet TEXT NOT NULL DEFAULT '0',\n    score_defense TEXT NOT NULL DEFAULT '0',\n    score_planet_evolution TEXT NOT NULL DEFAULT '0',\n    score_destroyed_raw TEXT NOT NULL DEFAULT '0',\n    score_combat TEXT NOT NULL DEFAULT '0',\n    score_destroyed TEXT NOT NULL DEFAULT '0',\n    updated_at INTEGER NOT NULL DEFAULT 0,\n    rank_total INTEGER,\n    rank_building INTEGER,\n    rank_research INTEGER,\n    rank_fleet INTEGER,\n    rank_combat INTEGER,\n    rank_destroyed INTEGER,\n    rank_military INTEGER\n);\n\nINSERT INTO player_scores_bigint (\n    player_id, score_total, score_resources, score_buildings, score_research,\n    score_fleet, score_defense, score_planet_evolution, score_destroyed_raw,\n    score_combat, score_destroyed, updated_at, rank_total, rank_building,\n    rank_research, rank_fleet, rank_combat, rank_destroyed, rank_military\n)\nSELECT\n    player_id, CAST(COALESCE(score_total, 0) AS TEXT),\n    CAST(COALESCE(score_resources, 0) AS TEXT),\n    CAST(COALESCE(score_buildings, 0) AS TEXT),\n    CAST(COALESCE(score_research, 0) AS TEXT),\n    CAST(COALESCE(score_fleet, 0) AS TEXT),\n    CAST(COALESCE(score_defense, 0) AS TEXT),\n    CAST(COALESCE(score_planet_evolution, 0) AS TEXT),\n    CAST(COALESCE(score_destroyed_raw, 0) AS TEXT),\n    CAST(COALESCE(score_combat, 0) AS TEXT),\n    CAST(COALESCE(score_destroyed, 0) AS TEXT),\n    COALESCE(updated_at, 0), rank_total, rank_building, rank_research, rank_fleet,\n    rank_combat, rank_destroyed, rank_military\nFROM player_scores;\n\nDROP TABLE player_scores;\nALTER TABLE player_scores_bigint RENAME TO player_scores;\n\nCREATE INDEX IF NOT EXISTS idx_player_scores_updated ON player_scores (updated_at DESC);\nCREATE INDEX IF NOT EXISTS idx_player_scores_rank_total ON player_scores (rank_total ASC);\nCREATE INDEX IF NOT EXISTS idx_player_scores_rank_fleet ON player_scores (rank_fleet ASC);\n''')


def patch_docs() -> None:
    path = "docs/SCORE_SYSTEM.md"
    text = read(path)
    note = '''\n## Arbitrary-precision progression scores (GC-SCORE-BIGNUM)\n\n- `total_score` is **invested progression only**: buildings + research + fleet + defense + planet evolution.\n- `resource_score` remains the separate **Liquid Wealth** metric; stockpiling raw resources does not raise progression rank.\n- Python `int` is the authoritative score type and has no gameplay ceiling.\n- `player_scores.score_*` persist as non-negative decimal `TEXT`, avoiding SQLite signed-64-bit overflow.\n- Ranking arithmetic, aggregation and ordering happen in Python, never through SQL numeric coercion of score text.\n- API integers above JavaScript `Number.MAX_SAFE_INTEGER` are decimal strings; the UI formats them with `BigInt`.\n- Compact display has no artificial `∞` threshold; very large values switch to scientific notation.\n\n'''
    if "Arbitrary-precision progression scores" not in text:
        text = note + text
    text = text.replace("resources + buildings + research + fleet + defense + evolution", "buildings + research + fleet + defense + evolution")
    write(path, text)


def main() -> None:
    patch_ranking()
    patch_scoring()
    patch_python_formatter()
    patch_js_formatter()
    patch_tests()
    write_migration()
    patch_docs()
    print("GC-SCORE-BIGNUM patch applied")


if __name__ == "__main__":
    main()
