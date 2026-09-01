from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "game" / "presence_store.py"
PRESENCE = ROOT / "game" / "presence.py"
MODELS = ROOT / "game" / "models.py"
ALLIANCE = ROOT / "game" / "alliance.py"
T142 = ROOT / "tests" / "test_gc_pg_142_presence_pool_starvation.py"
TEFF = ROOT / "tests" / "test_gc_pg_presence_effective_readers.py"
T165 = ROOT / "tests" / "test_gc_pg_165_presence_critical_readers.py"
T166 = ROOT / "tests" / "test_gc_pg_166_presence_secondary.py"
T172 = ROOT / "tests" / "test_gc_pg_172_no_legacy_presence_write.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_block(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{label}: start marker not found")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:a] + replacement + text[b:]


# ---------------------------------------------------------------------------
# Canonical store: PostgreSQL reads player_presence only. SQLite stays legacy.
# ---------------------------------------------------------------------------
text = STORE.read_text(encoding="utf-8")
text = replace_once(
    text,
    "PostgreSQL authenticated presence is owned by ``player_presence``. During the\n"
    "reader cutover we keep ``players.last_seen`` as a low-frequency compatibility\n"
    "mirror (<= once per four minutes), isolated by the caller with a SAVEPOINT.\n"
    "That preserves legacy online/inactive readers while removing the former\n"
    "per-presence-interval write pressure from the hot gameplay row.\n\n"
    "SQLite keeps the established ``players.last_seen`` path.\n",
    "PostgreSQL authenticated presence is owned exclusively by ``player_presence``.\n"
    "All PostgreSQL activity readers use that canonical table; ``players.last_seen``\n"
    "remains a SQLite compatibility column only.\n\n"
    "SQLite keeps the established ``players.last_seen`` path.\n",
    "presence_store module contract",
)
text = replace_once(
    text,
    'LEGACY_SYNC_INTERVAL_SEC = 4 * 60\n\n',
    '',
    "legacy sync constant",
)
text = replace_block(
    text,
    "def effective_last_seen_sql(",
    "def effective_last_seen_scalar_sql(",
    '''def effective_last_seen_sql(\n    *,\n    player_alias: str = "p",\n    presence_alias: str = "pp",\n    backend: str | None = None,\n) -> str:\n    """Backend-aware activity expression; PostgreSQL is canonical-only."""\n    if uses_dedicated_presence(backend=backend):\n        return f"COALESCE({presence_alias}.last_seen, 0)"\n    return f"COALESCE({player_alias}.last_seen, 0)"\n\n\n''',
    "effective expression",
)
text = replace_block(
    text,
    "def effective_last_seen_scalar_sql(",
    "def get_presence_last_seen(",
    '''def effective_last_seen_scalar_sql(\n    *,\n    player_alias: str = "p",\n    backend: str | None = None,\n) -> str:\n    """Correlated activity expression for existing player queries.\n\n    PostgreSQL reads only canonical ``player_presence``. SQLite intentionally\n    keeps the legacy players column for local/test compatibility.\n    """\n    if uses_dedicated_presence(backend=backend):\n        return (\n            f"COALESCE((SELECT pp_gc_presence.last_seen FROM {PRESENCE_TABLE} pp_gc_presence "\n            f"WHERE pp_gc_presence.player_id = {player_alias}.id), 0)"\n        )\n    return f"COALESCE({player_alias}.last_seen, 0)"\n\n\n''',
    "scalar expression",
)
text = replace_block(
    text,
    "def get_effective_last_seen(",
    "def get_effective_last_seen_by_ids(",
    '''def get_effective_last_seen(\n    conn, player_id: int, *, backend: str | None = None\n) -> int:  # noqa: ANN001\n    """Read current activity from the backend's canonical presence owner."""\n    pid = int(player_id)\n    if uses_dedicated_presence(backend=backend):\n        row = conn.execute(\n            f"SELECT last_seen FROM {PRESENCE_TABLE} WHERE player_id = ? LIMIT 1;",\n            (pid,),\n        ).fetchone()\n    else:\n        row = conn.execute(\n            "SELECT COALESCE(last_seen, 0) AS last_seen FROM players WHERE id = ? LIMIT 1;",\n            (pid,),\n        ).fetchone()\n    return int(row["last_seen"] or 0) if row else 0\n\n\n''',
    "single effective reader",
)
text = replace_block(
    text,
    "def get_effective_last_seen_by_ids(",
    "def should_sync_legacy_last_seen(",
    '''def get_effective_last_seen_by_ids(\n    conn,\n    player_ids: Sequence[int] | Iterable[int],\n    *,\n    backend: str | None = None,\n) -> Dict[int, int]:  # noqa: ANN001\n    """Bulk activity read from the backend's canonical presence owner."""\n    ids = sorted({int(pid) for pid in player_ids if int(pid) > 0})\n    if not ids:\n        return {}\n\n    placeholders = ",".join("?" for _ in ids)\n    if uses_dedicated_presence(backend=backend):\n        cur = conn.execute(\n            f"""\n            SELECT player_id, COALESCE(last_seen, 0) AS last_seen\n            FROM {PRESENCE_TABLE}\n            WHERE player_id IN ({placeholders});\n            """,\n            tuple(ids),\n        )\n    else:\n        cur = conn.execute(\n            f"""\n            SELECT id AS player_id, COALESCE(last_seen, 0) AS last_seen\n            FROM players\n            WHERE id IN ({placeholders});\n            """,\n            tuple(ids),\n        )\n\n    out = {pid: 0 for pid in ids}\n    for row in cur.fetchall():\n        out[int(row["player_id"])] = int(row["last_seen"] or 0)\n    return out\n\n\n''',
    "bulk effective reader",
)
text = replace_block(
    text,
    "def should_sync_legacy_last_seen(",
    "def touch_presence(",
    "",
    "legacy mirror helpers",
)
STORE.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Authenticated PG hotpath: no players read, no mirror SAVEPOINT, no mirror write.
# ---------------------------------------------------------------------------
text = PRESENCE.read_text(encoding="utf-8")
text = replace_once(
    text,
    "GC-PG-HIGHSPEED-001C makes PostgreSQL ``player_presence`` the canonical hot\n"
    "presence store. While remaining readers are cut over, ``players.last_seen`` is\n"
    "kept as a low-frequency compatibility mirror (max once per four minutes).\n\n",
    "GC-PG-HIGHSPEED-001D makes PostgreSQL ``player_presence`` the exclusive\n"
    "presence owner. Authenticated PostgreSQL traffic never reads or writes\n"
    "``players.last_seen``.\n\n",
    "presence module contract",
)
text = replace_once(
    text,
    "from .presence_store import (\n"
    "    get_presence_last_seen,\n"
    "    should_sync_legacy_last_seen,\n"
    "    sync_legacy_last_seen,\n"
    "    touch_presence,\n"
    ")\n",
    "from .presence_store import get_presence_last_seen, touch_presence\n",
    "presence imports",
)
text = replace_block(
    text,
    "def _sync_legacy_presence_optional(",
    "def touch_player_online(",
    "",
    "presence mirror helper block",
)
text = replace_once(
    text,
    '''        # The compatibility mirror has its own cadence. Driving this from the\n        # dedicated timestamp would keep an actively polling player's\n        # players.last_seen stale forever after the first mirror write.\n        legacy_seen = (\n            _legacy_last_seen_for_mirror(conn, pid) if backend == "postgres" else previous_seen\n        )\n        need_legacy_sync = backend == "postgres" and should_sync_legacy_last_seen(\n            previous_seen=legacy_seen,\n            now=now,\n        )\n\n''',
    "",
    "presence mirror cadence block",
)
text = replace_once(
    text,
    "        if not need_last_seen and not need_roster and not need_legacy_sync:\n",
    "        if not need_last_seen and not need_roster:\n",
    "presence no-op condition",
)
text = replace_once(
    text,
    "        if need_legacy_sync:\n            _sync_legacy_presence_optional(conn, pid, now=now, backend=backend)\n",
    "",
    "presence mirror invocation",
)
PRESENCE.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Legacy public compatibility entry: PostgreSQL delegates before touching DB.
# ---------------------------------------------------------------------------
text = MODELS.read_text(encoding="utf-8")
start = text.index("def touch_player_online(player_id: int) -> None:")
end = text.index("def _release_roster_best_effort", start)
block = text[start:end]
block = replace_once(
    block,
    "    if not player_id:\n        return\n    now = int(_now_ts())\n",
    "    if not player_id:\n"
    "        return\n"
    "    from .db import get_db_backend\n\n"
    "    if get_db_backend() == \"postgres\":\n"
    "        from .presence import touch_player_online as touch_dedicated_presence\n\n"
    "        touch_dedicated_presence(int(player_id))\n"
    "        return\n"
    "    now = int(_now_ts())\n",
    "models postgres delegation",
)
text = text[:start] + block + text[end:]
MODELS.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Alliance already overlays batch effective presence; remove dead legacy SQL.
# ---------------------------------------------------------------------------
text = ALLIANCE.read_text(encoding="utf-8")
text = replace_once(
    text,
    "            SELECT am.player_id, am.role, am.joined_at, p.name AS player_name,\n"
    "                   COALESCE(p.last_seen, 0) AS last_seen,\n"
    "                   COALESCE(SUM(d.amount), 0) AS donation_points,\n",
    "            SELECT am.player_id, am.role, am.joined_at, p.name AS player_name,\n"
    "                   COALESCE(SUM(d.amount), 0) AS donation_points,\n",
    "alliance legacy projection",
)
text = replace_once(
    text,
    "            GROUP BY am.player_id, am.role, am.joined_at, p.name, p.last_seen, ps.score_total,\n",
    "            GROUP BY am.player_id, am.role, am.joined_at, p.name, ps.score_total,\n",
    "alliance legacy group-by",
)
ALLIANCE.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Update existing regression contracts from rolling fallback to canonical-only.
# ---------------------------------------------------------------------------
text = TEFF.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''def test_pg_effective_expression_uses_newest_timestamp():\n    expr = presence_store.effective_last_seen_sql(backend="postgres")\n    assert expr == "GREATEST(COALESCE(pp.last_seen, 0), COALESCE(p.last_seen, 0))"\n    assert presence_store.last_seen_join_sql(backend="postgres") == (\n        "LEFT JOIN player_presence pp ON pp.player_id = p.id"\n    )\n\n\ndef test_pg_effective_single_reader_uses_newest_wins_query():\n    conn = _Conn([_Rows(one={"last_seen": 999})])\n    seen = presence_store.get_effective_last_seen(conn, 7, backend="postgres")\n    assert seen == 999\n    sql = conn.sql[0]\n    assert "GREATEST(COALESCE(pp.last_seen, 0), COALESCE(p.last_seen, 0))" in sql\n    assert "LEFT JOIN player_presence pp ON pp.player_id = p.id" in sql\n    assert conn.params == [(7,)]\n\n\ndef test_pg_effective_bulk_reader_uses_one_query_and_fills_missing_ids():\n''',
    '''def test_pg_effective_expression_is_canonical_presence_only():\n    expr = presence_store.effective_last_seen_sql(backend="postgres")\n    assert expr == "COALESCE(pp.last_seen, 0)"\n    assert "p.last_seen" not in expr\n    assert presence_store.last_seen_join_sql(backend="postgres") == (\n        "LEFT JOIN player_presence pp ON pp.player_id = p.id"\n    )\n\n\ndef test_pg_effective_single_reader_reads_presence_table_only():\n    conn = _Conn([_Rows(one={"last_seen": 999})])\n    seen = presence_store.get_effective_last_seen(conn, 7, backend="postgres")\n    assert seen == 999\n    sql = conn.sql[0].lower()\n    assert "from player_presence" in sql\n    assert "from players" not in sql\n    assert "join players" not in sql\n    assert conn.params == [(7,)]\n\n\ndef test_pg_effective_bulk_reader_uses_one_query_and_fills_missing_ids():\n''',
    "effective reader tests",
)
text = replace_once(
    text,
    '''    assert len(conn.sql) == 1\n    assert "GREATEST(COALESCE(pp.last_seen, 0), COALESCE(p.last_seen, 0))" in conn.sql[0]\n    assert conn.params == [(2, 4, 9)]\n''',
    '''    assert len(conn.sql) == 1\n    sql = conn.sql[0].lower()\n    assert "from player_presence" in sql\n    assert "from players" not in sql\n    assert "join players" not in sql\n    assert conn.params == [(2, 4, 9)]\n''',
    "bulk effective reader test",
)
TEFF.write_text(text, encoding="utf-8")

text = T165.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''def test_pg_scalar_presence_reads_dedicated_table_with_legacy_fallback(monkeypatch):\n    monkeypatch.setattr("game.presence_store.get_db_backend", lambda: "postgres")\n    expr = effective_last_seen_scalar_sql(player_alias="p")\n    assert "player_presence" in expr\n    assert "pp_gc_presence.player_id = p.id" in expr\n    assert "p.last_seen" in expr\n''',
    '''def test_pg_scalar_presence_reads_dedicated_table_without_legacy_fallback(monkeypatch):\n    monkeypatch.setattr("game.presence_store.get_db_backend", lambda: "postgres")\n    expr = effective_last_seen_scalar_sql(player_alias="p")\n    assert "player_presence" in expr\n    assert "pp_gc_presence.player_id = p.id" in expr\n    assert "p.last_seen" not in expr\n''',
    "critical scalar presence test",
)
T165.write_text(text, encoding="utf-8")

text = T142.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''        if "FROM players WHERE id" in text:\n            return SimpleNamespace(fetchone=lambda: {"last_seen": self.legacy_seen})\n''',
    "",
    "fake legacy read",
)
text = replace_once(
    text,
    '''    assert "SAVEPOINT gc_presence_legacy" in conn.sql\n    assert any("UPDATE players SET last_seen" in sql for sql in conn.sql)\n''',
    '''    assert "SAVEPOINT gc_presence_legacy" not in conn.sql\n    assert not any("UPDATE players SET last_seen" in sql for sql in conn.sql)\n''',
    "roster mirror assertions",
)
text = replace_block(
    text,
    "def test_recent_dedicated_presence_skips_fresh_legacy_player_row_write(",
    "def test_postgres_store_never_references_players_on_canonical_touch(",
    '''def test_recent_dedicated_presence_skips_all_database_writes_when_not_rostered(monkeypatch):\n    conn = _FakeConn(lock_on_touch=False, presence_seen=990, legacy_seen=0)\n    local_marks: list[int] = []\n    _patch_presence_basics(monkeypatch, conn, local_marks=local_marks)\n    presence.touch_player_online(7)\n    assert conn.committed is False\n    assert local_marks == [7]\n    assert not any("INSERT INTO player_presence" in sql for sql in conn.sql)\n    assert not any("UPDATE players SET last_seen" in sql for sql in conn.sql)\n    assert not any("FROM players WHERE id" in sql for sql in conn.sql)\n\n\n''',
    "legacy cadence tests",
)
T142.write_text(text, encoding="utf-8")

text = T166.read_text(encoding="utf-8")
needle = '''    assert "get_effective_last_seen_by_ids" in block\n    assert 'd["last_seen"] = effective_seen.get' in block\n'''
replacement = needle + '''    assert "p.last_seen" not in block\n'''
text = replace_once(text, needle, replacement, "alliance regression assertion")
T166.write_text(text, encoding="utf-8")

T172.write_text(
    '''from pathlib import Path\n\nimport game.models as models\nimport game.presence as presence\nfrom game import presence_store\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_postgres_presence_owner_source_has_no_legacy_mirror_sql():\n    source = (ROOT / "game" / "presence.py").read_text(encoding="utf-8")\n    assert "sync_legacy_last_seen" not in source\n    assert "should_sync_legacy_last_seen" not in source\n    assert "gc_presence_legacy" not in source\n    assert "UPDATE players SET last_seen" not in source\n    assert "FROM players WHERE id" not in source\n\n\ndef test_postgres_store_readers_never_reference_players():\n    class Rows:\n        def __init__(self, one=None, many=None):\n            self.one = one\n            self.many = list(many or [])\n\n        def fetchone(self):\n            return self.one\n\n        def fetchall(self):\n            return self.many\n\n    class Conn:\n        def __init__(self):\n            self.sql = []\n\n        def execute(self, sql, params=None):\n            self.sql.append(str(sql))\n            if " IN (" in str(sql):\n                return Rows(many=[{"player_id": 7, "last_seen": 700}])\n            return Rows(one={"last_seen": 700})\n\n    conn = Conn()\n    assert presence_store.get_effective_last_seen(conn, 7, backend="postgres") == 700\n    assert presence_store.get_effective_last_seen_by_ids(conn, [7], backend="postgres") == {7: 700}\n    sql = "\\n".join(conn.sql).lower()\n    assert "player_presence" in sql\n    assert "from players" not in sql\n    assert "join players" not in sql\n    assert "p.last_seen" not in sql\n\n\ndef test_models_compat_entry_delegates_postgres_before_legacy_checkout(monkeypatch):\n    calls = []\n\n    monkeypatch.setattr("game.db.get_db_backend", lambda: "postgres")\n    monkeypatch.setattr(presence, "touch_player_online", lambda player_id: calls.append(int(player_id)))\n    monkeypatch.setattr(models, "db", lambda: (_ for _ in ()).throw(AssertionError("legacy checkout")))\n\n    models.touch_player_online(42)\n    assert calls == [42]\n\n\ndef test_postgres_scalar_expression_does_not_fallback_to_players(monkeypatch):\n    monkeypatch.setattr("game.presence_store.get_db_backend", lambda: "postgres")\n    expr = presence_store.effective_last_seen_scalar_sql(player_alias="p")\n    assert "player_presence" in expr\n    assert "p.last_seen" not in expr\n''',
    encoding="utf-8",
)

print("GC-PG-172 canonical presence cutover applied")
