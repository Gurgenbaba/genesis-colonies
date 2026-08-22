from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent.parent

HELP_ITEMS = [
    ("wb_help_raid_goal", "Community-Raid: World Bosse sind absichtlich auf viele Teilnehmer ausgelegt. Sehr starke Einzelspieler können früh beitragen, sollen den Boss aber nicht allein wegräumen."),
    ("wb_help_containment", "Eindämmung: In den ersten 2 Stunden wird übermäßiger persönlicher Frühschaden gedrosselt. Ab 5 % persönlichem Boss-Beitrag sinkt die Wirksamkeit deutlich; ab 10 % noch stärker."),
    ("wb_help_damage_caps", "Schadensgrenzen: Ein ×1-Angriff kann höchstens 3 % der maximalen Boss-HP entfernen, ein ×5-Angriff höchstens 12,5 %."),
    ("wb_help_resonance", "Flottenresonanz: Erfolgreiche Angriffe laden den gemeinsamen Serverbalken (×1 = +1, ×5 = +5). Bei 100 startet für 10 Minuten +50 % Schaden und +10 Prozentpunkte Krit-Chance für alle."),
    ("wb_help_target_lock", "Zielerfassung: Dein persönlicher Balken lädt pro Welle um 20 %, während Flottenresonanz um 25 %. Bei 100 % ist dein nächster Angriff garantiert kritisch."),
    ("wb_help_last_stand", "Letztes Aufgebot: Nach 75 % der Event-Laufzeit erhalten alle +25 % Schaden, falls der Boss noch lebt."),
    ("wb_help_attack", "Angriffe: Direkter Treffer ohne Flugzeit und ohne Schiffsverluste. ×1 hat 5 Minuten Cooldown; ×5 zählt als 5 Wellen und hat 25 Minuten Cooldown."),
    ("wb_help_limits", "Limits: Maximal 40 Wellen pro Spieler und Boss-Ereignis. Cooldowns und Wellenlimit gelten jeweils separat pro Boss."),
    ("wb_help_board", "Rangliste: Schaden, Wellen und Allianzbeiträge werden pro Boss gewertet. Dein aktueller Rang und Allianzschaden stehen direkt auf der Boss-Card."),
    ("wb_help_rewards", "Belohnungen: Teilnahme gewährt Boss-Loot; Top 10 % erhalten zusätzlich Void + Boss-Loot, Platz 1 Mythic, die Top-Allianz ein Relic und der Expo-Entdecker bei Schaden zusätzlich Boss-Loot."),
    ("wb_help_alliance_xp", "Allianz-XP: Skaliert mit dem Schaden deiner Wellen — mehr Schaden bringt mehr Allianz-XP, mit einem Cap pro Welle."),
    ("wb_help_schedule", "Zeitplan: Bis zu 3 World Bosse können gleichzeitig aktiv sein. Neue Bosse erscheinen nach dem Spawn-Takt oder selten durch Expeditionen."),
    ("wb_help_catch", "Zähmen: In Phase 3 (≤25 % HP) besteht pro Versuch eine Chance von 10 % für 10h Timekeeper. Gezähmte Companions stehen auf der Übersicht und sammeln Ark-Token."),
]

TRANSLATIONS = {
    "de": {
        "wb_help_lead": "World Bosse sind serverweite Community-Raids. Alle Spieler greifen dieselben Lebenspunkte an, bauen gemeinsam Raid-Boni auf und kämpfen um persönliche sowie Allianz-Ränge.",
        **dict(HELP_ITEMS),
    },
    "en": {
        "wb_help_lead": "World Bosses are server-wide community raids. All players attack the same shared health pool, build raid bonuses together, and compete for personal and alliance ranks.",
        "wb_help_raid_goal": "Community raid: World Bosses are deliberately designed for many participants. Very strong solo players can contribute early, but should not be able to erase a fresh boss alone.",
        "wb_help_containment": "Containment: During the first 2 hours, excessive personal early damage is throttled. After 5% personal boss contribution effectiveness drops sharply; after 10% it is reduced even further.",
        "wb_help_damage_caps": "Damage caps: A ×1 attack can remove at most 3% of the boss's maximum HP, while a ×5 attack can remove at most 12.5%.",
        "wb_help_resonance": "Fleet Resonance: Successful attacks charge the shared server meter (×1 = +1, ×5 = +5). At 100, a 10-minute window starts with +50% damage and +10 percentage points critical-hit chance for everyone.",
        "wb_help_target_lock": "Target Lock: Your personal meter charges by 20% per wave, or 25% during Fleet Resonance. At 100%, your next attack is guaranteed to critically hit.",
        "wb_help_last_stand": "Last Stand: After 75% of the event lifetime has passed, everyone gains +25% damage if the boss is still alive.",
        "wb_help_attack": "Attacks: Instant strike with no flight time and no ship losses. ×1 has a 5-minute cooldown; ×5 counts as 5 waves and has a 25-minute cooldown.",
        "wb_help_limits": "Limits: Maximum 40 waves per player and boss event. Cooldowns and wave limits are tracked separately for each boss.",
        "wb_help_board": "Ranking: Damage, waves, and alliance contributions are scored per boss. Your current rank and alliance damage are shown directly on the boss card.",
        "wb_help_rewards": "Rewards: Participation grants boss loot; the top 10% also receive Void + boss loot, rank 1 gets Mythic, the top alliance gets a Relic, and an expedition discoverer who deals damage gets extra boss loot.",
        "wb_help_alliance_xp": "Alliance XP: Scales with the damage of your waves — more damage grants more Alliance XP, with a cap per wave.",
        "wb_help_schedule": "Schedule: Up to 3 World Bosses can be active at once. New bosses appear through the spawn cycle or rarely through expeditions.",
        "wb_help_catch": "Taming: In Phase 3 (≤25% HP), each attempt has a 10% chance and costs 10h Timekeeper. Tamed companions appear on the overview and collect Ark Tokens.",
    },
    "fr": {
        "wb_help_lead": "Les World Bosses sont des raids communautaires à l'échelle du serveur. Tous les joueurs attaquent les mêmes PV partagés, construisent ensemble des bonus de raid et se disputent les classements individuels et d'alliance.",
        "wb_help_raid_goal": "Raid communautaire : les World Bosses sont conçus pour de nombreux participants. Les joueurs très puissants peuvent contribuer tôt, mais ne doivent pas pouvoir éliminer seuls un boss fraîchement apparu.",
        "wb_help_containment": "Confinement : pendant les 2 premières heures, les dégâts personnels excessifs sont freinés. Après 5 % de contribution personnelle aux PV du boss, l'efficacité baisse fortement ; après 10 %, elle baisse encore davantage.",
        "wb_help_damage_caps": "Limites de dégâts : une attaque ×1 peut retirer au maximum 3 % des PV max du boss, et une attaque ×5 au maximum 12,5 %.",
        "wb_help_resonance": "Résonance de flotte : les attaques réussies chargent la jauge commune du serveur (×1 = +1, ×5 = +5). À 100, une fenêtre de 10 minutes donne +50 % de dégâts et +10 points de pourcentage de chance de critique à tous.",
        "wb_help_target_lock": "Verrouillage de cible : votre jauge personnelle gagne 20 % par vague, ou 25 % pendant la Résonance de flotte. À 100 %, votre prochaine attaque est un coup critique garanti.",
        "wb_help_last_stand": "Dernier rempart : après 75 % de la durée de l'événement, tous gagnent +25 % de dégâts si le boss est toujours vivant.",
        "wb_help_attack": "Attaques : frappe instantanée sans temps de vol ni perte de vaisseaux. ×1 a 5 minutes de recharge ; ×5 compte comme 5 vagues et a 25 minutes de recharge.",
        "wb_help_limits": "Limites : 40 vagues maximum par joueur et par événement de boss. Les temps de recharge et la limite de vagues sont suivis séparément pour chaque boss.",
        "wb_help_board": "Classement : dégâts, vagues et contributions d'alliance sont comptés par boss. Votre rang actuel et les dégâts de votre alliance apparaissent directement sur la carte du boss.",
        "wb_help_rewards": "Récompenses : la participation donne du butin de boss ; le top 10 % reçoit aussi Void + butin de boss, la 1re place obtient Mythic, la meilleure alliance un Relic, et le découvreur par expédition ayant infligé des dégâts reçoit du butin supplémentaire.",
        "wb_help_alliance_xp": "XP d'alliance : elle augmente avec les dégâts de vos vagues — plus de dégâts donnent plus d'XP d'alliance, avec un plafond par vague.",
        "wb_help_schedule": "Calendrier : jusqu'à 3 World Bosses peuvent être actifs en même temps. Les nouveaux boss apparaissent selon le cycle de spawn ou rarement via les expéditions.",
        "wb_help_catch": "Apprivoisement : en Phase 3 (≤25 % PV), chaque tentative a 10 % de chance et coûte 10 h de Timekeeper. Les compagnons apprivoisés apparaissent sur l'aperçu et collectent des Ark Tokens.",
    },
    "es": {
        "wb_help_lead": "Los World Bosses son incursiones comunitarias de todo el servidor. Todos los jugadores atacan la misma vida compartida, generan juntos bonificaciones de incursión y compiten por rangos personales y de alianza.",
        "wb_help_raid_goal": "Incursión comunitaria: los World Bosses están diseñados para muchos participantes. Los jugadores muy fuertes pueden aportar mucho al principio, pero no deberían poder borrar solos a un jefe recién aparecido.",
        "wb_help_containment": "Contención: durante las primeras 2 horas se reduce el daño personal excesivo al inicio. Tras aportar un 5 % de la vida del jefe, la eficacia baja claramente; después del 10 %, baja aún más.",
        "wb_help_damage_caps": "Límites de daño: un ataque ×1 puede quitar como máximo un 3 % de la vida máxima del jefe y un ataque ×5 como máximo un 12,5 %.",
        "wb_help_resonance": "Resonancia de flota: los ataques exitosos cargan el medidor compartido del servidor (×1 = +1, ×5 = +5). Al llegar a 100 comienza una ventana de 10 minutos con +50 % de daño y +10 puntos porcentuales de probabilidad de crítico para todos.",
        "wb_help_target_lock": "Fijación de objetivo: tu medidor personal carga un 20 % por oleada, o un 25 % durante Resonancia de flota. Al 100 %, tu siguiente ataque será crítico garantizado.",
        "wb_help_last_stand": "Última resistencia: cuando ha pasado el 75 % de la duración del evento, todos obtienen +25 % de daño si el jefe sigue vivo.",
        "wb_help_attack": "Ataques: golpe instantáneo sin tiempo de vuelo ni pérdidas de naves. ×1 tiene 5 minutos de enfriamiento; ×5 cuenta como 5 oleadas y tiene 25 minutos de enfriamiento.",
        "wb_help_limits": "Límites: máximo 40 oleadas por jugador y evento de jefe. Los enfriamientos y el límite de oleadas se controlan por separado para cada jefe.",
        "wb_help_board": "Clasificación: daño, oleadas y contribuciones de alianza se contabilizan por jefe. Tu rango actual y el daño de tu alianza aparecen directamente en la tarjeta del jefe.",
        "wb_help_rewards": "Recompensas: participar otorga botín del jefe; el top 10 % recibe además Void + botín del jefe, el puesto 1 obtiene Mythic, la mejor alianza un Relic y el descubridor por expedición que haga daño obtiene botín adicional.",
        "wb_help_alliance_xp": "XP de alianza: escala con el daño de tus oleadas — más daño concede más XP de alianza, con un límite por oleada.",
        "wb_help_schedule": "Calendario: pueden estar activos hasta 3 World Bosses a la vez. Los nuevos jefes aparecen mediante el ciclo de aparición o raramente por expediciones.",
        "wb_help_catch": "Domesticación: en la Fase 3 (≤25 % de vida), cada intento tiene un 10 % de probabilidad y cuesta 10 h de Timekeeper. Los compañeros domesticados aparecen en la vista general y recogen Ark Tokens.",
    },
    "pl": {
        "wb_help_lead": "World Bossowie to rajdy społecznościowe całego serwera. Wszyscy gracze atakują wspólną pulę HP, razem budują premie rajdowe i rywalizują o rankingi graczy oraz sojuszy.",
        "wb_help_raid_goal": "Rajd społecznościowy: World Bossowie są celowo zaprojektowani dla wielu uczestników. Bardzo silni gracze mogą mocno pomóc na początku, ale nie powinni samodzielnie usuwać świeżo pojawionego bossa.",
        "wb_help_containment": "Powstrzymanie: przez pierwsze 2 godziny nadmierne wczesne obrażenia jednego gracza są ograniczane. Po osobistym wkładzie równym 5 % HP bossa skuteczność wyraźnie spada, a po 10 % spada jeszcze mocniej.",
        "wb_help_damage_caps": "Limity obrażeń: atak ×1 może zabrać maksymalnie 3 % maksymalnego HP bossa, a atak ×5 maksymalnie 12,5 %.",
        "wb_help_resonance": "Rezonans floty: udane ataki ładują wspólny licznik serwera (×1 = +1, ×5 = +5). Przy 100 uruchamia się 10-minutowe okno z +50 % obrażeń i +10 punktów procentowych szansy na trafienie krytyczne dla wszystkich.",
        "wb_help_target_lock": "Namierzanie celu: twój osobisty licznik rośnie o 20 % na falę lub o 25 % podczas Rezonansu floty. Przy 100 % następny atak ma gwarantowane trafienie krytyczne.",
        "wb_help_last_stand": "Ostatni bastion: po upływie 75 % czasu wydarzenia wszyscy otrzymują +25 % obrażeń, jeśli boss nadal żyje.",
        "wb_help_attack": "Ataki: natychmiastowe uderzenie bez czasu lotu i bez strat statków. ×1 ma 5 minut odnowienia; ×5 liczy się jako 5 fal i ma 25 minut odnowienia.",
        "wb_help_limits": "Limity: maksymalnie 40 fal na gracza i wydarzenie bossa. Czasy odnowienia i limity fal są liczone osobno dla każdego bossa.",
        "wb_help_board": "Ranking: obrażenia, fale i wkład sojuszu są liczone osobno dla każdego bossa. Aktualna pozycja i obrażenia sojuszu są widoczne bezpośrednio na karcie bossa.",
        "wb_help_rewards": "Nagrody: udział daje łup bossa; top 10 % otrzymuje dodatkowo Void + łup bossa, 1. miejsce Mythic, najlepszy sojusz Relic, a odkrywca z ekspedycji po zadaniu obrażeń dodatkowy łup bossa.",
        "wb_help_alliance_xp": "XP sojuszu: skaluje się z obrażeniami twoich fal — większe obrażenia dają więcej XP sojuszu, z limitem na falę.",
        "wb_help_schedule": "Harmonogram: jednocześnie mogą być aktywni maksymalnie 3 World Bossowie. Nowi bossowie pojawiają się zgodnie z cyklem spawnu lub rzadko dzięki ekspedycjom.",
        "wb_help_catch": "Oswajanie: w Fazie 3 (≤25 % HP) każda próba ma 10 % szans i kosztuje 10 h Timekeepera. Oswojeni towarzysze pojawiają się na przeglądzie i zbierają Ark Tokeny.",
    },
    "tr": {
        "wb_help_lead": "World Boss'lar sunucu çapında topluluk baskınlarıdır. Tüm oyuncular aynı ortak can havuzuna saldırır, baskın bonuslarını birlikte oluşturur ve bireysel ile ittifak sıralamaları için yarışır.",
        "wb_help_raid_goal": "Topluluk baskını: World Boss'lar özellikle çok sayıda katılımcı için tasarlanmıştır. Çok güçlü tek oyuncular başlangıçta büyük katkı sağlayabilir, ancak yeni doğmuş bir boss'u tek başına silememelidir.",
        "wb_help_containment": "Sınırlama: İlk 2 saat boyunca aşırı kişisel erken hasar kısılır. Boss canının kişisel olarak %5'ine ulaşıldığında etkinlik belirgin biçimde düşer; %10'dan sonra daha da azalır.",
        "wb_help_damage_caps": "Hasar sınırları: ×1 saldırısı boss'un maksimum canının en fazla %3'ünü, ×5 saldırısı ise en fazla %12,5'ini azaltabilir.",
        "wb_help_resonance": "Filo Rezonansı: Başarılı saldırılar ortak sunucu göstergesini doldurur (×1 = +1, ×5 = +5). 100'e ulaştığında herkes için 10 dakika boyunca +%50 hasar ve +10 yüzde puanı kritik şansı başlar.",
        "wb_help_target_lock": "Hedef Kilidi: Kişisel göstergen her dalgada %20, Filo Rezonansı sırasında %25 dolar. %100'de bir sonraki saldırın garantili kritik vurur.",
        "wb_help_last_stand": "Son Direniş: Etkinlik süresinin %75'i geçtiğinde boss hâlâ yaşıyorsa herkes +%25 hasar kazanır.",
        "wb_help_attack": "Saldırılar: Uçuş süresi ve gemi kaybı olmadan anlık vuruş. ×1 için 5 dakika bekleme süresi vardır; ×5, 5 dalga sayılır ve 25 dakika bekleme süresine sahiptir.",
        "wb_help_limits": "Sınırlar: Oyuncu ve boss etkinliği başına en fazla 40 dalga. Bekleme süreleri ve dalga sınırı her boss için ayrı takip edilir.",
        "wb_help_board": "Sıralama: Hasar, dalgalar ve ittifak katkıları boss başına hesaplanır. Güncel sıran ve ittifak hasarın doğrudan boss kartında gösterilir.",
        "wb_help_rewards": "Ödüller: Katılım boss ganimeti verir; ilk %10 ayrıca Void + boss ganimeti, 1. sıra Mythic, en iyi ittifak Relic ve hasar veren keşif kâşifi ek boss ganimeti alır.",
        "wb_help_alliance_xp": "İttifak XP'si: Dalgalarının hasarıyla ölçeklenir — daha fazla hasar daha fazla İttifak XP'si verir, dalga başına bir üst sınır vardır.",
        "wb_help_schedule": "Takvim: Aynı anda en fazla 3 World Boss aktif olabilir. Yeni boss'lar doğma döngüsüyle veya nadiren keşiflerden ortaya çıkar.",
        "wb_help_catch": "Evcilleştirme: Faz 3'te (≤%25 HP) her denemenin %10 şansı vardır ve 10 saat Timekeeper harcar. Evcilleştirilen yoldaşlar genel bakışta görünür ve Ark Token toplar.",
    },
    "ru": {
        "wb_help_lead": "World Boss — это общесерверные рейды сообщества. Все игроки атакуют общий запас здоровья, вместе накапливают рейдовые бонусы и соревнуются в личном и союзном рейтингах.",
        "wb_help_raid_goal": "Рейд сообщества: World Boss специально рассчитаны на множество участников. Очень сильные одиночные игроки могут много внести в начале, но не должны в одиночку уничтожать только что появившегося босса.",
        "wb_help_containment": "Сдерживание: первые 2 часа чрезмерный ранний личный урон ограничивается. После личного вклада в 5 % HP босса эффективность заметно падает, а после 10 % снижается ещё сильнее.",
        "wb_help_damage_caps": "Лимиты урона: атака ×1 может снять не более 3 % максимального HP босса, а атака ×5 — не более 12,5 %.",
        "wb_help_resonance": "Резонанс флота: успешные атаки заряжают общий серверный индикатор (×1 = +1, ×5 = +5). При 100 запускается окно на 10 минут: +50 % урона и +10 процентных пунктов к шансу критического удара для всех.",
        "wb_help_target_lock": "Захват цели: ваш личный индикатор заряжается на 20 % за волну или на 25 % во время Резонанса флота. При 100 % следующая атака гарантированно будет критической.",
        "wb_help_last_stand": "Последний рубеж: после 75 % длительности события все получают +25 % урона, если босс всё ещё жив.",
        "wb_help_attack": "Атаки: мгновенный удар без времени полёта и без потерь кораблей. ×1 имеет перезарядку 5 минут; ×5 считается как 5 волн и имеет перезарядку 25 минут.",
        "wb_help_limits": "Лимиты: максимум 40 волн на игрока в одном событии босса. Перезарядки и лимит волн учитываются отдельно для каждого босса.",
        "wb_help_board": "Рейтинг: урон, волны и вклад союза считаются отдельно для каждого босса. Текущий ранг и урон союза отображаются прямо на карточке босса.",
        "wb_help_rewards": "Награды: участие даёт добычу босса; топ-10 % дополнительно получают Void + добычу босса, 1-е место — Mythic, лучший союз — Relic, а обнаруживший босса экспедицией и нанёсший урон — дополнительную добычу босса.",
        "wb_help_alliance_xp": "XP союза: зависит от урона ваших волн — больше урона даёт больше XP союза, с лимитом на одну волну.",
        "wb_help_schedule": "Расписание: одновременно могут быть активны до 3 World Boss. Новые боссы появляются по циклу спавна или редко благодаря экспедициям.",
        "wb_help_catch": "Приручение: в Фазе 3 (≤25 % HP) каждая попытка имеет шанс 10 % и стоит 10 ч Timekeeper. Прирученные компаньоны появляются в обзоре и собирают Ark Token.",
    },
    "pt": {
        "wb_help_lead": "Os World Bosses são incursões comunitárias de todo o servidor. Todos os jogadores atacam a mesma vida partilhada, constroem juntos bónus de incursão e competem por classificações pessoais e de aliança.",
        "wb_help_raid_goal": "Incursão comunitária: os World Bosses foram feitos para muitos participantes. Jogadores muito fortes podem contribuir bastante no início, mas não devem conseguir eliminar sozinhos um boss recém-aparecido.",
        "wb_help_containment": "Contenção: durante as primeiras 2 horas, dano pessoal excessivo no início é reduzido. Após contribuir pessoalmente com 5 % da vida do boss, a eficácia cai bastante; após 10 %, cai ainda mais.",
        "wb_help_damage_caps": "Limites de dano: um ataque ×1 pode remover no máximo 3 % da vida máxima do boss, enquanto um ataque ×5 pode remover no máximo 12,5 %.",
        "wb_help_resonance": "Ressonância da frota: ataques bem-sucedidos carregam o medidor partilhado do servidor (×1 = +1, ×5 = +5). Ao chegar a 100 começa uma janela de 10 minutos com +50 % de dano e +10 pontos percentuais de chance crítica para todos.",
        "wb_help_target_lock": "Travamento de alvo: o teu medidor pessoal carrega 20 % por vaga, ou 25 % durante a Ressonância da frota. A 100 %, o próximo ataque é um crítico garantido.",
        "wb_help_last_stand": "Última resistência: após 75 % da duração do evento, todos recebem +25 % de dano se o boss ainda estiver vivo.",
        "wb_help_attack": "Ataques: golpe instantâneo sem tempo de voo nem perda de naves. ×1 tem 5 minutos de recarga; ×5 conta como 5 vagas e tem 25 minutos de recarga.",
        "wb_help_limits": "Limites: máximo de 40 vagas por jogador e evento de boss. Recargas e limite de vagas são controlados separadamente para cada boss.",
        "wb_help_board": "Classificação: dano, vagas e contribuições da aliança são contabilizados por boss. A tua posição atual e o dano da aliança aparecem diretamente no cartão do boss.",
        "wb_help_rewards": "Recompensas: participar concede loot do boss; o top 10 % recebe também Void + loot do boss, o 1.º lugar recebe Mythic, a melhor aliança recebe Relic e quem descobre o boss numa expedição e causa dano recebe loot adicional.",
        "wb_help_alliance_xp": "XP de aliança: escala com o dano das tuas vagas — mais dano concede mais XP de aliança, com um limite por vaga.",
        "wb_help_schedule": "Agenda: podem estar ativos até 3 World Bosses ao mesmo tempo. Novos bosses aparecem pelo ciclo de spawn ou raramente através de expedições.",
        "wb_help_catch": "Domesticação: na Fase 3 (≤25 % HP), cada tentativa tem 10 % de chance e custa 10h de Timekeeper. Companheiros domesticados aparecem na visão geral e recolhem Ark Tokens.",
    },
}


def replace_json_string(text: str, key: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(r'(?m)^(\s*)' + re.escape(json.dumps(key, ensure_ascii=False)) + r'\s*:\s*"(?:\\.|[^"\\])*"(,?)\s*$')
    replacement_value = json.dumps(value, ensure_ascii=False)
    match = pattern.search(text)
    if not match:
        return text, False
    replacement = f'{match.group(1)}{json.dumps(key, ensure_ascii=False)}: {replacement_value}{match.group(2)}'
    return text[:match.start()] + replacement + text[match.end():], True


def update_locale(path: Path, values: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    missing: list[tuple[str, str]] = []
    for key, value in values.items():
        text, found = replace_json_string(text, key, value)
        if not found:
            missing.append((key, value))
    if missing:
        stripped = text.rstrip()
        if not stripped.endswith("}"):
            raise RuntimeError(f"Invalid locale JSON shape: {path}")
        body = stripped[:-1].rstrip()
        sep = "\n" if body.endswith(",") else ",\n"
        lines = []
        for idx, (key, value) in enumerate(missing):
            comma = "," if idx < len(missing) - 1 else ""
            lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}{comma}")
        text = body + sep + "\n".join(lines) + "\n}\n"
    path.write_text(text, encoding="utf-8")
    parsed = json.loads(text)
    for key, value in values.items():
        assert parsed.get(key) == value, (path, key, parsed.get(key), value)


def main() -> None:
    template_path = ROOT / "templates" / "world_boss.html"
    template = template_path.read_text(encoding="utf-8")

    lead_start = template.index('        <p class="gc-world-boss-help-lead">')
    lead_end = template.index("</p>", lead_start) + len("</p>")
    lead = '        <p class="gc-world-boss-help-lead">{{ T("wb_help_lead", "World Bosse sind serverweite Community-Raids. Alle Spieler greifen dieselben Lebenspunkte an, bauen gemeinsam Raid-Boni auf und kämpfen um persönliche sowie Allianz-Ränge.") }}</p>'
    template = template[:lead_start] + lead + template[lead_end:]

    list_start = template.index('        <ul class="gc-world-boss-help-list">')
    list_end = template.index("        </ul>", list_start) + len("        </ul>")
    lines = ['        <ul class="gc-world-boss-help-list">']
    for key, fallback in HELP_ITEMS:
        escaped = fallback.replace('"', '&quot;')
        lines.append(f'          <li>{{{{ T("{key}", "{escaped}") }}}}</li>')
    lines.append('        </ul>')
    template = template[:list_start] + "\n".join(lines) + template[list_end:]
    template_path.write_text(template, encoding="utf-8")

    for locale, values in TRANSLATIONS.items():
        update_locale(ROOT / "locales" / f"{locale}.json", values)

    rendered = template_path.read_text(encoding="utf-8")
    for key, _ in HELP_ITEMS:
        assert f'T("{key}"' in rendered, key
    assert "10–20 Wellen solo" not in rendered
    assert "wb_help_containment" in rendered
    assert "wb_help_resonance" in rendered
    assert "wb_help_target_lock" in rendered
    assert "wb_help_last_stand" in rendered


if __name__ == "__main__":
    main()
