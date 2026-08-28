from __future__ import annotations

import json
from pathlib import Path


def must_replace(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, count)


ast = Path("game/asteroids.py")
text = ast.read_text(encoding="utf-8")
text = must_replace(
    text,
    "MEGA_BELT_STORAGE_FRACTION = 0.02\nMEGA_BELT_MIN_POOL_PER_RESOURCE = 5_000_000\n",
    "MEGA_BELT_STORAGE_FRACTION = 0.02\nMEGA_BELT_MIN_POOL_PER_RESOURCE = 5_000_000\n"
    "# Each player may harvest at most 10% of the original mega-belt pool.\n"
    "# The cap is per resource so ten fully equipped players can cleanly split a belt,\n"
    "# while smaller fleets may make repeated trips until their own share is exhausted.\n"
    "MEGA_BELT_PLAYER_SHARE = 0.10\n",
    "mega constants",
)
text = must_replace(
    text,
    '''    engaged = bool(aid and (aid in engaged_ids or fleet.get("engaged")))
    status = str(fleet.get("fleet_status") or "")
    arrival = fleet.get("arrival_at")
    try:
        arrival_f = float(arrival) if arrival is not None else None
    except (TypeError, ValueError):
        arrival_f = None
    ts = float(now if now is not None else _now())
    # Consistent "Unterwegs": any outbound hunt, including ETA still in the future.
    en_route = bool(status == "outbound")
    if not en_route and engaged and arrival_f is not None and arrival_f > ts:
        en_route = True
    out["viewer_engaged"] = engaged
    out["viewer_fleet_status"] = status if engaged else ""
    out["viewer_arrival_at"] = arrival_f
    out["viewer_en_route"] = en_route
    out["viewer_harvest_locked"] = en_route
    return out
''',
    '''    status = str(fleet.get("fleet_status") or "").strip().lower()
    arrival = fleet.get("arrival_at")
    try:
        arrival_f = float(arrival) if arrival is not None else None
    except (TypeError, ValueError):
        arrival_f = None
    active_fleet = bool(fleet.get("engaged") and status in ("outbound", "returning"))
    en_route = bool(active_fleet and status == "outbound")
    returning = bool(active_fleet and status == "returning")
    # Durable engagement history must never masquerade as a live flight.
    out["viewer_has_engaged"] = bool(aid and (aid in engaged_ids or active_fleet))
    out["viewer_engaged"] = active_fleet
    out["viewer_fleet_status"] = status if active_fleet else ""
    out["viewer_arrival_at"] = arrival_f if active_fleet else None
    out["viewer_en_route"] = en_route
    out["viewer_returning"] = returning
    out["viewer_harvest_locked"] = active_fleet
    return out
''',
    "viewer lifecycle",
)
marker = "\n\ndef build_asteroid_board_entries(\n"
if marker not in text:
    raise SystemExit("missing board marker")
helper = r'''


def mega_belt_player_share_state(
    asteroid_id: int,
    player_id: int,
    *,
    conn,
    row: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the canonical per-player 10% Mega Belt entitlement.

    The original spawn pool is reconstructed as current remaining resources
    plus the append-only claim ledger, so repeated small-fleet trips remain
    exact without a second mutable source of truth.
    """
    zero = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    aid = int(asteroid_id or 0)
    pid = int(player_id or 0)
    empty = {
        "original_pool": dict(zero),
        "player_claimed": dict(zero),
        "player_quota": dict(zero),
        "player_remaining": dict(zero),
        "player_remaining_total": 0,
        "share_percent": 0.0,
        "quota_exhausted": False,
    }
    if aid <= 0 or pid <= 0 or not table_exists(conn, "asteroid_field_claims"):
        return empty
    source = row
    if source is None:
        source = conn.execute(
            "SELECT * FROM asteroid_fields WHERE id = ? LIMIT 1;", (aid,)
        ).fetchone()
    if not source:
        return empty
    try:
        tier = str(source["tier"] or TIER_STANDARD)
    except (KeyError, IndexError, TypeError):
        tier = TIER_STANDARD
    if tier != TIER_MEGA:
        return empty

    all_claims = conn.execute(
        """
        SELECT COALESCE(SUM(metal), 0) AS metal,
               COALESCE(SUM(crystal), 0) AS crystal,
               COALESCE(SUM(fuel_cells), 0) AS fuel_cells
        FROM asteroid_field_claims WHERE asteroid_id = ?;
        """,
        (aid,),
    ).fetchone()
    own_claims = conn.execute(
        """
        SELECT COALESCE(SUM(metal), 0) AS metal,
               COALESCE(SUM(crystal), 0) AS crystal,
               COALESCE(SUM(fuel_cells), 0) AS fuel_cells
        FROM asteroid_field_claims WHERE asteroid_id = ? AND player_id = ?;
        """,
        (aid, pid),
    ).fetchone()
    current = {
        "metal": max(0, int(source["metal"] or 0)),
        "crystal": max(0, int(source["crystal"] or 0)),
        "fuel_cells": max(0, int(source["fuel_cells"] or 0)),
    }
    claimed_all = {key: max(0, int(all_claims[key] or 0)) for key in zero}
    claimed_own = {key: max(0, int(own_claims[key] or 0)) for key in zero}
    original = {key: current[key] + claimed_all[key] for key in zero}
    quota = {
        key: max(1, int(math.floor(original[key] * MEGA_BELT_PLAYER_SHARE)))
        if original[key] > 0
        else 0
        for key in zero
    }
    remaining = {key: max(0, quota[key] - claimed_own[key]) for key in zero}
    original_total = sum(original.values())
    claimed_total = sum(claimed_own.values())
    remaining_total = sum(remaining.values())
    share_percent = (
        min(MEGA_BELT_PLAYER_SHARE * 100.0, (claimed_total / original_total) * 100.0)
        if original_total > 0
        else 0.0
    )
    return {
        "original_pool": original,
        "player_claimed": claimed_own,
        "player_quota": quota,
        "player_remaining": remaining,
        "player_remaining_total": remaining_total,
        "share_percent": share_percent,
        "quota_exhausted": remaining_total <= 0,
    }


def enrich_mega_belt_player_state(
    asteroid: Mapping[str, Any],
    *,
    player_id: Optional[int],
    conn,
) -> Dict[str, Any]:
    out = dict(asteroid)
    if str(out.get("tier") or TIER_STANDARD) != TIER_MEGA or not player_id:
        return out
    state = mega_belt_player_share_state(
        int(out.get("id") or 0), int(player_id), conn=conn, row=out
    )
    remaining = dict(state.get("player_remaining") or {})
    out["viewer_mega_share_percent"] = float(state.get("share_percent") or 0.0)
    out["viewer_mega_quota_exhausted"] = bool(state.get("quota_exhausted"))
    out["viewer_mega_quota_remaining"] = int(state.get("player_remaining_total") or 0)
    out["viewer_harvest_locked"] = bool(
        out.get("viewer_harvest_locked") or state.get("quota_exhausted")
    )
    out["recycler_slots_needed"] = estimate_reclaimer_slots_needed(
        int(remaining.get("metal") or 0),
        int(remaining.get("crystal") or 0),
        int(remaining.get("fuel_cells") or 0),
    )
    return out
'''
text = text.replace(marker, helper + marker, 1)
text = must_replace(
    text,
    '''        enriched = enrich_asteroid_viewer_state(
            row, engaged_ids=engaged_ids, fleet_map=fleet_map, now=ts
        )
        # Keep engaged hunts visible with en-route state (no silent vanish).
''',
    '''        enriched = enrich_asteroid_viewer_state(
            row, engaged_ids=engaged_ids, fleet_map=fleet_map, now=ts
        )
        if viewer_player_id is not None and int(viewer_player_id) > 0:
            enriched = enrich_mega_belt_player_state(
                enriched, player_id=int(viewer_player_id), conn=conn
            )
        # Keep active hunts visible with their exact flight phase.
''',
    "board enrich",
)
text = must_replace(
    text,
    '"SELECT COUNT(*) AS n FROM asteroid_field_claims WHERE asteroid_id = ?;",',
    '"SELECT COUNT(DISTINCT player_id) AS n FROM asteroid_field_claims WHERE asteroid_id = ?;",',
    "distinct claimers",
)
text = must_replace(
    text,
    '''                "viewer_arrival_at": enriched.get("viewer_arrival_at"),
                "viewer_en_route": bool(enriched.get("viewer_en_route")),
                "viewer_harvest_locked": bool(enriched.get("viewer_harvest_locked")),
''',
    '''                "viewer_arrival_at": enriched.get("viewer_arrival_at"),
                "viewer_en_route": bool(enriched.get("viewer_en_route")),
                "viewer_returning": bool(enriched.get("viewer_returning")),
                "viewer_mega_share_percent": float(enriched.get("viewer_mega_share_percent") or 0.0),
                "viewer_mega_quota_exhausted": bool(enriched.get("viewer_mega_quota_exhausted")),
                "viewer_mega_quota_remaining": int(enriched.get("viewer_mega_quota_remaining") or 0),
                "viewer_harvest_locked": bool(enriched.get("viewer_harvest_locked")),
''',
    "board payload",
)
text = must_replace(
    text,
    '            0 if e.get("viewer_en_route") else 1 if e.get("viewer_engaged") else 2,\n',
    '            0 if e.get("viewer_en_route") else 1 if e.get("viewer_returning") else 2,\n',
    "board sort",
)
text = must_replace(
    text,
    '''        payload = enrich_asteroid_viewer_state(
            _row_to_asteroid(row),
            engaged_ids=engaged_ids,
            fleet_map=fleet_map,
            now=ts,
        )
        out[int(payload["position"])] = payload
''',
    '''        payload = enrich_asteroid_viewer_state(
            _row_to_asteroid(row),
            engaged_ids=engaged_ids,
            fleet_map=fleet_map,
            now=ts,
        )
        if viewer_player_id is not None and int(viewer_player_id) > 0:
            payload = enrich_mega_belt_player_state(
                payload, player_id=int(viewer_player_id), conn=conn
            )
        out[int(payload["position"])] = payload
''',
    "system payload",
)
text = must_replace(
    text,
    '''    harvested = _split_load(pool, int(cargo_capacity))

    if tier == TIER_MEGA:
        return _claim_mega_harvest(
            conn,
            row=row,
            aid=aid,
            pool=pool,
            harvested=harvested,
            player_id=int(player_id),
            ts=ts,
        )

    cur = conn.execute(
''',
    '''    if tier == TIER_MEGA:
        share = mega_belt_player_share_state(aid, int(player_id), conn=conn, row=row)
        if share.get("quota_exhausted"):
            return {
                "status": "quota_exhausted",
                "harvested": {"metal": 0, "crystal": 0, "fuel_cells": 0},
                "asteroid_id": aid,
                "asteroid_key": str(row["asteroid_key"] or ""),
                "player_share": share,
            }
        allowance = dict(share.get("player_remaining") or {})
        eligible_pool = {
            key: min(int(pool[key]), max(0, int(allowance.get(key) or 0)))
            for key in ("metal", "crystal", "fuel_cells")
        }
        harvested = _split_load(eligible_pool, int(cargo_capacity))
        if sum(int(v or 0) for v in harvested.values()) <= 0:
            return {
                "status": "quota_exhausted",
                "harvested": {"metal": 0, "crystal": 0, "fuel_cells": 0},
                "asteroid_id": aid,
                "asteroid_key": str(row["asteroid_key"] or ""),
                "player_share": share,
            }
        return _claim_mega_harvest(
            conn,
            row=row,
            aid=aid,
            pool=pool,
            harvested=harvested,
            player_id=int(player_id),
            ts=ts,
        )

    harvested = _split_load(pool, int(cargo_capacity))
    cur = conn.execute(
''',
    "mega claim cap",
)
text = must_replace(
    text,
    '''    return {
        "status": "claimed",
        "harvested": harvested,
        "asteroid_id": aid,
        "asteroid_key": asteroid.get("asteroid_key"),
        "pool": pool,
        "remaining_pool": remaining,
        "asteroid": asteroid,
    }
''',
    '''    player_share = mega_belt_player_share_state(aid, int(player_id), conn=conn)
    return {
        "status": "claimed",
        "harvested": harvested,
        "asteroid_id": aid,
        "asteroid_key": asteroid.get("asteroid_key"),
        "pool": pool,
        "remaining_pool": remaining,
        "player_share": player_share,
        "asteroid": asteroid,
    }
''',
    "mega claim return",
)
ast.write_text(text, encoding="utf-8")

fleet = Path("game/fleet.py")
text = fleet.read_text(encoding="utf-8")
text = must_replace(
    text,
    '''    missed: bool = False,
    expired: bool = False,
    locale: str | None = None,
''',
    '''    missed: bool = False,
    expired: bool = False,
    quota_exhausted: bool = False,
    locale: str | None = None,
''',
    "report signature",
)
text = must_replace(
    text,
    '''    if expired:
        return tr(
''',
    '''    if quota_exhausted:
        return tr(
            "fleet_asteroid_report_quota_exhausted",
            "Your 10% share of the Mega Belt at %(coords)s is exhausted. Fleet returning empty to %(origin)s.",
            locale=locale,
            coords=coords,
            origin=origin_name,
        )
    if expired:
        return tr(
''',
    "quota report",
)
text = must_replace(
    text,
    '''        asteroid_missed = False
        asteroid_harvested = False
        asteroid_expired = False
''',
    '''        asteroid_missed = False
        asteroid_harvested = False
        asteroid_expired = False
        asteroid_quota_exhausted = False
''',
    "fleet flags",
)
text = must_replace(
    text,
    '''                if status == "missed":
                    asteroid_missed = True
                else:
                    asteroid_expired = True
''',
    '''                if status == "missed":
                    asteroid_missed = True
                elif status == "quota_exhausted":
                    asteroid_quota_exhausted = True
                else:
                    asteroid_expired = True
''',
    "claim status",
)
text = text.replace(
    "if not (asteroid_harvested or asteroid_missed or asteroid_expired):",
    "if not (asteroid_harvested or asteroid_missed or asteroid_expired or asteroid_quota_exhausted):",
    1,
)
text = text.replace(
    "if asteroid_harvested or asteroid_missed or asteroid_expired:",
    "if asteroid_harvested or asteroid_missed or asteroid_expired or asteroid_quota_exhausted:",
)
text = must_replace(
    text,
    '''                missed=asteroid_missed,
                expired=asteroid_expired,
                locale=sender_locale,
''',
    '''                missed=asteroid_missed,
                expired=asteroid_expired,
                quota_exhausted=asteroid_quota_exhausted,
                locale=sender_locale,
''',
    "report call",
)
text = must_replace(
    text,
    '''            "asteroid_expired": asteroid_expired,
            **({"asteroid": asteroid_meta} if asteroid_meta else {}),
''',
    '''            "asteroid_expired": asteroid_expired,
            "asteroid_quota_exhausted": asteroid_quota_exhausted,
            **({"asteroid": asteroid_meta} if asteroid_meta else {}),
''',
    "report metadata",
)
fleet.write_text(text, encoding="utf-8")

board = Path("templates/partials/galaxy_asteroid_board.html")
text = board.read_text(encoding="utf-8")
text = must_replace(
    text,
    "{% set harvest_locked = entry.viewer_harvest_locked if entry.viewer_harvest_locked is defined else false %}\n",
    "{% set harvest_locked = entry.viewer_harvest_locked if entry.viewer_harvest_locked is defined else false %}\n"
    "{% set returning = entry.viewer_returning if entry.viewer_returning is defined else false %}\n"
    "{% set mega_limit = entry.viewer_mega_quota_exhausted if entry.viewer_mega_quota_exhausted is defined else false %}\n",
    "board vars",
)
text = must_replace(
    text,
    '<li class="galaxy-asteroid-board-row{% if entry.is_current_system %} is-current-system{% endif %}{% if entry.viewer_en_route or entry.viewer_engaged %} is-en-route{% endif %}">',
    '<li class="galaxy-asteroid-board-row{% if entry.is_current_system %} is-current-system{% endif %}{% if entry.viewer_en_route or returning %} is-en-route{% endif %}">',
    "board row class",
)
text = must_replace(
    text,
    '''          {% elif entry.viewer_engaged %}
          {# Same visual language as en-route (no weaker "Angeflogen" chip). #}
          <span class="galaxy-asteroid-board-badge galaxy-asteroid-board-badge--en-route">
            {{ T('galaxy_asteroid_en_route', 'Unterwegs') }}
          </span>
          {% endif %}
''',
    '''          {% elif returning %}
          <span class="galaxy-asteroid-board-badge galaxy-asteroid-board-badge--en-route">
            {{ T('fleet_status_returning', 'Rückflug') }}
            {% if entry.viewer_arrival_at %}
            <span class="gc-mono"
                  data-countdown-at="{{ entry.viewer_arrival_at|int }}"
                  data-countdown-format="eta"
                  data-refresh-on-zero="galaxy">—</span>
            {% endif %}
          </span>
          {% endif %}
          {% if entry.tier == 'mega' %}
          <span class="galaxy-asteroid-board-badge galaxy-asteroid-board-badge--mega"
                {% if mega_limit %}title="{{ T('galaxy_asteroid_mega_limit_reached', 'Dein 10%-Anteil an diesem Mega-Belt ist ausgeschöpft.') }}"{% endif %}>
            {{ '%.1f'|format(entry.viewer_mega_share_percent or 0) }} / 10%{% if mega_limit %} ✓{% endif %}
          </span>
          {% endif %}
''',
    "board status badges",
)
text = must_replace(
    text,
    '''                    title="{% if harvest_locked %}{{ T('galaxy_asteroid_en_route_title', 'Harvest-Flotte unterwegs') }}{% else %}{{ T('galaxy_asteroid_harvest_click', 'Harvest Reclaimer zum Asteroiden senden') }}{% endif %}">
''',
    '''                    title="{% if mega_limit %}{{ T('galaxy_asteroid_mega_limit_reached', 'Dein 10%-Anteil an diesem Mega-Belt ist ausgeschöpft.') }}{% elif returning %}{{ T('fleet_status_returning', 'Rückflug') }}{% elif harvest_locked %}{{ T('galaxy_asteroid_en_route_title', 'Harvest-Flotte unterwegs') }}{% else %}{{ T('galaxy_asteroid_harvest_click', 'Harvest Reclaimer zum Asteroiden senden') }}{% endif %}">
''',
    "board button title",
)
board.write_text(text, encoding="utf-8")

block = Path("templates/partials/galaxy_asteroid_block.html")
text = block.read_text(encoding="utf-8")
text = must_replace(
    text,
    "{% set en_route = asteroid.viewer_en_route if asteroid.viewer_en_route is defined else false %}\n{% set harvest_locked = asteroid.viewer_harvest_locked if asteroid.viewer_harvest_locked is defined else false %}\n",
    "{% set en_route = asteroid.viewer_en_route if asteroid.viewer_en_route is defined else false %}\n"
    "{% set returning = asteroid.viewer_returning if asteroid.viewer_returning is defined else false %}\n"
    "{% set mega_limit = asteroid.viewer_mega_quota_exhausted if asteroid.viewer_mega_quota_exhausted is defined else false %}\n"
    "{% set harvest_locked = asteroid.viewer_harvest_locked if asteroid.viewer_harvest_locked is defined else false %}\n",
    "block vars",
)
text = must_replace(
    text,
    '<div class="galaxy-slot-asteroid galaxy-asteroid-block{% if en_route %} is-en-route{% endif %}{% if asteroid.tier == \'mega\' %} is-mega-belt{% endif %}"',
    '<div class="galaxy-slot-asteroid galaxy-asteroid-block{% if en_route or returning %} is-en-route{% endif %}{% if asteroid.tier == \'mega\' %} is-mega-belt{% endif %}"',
    "block class",
)
text = must_replace(
    text,
    '''    {% if en_route %}
    <span class="galaxy-asteroid-board-badge galaxy-asteroid-board-badge--en-route">
      {{ T('galaxy_asteroid_en_route', 'Unterwegs') }}
      {% if asteroid.viewer_arrival_at %}
      <span class="gc-mono"
            data-countdown-at="{{ asteroid.viewer_arrival_at|int }}"
            data-countdown-format="eta"
            data-refresh-on-zero="galaxy">—</span>
      {% endif %}
    </span>
    {% endif %}
''',
    '''    {% if en_route %}
    <span class="galaxy-asteroid-board-badge galaxy-asteroid-board-badge--en-route">
      {{ T('galaxy_asteroid_en_route', 'Unterwegs') }}
      {% if asteroid.viewer_arrival_at %}
      <span class="gc-mono"
            data-countdown-at="{{ asteroid.viewer_arrival_at|int }}"
            data-countdown-format="eta"
            data-refresh-on-zero="galaxy">—</span>
      {% endif %}
    </span>
    {% elif returning %}
    <span class="galaxy-asteroid-board-badge galaxy-asteroid-board-badge--en-route">
      {{ T('fleet_status_returning', 'Rückflug') }}
      {% if asteroid.viewer_arrival_at %}
      <span class="gc-mono"
            data-countdown-at="{{ asteroid.viewer_arrival_at|int }}"
            data-countdown-format="eta"
            data-refresh-on-zero="galaxy">—</span>
      {% endif %}
    </span>
    {% endif %}
    {% if asteroid.tier == 'mega' %}
    <span class="galaxy-asteroid-board-badge galaxy-asteroid-board-badge--mega"
          {% if mega_limit %}title="{{ T('galaxy_asteroid_mega_limit_reached', 'Dein 10%-Anteil an diesem Mega-Belt ist ausgeschöpft.') }}"{% endif %}>
      {{ '%.1f'|format(asteroid.viewer_mega_share_percent or 0) }} / 10%{% if mega_limit %} ✓{% endif %}
    </span>
    {% endif %}
''',
    "block badges",
)
text = must_replace(
    text,
    "    {% if en_route %}{{ T('galaxy_asteroid_en_route', 'Unterwegs') }}{% else %}{{ T('galaxy_asteroid_harvest', 'Abbauen') }}{% endif %}\n",
    "    {% if returning %}{{ T('fleet_status_returning', 'Rückflug') }}{% elif en_route %}{{ T('galaxy_asteroid_en_route', 'Unterwegs') }}{% else %}{{ T('galaxy_asteroid_harvest', 'Abbauen') }}{% endif %}\n",
    "block button",
)
block.write_text(text, encoding="utf-8")

translations = {
    "de": ("Dein 10%-Anteil an diesem Mega-Belt ist ausgeschöpft.", "Dein 10%-Anteil am Mega-Belt bei %(coords)s ist ausgeschöpft. Die Flotte kehrt leer nach %(origin)s zurück."),
    "en": ("Your 10% share of this Mega Belt is exhausted.", "Your 10% share of the Mega Belt at %(coords)s is exhausted. Fleet returning empty to %(origin)s."),
    "fr": ("Votre part de 10 % de cette ceinture méga est épuisée.", "Votre part de 10 % de la ceinture méga en %(coords)s est épuisée. La flotte revient à vide vers %(origin)s."),
    "es": ("Tu cuota del 10 % de este megacinturón está agotada.", "Tu cuota del 10 % del megacinturón en %(coords)s está agotada. La flota regresa vacía a %(origin)s."),
    "pl": ("Twój 10% udział w tym Mega Pasie został wyczerpany.", "Twój 10% udział w Mega Pasie na %(coords)s został wyczerpany. Flota wraca pusta do %(origin)s."),
    "tr": ("Bu Mega Kuşak'taki %10 payın tükendi.", "%(coords)s konumundaki Mega Kuşak'taki %10 payın tükendi. Filo %(origin)s konumuna boş dönüyor."),
    "ru": ("Ваша доля 10% в этом мегапоясе исчерпана.", "Ваша доля 10% в мегапоясе %(coords)s исчерпана. Флот возвращается в %(origin)s без добычи."),
    "pt": ("A tua quota de 10% deste Mega Belt foi esgotada.", "A tua quota de 10% do Mega Belt em %(coords)s foi esgotada. A frota regressa vazia a %(origin)s."),
}
for code, (limit_text, report_text) in translations.items():
    path = Path("locales") / f"{code}.json"
    raw = path.read_text(encoding="utf-8").rstrip()
    if '"galaxy_asteroid_mega_limit_reached"' in raw:
        continue
    if not raw.endswith("}"):
        raise SystemExit(f"bad locale ending: {path}")
    body = raw[:-1].rstrip()
    if not body.endswith(","):
        body += ","
    body += (
        '\n  "galaxy_asteroid_mega_limit_reached": '
        + json.dumps(limit_text, ensure_ascii=False)
        + ',\n  "fleet_asteroid_report_quota_exhausted": '
        + json.dumps(report_text, ensure_ascii=False)
        + "\n}\n"
    )
    path.write_text(body, encoding="utf-8")

tests = Path("tests/test_asteroids.py")
text = tests.read_text(encoding="utf-8")
if "test_mega_belt_player_share_is_capped_at_ten_percent" not in text:
    text += r'''


def test_mega_belt_player_share_is_capped_at_ten_percent(ast_db):
    from game.asteroids import MEGA_BELT_PLAYER_SHARE, TIER_MEGA, mega_belt_player_share_state

    uid = _player("MegaShare")
    uid_other = _player("MegaOther")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(conn=conn, galaxy=g, system=s, position=pos, asteroid_key="mega_belt", tier=TIER_MEGA, rng=random.Random(123))
        assert ins["ok"]
        initial = {k: int(ins["asteroid"][k]) for k in ("metal", "crystal", "fuel_cells")}
        claim = try_claim_harvest(g, s, pos, player_id=uid, cargo_capacity=sum(initial.values()) * 2, conn=conn)
        assert claim["status"] == "claimed"
        expected = {k: int(initial[k] * MEGA_BELT_PLAYER_SHARE) for k in initial}
        assert {k: int(claim["harvested"][k]) for k in expected} == expected
        again = try_claim_harvest(g, s, pos, player_id=uid, cargo_capacity=sum(initial.values()) * 2, conn=conn)
        assert again["status"] == "quota_exhausted"
        assert sum(int(v or 0) for v in again["harvested"].values()) == 0
        other = try_claim_harvest(g, s, pos, player_id=uid_other, cargo_capacity=sum(initial.values()) * 2, conn=conn)
        assert other["status"] == "claimed"
        assert {k: int(other["harvested"][k]) for k in expected} == expected
        state = mega_belt_player_share_state(int(ins["asteroid"]["id"]), uid, conn=conn)
        assert state["quota_exhausted"] is True
        assert state["share_percent"] == pytest.approx(10.0, abs=0.01)
        assert get_active_asteroid_at(g, s, pos, conn=conn) is not None
        commit(conn)
    finally:
        conn.close()


def test_mega_belt_small_fleet_can_repeat_until_personal_share_is_full(ast_db):
    from game.asteroids import TIER_MEGA, mega_belt_player_share_state

    uid = _player("MegaSmall")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(conn=conn, galaxy=g, system=s, position=pos, asteroid_key="mega_belt", tier=TIER_MEGA, rng=random.Random(321))
        assert ins["ok"]
        aid = int(ins["asteroid"]["id"])
        quota_total = int(mega_belt_player_share_state(aid, uid, conn=conn)["player_remaining_total"])
        assert quota_total > 10
        tiny_capacity = max(1, quota_total // 4)
        harvested_total = 0
        claims = 0
        while True:
            result = try_claim_harvest(g, s, pos, player_id=uid, cargo_capacity=tiny_capacity, conn=conn)
            if result["status"] == "quota_exhausted":
                break
            assert result["status"] == "claimed"
            harvested_total += sum(int(v or 0) for v in result["harvested"].values())
            claims += 1
            assert claims < 10
        assert claims >= 2
        assert harvested_total == quota_total
        state = mega_belt_player_share_state(aid, uid, conn=conn)
        assert state["quota_exhausted"] is True
        assert state["player_remaining_total"] == 0
        commit(conn)
    finally:
        conn.close()


def test_asteroid_viewer_lifecycle_distinguishes_return_and_clears_stale_engagement():
    from game.asteroids import enrich_asteroid_viewer_state

    asteroid = {"id": 77, "tier": "mega"}
    future = time.time() + 120
    outbound = enrich_asteroid_viewer_state(asteroid, engaged_ids={77}, fleet_map={77: {"fleet_status": "outbound", "arrival_at": future, "engaged": True}})
    assert outbound["viewer_en_route"] is True
    assert outbound["viewer_returning"] is False
    assert outbound["viewer_harvest_locked"] is True
    returning = enrich_asteroid_viewer_state(asteroid, engaged_ids={77}, fleet_map={77: {"fleet_status": "returning", "arrival_at": future, "engaged": True}})
    assert returning["viewer_en_route"] is False
    assert returning["viewer_returning"] is True
    assert returning["viewer_harvest_locked"] is True
    completed = enrich_asteroid_viewer_state(asteroid, engaged_ids={77}, fleet_map={})
    assert completed["viewer_has_engaged"] is True
    assert completed["viewer_engaged"] is False
    assert completed["viewer_en_route"] is False
    assert completed["viewer_returning"] is False
    assert completed["viewer_harvest_locked"] is False
'''
    tests.write_text(text, encoding="utf-8")

docs = Path("docs/ASTEROID_SYSTEM.md")
dtext = docs.read_text(encoding="utf-8")
if "## Mega Belt Fair-Share" not in dtext:
    docs.write_text(
        dtext.rstrip()
        + "\n\n## Mega Belt Fair-Share\n\nMega Belts use a server-authoritative **10% maximum share per player** based on the original spawn pool, enforced per resource. Large Harvest Reclaimer fleets can collect the remaining personal share in one trip; smaller fleets may repeat trips until the same 10% cap is reached. Outbound and returning are distinct live fleet states; historical engagement never keeps a completed flight visually locked.\n",
        encoding="utf-8",
    )

print("mega belt share patch applied")
