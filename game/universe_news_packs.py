"""Curated player release packs — multi-locale copy for Universe News.

Owner remains game/universe_news.py. DB seeds store canonical German (de);
read-path overlays title/body from this module via current_locale().
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Structure per version:
#   version_tag, release_date, badge,
#   locales: { loc: { version_label, intro, added, changed, fixed } }
#
# German (de) is the canonical seed source.

RELEASE_PACK_I18N: Dict[str, Dict[str, Any]] = {
    "v0.9": {
        "version_tag": "v0.9",
        "release_date": "2026-07-31",
        "badge": "ALPHA",
        "locales": {
            "de": {
                "version_label": "LiveOps & World Events",
                "intro": (
                    "Genesis Colonies lebt: World Bosses, Titanen-Missionen, Piraten, "
                    "Login/Battle Pass, Allianz-Hub und mehr — Patchnotes für Commander."
                ),
                "added": [
                    "World Boss Events mit Encounter-Stage, Sofort-Angriff und Auto-Angriff",
                    "Zähmen in Phase 3 (10 % Chance, 10h Timekeeper, 1h Cooldown)",
                    "Titanen auf der Übersicht mit Titan-Link Popover",
                    "Ark-Token-Missionen: Patrouille, Schlag und Void-Run mit Fail-Risiko",
                    "Titan-Slots: Start 1, im Shop erweiterbar bis 4",
                    "Piraten-Ökosystem als lebendige Bedrohung",
                    "Login-Kalender und Battle Pass",
                    "Allianz-Hub mit Spenden, Projekten, Tech und Boni",
                    "Convenience-Shop (Stripe / PayPal)",
                    "Story Ops / Lore Sidequests mit Free-Shop Ark-Token Loop",
                ],
                "changed": [
                    "Titanen größer und mit Aura — lesbar auf hellen und dunklen Landscapes",
                    "Titan-Hotspots ohne Auswahl-Rahmen — nur Glow/Aura",
                    "World Boss: Angriff, Auto und Zähmen in einer Action-Bar",
                    "Performance und Live-Updates weiter gehärtet",
                    "UI-Feinschliff über Overview, Fleet und News",
                ],
                "fixed": [
                    "Diverse Sync- und PJAX-Themen",
                    "Timer- und Queue-Stabilität",
                    "Viele kleine Darstellungsfehler aus dem Alpha-Feedback",
                    "Titan-Link: Mission-Ende sofort sichtbar (ohne langes Warten)",
                ],
            },
            "en": {
                "version_label": "LiveOps & World Events",
                "intro": (
                    "Genesis Colonies is alive: World Bosses, Titan missions, pirates, "
                    "login/Battle Pass, Alliance Hub and more — patch notes for commanders."
                ),
                "added": [
                    "World Boss Events with encounter stage, instant attack and auto-attack",
                    "Taming in phase 3 (10% chance, 10h Timekeeper, 1h cooldown)",
                    "Titans on Overview with Titan-Link popover",
                    "Ark-Token missions: Patrol, Strike and Void-Run with fail risk",
                    "Titan slots: start at 1, expandable to 4 in the shop",
                    "Pirate ecosystem as a living threat",
                    "Login calendar and Battle Pass",
                    "Alliance Hub with donations, projects, tech and bonuses",
                    "Convenience shop (Stripe / PayPal)",
                    "Story Ops / lore sidequests with Free Shop Ark-Token loop",
                ],
                "changed": [
                    "Titans larger with aura — readable on light and dark landscapes",
                    "Titan hotspots without selection frames — glow/aura only",
                    "World Boss: attack, auto and tame in one action bar",
                    "Performance and live updates hardened further",
                    "UI polish across Overview, Fleet and News",
                ],
                "fixed": [
                    "Various sync and PJAX issues",
                    "Timer and queue stability",
                    "Many small display bugs from alpha feedback",
                    "Titan-Link: mission end visible immediately (no long wait)",
                ],
            },
            "es": {
                "version_label": "LiveOps y eventos mundiales",
                "intro": (
                    "Genesis Colonies cobra vida: World Bosses, misiones de Titanes, piratas, "
                    "login/Battle Pass, Hub de alianza y más — notas para comandantes."
                ),
                "added": [
                    "Eventos World Boss con fase de encuentro, ataque inmediato y autoataque",
                    "Domesticar en fase 3 (10 % de probabilidad, 10 h Timekeeper, 1 h de enfriamiento)",
                    "Titanes en la vista general con popover Titan-Link",
                    "Misiones Ark-Token: Patrulla, Golpe y Void-Run con riesgo de fallo",
                    "Ranuras de Titán: empieza en 1, ampliables a 4 en la tienda",
                    "Ecosistema pirata como amenaza viva",
                    "Calendario de login y Battle Pass",
                    "Hub de alianza con donaciones, proyectos, tech y bonos",
                    "Tienda de conveniencia (Stripe / PayPal)",
                    "Story Ops / misiones secundarias de lore con bucle Free Shop Ark-Token",
                ],
                "changed": [
                    "Titanes más grandes con aura — legibles en paisajes claros y oscuros",
                    "Hotspots de Titán sin marco de selección — solo brillo/aura",
                    "World Boss: ataque, auto y domesticar en una barra de acción",
                    "Rendimiento y actualizaciones en vivo más robustos",
                    "Pulido de UI en Overview, Flota y Noticias",
                ],
                "fixed": [
                    "Varios problemas de sync y PJAX",
                    "Estabilidad de temporizadores y colas",
                    "Muchos errores visuales pequeños del feedback alpha",
                    "Titan-Link: fin de misión visible al instante (sin larga espera)",
                ],
            },
            "fr": {
                "version_label": "LiveOps & événements mondiaux",
                "intro": (
                    "Genesis Colonies vit : World Bosses, missions Titan, pirates, "
                    "login/Battle Pass, Hub d'alliance et plus — notes pour les commandants."
                ),
                "added": [
                    "Événements World Boss avec phase de rencontre, attaque instantanée et auto-attaque",
                    "Apprivoisement en phase 3 (10 % de chance, 10 h Timekeeper, 1 h de recharge)",
                    "Titans sur l'aperçu avec popover Titan-Link",
                    "Missions Ark-Token : Patrouille, Frappe et Void-Run avec risque d'échec",
                    "Emplacements Titan : démarre à 1, extensible à 4 dans la boutique",
                    "Écosystème pirate comme menace vivante",
                    "Calendrier de connexion et Battle Pass",
                    "Hub d'alliance avec dons, projets, tech et bonus",
                    "Boutique de confort (Stripe / PayPal)",
                    "Story Ops / quêtes secondaires lore avec boucle Free Shop Ark-Token",
                ],
                "changed": [
                    "Titans plus grands avec aura — lisibles sur paysages clairs et sombres",
                    "Hotspots Titan sans cadre de sélection — glow/aura seulement",
                    "World Boss : attaque, auto et apprivoiser dans une barre d'actions",
                    "Performances et mises à jour live encore renforcées",
                    "Polish UI sur Overview, Flotte et Actualités",
                ],
                "fixed": [
                    "Divers problèmes de sync et PJAX",
                    "Stabilité des timers et files d'attente",
                    "Nombreux petits bugs d'affichage issus du feedback alpha",
                    "Titan-Link : fin de mission visible immédiatement (sans longue attente)",
                ],
            },
            "pl": {
                "version_label": "LiveOps i wydarzenia światowe",
                "intro": (
                    "Genesis Colonies żyje: World Bosses, misje Tytanów, piraci, "
                    "login/Battle Pass, Hub sojuszu i więcej — notatki dla dowódców."
                ),
                "added": [
                    "Wydarzenia World Boss z fazą starcia, natychmiastowym atakiem i auto-atakiem",
                    "Oswajanie w fazie 3 (10 % szansy, 10 h Timekeeper, 1 h odnowienia)",
                    "Tytani na przeglądzie z popoverem Titan-Link",
                    "Misje Ark-Token: Patrol, Uderzenie i Void-Run z ryzykiem porażki",
                    "Sloty Tytana: start 1, w sklepie do 4",
                    "Ekosystem piracki jako żywe zagrożenie",
                    "Kalendarz logowania i Battle Pass",
                    "Hub sojuszu z darowiznami, projektami, tech i bonusami",
                    "Sklep wygody (Stripe / PayPal)",
                    "Story Ops / sidequesty lore z pętlą Free Shop Ark-Token",
                ],
                "changed": [
                    "Większe Tytany z aurą — czytelne na jasnych i ciemnych krajobrazach",
                    "Hotspoty Tytana bez ramki zaznaczenia — tylko glow/aura",
                    "World Boss: atak, auto i oswajanie w jednym pasku akcji",
                    "Wydajność i aktualizacje na żywo dalej wzmocnione",
                    "Dopracowanie UI na Overview, Flocie i News",
                ],
                "fixed": [
                    "Różne problemy sync i PJAX",
                    "Stabilność timerów i kolejek",
                    "Wiele drobnych błędów wyświetlania z feedbacku alpha",
                    "Titan-Link: koniec misji widoczny od razu (bez długiego czekania)",
                ],
            },
            "pt": {
                "version_label": "LiveOps e eventos mundiais",
                "intro": (
                    "Genesis Colonies está vivo: World Bosses, missões de Titãs, piratas, "
                    "login/Battle Pass, Hub de aliança e mais — notas para comandantes."
                ),
                "added": [
                    "Eventos World Boss com fase de encontro, ataque instantâneo e autoataque",
                    "Domar na fase 3 (10 % de chance, 10 h Timekeeper, 1 h de recarga)",
                    "Titãs na visão geral com popover Titan-Link",
                    "Missões Ark-Token: Patrulha, Golpe e Void-Run com risco de falha",
                    "Slots de Titã: começa em 1, expansível até 4 na loja",
                    "Ecossistema pirata como ameaça viva",
                    "Calendário de login e Battle Pass",
                    "Hub de aliança com doações, projetos, tech e bônus",
                    "Loja de conveniência (Stripe / PayPal)",
                    "Story Ops / sidequests de lore com loop Free Shop Ark-Token",
                ],
                "changed": [
                    "Titãs maiores com aura — legíveis em paisagens claras e escuras",
                    "Hotspots de Titã sem moldura de seleção — só glow/aura",
                    "World Boss: ataque, auto e domar numa barra de ações",
                    "Desempenho e atualizações ao vivo ainda mais sólidos",
                    "Polimento de UI em Overview, Frota e Notícias",
                ],
                "fixed": [
                    "Vários problemas de sync e PJAX",
                    "Estabilidade de timers e filas",
                    "Muitos pequenos bugs de exibição do feedback alpha",
                    "Titan-Link: fim da missão visível de imediato (sem longa espera)",
                ],
            },
            "ru": {
                "version_label": "LiveOps и мировые события",
                "intro": (
                    "Genesis Colonies живёт: World Bosses, миссии Титанов, пираты, "
                    "login/Battle Pass, хаб альянса и многое другое — патчноуты для командиров."
                ),
                "added": [
                    "События World Boss с фазой столкновения, мгновенной атакой и автоатакой",
                    "Приручение в фазе 3 (10 % шанс, 10 ч Timekeeper, 1 ч перезарядка)",
                    "Титаны на обзоре с поповером Titan-Link",
                    "Миссии Ark-Token: Патруль, Удар и Void-Run с риском провала",
                    "Слоты Титана: старт 1, в магазине до 4",
                    "Пиратская экосистема как живая угроза",
                    "Календарь входа и Battle Pass",
                    "Хаб альянса с пожертвованиями, проектами, tech и бонусами",
                    "Магазин удобств (Stripe / PayPal)",
                    "Story Ops / лор-сайдквесты с циклом Free Shop Ark-Token",
                ],
                "changed": [
                    "Титаны крупнее с аурой — читаемы на светлых и тёмных ландшафтах",
                    "Хотспоты Титана без рамки выбора — только glow/aura",
                    "World Boss: атака, авто и приручение в одной панели действий",
                    "Производительность и live-обновления ещё надёжнее",
                    "Полировка UI на Overview, флоте и новостях",
                ],
                "fixed": [
                    "Разные проблемы sync и PJAX",
                    "Стабильность таймеров и очередей",
                    "Много мелких ошибок отображения из alpha-фидбека",
                    "Titan-Link: конец миссии виден сразу (без долгого ожидания)",
                ],
            },
            "tr": {
                "version_label": "LiveOps ve dünya etkinlikleri",
                "intro": (
                    "Genesis Colonies yaşıyor: World Bosses, Titan görevleri, korsanlar, "
                    "login/Battle Pass, İttifak Hub'ı ve daha fazlası — komutanlar için yama notları."
                ),
                "added": [
                    "Karşılaşma aşaması, anında saldırı ve otomatik saldırı ile World Boss etkinlikleri",
                    "3. fazda evcilleştirme (%10 şans, 10s Timekeeper, 1s bekleme)",
                    "Genel bakışta Titan-Link popover'lı Titanlar",
                    "Ark-Token görevleri: Devriye, Darbe ve başarısızlık riskli Void-Run",
                    "Titan yuvaları: 1 ile başlar, mağazada 4'e kadar",
                    "Canlı tehdit olarak korsan ekosistemi",
                    "Giriş takvimi ve Battle Pass",
                    "Bağışlar, projeler, tech ve bonuslarla İttifak Hub'ı",
                    "Kolaylık mağazası (Stripe / PayPal)",
                    "Free Shop Ark-Token döngülü Story Ops / lore yan görevleri",
                ],
                "changed": [
                    "Aura'lı daha büyük Titanlar — açık ve koyu manzaralarda okunur",
                    "Seçim çerçevesiz Titan hotspot'ları — yalnızca glow/aura",
                    "World Boss: saldırı, otomatik ve evcilleştirme tek eylem çubuğunda",
                    "Performans ve canlı güncellemeler daha da sağlam",
                    "Overview, Filo ve Haberler'de UI cilası",
                ],
                "fixed": [
                    "Çeşitli sync ve PJAX sorunları",
                    "Zamanlayıcı ve kuyruk kararlılığı",
                    "Alpha geri bildiriminden birçok küçük görüntü hatası",
                    "Titan-Link: görev sonu hemen görünür (uzun bekleme yok)",
                ],
            },
        },
    },
    "v0.9.1": {
        "version_tag": "v0.9.1",
        "release_date": "2026-08-01",
        "badge": "ALPHA",
        "locales": {
            "de": {
                "version_label": "Effective Stats & Polyglot Story",
                "intro": (
                    "Standardwerte werden zu echten Kampfwerten, Story Ops spricht deine Sprache, "
                    "und Titanen, Boosts sowie Mobile-UX sind geschärft."
                ),
                "added": [
                    "Story Ops vollständig in acht Sprachen (DE/EN/ES/FR/PL/PT/RU/TR)",
                    "Vorleser folgt der gewählten Game-Sprache (Neural + Browser-Fallback)",
                ],
                "changed": [
                    "GC-EFFSTAT: Katalog-Stats zeigen effektive Werte inkl. Gesamtbonus-%",
                    "Commander-, Tech-Tree- und World-Boss-Boosts ehrlich und sichtbar",
                    "Titan-Link mit wanderndem Progress-Icon und Fire-FX",
                    "Identity Name-Styles, Logistics Collect von Quell-Kolonien, Mobile Fleet-Details",
                    "Codex nur noch über Context-Button (keine Quick-Help-Banner)",
                ],
                "fixed": [
                    "EFFSTAT Aktive-Boni: lesbare Labels statt interner Keys; korrekte Direktiven-Beiträge",
                    "Admins erhalten alle Titan-Slots ohne Shop-Kauf",
                    "Timekeeper-Finish aktualisiert Karten-Locks und Afford korrekt",
                ],
            },
            "en": {
                "version_label": "Effective Stats & Polyglot Story",
                "intro": (
                    "Catalog base stats become real combat values, Story Ops speaks your language, "
                    "and Titans, boosts and mobile UX are sharpened."
                ),
                "added": [
                    "Story Ops fully in eight languages (DE/EN/ES/FR/PL/PT/RU/TR)",
                    "Narrator follows the selected game language (neural + browser fallback)",
                ],
                "changed": [
                    "GC-EFFSTAT: catalog stats show effective values including total bonus %",
                    "Commander, tech-tree and World Boss boosts honest and visible",
                    "Titan-Link with wandering progress icon and fire FX",
                    "Identity name styles, logistics collect from source colonies, mobile fleet details",
                    "Codex only via context button (no quick-help banners)",
                ],
                "fixed": [
                    "EFFSTAT active bonuses: readable labels instead of internal keys; correct directive contributions",
                    "Admins receive all Titan slots without a shop purchase",
                    "Timekeeper finish correctly refreshes card locks and afford state",
                ],
            },
            "es": {
                "version_label": "Stats efectivos e historia políglota",
                "intro": (
                    "Los valores de catálogo pasan a ser valores de combate reales, Story Ops habla tu idioma "
                    "y Titanes, boosts y UX móvil están más afilados."
                ),
                "added": [
                    "Story Ops completo en ocho idiomas (DE/EN/ES/FR/PL/PT/RU/TR)",
                    "El narrador sigue el idioma de juego elegido (neural + fallback del navegador)",
                ],
                "changed": [
                    "GC-EFFSTAT: las stats de catálogo muestran valores efectivos incl. % de bonus total",
                    "Boosts de Commander, árbol tech y World Boss honestos y visibles",
                    "Titan-Link con icono de progreso móvil y Fire-FX",
                    "Estilos de nombre Identity, Logistics Collect desde colonias origen, detalles de flota móvil",
                    "Codex solo por botón de contexto (sin banners quick-help)",
                ],
                "fixed": [
                    "Bonos activos EFFSTAT: etiquetas legibles en lugar de keys internas; aportes de directivas correctos",
                    "Los admins reciben todas las ranuras de Titán sin comprar en la tienda",
                    "Timekeeper finish actualiza correctamente bloqueos de carta y afford",
                ],
            },
            "fr": {
                "version_label": "Stats effectives & Story polyglotte",
                "intro": (
                    "Les valeurs catalogue deviennent de vraies valeurs de combat, Story Ops parle votre langue, "
                    "et Titans, boosts et UX mobile sont affûtés."
                ),
                "added": [
                    "Story Ops entièrement en huit langues (DE/EN/ES/FR/PL/PT/RU/TR)",
                    "Le narrateur suit la langue de jeu choisie (neural + fallback navigateur)",
                ],
                "changed": [
                    "GC-EFFSTAT : les stats catalogue montrent les valeurs effectives incl. % de bonus total",
                    "Boosts Commander, arbre tech et World Boss honnêtes et visibles",
                    "Titan-Link avec icône de progression mobile et Fire-FX",
                    "Styles de nom Identity, Logistics Collect depuis les colonies sources, détails flotte mobile",
                    "Codex uniquement via bouton contextuel (plus de bannières quick-help)",
                ],
                "fixed": [
                    "Bonus actifs EFFSTAT : libellés lisibles au lieu de clés internes ; contributions de directives correctes",
                    "Les admins reçoivent tous les emplacements Titan sans achat boutique",
                    "Timekeeper finish rafraîchit correctement les verrous de carte et l'afford",
                ],
            },
            "pl": {
                "version_label": "Efektywne statystyki i wielojęzyczna Story",
                "intro": (
                    "Wartości katalogowe stają się prawdziwymi wartościami bojowymi, Story Ops mówi Twoim językiem, "
                    "a Tytani, boosty i mobilne UX są wyostrzone."
                ),
                "added": [
                    "Story Ops w pełni w ośmiu językach (DE/EN/ES/FR/PL/PT/RU/TR)",
                    "Lektor podąża za wybranym językiem gry (neural + fallback przeglądarki)",
                ],
                "changed": [
                    "GC-EFFSTAT: statystyki katalogowe pokazują wartości efektywne w tym % łącznego bonusu",
                    "Boosty Commander, drzewa tech i World Boss uczciwe i widoczne",
                    "Titan-Link z wędrującą ikoną postępu i Fire-FX",
                    "Style nazw Identity, Logistics Collect z kolonii źródłowych, szczegóły floty na mobile",
                    "Codex tylko przez przycisk kontekstu (bez bannerów quick-help)",
                ],
                "fixed": [
                    "Aktywne bonusy EFFSTAT: czytelne etykiety zamiast wewnętrznych kluczy; poprawne wkłady dyrektyw",
                    "Admini otrzymują wszystkie sloty Tytana bez zakupu w sklepie",
                    "Timekeeper finish poprawnie odświeża blokady kart i afford",
                ],
            },
            "pt": {
                "version_label": "Stats efetivos e Story poliglota",
                "intro": (
                    "Valores de catálogo viram valores de combate reais, Story Ops fala o seu idioma "
                    "e Titãs, boosts e UX mobile estão mais afiados."
                ),
                "added": [
                    "Story Ops completo em oito idiomas (DE/EN/ES/FR/PL/PT/RU/TR)",
                    "O narrador segue o idioma de jogo escolhido (neural + fallback do navegador)",
                ],
                "changed": [
                    "GC-EFFSTAT: stats de catálogo mostram valores efetivos incl. % de bônus total",
                    "Boosts de Commander, árvore tech e World Boss honestos e visíveis",
                    "Titan-Link com ícone de progresso móvel e Fire-FX",
                    "Estilos de nome Identity, Logistics Collect de colônias fonte, detalhes de frota no mobile",
                    "Codex só via botão de contexto (sem banners quick-help)",
                ],
                "fixed": [
                    "Bônus ativos EFFSTAT: rótulos legíveis em vez de keys internas; contribuições de diretivas corretas",
                    "Admins recebem todos os slots de Titã sem comprar na loja",
                    "Timekeeper finish atualiza corretamente locks de carta e afford",
                ],
            },
            "ru": {
                "version_label": "Эффективные статы и многоязычная Story",
                "intro": (
                    "Каталожные значения становятся реальными боевыми, Story Ops говорит на вашем языке, "
                    "а Титаны, бусты и мобильный UX заточены."
                ),
                "added": [
                    "Story Ops полностью на восьми языках (DE/EN/ES/FR/PL/PT/RU/TR)",
                    "Диктор следует выбранному языку игры (neural + браузерный fallback)",
                ],
                "changed": [
                    "GC-EFFSTAT: каталожные статы показывают эффективные значения вкл. общий бонус-%",
                    "Бусты Commander, техдерева и World Boss честные и видимые",
                    "Titan-Link с блуждающей иконкой прогресса и Fire-FX",
                    "Стили имён Identity, Logistics Collect с исходных колоний, детали флота на mobile",
                    "Codex только через context-кнопку (без quick-help баннеров)",
                ],
                "fixed": [
                    "Активные бонусы EFFSTAT: читаемые подписи вместо внутренних ключей; корректные вклады директив",
                    "Админы получают все слоты Титана без покупки в магазине",
                    "Timekeeper finish корректно обновляет блокировки карт и afford",
                ],
            },
            "tr": {
                "version_label": "Efektif istatistikler ve çok dilli Story",
                "intro": (
                    "Katalog değerleri gerçek savaş değerlerine dönüşür, Story Ops dilinizi konuşur "
                    "ve Titanlar, boostlar ile mobil UX keskinleştirildi."
                ),
                "added": [
                    "Story Ops sekiz dilde tam (DE/EN/ES/FR/PL/PT/RU/TR)",
                    "Anlatıcı seçilen oyun dilini izler (neural + tarayıcı fallback)",
                ],
                "changed": [
                    "GC-EFFSTAT: katalog istatistikleri toplam bonus-% dahil efektif değerleri gösterir",
                    "Commander, tech ağacı ve World Boss boostları dürüst ve görünür",
                    "Gezinen ilerleme ikonu ve Fire-FX ile Titan-Link",
                    "Identity isim stilleri, kaynak kolonilerden Logistics Collect, mobil filo detayları",
                    "Codex yalnızca bağlam düğmesiyle (quick-help banner yok)",
                ],
                "fixed": [
                    "EFFSTAT aktif bonuslar: iç key yerine okunabilir etiketler; doğru direktif katkıları",
                    "Adminler mağaza alımı olmadan tüm Titan yuvalarını alır",
                    "Timekeeper finish kart kilitlerini ve afford'u doğru yeniler",
                ],
            },
        },
    },
    "v0.9.2": {
        "version_tag": "v0.9.2",
        "release_date": "2026-08-04",
        "badge": "ALPHA",
        "locales": {
            "de": {
                "version_label": "Knowledge, LiveOps & Kolonie-Stage",
                "intro": (
                    "Catch-up für LiveOps-Entdeckung plus die neue Kolonie-Stage auf Gebäude: "
                    "Planet-Landschaft, runde Props, +1/MAX direkt auf der Stage — und die Buttons "
                    "folgen deiner PlayerCard Identity-Farbe."
                ),
                "added": [
                    "Kolonie-Stage (Gebäude) — Planet-Landschaft mit runden Props und Inline-+1/MAX",
                    "World Boss & Titanen — serverweite Events, Angriff/Zähmen und Titan-Missionen auf der Übersicht",
                    "Commander-Klassen — Command Staff wählen, Skill-Trunk freischalten (dauerhaft)",
                    "Allianz-Hub — Spenden, Projekte, Tech und gemeinsame Boni",
                    "Story Ops — Lore-Arcs und Sidequests mit Ark-Token-Loop",
                    "Login-Kalender & Season Pass — tägliche Belohnungen und Season Ops",
                    "Shop & Identity — Convenience-Packs, Name-Styles und Free Shop (kein Combat-P2W)",
                    "Inventar & Sammler-Markt — Container öffnen, Collectibles tauschen",
                    "Asteroiden & Relikt-Arena — Bergung in der Galaxie, Case Battles im Inventar",
                    "Logistik & Expeditionen — Collect/Distribute über Kolonien, Deep-Space-Missionen",
                    "Codex-Wissen erweitert — Quick Help und Guides zu den LiveOps-Systemen",
                ],
                "changed": [
                    "Gebäude-Stage: kein schwarzes Deck/Blur; Detail-Popup ohne doppelte Build-Buttons",
                    "Stage-Buttons folgen der PlayerCard Identity-Farbe; Defaults pro Tab ohne Überlappung",
                    "Wissenslandkarte und Context-Help an den aktuellen Catalog angepasst",
                    "Spieler-Entdeckbarkeit: Hinweise und Codex-Routen für LiveOps nachgezogen",
                ],
                "fixed": [
                    "Technische Daten aus dem Stage-Popup: Card schließt zuerst (kein Modal-Stack)",
                    "Stale „Coming soon“-Hinweise zur Allianz in internen Patchnotes bereinigt",
                ],
            },
            "en": {
                "version_label": "Knowledge, LiveOps & Colony Stage",
                "intro": (
                    "LiveOps discoverability catch-up plus the new Buildings colony stage: "
                    "planet landscape, round props, +1/MAX on the stage — and buttons follow "
                    "your PlayerCard identity color."
                ),
                "added": [
                    "Colony Stage (Buildings) — planet landscape with round props and inline +1/MAX",
                    "World Boss & Titans — server-wide events, attack/tame, and Titan missions on Overview",
                    "Commander Classes — pick Command Staff, unlock the skill trunk (permanent)",
                    "Alliance Hub — donations, projects, tech and shared bonuses",
                    "Story Ops — lore arcs and sidequests with Ark-Token loop",
                    "Login calendar & Season Pass — daily rewards and Season Ops",
                    "Shop & Identity — convenience packs, name styles and Free Shop (no combat P2W)",
                    "Inventory & Collector Market — open containers, trade collectibles",
                    "Asteroids & Relic Arena — galaxy salvage, case battles in Inventory",
                    "Logistics & Expeditions — collect/distribute across colonies, deep-space missions",
                    "Codex knowledge expanded — quick help and guides for LiveOps systems",
                ],
                "changed": [
                    "Buildings stage: no black deck/blur; detail popup without duplicate build buttons",
                    "Stage buttons follow PlayerCard identity color; per-tab defaults without overlap",
                    "Knowledge map and context help aligned with the current catalog",
                    "Player discoverability: page hints and Codex routes for LiveOps updated",
                ],
                "fixed": [
                    "Technical data from stage popup: card closes first (no modal stack)",
                    "Stale “coming soon” Alliance notes cleaned up in internal patch notes",
                ],
            },
            "es": {
                "version_label": "Knowledge, LiveOps y Colony Stage",
                "intro": (
                    "Catch-up de LiveOps más la nueva Colony Stage en Edificios: "
                    "paisaje del planeta, props redondos, +1/MAX en la stage — y los botones "
                    "siguen el color Identity de tu PlayerCard."
                ),
                "added": [
                    "Colony Stage (Edificios) — paisaje planetario con props redondos y +1/MAX inline",
                    "World Boss y Titanes — eventos de servidor, ataque/domesticar y misiones de Titán en Overview",
                    "Clases de Commander — elige Command Staff, desbloquea el skill trunk (permanente)",
                    "Hub de alianza — donaciones, proyectos, tech y bonos compartidos",
                    "Story Ops — arcos de lore y misiones secundarias con bucle Ark-Token",
                    "Calendario de login y Season Pass — recompensas diarias y Season Ops",
                    "Tienda e Identity — packs de comodidad, estilos de nombre y Free Shop (sin P2W de combate)",
                    "Inventario y mercado coleccionista — abre contenedores, intercambia coleccionables",
                    "Asteroides y Relic Arena — salvamento en galaxia, case battles en Inventario",
                    "Logística y expediciones — collect/distribute entre colonias, misiones de espacio profundo",
                    "Codex ampliado — ayuda rápida y guías de sistemas LiveOps",
                ],
                "changed": [
                    "Stage de edificios: sin deck/blur negro; popup de detalle sin botones de build duplicados",
                    "Botones de stage siguen el color Identity de PlayerCard; defaults por pestaña sin solapes",
                    "Mapa de conocimiento y ayuda contextual alineados con el catálogo actual",
                    "Descubribilidad: pistas de página y rutas Codex de LiveOps actualizadas",
                ],
                "fixed": [
                    "Datos técnicos desde el popup de stage: la card se cierra primero (sin stack de modales)",
                    "Notas internas obsoletas de “próximamente” sobre Alianza limpiadas",
                ],
            },
            "fr": {
                "version_label": "Knowledge, LiveOps & Colony Stage",
                "intro": (
                    "Catch-up LiveOps plus la nouvelle Colony Stage des Bâtiments : "
                    "paysage planétaire, props ronds, +1/MAX sur la stage — et les boutons "
                    "suivent la couleur Identity de votre PlayerCard."
                ),
                "added": [
                    "Colony Stage (Bâtiments) — paysage planétaire avec props ronds et +1/MAX inline",
                    "World Boss & Titans — événements serveur, attaque/apprivoiser et missions Titan sur Overview",
                    "Classes Commander — choisissez le Command Staff, débloquez le skill trunk (permanent)",
                    "Hub d'alliance — dons, projets, tech et bonus partagés",
                    "Story Ops — arcs lore et quêtes secondaires avec boucle Ark-Token",
                    "Calendrier de connexion & Season Pass — récompenses quotidiennes et Season Ops",
                    "Boutique & Identity — packs confort, styles de nom et Free Shop (pas de P2W combat)",
                    "Inventaire & marché collectionneur — ouvrir des conteneurs, échanger des collectibles",
                    "Astéroïdes & Relic Arena — salvage galaxie, case battles dans l'Inventaire",
                    "Logistique & expéditions — collect/distribute entre colonies, missions deep-space",
                    "Codex élargi — aide rapide et guides des systèmes LiveOps",
                ],
                "changed": [
                    "Stage bâtiments : plus de deck/blur noir ; popup détail sans boutons build en double",
                    "Boutons de stage suivent la couleur Identity PlayerCard ; defaults par onglet sans chevauchement",
                    "Carte du savoir et aide contextuelle alignées sur le catalogue actuel",
                    "Découvrabilité : indices de page et routes Codex LiveOps mises à jour",
                ],
                "fixed": [
                    "Données techniques depuis le popup stage : la card se ferme d'abord (pas de stack modal)",
                    "Notes internes « bientôt » obsolètes sur l'Alliance nettoyées",
                ],
            },
            "pl": {
                "version_label": "Knowledge, LiveOps i Colony Stage",
                "intro": (
                    "Catch-up LiveOps oraz nowa Colony Stage na Budynkach: "
                    "krajobraz planety, okrągłe propsy, +1/MAX na stage — a przyciski "
                    "podążają za kolorem Identity Twojej PlayerCard."
                ),
                "added": [
                    "Colony Stage (Budynki) — krajobraz planety z okrągłymi propsami i inline +1/MAX",
                    "World Boss i Tytani — wydarzenia serwerowe, atak/oswajanie i misje Tytana na Overview",
                    "Klasy Commander — wybierz Command Staff, odblokuj skill trunk (trwale)",
                    "Hub sojuszu — darowizny, projekty, tech i wspólne bonusy",
                    "Story Ops — łuki lore i sidequesty z pętlą Ark-Token",
                    "Kalendarz logowania i Season Pass — codzienne nagrody i Season Ops",
                    "Sklep i Identity — pakiety wygody, style nazw i Free Shop (bez combat P2W)",
                    "Ekwipunek i rynek kolekcjonerski — otwieraj kontenery, wymieniaj collectibles",
                    "Asteroidy i Relic Arena — salvage w galaktyce, case battles w Ekwipunku",
                    "Logistyka i ekspedycje — collect/distribute między koloniami, misje deep-space",
                    "Rozszerzony Codex — szybka pomoc i przewodniki systemów LiveOps",
                ],
                "changed": [
                    "Stage budynków: bez czarnego deck/blur; popup szczegółów bez podwójnych przycisków budowy",
                    "Przyciski stage podążają za kolorem Identity PlayerCard; domyślne układy per zakładka bez nakładania",
                    "Mapa wiedzy i pomoc kontekstowa dopasowane do aktualnego katalogu",
                    "Odkrywalność: wskazówki stron i trasy Codex LiveOps zaktualizowane",
                ],
                "fixed": [
                    "Dane techniczne z popup stage: karta zamyka się najpierw (bez stosu modali)",
                    "Przestarzałe wewnętrzne notatki „wkrótce” o Sojuszu wyczyszczone",
                ],
            },
            "pt": {
                "version_label": "Knowledge, LiveOps e Colony Stage",
                "intro": (
                    "Catch-up LiveOps mais a nova Colony Stage em Edifícios: "
                    "paisagem do planeta, props redondos, +1/MAX no stage — e os botões "
                    "seguem a cor Identity do teu PlayerCard."
                ),
                "added": [
                    "Colony Stage (Edifícios) — paisagem planetária com props redondos e +1/MAX inline",
                    "World Boss e Titãs — eventos de servidor, ataque/domar e missões de Titã no Overview",
                    "Classes Commander — escolha o Command Staff, desbloqueie o skill trunk (permanente)",
                    "Hub de aliança — doações, projetos, tech e bônus partilhados",
                    "Story Ops — arcos de lore e sidequests com loop Ark-Token",
                    "Calendário de login e Season Pass — recompensas diárias e Season Ops",
                    "Loja e Identity — packs de conveniência, estilos de nome e Free Shop (sem P2W de combate)",
                    "Inventário e mercado colecionador — abra contentores, troque collectibles",
                    "Asteroides e Relic Arena — salvage na galáxia, case battles no Inventário",
                    "Logística e expedições — collect/distribute entre colónias, missões deep-space",
                    "Codex expandido — ajuda rápida e guias dos sistemas LiveOps",
                ],
                "changed": [
                    "Stage de edifícios: sem deck/blur preto; popup de detalhe sem botões de build duplicados",
                    "Botões do stage seguem a cor Identity do PlayerCard; defaults por separador sem sobreposição",
                    "Mapa de conhecimento e ajuda contextual alinhados com o catálogo atual",
                    "Descoberta: dicas de página e rotas Codex LiveOps atualizadas",
                ],
                "fixed": [
                    "Dados técnicos a partir do popup do stage: a card fecha primeiro (sem stack de modais)",
                    "Notas internas obsoletas de “em breve” sobre Aliança limpas",
                ],
            },
            "ru": {
                "version_label": "Knowledge, LiveOps и Colony Stage",
                "intro": (
                    "Catch-up LiveOps плюс новая Colony Stage на Зданиях: "
                    "пейзаж планеты, круглые props, +1/MAX на stage — и кнопки "
                    "следуют цвету Identity вашей PlayerCard."
                ),
                "added": [
                    "Colony Stage (Здания) — пейзаж планеты с круглыми props и inline +1/MAX",
                    "World Boss и Титаны — серверные события, атака/приручение и миссии Титана на Overview",
                    "Классы Commander — выберите Command Staff, откройте skill trunk (навсегда)",
                    "Хаб альянса — пожертвования, проекты, tech и общие бонусы",
                    "Story Ops — лор-арки и сайдквесты с циклом Ark-Token",
                    "Календарь входа и Season Pass — ежедневные награды и Season Ops",
                    "Магазин и Identity — пакеты удобства, стили имён и Free Shop (без combat P2W)",
                    "Инвентарь и рынок коллекционера — открывайте контейнеры, обменивайте collectibles",
                    "Астероиды и Relic Arena — salvage в галактике, case battles в Инвентаре",
                    "Логистика и экспедиции — collect/distribute между колониями, deep-space миссии",
                    "Расширенный Codex — быстрая помощь и гайды по LiveOps",
                ],
                "changed": [
                    "Stage зданий: без чёрного deck/blur; detail popup без дублирующих кнопок постройки",
                    "Кнопки stage следуют цвету Identity PlayerCard; defaults по вкладкам без наложений",
                    "Карта знаний и контекстная помощь приведены к актуальному каталогу",
                    "Открываемость: подсказки страниц и маршруты Codex LiveOps обновлены",
                ],
                "fixed": [
                    "Техданные из stage popup: карточка закрывается первой (без стека модалок)",
                    "Устаревшие внутренние заметки «скоро» про Альянс очищены",
                ],
            },
            "tr": {
                "version_label": "Knowledge, LiveOps ve Colony Stage",
                "intro": (
                    "LiveOps catch-up artı Binalar’daki yeni Colony Stage: "
                    "gezegen manzarası, yuvarlak props, stage üzerinde +1/MAX — ve düğmeler "
                    "PlayerCard Identity renginizi takip eder."
                ),
                "added": [
                    "Colony Stage (Binalar) — yuvarlak props ve inline +1/MAX ile gezegen manzarası",
                    "World Boss ve Titanlar — sunucu etkinlikleri, saldırı/evcilleştirme ve Overview'da Titan görevleri",
                    "Commander sınıfları — Command Staff seçin, skill trunk açın (kalıcı)",
                    "İttifak Hub — bağışlar, projeler, tech ve ortak bonuslar",
                    "Story Ops — lore yayları ve Ark-Token döngülü yan görevler",
                    "Giriş takvimi ve Season Pass — günlük ödüller ve Season Ops",
                    "Mağaza ve Identity — kolaylık paketleri, isim stilleri ve Free Shop (combat P2W yok)",
                    "Envanter ve koleksiyoncu pazarı — kapları açın, collectible takas edin",
                    "Asteroitler ve Relic Arena — galakside salvage, Envanterde case battles",
                    "Lojistik ve seferler — koloniler arası collect/distribute, deep-space görevler",
                    "Genişletilmiş Codex — LiveOps sistemleri için hızlı yardım ve rehberler",
                ],
                "changed": [
                    "Bina stage: siyah deck/blur yok; ayrıntı popup’ta çift build düğmesi yok",
                    "Stage düğmeleri PlayerCard Identity rengini takip eder; sekme başına çakışmasız varsayılanlar",
                    "Bilgi haritası ve bağlamsal yardım güncel katalogla hizalandı",
                    "Keşfedilebilirlik: LiveOps sayfa ipuçları ve Codex rotaları güncellendi",
                ],
                "fixed": [
                    "Stage popup’tan teknik veriler: card önce kapanır (modal yığını yok)",
                    "İttifak hakkında eski “yakında” iç yama notları temizlendi",
                ],
            },
        },
    },
    "v0.9.3": {
        "version_tag": "v0.9.3",
        "release_date": "2026-08-05",
        "badge": "ALPHA",
        "locales": {
            "de": {
                "version_label": "Command Initiation, World Boss & Vault",
                "intro": (
                    "Nachtrag seit v0.9.2: Command Initiation für neue Commander, "
                    "World-Boss-Cinematics, Secret Vault & Bodentruppen — plus weichere "
                    "Navigation ohne Reload-Feeling."
                ),
                "added": [
                    "Command Initiation — Do-first Tour mit LiveOps-Icons in der Topbar",
                    "Volle Spiel-Tour: Overview → Gebäude → Forschung → Militär → Galaxy",
                    "Bestehende Gebäude-/Tech-Level zählen für den Initiation-Fortschritt",
                    "Tipps zur effizienten Kolonie-Build-Order",
                    "World Boss Hero-Video-Reels — Farben folgen der Commander-Identity",
                    "Theater-Kampf-SFX bei World-Boss-Angriffen",
                    "Secret Vault auf der Verteidigung mit aktueller Loot-Exposition",
                    "Vault-Raid & Bodentruppen spielerreif (Inbound-Flotten, HUD, Records-Tab)",
                ],
                "changed": [
                    "Gebäude-Stage: Bau-FX, Detail-Popup und Level-Sync nach Queue-Finish",
                    "Schnelleres First Paint der Kolonie-Stage",
                    "Login Rewards, Battle Pass und Shop Claims ohne Soft-Reload",
                    "Topbar (Logo, Score, LiveOps-Icons) navigiert per PJAX in der Shell",
                    "Radar / Threat Net: weniger Last auf Probe- und Notification-Polls",
                    "Story Ops TTS gehärtet (Killian-Stimme, keine Smiley-Fehllektüre)",
                ],
                "fixed": [
                    "Planetwechsel: keine grauen Panels mehr",
                    "Story Ops 500 ohne gewählte Commander-Klasse",
                    "Stage-Queue- und Construction-Darstellung",
                    "Locale-Lücken (Crystal Tech, Tech-Tree Troops)",
                    "Diverse PJAX-/State-Sync-Themen auf Meta-Seiten und in der Topbar",
                ],
            },
            "en": {
                "version_label": "Command Initiation, World Boss & Vault",
                "intro": (
                    "Addendum since v0.9.2: Command Initiation for new commanders, "
                    "World Boss cinematics, Secret Vault & troops — plus smoother "
                    "navigation without reload feel."
                ),
                "added": [
                    "Command Initiation — do-first tour with LiveOps icons in the top bar",
                    "Full game tour: Overview → Buildings → Research → Military → Galaxy",
                    "Existing building/tech levels count toward Initiation progress",
                    "Tips for an efficient colony build order",
                    "World Boss hero video reels — colors follow Commander identity",
                    "Theater fight SFX on World Boss attacks",
                    "Secret Vault on Defense with current loot exposure",
                    "Vault raid & ground troops player-ready (inbound fleets, HUD, Records tab)",
                ],
                "changed": [
                    "Buildings stage: construction FX, detail popup, level sync after queue finish",
                    "Faster first paint for the colony stage",
                    "Login Rewards, Battle Pass and Shop claims without soft reload",
                    "Top bar (logo, score, LiveOps icons) navigates via PJAX in the shell",
                    "Radar / Threat Net: less load on probe and notification polls",
                    "Story Ops TTS hardened (Killian voice, no smiley misreads)",
                ],
                "fixed": [
                    "Planet switch: no more grey panels",
                    "Story Ops 500 without a chosen Commander class",
                    "Stage queue and construction presentation",
                    "Locale gaps (Crystal Tech, Tech-Tree troops)",
                    "Assorted PJAX/state sync issues on meta pages and the top bar",
                ],
            },
            "es": {
                "version_label": "Command Initiation, World Boss y Vault",
                "intro": (
                    "Addendum desde v0.9.2: Command Initiation para nuevos commanders, "
                    "cinemáticas de World Boss, Secret Vault y tropas — más navegación "
                    "suave sin sensación de recarga."
                ),
                "added": [
                    "Command Initiation — tour do-first con iconos LiveOps en la barra superior",
                    "Tour completo: Overview → Edificios → Investigación → Militar → Galaxia",
                    "Los niveles de edificios/tech existentes cuentan para el progreso de Initiation",
                    "Consejos para un orden de construcción eficiente de la colonia",
                    "Reels de vídeo hero de World Boss — colores según Identity del Commander",
                    "SFX de combate Theater en ataques al World Boss",
                    "Secret Vault en Defensa con exposición actual del botín",
                    "Asalto al Vault y tropas terrestres listos (flotas entrantes, HUD, pestaña Records)",
                ],
                "changed": [
                    "Stage de edificios: FX de construcción, popup de detalle, sync de nivel tras la cola",
                    "First paint más rápido de la Colony Stage",
                    "Login Rewards, Battle Pass y reclamaciones de Tienda sin soft reload",
                    "Barra superior (logo, score, iconos LiveOps) navega con PJAX en el shell",
                    "Radar / Threat Net: menos carga en polls de sonda y notificaciones",
                    "TTS de Story Ops reforzado (voz Killian, sin lectura errónea de smileys)",
                ],
                "fixed": [
                    "Cambio de planeta: sin paneles grises",
                    "Story Ops 500 sin clase de Commander elegida",
                    "Presentación de cola y construcción en la stage",
                    "Huecos de locale (Crystal Tech, tropas del Tech-Tree)",
                    "Varios temas de sync PJAX/estado en páginas meta y la barra superior",
                ],
            },
            "fr": {
                "version_label": "Command Initiation, World Boss & Vault",
                "intro": (
                    "Addendum depuis v0.9.2 : Command Initiation pour les nouveaux commanders, "
                    "cinématiques World Boss, Secret Vault & troupes — plus une navigation "
                    "plus fluide sans sensation de rechargement."
                ),
                "added": [
                    "Command Initiation — tour do-first avec icônes LiveOps dans la barre du haut",
                    "Tour complet : Overview → Bâtiments → Recherche → Militaire → Galaxie",
                    "Les niveaux bâtiments/tech existants comptent pour la progression Initiation",
                    "Conseils pour un ordre de construction de colonie efficace",
                    "Reels vidéo hero World Boss — couleurs selon l'Identity Commander",
                    "SFX de combat Theater sur les attaques World Boss",
                    "Secret Vault en Défense avec exposition actuelle du butin",
                    "Raid Vault & troupes terrestres prêts (flottes entrantes, HUD, onglet Records)",
                ],
                "changed": [
                    "Stage bâtiments : FX de construction, popup détail, sync niveau après fin de file",
                    "First paint plus rapide de la Colony Stage",
                    "Login Rewards, Battle Pass et claims Boutique sans soft reload",
                    "Barre du haut (logo, score, icônes LiveOps) navigue en PJAX dans le shell",
                    "Radar / Threat Net : moins de charge sur les polls sonde et notifications",
                    "TTS Story Ops renforcé (voix Killian, pas de lecture erronée des smileys)",
                ],
                "fixed": [
                    "Changement de planète : plus de panneaux gris",
                    "Story Ops 500 sans classe Commander choisie",
                    "Présentation file/construction sur la stage",
                    "Lacunes de locale (Crystal Tech, troupes Tech-Tree)",
                    "Divers sujets de sync PJAX/état sur pages méta et barre du haut",
                ],
            },
            "pl": {
                "version_label": "Command Initiation, World Boss i Vault",
                "intro": (
                    "Dodatek od v0.9.2: Command Initiation dla nowych commanderów, "
                    "cinematic World Boss, Secret Vault i oddziały — plus płynniejsza "
                    "nawigacja bez uczucia przeładowania."
                ),
                "added": [
                    "Command Initiation — tour do-first z ikonami LiveOps na górnym pasku",
                    "Pełna wycieczka: Overview → Budynki → Badania → Wojsko → Galaktyka",
                    "Istniejące poziomy budynków/tech liczą się do postępu Initiation",
                    "Wskazówki do efektywnej kolejności budowy kolonii",
                    "Reele wideo hero World Boss — kolory według Identity Commandera",
                    "SFX walki Theater przy atakach World Boss",
                    "Secret Vault w Obronie z aktualną ekspozycją łupu",
                    "Rajd Vault i wojska lądowe gotowe (floty przychodzące, HUD, zakładka Records)",
                ],
                "changed": [
                    "Stage budynków: FX budowy, popup szczegółów, sync poziomu po kolejce",
                    "Szybszy first paint Colony Stage",
                    "Login Rewards, Battle Pass i claimy Sklepu bez soft reload",
                    "Górny pasek (logo, score, ikony LiveOps) nawiguje PJAX w shellu",
                    "Radar / Threat Net: mniejsze obciążenie polli sondy i powiadomień",
                    "Wzmocnione TTS Story Ops (głos Killian, bez błędnego odczytu smile)",
                ],
                "fixed": [
                    "Zmiana planety: bez szarych paneli",
                    "Story Ops 500 bez wybranej klasy Commandera",
                    "Prezentacja kolejki i budowy na stage",
                    "Luki locale (Crystal Tech, oddziały Tech-Tree)",
                    "Różne tematy sync PJAX/stanu na stronach meta i górnym pasku",
                ],
            },
            "pt": {
                "version_label": "Command Initiation, World Boss e Vault",
                "intro": (
                    "Adenda desde v0.9.2: Command Initiation para novos commanders, "
                    "cinemáticas de World Boss, Secret Vault e tropas — mais navegação "
                    "suave sem sensação de reload."
                ),
                "added": [
                    "Command Initiation — tour do-first com ícones LiveOps na barra superior",
                    "Tour completo: Overview → Edifícios → Pesquisa → Militar → Galáxia",
                    "Níveis de edifícios/tech existentes contam para o progresso da Initiation",
                    "Dicas para uma ordem de construção eficiente da colónia",
                    "Reels de vídeo hero do World Boss — cores seguem a Identity do Commander",
                    "SFX de combate Theater em ataques ao World Boss",
                    "Secret Vault na Defesa com exposição atual do saque",
                    "Raid ao Vault e tropas terrestres prontos (frotas a chegar, HUD, separador Records)",
                ],
                "changed": [
                    "Stage de edifícios: FX de construção, popup de detalhe, sync de nível após a fila",
                    "First paint mais rápido da Colony Stage",
                    "Login Rewards, Battle Pass e claims da Loja sem soft reload",
                    "Barra superior (logo, score, ícones LiveOps) navega via PJAX no shell",
                    "Radar / Threat Net: menos carga nos polls de sonda e notificações",
                    "TTS Story Ops reforçado (voz Killian, sem leitura errada de smileys)",
                ],
                "fixed": [
                    "Troca de planeta: sem painéis cinzentos",
                    "Story Ops 500 sem classe Commander escolhida",
                    "Apresentação de fila e construção no stage",
                    "Falhas de locale (Crystal Tech, tropas Tech-Tree)",
                    "Vários temas de sync PJAX/estado em páginas meta e na barra superior",
                ],
            },
            "ru": {
                "version_label": "Command Initiation, World Boss и Vault",
                "intro": (
                    "Дополнение с v0.9.2: Command Initiation для новых commanders, "
                    "кинематограф World Boss, Secret Vault и войска — плюс более плавная "
                    "навигация без ощущения перезагрузки."
                ),
                "added": [
                    "Command Initiation — do-first тур с иконками LiveOps в верхней панели",
                    "Полный тур: Overview → Здания → Исследования → Военные → Галактика",
                    "Существующие уровни зданий/tech учитываются в прогрессе Initiation",
                    "Советы по эффективному порядку строительства колонии",
                    "Hero-видео рилы World Boss — цвета по Identity командира",
                    "Theater combat SFX при атаках World Boss",
                    "Secret Vault в Обороне с текущей экспозицией добычи",
                    "Рейд Vault и наземные войска готовы (входящие флоты, HUD, вкладка Records)",
                ],
                "changed": [
                    "Stage зданий: FX строительства, detail popup, sync уровня после очереди",
                    "Более быстрый first paint Colony Stage",
                    "Login Rewards, Battle Pass и claims Магазина без soft reload",
                    "Верхняя панель (лого, score, иконки LiveOps) навигирует PJAX в shell",
                    "Radar / Threat Net: меньше нагрузки на опросы зонда и уведомлений",
                    "Усилен TTS Story Ops (голос Killian, без ошибочного чтения смайлов)",
                ],
                "fixed": [
                    "Смена планеты: без серых панелей",
                    "Story Ops 500 без выбранного класса Commander",
                    "Отображение очереди и строительства на stage",
                    "Пробелы locale (Crystal Tech, войска Tech-Tree)",
                    "Разные темы sync PJAX/состояния на meta-страницах и верхней панели",
                ],
            },
            "tr": {
                "version_label": "Command Initiation, World Boss ve Vault",
                "intro": (
                    "v0.9.2’den beri ek: yeni commanderlar için Command Initiation, "
                    "World Boss sinematikleri, Secret Vault ve birlikler — artı reload "
                    "hissi olmadan daha akıcı gezinme."
                ),
                "added": [
                    "Command Initiation — üst çubukta LiveOps ikonlarıyla do-first tur",
                    "Tam oyun turu: Overview → Binalar → Araştırma → Askeri → Galaksi",
                    "Mevcut bina/tech seviyeleri Initiation ilerlemesine sayılır",
                    "Verimli koloni inşa sırası için ipuçları",
                    "World Boss hero video reels — renkler Commander Identity’yi izler",
                    "World Boss saldırılarında Theater savaş SFX",
                    "Savunmada Secret Vault — güncel ganimet maruziyeti",
                    "Vault baskını ve kara birlikleri hazır (gelen filolar, HUD, Records sekmesi)",
                ],
                "changed": [
                    "Bina stage: inşa FX, ayrıntı popup, kuyruk bitince seviye sync",
                    "Colony Stage için daha hızlı first paint",
                    "Login Rewards, Battle Pass ve Mağaza claim’leri soft reload olmadan",
                    "Üst çubuk (logo, score, LiveOps ikonları) shell içinde PJAX ile gezinir",
                    "Radar / Threat Net: sonda ve bildirim poll yükü azaltıldı",
                    "Story Ops TTS güçlendirildi (Killian sesi, smiley yanlış okuma yok)",
                ],
                "fixed": [
                    "Gezegen değişimi: gri paneller yok",
                    "Seçili Commander sınıfı olmadan Story Ops 500",
                    "Stage kuyruk ve inşa sunumu",
                    "Locale boşlukları (Crystal Tech, Tech-Tree birlikleri)",
                    "Meta sayfalarında ve üst çubukta çeşitli PJAX/state sync konuları",
                ],
            },
        },
    },
}


def _normalize_tag(version_tag: str) -> str:
    tag = str(version_tag or "").strip().lower()
    if tag and not tag.startswith("v"):
        tag = f"v{tag}"
    return tag


def get_release_pack(version_tag: str) -> Optional[Dict[str, Any]]:
    return RELEASE_PACK_I18N.get(_normalize_tag(version_tag))


def get_pack_locale(version_tag: str, locale: str) -> Optional[Dict[str, Any]]:
    """Return localized pack slice with fallback en → de."""
    pack = get_release_pack(version_tag)
    if not pack:
        return None
    locales = pack.get("locales") or {}
    loc = str(locale or "de").strip().lower().split("-")[0]
    return locales.get(loc) or locales.get("en") or locales.get("de")


def canonical_de_seed(version_tag: str) -> Optional[Dict[str, Any]]:
    """Flat DE pack for publish_release_pack seeding (single source of truth)."""
    pack = get_release_pack(version_tag)
    if not pack:
        return None
    de = (pack.get("locales") or {}).get("de")
    if not de:
        return None
    return {
        "version_tag": pack["version_tag"],
        "version_label": de["version_label"],
        "release_date": pack["release_date"],
        "badge": pack["badge"],
        "intro": de["intro"],
        "added": list(de.get("added") or []),
        "changed": list(de.get("changed") or []),
        "fixed": list(de.get("fixed") or []),
    }


def localize_release_news_entry(
    entry: Dict[str, Any],
    *,
    locale: str | None = None,
) -> Dict[str, Any]:
    """Overlay title/body for release:* rows from multi-locale packs."""
    from game.i18n import current_locale, normalize_locale

    ref = str(entry.get("source_ref") or "").strip()
    if not ref.startswith("release:"):
        return entry

    tag = _normalize_tag(entry.get("version_tag") or "")
    if not tag:
        # Parse from source_ref release:v0.9.1 or release:v0.9.1:added:0
        parts = ref.split(":")
        if len(parts) >= 2:
            tag = _normalize_tag(parts[1])
    pack = get_release_pack(tag)
    if not pack:
        return entry

    loc = normalize_locale(locale) if locale is not None else current_locale()
    loc_slice = get_pack_locale(tag, loc)
    de_slice = get_pack_locale(tag, "de")
    if not loc_slice or not de_slice:
        return entry

    out = dict(entry)
    is_major = bool(entry.get("is_major_release"))
    # Major: source_ref == release:{tag} (no section)
    ref_parts = ref.split(":")
    if is_major or (len(ref_parts) == 2):
        label = str(loc_slice.get("version_label") or "").strip()
        intro = str(loc_slice.get("intro") or "").strip()
        if label:
            out["title"] = f"{tag} — {label}"[:200]
        if intro:
            out["body"] = intro
        return out

    section = str(entry.get("entry_section") or "").strip().lower()
    if section not in ("added", "changed", "fixed"):
        # Infer from source_ref release:tag:section[:index]
        if len(ref_parts) >= 3:
            section = str(ref_parts[2] or "").strip().lower()
    if section not in ("added", "changed", "fixed"):
        return out

    de_bullets: List[str] = list(de_slice.get(section) or [])
    loc_bullets: List[str] = list(loc_slice.get(section) or [])
    if not de_bullets or not loc_bullets:
        return out

    body = str(entry.get("body") or "").strip()
    title = str(entry.get("title") or "").strip()
    idx: Optional[int] = None

    # Indexed source_ref: release:v0.9.1:added:0
    if len(ref_parts) >= 4:
        try:
            idx = int(ref_parts[3])
        except (TypeError, ValueError):
            idx = None

    if idx is None:
        for candidate in (body, title):
            if candidate in de_bullets:
                idx = de_bullets.index(candidate)
                break

    if idx is None or idx < 0 or idx >= len(loc_bullets):
        return out

    text = str(loc_bullets[idx] or "").strip()
    if text:
        out["title"] = text[:200]
        out["body"] = text
    return out
