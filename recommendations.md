# Agrolav — Recommendations

Ranked by how much they reduce operational risk or finish the SQL cutover. None of this requires a new product; it is tightening what the repo already claims to be.

---

## 1. Finish SQL-only I/O

Follow `legacy_removal_agenda.md`: stop discovering people from disk, stop writing categorized JSON as the live path, list uploads from `account_balance_file`, and ingest parse-from-bytes into `transaction_*`. Add tests that pass with no country/center/person folders. Until then every feature has two implementations.

## 2. Login and upload tokens

SAFETY is right: guessable passwords (username, or a shared prefix) are weaker than the bank-key story. Store hashes. Give each person their own upload token instead of one scrypt string for everyone, and keep person/center on the grant URL. Set `CLIENT_SESSION_SECRET` in production; the default is documented as insecure.

## 3. One policy for bank keys

SAFETY says never put PEMs in SQL (backups become a key dump). Later code stores PEM on `enable_connection`. Pick one: files outside DB backups, or SQL with encryption and backup exclusion. Document it once. Do not leave both stories in the repo.

## 4. One booking table

`transaction_nederland` / `transaction_uk` copies the old folder grain. A single `transaction` with `country_id`, `year`, and `account_id` matches how the app queries (matrix, recalc, category totals) and removes a table per country. Category hundred-blocks already isolate catalogs.

---

## Hygiene that will keep paying off

| Item | Why |
|------|-----|
| One deployment + one public hostname | README, SAFETY, and deployment guides name different sites and still mention SQLite, DigitalOcean vs Lightsail, and folder copies. Collapse to the Caddy + systemd + Docker SQL path that is actually used. |
| Secrets out of git and markdown | Connection strings, session secrets, and host passwords must not live in .md files. Rotate anything that already did. |
| dbo.hub\_ip as the only allowlist | Hub README still describes upload\_acl.json grants and hub\_ips. Finish the SQL allowlist and drop the file dual-path. |
| Categorize in SQL | `finalize_imported_bookings` still thinks in JSON files then replicas. Recategorize UPDATE on `transaction_*` so refresh/upload cannot drift. |
| Drop artifacts/ as a second codebase | Dated copies of hub and client confuse search and reviews. Keep git history; delete the tree from the working copy. |

---

> **Do next, in order:**
> SQL-only upload and matrix (no disk pack) → hashed passwords and per-person upload tokens → PEM policy + backup runbook → unify docs and remove secrets from the tree. Schema merge of `transaction_*` can wait until the dual-write path is gone.

---

*Sources: README, hub/client READMEs, DATABASE.md, MIGRATION\_TO\_SQLSERVER.md, SAFETY.md, deployment.md, legacy\_removal\_agenda.md, authentication.md, and the hub/client Python + React tree. Docs that still describe JSON-as-source or password=username are treated as stale relative to the sqlserver cutover.*
