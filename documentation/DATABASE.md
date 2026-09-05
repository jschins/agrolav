# Database

SQL Server database **agrolav** is the source of truth. Logins, bookings,
categories, bank connections, and IP allowlists all live here.

Schema sources in the repo:

- `hub/sql/phase_c.sql` — base schema (do not run against a live database; it drops tables)
- `hub/sql/json_independence.sql` — `table_header_term`, `type_rule`, `bank_modality`, `enable_connection`, `enable_redirect`, `visitor_ip`
- `hub/sql/visitor_ip.sql` — `egress_ip` columns and `dbo.visitor_ip` (idempotent)
- `hub/sql/administrator.sql` — `dbo.administrator` (idempotent)
- Hub startup creates `dbo.consent_pending` if it is missing

---

## Write a backup

```sql
BACKUP DATABASE agrolav
TO DISK = '/var/opt/mssql/backup/agrolav.bak'
WITH
    INIT,
    COMPRESSION,
    CHECKSUM,
    STATS = 10;
```

The destination folder on disk (`C:/SQLBackups`) is the Docker volume in
`docker-compose.sqlserver.yml`:

```text
volumes:
  - "C:/SQLBackups:/var/opt/mssql/backup"
```

Restoring a backup over the remote database is in `deployment.md`.

---

## Category IDs

SQL Server stores a **stable surrogate**. All categories, all countries, are
numbered from 100 upwards. Nederland is assigned in catalog order:

| `category_id` | country    | `local_code` | label |
|--------------:|:-----------|-------------:|:------|
| 100 | nederland | 8 | 08 Naar kas |
| 101 | nederland | 9 | 09 Pension |
| 102 | nederland | 10 | 10 Gezondheid |
| 103 | nederland | 11 | 11 Convivencias |
| **104** | nederland | **12** | **12 Vervoer** |
| 105 | nederland | 13 | 13 Kleding Fiets |
| 106 | nederland | 14 | 14 Gewone uitgaven |
| 107 | nederland | 15 | 15 Buitengewone uitgaven |
| 108 | nederland | 16 | 16 Auto |
| 109 | nederland | 18 | 18 Overige uitgaven |
| 110 | nederland | 19 | 19 Giften |
| 111 | nederland | 20 | 20 Werk |
| 112 | nederland | 21 | 21 Familie |
| **113** | nederland | **22** | **saldo** (matrix footer; not a booking category) |
| **114** | nederland | **23** | **datum** (matrix footer; not a booking category) |

The UI still shows local codes (`"12 Vervoer"`). The dimension projects 104
back to that label. `saldo` and `datum` are on the same catalog so the matrix
last rows use country labels. UK later renames those two labels (e.g.
`balance` / `date`) without changing `category_id` or `local_code`. They never
appear on `transaction_*.category_id`; the cells are `account.balance` and
`account.last_booked`.

Hundred-blocks so a later insert in one catalog does not shift the others:

| country | `country_id` | `category_id` range | default currency |
|:--------|-------------:|:--------------------|:-----------------|
| nederland | 1 | 100– | EUR |
| uk | 2 | 200– | GBP |

Remainder / unmatched (local 18, hub `DEFAULT_CATEGORY`) is **109** for
nederland, and the matching remainder row in the 200-block.

Do not use `IDENTITY` for `category_id`. Seed the table explicitly.

A user override overwrites that same `category_id` and sets `modification` to
1 or 3. There is no overlay column.

---

## Tables

### `country`

| column | type | notes |
|:-------|:-----|:------|
| `country_id` | `INT` PK | 1 = nederland, 2 = uk, … |
| `username` | `NVARCHAR(32)` unique | the country login |
| `title` | `NVARCHAR(256)` | display name |
| `currency_default` | `CHAR(3)` | `EUR` / `GBP` (accounts may still differ) |
| `egress_ip` | `VARCHAR(256)` NULL | comma-separated allowlist; empty or NULL admits nobody |
| `digits` | `INT` | category-code width in the UI (default 2; 4 on some countries) |

### `dim_category`

Country-specific catalog. One row per (country, local code).

| column | type | notes |
|:-------|:-----|:------|
| `category_id` | `INT` PK | 100, 101, … (see above) |
| `country_id` | `INT` FK | |
| `local_code` | `INT` NOT NULL | UI code (8, 9, 12, 18, …) |
| `label` | `NVARCHAR(128)` NOT NULL | `"12 Vervoer"`; footers `"saldo"` / `"datum"` |
| `is_remainder` | `BIT` | NL 109 / UK remainder |
| `matrix_role` | `NVARCHAR(32)` NULL | `NULL` for booking categories; `balance` (local 22) or `last_booked` (local 23) |

Unique: `(country_id, local_code)`. Unique: `(country_id, label)`.
Footer rows have empty `category_term` lists and must not be assigned to
transactions.

### `category_term`

Keyword lists that assign bookings to categories.

| column | type | notes |
|:-------|:-----|:------|
| `category_id` | `INT` FK | |
| `person_id` | `INT` FK NULL | NULL = country catalog; set = personal overlay |
| `term` | `NVARCHAR(256)` | as stored, including `#` and `&&` |
| `sort_order` | `INT` | file order |

### `type_abbreviation`

Bank-type abbreviations (Betaalautomaat → BA). Per country.

### `type_rule`

Bank `bank_type` → `category_id`. Typerules beat all keywords.

### `table_header_term`

Matrix / list column headers per country (`term_key` → `label`).

### `center`

| column | type | notes |
|:-------|:-----|:------|
| `center_id` | `INT` PK IDENTITY | |
| `country_id` | `INT` FK | |
| `username` | `NVARCHAR(64)` unique | `dkg`, `gph`, … — the center login |
| `title` | `NVARCHAR(256)` | display name |
| `egress_ip` | `VARCHAR(256)` NULL | comma-separated allowlist; empty or NULL admits nobody |

### `person`

| column | type | notes |
|:-------|:-----|:------|
| `id` | `INT` PK IDENTITY | referenced as `person_id` from other tables |
| `username` | `NVARCHAR(128)` unique | the person login |
| `title` | `NVARCHAR(256)` | display name |
| `country_id` | `INT` FK | |
| `center_id` | `INT` FK | |
| `number_of_accounts` | `INT` NOT NULL | count of rows in `account` for this person |
| `password_hash` | `NVARCHAR(256)` NULL | scrypt; see `double_login.md` |
| `mobile_phone` | `NVARCHAR(32)` NULL | E.164; SMS second step when set |

Country is `person → center → country`. Check:
`person.number_of_accounts = COUNT(*) FROM account WHERE account.person_id = person.id`.

### `account`

One row per bank account the person holds. `person_id` is the same on every
row for a multi-account person. `iban` is unique per person.

| column | type | notes |
|:-------|:-----|:------|
| `account_id` | `INT` PK | |
| `person_id` | `INT` FK | → `dbo.person.id` |
| `iban` | `NVARCHAR(64)` NOT NULL | unique per person |
| `account_name` | `NVARCHAR(64)` NOT NULL | may or may not vary |
| `format` | `NVARCHAR(64)` NULL | CSV layout, Enable ASPSP, or excel |
| `balance` | `DECIMAL(18,2)` | live figure; matrix `saldo` / `balance` row |
| `last_booked` | `DATE` NULL | latest booking on this account; matrix `datum` / `date` row |
| `connection_id` | `INT` FK NULL | Enable Banking connection; NULL for uploaded accounts |
| `uid` | `NVARCHAR(128)` NULL | Enable Banking account uid (required when `connection_id` is set) |
| `identification_hash` | `NVARCHAR(128)` NULL | |

Unique: `(person_id, iban)`. A person-column matrix cell is the **sum** of
`balance` and the **max** of `last_booked` across that person’s accounts.

### `bank`

Lookup of bank processors. `bank_id` is assigned from 1 (no `IDENTITY`).

| column | type | notes |
|:-------|:-----|:------|
| `bank_id` | `INT` PK | 1, 2, … |
| `bank_name_official` | `NVARCHAR(64)` NOT NULL | `"Bank of Scotland"` |
| `file_format` | `NVARCHAR(64)` NOT NULL | `"csv"` or `"excel"` |

### `bank_modality`

Maps an upload folder name to a `bank_id`.

### `enable_connection`

Enable Banking credentials and session for a person.

| column | type | notes |
|:-------|:-----|:------|
| `connection_id` | `INT` PK IDENTITY | |
| `person_id` | `INT` FK NULL | → `dbo.person.id` |
| `app_id` | `NVARCHAR(128)` | Enable Banking application id |
| `session_id` | `NVARCHAR(256)` | live bank session |
| `valid_until` | `DATETIME2` | consent expiry |
| `created_at` | `DATETIME2` | |
| `pem` | `NVARCHAR(MAX)` | application private key |

### `enable_redirect`

Last Enable Banking redirect payload per person.

### `consent_pending`

Short-lived callback tokens while a bank consent is in flight. The hub
creates this table at startup if it is missing.

### `transaction_nederland` / `transaction_uk` / …

One booking table per country. Same columns on each. A Nederland row never
lands in `transaction_uk`. Category ids on each table are checked against
that country’s hundred-block (NL 100–199, UK 200–299).

User category and description edits overwrite the row. There is no
modifications table.

| column | type | notes |
|:-------|:-----|:------|
| `transaction_id` | `BIGINT` PK IDENTITY | |
| `person_id` | `INT` FK | |
| `account_id` | `INT` FK | this person’s account the row was booked on |
| `year` | `SMALLINT` | 2026 |
| `bank_id` | `INT` FK NULL | per-bank file vs consolidated |
| `source_id` | `NVARCHAR(128)` | bank’s id for the booking |
| `parent_source_id` | `NVARCHAR(128)` NULL | set on split lines |
| `amount` | `DECIMAL(18,2)` | |
| `bank_type` | `NVARCHAR(64)` | e.g. `Betaalautomaat` |
| `counterparty_name` | `NVARCHAR(512)` | |
| `counterparty_iban` | `NVARCHAR(64)` | other party; may be empty |
| `description` | `NVARCHAR(MAX)` | |
| `booked_on` | `DATE` | |
| `category_id` | `INT` FK | **104** for NL Vervoer, not 12 |
| `modification` | `SMALLINT` | -1 uncalculated; 0 none; 1 category; 2 description; 3 both |
| `hit` | `NVARCHAR(64)` NULL | `P:{term}` or `G:{term}`; NULL for typerules / remainder |

`modification` records what the user touched:

| `modification` | meaning | table CSS |
|---------------:|:--------|:----------|
| -1 | not yet categorized (fresh download/upload) | — |
| 0 | categorized; user has not edited | — |
| 1 | user overwrote only `category_id` | category cell **bold** |
| 2 | user overwrote only `description` | whole row blue |
| 3 | user overwrote both | bold + blue |

Recalc writes `category_id` only when `modification` is -1, 0, or 2. After the
first calculation, -1 becomes 0. Flags 1 and 3 keep the user's category.

`hit` is the keyword that won (`P:` personal or `G:` general). Typerules and
remainder leave it NULL.

Unique `(person_id, year, bank_id, source_id)` with a filtered unique for
`bank_id IS NULL`, per table.

`counterparty_iban` is the payee / payer. It is not the person’s own account;
that is `account_id` → `account.iban`.

### `category_total`

Snapshot of category amounts per person/year (and optional bank).

| column | type |
|:-------|:-----|
| `person_id`, `year`, `bank_id` NULL | same grain as files |
| `category_id` | INT FK (104, not the label) |
| `amount` | `DECIMAL(18,2)` |

### `uploaded_files`

One row per spreadsheet or bank CSV taken in for an account.

| column | type | notes |
|:-------|:-----|:------|
| `uploaded_file_id` | `INT` PK IDENTITY | |
| `account_id` | `INT` FK | → `dbo.account` |
| `file_name` | `NVARCHAR(256)` | as uploaded |
| `format` | `NVARCHAR(64)` NULL | parser that read it |

### `administrator`

Egress addresses allowed for **every** country and center. Hand-edited in
SSMS; there is no UI for it. See `hub/sql/administrator.sql`.

| column | type | notes |
|:-------|:-----|:------|
| `egress_ip` | `VARCHAR(45)` PK | one address per row, IPv4 or IPv6 |

### `visitor_ip`

Login attempts, so you can see who is knocking. See `hub/sql/visitor_ip.sql`.

| column | type | notes |
|:-------|:-----|:------|
| `visitor_id` | `INT` PK IDENTITY | |
| `egress_ip` | `VARCHAR(45)` | 45 fits a compressed IPv6 address (39) |
| `username` | `VARCHAR(64)` NOT NULL, default `''` | `''` for a refused attempt |
| Unique `(egress_ip, username)` | | the only uniqueness condition; repeats collapse |

Not recorded: loopback and LAN addresses, anything listed in
`dbo.administrator`, and — on a development hub (`HUB_DEV_LOGIN`) — nothing
at all.

---

## Logins

A login is a row in one of three tables, and which one it is decides the
access level:

| Row in | Access | Password |
|:-------|:-------|:---------|
| `dbo.person` | that person only | scrypt hash in `password_hash`, plus an SMS code when `mobile_phone` is set |
| `dbo.center` | that center | derived formula (prefix + username) |
| `dbo.country` | every center in that country | derived formula (prefix + username) |

No login spans all countries. Country and center logins are gated by egress
IP; person logins are not. A country or center may sign in only from an
address listed in `dbo.administrator` or in its own `egress_ip` column — the
allowed set is the **sum** of the two, and an empty column admits nobody, so a
database with no addresses listed anywhere refuses every country and center
login.

A development hub (`HUB_DEV_LOGIN=1` in `hub/.env`, caller on loopback) skips
the gate and writes no `visitor_ip` rows: there the browser, client and hub
share one machine and no public address exists to list. Never set that flag
on the server.

---

## Reports

UI labels always go through `dim_category` on the **effective** category:

```sql
SELECT c.label, t.amount, t.booked_on, a.iban, a.account_name
FROM dbo.transaction_nederland t
JOIN dbo.person p ON p.id = t.person_id
JOIN dbo.center n ON n.center_id = p.center_id
JOIN dbo.account a ON a.account_id = t.account_id
JOIN dbo.dim_category c
  ON c.category_id = t.category_id
WHERE n.username = N'dkg'
  AND p.username = N'anton_schins'
  AND t.year = 2026;
```

For a Nederland person this shows `"12 Vervoer"` wherever the effective id
is 104. Query `transaction_uk` for the UK; local code 12 there is 204, not 104.

Matrix last rows (not summed from `transaction_*` amounts):

```sql
-- per account (SQL); matrix person column = SUM(balance), MAX(last_booked)
SELECT a.account_name, a.balance, a.last_booked
FROM dbo.account a
WHERE a.person_id = @person_id;

-- header labels from dim_category.matrix_role (NL saldo/datum; UK later
-- balance/date on the same local_codes 22 and 23)
SELECT local_code, label, matrix_role
FROM dbo.dim_category
WHERE country_id = @country_id AND matrix_role IS NOT NULL;
```

---

## Occasional DDL (run in SSMS; keep local and remote identical)

```sql
INSERT INTO dbo.table_header_term (country_id, term_key, label)
SELECT 3, term_key, label
FROM dbo.table_header_term
WHERE country_id = 1;

INSERT INTO dbo.table_header_term (country_id, term_key, label)
SELECT 4, term_key, label
FROM dbo.table_header_term
WHERE country_id = 1;

ALTER TABLE dbo.transaction_beheer
DROP CONSTRAINT ck_txn_beheer_cat;

ALTER TABLE dbo.transaction_beheer
ADD CONSTRAINT ck_txn_beheer_cat
CHECK ([category_id] >= 1000 AND [category_id] < 10000);

ALTER TABLE dbo.country ADD digits INT NOT NULL CONSTRAINT DF_num_digits DEFAULT 2;
UPDATE dbo.country SET digits = 4 WHERE country_id = 4;

UPDATE dbo.dim_category
SET label = SUBSTRING(label, 4, LEN(label))
WHERE matrix_role NOT IN ('balance', 'last_booked');
```
