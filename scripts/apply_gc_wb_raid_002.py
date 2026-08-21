#!/usr/bin/env python3
"""One-shot/idempotent codemod for GC-WB-RAID-002.

Patches the canonical World Boss owner and its SSR template without introducing a
second combat/state owner. Safe to re-run: markers make every transformation
idempotent and missing source anchors fail loudly.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB = ROOT / "game" / "world_boss.py"
TPL = ROOT / "templates" / "world_boss.html"
TEST = ROOT / "tests" / "test_world_boss_raid.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"GC-WB-RAID-002 anchor missing: {label}")
    return text.replace(old, new, 1)


def patch_world_boss() -> None:
    text = WB.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "WAVE_HP_FRACTION = 0.02\n# Soft overkill: 1 + scale * log2(1 + force_ratio). Mega fleets approach the cap.\nOVERKILL_LOG_SCALE = 0.15\n# Cap ≈ 8% → solo mega fleet needs ~13 waves (target band 10–20 hits).\nMAX_WAVE_HP_FRACTION = 0.08\n",
        "WAVE_HP_FRACTION = 0.0125\n# Soft overkill remains useful for prestige fleets, but cannot dominate the raid.\nOVERKILL_LOG_SCALE = 0.10\n# Hard single-wave ceiling; final action caps are enforced after raid modifiers too.\nMAX_WAVE_HP_FRACTION = 0.03\n",
        "damage constants",
    )

    text = replace_once(
        text,
        "ALLIANCE_SALVO_FRACTION = 0.0  # reserved; visual hook only until LIVEOPS tuning\n",
        "ALLIANCE_SALVO_FRACTION = 0.0  # reserved; visual hook only until LIVEOPS tuning\n\n"
        "# GC-WB-RAID-002 — Monster-Warlord-inspired community raid pacing.\n"
        "RAID_CONTAINMENT_SECONDS = 2 * 3600\n"
        "RAID_RESONANCE_THRESHOLD = 100\n"
        "RAID_RESONANCE_DURATION_SECONDS = 10 * 60\n"
        "RAID_RESONANCE_DAMAGE_MULT = 1.50\n"
        "RAID_RESONANCE_CRIT_BONUS = 0.10\n"
        "RAID_LAST_STAND_LIFETIME_RATIO = 0.75\n"
        "RAID_LAST_STAND_DAMAGE_MULT = 1.25\n"
        "RAID_TARGET_LOCK_PER_WAVE = 20\n"
        "RAID_TARGET_LOCK_RESONANCE_PER_WAVE = 25\n"
        "RAID_SINGLE_ACTION_CAP_FRACTION = 0.03\n"
        "RAID_MULTI_ACTION_CAP_FRACTION = 0.125\n",
        "raid constants",
    )

    text = replace_once(
        text,
        "soft_cap = int(float(hp_budget) * 0.45) if hp_budget > 0 else int(scaled)",
        "soft_cap = int(float(hp_budget) * float(RAID_MULTI_ACTION_CAP_FRACTION)) if hp_budget > 0 else int(scaled)",
        "x5 cap",
    )
    text = text.replace("soft-caps at 45% HP.", "hard-caps at 12.5% HP.", 1)

    helper_marker = "# GC-WB-RAID-002 HELPERS\n"
    if helper_marker not in text:
        anchor = "\ndef execute_instant_attack(\n"
        if anchor not in text:
            raise SystemExit("GC-WB-RAID-002 anchor missing: execute_instant_attack")
        helpers = r'''
# GC-WB-RAID-002 HELPERS

def _raid_event_columns_ready(conn) -> bool:
    from .db import column_exists

    return all(
        column_exists(conn, WORLD_BOSS_EVENT_TABLE, key)
        for key in (
            "resonance_points",
            "resonance_ends_at",
            "resonance_initiator_player_id",
            "finisher_player_id",
        )
    )


def _raid_target_lock_ready(conn) -> bool:
    from .db import column_exists

    return column_exists(conn, WORLD_BOSS_CONTRIB_TABLE, "target_lock")


def get_world_boss_raid_state(
    event: Mapping[str, Any],
    player_id: Optional[int] = None,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Server-authored raid state used by combat, SSR and attack responses."""
    ts = float(now if now is not None else _now())
    starts_at = float(event.get("starts_at") or ts)
    ends_at = float(event.get("ends_at") or starts_at)
    lifetime = max(1.0, ends_at - starts_at)
    last_stand_at = starts_at + lifetime * float(RAID_LAST_STAND_LIFETIME_RATIO)
    last_stand_active = bool(
        str(event.get("status") or "") == STATUS_ACTIVE and ts >= last_stand_at and ts < ends_at
    )
    containment_ends_at = starts_at + float(RAID_CONTAINMENT_SECONDS)
    containment_active = bool(
        str(event.get("status") or "") == STATUS_ACTIVE
        and not last_stand_active
        and ts < containment_ends_at
    )

    points = 0
    resonance_ends_at = None
    initiator_id = None
    finisher_id = None
    if _raid_event_columns_ready(conn):
        row = conn.execute(
            """
            SELECT resonance_points, resonance_ends_at,
                   resonance_initiator_player_id, finisher_player_id
            FROM world_boss_events WHERE id = ? LIMIT 1;
            """,
            (int(event.get("id") or 0),),
        ).fetchone()
        if row:
            points = max(0, int(row["resonance_points"] or 0))
            resonance_ends_at = (
                float(row["resonance_ends_at"])
                if row["resonance_ends_at"] is not None
                else None
            )
            initiator_id = (
                int(row["resonance_initiator_player_id"])
                if row["resonance_initiator_player_id"] is not None
                else None
            )
            finisher_id = (
                int(row["finisher_player_id"])
                if row["finisher_player_id"] is not None
                else None
            )
    resonance_active = bool(resonance_ends_at is not None and ts < resonance_ends_at)

    target_lock = 0
    player_damage = 0
    if player_id is not None:
        lock_select = ", target_lock" if _raid_target_lock_ready(conn) else ""
        row = conn.execute(
            f"""
            SELECT damage{lock_select}
            FROM world_boss_contributions
            WHERE event_id = ? AND player_id = ? LIMIT 1;
            """,
            (int(event.get("id") or 0), int(player_id)),
        ).fetchone()
        if row:
            player_damage = max(0, int(row["damage"] or 0))
            if _raid_target_lock_ready(conn):
                target_lock = max(0, min(100, int(row["target_lock"] or 0)))

    max_hp = max(1, int(event.get("max_hp") or 1))
    damage_ratio = float(player_damage) / float(max_hp)
    if damage_ratio < 0.05:
        containment_efficiency = 1.0
    elif damage_ratio < 0.10:
        containment_efficiency = 0.25
    else:
        containment_efficiency = 0.05

    progress_pct = 100.0 if resonance_active else min(
        100.0,
        (float(points) / float(max(1, RAID_RESONANCE_THRESHOLD))) * 100.0,
    )
    return {
        "containment": {
            "active": containment_active,
            "ends_at": float(containment_ends_at),
            "seconds": int(RAID_CONTAINMENT_SECONDS),
            "player_damage_ratio": round(damage_ratio, 6),
            "current_efficiency": containment_efficiency,
        },
        "resonance": {
            "active": resonance_active,
            "points": int(points),
            "threshold": int(RAID_RESONANCE_THRESHOLD),
            "progress_pct": round(progress_pct, 2),
            "ends_at": resonance_ends_at,
            "damage_mult": float(RAID_RESONANCE_DAMAGE_MULT) if resonance_active else 1.0,
            "crit_bonus": float(RAID_RESONANCE_CRIT_BONUS) if resonance_active else 0.0,
            "initiator_player_id": initiator_id,
        },
        "last_stand": {
            "active": last_stand_active,
            "starts_at": float(last_stand_at),
            "damage_mult": float(RAID_LAST_STAND_DAMAGE_MULT) if last_stand_active else 1.0,
        },
        "target_lock": {
            "charge": int(target_lock),
            "ready": bool(target_lock >= 100),
            "gain_per_wave": int(
                RAID_TARGET_LOCK_RESONANCE_PER_WAVE
                if resonance_active
                else RAID_TARGET_LOCK_PER_WAVE
            ),
        },
        "finisher_player_id": finisher_id,
    }


def _apply_raid_containment(raw_damage: int, current_damage: int, max_hp: int) -> int:
    """Piecewise 100% / 25% / 5% effective damage during opening containment."""
    remaining_raw = float(max(0, int(raw_damage)))
    if remaining_raw <= 0:
        return 0
    hp = float(max(1, int(max_hp)))
    effective_pos = float(max(0, int(current_damage)))
    gained = 0.0
    for ceiling, efficiency in ((0.05 * hp, 1.0), (0.10 * hp, 0.25), (float("inf"), 0.05)):
        if remaining_raw <= 0:
            break
        if effective_pos >= ceiling:
            continue
        effective_capacity = ceiling - effective_pos
        raw_capacity = effective_capacity / efficiency
        raw_take = min(remaining_raw, raw_capacity)
        effective_take = raw_take * efficiency
        gained += effective_take
        effective_pos += effective_take
        remaining_raw -= raw_take
    out = int(max(0.0, gained))
    return max(1, out) if raw_damage > 0 else 0


def _apply_raid_damage_rules(
    raw_damage: int,
    *,
    hit_mult: int,
    event: Mapping[str, Any],
    player_id: int,
    conn,
    now: float,
) -> Tuple[int, Dict[str, Any], Dict[str, Any]]:
    """Apply raid buffs, strict action cap, then opening containment."""
    state = get_world_boss_raid_state(event, int(player_id), conn=conn, now=now)
    max_hp = max(1, int(event.get("max_hp") or 1))
    boosted = float(max(0, int(raw_damage)))
    damage_mult = 1.0
    if state["resonance"]["active"]:
        damage_mult *= float(RAID_RESONANCE_DAMAGE_MULT)
    if state["last_stand"]["active"]:
        damage_mult *= float(RAID_LAST_STAND_DAMAGE_MULT)
    boosted *= damage_mult

    cap_fraction = (
        float(RAID_MULTI_ACTION_CAP_FRACTION)
        if int(hit_mult or 1) > 1
        else float(RAID_SINGLE_ACTION_CAP_FRACTION)
    )
    action_cap = max(1, int(float(max_hp) * cap_fraction))
    capped = min(action_cap, max(0, int(round(boosted))))

    current_damage = int(
        round(float(state["containment"].get("player_damage_ratio") or 0.0) * float(max_hp))
    )
    final_damage = capped
    if state["containment"]["active"]:
        final_damage = _apply_raid_containment(capped, current_damage, max_hp)
    final_damage = min(action_cap, max(0, int(final_damage)))
    return final_damage, {
        "damage_mult": round(damage_mult, 3),
        "action_cap": int(action_cap),
        "action_cap_fraction": cap_fraction,
        "pre_raid_damage": int(raw_damage),
        "boosted_damage": int(round(boosted)),
        "capped_damage": int(capped),
        "containment_applied": bool(state["containment"]["active"]),
        "final_damage": int(final_damage),
    }, state


def _advance_world_boss_raid_after_hit(
    *,
    event: Mapping[str, Any],
    player_id: int,
    hit_mult: int,
    target_lock_before: int,
    target_lock_consumed: bool,
    defeated: bool,
    conn,
    now: float,
    state_before: Mapping[str, Any],
) -> Dict[str, Any]:
    """Charge personal Target Lock and the shared Fleet Resonance meter."""
    eid = int(event.get("id") or 0)
    pid = int(player_id)
    mult = max(1, int(hit_mult or 1))

    if _raid_target_lock_ready(conn):
        base_lock = max(0, int(target_lock_before) - (100 if target_lock_consumed else 0))
        per_wave = (
            int(RAID_TARGET_LOCK_RESONANCE_PER_WAVE)
            if bool((state_before.get("resonance") or {}).get("active"))
            else int(RAID_TARGET_LOCK_PER_WAVE)
        )
        new_lock = min(100, base_lock + per_wave * mult)
        conn.execute(
            """
            UPDATE world_boss_contributions
            SET target_lock = ?, updated_at = ?
            WHERE event_id = ? AND player_id = ?;
            """,
            (int(new_lock), float(now), eid, pid),
        )

    if _raid_event_columns_ready(conn):
        row = conn.execute(
            """
            SELECT resonance_points, resonance_ends_at
            FROM world_boss_events WHERE id = ? LIMIT 1;
            """,
            (eid,),
        ).fetchone()
        points = max(0, int(row["resonance_points"] or 0)) if row else 0
        resonance_ends_at = (
            float(row["resonance_ends_at"])
            if row and row["resonance_ends_at"] is not None
            else None
        )
        resonance_active = bool(resonance_ends_at is not None and float(now) < resonance_ends_at)
        activated = False
        if not resonance_active and not defeated:
            points += mult
            if points >= int(RAID_RESONANCE_THRESHOLD):
                points = 0
                resonance_ends_at = float(now) + float(RAID_RESONANCE_DURATION_SECONDS)
                activated = True
        conn.execute(
            """
            UPDATE world_boss_events
            SET resonance_points = ?,
                resonance_ends_at = ?,
                resonance_initiator_player_id = CASE
                    WHEN ? THEN ? ELSE resonance_initiator_player_id END,
                finisher_player_id = CASE
                    WHEN ? THEN ? ELSE finisher_player_id END,
                updated_at = ?
            WHERE id = ?;
            """,
            (
                int(points),
                resonance_ends_at,
                1 if activated else 0,
                pid,
                1 if defeated else 0,
                pid,
                float(now),
                eid,
            ),
        )

    return get_world_boss_raid_state(event, pid, conn=conn, now=now)


def build_world_boss_recognition(event_id: int, *, conn) -> Dict[str, Any]:
    """Small MVP recognition board; prestige only, no extra economy payout."""
    contribs = list_contributions(int(event_id), conn=conn, limit=10000)
    top_damage = next((row for row in contribs if int(row.get("damage") or 0) > 0), None)
    most_waves = max(contribs, key=lambda row: int(row.get("waves") or 0), default=None)
    event = get_event_by_id(int(event_id), conn=conn) or {}
    initiator_id = None
    finisher_id = None
    if _raid_event_columns_ready(conn):
        row = conn.execute(
            """
            SELECT resonance_initiator_player_id, finisher_player_id
            FROM world_boss_events WHERE id = ? LIMIT 1;
            """,
            (int(event_id),),
        ).fetchone()
        if row:
            initiator_id = row["resonance_initiator_player_id"]
            finisher_id = row["finisher_player_id"]

    def player_ref(pid):
        if pid is None:
            return None
        return {"player_id": int(pid), "player_name": _player_name(int(pid), conn=conn)}

    return {
        "top_damage": (
            {
                "player_id": int(top_damage["player_id"]),
                "player_name": str(top_damage.get("player_name") or ""),
                "value": int(top_damage.get("damage") or 0),
            }
            if top_damage
            else None
        ),
        "most_waves": (
            {
                "player_id": int(most_waves["player_id"]),
                "player_name": str(most_waves.get("player_name") or ""),
                "value": int(most_waves.get("waves") or 0),
            }
            if most_waves and int(most_waves.get("waves") or 0) > 0
            else None
        ),
        "resonance_initiator": player_ref(initiator_id),
        "finisher": player_ref(finisher_id),
        "discoverer": player_ref(event.get("discovered_by_player_id")),
    }

'''
        text = text.replace(anchor, "\n" + helpers + "def execute_instant_attack(\n", 1)

    start = text.index("def execute_instant_attack(\n")
    end = text.index("\ndef compute_world_boss_hp_damage(\n", start)
    if "GC-WB-RAID-002 — resolve" not in text[start:end]:
        replacement = r'''def execute_instant_attack(
    player_id: int,
    event_id: int,
    ships: Mapping[str, int] | None,
    *,
    planet_id: int,
    conn,
    now: Optional[float] = None,
    rng: Any = None,
    auto_select: bool = False,
    hit_mult: int = 1,
) -> Dict[str, Any]:
    """
    GC-WB-RAID-002 — resolve a server-owned World Boss raid strike in-request.

    Ships stay in hangar. Damage, cooldown, contribution, Containment, Fleet
    Resonance and Target Lock are resolved in the same DB transaction owned by
    the caller. ``hit_mult`` ∈ {1, 5}; ×5 remains five waves / five cooldowns.
    """
    import random

    from .fleet import get_planet_ships

    ts = float(now if now is not None else _now())
    pid = int(player_id)
    eid = int(event_id)
    origin_id = int(planet_id)
    try:
        mult = int(hit_mult or 1)
    except (TypeError, ValueError):
        mult = 1
    if mult not in ALLOWED_HIT_MULT:
        return {"ok": False, "error": "invalid_hit_mult", "attack": None, "boss": None, "player": None}

    ok_atk, reason, meta = can_player_attack_boss(
        pid, eid, conn=conn, now=ts, enforce_cooldown=True, check_inflight=False
    )
    if not ok_atk:
        return {
            "ok": False,
            "error": reason,
            "attack": None,
            "boss": None,
            "player": None,
            **(meta or {}),
        }

    waves_done = int((meta or {}).get("waves") or 0)
    if waves_done + mult > int(MAX_WAVES_PER_PLAYER):
        return {
            "ok": False,
            "error": "world_boss_wave_limit",
            "attack": None,
            "boss": None,
            "player": None,
            "waves": waves_done,
            "max_waves": int(MAX_WAVES_PER_PLAYER),
            "hit_mult": mult,
        }

    event = meta.get("event") or get_event_by_id(eid, conn=conn)
    if not event or event["status"] != STATUS_ACTIVE:
        return {"ok": False, "error": "world_boss_inactive", "attack": None, "boss": None, "player": None}

    hangar = get_planet_ships(origin_id, conn=conn)
    selected = _normalize_attack_ships(ships)
    if auto_select or not selected:
        defender_preview = defender_ships_for_event(event, conn=conn)
        selected, pick_meta = select_world_boss_auto_attack_ships(
            hangar,
            defender_ships=defender_preview,
            max_hp=int(event.get("max_hp") or 0),
            event_id=eid,
            conn=conn,
        )
        if not selected:
            return {
                "ok": False,
                "error": "no_combat_ships_available",
                "attack": None,
                "boss": None,
                "player": None,
                "auto_meta": pick_meta,
            }

    ok_ships, ship_reason = _validate_ships_in_hangar(selected, hangar)
    if not ok_ships:
        return {"ok": False, "error": ship_reason, "attack": None, "boss": None, "player": None}

    definition = get_definition(event["boss_key"], conn=conn) or {}
    phase_index, defender_ships = _resolve_phase_stacks(
        definition,
        current_hp=int(event["current_hp"]),
        max_hp=int(event["max_hp"]),
        current_stacks=event.get("fleet_stacks") or {},
    )

    battle_rng = rng if rng is not None else random.Random(
        int(eid) * 1_000_003 + int(pid) * 97 + int(ts)
    )
    raid_before = get_world_boss_raid_state(event, pid, conn=conn, now=ts)
    target_lock_before = int((raid_before.get("target_lock") or {}).get("charge") or 0)
    guaranteed_crit = bool(target_lock_before >= 100)
    crit_chance = min(
        0.95,
        float(INSTANT_CRIT_CHANCE)
        + float((raid_before.get("resonance") or {}).get("crit_bonus") or 0.0),
    )
    critical = bool(guaranteed_crit or battle_rng.random() < crit_chance)

    attack_power = compute_attack_power(selected, player_id=pid, planet_id=origin_id, conn=conn)
    rolled = compute_instant_hp_damage(
        ships=selected,
        defender_ships=defender_ships,
        max_hp=int(event["max_hp"]),
        critical=critical,
    )
    if mult > 1:
        rolled = scale_instant_hit_damage(
            rolled, hit_mult=mult, max_hp=int(event["max_hp"]), rng=battle_rng
        )
    else:
        rolled = max(0, int(rolled))

    alliance_salvo = 0
    if float(ALLIANCE_SALVO_FRACTION) > 0:
        alliance_salvo = int(rolled * float(ALLIANCE_SALVO_FRACTION))
        rolled += alliance_salvo

    rolled, raid_damage_meta, raid_before = _apply_raid_damage_rules(
        rolled,
        hit_mult=mult,
        event=event,
        player_id=pid,
        conn=conn,
        now=ts,
    )
    if rolled <= 0:
        return {
            "ok": False,
            "error": "world_boss_no_damage",
            "attack": None,
            "boss": None,
            "player": None,
            "attack_power": attack_power,
            "raid": raid_before,
        }

    before_hp = int(event["current_hp"])
    max_hp = int(event["max_hp"])
    cur = conn.execute(
        """
        UPDATE world_boss_events
        SET current_hp = MAX(0, current_hp - ?), updated_at = ?
        WHERE id = ? AND status = ? AND current_hp > 0;
        """,
        (int(rolled), ts, eid, STATUS_ACTIVE),
    )
    if int(cur.rowcount or 0) <= 0:
        return {"ok": False, "error": "world_boss_defeated", "attack": None, "boss": None, "player": None}

    updated_row = conn.execute(
        "SELECT current_hp FROM world_boss_events WHERE id = ? LIMIT 1;", (eid,)
    ).fetchone()
    new_hp = max(0, int(updated_row["current_hp"] if updated_row else 0))
    applied = max(0, before_hp - new_hp)
    defeated = new_hp <= 0

    if applied > 0:
        try:
            from .stellar_forge import grant_forge_cores, record_operational_progress

            record_operational_progress(origin_id, "titan", applied, conn=conn, now=ts)
            if defeated and random.random() < 0.5:
                grant_forge_cores(pid, 1, conn=conn, now=ts)
        except Exception:
            logger.exception("stellar_forge world boss hook failed event=%s player=%s", eid, pid)

    new_phase, remaining_def = _resolve_phase_stacks(
        definition, current_hp=new_hp, max_hp=max_hp, current_stacks=defender_ships
    )
    new_status = STATUS_DEFEATED if defeated else STATUS_ACTIVE
    conn.execute(
        """
        UPDATE world_boss_events
        SET phase_index = ?, fleet_stacks_json = ?, status = ?,
            defeated_at = CASE WHEN ? THEN ? ELSE defeated_at END,
            updated_at = ?
        WHERE id = ?;
        """,
        (
            int(new_phase),
            _json_dumps(remaining_def),
            new_status,
            1 if defeated else 0,
            ts,
            ts,
            eid,
        ),
    )

    try:
        from .pirates.hooks import safe_record_heat
        safe_record_heat(conn, int(event.get("galaxy") or 0) or None, "world_boss")
    except Exception:
        logger.exception("pirate heat world_boss instant hook failed event_id=%s", eid)

    alliance_id = None
    try:
        from .alliance import get_player_alliance
        membership = get_player_alliance(pid, conn=conn)
        if membership:
            alliance_id = int(membership["alliance_id"])
    except Exception:
        logger.exception("world_boss alliance lookup failed player=%s", pid)

    note_attack_dispatched(
        pid, eid, conn=conn, now=ts, alliance_id=alliance_id, hit_mult=mult
    )

    wave_xp = 0
    alliance_xp_granted = 0
    if alliance_id is not None and applied > 0:
        wave_xp = alliance_xp_from_boss_damage(int(applied))

    _upsert_contribution(
        event_id=eid,
        player_id=pid,
        alliance_id=alliance_id,
        damage=applied,
        alliance_xp=wave_xp,
        now=ts,
        conn=conn,
        wave_delta=mult,
    )

    raid_after = _advance_world_boss_raid_after_hit(
        event=event,
        player_id=pid,
        hit_mult=mult,
        target_lock_before=target_lock_before,
        target_lock_consumed=guaranteed_crit,
        defeated=defeated,
        conn=conn,
        now=ts,
        state_before=raid_before,
    )

    if alliance_id is not None and wave_xp > 0:
        try:
            from .alliance import grant_alliance_xp
            alliance_xp_granted = int(grant_alliance_xp(int(alliance_id), wave_xp, conn=conn))
        except Exception:
            logger.exception("world_boss alliance xp failed player=%s alliance=%s", pid, alliance_id)

    try:
        from .directives.progress import emit_world_boss_damage_event
        waves_after = int(meta.get("waves") or 0) + int(mult)
        synth_movement = int(eid) * 1_000_000 + (pid % 10_000) * 100 + (waves_after % 100)
        emit_world_boss_damage_event(
            pid,
            movement_id=synth_movement,
            damage=applied,
            event_id=eid,
            conn=conn,
            now=ts,
        )
    except Exception:
        logger.exception("world_boss directive emit failed instant event=%s", eid)

    updated = get_event_by_id(eid, conn=conn)
    if defeated and updated:
        set_runtime_value(SCHEDULE_RUNTIME_KEY, str(ts), conn=conn)
        try:
            _announce_defeat(updated, conn=conn)
        except Exception:
            logger.exception("world_boss defeat news failed event=%s", eid)

    cooldown_until = float(ts + WAVE_COOLDOWN_SEC * int(mult))
    hp_ratio = (float(new_hp) / float(max_hp)) if max_hp > 0 else 0.0
    contrib_row = conn.execute(
        """
        SELECT damage, waves FROM world_boss_contributions
        WHERE event_id = ? AND player_id = ? LIMIT 1;
        """,
        (eid, pid),
    ).fetchone()
    total_damage = int(contrib_row["damage"] or 0) if contrib_row else int(applied)
    waves_done = int(contrib_row["waves"] or 0) if contrib_row else int(mult)

    rank = None
    total_players = None
    try:
        contribs = list_contributions(eid, conn=conn, limit=200)
        total_players = len(contribs)
        for row in contribs:
            if int(row.get("player_id") or 0) == pid:
                rank = int(row.get("rank") or 0)
                break
    except Exception:
        logger.exception("world_boss rank lookup failed")

    hangar_after = get_planet_ships(origin_id, conn=conn)
    return {
        "ok": True,
        "error": "",
        "attack": {
            "damage": int(applied),
            "critical": bool(critical),
            "critical_guaranteed": bool(guaranteed_crit),
            "crit_chance": round(float(crit_chance), 4),
            "projectile_profile": _projectile_profile_for_ships(selected),
            "hit_at": int(ts),
            "alliance_salvo": int(alliance_salvo),
            "attack_power": int(attack_power),
            "ships": dict(selected),
            "hit_mult": int(mult),
            "raid_modifiers": raid_damage_meta,
            "target_lock_before": int(target_lock_before),
            "target_lock_after": int((raid_after.get("target_lock") or {}).get("charge") or 0),
        },
        "boss": {
            "event_id": eid,
            "hp": int(new_hp),
            "max_hp": int(max_hp),
            "hp_pct": round(max(0.0, min(100.0, hp_ratio * 100.0)), 2),
            "phase": int(hp_phase_from_ratio(hp_ratio)),
            "phase_index": int(new_phase),
            "defeated": bool(defeated),
            "status": new_status,
            "boss_key": str(event.get("boss_key") or ""),
            "raid": raid_after,
        },
        "player": {
            "total_damage": int(total_damage),
            "rank": rank,
            "total_players": total_players,
            "cooldown_until": cooldown_until,
            "waves": int(waves_done),
            "max_waves": int(MAX_WAVES_PER_PLAYER),
            "alliance_xp_granted": int(alliance_xp_granted),
            "raid": raid_after,
        },
        "ships_snapshot": dict(selected),
        "hangar_unchanged": hangar_after == hangar,
        "event": updated,
        "raid": raid_after,
        "recognition": build_world_boss_recognition(eid, conn=conn),
        "damage": int(applied),
        "defeated": bool(defeated),
    }
'''
        text = text[:start] + replacement + text[end:]

    text = replace_once(
        text,
        "    contribs = list_contributions(int(event[\"id\"]), conn=conn, limit=100)\n    alliance_board = list_alliance_contributions(int(event[\"id\"]), conn=conn, limit=50)\n",
        "    contribs = list_contributions(int(event[\"id\"]), conn=conn, limit=100)\n"
        "    alliance_board = list_alliance_contributions(int(event[\"id\"]), conn=conn, limit=50)\n"
        "    raid_state = get_world_boss_raid_state(event, player_id, conn=conn, now=now)\n"
        "    recognition = build_world_boss_recognition(int(event[\"id\"]), conn=conn)\n",
        "event card raid state",
    )
    text = replace_once(
        text,
        '            "auto_attack_enabled": auto_enabled,\n            "catch": None,\n',
        '            "auto_attack_enabled": auto_enabled,\n            "raid": raid_state,\n            "catch": None,\n',
        "player raid payload",
    )
    text = replace_once(
        text,
        '        "event": event,\n        "contributions": contribs,\n',
        '        "event": event,\n        "raid": raid_state,\n        "recognition": recognition,\n        "contributions": contribs,\n',
        "card raid payload",
    )

    WB.write_text(text, encoding="utf-8")


def patch_template() -> None:
    text = TPL.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "        {% set cooldown_until = atk_meta.cooldown_until if atk_meta.cooldown_until is defined else (atk_meta.next_attack_at if atk_meta.next_attack_at is defined else none) %}\n",
        "        {% set cooldown_until = atk_meta.cooldown_until if atk_meta.cooldown_until is defined else (atk_meta.next_attack_at if atk_meta.next_attack_at is defined else none) %}\n"
        "        {% set raid = card.raid if card.raid is defined and card.raid else {} %}\n",
        "template raid variable",
    )

    marker = '                  <div class="gc-world-boss-formation" data-wb-formation'
    if "data-wb-raid-state" not in text:
        if marker not in text:
            raise SystemExit("GC-WB-RAID-002 anchor missing: template formation")
        block = r'''                  {% if raid %}
                  <div class="gc-world-boss-raid-strip" data-wb-raid-state
                       style="display:grid;gap:.45rem;margin:.65rem 0;padding:.65rem .75rem;border:1px solid rgba(120,190,255,.22);background:rgba(4,14,28,.72);border-radius:.65rem;">
                    <div style="display:flex;gap:.55rem;flex-wrap:wrap;align-items:center;justify-content:space-between;">
                      {% if raid.containment and raid.containment.active %}
                      <span class="gc-world-boss-status-badge" data-wb-containment>
                        🛡 {{ T("wb_raid_containment", "Containment") }} ·
                        <span data-countdown-at="{{ raid.containment.ends_at|int }}" data-countdown-format="eta">—</span>
                      </span>
                      {% endif %}
                      {% if raid.resonance and raid.resonance.active %}
                      <span class="gc-world-boss-status-badge gc-world-boss-status-badge--active" data-wb-resonance-active>
                        ⚡ {{ T("wb_raid_resonance", "Fleet Resonance") }} +50% ·
                        <span data-countdown-at="{{ raid.resonance.ends_at|int }}" data-countdown-format="eta">—</span>
                      </span>
                      {% elif raid.resonance %}
                      <span class="hint gc-mono" data-wb-resonance-label>
                        ⚡ {{ T("wb_raid_resonance", "Fleet Resonance") }} {{ raid.resonance.points }} / {{ raid.resonance.threshold }}
                      </span>
                      {% endif %}
                      {% if raid.last_stand and raid.last_stand.active %}
                      <span class="gc-world-boss-status-badge gc-world-boss-status-badge--active" data-wb-last-stand>
                        🚨 {{ T("wb_raid_last_stand", "Last Stand") }} +25%
                      </span>
                      {% endif %}
                    </div>
                    {% if raid.resonance %}
                    <div class="gc-world-boss-hp" role="meter" aria-valuemin="0" aria-valuemax="100"
                         aria-valuenow="{{ raid.resonance.progress_pct|int }}" data-wb-resonance-meter>
                      <div class="gc-world-boss-hp-fill" data-wb-resonance-fill
                           style="width: {{ raid.resonance.progress_pct }}%;"></div>
                    </div>
                    {% endif %}
                    {% if raid.target_lock %}
                    <div style="display:flex;gap:.55rem;align-items:center;">
                      <span class="hint" style="white-space:nowrap;">🎯 {{ T("wb_raid_target_lock", "Target Lock") }}</span>
                      <div class="gc-world-boss-hp" role="meter" aria-valuemin="0" aria-valuemax="100"
                           aria-valuenow="{{ raid.target_lock.charge|int }}" data-wb-target-lock-meter style="flex:1;">
                        <div class="gc-world-boss-hp-fill" data-wb-target-lock-fill
                             style="width: {{ raid.target_lock.charge }}%;"></div>
                      </div>
                      <span class="gc-mono">{{ raid.target_lock.charge }}%</span>
                    </div>
                    {% endif %}
                  </div>
                  {% endif %}

'''
        text = text.replace(marker, block + marker, 1)
    TPL.write_text(text, encoding="utf-8")


def write_tests() -> None:
    if TEST.exists():
        return
    TEST.write_text(r'''"""GC-WB-RAID-002 focused raid pacing tests."""
from __future__ import annotations

import sqlite3

from game.world_boss import (
    RAID_MULTI_ACTION_CAP_FRACTION,
    RAID_RESONANCE_THRESHOLD,
    RAID_SINGLE_ACTION_CAP_FRACTION,
    _advance_world_boss_raid_after_hit,
    _apply_raid_containment,
    _apply_raid_damage_rules,
    get_world_boss_raid_state,
    scale_instant_hit_damage,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE world_boss_events (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            resonance_points INTEGER NOT NULL DEFAULT 0,
            resonance_ends_at REAL,
            resonance_initiator_player_id INTEGER,
            finisher_player_id INTEGER,
            updated_at REAL
        );
        CREATE TABLE world_boss_contributions (
            event_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            damage INTEGER NOT NULL DEFAULT 0,
            waves INTEGER NOT NULL DEFAULT 0,
            target_lock INTEGER NOT NULL DEFAULT 0,
            updated_at REAL,
            PRIMARY KEY(event_id, player_id)
        );
        INSERT INTO world_boss_events(id,status,resonance_points,updated_at)
        VALUES (1,'active',0,0);
        INSERT INTO world_boss_contributions(event_id,player_id,damage,waves,target_lock,updated_at)
        VALUES (1,7,0,0,0,0);
        """
    )
    return conn


def _event(now=1000.0):
    return {
        "id": 1,
        "status": "active",
        "max_hp": 1_000_000,
        "current_hp": 1_000_000,
        "starts_at": now,
        "ends_at": now + 48 * 3600,
    }


def test_opening_containment_piecewise():
    hp = 1_000_000
    assert _apply_raid_containment(50_000, 0, hp) == 50_000
    # Crossing 5%: first 10k is full, remaining 30k only 25% effective.
    assert _apply_raid_containment(40_000, 40_000, hp) == 17_500
    # Above 10% contribution only 5% effective.
    assert _apply_raid_containment(100_000, 100_000, hp) == 5_000


def test_strict_action_caps_even_with_large_raw_damage():
    conn = _conn()
    try:
        event = _event()
        # After containment window so only strict cap is relevant.
        one, meta1, _ = _apply_raid_damage_rules(
            999_999_999, hit_mult=1, event=event, player_id=7, conn=conn, now=event["starts_at"] + 3 * 3600
        )
        five, meta5, _ = _apply_raid_damage_rules(
            999_999_999, hit_mult=5, event=event, player_id=7, conn=conn, now=event["starts_at"] + 3 * 3600
        )
        assert one <= int(event["max_hp"] * RAID_SINGLE_ACTION_CAP_FRACTION)
        assert five <= int(event["max_hp"] * RAID_MULTI_ACTION_CAP_FRACTION)
        assert meta1["action_cap_fraction"] == RAID_SINGLE_ACTION_CAP_FRACTION
        assert meta5["action_cap_fraction"] == RAID_MULTI_ACTION_CAP_FRACTION
    finally:
        conn.close()


def test_x5_scaler_is_never_above_12_5_percent():
    class Rng:
        def random(self):
            return 1.0

    hp = 1_000_000
    out = scale_instant_hit_damage(500_000, hit_mult=5, max_hp=hp, rng=Rng())
    assert out <= int(hp * RAID_MULTI_ACTION_CAP_FRACTION)


def test_resonance_activates_and_target_lock_charges():
    conn = _conn()
    try:
        event = _event()
        conn.execute(
            "UPDATE world_boss_events SET resonance_points = ? WHERE id = 1",
            (RAID_RESONANCE_THRESHOLD - 1,),
        )
        state_before = get_world_boss_raid_state(event, 7, conn=conn, now=event["starts_at"] + 3 * 3600)
        state_after = _advance_world_boss_raid_after_hit(
            event=event,
            player_id=7,
            hit_mult=1,
            target_lock_before=0,
            target_lock_consumed=False,
            defeated=False,
            conn=conn,
            now=event["starts_at"] + 3 * 3600,
            state_before=state_before,
        )
        assert state_after["resonance"]["active"] is True
        assert state_after["resonance"]["initiator_player_id"] == 7
        assert state_after["target_lock"]["charge"] == 20
    finally:
        conn.close()


def test_last_stand_is_derived_from_event_lifetime():
    conn = _conn()
    try:
        event = _event()
        at = event["starts_at"] + (event["ends_at"] - event["starts_at"]) * 0.75 + 1
        state = get_world_boss_raid_state(event, 7, conn=conn, now=at)
        assert state["last_stand"]["active"] is True
        assert state["containment"]["active"] is False
    finally:
        conn.close()
''', encoding="utf-8")


def main() -> None:
    patch_world_boss()
    patch_template()
    write_tests()
    print("GC-WB-RAID-002 codemod applied")


if __name__ == "__main__":
    main()
