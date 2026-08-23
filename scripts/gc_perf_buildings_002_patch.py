"""One-shot GC-PERF-BUILDINGS-002 source patch helper.

Shares DB-backed EffectResolver probe results across synthetic building target
resolvers while keeping all building/research formula evaluation per resolver.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_effect_resolver() -> None:
    path = ROOT / "game" / "effects" / "effect_resolver.py"

    replace_once(
        path,
        '''        conn=None,\n        skip_inventory_boosters: bool = False,\n    ) -> None:\n        self.buildings = {k: _bld(buildings, k) for k in buildings}\n        self.research = dict(research or {})\n        self.player_id = int(player_id) if player_id is not None else None\n        self.planet_id = int(planet_id) if planet_id is not None else None\n        self._skip_inventory_boosters = bool(skip_inventory_boosters)\n''',
        '''        conn=None,\n        skip_inventory_boosters: bool = False,\n        external_probe_cache: Optional[Dict[tuple, Any]] = None,\n    ) -> None:\n        self.buildings = {k: _bld(buildings, k) for k in buildings}\n        self.research = dict(research or {})\n        self.player_id = int(player_id) if player_id is not None else None\n        self.planet_id = int(planet_id) if planet_id is not None else None\n        self._skip_inventory_boosters = bool(skip_inventory_boosters)\n        # GC-PERF-BUILDINGS-002: raw DB-backed modifier inputs may be shared\n        # by synthetic target-level resolvers. Finished modifiers are never shared.\n        self._external_probe_cache: Dict[tuple, Any] = (\n            external_probe_cache if external_probe_cache is not None else {}\n        )\n''',
    )

    replace_once(
        path,
        '''    def _settings_dict(self) -> Dict[str, Any]:\n        if self._settings is not None:\n            return self._settings\n        # GC-PERF-PANEL-CONN-001: reuse request conn when present (no orphan db()).\n        self._settings = get_game_settings(conn=self._conn)\n        return self._settings\n\n''',
        '''    def _settings_dict(self) -> Dict[str, Any]:\n        if self._settings is not None:\n            return self._settings\n        # GC-PERF-PANEL-CONN-001: reuse request conn when present (no orphan db()).\n        self._settings = get_game_settings(conn=self._conn)\n        return self._settings\n\n    def shared_external_probe_cache(self) -> Dict[tuple, Any]:\n        """Panel-local cache of raw external modifier probes, never computed mods."""\n        return self._external_probe_cache\n\n''',
    )

    replace_once(
        path,
        '''        global _ER_SAVEPOINT_SEQ\n        conn = self._conn\n        if conn is None:\n            return fn()\n''',
        '''        cache_key = (\n            str(label),\n            self.player_id,\n            self.galaxy_id,\n            bool(self._skip_inventory_boosters),\n        )\n        if cache_key in self._external_probe_cache:\n            return self._external_probe_cache[cache_key]\n\n        global _ER_SAVEPOINT_SEQ\n        conn = self._conn\n        if conn is None:\n            out = fn()\n            self._external_probe_cache[cache_key] = out\n            return out\n''',
    )

    replace_once(
        path,
        '''                raise\n        return out\n\n    def _apply_gd_er_mods(\n''',
        '''                raise\n        self._external_probe_cache[cache_key] = out\n        return out\n\n    def _apply_gd_er_mods(\n''',
    )

    replace_once(
        path,
        '''            sev_build = float(active_build_time_speed(conn=self._conn) or 1.0)\n            sev_research = float(active_research_time_speed(conn=self._conn) or 1.0)\n''',
        '''            sev_build, sev_research = self._run_optional_conn_probe(\n                "server_event_time_speed",\n                lambda: (\n                    float(active_build_time_speed(conn=self._conn) or 1.0),\n                    float(active_research_time_speed(conn=self._conn) or 1.0),\n                ),\n            )\n''',
    )


def patch_buildings() -> None:
    path = ROOT / "game" / "buildings.py"

    replace_once(
        path,
        '''            galaxy_id=base.galaxy_id,\n            conn=base._conn,\n        )\n''',
        '''            galaxy_id=base.galaxy_id,\n            conn=base._conn,\n            external_probe_cache=base.shared_external_probe_cache(),\n        )\n''',
    )

    replace_once(
        path,
        '''            evo_ranks = get_evolution_ranks_for_planet(pid)\n''',
        '''            evo_conn = getattr(panel_ctx.resolver, "_conn", None)\n            evo_ranks = get_evolution_ranks_for_planet(pid, conn=evo_conn)\n''',
    )


def main() -> None:
    patch_effect_resolver()
    patch_buildings()
    print("GC-PERF-BUILDINGS-002 source patch applied")


if __name__ == "__main__":
    main()
