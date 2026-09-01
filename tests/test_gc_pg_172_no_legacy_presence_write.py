from pathlib import Path

import game.models as models
import game.presence as presence
from game import presence_store

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_presence_owner_source_has_no_legacy_mirror_sql():
    source = (ROOT / "game" / "presence.py").read_text(encoding="utf-8")
    assert "sync_legacy_last_seen" not in source
    assert "should_sync_legacy_last_seen" not in source
    assert "gc_presence_legacy" not in source
    assert "UPDATE players SET last_seen" not in source
    assert "FROM players WHERE id" not in source


def test_postgres_store_readers_never_reference_players():
    class Rows:
        def __init__(self, one=None, many=None):
            self.one = one
            self.many = list(many or [])

        def fetchone(self):
            return self.one

        def fetchall(self):
            return self.many

    class Conn:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append(str(sql))
            if " IN (" in str(sql):
                return Rows(many=[{"player_id": 7, "last_seen": 700}])
            return Rows(one={"last_seen": 700})

    conn = Conn()
    assert presence_store.get_effective_last_seen(conn, 7, backend="postgres") == 700
    assert presence_store.get_effective_last_seen_by_ids(conn, [7], backend="postgres") == {7: 700}
    sql = "\n".join(conn.sql).lower()
    assert "player_presence" in sql
    assert "from players" not in sql
    assert "join players" not in sql
    assert "p.last_seen" not in sql


def test_models_compat_entry_delegates_postgres_before_legacy_checkout(monkeypatch):
    calls = []

    monkeypatch.setattr("game.db.get_db_backend", lambda: "postgres")
    monkeypatch.setattr(presence, "touch_player_online", lambda player_id: calls.append(int(player_id)))
    monkeypatch.setattr(models, "db", lambda: (_ for _ in ()).throw(AssertionError("legacy checkout")))

    models.touch_player_online(42)
    assert calls == [42]


def test_postgres_scalar_expression_does_not_fallback_to_players(monkeypatch):
    monkeypatch.setattr("game.presence_store.get_db_backend", lambda: "postgres")
    expr = presence_store.effective_last_seen_scalar_sql(player_alias="p")
    assert "player_presence" in expr
    assert "p.last_seen" not in expr
