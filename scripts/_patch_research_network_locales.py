from __future__ import annotations

import json
from pathlib import Path

TRANSLATIONS = {
    "es": {
        "research_network_title": "RED DE INVESTIGACIÓN",
        "research_network_jobs": "{count} / {limit} órdenes de investigación",
        "research_network_lab_ascension": "Laboratorio {level} · Ascensión {rank}",
        "research_network_lab_plain": "Laboratorio {level}",
        "research_network_speed": "Bonificación de investigación por Ascensión +{pct}%",
        "research_network_next_lab": "Siguiente espacio de cola: Laboratorio de investigación {level} → {slots} espacios",
        "research_network_next_ascension": "Siguiente espacio de cola: Ascensión {rank} con Laboratorio {level} → {slots} espacios",
        "research_network_ascend": "ACTIVAR ASCENSIÓN {rank}",
        "research_network_max": "Red de investigación completamente ampliada · 10 espacios de prestigio",
        "research_network_capacity": "Capacidad de cola: {slots}",
        "research_network_rank_speed": "Ascensión {rank} · +{pct}% velocidad de investigación",
        "research_network_ready": "Ascensión {rank} lista",
        "research_network_requires": "Ascensión {rank} con Laboratorio {level}",
        "research_network_error_generic": "La Ascensión de la red de investigación ha fallado.",
        "research_network_error_level_too_low": "El Laboratorio de investigación aún no ha alcanzado el nivel requerido.",
        "research_network_error_insufficient_resources": "No hay suficientes recursos para el tributo de Ascensión.",
        "research_network_error_queue_pending": "Finaliza o cancela primero las mejoras pendientes del Laboratorio de investigación.",
        "research_network_error_max_ascension": "Ya se ha alcanzado la Ascensión V.",
        "research_network_error_ascension_race": "La Ascensión ya fue procesada. Actualizando estado."
    },
    "fr": {
        "research_network_title": "RÉSEAU DE RECHERCHE",
        "research_network_jobs": "{count} / {limit} ordres de recherche",
        "research_network_lab_ascension": "Laboratoire {level} · Ascension {rank}",
        "research_network_lab_plain": "Laboratoire {level}",
        "research_network_speed": "Bonus de recherche d’Ascension +{pct}%",
        "research_network_next_lab": "Prochain emplacement de file : Laboratoire de recherche {level} → {slots} emplacements",
        "research_network_next_ascension": "Prochain emplacement de file : Ascension {rank} au Laboratoire {level} → {slots} emplacements",
        "research_network_ascend": "ACTIVER L’ASCENSION {rank}",
        "research_network_max": "Réseau de recherche entièrement développé · 10 emplacements de prestige",
        "research_network_capacity": "Capacité de file : {slots}",
        "research_network_rank_speed": "Ascension {rank} · +{pct}% vitesse de recherche",
        "research_network_ready": "Ascension {rank} prête",
        "research_network_requires": "Ascension {rank} au Laboratoire {level}",
        "research_network_error_generic": "L’Ascension du réseau de recherche a échoué.",
        "research_network_error_level_too_low": "Le Laboratoire de recherche n’a pas encore atteint le niveau requis.",
        "research_network_error_insufficient_resources": "Ressources insuffisantes pour le tribut d’Ascension.",
        "research_network_error_queue_pending": "Terminez ou annulez d’abord les améliorations du Laboratoire de recherche en attente.",
        "research_network_error_max_ascension": "L’Ascension V est déjà atteinte.",
        "research_network_error_ascension_race": "L’Ascension a déjà été traitée. Actualisation de l’état."
    },
    "pl": {
        "research_network_title": "SIEĆ BADAWCZA",
        "research_network_jobs": "{count} / {limit} zleceń badawczych",
        "research_network_lab_ascension": "Laboratorium {level} · Ascensja {rank}",
        "research_network_lab_plain": "Laboratorium {level}",
        "research_network_speed": "Premia badawcza Ascensji +{pct}%",
        "research_network_next_lab": "Następne miejsce kolejki: Laboratorium badawcze {level} → {slots} miejsc",
        "research_network_next_ascension": "Następne miejsce kolejki: Ascensja {rank} przy Laboratorium {level} → {slots} miejsc",
        "research_network_ascend": "AKTYWUJ ASCENSJĘ {rank}",
        "research_network_max": "Sieć badawcza w pełni rozwinięta · 10 miejsc prestiżowych",
        "research_network_capacity": "Pojemność kolejki: {slots}",
        "research_network_rank_speed": "Ascensja {rank} · +{pct}% szybkości badań",
        "research_network_ready": "Ascensja {rank} gotowa",
        "research_network_requires": "Ascensja {rank} przy Laboratorium {level}",
        "research_network_error_generic": "Ascensja sieci badawczej nie powiodła się.",
        "research_network_error_level_too_low": "Laboratorium badawcze nie osiągnęło jeszcze wymaganego poziomu.",
        "research_network_error_insufficient_resources": "Za mało zasobów na daninę Ascensji.",
        "research_network_error_queue_pending": "Najpierw zakończ lub anuluj oczekujące ulepszenia Laboratorium badawczego.",
        "research_network_error_max_ascension": "Ascensja V została już osiągnięta.",
        "research_network_error_ascension_race": "Ascensja została już przetworzona. Odświeżanie stanu."
    },
    "pt": {
        "research_network_title": "REDE DE PESQUISA",
        "research_network_jobs": "{count} / {limit} ordens de pesquisa",
        "research_network_lab_ascension": "Laboratório {level} · Ascensão {rank}",
        "research_network_lab_plain": "Laboratório {level}",
        "research_network_speed": "Bónus de pesquisa da Ascensão +{pct}%",
        "research_network_next_lab": "Próximo espaço da fila: Laboratório de Pesquisa {level} → {slots} espaços",
        "research_network_next_ascension": "Próximo espaço da fila: Ascensão {rank} no Laboratório {level} → {slots} espaços",
        "research_network_ascend": "ATIVAR ASCENSÃO {rank}",
        "research_network_max": "Rede de pesquisa totalmente expandida · 10 espaços de prestígio",
        "research_network_capacity": "Capacidade da fila: {slots}",
        "research_network_rank_speed": "Ascensão {rank} · +{pct}% velocidade de pesquisa",
        "research_network_ready": "Ascensão {rank} pronta",
        "research_network_requires": "Ascensão {rank} no Laboratório {level}",
        "research_network_error_generic": "A Ascensão da rede de pesquisa falhou.",
        "research_network_error_level_too_low": "O Laboratório de Pesquisa ainda não atingiu o nível necessário.",
        "research_network_error_insufficient_resources": "Recursos insuficientes para o tributo de Ascensão.",
        "research_network_error_queue_pending": "Conclua ou cancele primeiro as melhorias pendentes do Laboratório de Pesquisa.",
        "research_network_error_max_ascension": "A Ascensão V já foi alcançada.",
        "research_network_error_ascension_race": "A Ascensão já foi processada. A atualizar o estado."
    },
    "ru": {
        "research_network_title": "ИССЛЕДОВАТЕЛЬСКАЯ СЕТЬ",
        "research_network_jobs": "{count} / {limit} исследовательских заданий",
        "research_network_lab_ascension": "Лаборатория {level} · Вознесение {rank}",
        "research_network_lab_plain": "Лаборатория {level}",
        "research_network_speed": "Бонус исследований от Вознесения +{pct}%",
        "research_network_next_lab": "Следующий слот очереди: Исследовательская лаборатория {level} → {slots} слотов",
        "research_network_next_ascension": "Следующий слот очереди: Вознесение {rank} при Лаборатории {level} → {slots} слотов",
        "research_network_ascend": "АКТИВИРОВАТЬ ВОЗНЕСЕНИЕ {rank}",
        "research_network_max": "Исследовательская сеть полностью развита · 10 престижных слотов",
        "research_network_capacity": "Вместимость очереди: {slots}",
        "research_network_rank_speed": "Вознесение {rank} · +{pct}% к скорости исследований",
        "research_network_ready": "Вознесение {rank} готово",
        "research_network_requires": "Вознесение {rank} при Лаборатории {level}",
        "research_network_error_generic": "Не удалось выполнить Вознесение исследовательской сети.",
        "research_network_error_level_too_low": "Исследовательская лаборатория ещё не достигла требуемого уровня.",
        "research_network_error_insufficient_resources": "Недостаточно ресурсов для дани Вознесения.",
        "research_network_error_queue_pending": "Сначала завершите или отмените ожидающие улучшения Исследовательской лаборатории.",
        "research_network_error_max_ascension": "Вознесение V уже достигнуто.",
        "research_network_error_ascension_race": "Вознесение уже обработано. Состояние обновляется."
    },
    "tr": {
        "research_network_title": "ARAŞTIRMA AĞI",
        "research_network_jobs": "{count} / {limit} araştırma emri",
        "research_network_lab_ascension": "Laboratuvar {level} · Yükseliş {rank}",
        "research_network_lab_plain": "Laboratuvar {level}",
        "research_network_speed": "Yükseliş araştırma bonusu +{pct}%",
        "research_network_next_lab": "Sonraki kuyruk yuvası: Araştırma Laboratuvarı {level} → {slots} yuva",
        "research_network_next_ascension": "Sonraki kuyruk yuvası: Laboratuvar {level} seviyesinde Yükseliş {rank} → {slots} yuva",
        "research_network_ascend": "YÜKSELİŞ {rank} ETKİNLEŞTİR",
        "research_network_max": "Araştırma ağı tamamen genişletildi · 10 prestij yuvası",
        "research_network_capacity": "Kuyruk kapasitesi: {slots}",
        "research_network_rank_speed": "Yükseliş {rank} · +{pct}% araştırma hızı",
        "research_network_ready": "Yükseliş {rank} hazır",
        "research_network_requires": "Laboratuvar {level} seviyesinde Yükseliş {rank}",
        "research_network_error_generic": "Araştırma ağı Yükselişi başarısız oldu.",
        "research_network_error_level_too_low": "Araştırma Laboratuvarı henüz gerekli seviyeye ulaşmadı.",
        "research_network_error_insufficient_resources": "Yükseliş vergisi için yeterli kaynak yok.",
        "research_network_error_queue_pending": "Önce bekleyen Araştırma Laboratuvarı yükseltmelerini tamamlayın veya iptal edin.",
        "research_network_error_max_ascension": "Yükseliş V zaten ulaşıldı.",
        "research_network_error_ascension_race": "Yükseliş zaten işlendi. Durum yenileniyor."
    },
}

EXPECTED_KEYS = set(next(iter(TRANSLATIONS.values())))
assert all(set(values) == EXPECTED_KEYS for values in TRANSLATIONS.values())
assert len(EXPECTED_KEYS) == 19

for locale, additions in TRANSLATIONS.items():
    path = Path("locales") / f"{locale}.json"
    text = path.read_text(encoding="utf-8")
    current = json.loads(text)
    overlap = EXPECTED_KEYS.intersection(current)
    if overlap:
        raise SystemExit(f"{locale}: research keys already present: {sorted(overlap)}")

    stripped = text.rstrip()
    if not stripped.endswith("}"):
        raise SystemExit(f"{locale}: locale file does not end in JSON object")
    prefix = stripped[:-1].rstrip()
    if not prefix.endswith((',', '{')):
        prefix += ','

    lines = []
    for idx, (key, value) in enumerate(additions.items()):
        comma = ',' if idx < len(additions) - 1 else ''
        lines.append(
            f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}{comma}"
        )
    patched = prefix + "\n" + "\n".join(lines) + "\n}\n"
    json.loads(patched)
    path.write_text(patched, encoding="utf-8")

print("research network locale parity patch applied to:", ", ".join(TRANSLATIONS))
