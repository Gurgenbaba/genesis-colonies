from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


path = Path("game/inactive_autoplay.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "import json\nimport logging\n",
    "import hashlib\nimport json\nimport logging\n",
    "hashlib import",
)

text = replace_once(
    text,
    "INACTIVE_CHAIN_LIMIT = 1\n\n# Soft floor so empty dormant empires can enqueue (far below pirate seed).\n",
    '''INACTIVE_CHAIN_LIMIT = 1

# GC-2621 — Living Universe V3. One dormant commander decision starts at most
# one progression domain. Per-player cadence breaks ranking lockstep without
# increasing the global SQLite writer budget.
INACTIVE_ACTION_DOMAINS = ("building", "research", "defense")
INACTIVE_ACTION_WEIGHTS = {
    "economy": {"building": 65, "research": 25, "defense": 10},
    "aggressive": {"building": 40, "research": 25, "defense": 35},
    "turtle": {"building": 45, "research": 15, "defense": 40},
    "spy": {"building": 35, "research": 50, "defense": 15},
    "swarm": {"building": 45, "research": 25, "defense": 30},
    "elite": {"building": 45, "research": 35, "defense": 20},
}
INACTIVE_ACTION_PACE_RANGES_SEC = {
    "aggressive": (5 * 60, 14 * 60),
    "swarm": (6 * 60, 16 * 60),
    "elite": (8 * 60, 20 * 60),
    "economy": (10 * 60, 24 * 60),
    "spy": (12 * 60, 28 * 60),
    "turtle": (15 * 60, 35 * 60),
}
INACTIVE_WORLD_BOSS_SAFE_HP_RATIO = 0.05

# Soft floor so empty dormant empires can enqueue (far below pirate seed).
''',
    "GC-2621 constants",
)

online_anchor = '''def online_visible_cap(*, conn=None, now: Optional[float] = None) -> int:
    """GC-INACTIVE-SHIFT-001: shift size (== visible online)."""
    return shift_cap(now=now, conn=conn)


'''
helpers = online_anchor + '''def _stable_roll(player_id: int, namespace: str, sequence: int, modulo: int) -> int:
    """Process-stable deterministic roll; Python's salted hash() is forbidden here."""
    cap = max(1, int(modulo))
    raw = f"inactive:{namespace}:{int(player_id)}:{int(sequence)}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return int(digest[:16], 16) % cap


def _action_domain_for_player(player_id: int, personality: str, action_seq: int) -> str:
    weights = INACTIVE_ACTION_WEIGHTS.get(str(personality)) or INACTIVE_ACTION_WEIGHTS["economy"]
    total = sum(max(0, int(weights.get(key) or 0)) for key in INACTIVE_ACTION_DOMAINS)
    if total <= 0:
        return "building"
    roll = _stable_roll(player_id, "domain", action_seq, total)
    cursor = 0
    for domain in INACTIVE_ACTION_DOMAINS:
        cursor += max(0, int(weights.get(domain) or 0))
        if roll < cursor:
            return domain
    return "building"


def _next_action_delay_sec(player_id: int, personality: str, action_seq: int) -> int:
    low, high = INACTIVE_ACTION_PACE_RANGES_SEC.get(
        str(personality), INACTIVE_ACTION_PACE_RANGES_SEC["economy"]
    )
    low_i, high_i = max(60, int(low)), max(int(low), int(high))
    return low_i + _stable_roll(player_id, "pace", action_seq, high_i - low_i + 1)


'''
text = replace_once(text, online_anchor, helpers, "GC-2621 helpers")

# Keep cadence data when runtime-state roster JSON is normalized/pruned.
old_roster_field = '                "defense_done": int(item.get("defense_done") or 0),\n'
new_roster_field = old_roster_field + '                "action_seq": int(item.get("action_seq") or 0),\n                "next_action_at": item.get("next_action_at"),\n'
if text.count(old_roster_field) < 2:
    raise SystemExit("expected roster normalization fields")
text = text.replace(old_roster_field, new_roster_field)

# Add minimal World Boss participation helpers before the economy runner.
run_marker = "def _run_player_economy(\n"
run_pos = text.index(run_marker)
wb_helpers = '''def _weakest_combat_ship_for_player(conn, player_id: int) -> Optional[Dict[str, Any]]:
    """Find one weakest combat-capable ship across the commander's empire."""
    from .combat_models import combat_stats_for_ship

    rows = conn.execute(
        """
        SELECT ps.planet_id, ps.ship_key, ps.amount
        FROM planet_ships ps
        JOIN planets p ON p.id = ps.planet_id
        WHERE p.player_id = ? AND COALESCE(ps.amount, 0) > 0;
        """,
        (int(player_id),),
    ).fetchall()
    best: Optional[Tuple[int, str, int]] = None
    for row in rows:
        stats = combat_stats_for_ship(str(row["ship_key"]))
        if stats is None or int(stats.attack or 0) <= 0:
            continue
        candidate = (int(stats.attack or 0), str(row["ship_key"]), int(row["planet_id"]))
        if best is None or candidate < best:
            best = candidate
    if best is None:
        return None
    return {"planet_id": best[2], "ships": {best[1]: 1}}


def _maybe_join_world_boss(conn, player_id: int, *, now: float) -> Dict[str, Any]:
    """One tiny canonical instant strike per boss, never during the final 5% HP."""
    try:
        from .world_boss import can_player_attack_boss, execute_instant_attack, list_active_events

        token_force = _weakest_combat_ship_for_player(conn, int(player_id))
        if not token_force:
            return {"ok": True, "joined": False, "reason": "no_combat_ships"}
        for event in list_active_events(conn=conn, now=float(now), limit=3):
            max_hp = max(1, int(event.get("max_hp") or 1))
            hp_ratio = float(event.get("current_hp") or 0) / float(max_hp)
            if hp_ratio <= INACTIVE_WORLD_BOSS_SAFE_HP_RATIO:
                continue
            ok, _reason, meta = can_player_attack_boss(
                int(player_id),
                int(event["id"]),
                conn=conn,
                now=float(now),
                enforce_cooldown=False,
                check_inflight=False,
            )
            if not ok or int((meta or {}).get("waves") or 0) > 0:
                continue
            strike = execute_instant_attack(
                int(player_id),
                int(event["id"]),
                token_force["ships"],
                planet_id=int(token_force["planet_id"]),
                conn=conn,
                now=float(now),
                auto_select=False,
                hit_mult=1,
            )
            if strike.get("ok"):
                return {
                    "ok": True,
                    "joined": True,
                    "event_id": int(event["id"]),
                    "damage": int(strike.get("damage") or 0),
                    "ships": dict(token_force["ships"]),
                }
        return {"ok": True, "joined": False, "reason": "no_eligible_boss"}
    except Exception:
        logger.exception("inactive autoplay world boss participation failed player=%s", player_id)
        return {"ok": False, "joined": False, "reason": "world_boss_error"}


'''
text = text[:run_pos] + wb_helpers + text[run_pos:]

# Give the existing runner personal cadence state.
old_sig = '''def _run_player_economy(
    conn,
    player_id: int,
    *,
    now: float,
    is_wake: bool = False,
) -> Dict[str, Any]:
'''
new_sig = '''def _run_player_economy(
    conn,
    player_id: int,
    *,
    now: float,
    is_wake: bool = False,
    action_seq: int = 0,
    next_action_at: Optional[float] = None,
) -> Dict[str, Any]:
'''
text = replace_once(text, old_sig, new_sig, "runner signature")

old_setup = '''    personality = personality_for_player(player_id)
    idle_chance = 0.0 if is_wake else AUTOPLAY_STANDING_IDLE_CHANCE
    results: List[Dict[str, Any]] = []
'''
new_setup = '''    personality = personality_for_player(player_id)
    seq = max(0, int(action_seq or 0))
    personal_cooldown = bool(
        not is_wake
        and next_action_at is not None
        and float(now) < float(next_action_at)
    )
    action_domain = None if personal_cooldown else _action_domain_for_player(
        player_id, personality, seq
    )
    idle_chance = 1.0 if personal_cooldown else (
        0.0 if is_wake else AUTOPLAY_STANDING_IDLE_CHANCE
    )
    results: List[Dict[str, Any]] = []
'''
text = replace_once(text, old_setup, new_setup, "runner cadence setup")

text = replace_once(text, "                    allow_buildings=True,\n                    allow_research=True,\n                    allow_ships=False,\n                    allow_defense=True,\n", "                    allow_buildings=action_domain == \"building\",\n                    allow_research=action_domain == \"research\",\n                    allow_ships=False,\n                    allow_defense=action_domain == \"defense\",\n", "serialized domains")

old_before_return = '''    return {
        "ok": True,
        "player_id": player_id,
        "economy": results,
'''
new_before_return = '''    boss_participation = _maybe_join_world_boss(conn, player_id, now=now)
    next_seq = seq if personal_cooldown else seq + 1
    next_at = float(next_action_at) if personal_cooldown and next_action_at is not None else None
    next_delay = None
    if not personal_cooldown:
        next_delay = _next_action_delay_sec(player_id, personality, seq)
        next_at = float(now) + float(next_delay)
    return {
        "ok": True,
        "player_id": player_id,
        "economy": results,
'''
text = replace_once(text, old_before_return, new_before_return, "runner return prelude")

old_return_tail = '''        "last_action": _describe_last_action(results),
        "resource_floor": floor,
    }
'''
new_return_tail = '''        "last_action": _describe_last_action(results),
        "resource_floor": floor,
        "action_domain": action_domain,
        "action_seq": next_seq,
        "next_action_delay_sec": next_delay,
        "next_action_at": next_at,
        "personal_cooldown": personal_cooldown,
        "boss_participation": boss_participation,
    }
'''
text = replace_once(text, old_return_tail, new_return_tail, "runner return cadence")

# Persist cadence after every roster economy slice.
old_apply = '''    action = result.get("last_action")
    if action:
        item["last_action"] = action
'''
new_apply = '''    if result.get("action_seq") is not None:
        item["action_seq"] = max(0, int(result.get("action_seq") or 0))
    if result.get("next_action_at") is not None:
        item["next_action_at"] = float(result["next_action_at"])
    action = result.get("last_action")
    if action:
        item["last_action"] = action
'''
text = replace_once(text, old_apply, new_apply, "persist cadence")

old_standing = '                    res = _run_player_economy(conn, player_id, now=ts)\n'
new_standing = '''                    res = _run_player_economy(
                        conn,
                        player_id,
                        now=ts,
                        action_seq=int(roster_item.get("action_seq") or 0),
                        next_action_at=roster_item.get("next_action_at"),
                    )
'''
text = replace_once(text, old_standing, new_standing, "standing cadence args")

path.write_text(text, encoding="utf-8")

# Owner-doc reality sync.
doc_path = Path("docs/INACTIVE_AUTOPLAY.md")
doc = doc_path.read_text(encoding="utf-8")
doc = doc.replace(
    '| Economy | `plan_passive_planet_tick` mit Soft-Caps (15/20 min) + Chain **1** (kein same-tick Force-Complete); Standing-RR nur alle **`economy_interval`** (Default 300s), entkoppelt vom Fleet-Due-Pfad |',
    '| Economy | `plan_passive_planet_tick` mit Soft-Caps (15/20 min) + Chain **1**; GC-2621 startet pro Commander-Entscheidung nur **eine** Progression-Domäne und nutzt eine stabile 5–35-Minuten-Pace je Personality. Standing-RR bleibt global budgetiert. |',
)
doc = doc.replace(
    '| Ships | **nein** (Inactive) / ja (Pirate-AI, siehe unten) |',
    '| Ships | **nein** (Inactive) / ja (Pirate-AI, siehe unten) |\n| World Boss | GC-2621: Inaktive mit vorhandenen Kampfschiffen setzen pro aktivem Boss genau **einen** Token-Schlag mit dem schwächsten verfügbaren Kampfschiff. Instant-Attack verursacht keine Schiffsverluste; unter 5% Boss-HP wird nicht mehr automatisch angegriffen. |',
)
if "| GC-2621 |" not in doc:
    doc += "\n\n## GC-2621 — Living Universe V3\n\n- Pro Commander-Entscheidung genau eine Progression-Domäne.\n- Deterministische 5–35-Minuten-Pace je Personality.\n- Ein minimaler World-Boss-Token-Schlag pro Event bei vorhandenem Kampfschiff; kein Auto-Finisher unter 5% HP.\n"
doc_path.write_text(doc, encoding="utf-8")
