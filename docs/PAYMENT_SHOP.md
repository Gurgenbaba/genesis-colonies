# EPIC-23 — Payment / Shop (Cash Grab MVP)

> Convenience-Shop: Season Pass Premium + Timekeeper-/Booster-/Container-Packs.  
> Provider: **PayPal** (default). Stripe optional via `SHOP_ENABLE_STRIPE=1`. Keine Hard-Currency-Wallet, kein Pay-to-Win.

## Status

| Phase | Inhalt | Tickets | Status |
|-------|--------|---------|--------|
| 0 | Master-Doc + Owner-Registrierung | GC-2300 | ✅ |
| 1 | Schema + Order skeleton | GC-2301 | ✅ |
| 2 | Catalog + Fulfill | GC-2302 | ✅ |
| 3 | Stripe Checkout + Webhook | GC-2303 | ✅ |
| 4 | PayPal Checkout + Webhook | GC-2304 | ✅ |
| 5 | Shop UI + Premium Buy-CTA | GC-2305 | ✅ |
| 6 | Contract tests + GAME_RULES | GC-2306 | ✅ |
| 7 | Free-Baseline Value Balance | GC-2310…2313 | ✅ |
| 8 | PayPal Live go-live | Ops | ✅ |
| 9 | Creator Promo Codes (Rabatt + Kommission + Referral-Bridge + Dashboard) | GC-Creator | ✅ |
| 10 | Campaign / Event Discount Codes (nur Shop-Rabatt) | GC-Campaign | ✅ |

## Creator Partner Program

Owner: `game/shop_promos.py` — Vanity-Code für Shop-Rabatt/Kommission **und** Referral-Attribution (Register/nachträglich via Bridge in `game/referrals.py`).

- Default: 10% Rabatt + 10% Kommission vom **Listenpreis**; Codes laufen nie ab.
- Ledger: `held` → `available` erst wenn Käufer **qualifiziert** ist:
  - Account-Alter ≥ 7 Tage (`CREATOR_COMMISSION_HOLD_SEC`)
  - `last_seen` innerhalb 7 Tage (`CREATOR_BUYER_ACTIVE_WINDOW_SEC`)
  - `score_total` ≥ 100 (`CREATOR_MIN_BUYER_SCORE`)
  - nicht gebannt
  - danach Admin-Payout (Min 25 €)
- Partner-KPIs (Admin + `/creator`): Registrierungen, Active 7d/30d, Spenden, Umsatz, Balance, Status.
- Surfaces: `/shop` Promo-Feld, `/r/<CODE>`, `/creator` Dashboard, Admin Tab **Creator Promos**.
- Providers chargen `order.amount_cents` (nicht Catalog-Preis).
- Kein Parallel-Tracking: Spielerzählung bleibt `player_referrals`.

## Campaign / Event Codes

Gleicher Owner (`shop_promos`, `kind=campaign`): Admin legt Discount-Codes an (z. B. Verlosung). Einlösen im Premium-Shop → Rabatt, **keine** Creator-Kommission, **kein** Referral-Bridge. Optional `max_redemptions`; sonst unbegrenzt bis `active=0`.

## Philosophy

- **F2P first:** Free Track / Login bleiben wertvoll; Shop verkauft Convenience.
- **Erlaubt:** Timekeeper-Sekunden, meta-only Container, %/Time-Boosters, Season-Pass-Entitlement, **Name-Styles / Identity** (ala-carte über Shop → `playercard.unlock_*`).
- **Verboten:** Schiffe, Defense, Rohstoff-Stacks; Gem-Wallet; parallele Unlock-/Grant-Engines; Frontend-Preis-Math.
- **Unlock:** `battle_pass.unlock_premium` → `premium_entitlements`; Cosmetics → `playercard.unlock_name_style` / `unlock_title_flair` (kein zweites Cosmetics-Modul).

## Free-Baseline (Messlatte)

Aktiver Free-Spieler (Login + Directives EV, ~30 Tage) — **kein Free-Nerf**:

| Metrik | Free / Monat (ca.) |
|--------|-------------------:|
| Flexibles Timekeeper | **~2,6 h** (Login; BP Free ~1 h/Season extra) |
| Domain Build-Skip (Boosters) | **~140–150 h** |
| Domain Research-Skip | **~135–145 h** |

Free ist reich an domain-locked Boosters, arm an flexiblem TK.

## Value-Anker (Paid muss sich lohnen)

1. Free-Monat = Benchmark „Geduld“, nicht „Armut“.
2. Impulse (€0,99–2,99) ≥ **1–2 Wochen Free-TK** *oder* klarer High-Tier-Vorsprung.
3. **Season Pass = bestes Season-/Long-term-€/Value** (Anker **4,99 €**, FEATURED-Lane).
4. **Impulse Trio (GC-2314 Goldilocks):** Starter (€2,99) = Decoy · **Genesis Accelerator (€4,99) = BEST VALUE / Primary Conversion** · Hyperdrive Protocol (€6,99) = CRAZY Upper-Anchor + TK-L-Killer. Shop rendert sie als `Commander Favorites`-Bucht (nicht flaches Grid).
5. Commander (~10 €) ≥ viel TK + High-Tier-Mix — nicht „teurer Login-Monat“.
6. Domain-Booster-Pack nur wenn Yield **≥ ~2× Login-Monats-Skip** (~140 h Build).
7. Paid verkauft, was Free **nicht** drip’t (TK, Season-FOMO, High-Tier-Sofortmacht).

## Owners (CORE_ARCHITECTURE §17)

| System | Owner | Notes |
|--------|-------|-------|
| Shop Catalog + Fulfill | `game/shop.py` | SKUs, Orders, Fulfillment |
| Creator Promos + Ledger | `game/shop_promos.py` | Codes, Pricing, Funnel, Commission |
| Payment Providers | `game/payment_providers.py` | Stripe/PayPal Session + Webhook verify |
| Premium Entitlement | `game/premium_entitlements.py` | Flag Single Source |
| Battle Pass Unlock | `game/battle_pass.py` | `unlock_premium(source=…)` |

**Grant path (canonical):** `unlock_premium` / `grant_inventory_item` / `timekeeper.credit` / `grant_companion_slot` — keine zweite Loot-Engine.

## Catalog (`CATALOG_VERSION = 7`)

| SKU | Kind | Price (EUR) | Fulfill |
|-----|------|-------------|---------|
| `season_pass_current` | entitlement | 4,99 | `unlock_premium` aktive Season |
| `tk_pack_s` | timekeeper | 0,99 | **6 h** TK |
| `tk_pack_m` | timekeeper | 2,99 | **24 h** TK |
| `tk_pack_l` | timekeeper | 5,99 | **72 h** TK |
| `booster_pack_starter` | inventory_bundle | 2,99 | Build/Research **24h ×6** + **6h ×8** + prod_50 ×4 (≥ ~176 h/Domain) — Impulse-Trio Decoy |
| `genesis_accelerator_pack` | inventory_bundle | 4,99 | **48 h** TK + Build/Research 24h ×8 + 6h ×6 + epic×2 + mythic×1 — Impulse BEST VALUE |
| `hyperdrive_protocol_pack` | inventory_bundle | 6,99 | **72 h** TK + Build/Research 24h ×10 + 6h ×8 + epic×3 + mythic×2 + ancient×1 — Impulse CRAZY / TK-L-Alternative |
| `container_pack_rare` | inventory_bundle | 2,99 | rare×8 + epic×4 + mythic×2 + relic×1 |
| `commander_supply_pack` | inventory_bundle | 9,99 | **48 h** TK + Build/Research 24h ×6 + prod_100 ×3 + epic×4 + mythic×3 + ancient×2 + relic×2 |
| `titan_slot_plus` | inventory_bundle | 2,99 | `grant_companion_slot` (+1 capacity, max 4); checkout blocked at max |

`ensure_catalog_seeded` **upsertet** Preise/Payloads aus Code (Server-Truth). Companion capacity owner: `game/world_boss_companions.py`.

UI-Badges (`SHOP_SKU_UI_BADGES` → `display.ui_badges`): Accelerator = `new` + `best_value`; Hyperdrive = `new` + `crazy`. Season Pass bleibt `FEATURED` (eigene Lane).
## Schema

- `shop_products` — sku, kind, price_cents, currency, active, payload_json, sort_order
- `shop_orders` — player_id, sku, provider, session/payment ids, status machine
- `shop_payment_events` — provider + event_id UNIQUE (webhook idempotency)

Statuses: `pending` → `paid` → `fulfilled` | `failed` | `refunded`

## API

| Route | Auth | Zweck |
|-------|------|-------|
| `GET /shop` | login | Shop page |
| `GET /api/shop/catalog` | login | Active products |
| `POST /api/shop/checkout` | login | `{ sku, provider }` → `checkout_url` |
| `GET /shop/return` | login | Post-checkout receipt (`build_shop_return_payload`: lines/titles/status; no client trust) |
| `POST /api/webhooks/stripe` | signature | Fulfill |
| `POST /api/webhooks/paypal` | signature | Fulfill |

Kill-switch: `SHOP_ENABLED=0` → checkout `shop_disabled`.

## Flow

1. Client `POST /api/shop/checkout` with `sku` + `provider` (`stripe`|`paypal`).
2. Server creates `shop_orders` row `pending`, opens provider Checkout.
3. Provider webhook verifies signature → `mark_paid` → `fulfill_order` once.
4. Season Pass: `unlock_premium(..., source=provider)`. Packs: inventory/TK grants.
5. Already owned Season Pass: fulfill as `already_owned` (no double entitlement); checkout may reject early.

## Config

- `SHOP_ENABLED`, `SHOP_SUCCESS_URL`, `SHOP_CANCEL_URL`
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`
- `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_MODE`

## Ops — Payment live schalten (PayPal-first)

**Wichtig:** Wir nutzen die **PayPal REST Checkout API** (`developer.paypal.com`),  
**nicht** die klassischen Verkäufer-Tools „PayPal-Buttons“ / IPN aus dem PayPal-Business-Menü.

Fulfillment: Webhook **oder** Browser-Return (`/shop/return`) capturt und schreibt die Belohnung gut.

### Pflicht-Env

| Variable | Wert |
|----------|------|
| `PUBLIC_BASE_URL` | `https://www.genesis-colonies.de` |
| `SHOP_ENABLED` | `1` |
| `PAYPAL_CLIENT_ID` | Client ID (**ohne** `#` am Zeilenanfang) |
| `PAYPAL_CLIENT_SECRET` | **Secret** (anders als Client ID — in der App auf „Show“ klicken) |
| `PAYPAL_WEBHOOK_ID` | Webhook-ID (empfohlen; Return-Capture funktioniert auch ohne) |
| `PAYPAL_MODE` | `sandbox` → später `live` |

Stripe bleibt aus, solange `SHOP_ENABLE_STRIPE` nicht `1` ist.

### PayPal Setup (Sandbox → Live)

1. Öffne [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/applications) (mit PayPal-Konto einloggen).
2. **Apps & Credentials** → **Sandbox** → **Create App** (z.B. `Genesis Colonies Shop`).
3. Kopiere **Client ID** + **Secret** → `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`.
4. In der App → **Webhooks** → Add:
   - URL: `https://www.genesis-colonies.de/api/webhooks/paypal`
   - Events: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`
   - Webhook ID → `PAYPAL_WEBHOOK_ID`
5. `.env` / Railway setzen, Redeploy, `/shop` öffnen → Button **Mit PayPal bezahlen**.
6. **Go-Live (echte Käufe / echtes PayPal-Login):**
   - developer.paypal.com → **Apps & Credentials** → Tab **Live** (nicht Sandbox)
   - Live-App anlegen oder vorhandene nutzen → Live **Client ID** + **Secret**
   - Unter der Live-App Webhook anlegen: `https://www.genesis-colonies.de/api/webhooks/paypal`
   - Railway + `.env`: Live-Keys, Live-`PAYPAL_WEBHOOK_ID`, **`PAYPAL_MODE=live`**
   - Sandbox-Keys funktionieren nicht mit Live-Login (nur „neues Konto erstellen“)

### Optional Stripe

Nur wenn später gewünscht: `SHOP_ENABLE_STRIPE=1` + `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`  
Webhook: `…/api/webhooks/stripe` Event `checkout.session.completed`.

### Lokal / Dev ohne PayPal

`SHOP_TEST_PROVIDER=1` → sofortiges Fulfill ohne Provider (nur Dev).

### Checkliste Go-Live

1. Migration `113` applied (`python migrate.py`)
2. PayPal-Keys + Webhook auf Railway
3. `SHOP_ENABLED=1`, Redeploy
5. `/shop` zeigt PayPal-Button (nur über `PUBLIC_BASE_URL`-Host bei `PAYPAL_MODE=live`)
6. Kauf → Order `fulfilled`
7. Orphan-Recovery: `/shop/return?token=<PAYPAL_ORDER_ID>` gutschreibt COMPLETED-Zahlungen auch ohne lokale Order-Zeile

## Non-goals (MVP+)

- Gem wallet, subscriptions, mobile IAP, auto refund-revoke, resource/ship shop.
- Avatar-Frames / Fleet-Skins (später).
- Free Login/Directives nerfen (Paid wird wertiger, Free bleibt stark).

## Shopping Cart (Multi-SKU)

Session cart (`session["shop_cart"]`) — no parallel checkout owner.

| Surface | Contract |
|---------|----------|
| `GET /api/shop/cart` | `{ ok, cart: { items, list_cents, paid_cents, promo? } }` |
| `POST /api/shop/cart/add` | `{ sku, qty? }` → merge into session |
| `POST /api/shop/cart/update` | `{ sku, qty }` (`qty=0` removes) |
| `POST /api/shop/checkout` | Instant: `{ sku, provider, … }` · Cart: `{ from_cart: true, provider, … }` |

- One PayPal/Stripe payment per cart order; `shop_orders.items_json` holds lines; `sku` = first line (legacy).
- One promo applies to **sum(list_cents)** once (`max_redemptions` counts orders, not lines).
- UI: „In den Warenkorb“ + cart panel; legal ack above catalog still required.

## Legal surfaces (digital goods)

Owner: `game/legal_panel.py` — Imprint, Privacy, Terms, Withdrawal.

| Surface | Notes |
|---------|--------|
| `GET /legal` (+ `/legal/<doc>`) | Public, no login — provider block always visible |
| Ingame special window `imprint` | Same docs + contact-form CTA (Support) |
| Auth/Landing footers | Links to `/legal` |
| Checkout | Client Doppel-Ack **über dem Katalog** (vor PayPal-CTAs); API `legal_ack` + `legal_text_version` stored on `shop_orders.metadata_json`. Ungültiger Promo-Code blockiert den Kauf nicht — Checkout droppt ihn und startet zum Listenpreis (`promo_dropped`). Bei externem Provider-Redirect (`checkout_url`) wird **kein** heavy `_build_game_state_payload` gebaut — sonst kann PayPal nach Order-Create an State/Timeout scheitern.
 |

**Policy:** Virtual goods credit immediately after payment. After § 356 Abs. 5 acknowledgement + fulfillment: no voluntary refund. Exception: technical non-delivery → re-grant or provider refund (`billing` support category).

Privacy / retention ops: [PRIVACY_OPS.md](PRIVACY_OPS.md).

## Identity Cosmetics (Catalog v5 — Impulse)

| SKU | Kind | Preis | Grant |
|-----|------|------:|-------|
| `name_style_ash/signal/etched` | `cosmetic_unlock` | **0,99** | `unlock_name_style` |
| `name_style_relic` | `cosmetic_unlock` | **1,49** | `unlock_name_style` |
| `name_style_imperial/plasma/void` | `cosmetic_unlock` | **1,99** | `unlock_name_style` |
| `identity_pack_signal` | `cosmetic_unlock` | **2,49** | signal + etched + flair etched |

Catchy Impulse-Preise (unter 3 €). Admin: alle Styles/Themes frei.

### Identity Shell — woran hängt UI-Farbe und Aura?

| Signal | Quelle | Wirkung |
|--------|--------|---------|
| **UI-Farbe** | Equipped **PlayerCard Theme** (`player_cards.theme`) | Header, Nav, Panels, Buttons, Landscape-Wash, **Page Tabs** (`.gc-page-tabs` / Active via `--gc-neon-cyan`). Attribut: `body[data-identity-theme]` |
| **UI-Aura (Prestige-FX)** | Equipped **PlayerCard Aura** (`player_cards.aura_key`) | Glow/Rim auf Shell (Header, Sidebar, Panels, Nav). Attribut: `body[data-identity-aura]` |
| **Name-Style** | Equipped `player_cards.name_style` (Shop-Unlock) | Nur sichtbarer Name überall: Galaxy (Orbit+Inspector), Chat, Ranking, Alliance, HoF, Records, World Boss, Auction, Fleet-Preview, Combat-Side-Cards. **Keine** UI-Farbe/Aura. Auch bei privatem Profil. Render: `player_name_link` (SSR) / `GC.playerNameHtml` (JS). |
| Title-Flair | Equipped Card-Feld | Nur PlayerCard-Ansicht |

### Social Identity Render Contract

Jeder fremde Commander-Name in Multiplayer-Surfaces nutzt denselben Markup-Vertrag:

- SSR: `player_name_link(player_id, name, …)` in `app.py`
- JS: `GC.playerNameHtml({ id, name, nameStyle, enableCard, extraClass })`
- Markup: `.gc-player-name` + `data-player-id` + `data-name-style` (+ optional `data-player-card`)
- Batch-Lookup: `playercard.map_equipped_name_styles(ids)`
- Owner: `game/playercard.py` — kein zweites Cosmetics-Modul

Identity Shell (Theme/Aura am eigenen Chrome) bleibt owner-only; Theme/Aura auf der öffentlichen PlayerCard sind für andere sichtbar.

Server-Owner: `game/playercard.get_equipped_identity()` → Context `IDENTITY_THEME` + `IDENTITY_AURA` → `templates/base.html`. Live-Preview im PlayerCard-Editor setzt beide Attribute clientseitig.

**Nicht:** Name-Style, Title-Flair oder Shop-SKU allein.

Themes/Auras freischalten: Basis-Themes immer frei; Season-Themes/Auras via Battle Pass; Admin = alle.

## Related

- [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md) — EPIC-22 entitlement hook
- [GAME_RULES.md](GAME_RULES.md) §3.3a — official premium policy
- [GENESIS_STORY_OPS.md](GENESIS_STORY_OPS.md) — **Free Shop** (Ark-Token) ist Story-Owner auf `/shop` Tab, **nicht** Teil des EUR-Catalogs in `game/shop.py`

---

## Player Article

```yaml
---
codex_id: shop_identity
band: III
difficulty: beginner
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - shop_view
related_codex:
  - liveops_retention
  - story_ops
  - titans
  - inventory
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: shop_view
teaser_key: codex_unlock_shop_identity_teaser
---
```

## Quick Help

Der **Shop** unter `/shop` verkauft Convenience und **Identity**: Season Pass, Timekeeper-Packs, Booster/Container — plus Name-Styles. Theme und Aura formen deine UI-Shell.

## Summary

Payment (PayPal, optional Stripe) erfüllt nur erlaubte SKUs: Premium-Entitlement, Timekeeper, Meta-Container, Booster-Bundles, Titan-Slot, Cosmetics. **Kein** Rohstoff-, Schiff- oder Defense-Shop. Die **Identity Shell** trennt Signale: ausgerüstetes PlayerCard-**Theme** färbt Chrome/UI; **Aura** legt Prestige-Glow; **Name-Style** stylt nur den sichtbaren Namen in Galaxie, Chat, Ranking usw. Free Shop (Ark-Token) ist ein eigener Tab — Story-Owner, nicht EUR-Katalog.

## Why

Paid beschleunigt Geduld und Ausdruck, nicht den Combat-Sieg. Identity macht Commander in Multiplayer-Surfaces wiedererkennbar, ohne zweite Cosmetics-Engine.

## How it works

- Katalog auf `/shop` → Checkout → Provider → Webhook/Return fulfillment (idempotent).
- Season Pass schreibt dasselbe Premium-Flag wie LiveOps.
- Cosmetics freischalten und in der PlayerCard ausrüsten.
- Theme/Aura wirken auf deinen Shell; Name-Style auf Namenslinks überall.
- Rechtliche Hinweise und Doppel-Ack vor dem Kauf; virtuelle Güter nach Fulfillment.

## Related Systems

- liveops_retention
- story_ops
- titans
- inventory

## Commander Tips

- Free-Baseline (Login, Directives, BP Free) zuerst ausschöpfen — Paid ist Impuls, kein Pflichtkauf.
- Name-Style ist sozial sichtbar; Theme/Aura vor allem dein Chrome.
- Ark-Token-Tab ≠ EUR-Tab — Währungen nicht mischen.

## FAQ

**Kann ich Ferronit kaufen?**
Nein. Shop und Loot bleiben meta-only für Paid/Convenience.

**Warum ändert mein Name-Style nicht die UI-Farbe?**
Absicht: Name-Style ≠ Theme. Farbe kommt vom ausgerüsteten Theme.

**Was ist der Free Shop?**
Ark-Token-Einlösung (Story/Titans) auf dem Shop-Tab — ohne Echtgeld.

## Discord Summary

**Shop & Identity**

`/shop`: Season Pass, TK, Meta-Packs, Cosmetics. Theme/Aura = Shell; Name-Style = Name only. Kein Resource/Ship-Shop. Free Shop = Ark-Token.
