from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected source block not found in {path}")
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one source block in {path}, got {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


promo_path = ROOT / "game" / "shop_promos.py"
replace_once(
    promo_path,
    '''    rows = conn.execute(
        """
        SELECT l.id, l.creator_id, l.order_id, l.buyer_player_id, l.promo_code_id,
               l.commission_cents, c.player_id AS creator_player_id
        FROM shop_creator_ledger l
        JOIN shop_creators c ON c.id = l.creator_id
        WHERE l.status = 'held'
          AND (? IS NULL OR l.creator_id = ?);
        """,
        (int(creator_id) if creator_id else None, int(creator_id) if creator_id else None),
    ).fetchall()
''',
    '''    creator_filter = int(creator_id) if creator_id is not None else None
    if creator_filter is None:
        rows = conn.execute(
            """
            SELECT l.id, l.creator_id, l.order_id, l.buyer_player_id, l.promo_code_id,
                   l.commission_cents, c.player_id AS creator_player_id
            FROM shop_creator_ledger l
            JOIN shop_creators c ON c.id = l.creator_id
            WHERE l.status = 'held';
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT l.id, l.creator_id, l.order_id, l.buyer_player_id, l.promo_code_id,
                   l.commission_cents, c.player_id AS creator_player_id
            FROM shop_creator_ledger l
            JOIN shop_creators c ON c.id = l.creator_id
            WHERE l.status = 'held'
              AND l.creator_id = ?;
            """,
            (creator_filter,),
        ).fetchall()
''',
)

shop_path = ROOT / "game" / "shop.py"
replace_once(
    shop_path,
    '''    if out is not None:
        out["granted"] = {"lines": granted_all}
        out["fulfill_reason"] = grant_reason
        try:
            from . import shop_promos as promos

            if promos.schema_ready(conn):
                promos.credit_commission_for_order(out, conn=conn, now=ts)
                promos.release_held_commissions(conn=conn, now=ts)
        except Exception:
            pass
    _release_fulfillment_savepoint()
''',
    '''    if out is not None:
        out["granted"] = {"lines": granted_all}
        out["fulfill_reason"] = grant_reason
        # Creator bookkeeping is secondary to paid reward delivery. PostgreSQL
        # marks a transaction failed after *any* SQL error, so swallowing an
        # exception here without rolling back poisoned the outer fulfillment
        # savepoint and rolled back already-granted rewards. Isolate optional
        # promo work in its own savepoint and recover the transaction state.
        promo_savepoint = f"{savepoint}_promo"
        conn.execute(f"SAVEPOINT {promo_savepoint};")
        try:
            from . import shop_promos as promos

            if promos.schema_ready(conn):
                promos.credit_commission_for_order(out, conn=conn, now=ts)
                promos.release_held_commissions(conn=conn, now=ts)
            conn.execute(f"RELEASE SAVEPOINT {promo_savepoint};")
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {promo_savepoint};")
            conn.execute(f"RELEASE SAVEPOINT {promo_savepoint};")
    _release_fulfillment_savepoint()
''',
)

replace_once(
    shop_path,
    '''    elif status == STATUS_PAID:
        status_key = "paid"
        headline_key = "shop_return_paid_title"
        body_key = "shop_return_paid"
    else:
        status_key = "pending"
        headline_key = "shop_return_pending_title"
        body_key = "shop_return_pending"
''',
    '''    elif status == STATUS_PAID:
        status_key = "paid"
        headline_key = "shop_return_paid_title"
        body_key = "shop_return_paid"
    elif status == STATUS_FAILED:
        status_key = "failed"
        headline_key = "shop_return_failed_title"
        body_key = "shop_return_failed"
    else:
        status_key = "pending"
        headline_key = "shop_return_pending_title"
        body_key = "shop_return_pending"
''',
)

tpl_path = ROOT / "templates" / "shop_return.html"
replace_once(
    tpl_path,
    '''        {% elif status_key == 'pending' %}
          {{ T("shop_return_status_pending", "Ausstehend") }}
        {% else %}
''',
    '''        {% elif status_key == 'pending' %}
          {{ T("shop_return_status_pending", "Ausstehend") }}
        {% elif status_key == 'failed' %}
          {{ T("shop_return_status_failed", "Fehlgeschlagen") }}
        {% else %}
''',
)

translations = {
    "de": {
        "shop_return_status_failed": "Fehlgeschlagen",
        "shop_return_failed_title": "Freischaltung fehlgeschlagen",
        "shop_return_failed": "Die Zahlung wurde erkannt, aber die Freischaltung ist fehlgeschlagen. Bitte nicht erneut bezahlen; der Support kann die Bestellung sicher wiederherstellen.",
    },
    "en": {
        "shop_return_status_failed": "Failed",
        "shop_return_failed_title": "Fulfillment failed",
        "shop_return_failed": "The payment was detected, but the reward grant failed. Please do not pay again; support can safely recover the order.",
    },
    "fr": {
        "shop_return_status_failed": "Échec",
        "shop_return_failed_title": "Échec de l’attribution",
        "shop_return_failed": "Le paiement a été détecté, mais l’attribution a échoué. Ne payez pas à nouveau ; le support peut restaurer la commande en toute sécurité.",
    },
    "es": {
        "shop_return_status_failed": "Fallido",
        "shop_return_failed_title": "Falló la entrega",
        "shop_return_failed": "El pago fue detectado, pero la entrega de la recompensa falló. No vuelvas a pagar; soporte puede recuperar el pedido de forma segura.",
    },
    "pl": {
        "shop_return_status_failed": "Niepowodzenie",
        "shop_return_failed_title": "Nie udało się przyznać nagrody",
        "shop_return_failed": "Płatność została wykryta, ale przyznanie nagrody nie powiodło się. Nie płać ponownie; wsparcie może bezpiecznie odzyskać zamówienie.",
    },
    "tr": {
        "shop_return_status_failed": "Başarısız",
        "shop_return_failed_title": "Teslimat başarısız",
        "shop_return_failed": "Ödeme algılandı ancak ödül teslimatı başarısız oldu. Lütfen tekrar ödeme yapmayın; destek siparişi güvenli şekilde kurtarabilir.",
    },
    "ru": {
        "shop_return_status_failed": "Ошибка",
        "shop_return_failed_title": "Не удалось выдать награду",
        "shop_return_failed": "Платёж обнаружен, но выдача награды завершилась ошибкой. Не оплачивайте повторно; поддержка может безопасно восстановить заказ.",
    },
    "pt": {
        "shop_return_status_failed": "Falhou",
        "shop_return_failed_title": "Falha na entrega",
        "shop_return_failed": "O pagamento foi detectado, mas a entrega da recompensa falhou. Não pague novamente; o suporte pode recuperar o pedido com segurança.",
    },
}

for lang, values in translations.items():
    path = ROOT / "locales" / f"{lang}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for key, value in values.items():
        data[key] = value
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("GC-PROD-PAYPAL-PG-43 patch applied")
