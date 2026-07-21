# Genesis Colonies — UML-Übersicht

Technische Architektur als UML-Diagramme (Stand: **v1.5.9.2**). Ergänzt [ARCHITECTURE.md](ARCHITECTURE.md) und [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md).

**Rendering:** Diagramme sind in [Mermaid](https://mermaid.js.org/) geschrieben. Zum Export als PNG/SVG:

- [mermaid.live](https://mermaid.live) — Code einfügen, exportieren
- VS Code / Cursor — Mermaid-Preview-Extension
- GitHub/GitLab — Mermaid wird in Markdown nativ gerendert

---

## Inhaltsverzeichnis

1. [Komponenten-Diagramm](#1-komponenten-diagramm-gesamtarchitektur)
2. [Paket-Diagramm](#2-paket-diagramm-backend-module)
3. [Klassen-Diagramm](#3-klassen-diagramm-zentrale-konzepte)
4. [Sequenz: App-Start](#4-sequenz-app-start-bootstrap)
5. [Sequenz: Live-State Polling](#5-sequenz-live-state-polling)
6. [Sequenz: Spieler-Aktion](#6-sequenz-spieler-aktion)
7. [Entity-Relationship](#7-entity-relationship-datenmodell--kern)
8. [Frontend-Shell](#8-frontend-shell-layout)
9. [Modul-Owner-Tabelle](#9-modul-owner-tabelle)
10. [PlantUML-Variante](#10-plantuml-variante)

---

## 1. Komponenten-Diagramm (Gesamtarchitektur)

```mermaid
flowchart TB
    subgraph Client["Browser (Client)"]
        Shell["templates/base.html<br/>Shell: Header, Sidebars, Dock"]
        MainJS["static/main.js<br/>GC-Namespace: PJAX, Polling, Actions"]
        ChatJS["static/js/chat.js"]
        AdminJS["static/admin.js"]
    end

    subgraph HTTP["Flask — app.py (Thin HTTP Layer)"]
        Routes["Routes & Decorators<br/>@require_login, @require_admin"]
        LiveCtx["_load_page_live_context()"]
        GameState["_build_game_state_payload()"]
    end

    subgraph Domain["game/ — Domain & Infrastructure"]
        Bootstrap["bootstrap.py"]
        Logic["logic.py"]
        LiveState["live_state.py"]
        QueueEngine["queue_engine.py"]
        Resources["resources.py"]
        Buildings["buildings.py"]
        Research["research.py"]
        Fleet["fleet.py"]
        Combat["combat.py"]
        Galaxy["galaxy.py"]
        Effects["effects/effect_resolver.py"]
        PlanetEvo["planet_evolution/"]
        Auth["auth.py"]
        Models["models.py + db.py"]
    end

    subgraph Workers["Background / Cron"]
        FleetWorker["fleet_worker.py"]
        RankingWorker["ranking_worker.py"]
        InternalCron["internal_cron.py"]
    end

    subgraph Storage["Persistenz"]
        SQLite[("SQLite WAL<br/>game/game.db")]
        Migrations["migrations/*.sql"]
    end

    Client -->|"HTML (Jinja2)<br/>JSON APIs"| HTTP
    HTTP --> Domain
    Domain --> Models
    Models --> SQLite
    Bootstrap --> Models
    Migrations --> SQLite
    InternalCron --> Workers
    Workers --> Domain
```

**Prinzip:** Der Server ist die einzige Wahrheit. `app.py` routet nur; die Logik lebt in `game/`.

---

## 2. Paket-Diagramm (Backend-Module)

```mermaid
graph TB
    app["app.py"]

    subgraph infra["Infrastruktur"]
        bootstrap
        config
        db
        models
        auth
        security
        i18n
    end

    subgraph core["Kern-Engine"]
        logic
        live_state
        queue_engine
        resources
        production_formula
        effects
    end

    subgraph gameplay["Spielmodule"]
        buildings
        research
        shipyard
        shipyard_queue
        defense
        fleet
        fleet_calc
        combat
        galaxy
        exchange
        planet_evolution
    end

    subgraph meta["Meta / Social"]
        alliance
        chat
        messages
        ranking
        support
        admin
        admin_api
    end

    app --> infra
    app --> core
    app --> gameplay
    app --> meta

    logic --> queue_engine
    logic --> resources
    logic --> buildings
    logic --> research
    buildings --> effects
    research --> effects
    fleet --> combat
    queue_engine --> buildings
    queue_engine --> research
    queue_engine --> shipyard_queue
    queue_engine --> fleet
```

---

## 3. Klassen-Diagramm (zentrale Konzepte)

Python nutzt hier vor allem **Module + Funktionen**, keine große OOP-Hierarchie. Dieses Diagramm zeigt die **logischen Owner** laut [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17.

```mermaid
classDiagram
    class FlaskApp {
        +app: Flask
        +bootstrap_application()
        +Routes: HTML + JSON
        +_load_page_live_context()
        +_build_game_state_payload()
    }

    class Bootstrap {
        +bootstrap_application()
        init_config()
        init_db()
        migrations_are_current()
    }

    class Logic {
        +refresh_player_live_state()
        +read_player_live_state_for_poll()
        +update_resources()
        +queue_build()
        +queue_research()
        +get_build_queue_status()
        +check_planet_cap_available()
    }

    class QueueEngine {
        +finish_due_work_once()
        +finish_due_work()
        +finish_planet_build_jobs()
        +finish_player_research_jobs()
        +finish_planet_shipyard_jobs()
    }

    class LiveState {
        +get_request_context_planet()
        +coerce_skip_finish()
        +global_queue_hud_for_game_state()
        +apply_action_state_diet()
    }

    class Resources {
        +update_planet_resources()
        +apply_resource_delta()
    }

    class EffectResolver {
        +resolve_production()
        +resolve_energy()
        +resolve_storage()
        +resolve_build_time()
    }

    class PlanetScope {
        +get_context_planet()
        +resolve_owned_planet_id()
    }

    class Database {
        +get_connection()
        +begin_write_transaction()
        +commit()
    }

    class GC_Client {
        +lastState
        +refreshGameState()
        +fetchGameAction()
        +applyActionState()
        +navigateTo()
        +cleanupPage()
    }

    FlaskApp --> Bootstrap : startet bei Import
    FlaskApp --> Logic : orchestriert Requests
    FlaskApp --> LiveState : baut Poll-Payload
    Logic --> QueueEngine : finish vor Mutations
    Logic --> Resources : Ressourcen-Tick
    Logic --> PlanetScope : aktiver Planet
    Resources --> EffectResolver : Formeln
    QueueEngine --> Database
    Logic --> Database
    GC_Client --> FlaskApp : GET /api/game-state, POST /api/*
```

---

## 4. Sequenz: App-Start (Bootstrap)

Beim Import von `app.py` wird `bootstrap_application()` ausgeführt.

```mermaid
sequenceDiagram
    participant Main as app.py (__main__)
    participant App as Flask app
    participant Boot as bootstrap.py
    participant Config as config.py
    participant DB as models/db
    participant Mig as migrations_util

    Main->>App: import app
    App->>Boot: bootstrap_application()
    Boot->>Config: init_config()
    Boot->>Config: validate_config()
    Boot->>DB: init_db()
    Boot->>DB: purge_stale_idempotency_global()
    Boot->>Mig: migrations_are_current()
    alt Production & pending migrations
        Mig-->>Boot: FAIL → SystemExit
    end
    Boot->>App: secret_key = get_secret_key()
    Note over App: App bereit — Routes registriert
```

---

## 5. Sequenz: Live-State Polling

Zwei Pfade — Details: [STATE_AJAX.md](STATE_AJAX.md).

```mermaid
sequenceDiagram
    participant Browser as static/main.js
    participant App as app.py
    participant Logic as logic.py
    participant QE as queue_engine.py
    participant Res as resources.py
    participant LS as live_state.py
    participant DB as SQLite

    Browser->>App: GET /api/game-state
    App->>DB: Connection öffnen
    alt Diet Poll (leicht)
        App->>Logic: read_player_live_state_for_poll()
    else Full Refresh (include_panel=1)
        App->>Logic: refresh_player_live_state()
        Logic->>QE: finish_due_work_once()
        QE->>DB: fällige Jobs abschließen
        Logic->>Res: update_planet_resources()
    end
    App->>LS: HUD + Panels bauen
    App-->>Browser: JSON { resources, queues, panels, ... }
    Browser->>Browser: applyGameStateData()
    Note over Browser: GC.lastState = Server-Wahrheit
```

---

## 6. Sequenz: Spieler-Aktion

Beispiel: Gebäude-Upgrade. Alle POST-Actions folgen dem gleichen Contract: `{ ok, state }` → `applyActionState()`.

```mermaid
sequenceDiagram
    participant Browser as static/main.js
    participant App as app.py
    participant Logic as logic.py
    participant QE as queue_engine.py
    participant Build as buildings.py
    participant DB as SQLite

    Browser->>App: POST /api/buildings/upgrade<br/>X-Request-Id (Idempotenz)
    App->>DB: BEGIN IMMEDIATE
    App->>QE: finish_due_work_once()
    App->>Build: queue_build_for_planet()
    Build->>DB: Ressourcen abziehen, Job einfügen
    App->>Logic: refresh_player_live_state()
    App->>DB: COMMIT
    App-->>Browser: { ok: true, state: {...} }
    Browser->>Browser: applyActionState(res)
    Note over Browser: Kein Full-Page-Reload (PJAX)
```

---

## 7. Entity-Relationship (Datenmodell — Kern)

Vereinfachtes ER-Diagramm der wichtigsten Tabellen. Vollständige Liste: [ARCHITECTURE.md](ARCHITECTURE.md) § Datenmodell.

```mermaid
erDiagram
    users ||--|| players : "id = id"
    players ||--o{ planets : owns
    players ||--o| planets : "active_planet_id"
    planets ||--|| planet_buildings : has
    planets ||--o{ build_queue : queues
    planets ||--o{ shipyard_queue : queues
    planets ||--o{ planet_ships : stores
    players ||--o{ research_levels : account-wide
    players ||--o{ research_queue : queues
    players ||--o{ fleet_movements : sends
    players ||--o{ fleet_presets : saves
    players ||--o| alliance_members : joins
    alliances ||--o{ alliance_members : has
    players ||--|| player_scores : ranked

    users {
        int id PK
        string username
        string password_hash
        string email
    }

    players {
        int id PK
        int active_planet_id FK
        datetime last_seen
    }

    planets {
        int id PK
        int player_id FK
        int galaxy system position
        float metal crystal fuel_cells
        bool is_homeworld
    }

    build_queue {
        int id PK
        int planet_id FK
        string building_type
        datetime finish_time
    }

    fleet_movements {
        int id PK
        int player_id FK
        string mission_type
        datetime arrival_time
    }
```

---

## 8. Frontend-Shell (Layout)

Seit GC-806: festes Dual-Sidebar-Layout. PJAX ersetzt nur `#main-content`.

```mermaid
graph TB
    subgraph Shell["templates/base.html — bleibt permanent"]
        Header["Header + Planet Switcher"]
        ResBar["Resource Bar (sticky)"]
        subgraph DualLayout[".gc-layout--dual"]
            LeftNav["Left Sidebar<br/>Gameplay-Navigation"]
            Main["#main-content<br/>PJAX ersetzt nur diesen Block"]
            RightNav["Right Sidebar<br/>Meta / Community"]
        end
        Dock["Bottom Utility Dock"]
    end

    MainJS["GC.navigateTo()"] -->|"fetch + X-PJAX"| Main
    MainJS -->|"GC.cleanupPage()"| Shell
```

---

## 9. Modul-Owner-Tabelle

Auszug aus [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17 — „Wo gehört das hin?"

| System | Owner (Modul) | Doc |
|--------|----------------|-----|
| Queues (Finish-Pass) | `game/queue_engine.py` | [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) |
| Live-State / Poll-Payload | `app.py` + `game/logic.py` + `game/live_state.py` | [STATE_AJAX.md](STATE_AJAX.md) |
| Planet Scope | `game/planet_evolution/repository.py` | [PLANET_SCOPE.md](PLANET_SCOPE.md) |
| Ressourcen / Tick | `game/resources.py` | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| Effekte / Formeln | `game/effects/effect_resolver.py` | [EFFECTS.md](EFFECTS.md) |
| Buildings / Bau-Queue | `game/buildings.py` | [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) |
| Account-Forschung | `game/research.py` | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) |
| Shipyard-Queue | `game/shipyard_queue.py`, `game/shipyard.py` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Fleet / Missionen | `game/fleet.py`, `game/fleet_calc.py` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Combat | `game/combat.py` | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| Galaxy | `game/galaxy.py` | [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) |
| Planet Evolution | `game/planet_evolution/` | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) |
| Alliance | `game/alliance.py` | [ALLIANCE_SYSTEM.md](ALLIANCE_SYSTEM.md) |

---

## 10. PlantUML-Variante

Für Tools wie IntelliJ, draw.io (PlantUML-Plugin) oder [plantuml.com](https://www.plantuml.com/plantuml):

### Komponenten

```plantuml
@startuml GC-Components
skinparam componentStyle rectangle

package "Browser" {
  [base.html Shell] as Shell
  [static/main.js GC] as MainJS
}

package "Flask app.py" {
  [Routes & Auth] as Routes
  [Live Context Builder] as LiveCtx
}

package "game/" {
  [logic.py] as Logic
  [queue_engine.py] as QE
  [live_state.py] as LS
  [buildings / research / fleet ...] as Modules
  [models.py + db.py] as DBLayer
}

database "SQLite game.db" as SQLite

Shell --> Routes : HTML
MainJS --> Routes : JSON API
Routes --> Logic
Routes --> LS
Logic --> QE
Logic --> Modules
Modules --> DBLayer
DBLayer --> SQLite
@enduml
```

### Sequenz: Game-State Poll

```plantuml
@startuml GC-GameStatePoll
actor Browser as "main.js"
participant app as "app.py"
participant logic as "logic.py"
participant qe as "queue_engine.py"
database DB as "SQLite"

Browser -> app : GET /api/game-state
app -> DB : open connection
alt full refresh
  app -> logic : refresh_player_live_state()
  logic -> qe : finish_due_work_once()
  qe -> DB : complete due jobs
  logic -> DB : update resources
else diet poll
  app -> logic : read_player_live_state_for_poll()
end
app --> Browser : JSON state payload
Browser -> Browser : applyGameStateData()
@enduml
```

### Sequenz: POST Action

```plantuml
@startuml GC-PostAction
actor Browser as "main.js"
participant app as "app.py"
participant qe as "queue_engine.py"
participant mod as "domain module"
database DB as "SQLite"

Browser -> app : POST /api/... + X-Request-Id
app -> DB : BEGIN IMMEDIATE
app -> qe : finish_due_work_once()
app -> mod : mutate (queue build, send fleet, ...)
mod -> DB : write
app -> DB : COMMIT
app --> Browser : { ok, state }
Browser -> Browser : applyActionState()
@enduml
```

---

## Goldene Regeln (Kurzreferenz)

| Regel | Umsetzung |
|-------|-----------|
| Server = Wahrheit | Keine Frontend-Game-Math; `GC.lastState` ist Cache |
| No Full Reload | `GC.navigateTo()`, `GC.reloadCurrentPage()` — kein `location.reload()` |
| Shell First | Nur `#main-content` wird per PJAX ersetzt |
| Queue Contract | Erst `finish_due_work_once()`, dann mutieren |
| Action Contract | POST → `{ ok, state }` → `applyActionState()` |
| Planet Scope | `get_context_planet()` — kein Session-Planet |
| Thin HTTP | Logik in `game/*`, nicht in `app.py` |

Siehe [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) für die vollständigen GC-000-Regeln.

---

## Verwandte Dokumentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Gesamtüberblick, Request-Flows
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Verbindliche Architekturvorgaben
- [STATE_AJAX.md](STATE_AJAX.md) — Polling, Live-State
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — Navigation, Actions
- [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) — Modul-Status aller Features
