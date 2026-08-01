# Privacy / DSGVO ops checklist (Genesis Colonies)

> Companion to in-game `/legal` privacy text (`game/legal_panel.py`).  
> **Not legal advice.** Close AV/DPA paperwork with providers outside the repo.

## In-product controls

| Control | Where |
|---------|--------|
| Privacy / cookies / retention text | `game/legal_panel.py` → `/legal/privacy` |
| Essential cookie notice | `templates/partials/cookie_notice.html` |
| Age 16+ + privacy/AGB on register | `templates/register.html` + `app.py` register / Discord |
| Data export (JSON) | `GET /api/options/data-export` · Options UI |
| Account deletion (7-day grace, anonymise) | `game/options.py` `execute_account_deletion` |
| Retention purge | `game/privacy_retention.py` via maintenance bag |

## Cookies (essential only)

- Flask session
- `gc_locale`
- `gc_cookie_notice`

No analytics / marketing cookies.

## Env knobs (retention)

| Env | Default | Effect |
|-----|--------:|--------|
| `GC_PRIVACY_PURGE_PAYMENT_DAYS` | 90 | Clear `shop_payment_events.payload_json` |
| `GC_PRIVACY_PURGE_AUDIT_IP_DAYS` | 180 | Null IP/UA on audit logs |
| `GC_PRIVACY_PURGE_AUDIT_DAYS` | 365 | Delete `account_audit_log` rows |
| `GC_PRIVACY_PURGE_ADMIN_AUDIT_DAYS` | 730 | Delete `admin_audit_log` rows |

## Operator checklist (outside code)

### Auftragsverarbeiter (Art. 28) — AV/DPA möglich

- [x] **Railway** hosting — DPA abgeschlossen (2026-08)
- [ ] SMTP provider AV / terms (if transactional mail is live)
- [ ] If edge-tts / OpenAI enabled: review provider DPA/terms

### Eigenständige Verantwortliche — kein Art.-28-AV

- [x] **PayPal** — kein AV; PayPal ist Zahlungsdienstleister / eigener Verantwortlicher (ggf. gemeinsame Verantwortlichkeit). Privacy: https://www.paypal.com/myaccount/privacy/privacyhub — Merchant-Einstellungen geprüft / dokumentiert
- [ ] **Stripe** (nur falls `SHOP_ENABLE_STRIPE=1`) — eigener Provider; Stripe DPA im Dashboard akzeptieren falls genutzt
- [ ] **Discord** OAuth / support webhooks — Privacy Policy & scopes reviewed

### Sonstiges

- [ ] Confirm no third-party analytics snippets were added to templates

## Tax / shop orders

Order rows (sku, amount, status, timestamps) may be retained after account anonymisation for accounting. Raw webhook payloads and rich metadata are reduced on deletion / purge.
