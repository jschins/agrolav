# Balance — Balansverklaring voor Beheer

A standalone hub (port 8100) that produces a balance statement for the Beheer
country (country_id=4). It reuses the existing `agrolav` SQL Server database and
the React frontend, but runs its own FastAPI process with balance-specific API
endpoints.

---

## 1. Goal

Produce an annual balance sheet (balansverklaring) for Beheer, structured as:

```
Activa                          Passiva
─────────────────────────────   ─────────────────────────────
1000 Gebouwen                   2000 Eigen vermogen
1005 Verbouwingen               2050 Reserve Vergeer
1010 Inventaris                 2055 Reserve FF-OG
1015 Autos                      2500 Schulden particulieren
1051 Bank algemeen
1052 Spaarrekening
1053 Bank huish. dienst
1054 Bank FPU
1055 Bank FOH
1056 Bank residentie ddkg
1110 Kruisposten
1111 r/c K218
─────────────────────────────   ─────────────────────────────
Totaal Activa                   Totaal Passiva
```

Activa must equal Passiva for each year.

---

## 2. Architecture — what is reused, what is new

| piece | reused | new |
|-------|--------|-----|
| SQL Server (`agrolav`) | yes — reads `dbo.account`, `dbo.dim_category`, `dbo.country` | two new tables (§3) |
| React frontend | yes — same build, new routes under `/balance/` | balance-specific pages |
| Hub on :8200 | no — untouched | |
| Hub on :8100 | | new FastAPI process, balance endpoints only |
| Caddy | extends existing config | new route `expenses.apsurt.nl/balance/` → :8100 |

The balance hub does not touch the existing matrix, transaction, or
categorization machinery. It reads account balances and category definitions
from the shared database and writes only to its own tables.

---

## 3. Database additions

### 3a. `dbo.balance_opening` — manually entered opening balances

Stores the opening balance for non-bank categories per year. Bank categories
(1051–1056) are read from `dbo.account.balance` and do not need this table.

```sql
IF OBJECT_ID(N'dbo.balance_opening', N'U') IS NULL
CREATE TABLE dbo.balance_opening (
    category_id   INT           NOT NULL,
    year          INT           NOT NULL,
    amount        DECIMAL(18,2) NOT NULL DEFAULT 0,
    note          NVARCHAR(256) NULL,
    CONSTRAINT pk_balance_opening PRIMARY KEY (category_id, year)
);
```

Categories covered by this table:

| category_id | label | source |
|-------------|-------|--------|
| 1000 | Gebouwen | manual valuation |
| 1005 | Verbouwingen | manual valuation |
| 1010 | Inventaris | manual valuation |
| 1015 | Autos | manual valuation |
| 1052 | Spaarrekening | manual (or link to account later) |
| 1110 | Kruisposten | manual elimination |
| 1111 | r/c K218 | manual elimination |
| 2000 | Eigen vermogen | computed or manual |
| 2050 | Reserve Vergeer | manual |
| 2055 | Reserve FF-OG | manual |
| 2500 | Schulden particulieren | manual |

### 3b. `dbo.balance_transaction` — journal entries

Future: depreciation, transfers between categories, corrections. Not built yet.

```sql
IF OBJECT_ID(N'dbo.balance_transaction', N'U') IS NULL
CREATE TABLE dbo.balance_transaction (
    transaction_id  INT           IDENTITY(1,1) PRIMARY KEY,
    year            INT           NOT NULL,
    date            DATE          NOT NULL,
    category_id     INT           NOT NULL,
    amount          DECIMAL(18,2) NOT NULL,
    description     NVARCHAR(256) NOT NULL,
    created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
```

### 3c. `dbo.balance_journal` — hand-edited linking transactions

Hand-edited journal entries that move money from one balance category to another
(used for person `sdog` in center `beh_stichtingen`; a future `instudo` person
will share the same structure). Each row has a FROM category, a TO category, an
amount and a description. These are deliberately **separate** from
`transaction_beheer` (bank bookings) and from the auto-generated spaar-mirror
rows in `balance_transaction`.

```sql
IF OBJECT_ID(N'dbo.balance_journal', N'U') IS NULL
CREATE TABLE dbo.balance_journal (
    journal_id      INT           IDENTITY(1,1) PRIMARY KEY,
    year            INT           NOT NULL,
    date            DATE          NOT NULL,
    category_from   INT           NOT NULL,
    category_to     INT           NOT NULL,
    amount          DECIMAL(18,2) NOT NULL,
    description     NVARCHAR(512) NOT NULL,
    created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
```

DDL file: `balance/sql/balance_journal.sql`. For each row the **FROM** category
decreases by `amount` and the **TO** category increases by `amount`, so the sum
across all categories is zero and the sheet stays balanced. In `balance_sheet`
these effects are folded into each category total (source becomes
`opening+journal` / `account:N+journal`).

---

## 4. Bank account → category mapping

Five bank accounts in `dbo.account` map to balance categories. The balance hub
reads `dbo.account.balance` directly — no duplication. The mapping follows the
account's purpose (account name), matching the actual rows in `dbo.account`.

| category_id | label | account_id | IBAN | account_name |
|-------------|-------|------------|------|--------------|
| 1051 | Bank algemeen | 18 | NL34INGB0004378667 | Stichting de Oude Gracht |
| 1053 | Bank huish. dienst | 20 | NL93INGB0669986755 | stichting de Oude Gracht |
| 1054 | Bank FPU | 17 | NL09INGB0006364222 | HULPFONDS PAUSELIJKUNIVERSITEIT VAN HET H KRUIS |
| 1055 | Bank FOH | 19 | NL44INGB0006494736 | HULPFONDS ONTW PROJECTEN STICHTING DE OUDE GRACHT |
| 1056 | Bank residentie ddkg | 21 | NL94INGB0006200605 | Stichting De Oude Gracht |

Category 1052 (Spaarrekening) has no linked account yet; its balance is
manually entered in `dbo.balance_opening`.

The mapping is hard-coded as `CATEGORY_MAP` in `app/balance.py`.

---

## 5. Why non-bank assets are not accounts

The `dbo.account` table is designed for bank accounts: it has IBAN, person_id,
consent fields, and Enable Banking integration. Non-bank assets (buildings,
inventory, autos) and equity/liability categories are not bank accounts:

- They have no IBAN.
- They do not produce bank transactions.
- Their values change via periodic revaluation or manual journal entries, not
  via bank refresh.
- Forcing them into `dbo.account` would require fake IBANs or a new account-type
  column, adding complexity without benefit.

Instead, `dbo.balance_opening` stores their values per year. This is the standard
approach for a balance sheet: bank balances come from the bank, everything else
is recorded by the accountant.

---

## 6. API design (hub on :8100)

### Endpoints

| method | path | description |
|--------|------|-------------|
| GET | `/api/balance/{year}` | Full balance sheet for a year |
| GET | `/api/balance/{year}/activa` | Activa side only |
| GET | `/api/balance/{year}/passiva` | Passiva side only |
| PUT | `/api/balance/{year}/opening` | Set/update opening balances for a year |
| POST | `/api/balance/{year}/spaar-mirror` | Rebuild the faked 1052 spaarrekening journal from the 1051 source rows |
| GET | `/api/balance/{year}/journal` | List the hand-edited journal rows for a year |
| PUT | `/api/balance/{year}/journal` | Full-replace the hand-edited journal for a year (from/to/amount/description) |
| GET | `/api/balance/years` | List years with data |
| GET | `/api/balance/categories` | Category list with bank account links |

### GET `/api/balance/{year}` response

```json
{
  "year": 2026,
  "activa": [
    {"category_id": 1000, "code": 1000, "label": "Gebouwen", "amount": 0.00, "source": "opening"},
    {"category_id": 1051, "code": 1051, "label": "Bank algemeen", "amount": 8393.74, "source": "account:18"},
    ...
  ],
  "passiva": [
    {"category_id": 2000, "code": 2000, "label": "Eigen vermogen", "amount": 0.00, "source": "opening"},
    ...
  ],
  "total_activa": 28313.04,
  "total_passiva": 28313.04,
  "balanced": true
}
```

The `source` field indicates where the amount came from:
- `"opening"` — from `dbo.balance_opening`
- `"account:{id}"` — from `dbo.account.balance`
- `"opening+journal"` — opening + sum of `dbo.balance_transaction` for that category/year
- `"computed"` — the Verlies post, computed so the two sides balance

Note: each bank-category balance is read live from `dbo.account.balance`. This
is the *current* snapshot, not a start-of-year figure. See §12 for how the
spaarrekening differs.

---

## 12. Spaarrekening (1052) mirror transactions

### Problem

The checking account 1051 (account 18, NL34..667) has a linked spaarrekening
(1052). Transfers between them appear **only** on the 1051 statement — the
spaarrekening side is invisible in the bank data. These transfers are not
included in the balance/PL because their combined total is unaffected by
transfers between them. We therefore reconstruct the spaarrekening ledger as
**faked** journal entries in `dbo.balance_transaction`.

### Detection

A 1051 transaction is a spaarrekening transfer when its description contains
the keyword `spaarrekening`:

```sql
SELECT booked_on, amount, description
FROM dbo.transaction_beheer
WHERE account_id = 18
  AND LOWER(COALESCE(description, N'')) LIKE '%spaarrekening%';
```

Verified: on the live remote DB this matches exactly the 7 transfer lines, all
on account 18.

### Mirror rule

The faked 1052 amount is the **negative** of the 1051 amount:

- `Naar ... spaarrekening` (money leaves 1051, negative) → 1052 **increases** (+)
- `Van ... spaarrekening` (money enters 1051, positive) → 1052 **decreases** (−)

So `1052 = -1051_amount`. Each generated row is stamped with the marker prefix
`[spaar-mirror]` in its `description` so it can be identified and rebuilt.

### Sheet total

1052 is a special non-bank category: its sheet total = opening balance +
sum of its mirror journal:

```
1052 = balance_opening(1052, year) + SUM(balance_transaction where category=1052)
```

Current 2026 figures: opening 688 269.91, mirror journal net −80 000.00
⇒ 1052 = 608 269.91. The `source` for 1052 is `"opening+journal"`.

### Endpoint: `POST /api/balance/{year}/spaar-mirror`

Rebuilds the faked journal for a year, **idempotently**: it first deletes all
existing `[spaar-mirror]` rows for that category/year, then re-inserts the rows
derived from the current 1051 source. Call it after a bank refresh so the sheet
tracks the latest transfers. Does not touch the 1051 rows or the PL.

```json
{"ok": true, "year": 2026, "generated": 7}
```

The deletion uses `LIKE ... ESCAPE '!'` on the `[spaar-mirror]` marker — the
square brackets must be escaped because `[...]` is a wildcard pattern in SQL
Server.

---

## 7. Frontend routes

The React app adds routes under `/balance/`:

| route | page |
|-------|------|
| `/balance/` | Balance overview — two-column table (activa / passiva) with totals |
| `/balance/{year}` | Same, for a specific year |
| `/balance/{year}/edit` | Edit opening balances (non-bank categories only) |

From the overview toolbar the **Herbouw spaarrekening (1052)** knob rebuilds the
1052 mirror journal, and the **Edit transactions** knob opens a full-screen
journal editor (same window, replacing the sheet) for the hand-edited
`balance_journal` rows of the selected year. The editor follows the client's
category-edit pattern (draft table with inline inputs, add/remove rows, Save
does a full-replace for the year). After returning to the sheet the totals are
reloaded so the journal effects show up.

The existing matrix/transaction/categorization UI is not affected.

---

## 8. Initial data

### Opening balances for year 2026

Bank balances are read from `dbo.account` (current `balance` column). Non-bank
categories are read from `dbo.balance_opening`. Actual values currently in the
database:

| category_id | label | amount (2026) | source |
|-------------|-------|---------------|--------|
| 1000 | Gebouwen | 89 000.00 | opening |
| 1005 | Verbouwingen | 2 272 550.85 | opening |
| 1010 | Inventaris | 29 245.54 | opening |
| 1015 | Autos | 6 685.34 | opening |
| 1051 | Bank algemeen | 18 393.74 | account:18 |
| 1052 | Spaarrekening | 688 269.91 | opening |
| 1053 | Bank huish. dienst | 2 867.50 | account:20 |
| 1054 | Bank FPU | 2 096.11 | account:17 |
| 1055 | Bank FOH | 2 230.56 | account:19 |
| 1056 | Bank residentie ddkg | 3 633.87 | account:21 |
| 1110 | Kruisposten | 0.00 | opening |
| 1111 | r/c K218 | -3 311.23 | opening |
| 2000 | Eigen vermogen | 2 525 971.26 | opening |
| 2050 | Reserve Vergeer | 174 733.25 | opening |
| 2055 | Reserve FF-OG | 500 000.00 | opening |
| 2100 | Verlies | computed (-169 245.86) | computed |
| 2500 | Schulden particulieren | 80 203.54 | opening |

Total activa = total passiva = 3 111 662.19 (balanced). The Verlies post is
computed by the hub so the two sides always balance.

---

## 9. Implementation phases

1. **Schema** — create `dbo.balance_opening` and `dbo.balance_transaction` tables. ✅
2. **Hub skeleton** — FastAPI on :8100, `/api/balance/{year}` endpoint that reads
   account balances and opening balances, returns the two-sided sheet. ✅
3. **Opening balance editor** — PUT endpoint for non-bank categories. ✅ (API)
4. **Spaarrekening mirror** — `POST /api/balance/{year}/spaar-mirror` rebuilds the
   faked 1052 journal from the 1051 "spaarrekening" rows (idempotent). ✅ (API)
5. **Frontend** — balance overview page, year switcher, activa/passiva columns. ✅
   (standalone Vite+React app under `frontend/`, talks to :8100)
6. **Transactions** (later) — journal entry interface, depreciation calculation.
7. **Caddy route** — proxy `/balance/` to :8100.

## 10. Files created

```
balance/
  README.md           ← this file
  pyproject.toml      ← balance-hub package (port 8100); `uv sync` here
  uv.lock             ← generated by uv sync
  .env                ← HUB_DATABASE_URL + PORT (local override)
  app/
    __init__.py
    main.py           ← FastAPI app (endpoints + serves /balance/ static)
    balance.py        ← balance calculation + CATEGORY_MAP + spaar-mirror
    db.py             ← pyodbc connection wrapper (+ .env loading)
  frontend/
    package.json      ← balance-frontend (Vite + React 18)
    vite.config.ts    ← base /balance/, dev proxy → http://127.0.0.1:8100 (port 5174)
    src/
      main.tsx        ← entry
      App.tsx         ← balance sheet UI (activa/passiva + view switch)
      JournalEditor.tsx ← hand-edited journal editor (Edit transactions)
      api.ts          ← /balance/api/... calls
      types.ts
      index.css
  sql/
    schema.sql            ← balance_opening + balance_transaction DDL
    balance_journal.sql   ← dbo.balance_journal DDL
```

The balance hub is standalone: it depends only on fastapi/uvicorn/pydantic/
pyodbc/python-dotenv. It does **not** import the main hub's `user_store` or auth
machinery. It also serves the built balance frontend under `/balance/`
(static assets + SPA index fallback).

Git-ignored (per the root `.gitignore`): `balance/.env`, `balance/.venv/`,
`balance/app/__pycache__/`, `balance/*.egg-info/`, `balance/frontend/node_modules/`,
`balance/frontend/dist/`, `balance/frontend/**/*.tsbuildinfo`,
`balance/frontend/vite.config.js`, `balance/frontend/vite.config.d.ts`. Only
source files are committed; `.env` (secrets) and build artifacts are rebuilt on
the server.

The balance frontend is a separate Vite+React app that talks directly to the
balance hub (`/balance/` base, `/balance/api/...` calls) — it does not go
through the client BFF or the main hub auth. Run `npm ci && npm run build`
inside `frontend/` to produce `dist/`.

---

## 13. Deployment (remote, everything on the server)

The balance hub and its frontend run entirely on the production server,
mirroring the client's deployment pattern. The code is committed to git; on the
server pull it first:

```bash
cd /opt/agrolav
git pull                          # brings balance/{app,frontend,sql,README}
```

### Backend on the server (`uv sync`)

The balance project follows the same `uv sync` convention as `client/`, `hub/`
and `shared/` — one `pyproject.toml` at the project root, `.venv` and `uv.lock`
created in `balance/`:

```bash
cd /opt/agrolav/balance
uv sync                           # → .venv + uv.lock
```

### Build the frontend on the server

```bash
cd /opt/agrolav/balance/frontend
npm ci
npm run build            # → dist/   (built with base /balance/)
```

### Balance hub systemd service (`/etc/systemd/system/agrolav-balance.service`)

```ini
[Unit]
Description=Agrolav balance hub
After=network.target

[Service]
WorkingDirectory=/opt/agrolav/balance
EnvironmentFile=/etc/agrolav/balance.env
ExecStart=/opt/agrolav/balance/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/agrolav/balance.env`:

```text
HOST=127.0.0.1
PORT=8100
HUB_DATABASE_URL=DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=YOUR_PASSWORD;Encrypt=yes;TrustServerCertificate=yes
# Optional: override where the built frontend is read from
# BALANCE_DIST=/opt/agrolav/balance/frontend/dist
```

### Optional API key (future)

The hub supports an optional `CENTRALE_API_KEY` in `balance.env`; when set, every
`/api/...` endpoint (except `/api/health`) requires an
`Authorization: Bearer <key>` header. **This is currently disabled by default**
because the balance SPA calls the API without an `Authorization` header — the
sheet is served as a public read-only view, and a shared secret cannot be safely
embedded in a browser app.

To enable it later (once the frontend gets a real login that can attach the
header), add:

```text
CENTRALE_API_KEY=your-secret-token
```

Keeping it empty (or the line absent) leaves the balance sheet public.

The hub serves the frontend's `dist/` at `/balance/` and its API at
`/api/balance/...`, all on `127.0.0.1:8100`.

### Caddy route

Add a `handle /balance/*` block to the existing site so browsers reach the
balance hub through the public HTTPS endpoint:

```caddy
handle /balance/* {
    reverse_proxy 127.0.0.1:8100 {
        header_up X-Forwarded-For {http.request.remote.host}
        header_up X-Real-IP {http.request.remote.host}
    }
}
```

Public URL: `https://expenses.apsurt.nl/balance/`.

Note the ordering: the Caddy `handle` for `/consent/callback`, `/upload`,
`/balance/*`, and the default client proxy each match a path prefix. The
`/balance/*` handler must come before the catch-all client proxy.

### Local dev quick start (for comparison)

```powershell
# terminal 0 — once: set up the balance python env
cd C:\Coding\agrolav\balance
uv sync                                 # → .venv + uv.lock

# terminal 1 — balance hub (reads HUB_DATABASE_URL from balance/.env)
cd C:\Coding\agrolav\balance
.\.venv\Scripts\python.exe -m app.main  # → 127.0.0.1:8100

# terminal 2 — frontend dev server
cd C:\Coding\agrolav\balance\frontend
npm run dev                             # → localhost:5174
```

## 11. Current status

The balance hub runs on `127.0.0.1:8100` and computes a balanced balance sheet
for Beheer (country_id=4). Verified against the remote database:

- `GET /api/balance/2026` → balanced activa = passiva = 3 111 662.19 (without
  the spaarrekening journal; with the mirror applied it is 3 031 662.19).
- Bank categories read live from `dbo.account.balance`.
- Non-bank categories read from `dbo.balance_opening` (+ journal where present).
- Verlies (2100) computed as the balancing figure.
- `PUT /api/balance/{year}/opening` upserts opening balances (bank + computed
  categories are skipped).
- `POST /api/balance/{year}/spaar-mirror` rebuilds the 1052 journal from the
  1051 "spaarrekening" rows; verified idempotent (repeated calls do not
  duplicate rows).

The balance frontend (standalone Vite+React app) is built and committed under
`frontend/`; it produces `dist/` (itself git-ignored — rebuild on deploy via
`npm ci && npm run build`). The Caddy `/balance/` route and the transaction-edit
interface are not yet deployed/built; see §13 and §9.6.
