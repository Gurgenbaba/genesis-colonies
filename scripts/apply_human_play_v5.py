from __future__ import annotations

from pathlib import Path
import re
import textwrap


ROOT = Path(__file__).resolve().parents[1]
INACTIVE = ROOT / "game" / "inactive_autoplay.py"
V4_TESTS = ROOT / "tests" / "test_living_universe_gc2622.py"
V5_TESTS = ROOT / "tests" / "test_human_play_loop_v5.py"
WORKFLOW = ROOT / ".github" / "workflows" / "apply-human-play-v5.yml"
SELF = Path(__file__).resolve()


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing literal for {label}: {old[:140]!r}")
    return text.replace(old, new, 1)


def replace_regex(text: str, pattern: str, replacement: str, *, label: str) -> str:
    out, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"expected one regex match for {label}, got {count}")
    return out


def patch_inactive_autoplay() -> None:
    text = INACTIVE.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "GC-INACTIVE-SHIFT-001 — Day Shift: a small shift crew (2–3) stays visibly\n"
        "online; after a fixed tenure they rotate back to the dormant queue. Never\n"
        "fleets or expeditions.",
        "GC-INACTIVE-SHIFT-001 — Day Shift: a small shift crew (2–3) stays visibly\n"
        "online; after a fixed tenure they rotate back to the dormant queue. Human Play\n"
        "V5 adds sparse canonical shipyard and expedition decisions without another loop.",
        label="module docstring",
    )

    text = replace_once(
        text,
        'INACTIVE_ACTION_DOMAINS = ("building", "research", "defense")',
        'INACTIVE_ACTION_DOMAINS = ("building", "research", "ships", "defense", "expedition")',
        label="action domains",
    )

    text = replace_regex(
        text,
        r"INACTIVE_ACTION_WEIGHTS = \{.*?\n\}\nINACTIVE_ACTION_PACE_RANGES_SEC =",
        textwrap.dedent(
            '''\
            INACTIVE_ACTION_WEIGHTS = {
                "economy": {"building": 55, "research": 20, "ships": 10, "defense": 8, "expedition": 7},
                "aggressive": {"building": 30, "research": 15, "ships": 30, "defense": 15, "expedition": 10},
                "turtle": {"building": 35, "research": 10, "ships": 12, "defense": 35, "expedition": 8},
                "spy": {"building": 25, "research": 35, "ships": 12, "defense": 8, "expedition": 20},
                "swarm": {"building": 30, "research": 15, "ships": 35, "defense": 10, "expedition": 10},
                "elite": {"building": 28, "research": 25, "ships": 27, "defense": 10, "expedition": 10},
            }
            INACTIVE_ACTION_PACE_RANGES_SEC ='''
        ),
        label="action weights",
    )

    text = replace_regex(
        text,
        r"INACTIVE_PHASE_DOMAIN_MULT = \{.*?\n\}\nINACTIVE_WORLD_BOSS_SAFE_HP_RATIO =",
        textwrap.dedent(
            '''\
            INACTIVE_PHASE_DOMAIN_MULT = {
                "growth": {"building": 1.75, "research": 0.70, "ships": 0.85, "defense": 0.55, "expedition": 0.75},
                "research": {"building": 0.70, "research": 1.85, "ships": 0.75, "defense": 0.55, "expedition": 0.90},
                "fortification": {"building": 0.70, "research": 0.65, "ships": 1.15, "defense": 1.90, "expedition": 0.65},
                "balanced": {"building": 1.00, "research": 1.00, "ships": 1.00, "defense": 1.00, "expedition": 1.00},
            }
            INACTIVE_WORLD_BOSS_SAFE_HP_RATIO ='''
        ),
        label="phase multipliers",
    )

    text = replace_once(
        text,
        "INACTIVE_WORLD_BOSS_SAFE_HP_RATIO = 0.05",
        "INACTIVE_WORLD_BOSS_SAFE_HP_RATIO = 0.05\n"
        'INACTIVE_EXPEDITION_SHIP_PREFERENCE = ("solar_skiff", "eclipse_runner")',
        label="expedition hulls",
    )

    text = replace_regex(
        text,
        r"def _next_action_delay_sec\(.*?\n\n\ndef is_inactive_autoplay_enabled",
        textwrap.dedent(
            '''\
            def _next_action_delay_sec(player_id: int, personality: str, action_seq: int) -> int:
                """Human-shaped cadence: short bursts interrupted by longer breaks."""
                low, high = INACTIVE_ACTION_PACE_RANGES_SEC.get(
                    str(personality), INACTIVE_ACTION_PACE_RANGES_SEC["economy"]
                )
                low_i, high_i = max(60, int(low)), max(int(low), int(high))
                seq = max(0, int(action_seq))
                cycle = seq // 8
                burst_len = 3 + _stable_roll(player_id, "session-span", cycle, 5)
                if seq > 0 and seq % burst_len == 0:
                    return 45 * 60 + _stable_roll(
                        player_id, "session-break", seq, 3 * 3600 + 1
                    )

                quick_chance = {
                    "aggressive": 55,
                    "swarm": 50,
                    "elite": 45,
                    "spy": 40,
                    "economy": 35,
                    "turtle": 25,
                }.get(str(personality), 35)
                if _stable_roll(player_id, "quick-return", seq, 100) < quick_chance:
                    return 3 * 60 + _stable_roll(
                        player_id, "quick-gap", seq, 8 * 60 + 1
                    )
                return low_i + _stable_roll(
                    player_id, "pace", seq, high_i - low_i + 1
                )


            def is_inactive_autoplay_enabled'''
        ),
        label="human cadence",
    )

    helpers = textwrap.dedent(
        '''\

        def _stockpile_snapshot(conn, planet_id: int) -> Dict[str, int]:
            """Read the real stockpile; Human Play V5 never injects resources."""
            row = conn.execute(
                """
                SELECT COALESCE(metal, 0) AS metal,
                       COALESCE(crystal, 0) AS crystal,
                       COALESCE(fuel_cells, 0) AS fuel_cells
                FROM planets WHERE id = ? LIMIT 1;
                """,
                (int(planet_id),),
            ).fetchone()
            if not row:
                return {}
            return {
                "metal": int(float(row["metal"] or 0)),
                "crystal": int(float(row["crystal"] or 0)),
                "fuel_cells": int(float(row["fuel_cells"] or 0)),
                "raised": 0,
            }


        def _pick_progression_planet(
            player_id: int,
            planets: Sequence[Mapping[str, Any]],
            *,
            action_seq: int,
        ) -> Optional[Dict[str, Any]]:
            """Spread local decisions across the commander's owned planets."""
            candidates = [dict(p) for p in planets if int(p.get("id") or 0) > 0]
            if not candidates:
                return None
            candidates.sort(key=lambda p: int(p.get("id") or 0))
            if len(candidates) == 1:
                return candidates[0]
            idx = _stable_roll(player_id, "planet-choice", action_seq, len(candidates))
            return candidates[idx]


        def _sync_planet_for_decision(
            conn,
            player_id: int,
            planet: Mapping[str, Any],
            *,
            now: float,
            is_home: bool,
            personality: str,
            ambition_scale: float,
        ) -> Dict[str, Any]:
            """Finish due work/update production without starting a new action."""
            return plan_passive_planet_tick(
                conn,
                player_id=int(player_id),
                planet=planet,
                now=float(now),
                is_home=bool(is_home),
                allow_buildings=False,
                allow_research=False,
                allow_ships=False,
                allow_defense=False,
                personality=str(personality),
                build_duration_cap=INACTIVE_BUILD_DURATION_CAP,
                research_duration_cap=INACTIVE_RESEARCH_DURATION_CAP,
                target_scale=float(ambition_scale),
                source="inactive_autoplay",
                update_scores=True,
                chain_limit=INACTIVE_CHAIN_LIMIT,
                idle_chance=0.0,
            )


        def _pick_expedition_force(
            conn,
            player_id: int,
            *,
            action_seq: int,
        ) -> Optional[Dict[str, Any]]:
            """Pick one real expedition-capable ship from an owned planet."""
            from .fleet import get_planet_ships
            from .models import get_planets_by_player

            planets = [
                dict(p)
                for p in (get_planets_by_player(int(player_id), conn=conn) or [])
            ]
            if not planets:
                return None
            planets.sort(key=lambda p: int(p.get("id") or 0))
            start = _stable_roll(
                player_id, "expedition-origin", action_seq, len(planets)
            )
            ordered = planets[start:] + planets[:start]
            ship_order = list(INACTIVE_EXPEDITION_SHIP_PREFERENCE)
            if _stable_roll(player_id, "expedition-hull", action_seq, 2):
                ship_order.reverse()
            for planet in ordered:
                planet_id = int(planet.get("id") or 0)
                hangar = get_planet_ships(planet_id, conn=conn)
                for ship_key in ship_order:
                    if int(hangar.get(ship_key) or 0) >= 1:
                        return {
                            "planet": planet,
                            "planet_id": planet_id,
                            "galaxy": int(planet.get("galaxy") or 1),
                            "system": int(planet.get("system") or 1),
                            "ships": {ship_key: 1},
                        }
            return None


        def _maybe_send_expedition(
            conn,
            player_id: int,
            *,
            now: float,
            action_seq: int,
            home_id: int,
            personality: str,
            ambition_scale: float,
        ) -> Dict[str, Any]:
            """Send one canonical expedition when hull, slot and fuel permit it."""
            force = _pick_expedition_force(
                conn, int(player_id), action_seq=int(action_seq)
            )
            if not force:
                return {"ok": True, "sent": False, "reason": "no_expedition_ship"}

            planet = dict(force["planet"])
            _sync_planet_for_decision(
                conn,
                int(player_id),
                planet,
                now=float(now),
                is_home=int(force["planet_id"]) == int(home_id),
                personality=str(personality),
                ambition_scale=float(ambition_scale),
            )

            from .fleet import send_fleet
            from .fleet_defs import EXPEDITION_POSITION

            hours = 1 + _stable_roll(player_id, "expedition-hours", action_seq, 4)
            ok, reason, meta = send_fleet(
                player_id=int(player_id),
                origin_planet_id=int(force["planet_id"]),
                mission_type="expedition",
                target_galaxy=int(force["galaxy"]),
                target_system=int(force["system"]),
                target_position=int(EXPEDITION_POSITION),
                ships=dict(force["ships"]),
                resources={},
                speed_percent=100,
                expedition_hours=int(hours),
                conn=conn,
            )
            if not ok:
                return {
                    "ok": True,
                    "sent": False,
                    "reason": str(reason or "blocked"),
                    "planet_id": int(force["planet_id"]),
                }
            return {
                "ok": True,
                "sent": True,
                "fleet_id": int((meta or {}).get("fleet", {}).get("id") or 0),
                "planet_id": int(force["planet_id"]),
                "ships": dict(force["ships"]),
                "expedition_hours": int(hours),
            }
        '''
    )
    text = replace_once(
        text,
        "\n\ndef _run_player_economy(",
        helpers + "\n\ndef _run_player_economy(",
        label="helper insertion",
    )

    new_run = textwrap.dedent(
        '''\
        def _run_player_economy(
            conn,
            player_id: int,
            *,
            now: float,
            is_wake: bool = False,
            action_seq: int = 0,
            next_action_at: Optional[float] = None,
        ) -> Dict[str, Any]:
            """Execute one human-shaped decision through canonical game systems."""
            from .auto_empire import try_build_defense, try_build_ships
            from .models import get_homeworld, get_planets_by_player

            home = get_homeworld(player_id, conn=conn)
            if not home:
                return {"ok": False, "error": "no_homeworld", "player_id": player_id}
            home = dict(home)
            home_id = int(home["id"])
            stockpile = _stockpile_snapshot(conn, home_id)
            planets = [
                dict(p)
                for p in (get_planets_by_player(player_id, conn=conn) or [home])
            ]
            personality = personality_for_player(player_id)
            seq = max(0, int(action_seq or 0))
            strategic_phase = _strategic_phase_for_player(player_id, seq)
            ambition_scale = _ambition_scale(player_id, personality)
            personal_cooldown = bool(
                not is_wake
                and next_action_at is not None
                and float(now) < float(next_action_at)
            )
            action_domain = (
                "building"
                if is_wake
                else None
                if personal_cooldown
                else _action_domain_for_player(player_id, personality, seq)
            )
            should_idle = bool(
                not is_wake
                and not personal_cooldown
                and _stable_roll(player_id, "idle", seq, 1000)
                < int(AUTOPLAY_STANDING_IDLE_CHANCE * 1000)
            )

            results: List[Dict[str, Any]] = []
            home_synced = False
            target_planet: Optional[Dict[str, Any]] = None
            if action_domain == "research" or is_wake:
                target_planet = home
            elif action_domain in {"building", "ships", "defense"}:
                target_planet = _pick_progression_planet(
                    player_id, planets, action_seq=seq
                )

            if target_planet is not None:
                is_home = int(target_planet["id"]) == home_id or bool(
                    target_planet.get("is_homeworld")
                )
                if action_domain in {"building", "research"}:
                    try:
                        planned = plan_passive_planet_tick(
                            conn,
                            player_id=player_id,
                            planet=target_planet,
                            now=now,
                            is_home=is_home,
                            allow_buildings=action_domain == "building",
                            allow_research=action_domain == "research",
                            allow_ships=False,
                            allow_defense=False,
                            personality=personality,
                            build_duration_cap=INACTIVE_BUILD_DURATION_CAP,
                            research_duration_cap=INACTIVE_RESEARCH_DURATION_CAP,
                            target_scale=ambition_scale,
                            source="inactive_autoplay",
                            update_scores=True,
                            chain_limit=INACTIVE_CHAIN_LIMIT,
                            idle_chance=(
                                1.0 if personal_cooldown or should_idle else 0.0
                            ),
                        )
                        results.append(planned)
                        home_synced = bool(is_home)
                    except Exception:
                        logger.exception(
                            "inactive autoplay economy failed player=%s planet=%s",
                            player_id,
                            target_planet.get("id"),
                        )
                elif not personal_cooldown and not should_idle:
                    try:
                        sync = _sync_planet_for_decision(
                            conn,
                            player_id,
                            target_planet,
                            now=now,
                            is_home=is_home,
                            personality=personality,
                            ambition_scale=ambition_scale,
                        )
                        home_synced = bool(is_home)
                        if action_domain == "ships":
                            direct_action = try_build_ships(
                                conn,
                                player_id=player_id,
                                planet_id=int(target_planet["id"]),
                                personality=personality,
                            )
                            if direct_action.get("ok"):
                                sync["ships"] = direct_action
                        elif action_domain == "defense":
                            direct_action = try_build_defense(
                                conn,
                                player_id=player_id,
                                planet_id=int(target_planet["id"]),
                                personality=personality,
                                target_scale=ambition_scale,
                            )
                            if direct_action.get("ok"):
                                sync["defense"] = direct_action
                        results.append(sync)
                    except Exception:
                        logger.exception(
                            "inactive autoplay local action failed player=%s planet=%s",
                            player_id,
                            target_planet.get("id"),
                        )

            expedition = {"ok": True, "sent": False, "reason": "not_selected"}
            if (
                action_domain == "expedition"
                and not personal_cooldown
                and not should_idle
            ):
                try:
                    expedition = _maybe_send_expedition(
                        conn,
                        player_id,
                        now=now,
                        action_seq=seq,
                        home_id=home_id,
                        personality=personality,
                        ambition_scale=ambition_scale,
                    )
                    if int(expedition.get("planet_id") or 0) == home_id:
                        home_synced = True
                except Exception:
                    logger.exception(
                        "inactive autoplay expedition failed player=%s", player_id
                    )
                    expedition = {
                        "ok": False,
                        "sent": False,
                        "reason": "exception",
                    }

            # A human may idle, use a colony, or fail to launch a fleet. Due homeworld
            # work must still complete so old queues do not freeze between sessions.
            if not home_synced:
                try:
                    results.append(
                        _sync_planet_for_decision(
                            conn,
                            player_id,
                            home,
                            now=now,
                            is_home=True,
                            personality=personality,
                            ambition_scale=ambition_scale,
                        )
                    )
                    home_synced = True
                except Exception:
                    logger.exception(
                        "inactive autoplay home sync failed player=%s", player_id
                    )

            enqueued = any(
                r.get("build")
                or r.get("research")
                or r.get("ships")
                or r.get("defense")
                or r.get("builds")
                or r.get("researches")
                for r in results
            ) or bool(expedition.get("sent"))
            finished_any = any((r.get("finished") or {}) for r in results)
            finished_totals = {
                "buildings": 0,
                "research": 0,
                "defense": 0,
                "shipyard": 0,
            }
            for result in results:
                finished = result.get("finished") or {}
                for key in finished_totals:
                    try:
                        finished_totals[key] += int(finished.get(key) or 0)
                    except (TypeError, ValueError):
                        continue

            boss_participation = _maybe_join_world_boss(conn, player_id, now=now)
            next_seq = seq if personal_cooldown else seq + 1
            next_at = (
                float(next_action_at)
                if personal_cooldown and next_action_at is not None
                else None
            )
            next_delay = None
            if not personal_cooldown:
                next_delay = _next_action_delay_sec(player_id, personality, seq)
                next_at = float(now) + float(next_delay)

            last_action = _describe_last_action(results)
            if not last_action and expedition.get("sent"):
                last_action = "expedition"
            return {
                "ok": True,
                "player_id": player_id,
                "economy": results,
                "enqueued": enqueued,
                "finished": finished_any,
                "finished_totals": finished_totals,
                "last_action": last_action,
                "resource_floor": stockpile,
                "action_domain": action_domain,
                "action_seq": next_seq,
                "next_action_delay_sec": next_delay,
                "next_action_at": next_at,
                "personal_cooldown": personal_cooldown,
                "strategic_phase": strategic_phase,
                "ambition_scale": ambition_scale,
                "expedition": expedition,
                "boss_participation": boss_participation,
            }
        '''
    )
    text = replace_regex(
        text,
        r"def _run_player_economy\(.*?\n\n\ndef get_roster_snapshot",
        new_run + "\n\ndef get_roster_snapshot",
        label="player decision loop",
    )

    INACTIVE.write_text(text, encoding="utf-8")


def patch_v4_test() -> None:
    text = V4_TESTS.read_text(encoding="utf-8")
    old = 'patch("game.inactive_autoplay._ensure_resource_floor", return_value={})'
    new = 'patch("game.inactive_autoplay._stockpile_snapshot", return_value={})'
    if old in text:
        text = text.replace(old, new, 1)
    V4_TESTS.write_text(text, encoding="utf-8")


def write_v5_tests() -> None:
    V5_TESTS.write_text(
        textwrap.dedent(
            '''\
            from __future__ import annotations

            from unittest.mock import patch


            def test_v5_action_pool_has_ships_and_expeditions():
                from game.inactive_autoplay import INACTIVE_ACTION_DOMAINS

                assert "ships" in INACTIVE_ACTION_DOMAINS
                assert "expedition" in INACTIVE_ACTION_DOMAINS


            def test_v5_cadence_has_short_returns_and_long_breaks():
                from game.inactive_autoplay import _next_action_delay_sec

                gaps = [
                    _next_action_delay_sec(pid, "aggressive", seq)
                    for pid in range(1, 12)
                    for seq in range(1, 40)
                ]
                assert min(gaps) <= 11 * 60
                assert max(gaps) >= 45 * 60


            def test_v5_planet_choice_spreads_local_actions():
                from game.inactive_autoplay import _pick_progression_planet

                planets = [{"id": 1}, {"id": 2}, {"id": 3}]
                picked = {
                    _pick_progression_planet(17, planets, action_seq=seq)["id"]
                    for seq in range(20)
                }
                assert len(picked) >= 2


            def test_v5_expedition_uses_canonical_send_fleet():
                from game.inactive_autoplay import _maybe_send_expedition

                force = {
                    "planet": {"id": 77, "galaxy": 2, "system": 19},
                    "planet_id": 77,
                    "galaxy": 2,
                    "system": 19,
                    "ships": {"solar_skiff": 1},
                }
                meta = {"fleet": {"id": 555}}
                with patch(
                    "game.inactive_autoplay._pick_expedition_force",
                    return_value=force,
                ), patch(
                    "game.inactive_autoplay._sync_planet_for_decision",
                    return_value={},
                ), patch(
                    "game.fleet.send_fleet",
                    return_value=(True, "ok", meta),
                ) as send:
                    out = _maybe_send_expedition(
                        object(),
                        9,
                        now=12345.0,
                        action_seq=6,
                        home_id=77,
                        personality="spy",
                        ambition_scale=1.0,
                    )

                assert out["sent"] is True
                assert out["fleet_id"] == 555
                kwargs = send.call_args.kwargs
                assert kwargs["mission_type"] == "expedition"
                assert kwargs["ships"] == {"solar_skiff": 1}
                assert 1 <= kwargs["expedition_hours"] <= 4


            def test_v5_runtime_never_uses_resource_injection_floor():
                from game.inactive_autoplay import _run_player_economy

                home = {"id": 5, "is_homeworld": 1, "galaxy": 1, "system": 1}
                with patch("game.models.get_homeworld", return_value=home), patch(
                    "game.models.get_planets_by_player", return_value=[home]
                ), patch(
                    "game.inactive_autoplay._stockpile_snapshot",
                    return_value={"metal": 0, "crystal": 0, "fuel_cells": 0, "raised": 0},
                ), patch(
                    "game.inactive_autoplay._ensure_resource_floor"
                ) as floor, patch(
                    "game.inactive_autoplay._action_domain_for_player",
                    return_value="building",
                ), patch(
                    "game.inactive_autoplay.plan_passive_planet_tick",
                    return_value={"build": None, "finished": {}},
                ), patch(
                    "game.inactive_autoplay._maybe_join_world_boss",
                    return_value={"ok": True, "joined": False},
                ):
                    out = _run_player_economy(object(), 4, now=1000.0, action_seq=0)

                assert out["ok"] is True
                floor.assert_not_called()


            def test_v5_ship_decision_uses_real_shipyard_without_timekeeper_boost():
                from game.inactive_autoplay import _run_player_economy

                home = {"id": 5, "is_homeworld": 1, "galaxy": 1, "system": 1}
                ship_result = {
                    "ok": True,
                    "ship_key": "solar_skiff",
                    "amount": 1,
                    "meta": {},
                }
                with patch("game.models.get_homeworld", return_value=home), patch(
                    "game.models.get_planets_by_player", return_value=[home]
                ), patch(
                    "game.inactive_autoplay._stockpile_snapshot",
                    return_value={},
                ), patch(
                    "game.inactive_autoplay._action_domain_for_player",
                    return_value="ships",
                ), patch(
                    "game.inactive_autoplay._stable_roll", return_value=999
                ), patch(
                    "game.inactive_autoplay._sync_planet_for_decision",
                    return_value={"finished": {}},
                ), patch(
                    "game.auto_empire.try_build_ships", return_value=ship_result
                ) as build, patch(
                    "game.auto_empire._auto_boost_timekeeper"
                ) as boost, patch(
                    "game.inactive_autoplay._maybe_join_world_boss",
                    return_value={"ok": True, "joined": False},
                ):
                    out = _run_player_economy(object(), 4, now=1000.0, action_seq=0)

                assert out["enqueued"] is True
                build.assert_called_once()
                boost.assert_not_called()
            '''
        ),
        encoding="utf-8",
    )


def main() -> None:
    patch_inactive_autoplay()
    patch_v4_test()
    write_v5_tests()
    if WORKFLOW.exists():
        WORKFLOW.unlink()
    if SELF.exists():
        SELF.unlink()


if __name__ == "__main__":
    main()
