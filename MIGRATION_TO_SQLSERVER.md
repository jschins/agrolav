# SQLite / JSON → SQL Server

Do this in three phases. Folder layout is already country-first
(`workspaces/nederland/…`, `workspaces/uk/…`, `workspaces/stichtingen/…`).
Hub code and SQL Server are not. **Stichtingen** is a third country: own
`categories.json`, own `300`– category ids. Category **labels and local
codes stay in JSON** until phase C; SQL then stores the `100+` surrogates
from `DATABASE.md`.

---

## Phase A — Hub reads the new JSON tree (implemented)

The hub binds **center** folders one level down from the country:

- first-level folder = **country** (`nederland`, `uk`, `stichtingen`)
- `categories.json` sits **next to the centers**
- SQLite `users.center` + `users.country`. Country logins
  (`nederland`, `united_kingdom`, `stichtingen`) have an empty center and
  see every center **in that country** only — never all countries at once.

Path: `{data_root}/{country}/{center}/{person}`. The HTTP API uses
`center` / `centers` for the center folder name.

JSON `category` values stay **8, 9, 12, 18**. Do not rewrite files to 104.

---

## Phase B — `users.db` → SQL Server

SQLite table (`hub/app/user_store.py`):

```text
users (id, username, title, center, person, format, created_at, updated_at, country)
```

Password = username (unchanged). `HUB_USERS_DB` can already point at another
path; point it at SQL Server after the cutover.

On SQL Server (`dbo.app_user` in `DATABASE.md`):

- Same columns, `NVARCHAR` / `DATE`.
- Add `country_id` (or resolve via `center.folder`).
- Keep `center` as the center folder so `dkg,jl` still splits the same way.

Practical bits:

- Driver: `ODBC Driver 18 for SQL Server` + `pyodbc` (or `mssql+pyodbc` if
  you introduce SQLAlchemy later). Azure SQL and a local/VPS instance use
  the same driver.
- Connection: env `HUB_DATABASE_URL` or `HUB_USERS_DB` equivalent; never
  commit the string.
- One-shot copy: dump SQLite → insert. `id` need not be preserved if
  nothing else FKs it (nothing does today).
- Hub: swap `sqlite3` in `user_store.py` only. JSON transactions stay on
  disk.

Leave `upload_acl.json` as a file. Tokens today are the shared scrypt
string keyed by `(person, center)`, not a SQL column.

---

## Phase C — Categories and transactions → SQL Server

Order matters: dimensions first, then facts. No `transaction_modification`
table.

### 1. Seed `country`, `center`, `person`

Walk the tree. `nederland/dkg/anton_schins` → country, center, person rows.
Same for `uk/…` and `stichtingen/…`. Do not invent centers the disk does
not have.

Set `person.number_accounts` from the number of distinct IBANs in that
person’s `account_balances` (or 1 if none yet). Then seed `account`.

### 2. Seed `bank`

Insert the rows in `DATABASE.md` (`bank_id` from 1; BoS = 5). This is the
SQL stand-in for `upload_acl.json` `bank modalities`: folder `BoS` +
`file_format` `csv` → only CSV uploads, processed as **BoS-csv**.

Match existing year subfolders (`BoS`, `RBS`, `LLOYDS`, `Natwest`) to
`bank_name_folder`. Unknown folders fail the load.

### 3. Seed `account`

One row per IBAN on the person. `person_id` is constant; `iban` is not.
`account_name` and `balance` from `account_balances[]`. `last_booked` is
filled after transactions load (`MAX(booked_on)` per `account_id`). After
insert, `COUNT(account)` for that person must equal `person.number_accounts`.

### 4. Seed `dim_category` from each `categories.json`

For each country file, assign `category_id` in **file order**:

- nederland: 100, 101, … (08 Naar kas = 100, …, 12 Vervoer = **104**,
  then **113 saldo** / **114 datum**)
- uk: 200, 201, … (same local codes 22/23 for the two matrix footers)
- stichtingen: 300, 301, …

Store `local_code = int(label[:2])` so ETL can map JSON `12` → 104 for
nederland only (200-block for uk, 300-block for stichtingen).

Load `category_term` from the JSON arrays. Load `type_abbreviation`.
Then load personal term overlays (`secret/personal_categories.json`) with
`person_id` set.

### 5. Load `transaction`

For each `**/YYYY/categorized_transactions.json` and each
`**/YYYY/<Bank>/categorized_transactions.json`:

- Parse `DD-MM-YYYY` → `DATE`.
- Parse amount strings (`-73.14`) → `DECIMAL(18,2)`.
- JSON `iban` → `counterparty_iban` (other party; may be empty).
- Set `account_id` to this person’s account the row was booked on (bank
  folder, totals `files[]`, or Enable Banking account). Not the JSON `iban`
  field when that field is a counterparty.
- `cat_id_calculated`: join JSON `transactions[].category` as in
  `DATABASE.md` (JSON 12 + nederland → 104). Fail if the local code is
  missing from that country’s dim.
- `cat_id_set`: NULL, except when `modifications` has `category` for that
  `id` (JSON 19 + nederland → 110). Description-only mods write through to
  `description`.

Year-level file = `bank_id` NULL (consolidated). A `{year}/BoS/` file sets
`bank_id = 5`.

Do not create a modifications table. After load, a UI category edit writes
only `cat_id_set`. Recalc updates `cat_id_calculated` only.

### 6. Load totals and balances

`category_totals.json`: map each **label** to `category_id` (not via local
code in the totals file — keys are the labels). `account_balances` attach
to `account_id`.

After a successful load, recalc can write SQL instead of rewriting JSON.
Until the hub write path is switched, treat SQL as read-only replica.

### 7. Cut over hub writes

Last: category edits (`cat_id_set`), CSV import, and recalc persist to SQL.
JSON can stay as export/backup. PEMs and CSVs never move.

---

## Mapping reminder (phase C)

JSON (nederland, unchanged):

```json
"category": 12
```

SQL:

```text
transaction.cat_id_calculated = 104
transaction.cat_id_set        = NULL   -- unless the user overrode it
dim_category: 104 → country = nederland, local_code = 12, label = '12 Vervoer'
```

Do not store 12 in SQL. Do not store 104 in JSON until you deliberately
change the JSON schema (not required).

---

## What not to migrate

| stays a file | reason |
|:-------------|:-------|
| `secret/*.pem`, `consent.json` | Enable Banking credentials |
| uploaded CSV / xlsx | import artefacts |
| `downloaded_transactions.json` | optional later |
| `upload_acl.json`, `upload.log` | IP policy |

---

## Instance

Same VPS as `DEPLOYMENT_GUIDE.md`, or Azure SQL. Hub stays on `:8200`
localhost; only the connection string changes in B and C.

Install on Ubuntu: Microsoft ODBC 18, then `uv add pyodbc` on the hub.
Windows dev: the same driver from Microsoft.

---

## Check order

1. Phase A: open a nederland, uk, and stichtingen person; each uses its
   own `categories.json`, not a missing root file.
2. Phase B: login list identical to SQLite; personal vs local vs
   regional_admin still derived from `person` + `center`.
3. Phase C: anton’s `010305258369428750000000_0` has
   `cat_id_calculated = 104`, `cat_id_set` NULL, and joins to
   `"12 Vervoer"`; a UK or stichtingen row with JSON `12` joins to the 200-
   or 300-block, not to 104. A person with several IBANs has
   `number_accounts` equal to the count of `account` rows, all sharing
   `person_id`. Matrix last rows: `saldo` from `account.balance` (summed
   per person), `datum` from `MAX(account.last_booked)`.
