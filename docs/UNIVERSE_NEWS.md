# Universe News — Genesis Timeline (Spieler-Patchnotes)

**Status:** ✅ GC-642 / GC-650 / GC-651 · ✅ GC-NEWS AAAA+ (Release-Publisher, kein Git im Spieler-Pfad)  
**Owner:** `game/universe_news.py` (+ Daten `game/universe_news_packs.py`)  
**Store:** `universe_news` (Audience `player` | `dev`)

---

## Prinzip

Spieler sehen **nur kuratierte** Patchnotes (`audience=player`).  
Git-Commits sind **kein** Spieler-Content. `CHANGELOG.md` und Git-Import sind Seed/Dev-Backfill (Dev-Historie, **Deutsch**).

**Locale:** DB speichert kanonisches DE für kuratierte Releases. Read-Path (`_maybe_localize_entry`) overlayt Title/Body aus `universe_news_packs` für `source_ref=release:…` gemäß `current_locale()` (Fallback en→de). World-Boss-EVENT-News bleiben im bestehenden World-Boss-Localize. Admin-Freitext ohne Pack bleibt gespeicherter Text.

| Surface | Quelle |
|---------|--------|
| `/news` Genesis Timeline | DB player rows → `build_player_timeline` (**ohne** EVENT, **ohne** git/dev-stream; neuestes Major zuerst) |
| Whats-New Modal | Latest **major** player version highlights |
| Sidebar Release-Chip | `sidebar_release_nav` → `/news#version-…` (+ PJAX Hash-Scroll) |
| `/devlog` | Admin-only; git-imported `audience=dev` / DEVELOPMENT stream |
| Live Banner | One `is_banner=1` player row + MOTD flag (darf EVENT sein) |

**EVENT vs Patchnotes:** World Boss / Piraten (`create_news(..., category="EVENT")`) bleiben in der DB und dürfen Live-Banner/MOTD speisen. Sie erscheinen **nicht** in der Spieler-Patchnotes-Timeline und nicht in Whats-New Highlights.

**Sortierung:** Innerhalb eines Jahres: neuestes Release oben (`published_at` des Majors, dann Versionsnummer). Die DEVELOPMENT-/Git-Stream-Karten gehören nur auf `/devlog`.

---

## Publish-Flow (Admin)

Admin → Server → Universums-News → **Release veröffentlichen**:

1. `version_tag`, Label, Datum, Intro
2. Textareas **Neu / Verbessert / Behoben** (eine Zeile = ein Bullet)
3. `POST /api/admin/universe-news/publish-release` → `publish_release_pack`
4. Reject if version already has player rows (`version_exists`) — edit existing entries

Einzelmeldungen / Entwürfe bleiben über das Compose-Form möglich.

---

## Boot seed

`bootstrap_application` → `ensure_player_news_seeded()`:

1. `ensure_changelog_seeded` — wenn keine Major Releases: Import `CHANGELOG.md`
2. `ensure_v09_release_seeded` — kuratiertes v0.9 Pack, wenn `v0.9` fehlt
3. `ensure_v091_release_seeded` — kuratiertes v0.9.1 Pack (EFFSTAT / Story-i18n), wenn `v0.9.1` fehlt
4. `ensure_v092_release_seeded` — kuratiertes v0.9.2 Pack (LiveOps Catch-up + Kolonie-Stage), wenn `v0.9.2` fehlt

Idempotent. Kein Runtime-Git.

---

## Verboten

- `repository_history_audit()` / `git log` auf `/news` oder Whats-New
- Commit-Subjects als Spieler-Copy
- Zweites News-/Changelog-Modul parallel zu `universe_news`

## Erlaubt

- Admin `GET …/repository-audit` und Git-Import als **Dev/Offline-Backfill** (braucht `.git`)
- Event-Systeme (`world_boss`, pirates) → `create_news(..., category="EVENT")` für Banner/Live — **nicht** für Patchnotes-Timeline

---

## APIs

| Route | Role |
|-------|------|
| `GET /news` | Player timeline (patchnotes only) |
| `GET /api/news` | JSON payload (`timeline`, `current_release.anchor_id`) |
| `GET /api/news/whats-new` | Major highlights for modal |
| `POST /api/admin/universe-news/publish-release` | Curated release pack |
| `POST /api/admin/universe-news/import-changelog` | CHANGELOG.md seed |
| `POST /api/admin/universe-news/import-git-history` | Dev only |
| `GET /api/admin/universe-news/repository-audit` | Admin diagnostics |

---

## Tests

`tests/test_universe_news.py`, `tests/test_universe_news_timeline.py` — create/list, publish-release idempotency, no git in `news_page_payload`, v0.9 / v0.9.1 / v0.9.2 seed, release pack locale overlay, indexed `source_ref`, whats-new major, EVENT excluded from timeline but banner-capable.
