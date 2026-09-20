from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "179_pg_activity_xp_planet_fk_cascade.sql"


def test_activity_xp_planet_fk_cascades_for_postgres_reset():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "-- GC-BACKEND: postgres" in sql
    assert "DROP CONSTRAINT IF EXISTS activity_xp_log_planet_id_fkey" in sql
    assert "FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE" in sql
