from pathlib import Path

from game.presence_store import effective_last_seen_scalar_sql

ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_pg_scalar_presence_reads_dedicated_table_without_legacy_fallback(monkeypatch):
    monkeypatch.setattr("game.presence_store.get_db_backend", lambda: "postgres")
    expr = effective_last_seen_scalar_sql(player_alias="p")
    assert "player_presence" in expr
    assert "pp_gc_presence.player_id = p.id" in expr
    assert "p.last_seen" not in expr


def test_sqlite_scalar_presence_keeps_legacy_column(monkeypatch):
    monkeypatch.setattr("game.presence_store.get_db_backend", lambda: "sqlite")
    assert effective_last_seen_scalar_sql(player_alias="p") == "COALESCE(p.last_seen, 0)"


def test_critical_activity_readers_use_presence_store():
    models = _read("game/models.py")
    ranking = _read("game/ranking.py")
    galaxy = _read("game/galaxy.py")
    autoplay = _read("game/inactive_autoplay.py")
    assert "effective_last_seen_scalar_sql" in models
    assert "get_effective_last_seen_by_ids" in ranking
    assert "effective_last_seen_scalar_sql" in galaxy
    assert "touch_presence_bulk(conn, ids" in autoplay
    assert "UPDATE players SET last_seen = ? WHERE id IN" not in autoplay
