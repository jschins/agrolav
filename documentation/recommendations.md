# Agrolav — Recommendations

Ranked by operational risk. None of this is a new product; it is tightening
what the repo already claims to be.

---

## 1. Login strength for country and center

Person passwords are hashed. Country and center still use a derived formula,
so they depend entirely on the egress-IP allowlist. That is acceptable only
while those lists stay short and `HUB_DEV_LOGIN` stays off the server.

## 2. Encrypt database backups

`dbo.enable_connection.pem` travels with every `.bak`. Encrypt before the
file leaves the box. See `SAFETY.md`.

## 3. One booking table

`transaction_nederland` / `transaction_uk` copies the old country grain. A
single `transaction` with `country_id`, `year`, and `account_id` matches how
the app queries (matrix, recalc, category totals) and removes a table per
country. Category hundred-blocks already isolate catalogs. Wait until there
is no dual-write path left.

---

## Hygiene

| Item | Why |
|------|-----|
| One public hostname | `expenses.apsurt.nl` via Caddy + systemd + Docker SQL. |
| Secrets out of git and markdown | Connection strings, session secrets, and host passwords must not live in `.md` files. |
| Keep local and remote schema identical | Run `hub/sql/visitor_ip.sql` and `hub/sql/administrator.sql` on both after a restore. |

---

*Sources: DATABASE.md, deployment.md, SAFETY.md, double_login.md, and the
hub/client Python + React tree.*
