"""VOIDFALL 2026 daily operations and account welcome claim.

Reads canonical activity_xp_log; grants canonical inventory items only.
All writes must run inside the caller's transaction after locking the user row.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from .db import table_exists
from .inventory import grant_inventory_item, inventory_schema_ready
from .inventory_catalog import item_catalog_entry

START_AT = 1793404800
END_AT = 1794095999
SLUG = "voidfall-rift-opening-2026"
CLAIM_PREFIX = "voidfall2026"
WELCOME_KEY = "welcome"

# Complete all three objectives with just two expeditions and one completed build.
# No planet count, premium requirement, timekeeper, or raw-resource injection.
MISSION_CATALOG = (
    ("expeditions", 2, ("expedition",), (("booster_expedition_loot_25_24h", 1),), "🚀"),
    ("construction", 1, ("building_finish",), (("booster_build_15m", 1),), "⚒"),
    ("operations", 3, ("expedition", "building_finish", "account_research_finish", "spy", "recycle"),
     (("container_event_special", 1),), "✦"),
)
WELCOME_ITEMS = (("container_rare", 1), ("booster_research_15m", 1))

COPY = {
    "de": {
        "subtitle": "Die Anomalie ist geöffnet. Schließe tägliche Aufträge ab und sichere Event-Beute. Reset: 00:00 UTC.",
        "welcome": "Willkommensversorgung", "welcome_hint": "Einmal pro Commander im Eventzeitraum – für neue und bestehende Konten.",
        "expeditions": "Riss-Erkundung", "construction": "Kolonie verstärken", "operations": "Einsatzbereitschaft",
        "claim": "Belohnung abholen", "claimed": "Abgeholt", "locked": "Noch nicht erfüllt",
        "ended": "Event derzeit nicht aktiv", "success": "Belohnung im Inventar!", "failed": "Abholung nicht möglich.",
        "remaining": "Fortschritt", "reward": "Belohnung", "until": "Endet am 7. November, 23:59 UTC",
    },
    "en": {
        "subtitle": "The rift is open. Complete daily objectives for event loot. Reset: 00:00 UTC.",
        "welcome": "Welcome supplies", "welcome_hint": "Once per Commander during the event – new and existing accounts.",
        "expeditions": "Rift exploration", "construction": "Fortify your colony", "operations": "Operational readiness",
        "claim": "Claim reward", "claimed": "Claimed", "locked": "Not yet completed",
        "ended": "Event currently inactive", "success": "Reward delivered to inventory!", "failed": "Claim unavailable.",
        "remaining": "Progress", "reward": "Reward", "until": "Ends November 7, 23:59 UTC",
    },
    "fr": {
        "subtitle": "La faille est ouverte. Terminez les missions quotidiennes pour gagner du butin. Réinitialisation : 00:00 UTC.",
        "welcome": "Ravitaillement de bienvenue", "welcome_hint": "Une fois par commandant, nouveau ou ancien.",
        "expeditions": "Exploration de la faille", "construction": "Renforcer la colonie", "operations": "Préparation opérationnelle",
        "claim": "Récupérer", "claimed": "Récupéré", "locked": "Pas encore terminé",
        "ended": "Événement inactif", "success": "Récompense dans l'inventaire !", "failed": "Récompense indisponible.",
        "remaining": "Progression", "reward": "Récompense", "until": "Fin le 7 novembre à 23:59 UTC",
    },
    "es": {
        "subtitle": "La grieta está abierta. Completa misiones diarias para ganar botín. Reinicio: 00:00 UTC.",
        "welcome": "Suministros de bienvenida", "welcome_hint": "Una vez por comandante, nuevo o veterano.",
        "expeditions": "Explorar la grieta", "construction": "Reforzar la colonia", "operations": "Preparación operativa",
        "claim": "Reclamar recompensa", "claimed": "Reclamado", "locked": "Aún sin completar",
        "ended": "Evento inactivo", "success": "¡Recompensa en el inventario!", "failed": "Recompensa no disponible.",
        "remaining": "Progreso", "reward": "Recompensa", "until": "Termina el 7 de noviembre, 23:59 UTC",
    },
    "pl": {
        "subtitle": "Szczelina jest otwarta. Wykonuj codzienne zadania po nagrody. Reset: 00:00 UTC.",
        "welcome": "Pakiet powitalny", "welcome_hint": "Raz na dowódcę, dla nowych i obecnych graczy.",
        "expeditions": "Badanie szczeliny", "construction": "Wzmocnij kolonię", "operations": "Gotowość operacyjna",
        "claim": "Odbierz nagrodę", "claimed": "Odebrano", "locked": "Jeszcze nieukończone",
        "ended": "Wydarzenie nieaktywne", "success": "Nagroda w ekwipunku!", "failed": "Nie można odebrać nagrody.",
        "remaining": "Postęp", "reward": "Nagroda", "until": "Koniec 7 listopada, 23:59 UTC",
    },
    "pt": {
        "subtitle": "A fenda está aberta. Completa missões diárias para ganhar prémios. Reinício: 00:00 UTC.",
        "welcome": "Suprimentos de boas-vindas", "welcome_hint": "Uma vez por comandante, novo ou antigo.",
        "expeditions": "Explorar a fenda", "construction": "Fortificar a colónia", "operations": "Prontidão operacional",
        "claim": "Recolher prémio", "claimed": "Recolhido", "locked": "Ainda não concluído",
        "ended": "Evento inativo", "success": "Prémio no inventário!", "failed": "Prémio indisponível.",
        "remaining": "Progresso", "reward": "Prémio", "until": "Termina a 7 de novembro, 23:59 UTC",
    },
    "ru": {
        "subtitle": "Разлом открыт. Выполняйте ежедневные задания ради наград. Сброс: 00:00 UTC.",
        "welcome": "Приветственный набор", "welcome_hint": "Один раз на командира, для новых и старых игроков.",
        "expeditions": "Исследование разлома", "construction": "Укрепление колонии", "operations": "Боевая готовность",
        "claim": "Забрать награду", "claimed": "Получено", "locked": "Ещё не выполнено",
        "ended": "Событие неактивно", "success": "Награда в инвентаре!", "failed": "Награда недоступна.",
        "remaining": "Прогресс", "reward": "Награда", "until": "До 7 ноября, 23:59 UTC",
    },
    "tr": {
        "subtitle": "Yarık açıldı. Etkinlik ödülleri için günlük görevleri tamamla. Sıfırlama: 00:00 UTC.",
        "welcome": "Hoş geldin erzakları", "welcome_hint": "Yeni ve mevcut her komutan için etkinlik boyunca bir kez.",
        "expeditions": "Yarık keşfi", "construction": "Koloniyi güçlendir", "operations": "Operasyon hazırlığı",
        "claim": "Ödülü al", "claimed": "Alındı", "locked": "Henüz tamamlanmadı",
        "ended": "Etkinlik etkin değil", "success": "Ödül envantere eklendi!", "failed": "Ödül alınamıyor.",
        "remaining": "İlerleme", "reward": "Ödül", "until": "7 Kasım, 23:59 UTC'de sona erer",
    },
}


def schema_ready(conn) -> bool:
    return (
        table_exists(conn, "voidfall_reward_claims")
        and table_exists(conn, "server_events")
        and table_exists(conn, "activity_xp_log")
        and inventory_schema_ready(conn)
    )


def _reward_preview(items: tuple[tuple[str, int], ...]) -> list[dict[str, Any]]:
    out = []
    for key, amount in items:
        spec = item_catalog_entry(key) or {}
        out.append({
            "item_key": key, "amount": amount,
            "name_key": spec.get("name_key") or key,
            "icon": spec.get("icon") or "✦",
            "image": spec.get("image") or "",
        })
    return out


def _utc_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _claim_key(key: str, ts: float) -> str:
    if key == WELCOME_KEY:
        return f"{CLAIM_PREFIX}:{WELCOME_KEY}"
    return f"{CLAIM_PREFIX}:{_utc_day(ts)}:{key}"


def _event_status(conn, ts: float) -> tuple[bool, bool]:
    row = conn.execute(
        "SELECT enabled, starts_at, ends_at FROM server_events WHERE slug = ? LIMIT 1;",
        (SLUG,),
    ).fetchone()
    if not row:
        return False, False
    active = (
        bool(int(row["enabled"] or 0))
        and START_AT <= ts <= END_AT
        and float(row["starts_at"]) <= ts <= float(row["ends_at"])
    )
    return True, active


def get_state(player_id: int, *, conn, now: float | None = None, locale: str | None = None) -> dict[str, Any]:
    ts = float(time.time() if now is None else now)
    if not schema_ready(conn) or int(player_id) <= 0:
        return {"ready": False, "visible": False, "active": False}
    from .i18n import current_locale
    loc = (locale or current_locale()).lower()
    copy = COPY.get(loc, COPY["en"])
    visible, active = _event_status(conn, ts)
    if not visible:
        return {"ready": True, "visible": False, "active": False}
    bucket = int(ts // 86400)
    rows = conn.execute(
        """
        SELECT source_key, COUNT(*) AS n FROM activity_xp_log
        WHERE player_id = ? AND day_bucket = ?
          AND source_key IN ('expedition','building_finish','account_research_finish','spy','recycle')
        GROUP BY source_key;
        """,
        (int(player_id), bucket),
    ).fetchall()
    counts = {str(r["source_key"]): int(r["n"]) for r in rows}
    date = _utc_day(ts)
    claim_rows = conn.execute(
        "SELECT claim_key FROM voidfall_reward_claims WHERE user_id = ? AND (claim_key = ? OR claim_key LIKE ?);",
        (int(player_id), f"{CLAIM_PREFIX}:welcome", f"{CLAIM_PREFIX}:{date}:%"),
    ).fetchall()
    claimed = {str(r["claim_key"]) for r in claim_rows}
    missions = []
    for key, target, sources, rewards, icon in MISSION_CATALOG:
        progress = min(target, sum(counts.get(src, 0) for src in sources))
        has_claimed = _claim_key(key, ts) in claimed
        missions.append({
            "key": key, "title": copy[key], "icon": icon,
            "progress": progress, "target": target,
            "claimed": has_claimed, "claimable": active and progress >= target and not has_claimed,
            "rewards": _reward_preview(rewards),
        })
    welcomed = _claim_key(WELCOME_KEY, ts) in claimed
    return {
        "ready": True, "visible": True, "active": active,
        "slug": SLUG, "day": date, "ends_at": END_AT,
        "copy": copy,
        "welcome": {
            "key": WELCOME_KEY, "claimed": welcomed, "claimable": active and not welcomed,
            "rewards": _reward_preview(WELCOME_ITEMS),
        },
        "missions": missions,
    }


def claim(player_id: int, key: str, *, conn, now: float | None = None) -> tuple[bool, str, dict[str, Any] | None]:
    """Caller owns a write transaction and must lock the account row first."""
    ts = float(time.time() if now is None else now)
    if not schema_ready(conn):
        return False, "unavailable", None
    if not (START_AT <= ts <= END_AT):
        return False, "event_ended", None
    allowed = (WELCOME_KEY,) + tuple(m[0] for m in MISSION_CATALOG)
    if key not in allowed:
        return False, "unknown_claim", None
    state = get_state(int(player_id), conn=conn, now=ts)
    if not state.get("active"):
        return False, "event_inactive", None
    if key == WELCOME_KEY:
        target = state["welcome"]
        rewards = WELCOME_ITEMS
    else:
        target = next(m for m in state["missions"] if m["key"] == key)
        rewards = next(m[3] for m in MISSION_CATALOG if m[0] == key)
    if target["claimed"]:
        return False, "already_claimed", None
    if not target["claimable"]:
        return False, "objective_incomplete", None

    claim_key = _claim_key(key, ts)
    for item_key, amount in rewards:
        if not grant_inventory_item(
            int(player_id), item_key, amount, conn=conn,
            metadata={"source": "voidfall", "claim_key": claim_key},
        ):
            return False, "grant_failed", None

    payload = [{"item_key": k, "amount": n} for k, n in rewards]
    conn.execute(
        "INSERT INTO voidfall_reward_claims (user_id, claim_key, reward_json, claimed_at) VALUES (?, ?, ?, ?);",
        (int(player_id), claim_key, json.dumps(payload, separators=(",", ":")), ts),
    )
    return True, "ok", {"claim_key": claim_key, "rewards": _reward_preview(rewards)}
