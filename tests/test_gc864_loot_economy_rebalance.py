"""
GC-864 — Container loot: meta/progression only (no economy rewards).

Run: python -m pytest tests/test_gc864_loot_economy_rebalance.py -v
"""

from __future__ import annotations

import random
from typing import List

import pytest

from game.defense_defs import DEFENSES
from game.economy_balance import (
    LOOT_JACKPOT_MAX_WEIGHT_PCT,
    generate_loot_balance_table_markdown,
    loot_duplicate_reward_audit,
    loot_jackpot_entries,
    loot_pool_total_weight,
)
from game.fleet_defs import SHIPS
from game.inventory import grant_inventory_item, open_containers
from game.inventory_catalog import CONTAINER_KEYS
from game.inventory_loot import (
    FORBIDDEN_LOOT_REWARD_TYPES,
    LOOT_POOLS,
    META_LOOT_REWARD_TYPES,
    get_loot_pools,
    resolve_loot_entry_amount,
    sanitize_loot_pool,
)
from game.db import begin_write_transaction, commit, db
from game.models import ensure_player_and_homeworld, init_db, create_user
from game.planet_evolution.repository import get_context_planet


_FORBIDDEN_RESOURCE_KEYS = frozenset({"metal", "crystal", "fuel_cells"})


class TestGc864ForbiddenPoolEntries:
    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_pool_has_no_metal(self, container_key: str) -> None:
        for entry in LOOT_POOLS[container_key]:
            assert str(entry.get("reward_key")) != "metal"

    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_pool_has_no_crystal(self, container_key: str) -> None:
        for entry in LOOT_POOLS[container_key]:
            assert str(entry.get("reward_key")) != "crystal"

    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_pool_has_no_fuel_cells(self, container_key: str) -> None:
        for entry in LOOT_POOLS[container_key]:
            assert str(entry.get("reward_key")) != "fuel_cells"

    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_pool_has_no_ships(self, container_key: str) -> None:
        for entry in LOOT_POOLS[container_key]:
            assert str(entry.get("reward_key")) not in SHIPS

    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_pool_has_no_defense(self, container_key: str) -> None:
        for entry in LOOT_POOLS[container_key]:
            assert str(entry.get("reward_key")) not in DEFENSES

    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_pool_only_meta_reward_types(self, container_key: str) -> None:
        for entry in LOOT_POOLS[container_key]:
            rtype = str(entry.get("reward_type") or "")
            assert rtype in META_LOOT_REWARD_TYPES
            assert rtype not in FORBIDDEN_LOOT_REWARD_TYPES

    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_pool_has_at_least_one_reward(self, container_key: str) -> None:
        assert loot_pool_total_weight(LOOT_POOLS[container_key]) > 0
        assert sanitize_loot_pool(LOOT_POOLS[container_key])


class TestGc864Simulation:
    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_simulation_100k_no_economy_rewards(self, container_key: str) -> None:
        pool = LOOT_POOLS[container_key]
        entries = sanitize_loot_pool(pool)
        weights = [int(e["weight"]) for e in entries]
        rng = random.Random(864_000 + hash(container_key) % 10_000)
        for _ in range(100_000):
            pick = rng.choices(entries, weights=weights, k=1)[0]
            rtype = str(pick.get("reward_type") or "")
            rkey = str(pick.get("reward_key") or "")
            assert rtype in META_LOOT_REWARD_TYPES
            assert rtype not in FORBIDDEN_LOOT_REWARD_TYPES
            assert rkey not in _FORBIDDEN_RESOURCE_KEYS
            assert rkey not in SHIPS
            assert rkey not in DEFENSES
            amount = resolve_loot_entry_amount(
                pick,
                user_id=1,
                container_key=container_key,
                conn=None,
                rng=rng,
            )
            assert amount >= 1


class TestGc864Jackpots:
    @pytest.mark.parametrize("container_key", sorted(CONTAINER_KEYS))
    def test_upgrade_jackpots_at_or_below_weight_cap(self, container_key: str) -> None:
        pool = LOOT_POOLS[container_key]
        total = loot_pool_total_weight(pool)
        for entry in pool:
            rtype = str(entry.get("reward_type") or "")
            rkey = str(entry.get("reward_key") or "")
            if rtype != "item" or not rkey.startswith("container_"):
                continue
            pct = 100.0 * int(entry["weight"]) / float(total)
            assert pct <= LOOT_JACKPOT_MAX_WEIGHT_PCT + 0.05


class TestGc864OpenContainer:
    def test_open_container_never_credits_economy(self, tmp_path, monkeypatch):
        db_path = tmp_path / "gc864_open.db"
        monkeypatch.setenv("GC_DB_PATH", str(db_path))
        monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
        import game.db as gdb

        gdb._DB_PATH = None
        init_db()
        import migrate

        migrate.main()

        conn = db()
        ok_u, _, user = create_user("gc864_open", "test-pass-123")
        assert ok_u
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="Gc864", conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        metal_before = float(planet["metal"])
        grant_inventory_item(uid, "container_basic", 1, conn=conn)
        conn.commit()

        begin_write_transaction(conn)
        ok, reason, result = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(42))
        assert ok, reason
        commit(conn)

        rewards = (result or {}).get("rewards") or []
        assert rewards
        for r in rewards:
            assert str(r.get("reward_type")) in META_LOOT_REWARD_TYPES

        row = conn.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()
        assert float(row["metal"]) == metal_before
        conn.close()


class TestGc864Artifacts:
    def test_balance_table_generator_nonempty(self) -> None:
        md = generate_loot_balance_table_markdown()
        assert "GC-864" in md
        assert "Meta-only" in md

    def test_get_loot_pools_strips_forbidden_admin_override(self, monkeypatch):
        from game import inventory_loot

        monkeypatch.setattr(
            inventory_loot,
            "load_pool_overrides",
            lambda conn=None: {
                "container_basic": [
                    {"weight": 50, "reward_type": "resource", "reward_key": "metal", "production_hours": 1.0},
                    {"weight": 50, "reward_type": "booster", "reward_key": "booster_build_5m", "min_amount": 1, "max_amount": 1},
                ]
            },
        )
        effective = get_loot_pools()
        basic = effective["container_basic"]
        assert all(str(e.get("reward_type")) in META_LOOT_REWARD_TYPES for e in basic)
        assert not any(str(e.get("reward_key")) == "metal" for e in basic)

    def test_duplicate_audit_runs(self) -> None:
        assert isinstance(loot_duplicate_reward_audit(LOOT_POOLS), list)

    def test_no_duplicate_roll_path_in_pool(self) -> None:
        for container_key in CONTAINER_KEYS:
            seen: set[str] = set()
            for entry in LOOT_POOLS[container_key]:
                token = f"{entry.get('reward_type')}:{entry.get('reward_key')}"
                assert token not in seen, container_key
                seen.add(token)
