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

## Philosophy

- **F2P first:** Free Track / Login bleiben wertvoll; Shop verkauft Convenience.
- **Erlaubt:** Timekeeper-Sekunden, meta-only Container, %/Time-Boosters, Season-Pass-Entitlement (Cosmetics/QoL über BP Premium Track).
- **Verboten:** Schiffe, Defense, Rohstoff-Stacks; Gem-Wallet; parallele Unlock-/Grant-Engines; Frontend-Preis-Math.
- **Unlock:** Nur `battle_pass.unlock_premium` → `premium_entitlements.grant_entitlement` (`source=stripe|paypal`).

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
3. **Season Pass = bestes €/Value** (Anker **4,99 €**).
4. Commander (~10 €) ≥ viel TK + High-Tier-Mix — nicht „teurer Login-Monat“.
5. Domain-Booster-Pack nur wenn Yield **≥ ~2× Login-Monats-Skip** (~140 h Build).
6. Paid verkauft, was Free **nicht** drip’t (TK, Season-FOMO, High-Tier-Sofortmacht).

## Owners (CORE_ARCHITECTURE §17)

| System | Owner | Notes |
|--------|-------|-------|
| Shop Catalog + Fulfill | `game/shop.py` | SKUs, Orders, Fulfillment |
| Payment Providers | `game/payment_providers.py` | Stripe/PayPal Session + Webhook verify |
| Premium Entitlement | `game/premium_entitlements.py` | Flag Single Source |
| Battle Pass Unlock | `game/battle_pass.py` | `unlock_premium(source=…)` |

**Grant path (canonical):** `unlock_premium` / `grant_inventory_item` / `timekeeper.credit` — keine zweite Loot-Engine.

## Catalog v3 (`CATALOG_VERSION = 3`)

| SKU | Kind | Price (EUR) | Fulfill |
|-----|------|-------------|---------|
| `season_pass_current` | entitlement | 4,99 | `unlock_premium` aktive Season |
| `tk_pack_s` | timekeeper | 0,99 | **6 h** TK |
| `tk_pack_m` | timekeeper | 2,99 | **24 h** TK |
| `tk_pack_l` | timekeeper | 5,99 | **72 h** TK |
| `booster_pack_starter` | inventory_bundle | 2,99 | Build/Research **24h ×6** + **6h ×8** + prod_50 ×4 (≥ ~176 h/Domain) |
| `container_pack_rare` | inventory_bundle | 2,99 | rare×8 + epic×4 + mythic×2 + relic×1 |
| `commander_supply_pack` | inventory_bundle | 9,99 | **48 h** TK + Build/Research 24h ×6 + prod_100 ×3 + epic×4 + mythic×3 + ancient×2 + relic×2 |

`ensure_catalog_seeded` **upsertet** Preise/Payloads aus Code (Server-Truth).

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
| `GET /shop/return` | login | Post-checkout return (no client trust) |
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
4. `/shop` zeigt PayPal-Button
5. Sandbox-Kauf → Order `fulfilled`

## Non-goals (MVP)

- Gem wallet, subscriptions, mobile IAP, auto refund-revoke, cosmetics ala-carte, resource/ship shop.
- Free Login/Directives nerfen (Paid wird wertiger, Free bleibt stark).

## Related

- [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md) — EPIC-22 entitlement hook
- [GAME_RULES.md](GAME_RULES.md) §3.3a — official premium policy
