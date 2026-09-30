# Agrolav — Overview

| Component | Port | Role |
|-----------|------|------|
| Hub | :8200 | FastAPI data API |
| Client | :8300 | BFF + React UI |
| Balance | :8500 | Profit/loss under `/result/{slug}` |
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

## Hub, client, and balance

| Process | Port | What the browser sees |
|---------|------|------------------------|
| Hub | 8200 | Nothing of its own. Caddy forwards selected `/api/local/*` calls. |
| Client | 8300 | The site: login, matrix, menu. |
| Balance | 8500 | `/result/{slug}/` — profit/loss (Resultaat). |

All three bind to `127.0.0.1`. `slug` is `dbo.country.username`.

The hub is the data API: login, bookings, categories, bank refresh, and
upload. SQL Server is the only store. The client is the BFF and the React
UI. The browser session stays on the client, and the client calls the hub.

Balance is a window opened from the client menu. Escape on the sheet, or
logout on the menu page, closes that window. It is served from the balance
app and its frontend build (`balance/frontend/dist`).

Balance shows local codes 3000–4999: kosten 3000–3999 and opbrengsten
4000–4999. The amounts follow the login — the country, that center, that
person, or that unit account. The menu link is `RESULT_URL`, otherwise
`http://127.0.0.1:8500`. On the public site set `RESULT_URL` to the site
origin and proxy `/result*` to port 8500. The process is
`uvicorn app.result_main:app` from the balance directory.

### Starting Balance locally

The command runs from the `balance` directory. That directory is one Python
project (`balance/pyproject.toml`, one `.venv`). It publishes one console
script:

| Command | Calls | Port |
|---------|--------|------|
| `uv run balance` | `app.result_main:run` | 8500 |

`uv run balance` starts the profit/loss window. The module form
`.\.venv\Scripts\python.exe -m app.result_main` calls the same
`app.result_main:run` function as `uv run balance`. `uv run` looks the name
up in `[project.scripts]` and runs it with the project virtualenv;
`python -m` loads that module with the virtualenv interpreter directly.

There is no `result` directory. Balance uses that project's virtualenv,
dependencies, and `balance/frontend/dist`. Hub, client, and balance each
have their own directory and `pyproject.toml`.

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

### Enable Banking and Excel or CSV upload

**Enable Banking**

Create the person, store the application PEM on `dbo.enable_connection`,
run bank consent, then refresh downloads transactions into SQL. Session
state (`session_id`, `valid_until`) lives on the same row.

**Excel / CSV upload**

People paste a spreadsheet or a bank CSV. The hub parses the bytes,
categorizes rows (remainder until keywords match), records the filename on
`dbo.uploaded_files`, and writes the rows on `dbo.transaction_*`.

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
