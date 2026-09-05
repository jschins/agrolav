# Agrolav — Overview

| Component | Port | Role |
|-----------|------|------|
| Hub | :8200 | FastAPI data API |
| Client | :8300 | BFF + React UI |
| SQL Server | :1433 | Authoritative store |
| Caddy | 80/443 | Public HTTPS; hub and client stay on loopback |
| 3 roles | — | Country / center / person |

Agrolav is a multi-household expense system. People in several countries
keep bank bookings in one place: a year-by-year matrix of people against
spending categories, with balances and last-booked dates as footer rows.
The public site is Caddy in front of a thin client. The hub and SQL Server
stay off the public internet.

Country and center logins are restricted by egress IP: the address must
appear in `dbo.administrator` or in that login's own `egress_ip` column,
and an empty column admits nobody. Person logins are not IP-gated.
Attempted public addresses land in `dbo.visitor_ip`.

## How it is put together

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
as "12 Vervoer". Keyword terms, type rules, and matrix footer labels live
in dimension tables. See `DATABASE.md`.

### Two ways money enters

**Enable Banking**

Create the person, store the application PEM on `dbo.enable_connection`,
run bank consent, then refresh downloads transactions into SQL. Session
state (`session_id`, `valid_until`) lives on the same row.

**Excel / CSV upload**

People paste a spreadsheet or a bank CSV. The hub parses the bytes,
categorizes rows (remainder until keywords match), records the filename on
`dbo.uploaded_files`, and writes the rows on `dbo.transaction_*`.

## What users actually do

| Surface | Role |
|---------|------|
| Matrix + year switcher | Totals by person and category; saldo/datum from `account.balance` and `last_booked` |
| Transaction list | Open a cell; edit category or description; split an amount; personal keyword overlays |
| Refresh | Pull from the bank, or re-import; consent URL if the bank session expired |
| Upload | Personal login: token-gated hub page for xlsx/csv |
| Admin on :8200 | Add person, create country/center |

The frontend user guide is the root `README.md`. Operator setup is
`deployment.md`.
