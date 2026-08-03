# Referrals — Invite System

**Owner:** `game/referrals.py`  
**UI:** `/referrals` (`referrals_view`)  
**Related:** [INVENTORY_SYSTEM.md](INVENTORY_SYSTEM.md) · [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md)

Unique referral codes and activity-gated tier rewards (meta containers into Inventory). Same-IP referrals are recorded but do not count toward tiers.

**Creator bridge:** Active `shop_promo_codes` resolve to the creator `player_id` inside `_resolve_referrer_by_code` when no native referral code matches — one vanity code for invites + shop. See [PAYMENT_SHOP.md](PAYMENT_SHOP.md) Creator Partner Program.

---

## Player Article

```yaml
---
codex_id: referrals
band: III
difficulty: beginner
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - referrals_view
related_codex:
  - inventory
  - liveops_retention
  - genesis_ark
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: referrals_view
teaser_key: codex_unlock_referrals_teaser
---
```

## Quick Help

**Referrals** unter `/referrals`: teile deinen Code, verlinke neue Commander und claime Tier-Belohnungen, wenn geworbene Spieler aktiv werden.

## Summary

Jeder Commander hat einen einzigartigen Referral-Code und Link. Neue Spieler können einen Code einmal anwenden (bei Registrierung oder im Spiel). Wenn geworbene Accounts Aktivitäts-Meilensteine erreichen, schaltet der Werber Tier-Belohnungen frei — Meta-Container ins **Inventar**. Same-IP-Referrals werden erfasst, zählen aber nicht für Tiers.

## Why

Community fair wachsen: Belohnungen für echte Aktivität, nicht für leere Alts. Rewards bleiben in der Inventar-Meta-Schleife — kein Rohstoff-Dump.

## How it works

- Öffne **`/referrals`** für Code, Link, Fortschritt und claimbare Tiers.
- Link/Code teilen; der Geworbene wendet ihn einmal an.
- Aktivitäts-Gates (Account-Alter / Planetenfortschritt) entscheiden, wann eine Referral zählt.
- Tier-Boxen ins Inventar claimen, wenn die erforderlichen Counts erreicht sind.
- Server lehnt Missbrauchsmuster (z. B. gleiche IP) für Tier-Credit ab.

## Related Systems

- inventory
- liveops_retention
- genesis_ark

## Commander Tips

- Link früh teilen — Codes gelten nur einmal pro Account.
- Tiers claimen, wenn der Zähler voll ist; Boxen warten im Inventar.
- Keine Same-IP-Alts farmen — sie zählen nicht.

## FAQ

**Kann ich meinen Werber später ändern?**
Nein — ein Code verknüpft einmal pro Account.

**Was bekomme ich?**
Gestaffelte Meta-Container im Inventar, nachdem geworbene Spieler qualifizieren.

## Discord Summary

**Referrals — Einladungs-Code und Tiers**

`/referrals`: einzigartiger Code, aktivitätsgegate Tiers, Inventar-Belohnungen. Freischaltung nach erstem Besuch.
