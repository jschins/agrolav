# Agrolav — Overview

| Component | Port | Role |
|-----------|------|------|
| Hub | :8200 | FastAPI data API |
| Client | :8300 | BFF + React UI |
| Balance | :8100 | Balance sheets under `/balance/{slug}` |
| Result | :8500 | Profit/loss under `/result/{slug}` |
| Maaltijden | :8400 | Meal matrix for `nl_dkg` at `/maaltijden` |
| SQL Server | :1433 | Authoritative store |
| Caddy | 80/443 | Public HTTPS; hub and apps stay on loopback |
| 3 roles | — | Country / center / person |

Agrolav is a multi-household expense system. People in several countries
keep bank bookings in one place: a year-by-year matrix of people against
spending categories, with balances and last-booked dates as footer rows.
The public site is Caddy in front of a thin client. The hub and SQL Server
stay off the public internet.

Country and center logins are restricted by egress IP: the address must
appear in `dbo.egress_ip` or in that login's own `egress_ip` column,
and an empty column admits nobody. Person logins are not IP-gated.
Attempted public addresses land in `dbo.visitor_ip`.

<!-- {en:agrolav[5],overview[5],hub,client,port} -->
<!-- {nl:agrolav[5],overzicht[5],hub,client,poort} -->

## Hub, client, balance, and result

| Process | Port | What the browser sees |
|---------|------|------------------------|
| Hub | 8200 | Nothing of its own. Caddy forwards selected `/api/local/*` calls. |
| Client | 8300 | The site: login, matrix, menu. |
| Balance | 8100 | `/balance/{slug}/` — the balance sheet. |
| Result | 8500 | `/result/{slug}/` — profit/loss (Resultaat). |

All four bind to `127.0.0.1`. `slug` is `dbo.country.username`.

The hub is the data API: login, bookings, categories, bank refresh, and
upload. SQL Server is the only store. The client is the BFF and the React
UI. The browser session stays on the client, and the client calls the hub.

Balance and Result are separate windows opened from the client menu. Escape
on the sheet, or logout on the menu page, closes that window. Both are
served from the balance app and its frontend build (`balance/frontend/dist`).

Balance shows local codes 1000–2999, and only for a country with
`dbo.country.has_balance = 1`. The amounts are the whole country. The menu
link is `BALANCE_URL`, otherwise `PUBLIC_HUB_URL`, otherwise
`http://127.0.0.1:8100`. Caddy proxies `/balance*` to port 8100.

Result shows local codes 3000–4999: kosten 3000–3999 and opbrengsten
4000–4999. The amounts follow the login — the country, that center, that
person, or that unit account. The menu link is `RESULT_URL`, otherwise
`http://127.0.0.1:8500`. On the public site set `RESULT_URL` to the site
origin and proxy `/result*` to port 8500. The process is
`uvicorn app.result_main:app` from the balance directory.

<!-- {en:hub[5],client[5],balance[5],result[5],port,caddy} -->
<!-- {nl:hub[5],client[5],balans[5],resultaat[5],poort,caddy} -->

## Hub logic, the client BFF, and the SQL tables

The hub owns domain logic: login, IP allowlists, bank refresh (Enable
Banking), Excel/CSV upload, categorization, and recalculation. The client
is a BFF: browser login cookies, session heartbeats, and a React app that
talks only to the client. Access is deduced from the identity row: person
set → personal; center set, person empty → that center; only country set →
every center in that country.

Data lives in SQL Server database **agrolav**. Countries, centers, and
people are login rows (`dbo.country` / `dbo.center` / `dbo.person`). Each
person has accounts; bookings sit in a per-country table
(`transaction_nederland`, `transaction_uk`, …). Categories use a stable
`category_id` (100+ per country) while the UI still shows local codes such
as "12 Vervoer". Keyword terms and matrix footer labels live in dimension
tables. See `DATABASE.md`.

<!-- {en:hub[5],logic[5],client[5],bff[5],sql[5],tables[5]} -->
<!-- {nl:hub[5],logica[5],client[5],bff[5],sql[5],tabellen[5]} -->

### Enable Banking and Excel or CSV upload

**Enable Banking**

Create the person, store the application PEM on `dbo.enable_connection`,
run bank consent, then refresh downloads transactions into SQL. Session
state (`session_id`, `valid_until`) lives on the same row.

**Excel / CSV upload**

People paste a spreadsheet or a bank CSV. The hub parses the bytes,
categorizes rows (remainder until keywords match), records the filename on
`dbo.uploaded_files`, and writes the rows on `dbo.transaction_*`.

<!-- {en:enable[5],banking[5],excel[5],csv[5],upload[5],consent} -->
<!-- {nl:enable[5],banking[5],excel[5],csv[5],uploaden[5],toestemming} -->

## Matrix, booking list, refresh, and upload

| Surface | Role |
|---------|------|
| Matrix + year switcher | Totals by person and category; saldo/datum from `account.balance` and `last_booked` |
| Transaction list | Open a cell; edit category or description; split an amount; personal keyword overlays |
| Refresh | Pull from the bank, or re-import; consent URL if the bank session expired |
| Upload | Personal login: token-gated hub page for xlsx/csv |
| Admin on :8200 | Add person, create country/center |

The frontend user guide is the root `README.md`. Operator setup is
`deployment_tech.md`. The meal sheet is `maaltijden.md`.

<!-- {en:matrix[5],booking[5],list[5],refresh[5],upload[5],year} -->
<!-- {nl:matrix[5],boeking[5],lijst[5],verversen[5],uploaden[5],jaar} -->
