from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TRANSLATIONS = {
    "de": {
        "support_my_tickets": "Meine Tickets",
        "support_create_intro": "Neues Support-Ticket erstellen. Deine bestehenden Tickets findest du unter TICKETS in der Leiste.",
        "support_subject_label": "Betreff",
        "support_subject_placeholder": "Kurzbeschreibung deines Anliegens",
        "support_category_label": "Kategorie",
        "support_category_general": "Allgemein",
        "support_category_bug": "Bug",
        "support_category_account": "Account",
        "support_category_balance": "Balance",
        "support_category_billing": "Zahlung / Billing",
        "support_category_report": "Meldung",
        "support_priority_label": "Priorität",
        "support_priority_low": "Niedrig",
        "support_priority_normal": "Normal",
        "support_priority_high": "Hoch",
        "support_message_label": "Nachricht",
        "support_message_placeholder": "Beschreibe dein Problem möglichst konkret...",
        "support_submit": "Ticket senden",
        "support_tickets_intro": "Nur deine eigenen Tickets – Antworten vom Support und deine Nachrichten.",
        "support_ticket_list": "Ticketliste",
        "support_refresh": "Aktualisieren",
        "support_empty_tickets": "Noch keine Tickets vorhanden.",
        "support_status_open": "Offen",
        "support_status_progress": "In Bearbeitung",
        "support_status_closed": "Geschlossen",
        "support_sender_you": "Du",
        "support_sender_player": "Spieler",
        "support_unknown": "Unbekannt",
        "support_reply_placeholder": "Antwort schreiben...",
        "support_reply_send": "Antwort senden",
        "support_close_ticket": "Ticket schließen"
    },
    "en": {
        "support_my_tickets": "My tickets",
        "support_create_intro": "Create a new support ticket. You can find your existing tickets under TICKETS in the bar.",
        "support_subject_label": "Subject",
        "support_subject_placeholder": "Brief summary of your issue",
        "support_category_label": "Category",
        "support_category_general": "General",
        "support_category_bug": "Bug",
        "support_category_account": "Account",
        "support_category_balance": "Balance",
        "support_category_billing": "Billing",
        "support_category_report": "Report",
        "support_priority_label": "Priority",
        "support_priority_low": "Low",
        "support_priority_normal": "Normal",
        "support_priority_high": "High",
        "support_message_label": "Message",
        "support_message_placeholder": "Describe your issue as clearly as possible...",
        "support_submit": "Send ticket",
        "support_tickets_intro": "Only your own tickets – replies from support and your messages.",
        "support_ticket_list": "Ticket list",
        "support_refresh": "Refresh",
        "support_empty_tickets": "No tickets yet.",
        "support_status_open": "Open",
        "support_status_progress": "In progress",
        "support_status_closed": "Closed",
        "support_sender_you": "You",
        "support_sender_player": "Player",
        "support_unknown": "Unknown",
        "support_reply_placeholder": "Write a reply...",
        "support_reply_send": "Send reply",
        "support_close_ticket": "Close ticket"
    },
    "fr": {
        "support_my_tickets": "Mes tickets",
        "support_create_intro": "Créez un nouveau ticket de support. Vos tickets existants se trouvent sous TICKETS dans la barre.",
        "support_subject_label": "Objet",
        "support_subject_placeholder": "Résumé bref de votre demande",
        "support_category_label": "Catégorie",
        "support_category_general": "Général",
        "support_category_bug": "Bug",
        "support_category_account": "Compte",
        "support_category_balance": "Équilibrage",
        "support_category_billing": "Paiement",
        "support_category_report": "Signalement",
        "support_priority_label": "Priorité",
        "support_priority_low": "Faible",
        "support_priority_normal": "Normale",
        "support_priority_high": "Élevée",
        "support_message_label": "Message",
        "support_message_placeholder": "Décrivez votre problème aussi précisément que possible...",
        "support_submit": "Envoyer le ticket",
        "support_tickets_intro": "Uniquement vos tickets – réponses du support et vos messages.",
        "support_ticket_list": "Liste des tickets",
        "support_refresh": "Actualiser",
        "support_empty_tickets": "Aucun ticket pour le moment.",
        "support_status_open": "Ouvert",
        "support_status_progress": "En cours",
        "support_status_closed": "Fermé",
        "support_sender_you": "Vous",
        "support_sender_player": "Joueur",
        "support_unknown": "Inconnu",
        "support_reply_placeholder": "Écrire une réponse...",
        "support_reply_send": "Envoyer la réponse",
        "support_close_ticket": "Fermer le ticket"
    },
    "es": {
        "support_my_tickets": "Mis tickets",
        "support_create_intro": "Crea un nuevo ticket de soporte. Encontrarás tus tickets existentes en TICKETS, en la barra.",
        "support_subject_label": "Asunto",
        "support_subject_placeholder": "Resumen breve de tu problema",
        "support_category_label": "Categoría",
        "support_category_general": "General",
        "support_category_bug": "Error",
        "support_category_account": "Cuenta",
        "support_category_balance": "Balance",
        "support_category_billing": "Pago",
        "support_category_report": "Reporte",
        "support_priority_label": "Prioridad",
        "support_priority_low": "Baja",
        "support_priority_normal": "Normal",
        "support_priority_high": "Alta",
        "support_message_label": "Mensaje",
        "support_message_placeholder": "Describe tu problema con la mayor precisión posible...",
        "support_submit": "Enviar ticket",
        "support_tickets_intro": "Solo tus propios tickets – respuestas del soporte y tus mensajes.",
        "support_ticket_list": "Lista de tickets",
        "support_refresh": "Actualizar",
        "support_empty_tickets": "Aún no hay tickets.",
        "support_status_open": "Abierto",
        "support_status_progress": "En curso",
        "support_status_closed": "Cerrado",
        "support_sender_you": "Tú",
        "support_sender_player": "Jugador",
        "support_unknown": "Desconocido",
        "support_reply_placeholder": "Escribe una respuesta...",
        "support_reply_send": "Enviar respuesta",
        "support_close_ticket": "Cerrar ticket"
    },
    "pl": {
        "support_my_tickets": "Moje zgłoszenia",
        "support_create_intro": "Utwórz nowe zgłoszenie do pomocy. Swoje istniejące zgłoszenia znajdziesz pod TICKETS na pasku.",
        "support_subject_label": "Temat",
        "support_subject_placeholder": "Krótki opis problemu",
        "support_category_label": "Kategoria",
        "support_category_general": "Ogólne",
        "support_category_bug": "Błąd",
        "support_category_account": "Konto",
        "support_category_balance": "Balans",
        "support_category_billing": "Płatność",
        "support_category_report": "Zgłoszenie",
        "support_priority_label": "Priorytet",
        "support_priority_low": "Niski",
        "support_priority_normal": "Normalny",
        "support_priority_high": "Wysoki",
        "support_message_label": "Wiadomość",
        "support_message_placeholder": "Opisz swój problem możliwie dokładnie...",
        "support_submit": "Wyślij zgłoszenie",
        "support_tickets_intro": "Tylko twoje zgłoszenia – odpowiedzi pomocy i twoje wiadomości.",
        "support_ticket_list": "Lista zgłoszeń",
        "support_refresh": "Odśwież",
        "support_empty_tickets": "Brak zgłoszeń.",
        "support_status_open": "Otwarte",
        "support_status_progress": "W trakcie",
        "support_status_closed": "Zamknięte",
        "support_sender_you": "Ty",
        "support_sender_player": "Gracz",
        "support_unknown": "Nieznane",
        "support_reply_placeholder": "Napisz odpowiedź...",
        "support_reply_send": "Wyślij odpowiedź",
        "support_close_ticket": "Zamknij zgłoszenie"
    },
    "tr": {
        "support_my_tickets": "Taleplerim",
        "support_create_intro": "Yeni bir destek talebi oluştur. Mevcut taleplerini çubuktaki TICKETS bölümünde bulabilirsin.",
        "support_subject_label": "Konu",
        "support_subject_placeholder": "Sorununun kısa özeti",
        "support_category_label": "Kategori",
        "support_category_general": "Genel",
        "support_category_bug": "Hata",
        "support_category_account": "Hesap",
        "support_category_balance": "Denge",
        "support_category_billing": "Ödeme",
        "support_category_report": "Bildirim",
        "support_priority_label": "Öncelik",
        "support_priority_low": "Düşük",
        "support_priority_normal": "Normal",
        "support_priority_high": "Yüksek",
        "support_message_label": "Mesaj",
        "support_message_placeholder": "Sorununu mümkün olduğunca ayrıntılı açıkla...",
        "support_submit": "Talebi gönder",
        "support_tickets_intro": "Yalnızca kendi taleplerin – destek yanıtları ve mesajların.",
        "support_ticket_list": "Talep listesi",
        "support_refresh": "Yenile",
        "support_empty_tickets": "Henüz talep yok.",
        "support_status_open": "Açık",
        "support_status_progress": "İşlemde",
        "support_status_closed": "Kapalı",
        "support_sender_you": "Sen",
        "support_sender_player": "Oyuncu",
        "support_unknown": "Bilinmiyor",
        "support_reply_placeholder": "Yanıt yaz...",
        "support_reply_send": "Yanıtı gönder",
        "support_close_ticket": "Talebi kapat"
    },
    "ru": {
        "support_my_tickets": "Мои обращения",
        "support_create_intro": "Создайте новое обращение в поддержку. Существующие обращения находятся в разделе TICKETS на панели.",
        "support_subject_label": "Тема",
        "support_subject_placeholder": "Кратко опишите проблему",
        "support_category_label": "Категория",
        "support_category_general": "Общее",
        "support_category_bug": "Ошибка",
        "support_category_account": "Аккаунт",
        "support_category_balance": "Баланс",
        "support_category_billing": "Оплата",
        "support_category_report": "Жалоба",
        "support_priority_label": "Приоритет",
        "support_priority_low": "Низкий",
        "support_priority_normal": "Обычный",
        "support_priority_high": "Высокий",
        "support_message_label": "Сообщение",
        "support_message_placeholder": "Опишите проблему как можно подробнее...",
        "support_submit": "Отправить обращение",
        "support_tickets_intro": "Только ваши обращения – ответы поддержки и ваши сообщения.",
        "support_ticket_list": "Список обращений",
        "support_refresh": "Обновить",
        "support_empty_tickets": "Обращений пока нет.",
        "support_status_open": "Открыто",
        "support_status_progress": "В работе",
        "support_status_closed": "Закрыто",
        "support_sender_you": "Вы",
        "support_sender_player": "Игрок",
        "support_unknown": "Неизвестно",
        "support_reply_placeholder": "Написать ответ...",
        "support_reply_send": "Отправить ответ",
        "support_close_ticket": "Закрыть обращение"
    },
    "pt": {
        "support_my_tickets": "Meus tickets",
        "support_create_intro": "Crie um novo ticket de suporte. Seus tickets existentes ficam em TICKETS, na barra.",
        "support_subject_label": "Assunto",
        "support_subject_placeholder": "Resumo breve do seu problema",
        "support_category_label": "Categoria",
        "support_category_general": "Geral",
        "support_category_bug": "Bug",
        "support_category_account": "Conta",
        "support_category_balance": "Balanceamento",
        "support_category_billing": "Pagamento",
        "support_category_report": "Denúncia",
        "support_priority_label": "Prioridade",
        "support_priority_low": "Baixa",
        "support_priority_normal": "Normal",
        "support_priority_high": "Alta",
        "support_message_label": "Mensagem",
        "support_message_placeholder": "Descreva seu problema com o máximo de detalhes possível...",
        "support_submit": "Enviar ticket",
        "support_tickets_intro": "Somente seus tickets – respostas do suporte e suas mensagens.",
        "support_ticket_list": "Lista de tickets",
        "support_refresh": "Atualizar",
        "support_empty_tickets": "Ainda não há tickets.",
        "support_status_open": "Aberto",
        "support_status_progress": "Em andamento",
        "support_status_closed": "Fechado",
        "support_sender_you": "Você",
        "support_sender_player": "Jogador",
        "support_unknown": "Desconhecido",
        "support_reply_placeholder": "Escrever uma resposta...",
        "support_reply_send": "Enviar resposta",
        "support_close_ticket": "Fechar ticket"
    },
}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 occurrence, got {count}")
    return text.replace(old, new, 1)


def append_locale_keys() -> None:
    expected_keys = set(next(iter(TRANSLATIONS.values())))
    for lang, values in TRANSLATIONS.items():
        if set(values) != expected_keys:
            raise RuntimeError(f"locale key mismatch in {lang}")
        path = ROOT / "locales" / f"{lang}.json"
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        for key in expected_keys:
            if key in data:
                if data[key] != values[key]:
                    raise RuntimeError(f"{lang}: existing {key!r} has unexpected value")
        missing = [(key, values[key]) for key in values if key not in data]
        if not missing:
            continue
        stripped = text.rstrip()
        if not stripped.endswith("}"):
            raise RuntimeError(f"{path} is not a JSON object")
        prefix = stripped[:-1].rstrip()
        separator = "\n" if prefix.endswith("{") else ",\n"
        lines = [
            f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in missing
        ]
        new_text = prefix + separator + ",\n".join(lines) + "\n}\n"
        parsed = json.loads(new_text)
        for key, value in values.items():
            if parsed.get(key) != value:
                raise RuntimeError(f"{lang}: failed to write {key}")
        path.write_text(new_text, encoding="utf-8")


def patch_support_backend() -> None:
    path = "game/support.py"
    text = read(path)
    text = replace_once(
        text,
        "from .db import begin_write_transaction, commit, db, rollback, table_exists\n",
        "from .db import begin_write_transaction, commit, db, rollback, table_exists\nfrom .i18n import tr\n",
        label="support import",
    )
    old = '''def _ticket_status_label(status: str) -> str:\n    mapping = {\n        "open": "Offen",\n        "in_progress": "In Bearbeitung",\n        "closed": "Geschlossen",\n    }\n    return mapping.get(str(status or "open"), "Offen")\n\n\ndef _priority_label(priority: str) -> str:\n    mapping = {\n        "low": "Niedrig",\n        "normal": "Normal",\n        "high": "Hoch",\n    }\n    return mapping.get(str(priority or "normal"), "Normal")\n\n\ndef _category_label(category: str) -> str:\n    mapping = {\n        "general": "Allgemein",\n        "bug": "Bug",\n        "account": "Account",\n        "balance": "Balance",\n        "billing": "Zahlung / Billing",\n        "report": "Meldung",\n    }\n    return mapping.get(str(category or "general"), "Allgemein")\n'''
    new = '''def _ticket_status_label(status: str) -> str:\n    mapping = {\n        "open": "support_status_open",\n        "in_progress": "support_status_progress",\n        "closed": "support_status_closed",\n    }\n    return tr(mapping.get(str(status or "open"), "support_status_open"))\n\n\ndef _priority_label(priority: str) -> str:\n    mapping = {\n        "low": "support_priority_low",\n        "normal": "support_priority_normal",\n        "high": "support_priority_high",\n    }\n    return tr(mapping.get(str(priority or "normal"), "support_priority_normal"))\n\n\ndef _category_label(category: str) -> str:\n    mapping = {\n        "general": "support_category_general",\n        "bug": "support_category_bug",\n        "account": "support_category_account",\n        "balance": "support_category_balance",\n        "billing": "support_category_billing",\n        "report": "support_category_report",\n    }\n    return tr(mapping.get(str(category or "general"), "support_category_general"))\n'''
    text = replace_once(text, old, new, label="support label helpers")
    text = replace_once(text, '        return "Du"\n    return str(m["sender_name"] or "Spieler")\n', '        return tr("support_sender_you")\n    return str(m["sender_name"] or tr("support_sender_player"))\n', label="support sender labels")
    write(path, text)


def patch_support_template() -> None:
    path = "templates/partials/special_panel.html"
    text = read(path)
    replacements = {
        'aria-label="Meine Tickets" title="Meine Tickets"': 'aria-label="{{ T(\'support_my_tickets\') }}" title="{{ T(\'support_my_tickets\') }}"',
        'Neues Support-Ticket erstellen. Deine bestehenden Tickets findest du unter <strong>TICKETS</strong> in der Leiste.': '{{ T(\'support_create_intro\') }}',
        '<span>Betreff</span>': '<span>{{ T(\'support_subject_label\') }}</span>',
        'placeholder="Kurzbeschreibung deines Anliegens"': 'placeholder="{{ T(\'support_subject_placeholder\') }}"',
        '<span>Kategorie</span>': '<span>{{ T(\'support_category_label\') }}</span>',
        '<option value="general">Allgemein</option>': '<option value="general">{{ T(\'support_category_general\') }}</option>',
        '<option value="bug">Bug</option>': '<option value="bug">{{ T(\'support_category_bug\') }}</option>',
        '<option value="account">Account</option>': '<option value="account">{{ T(\'support_category_account\') }}</option>',
        '<option value="balance">Balance</option>': '<option value="balance">{{ T(\'support_category_balance\') }}</option>',
        '<option value="billing">Zahlung / Billing</option>': '<option value="billing">{{ T(\'support_category_billing\') }}</option>',
        '<option value="report">Meldung</option>': '<option value="report">{{ T(\'support_category_report\') }}</option>',
        '<span>Prioritaet</span>': '<span>{{ T(\'support_priority_label\') }}</span>',
        '<option value="low">Niedrig</option>': '<option value="low">{{ T(\'support_priority_low\') }}</option>',
        '<option value="normal" selected>Normal</option>': '<option value="normal" selected>{{ T(\'support_priority_normal\') }}</option>',
        '<option value="high">Hoch</option>': '<option value="high">{{ T(\'support_priority_high\') }}</option>',
        '<span>Nachricht</span>': '<span>{{ T(\'support_message_label\') }}</span>',
        'placeholder="Beschreibe dein Problem moeglichst konkret..."': 'placeholder="{{ T(\'support_message_placeholder\') }}"',
        '>Ticket senden</button>': '>{{ T(\'support_submit\') }}</button>',
        'data-support-open-tickets>Meine Tickets</button>': 'data-support-open-tickets>{{ T(\'support_my_tickets\') }}</button>',
        '<span class="gc-special-title">Meine Tickets</span>': '<span class="gc-special-title">{{ T(\'support_my_tickets\') }}</span>',
        'Nur deine eigenen Tickets – Antworten vom Support und deine Nachrichten.': '{{ T(\'support_tickets_intro\') }}',
        '<strong>Ticketliste</strong>': '<strong>{{ T(\'support_ticket_list\') }}</strong>',
        'data-support-refresh>Aktualisieren</button>': 'data-support-refresh>{{ T(\'support_refresh\') }}</button>',
        '<div class="gc-support-empty">Noch keine Tickets vorhanden.</div>': '<div class="gc-support-empty">{{ T(\'support_empty_tickets\') }}</div>',
    }
    for old, new in replacements.items():
        text = replace_once(text, old, new, label=f"support template {old[:32]}")
    write(path, text)


def patch_support_js() -> None:
    path = "static/main.js"
    text = read(path)
    replacements = {
        "Antwort schreiben...": "support_reply_placeholder",
        "Antwort senden": "support_reply_send",
        "Ticket schliessen": "support_close_ticket",
        "Ticket schließen": "support_close_ticket",
    }
    positions = []
    for literal in ("Antwort schreiben...", "Antwort senden", "Ticket schliessen", "Ticket schließen"):
        positions.extend(m.start() for m in re.finditer(re.escape(literal), text))
    if not positions:
        raise RuntimeError("support JS: could not locate reply UI")
    start = max(0, min(positions) - 16000)
    end = min(len(text), max(positions) + 16000)
    block = text[start:end]
    changed = 0
    for literal, key in replacements.items():
        pattern = re.compile(r'(["\'])' + re.escape(literal) + r'\1')
        block, count = pattern.subn(f't("{key}")', block)
        changed += count
    unknown_pattern = re.compile(r'(["\'])Unbekannt\1')
    block, unknown_count = unknown_pattern.subn('t("support_unknown")', block)
    changed += unknown_count
    if changed < 4:
        raise RuntimeError(f"support JS: expected at least 4 localized literals, changed {changed}")
    text = text[:start] + block + text[end:]
    write(path, text)


def patch_world_boss_help() -> None:
    template_path = "templates/world_boss.html"
    text = read(template_path)
    text = replace_once(
        text,
        "filename='css/world_boss_help_modal.css') }}?v={{ GC_ASSET_VERSION }}\">",
        "filename='css/world_boss_help_modal.css') }}?v={{ GC_ASSET_VERSION }}-wbhelp3\">",
        label="world boss css cache bust",
    )
    marker = "{% block content %}"
    extra = '''{% block extra_scripts %}\n{{ super() }}\n<script src="{{ url_for('static', filename='js/pages/world_boss_help.js') }}?v={{ GC_ASSET_VERSION }}-wbhelp3"></script>\n{% endblock %}\n\n\n'''
    text = replace_once(text, marker, extra + marker, label="world boss extra scripts")
    write(template_path, text)

    css_path = "static/css/world_boss_help_modal.css"
    css = read(css_path)
    css = replace_once(css, "  z-index: 5000;\n", "  z-index: 20000;\n  isolation: isolate;\n", label="world boss top z-index")
    write(css_path, css)

    js_path = ROOT / "static" / "js" / "pages" / "world_boss_help.js"
    js_path.write_text('''/* World Boss help modal top-layer portal. UI only; no gameplay state changes. */\n(() => {\n  "use strict";\n\n  const origins = new WeakMap();\n\n  function portalModal(modal) {\n    if (!modal || modal.parentElement === document.body) return;\n    origins.set(modal, { parent: modal.parentNode, next: modal.nextSibling });\n    document.body.appendChild(modal);\n  }\n\n  function restoreModal(modal) {\n    const origin = modal ? origins.get(modal) : null;\n    if (!modal || !origin) return;\n    if (!origin.parent || !origin.parent.isConnected) {\n      modal.remove();\n      origins.delete(modal);\n      return;\n    }\n    if (origin.next && origin.next.parentNode === origin.parent) {\n      origin.parent.insertBefore(modal, origin.next);\n    } else {\n      origin.parent.appendChild(modal);\n    }\n    origins.delete(modal);\n  }\n\n  function helpModal() {\n    return document.getElementById("wb-help-modal");\n  }\n\n  function restoreWhenClosed(modal) {\n    window.setTimeout(() => {\n      if (!modal) return;\n      const closed = modal.hidden || modal.getAttribute("aria-hidden") === "true";\n      if (closed) restoreModal(modal);\n    }, 0);\n  }\n\n  document.addEventListener("click", (event) => {\n    const target = event.target instanceof Element ? event.target : null;\n    if (!target) return;\n\n    if (target.closest("#wb-help-open")) {\n      portalModal(helpModal());\n      return;\n    }\n\n    if (target.closest("[data-wb-help-close]")) {\n      restoreWhenClosed(helpModal());\n      return;\n    }\n\n    if (target.closest("a[data-pjax-link]")) {\n      const modal = helpModal();\n      if (modal && origins.has(modal)) restoreModal(modal);\n    }\n  }, true);\n\n  document.addEventListener("keydown", (event) => {\n    if (event.key === "Escape") restoreWhenClosed(helpModal());\n  });\n})();\n''', encoding="utf-8")


def add_regression_tests() -> None:
    path = "tests/test_i18n_hardening.py"
    text = read(path)
    marker = "\n\ndef test_i18n_phase3_support_player_ui_uses_locale_ssot():"
    if marker in text:
        return
    addition = r'''


def test_i18n_phase3_support_player_ui_uses_locale_ssot():
    support_py = (ROOT / "game" / "support.py").read_text(encoding="utf-8")
    support_tpl = (ROOT / "templates" / "partials" / "special_panel.html").read_text(encoding="utf-8")
    main_js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    for literal in ("Offen", "In Bearbeitung", "Geschlossen", "Niedrig", "Allgemein"):
        assert literal not in support_py
    assert 'from .i18n import tr' in support_py
    assert 'tr("support_sender_you")' in support_py
    assert 'tr("support_sender_player")' in support_py

    for literal in (
        "Neues Support-Ticket erstellen.",
        ">Betreff<",
        ">Kategorie<",
        ">Prioritaet<",
        ">Ticket senden<",
        ">Meine Tickets<",
        ">Ticketliste<",
        ">Aktualisieren<",
        "Noch keine Tickets vorhanden.",
    ):
        assert literal not in support_tpl
    assert "T('support_my_tickets')" in support_tpl
    assert "T('support_message_placeholder')" in support_tpl

    for literal in ('"Antwort schreiben..."', '"Antwort senden"', '"Ticket schliessen"', "'Antwort schreiben...'", "'Antwort senden'", "'Ticket schliessen'"):
        assert literal not in main_js
    assert 't("support_reply_placeholder")' in main_js
    assert 't("support_reply_send")' in main_js
    assert 't("support_close_ticket")' in main_js


def test_world_boss_help_uses_true_document_top_layer():
    template = (ROOT / "templates" / "world_boss.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "world_boss_help_modal.css").read_text(encoding="utf-8")
    portal = (ROOT / "static" / "js" / "pages" / "world_boss_help.js").read_text(encoding="utf-8")

    assert "GC_ASSET_VERSION }}-wbhelp3" in template
    assert "world_boss_help.js" in template
    assert "z-index: 20000" in css
    assert "document.body.appendChild(modal)" in portal
    assert "restoreModal(modal)" in portal
'''
    write(path, text.rstrip() + addition + "\n")


def main() -> None:
    append_locale_keys()
    patch_support_backend()
    patch_support_template()
    patch_support_js()
    patch_world_boss_help()
    add_regression_tests()
    print("GC I18N Phase 3 Support + World Boss help patch applied")


if __name__ == "__main__":
    main()
