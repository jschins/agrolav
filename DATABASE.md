# Database (proposed)

## write backup from existing database

```BACKUP DATABASE agrolav
TO DISK = '/var/opt/mssql/backup/agrolav19.bak'
WITH
    INIT,
    COMPRESSION,
    CHECKSUM,
    STATS = 10;
```

Note that the distination folder on disk (C:/SQLBackups) is determined by
    volumes:
      - "C:/SQLBackups:/var/opt/mssql/backup"
in file
C:\Coding\agrolav\docker-compose.sqlserver.yml



## upload backup to overwrite existing database



SQL Server (agrolav-sql) is the source of truth. The folder layout is gone:
the schema mirrors the old grain directly:

```text
data/ (removed)             -> dir is gone; everything is SQL
country                     -> dbo.country
center                      -> dbo.center
person                      -> dbo.person
account                     -> dbo.account
transaction                 -> dbo.transaction_<country>
categories.json             -> dbo.table_header_term / dbo.type_rule / dbo.dim_category
upload_acl.json             -> dbo.bank_modality / dbo.hub_ip
secret/profile.json + consent.json -> dbo.enable_connection
users.db                    -> removed (logins are dbo.country/center/person)
```

Hub storage is SQL Server only. The two always-overwritten flat JSON scratch
files — `downloaded_transactions.json` and `categorized_transactions.json` —
live at the `AGROLAV_SQL_DISK` mount root (see `MIGRATION_TO_SQLSERVER.md`).

---

## Category IDs

JSON today stores the **local code** taken from the first two digits of the
label. `"12 Vervoer"` is stored as `category: 12`.

SQL Server stores a **stable surrogate** instead. All categories, all
countries, are numbered from 100 upwards. Nederland is assigned in catalog
order:

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

So the JSON row with `"category": 12` for anyone under `nederland/` becomes
`category_id = 104` in `transaction_nederland`. The dimension projects
104 back to `"12 Vervoer"`.

`saldo` and `datum` are appended on the same catalog so the matrix last rows
use country labels. UK later renames those two labels (e.g. `balance` /
`date`) without changing `category_id` or `local_code`. They never appear on
`transaction_*.category_id`; the cells are `account.balance` and
`account.last_booked`.

Hundred-blocks so a later insert in one catalog does not shift the others:

| folder | `country_id` | `category_id` range | default currency |
|:-------|-------------:|:--------------------|:-----------------|
| nederland | 1 | 100– | EUR |
| uk | 2 | 200– | GBP |

UK `categories.json` may still be a Dutch copy. Change labels when that
catalog is written; do not change the ids.

Remainder / unmatched (JSON `18`, hub `DEFAULT_CATEGORY`) is **109** for
nederland, and the matching remainder row in the 200-block.

Do not use `IDENTITY` for `category_id`. Seed the table explicitly. JSON
keeps local codes until ETL; only SQL stores `100+`.

ETL join:

```text
json.transactions[].category  +  person.country  →  category_id
  WHERE dim_category.country     = person.country
    AND dim_category.local_code  = json.category
```

A user override overwrites that same `category_id` and sets `modification` to
1 or 3. There is no overlay column.

---

## Tables

### `country`

| column | type | notes |
|:-------|:-----|:------|
| `country_id` | `INT` PK | 1 = nederland, 2 = uk |
| `folder` | `NVARCHAR(32)` unique | JSON folder name |
| `currency_default` | `CHAR(3)` | `EUR` / `GBP` (accounts may still differ) |

### `dim_category`

Country-specific catalog. One row per (country, local code).

| column | type | notes |
|:-------|:-----|:------|
| `category_id` | `INT` PK | 100, 101, … (see above) |
| `country_id` | `INT` FK | |
| `local_code` | `INT` NOT NULL | JSON `category` value (8, 9, 12, 18, …) |
| `label` | `NVARCHAR(128)` NOT NULL | `"12 Vervoer"`; footers `"saldo"` / `"datum"` |
| `is_remainder` | `BIT` | NL 109 / UK remainder |
| `matrix_role` | `NVARCHAR(32)` NULL | `NULL` for booking categories; `balance` (local 22) or `last_booked` (local 23) |

Unique: `(country_id, local_code)`. Unique: `(country_id, label)`.
Footer rows have empty `category_term` lists and must not be assigned to
transactions.

### `category_term`

Keyword lists from `categories.json` (`"12 Vervoer": ["total", "ns", …]`).

| column | type | notes |
|:-------|:-----|:------|
| `category_id` | `INT` FK | |
| `term` | `NVARCHAR(256)` | as stored, including `#` and `&&` |
| `sort_order` | `INT` | file order |

Personal overlays (`secret/personal_categories.json`) are the same table
with `person_id` set; country-catalog rows have `person_id` NULL.

### `type_abbreviation`

From `categories.json` `abbreviations` (Betaalautomaat → BA). Per country.

### `center`

| column | type | notes |
|:-------|:-----|:------|
| `center_id` | `INT` PK IDENTITY | |
| `country_id` | `INT` FK | |
| `folder` | `NVARCHAR(64)` | `dkg`, `gph`, … |
| Unique `(country_id, folder)` | | |

### `person`

| column | type | notes |
|:-------|:-----|:------|
| `person_id` | `INT` PK IDENTITY | |
| `center_id` | `INT` FK | |
| `folder` | `NVARCHAR(128)` | `anton_schins` |
| `number_accounts` | `INT` NOT NULL | count of rows in `account` for this person |
| Unique `(center_id, folder)` | | |

Country is `person → center → country`. Check:
`person.number_accounts = COUNT(*) FROM account WHERE account.person_id = person.person_id`.

### `account`

One row per bank account the person holds. `person_id` is the same on every
row for a multi-account person. `iban` is unique per person. `account_name`
may repeat (Xavier’s BoS/Lloyds names equal the IBAN) or differ (Natwest
`LINDALE ED FOUND` vs `GREYGARTH HALL`).

| column | type | notes |
|:-------|:-----|:------|
| `account_id` | `INT` PK | |
| `person_id` | `INT` FK | does not vary across that person’s accounts |
| `iban` | `NVARCHAR(64)` NOT NULL | necessarily varies per person |
| `account_name` | `NVARCHAR(64)` NOT NULL | may or may not vary |
| `balance` | `DECIMAL(18,2)` | live figure; matrix `saldo` / `balance` row |
| `last_booked` | `DATE` NULL | date of the latest booking on this account; matrix `datum` / `date` row |

Unique: `(person_id, iban)`. Seed `iban` / `account_name` / `balance` from
`category_totals.json` `account_balances[]` (and Enable Banking profile if
totals are empty). Set `last_booked` to `MAX(booked_on)` on that country’s
`transaction_*` table for that `account_id` after facts are loaded (JSON
phase: max `date` in that account’s `categorized_transactions.json`).

A person-column matrix cell is the **sum** of `balance` and the **max** of
`last_booked` across that person’s accounts (or the one account in a bank
folder view).

### `bank`

Lookup that replaces `upload_acl.json` `bank modalities`. `bank_id` is
assigned from 1 (no `IDENTITY`). Unique on `bank_name_folder`.

| column | type | notes |
|:-------|:-----|:------|
| `bank_id` | `INT` PK | 1, 2, … |
| `bank_name_official` | `NVARCHAR(64)` NOT NULL | `"Bank of Scotland"` |
| `bank_name_folder` | `NVARCHAR(64)` NOT NULL | year subfolder: `"BoS"` |
| `file_format` | `NVARCHAR(64)` NOT NULL | `"csv"` or `"excel"` |

The upload path is `{person}/{year}/{bank_name_folder}/`. Only files of
`file_format` are accepted. The processor is
`{bank_name_folder}-{file_format}` (same string as today’s `BoS-csv`,
`RBS-csv`, …).

Example row (`bank_id = 5`):

| `bank_id` | `bank_name_official` | `bank_name_folder` | `file_format` |
|----------:|:---------------------|:-------------------|:--------------|
| 5 | Bank of Scotland | BoS | csv |

→ upload CSV only into `…/2026/BoS/`, parse with the **BoS-csv** method.

Seed from current `bank modalities` (BoS is 5 as in the example):

| `bank_id` | `bank_name_official` | `bank_name_folder` | `file_format` | processor |
|----------:|:---------------------|:-------------------|:--------------|:----------|
| 1 | NatWest | Natwest | csv | Natwest-csv |
| 2 | Royal Bank of Scotland | RBS | csv | RBS-csv |
| 3 | Lloyds Bank | LLOYDS | csv | LLOYDS-csv |
| 5 | Bank of Scotland | BoS | csv | BoS-csv |

`file_format` `excel` is allowed for a later NL row; it is not in the seed
until that bank has a folder and an excel processor.

`transaction_*.bank_id` is NULL on the year-level consolidated file (merge of
all bank folders). Per-bank JSON and uploads always set it.

### `transaction_nederland` / `transaction_uk`

One booking table per country folder. Same columns on both. A Nederland
row never lands in `transaction_uk`. Category ids on each table are checked
against that country’s hundred-block (NL 100–199, UK 200–299), so JSON
`12` cannot become 104 on a UK row.

| folder | table |
|:-------|:------|
| nederland | `transaction_nederland` |
| uk | `transaction_uk` |

No `transaction_modification` table. User category and description edits
overwrite the row.

| JSON key | column | type | example (anton, Vervoer) |
|:---------|:-------|:-----|:-------------------------|
| `id` | `source_id` | `NVARCHAR(128)` | `010305258369428750000000_0` |
| `amount` | `amount` | `DECIMAL(18,2)` | `-73.14` |
| `currency` | `currency` | `CHAR(3)` | `EUR` |
| `type` | `bank_type` | `NVARCHAR(64)` | `Betaalautomaat` |
| `name` | `counterparty_name` | `NVARCHAR(512)` | `Total Nn001398 Pto` |
| `iban` | `counterparty_iban` | `NVARCHAR(64)` | other party; may be empty |
| `description` | `description` | `NVARCHAR(MAX)` | |
| `date` | `booked_on` | `DATE` | `2026-08-09` (JSON is `DD-MM-YYYY`) |
| `category` | `category_id` | `INT` FK NULL | **104** (not 12); NULL only while `modification` is -1 |
| `modification` | `modification` | `SMALLINT` | -1 uncalculated; 0 none; 1 category; 2 description; 3 both |
| `hit` | `hit` | `NVARCHAR(64)` NULL | `P:{term}` or `G:{term}` from iRCfT; NULL for typerules / remainder |

Plus:

| column | type | notes |
|:-------|:-----|:------|
| `transaction_id` | `BIGINT` PK IDENTITY | |
| `person_id` | `INT` FK | |
| `account_id` | `INT` FK | this person’s account the row was booked on |
| `year` | `SMALLINT` | 2026 |
| `bank_id` | `INT` FK NULL | per-bank file vs consolidated |

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
remainder leave it NULL. Term add/delete uses iRCfT: only rows whose hit is
outranked (add) or whose hit is the deleted term (delete) are rewritten.

Unique `(person_id, year, bank_id, source_id)` with a filtered unique for
`bank_id IS NULL`, per table.

Checks: `category_id` (when not null) belongs to the same country as the
table. `account.person_id` matches the booking row’s `person_id`. ETL inserts
only people from that country into that table.

`counterparty_iban` is the JSON `iban` field (payee / payer). It is not
the person’s own account; that is `account_id` → `account.iban`.

### `category_total`

Snapshot of `category_totals.json` `categories` (name → amount string).
Can also be a view over that country’s `transaction_*` table using
`category_id`.
If stored:

| column | type |
|:-------|:-----|
| `person_id`, `year`, `bank_id` NULL | same grain as files |
| `category_id` | INT FK (104, not the label) |
| `amount` | `DECIMAL(18,2)` |

### `account_balance`

Yearly snapshot from `category_totals.json` `account_balances[]`, keyed by
`account_id` rather than repeating IBAN/name.

| column | type | notes |
|:-------|:-----|:------|
| `person_id`, `year`, `bank_id` | | |
| `account_id` | `INT` FK | |
| `currency` | `CHAR(3)` | |
| `balance` | `DECIMAL(18,2)` | |
| `uid` | `UNIQUEIDENTIFIER` NULL | present on some NL files |
| `source_file` | child table | JSON `files[]` when present |

### `app_user`

SQLite `users` (and later SQL Server) matches `users.csv`:

| column | notes |
|:-------|:------|
| `username` | login; password = username |
| `country` | folder: `nederland`, `uk` |
| `center` | folder: `dkg`, `gph`, … |
| `person` | person folder, or empty |
| `format` | `secret` / `excel` / `multiple` / a bank csv id |

Access: person set → personal; person empty and one center → local; person
empty, center empty, country set → country for **that country only**.
There is no login that spans all countries.

---

## What stays on disk

Not loaded into SQL Server:

- `secret/*.pem`, `consent.json`
- uploaded CSVs / xlsx
- `downloaded_transactions.json` (optional later) — after a bank download the
  hub also writes it inside the SQL Server container at
  `/var/opt/mssql/backup/downloaded_transactions.json` (the host dir that is
  mounted there is `AGROLAV_SQL_DISK`; see `docker-compose.sqlserver.yml`)
- `upload_acl.json`, `upload.log`

`categories.json` and `categorized_transactions.json` remain the JSON-store
until phase C; after load they become an export or a backup, not the live
write path.

---

## Reports

UI labels always go through `dim_category` on the **effective** category:

```sql
SELECT c.label, t.amount, t.booked_on, a.iban, a.account_name
FROM dbo.transaction_nederland t
JOIN dbo.person p ON p.person_id = t.person_id
JOIN dbo.center n ON n.center_id = p.center_id
JOIN dbo.account a ON a.account_id = t.account_id
JOIN dbo.dim_category c
  ON c.category_id = t.category_id
WHERE n.folder = N'dkg'
  AND p.folder = N'anton_schins'
  AND t.year = 2026;
```

For a Nederland person this shows `"12 Vervoer"` wherever the effective id
is 104. Query `transaction_uk` for the UK; JSON `12` there is 204, not 104.

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


