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

- [ ] AV / DPA / SCC with **Railway** (hosting)
- [ ] AV / terms with **SMTP** provider
- [ ] PayPal / Stripe merchant privacy settings reviewed
- [ ] Discord developer app privacy / webhook scope reviewed
- [ ] If edge-tts / OpenAI enabled: document in privacy + review provider terms
- [ ] Confirm no third-party analytics snippets were added to templates

## Tax / shop orders

Order rows (sku, amount, status, timestamps) may be retained after account anonymisation for accounting. Raw webhook payloads and rich metadata are reduced on deletion / purge.
