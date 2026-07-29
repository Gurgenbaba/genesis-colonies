# Genesis Colonies — Security

Sicherheitsmodell, bekannte Limitierungen und Operator-Checkliste für Genesis Colonies v1.5.1.

> Genesis Colonies ist **Early Alpha**. Dieses Dokument beschreibt den **aktuellen** Stand — nicht einen zertifizierten Security-Audit.

---

## Threat Model (vereinfacht)

| Bedrohung | Relevanz | Mitigation (aktuell) |
|-----------|----------|----------------------|
| Session-Hijacking | Hoch (öffentlicher Server) | `SECRET_KEY`, HTTPS, HttpOnly + SameSite=Lax + Secure (Prod) |
| Credential Theft (DB-Leak) | Hoch | Argon2id KDF; Legacy-Hashes werden bei Login migriert |
| Double-Submit / Race auf Queues | Mittel | `BEGIN IMMEDIATE`, Idempotency-Store, Tests |
| Privilege Escalation | Hoch | `@require_admin`, `@require_admin_api`, Ban-Check |
| Admin-Missbrauch | Mittel | Audit-Log, Confirm-Phrases, separate JSON-Guards |
| SQL Injection | Mittel | Parametrisierte Queries (`?` Placeholders) |
| CSRF auf JSON-APIs | Mittel | Same-Site-Session; keine expliziten CSRF-Tokens auf APIs |
| CSRF auf HTML-Forms | Mittel | Session-CSRF-Token auf Auth-Forms; Admin-Panel noch ohne Token |
| Information Disclosure | Niedrig | `/health` öffentlich (keine Secrets); Stack-Traces nur bei `FLASK_DEBUG=1` |
| Denial of Service | Mittel | Gunicorn-Timeout; Login/Register Rate-Limits (in-process) |

---

## Authentifizierung

### Session-Modell

- Flask-Session mit `SECRET_KEY` aus `.env`
- `session["user_id"]` = Player-ID (`users.id == players.id`)
- Login: `game/auth.py` → `login_user()` setzt Session nach `verify_user()`

### Passwort-Hashing

Neue Passwörter: **Argon2id** via Werkzeug + `argon2-cffi` (`game/models.py`).

| Aspekt | Status |
|--------|--------|
| KDF | ✅ Argon2id (`$argon2id$…`) |
| Salt | ✅ pro Hash (Werkzeug) |
| Legacy SHA-256 | ✅ Verifizierung + Re-Hash bei Login |
| Legacy PBKDF2 | ✅ Verifizierung + Re-Hash bei Login |
| Timing-safe compare | ✅ Werkzeug `check_password_hash` |

```python
# game/models.py — argon2-cffi PasswordHasher (Argon2id)
```

### Registrierung

- Mindestlänge Username 3, Passwort 4 (nur Basis-Validierung)
- E-Mail-Verifikation aktiv (`game/account_email.py`)
- Rate-Limit Register: **5 / Stunde / IP** (in-process, `game/security.py`)
- Rate-Limit Login: **10 / 15 Min / IP**
- CSRF-Token auf Auth-HTML-Forms (Login, Register, Forgot/Reset Password)

### Ban-System

- `players.banned_until > now` → Session wird geleert, Redirect `/login`
- Admin-API und HTML-Routes prüfen Ban vor Handler-Ausführung

---

## Autorisierung

| Guard | Verhalten |
|-------|-----------|
| `@require_login` | Redirect → `/login`; setzt `g.player` |
| `@require_admin` | Redirect → `/overview` + Flash bei Nicht-Admin |
| `@require_admin_api` | JSON `401` / `403`; setzt `g.admin_user` |

Admin-Status: `users.is_admin OR players.is_admin` (vereinheitlicht als `is_admin`).

**API vs. HTML:** Admin-JSON-Endpunkte geben niemals HTML-Redirects zurück — wichtig für `fetch()`-Clients.

---

## Idempotenz & Race Safety

### Idempotency-Store

- Tabelle: `action_idempotency` (Migration `008`)
- TTL: **120 Sekunden** (`_IDEMPOTENCY_TTL_SEC`)
- Key: `(user_id, request_id)`
- Purge: Bootstrap + bei Save pro User

Client sendet `request_id` (UUID) oder Header `X-Request-Id`. Identischer Request innerhalb TTL liefert gecachte JSON-Antwort.

### Queue-Transaktionen

SQLite-Schreibzugriffe für Queues:

```
BEGIN IMMEDIATE
  → finish_due_* (in derselben Tx)
  → Validierung + INSERT
COMMIT
```

`tests/test_race_conditions.py` verifiziert parallele Enqueues gegen Queue-Limit.

---

## Admin Control Center

### Audit Trail

Jede relevante Admin-API-Aktion schreibt nach `admin_audit_log`:

- `admin_id`, `action`, `target_type`, `target_id`
- `payload_json` (max. ~8000 Zeichen)
- `ip`, `user_agent`, `created_at`

Abfrage: `GET /api/admin/audit-log?action=...&limit=...`

### Destruktive Aktionen

Erfordern exakte `confirm`-Phrase (siehe [ARCHITECTURE.md](ARCHITECTURE.md#admin-control-center)). Falsche Phrase → `ok: false` ohne Seiteneffekt.

### Risiken

| Risiko | Hinweis |
|--------|---------|
| Kompromittierte Admin-Session | Vollzugriff auf Universe, Queues, Bans |
| `RUN MIGRATIONS` via API | Nur mit Confirm; trotzdem privilegiert |
| Legacy `/admin/wipe` | Universum-Reset — in Production extrem gefährlich |

**Operator:** Admin-Passwörter stark halten; Admin-Accounts minimieren; Audit-Log regelmäßig prüfen.

---

## Konfiguration & Production Guards

`game/config.py` + `game/bootstrap.py`:

| Bedingung | Production-Verhalten |
|-----------|---------------------|
| `SECRET_KEY` leer oder in `INSECURE_SECRET_KEYS` | `validate_config` → Exit |
| `FLASK_DEBUG=1` bei `APP_ENV=production` | Exit (auch `python app.py`) |
| Pending Migrations | Exit (außer `GC_SKIP_MIGRATION_CHECK`) |

Insecure Defaults (blockiert in Production):

```
change-me-dev-secret, change-me, dev, development, secret, admin, test, changeme
```

### Empfohlene `.env` (Production)

```env
APP_ENV=production
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=<64-char-random-hex>
# Local / non-volume: GC_DB_PATH=game/game.db
# Railway volume: GC_DB_PATH=/data/game.db  (see docs/RAILWAY_OPERATOR.md)
GC_DB_PATH=/data/game.db
```

Secret generieren:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Netzwerk & Deployment

| Maßnahme | Status |
|----------|--------|
| TLS (HTTPS) | Operator — nginx/Caddy vor Gunicorn |
| `SECRET_KEY` per Orchestrator | Docker: `${SECRET_KEY}` in compose |
| DB-Datei-Berechtigungen | Nur App-User lesen/schreiben |
| Debug aus | `FLASK_DEBUG=0` |
| Health-Monitoring | `/healthz` (liveness) + `/health` (readiness) ohne Auth — keine Credentials in Response |

### Docker

- Build-Time-`SECRET_KEY` im Dockerfile ist nur für `install.py` — **Runtime-Override Pflicht**
- Volume `gc_data` für persistente DB

### Headers (App + empfohlen am Reverse Proxy)

Flask `after_request` setzt:

```
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: strict-origin-when-cross-origin
Strict-Transport-Security: … (wenn SESSION_COOKIE_SECURE / HTTPS)
```

Zusätzlich am Proxy: TLS-Terminierung.

---

## Datenbank

| Thema | Detail |
|-------|--------|
| Backend | SQLite WAL, `foreign_keys=ON`, `busy_timeout` |
| Injection | ORM-freie, aber parametrisierte `execute()` |
| Backups | `game/game.db` regelmäßig kopieren (Datei-konsistent bei WAL: checkpoint oder App-Stop) |
| Multi-Instance | SQLite nicht für horizontale Skalierung geeignet — Postgres-Roadmap |

---

## Frontend-Security

| Thema | Detail |
|-------|--------|
| XSS | Jinja2 Auto-Escape für SSR; API-JSON wird per `textContent` gesetzt (kein `innerHTML` für User-Input in Kernpfaden) |
| Auth-Polling | Kein State-Fetch auf Auth-Seiten |
| Offline-Markierung | UI zeigt Verbindungsstatus, sendet keine sensiblen Daten |

Admin-Panel rendert dynamische Tabellen aus API — Admin-only, trotzdem vertrauenswürdige Datenquelle.

---

## Bekannte Limitierungen (v1.5.1)

1. **CSRF auf Admin-HTML-Forms** — `admin_panel.html` POST noch ohne Token
2. **Keine CSRF-Tokens** auf JSON-APIs — Same-Origin-Session + SameSite=Lax
3. **Keine 2FA** für Admin
4. **Öffentliches `/health`** — akzeptabel; keine Secrets, aber Versions-Leak
5. **SQLite Single-Writer** — kein Cluster-Betrieb
6. **Rate-Limits in-process** — pro Worker, nicht clusterweit (Redis-Roadmap)

---

## Security-Roadmap

| Priorität | Maßnahme |
|-----------|----------|
| P0 | Passwort-KDF (argon2id) + Migration bei Login | ✅ GC-SEC-P0 |
| P0 | Rate-Limiting Login/Register | ✅ GC-SEC-P0 |
| P1 | CSRF für HTML-Forms; optional API-Token für Admin | ⚠️ Auth-Forms ✅; Admin offen |
| P1 | Session-Cookie: `Secure`, `HttpOnly`, `SameSite=Lax` explizit | ✅ GC-SEC-P0 |
| P2 | Security-Headers in Flask `after_request` oder zentral im Proxy | ✅ GC-SEC-P0 (App) |
| P2 | Strukturiertes Security-Logging (failed logins) |
| P3 | Postgres + Row-Locks für Multi-Worker unter Last |

---

## Incident Response (Operator)

1. Kompromittierte Admin-Session → Passwort ändern, Session invalidieren (App-Neustart / neuer `SECRET_KEY` invalidiert alle Sessions)
2. Verdächtige Audit-Einträge → `GET /api/admin/audit-log` exportieren
3. DB-Integrität → Backup einspielen, `python migrate.py`, `/health` prüfen
4. Offener Wipe/Migration → Audit-Log + Confirm-Phrases prüfen

---

## Verwandte Dokumente

- [LICENSE](../LICENSE) — Nutzungsbeschränkungen
- [ARCHITECTURE.md](ARCHITECTURE.md) — Auth-Guards, Idempotenz-Flows
- [CONTRIBUTING.md](CONTRIBUTING.md) — Security-relevante Tests
