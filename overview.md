# Agrolav — Overview

| Component | Port | Role |
|-----------|------|------|
| Hub | :8200 | FastAPI data API |
| Client | :8300 | BFF + React UI |
| SQL Server | — | Authoritative store |
| 3 roles | — | Country / center / person |

---

Agrolav is a multi-household expense system. People in several countries (Nederland, United Kingdom, Ireland, and similar) keep bank bookings in one place: a year-by-year matrix of people against spending categories, with balances and last-booked dates as footer rows. The public site is an HTTPS reverse proxy (Caddy) in front of a thin client. The hub and SQL Server stay off the public internet.

## How it is put together

The hub owns domain logic: login, IP allowlists, bank refresh (Enable Banking), Excel/CSV upload, categorization, and recalculation. The client is a BFF: browser login cookies, session heartbeats, and a React app that talks only to the client. Shared login helpers decide access from the identity row: person set → personal; center set, person empty → that center; only country set → every center in that country.

Data lives in SQL Server database **agrolav**. Countries, centers, and people are login rows (`dbo.country` / `dbo.center` / `dbo.person`). Each person has accounts; bookings sit in a per-country table (`transaction_nederland`, `transaction_uk`, …). Categories use a stable `category_id` (100+ per country) while the UI still shows local codes such as "12 Vervoer". Keyword terms, type rules, and matrix footer labels live in dimension tables.

### Two ways money enters

**Enable Banking**

Secret-mode people: create the person, install a PEM, run bank consent, then refresh downloads transactions into SQL. Consent and connection state belong on `dbo.enable_connection`; older docs still describe `secret/*.pem` files.

**Excel / CSV upload**

Non-secret people paste a spreadsheet or a bank CSV. The hub parses the file, categorizes rows (remainder until keywords match), and should record the filename on `dbo.account_balance_file` and the rows on `dbo.transaction_*`.

## What users actually do

| Surface | Role |
|---------|------|
| Matrix + year switcher | Totals by person and category; saldo/datum (or UK labels) from account.balance and last_booked |
| Transaction list | Open a cell; edit category or description; split an amount; personal keyword overlays |
| Refresh | Pull from the bank (PEM people) or re-import; consent URL if the bank session expired |
| Upload | Personal login only: token-gated hub page for xlsx/csv |
| Admin on :8200 | Sessions, add person, create country/center; not a general upload console |

> **In-between architecture**
>
> The code is mid-cutover. SQL is the intended source of truth (README, deployment, DATABASE.md). A legacy folder tree (country/center/person/year JSON) and PersonPack paths are still wired through hub helpers. Docs disagree on public hostname, whether PEMs may live in SQL, and whether passwords equal the username. Treat the running hub + dbo.\* as ground truth, the markdown as a mix of plan and leftover procedure.
