"""P1-A no-max combat/progression numeric contract."""

from __future__ import annotations

from decimal import Decimal, localcontext
from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "169_pg_p1_combat_progression_numeric.sql"

HUGE_HP = 10**30 + 987_654_321


def test_p1_combat_progression_migration_uses_unbounded_numeric():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in sql
    assert "NUMERIC(" not in sql

    expected = (
        ("world_boss_definitions", "max_hp"),
        ("world_boss_events", "max_hp"),
        ("world_boss_events", "current_hp"),
        ("world_boss_contributions", "damage"),
        ("pirate_bases", "max_hp"),
        ("pirate_bases", "current_hp"),
        ("pirate_base_contributions", "damage"),
        ("combat_hall_of_fame", "attacker_loss_score"),
        ("combat_hall_of_fame", "defender_loss_score"),
        ("combat_hall_of_fame", "total_destroyed_score"),
        ("player_directives", "target_value"),
        ("player_directives", "progress_value"),
        ("directive_progress", "delta"),
        ("case_battles", "total_battle_value"),
        ("case_battle_rolls", "reward_amount"),
        ("case_battle_rolls", "reward_value"),
    )
    for table, column in expected:
        assert f"ALTER TABLE {table}" in sql
        assert f"ALTER COLUMN {column} TYPE NUMERIC" in sql


def test_world_boss_damage_is_exact_at_10_pow_30_hp():
    from game.world_boss import WAVE_HP_FRACTION, compute_instant_hp_damage

    damage = compute_instant_hp_damage(
        ships={"mule_courier": 1},
        defender_ships={"mule_courier": 1},
        max_hp=HUGE_HP,
        critical=False,
        apply_wave_cap=True,
    )

    with localcontext() as ctx:
        ctx.prec = 128
        expected = int(Decimal(HUGE_HP) * Decimal(str(WAVE_HP_FRACTION)))

    assert damage == expected


def test_world_boss_phase_thresholds_are_integer_exact_at_10_pow_30():
    from game.world_boss import hp_phase_from_values

    max_hp = 10**30
    assert hp_phase_from_values(0, max_hp) == 0
    assert hp_phase_from_values(max_hp // 4, max_hp) == 3
    assert hp_phase_from_values((max_hp // 4) + 1, max_hp) == 2
    assert hp_phase_from_values(max_hp // 2, max_hp) == 2
    assert hp_phase_from_values((max_hp // 2) + 1, max_hp) == 1


def test_world_boss_runtime_has_no_huge_hp_float_roundtrip():
    source = (ROOT / "game" / "world_boss.py").read_text(encoding="utf-8")
    companions = (ROOT / "game" / "world_boss_companions.py").read_text(
        encoding="utf-8"
    )
    autoplay = (ROOT / "game" / "inactive_autoplay.py").read_text(
        encoding="utf-8"
    )

    start = source.index("def compute_instant_hp_damage")
    end = source.index("def _projectile_profile_for_ships", start)
    damage_block = source[start:end]

    for forbidden in (
        "float(hp_budget)",
        "float(atk_score) / float(wave_score)",
        "float(hp_budget) * float(MAX_WAVE_HP_FRACTION)",
        "float(hp_budget) * float(RAID_MULTI_ACTION_CAP_FRACTION)",
    ):
        assert forbidden not in damage_block

    assert "hp_phase_from_values(current_hp, max_hp)" in companions
    assert "float(current_hp) / float(max_hp)" not in companions
    assert 'Decimal(str(INACTIVE_WORLD_BOSS_SAFE_HP_RATIO))' in autoplay
    assert 'float(event.get("current_hp") or 0) / float(max_hp)' not in autoplay


@requires_postgres
def test_live_postgres_p1_combat_progression_numeric_roundtrip(pg_parity_db):
    from migrate import main as migrate_main

    migrate_main()

    from game.db import db

    expected_columns = {
        ("world_boss_definitions", "max_hp"),
        ("world_boss_events", "max_hp"),
        ("world_boss_events", "current_hp"),
        ("world_boss_contributions", "damage"),
        ("pirate_bases", "max_hp"),
        ("pirate_bases", "current_hp"),
        ("pirate_base_contributions", "damage"),
        ("combat_hall_of_fame", "attacker_loss_score"),
        ("combat_hall_of_fame", "defender_loss_score"),
        ("combat_hall_of_fame", "total_destroyed_score"),
        ("player_directives", "target_value"),
        ("player_directives", "progress_value"),
        ("directive_progress", "delta"),
        ("case_battles", "total_battle_value"),
        ("case_battle_rolls", "reward_amount"),
        ("case_battle_rolls", "reward_value"),
    }

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type, numeric_precision
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (
                (table_name = 'world_boss_definitions' AND column_name = 'max_hp')
                OR (table_name = 'world_boss_events' AND column_name IN ('max_hp','current_hp'))
                OR (table_name = 'world_boss_contributions' AND column_name = 'damage')
                OR (table_name = 'pirate_bases' AND column_name IN ('max_hp','current_hp'))
                OR (table_name = 'pirate_base_contributions' AND column_name = 'damage')
                OR (table_name = 'combat_hall_of_fame' AND column_name IN (
                    'attacker_loss_score','defender_loss_score','total_destroyed_score'
                ))
                OR (table_name = 'player_directives' AND column_name IN (
                    'target_value','progress_value'
                ))
                OR (table_name = 'directive_progress' AND column_name = 'delta')
                OR (table_name = 'case_battles' AND column_name = 'total_battle_value')
                OR (table_name = 'case_battle_rolls' AND column_name IN (
                    'reward_amount','reward_value'
                ))
              );
            """
        ).fetchall()

        seen = set()
        for row in rows:
            key = (str(row["table_name"]), str(row["column_name"]))
            seen.add(key)
            assert str(row["data_type"]).lower() == "numeric"
            assert row["numeric_precision"] is None
        assert seen == expected_columns

        boss = conn.execute(
            "SELECT boss_key FROM world_boss_definitions ORDER BY boss_key LIMIT 1;"
        ).fetchone()
        assert boss is not None
        boss_key = str(boss["boss_key"])

        conn.execute(
            "UPDATE world_boss_definitions SET max_hp = ? WHERE boss_key = ?;",
            (HUGE_HP, boss_key),
        )
        conn.commit()

        row = conn.execute(
            "SELECT max_hp FROM world_boss_definitions WHERE boss_key = ?;",
            (boss_key,),
        ).fetchone()
        assert int(row["max_hp"]) == HUGE_HP
    finally:
        conn.close()
        close_pg_pool()
