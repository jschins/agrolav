# Database (proposed)

JSON under `workspaces/` is the source of truth until SQL Server is loaded.
The folder layout is already the grain of the future schema. **Stichtingen**
is a country in the same sense as Nederland and UK (own `categories.json`,
own `300`– category block), even though it is not a state:

```text
workspaces/
  nederland/
    categories.json
    dkg/
      anton_schins/
        secret/              # PEMs, personal_categories.json (stay files)
        2026/
          categorized_transactions.json
          category_totals.json
          downloaded_transactions.json
          <Bank>/            # optional per-bank copies
  uk/
    categories.json
    gph/
      xavier_bosch/
        …
  stichtingen/
    categories.json
    …
  users.db                   # SQLite logins (see SQLSERVER.md)
  upload_acl.json            # IP / upload policy (stays a file)
```

Hub paths are `workspaces/{country}/{center}/{person}` with
`categories.json` per country. See `MIGRATION_TO_SQLSERVER.md` phase A.

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
`cat_id_calculated = 104` in the fact table. The dimension projects 104 back
to `"12 Vervoer"`.

`saldo` and `datum` are appended on the same catalog so the matrix last rows
use country labels. UK later renames those two labels (e.g. `balance` /
`date`) without changing `category_id` or `local_code`. They never appear on
`transaction.cat_id_*`; the cells are `account.balance` and
`account.last_booked`.

Hundred-blocks so a later insert in one catalog does not shift the others:

| folder | `country_id` | `category_id` range | default currency |
|:-------|-------------:|:--------------------|:-----------------|
| nederland | 1 | 100– | EUR |
| uk | 2 | 200– | GBP |
| stichtingen | 3 | 300– | EUR |

UK and stichtingen `categories.json` may still be Dutch copies. Change
labels when those catalogs are written; do not change the ids.

Remainder / unmatched (JSON `18`, hub `DEFAULT_CATEGORY`) is **109** for
nederland, and the matching remainder row in the 200- and 300-blocks.

Do not use `IDENTITY` for `category_id`. Seed the table explicitly. JSON
keeps local codes until ETL; only SQL stores `100+`.

ETL join (for the **calculated** value):

```text
json.transactions[].category  +  person.country  →  cat_id_calculated
  WHERE dim_category.country     = person.country
    AND dim_category.local_code  = json.category
```

A user override (JSON `modifications[].category`) maps the same way into
`cat_id_set`. There is no overlay table.

---

## Tables

### `country`

| column | type | notes |
|:-------|:-----|:------|
| `country_id` | `INT` PK | 1 = nederland, 2 = uk, 3 = stichtingen |
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
| `is_remainder` | `BIT` | NL 109 / UK / stichtingen remainder |
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
totals are empty). Set `last_booked` to `MAX(transaction.booked_on)` for
that `account_id` after facts are loaded (JSON phase: max `date` in that
account’s `categorized_transactions.json`).

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

`transaction.bank_id` is NULL on the year-level consolidated file (merge of
all bank folders). Per-bank JSON and uploads always set it.

### `transaction`

No `transaction_modification` table. User category edits live on the row.

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
| `category` (base row) | `cat_id_calculated` | `INT` FK | **104** (not 12) |
| `modifications[].category` | `cat_id_set` | `INT` FK NULL | empty unless the user set a category |

Plus:

| column | type | notes |
|:-------|:-----|:------|
| `transaction_id` | `BIGINT` PK IDENTITY | |
| `person_id` | `INT` FK | |
| `account_id` | `INT` FK | this person’s account the row was booked on |
| `year` | `SMALLINT` | 2026 |
| `bank_id` | `INT` FK NULL | per-bank file vs consolidated |

`cat_id_set` is NULL on load except when JSON `modifications` contains a
`category` for that `id`. Recalc may refresh `cat_id_calculated`; it must
not clear `cat_id_set`. Effective category:

```sql
COALESCE(t.cat_id_set, t.cat_id_calculated)
```

JSON `modifications` that only change `description` write through to
`transaction.description` (the stored description is the effective one).

Unique `(person_id, year, bank_id, source_id)` with a filtered unique for
`bank_id IS NULL`.

Checks: `cat_id_calculated` and `cat_id_set` (when not null) belong to the
same country as `person_id`. `account.person_id = transaction.person_id`.

`counterparty_iban` is the JSON `iban` field (payee / payer). It is not
the person’s own account; that is `account_id` → `account.iban`.

### `category_total`

Snapshot of `category_totals.json` `categories` (name → amount string).
Can also be a view over `transaction` using `COALESCE(cat_id_set, cat_id_calculated)`.
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
| `country` | folder: `nederland`, `uk`, `stichtingen` |
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
- `downloaded_transactions.json` (optional later)
- `upload_acl.json`, `upload.log`

`categories.json` and `categorized_transactions.json` remain the JSON-store
until phase C; after load they become an export or a backup, not the live
write path.

---

## Reports

UI labels always go through `dim_category` on the **effective** category:

```sql
SELECT c.label, t.amount, t.booked_on, a.iban, a.account_name
FROM dbo.[transaction] t
JOIN dbo.person p ON p.person_id = t.person_id
JOIN dbo.center n ON n.center_id = p.center_id
JOIN dbo.account a ON a.account_id = t.account_id
JOIN dbo.dim_category c
  ON c.category_id = COALESCE(t.cat_id_set, t.cat_id_calculated)
WHERE n.folder = N'dkg'
  AND p.folder = N'anton_schins'
  AND t.year = 2026;
```

For a Nederland person this shows `"12 Vervoer"` wherever the effective id
is 104. A UK or stichtingen person with local code 12 joins to the 200- or
300-block, not to 104.

Matrix last rows (not summed from `transaction` amounts):

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
