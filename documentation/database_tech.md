# Database

SQL Server database **agrolav** is the source of truth. Logins, bookings,
categories, bank connections, and IP allowlists all live here. Backup and
restore for both instances are in this file, not in `deployment_tech.md`.

Schema sources in the repo:

- `hub/sql/phase_c.sql` — base schema (do not run against a live database; it drops tables)
- `hub/sql/json_independence.sql` — `language`, `country.language_id`, `bank_modality`, `enable_connection`, `enable_redirect`, `visitor_ip`
- `hub/sql/visitor_ip.sql` — `egress_ip` columns and `dbo.visitor_ip` (idempotent)
- `hub/sql/egress_ip.sql` — `dbo.egress_ip` (idempotent)
- Hub startup requires `dbo.consent_pending` (create it in SSMS if missing)
- `maaltijden/sql/maaltijden.sql` — `dbo.maaltijden_users` and `dbo.maaltijden_data` (run in SSMS; the app does not create them)

The folder names `local_backups` and `remote_backups` mean **where the file
was written**, and they are the same on both machines. Each SQL container
bind-mounts its host backup root at `/var/opt/mssql/backup`, so SSMS always
uses the container path (a Windows path such as `C:\SQLBackups\…` fails with
MSG 3201). The pull script writes `agrolav.bak` on the droplet, copies it
here, then **deletes** it (backups hold Enable Banking keys). Dated names
(`agrolav20260917_1150.bak`) are local archive only.

| | Local PC | Remote droplet |
|:--|:---------|:---------------|
| Host root | `C:\SQLBackups` | `/opt/sql_backups` |
| Container | `agrolav-sql` | `MSSQL2022` |
| Mount | `C:/SQLBackups` → `/var/opt/mssql/backup` | `/opt/sql_backups` → `/var/opt/mssql/backup` |
| SSMS | `127.0.0.1,1433` on this PC | authorized computer, through the VPC |
| Written here | `…/local_backups/` | `…/remote_backups/` |
| Copy of the other side | `…/remote_backups/` | `…/local_backups/` |

SSH / `scp` always use port **4523**. SQL Server in the container runs as uid
**10001** (`mssql`). `/opt/sql_backups` itself stays owned by `agrolav`.
The two folders under it change owner for each step. Who owns the folder,
and who owns an existing `.bak`, is what makes `BACKUP` and `scp` succeed
or fail. The sequences below hand the folder to the account that needs it,
then hand it back.

---

<!-- {en:database[5],sql,server,bookings,categories} -->
<!-- {nl:database[5],sql,server,boekingen,categorieën} -->

## 1. The remote database

Container `MSSQL2022` on the database host, mount `/opt/sql_backups` →
`/var/opt/mssql/backup`. Confirm it is up with `sudo docker ps`. The VPC
firewall admits the authorized computer and the application computer on
port 1433.

The host root is owned by `agrolav` (`drwxr-xr-x`). It has only the two
mirrored folders — no `.bak` files at the root:

```text
/opt/sql_backups/                  host, bind-mounted
├── local_backups/                 a .bak copied up from the PC (§1.2)
└── remote_backups/                written here by MSSQL2022 (§1.1), then deleted after the pull
```

Inside the container that is the same disk:

```text
/var/opt/mssql/backup/local_backups/
/var/opt/mssql/backup/remote_backups/
```

Do not `docker cp` through `/tmp`. The bind mount is the same directory.

<!-- {en:remote[5],database[5],container,backup,droplet} -->
<!-- {nl:extern[5],database[5],container,reservekopie,droplet} -->

### 1.1 Pull the remote database to this PC

`scripts/pull-remote-backup.ps1` is this sequence. Run it from the repo root when you want the whole list done for you. The steps are here so a failed `chown` or a `Permission denied` can be matched to the line that owns the file.

Uid **10001** is the SQL Server process inside `MSSQL2022`. User `agrolav` is the SSH login. A `BACKUP` is a create or an overwrite by uid 10001. An `scp` download is a read by `agrolav`.

`BACKUP` returns operating-system error 5 when `remote_backups` or the existing `agrolav.bak` is owned by `agrolav`: uid 10001 cannot create or replace that file. The script therefore gives the directory and the file to 10001 before the backup. After the backup the owner stays 10001 and the group becomes `agrolav`, mode 640, so `scp` can read the file and the next backup can still overwrite it.

The script asks for the `agrolav` password once (SSH and sudo; paste with Shift+Insert). It retries each ssh/scp step up to five times. The `sa` password is read on the droplet from `/root/sqlserver/.env` or `/opt/agrolav/.env`. It is not typed into the script.

**1. On the droplet, give the folder and the file to SQL.**

```bash
sudo chown 10001:10001 /opt/sql_backups/remote_backups
sudo chmod 775 /opt/sql_backups/remote_backups
```

When `agrolav.bak` is already there:

```bash
sudo chown 10001:10001 /opt/sql_backups/remote_backups/agrolav.bak
sudo chmod 660 /opt/sql_backups/remote_backups/agrolav.bak
```

When it is not there, create an empty file owned by 10001 so the backup overwrites that file instead of creating one as the wrong user:

```bash
sudo install -o 10001 -g 10001 -m 660 /dev/null /opt/sql_backups/remote_backups/agrolav.bak
```

**2. Write the database.** SSMS on the authorized computer, or `sqlcmd` inside `MSSQL2022`. The path is the container path. `INIT` replaces the contents of that file.

```sql
BACKUP DATABASE [agrolav]
TO DISK = N'/var/opt/mssql/backup/remote_backups/agrolav.bak'
WITH
    INIT,
    COMPRESSION,
    CHECKSUM,
    STATS = 10;
```

**3. Let `agrolav` read the file, and drop older dated copies in that folder.**

```bash
sudo chown 10001:agrolav /opt/sql_backups/remote_backups/agrolav.bak
sudo chmod 640 /opt/sql_backups/remote_backups/agrolav.bak
sudo rm -f /opt/sql_backups/remote_backups/agrolav[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_*.bak
sudo ls -lh /opt/sql_backups/remote_backups/agrolav.bak
```

The host path of that file is `/opt/sql_backups/remote_backups/agrolav.bak`.

**4. From Windows, copy it into the dated archive.** The stamp is the file time, with no seconds.

```powershell
scp -P 4523 agrolav@209.38.39.105:/opt/sql_backups/remote_backups/agrolav.bak C:/SQLBackups/remote_backups/agrolavYYYYMMDD_HHMM.bak
```

**5. On the droplet, delete every `.bak`.** The copy on the PC stays. The droplet must not keep the file: a backup holds the Enable Banking keys.

```bash
sudo find /opt/sql_backups/remote_backups -type f \( -name '*.bak' -o -name '*.bak.partial' \) -delete
```

That whole list is:

```powershell
powershell -File scripts/pull-remote-backup.ps1
```

`-CopyOnly` skips steps 1–3, copies the `agrolav.bak` already on the droplet, then runs step 5. That file has to be readable by `agrolav` already (owner 10001, group `agrolav`, mode 640).

<!-- {en:remote[5],backup[5],copy[5],pc[5],bak,scp} -->
<!-- {nl:extern[5],reservekopie[5],kopie[5],pc[5],bak,scp} -->

### 1.2 Copy a local backup onto the droplet

This sends a `.bak` that is already on the PC to `MSSQL2022`, then either replaces `agrolav` or restores a second database beside it. The PC file can be a dated pull under `C:\SQLBackups\remote_backups` or a backup this PC wrote under `C:\SQLBackups\local_backups` (§2.1).

`local_backups` on the droplet is owned by uid 10001 so SQL can create a backup there. `scp` logs in as `agrolav`. The login succeeds and the copy still fails with `Permission denied` in either of these cases:

- the directory is `10001:10001` mode 775, so `agrolav` is “other” and cannot create a file in it
- a file of the same name is already there, owned by 10001 mode 660, so `agrolav` cannot overwrite it

Hand the directory to `agrolav` for the `scp`, then hand the new file and the directory back to 10001 before `RESTORE`. SQL reads that file as uid 10001. A later `BACKUP` into the same folder is also uid 10001, and it returns error 5 while the folder belongs to `agrolav`.

Use one filename in every command below. `agrolav.bak` is that name on the droplet. Substitute your dated PC name in the `scp` source only.

**1. On the droplet, clear the destination and give the folder to `agrolav`.**

```bash
sudo rm -f /opt/sql_backups/local_backups/agrolav.bak
sudo chown agrolav:agrolav /opt/sql_backups/local_backups
```

**2. From Windows, copy the file.**

```powershell
scp -P 4523 C:/SQLBackups/remote_backups/agrolavYYYYMMDD_HHMM.bak agrolav@209.38.39.105:/opt/sql_backups/local_backups/agrolav.bak
```

A backup written on this PC uses the other folder as the source:

```powershell
scp -P 4523 C:/SQLBackups/local_backups/agrolav.bak agrolav@209.38.39.105:/opt/sql_backups/local_backups/agrolav.bak
```

**3. On the droplet, give the file and the folder back to SQL.**

```bash
sudo chown 10001:10001 /opt/sql_backups/local_backups/agrolav.bak
sudo chown 10001:10001 /opt/sql_backups/local_backups
sudo chmod 775 /opt/sql_backups/local_backups
sudo ls -lh /opt/sql_backups/local_backups/agrolav.bak
```

SQL Server sees `/var/opt/mssql/backup/local_backups/agrolav.bak`. That is the bind mount. The data files live under `/var/opt/mssql/data`. A restore path that puts `/opt/sql_backups` under `/var/opt/mssql/data` is not this file (operating-system error 2).

**4. Read the logical names.** SSMS on the authorized computer. The `LogicalName` column is what `MOVE` uses. For a backup of this database those names are `agrolav` and `agrolav_log`.

```sql
RESTORE FILELISTONLY
FROM DISK = N'/var/opt/mssql/backup/local_backups/agrolav.bak';
```

Keep the `.bak` until the restore in 1.2a or 1.2b has finished. The delete is the last command of that restore. The PC file stays.

#### 1.2a Overwrite `agrolav`

This replaces the live database. Every current row in `agrolav` is the backup’s row afterwards.

`MOVE` sends the files to the paths already used by the live database. If `FILELISTONLY` printed other logical names, use those names here.

```sql
USE master;

ALTER DATABASE [agrolav]
SET SINGLE_USER
WITH ROLLBACK IMMEDIATE;

RESTORE DATABASE [agrolav]
FROM DISK = N'/var/opt/mssql/backup/local_backups/agrolav.bak'
WITH
    MOVE N'agrolav'     TO N'/var/opt/mssql/data/agrolav.mdf',
    MOVE N'agrolav_log' TO N'/var/opt/mssql/data/agrolav_log.ldf',
    REPLACE,
    RECOVERY;

ALTER DATABASE [agrolav]
SET MULTI_USER;
```

The hub does not auto-create tables. After the restore:

```sql
USE agrolav;
SELECT name FROM sys.tables
WHERE name IN (
  'account','egress_ip','bank','bank_modality','category_term',
  'category_total','center','consent_pending','country','dim_category',
  'enable_connection','enable_redirect','person','table_header_term',
  'type_abbreviation','transaction_nederland','transaction_uk',
  'uploaded_files','visitor_ip'
)
ORDER BY name;
```

Run the idempotent scripts so local and remote stay identical:

- `hub/sql/visitor_ip.sql`
- `hub/sql/egress_ip.sql`

Insert the production router WAN addresses into `dbo.egress_ip` before country/center logins can succeed (an empty `egress_ip` admits nobody). See [Logins](#logins).

Delete the droplet copy after this restore has finished:

```bash
sudo rm -f /opt/sql_backups/local_backups/agrolav.bak
```

#### 1.2b A second database beside `agrolav`

This leaves `agrolav` as it is and restores the file as `agrolav_copy`, so a query can name both databases. Pick another name when `agrolav_copy` already exists. `MOVE` writes `agrolav_copy.mdf` and `agrolav_copy_log.ldf`. The live data files stay the live database.

```sql
RESTORE DATABASE [agrolav_copy]
FROM DISK = N'/var/opt/mssql/backup/local_backups/agrolav.bak'
WITH
    MOVE N'agrolav'     TO N'/var/opt/mssql/data/agrolav_copy.mdf',
    MOVE N'agrolav_log' TO N'/var/opt/mssql/data/agrolav_copy_log.ldf',
    RECOVERY;
```

Comparisons and copies use three-part names:

```sql
SELECT * FROM agrolav.dbo.journal;
SELECT * FROM agrolav_copy.dbo.journal;
```

Delete the droplet copy after this restore has finished. The PC file stays.

```bash
sudo rm -f /opt/sql_backups/local_backups/agrolav.bak
```

When the side database is no longer needed:

```sql
ALTER DATABASE [agrolav_copy] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
DROP DATABASE [agrolav_copy];
```

---

<!-- {en:sql[5],restoring[5],local[5],backup[5],restore,bak} -->
<!-- {nl:sql[5],terugzetten[5],lokaal[5],reservekopie[5],herstel,bak} -->

## 2. The local database

Container `agrolav-sql` (`docker-compose.sqlserver.yml`). Host mount
`C:\SQLBackups` → `/var/opt/mssql/backup`.

```text
C:\SQLBackups\local_backups\    =  /var/opt/mssql/backup/local_backups/
C:\SQLBackups\remote_backups\   =  /var/opt/mssql/backup/remote_backups/
```

<!-- {en:local[5],database[5],docker,container} -->
<!-- {nl:lokaal[5],database[5],docker,container} -->

### 2.1 SQL to write the database to disk

SSMS at `127.0.0.1,1433` (`sa`):

```sql
BACKUP DATABASE [agrolav]
TO DISK = N'/var/opt/mssql/backup/local_backups/agrolav.bak'
WITH
    INIT,
    COMPRESSION,
    CHECKSUM,
    STATS = 10;
```

Host file: `C:\SQLBackups\local_backups\agrolav.bak`. §1.2 can copy that file
to `/opt/sql_backups/local_backups/`.

<!-- {en:sql[5],write[5],database[5],disk[5],backup,bak} -->
<!-- {nl:sql[5],schrijven[5],database[5],schijf[5],reservekopie,bak} -->

### 2.2 scp from the remote system to the local disk

That copy is §1.1. `scripts/pull-remote-backup.ps1` writes the file, copies it to `C:\SQLBackups\remote_backups\agrolavYYYYMMDD_HHMM.bak`, and deletes it on the droplet.

<!-- {en:scp[5],remote[5],local[5],disk[5],copy,bak} -->
<!-- {nl:scp[5],extern[5],lokaal[5],schijf[5],kopie,bak} -->

### 2.3 SQL for restoring a local backup

On this PC, “local backup” in the restore sense is the file now sitting under
`C:\SQLBackups` — either the remote copy you just pulled (`remote_backups`)
or a previous write of this machine (`local_backups`). SSMS at
`127.0.0.1,1433` must use the **container** path.

Restore the pulled remote database:

```sql
USE master;
RESTORE FILELISTONLY
FROM DISK = N'/var/opt/mssql/backup/remote_backups/agrolav.bak';
```

```sql
USE master;

ALTER DATABASE [agrolav]
SET SINGLE_USER
WITH ROLLBACK IMMEDIATE;

RESTORE DATABASE [agrolav]
FROM DISK = N'/var/opt/mssql/backup/remote_backups/agrolav.bak'
WITH
    REPLACE,
    RECOVERY;

ALTER DATABASE [agrolav]
SET MULTI_USER;
```

To roll this PC back to its own last write, use
`N'/var/opt/mssql/backup/local_backups/agrolav.bak'` instead.

`scripts/upload-most-recent-remote-download-to-local.ps1` does the same
restore from the command line: it picks the newest `agrolav*.bak` in
`C:\SQLBackups\remote_backups`, reads `MSSQL_SA_PASSWORD` from the root `.env`,
and restores it over `agrolav` in the local `agrolav-sql` container (logical
file names from `FILELISTONLY`, `MOVE`d into `/var/opt/mssql/data`). It asks
for a typed `YES` first; `-Yes` skips that. Stop the hub, BFF and balance apps
before running it.

Then the same table check and `visitor_ip.sql` / `egress_ip.sql` as
§1.2a. A local restore does not need production WAN rows in
`dbo.egress_ip` if you sign in with `HUB_DEV_LOGIN=1` on loopback.

---

<!-- {en:sql[5],restoring[5],local[5],backup[5],restore,bak} -->
<!-- {nl:sql[5],terugzetten[5],lokaal[5],reservekopie[5],herstel,bak} -->

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

<!-- {en:category[5],ids[5],surrogate,dim_category,stable} -->
<!-- {nl:categorie[5],nummers[5],surrogaat,dim_category,stabiel} -->

## Tables

<!-- {en:tables[5],schema,columns} -->
<!-- {nl:tabellen[5],schema,kolommen} -->

### `country`

| column | type | notes |
|:-------|:-----|:------|
| `country_id` | `INT` PK | 1 = nederland, 2 = uk, … |
| `username` | `NVARCHAR(32)` unique | the country login |
| `title` | `NVARCHAR(256)` | display name |
| `currency_default` | `CHAR(3)` | `EUR` / `GBP` (accounts may still differ) |
| `egress_ip` | `VARCHAR(256)` NULL | comma-separated allowlist; empty or NULL admits nobody |
| `language_id` | `INT` NOT NULL | `1` = `dbo.language.term_lang1` (English); `2` = `term_lang2` (Dutch); unknown id → English |

<!-- {en:country[5],table,login,column} -->
<!-- {nl:land[5],tabel,inloggen,kolom} -->

### `dim_category`

Country-specific catalog. One row per (country, local code).

| column | type | notes |
|:-------|:-----|:------|
| `category_id` | `INT` PK | 100, 101, … (see above) |
| `country_id` | `INT` FK | |
| `local_code` | `INT` NOT NULL | UI code (8, 9, 12, 18, …) |
| `label` | `NVARCHAR(128)` NOT NULL | `"12 Vervoer"`; footers `"saldo"` / `"datum"` |
| `category_role` | `NVARCHAR(32)` NULL | `NULL` ordinary booking; `remainder` unclassified; `balance` / `last_booked` footers; `equity` Eigen vermogen (no HIT no journal); `profit` Verlies (no HIT no journal); `bank` / `source` / `mirror` (no HIT, journals allowed). `source` and `mirror` identify the spaar pair. |
| `parent` | `NVARCHAR` NULL | Slash-separated place of the post in the exported balance sheet, e.g. `Activa/Vlottende activa/Bank SIa`, `Passiva/Schulden`, `Passiva`. See below. |
| `visibility` | `INT` NOT NULL | Who may see the category. `1` country, `2` country and center, `3` those plus person, `4` those plus work-unit, `5` all of those plus HD. Default `5`. |

Unique: `(country_id, local_code)` (`UQ_category_country_code`). Label is not unique.
Footer rows have empty `category_term` lists and must not be assigned to
transactions.

<!-- {en:dim_category[5],table,category,column} -->
<!-- {nl:dim_category[5],tabel,categorie,kolom} -->

#### `parent` — structure of the "Export balans" workbook

The Balans sheet of "Export balans" lists the A/P posts that have a `parent`,
nested under the groups named by that path; posts with NULL `parent` are not
on the sheet. The Resultaat sheet does the same for 3000–4999 posts as soon
as any of them carries a `parent` (otherwise it stays the flat list of every
P&L category). Rules, implemented in `shared.balance_values.build_parent_tree`:

- The first segment is the side (`Activa` / `Passiva`); every further segment
  is a nested group.
- Group names match case-insensitively; the first spelling seen is printed
  (`Passiva/Schulden` and `Passiva/schulden` are one group).
- Within a group, posts and sub-groups are ordered by their lowest
  `local_code`. Each group prints a `Totaal <group>` line when it has more
  than one child; each side always prints its total.
- Posts print as `<local_code> <label>` (`1000 Kas Huis`); `category_id` is
  never shown.

`dbo.condensed_balance` (post lists with `sum_local_code`, page colours,
fonts) is discontinued and no longer read; drop it when convenient:

```sql
DROP TABLE dbo.condensed_balance;
```

<!-- {en:parent[5],structure[5],export[5],balance[5],workbook[5]} -->
<!-- {nl:ouder[5],structuur[5],exporteren[5],balans[5],werkmap[5]} -->

### `category_term`

Keyword lists that assign bookings to categories.

| column | type | notes |
|:-------|:-----|:------|
| `category_id` | `INT` FK | |
| `person_id` | `INT` FK NULL | NULL = country catalog; set = personal overlay |
| `term` | `NVARCHAR(256)` | as stored, including `#` and `&&` |
| `sort_order` | `INT` | file order |

<!-- {en:category_term[5],table,term,column} -->
<!-- {nl:category_term[5],tabel,term,kolom} -->

### `type_abbreviation`

Bank-type abbreviations (Betaalautomaat → BA). Per country.

<!-- {en:type_abbreviation[5],table,abbreviation,column} -->
<!-- {nl:type_abbreviation[5],tabel,afkorting,kolom} -->

### `language`

Shared UI terms. One row per English key (`term_lang1`). `term_lang2` is Dutch.
Each of those columns holds at most 64 characters. Further languages are extra
`term_lang{N}` columns, same limit. Country picks a column via
`country.language_id`. A `language_id` with no matching column uses `term_lang1`.

<!-- {en:language[5],table,label,column} -->
<!-- {nl:taal[5],tabel,bijschrift,kolom} -->

### `language_long`

Long UI texts, such as the priority-rules popup. `term_key` is the English
lookup (`NVARCHAR(64)`). `term_lang1` is the English body and `term_lang2` the
Dutch body, both `NVARCHAR(MAX)`. The country `language_id` picks the column
the same way as `dbo.language`. Created by `hub/sql/language_long.sql`.

<!-- {en:language_long[5],table,label,column} -->
<!-- {nl:language_long[5],tabel,bijschrift,kolom} -->

### `center`

| column | type | notes |
|:-------|:-----|:------|
| `center_id` | `INT` PK IDENTITY | |
| `country_id` | `INT` FK | |
| `username` | `NVARCHAR(64)` unique | `dkg`, `gph`, … — the center login |
| `title` | `NVARCHAR(256)` | display name |
| `egress_ip` | `VARCHAR(256)` NULL | comma-separated allowlist; empty or NULL admits nobody |

<!-- {en:center[5],table,login,column} -->
<!-- {nl:centrum[5],tabel,inloggen,kolom} -->

### `person`

| column | type | notes |
|:-------|:-----|:------|
| `id` | `INT` PK IDENTITY | referenced as `person_id` from other tables |
| `username` | `NVARCHAR(128)` unique | the person login |
| `title` | `NVARCHAR(256)` | display name |
| `country_id` | `INT` FK | |
| `center_id` | `INT` FK | |
| `password_hash` | `NVARCHAR(256)` NULL | scrypt; see `double_login.md` |
| `mobile_phone` | `NVARCHAR(32)` NULL | E.164; SMS second step when set |

Country is `person → center → country`. Account count is `COUNT(*) FROM dbo.account WHERE person_id = person.id`.

<!-- {en:person[5],table,login,column} -->
<!-- {nl:persoon[5],tabel,inloggen,kolom} -->

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

<!-- {en:account[5],table,iban,column} -->
<!-- {nl:rekening[5],tabel,iban,kolom} -->

### `bank`

Lookup of bank processors. `bank_id` is assigned from 1 (no `IDENTITY`).

| column | type | notes |
|:-------|:-----|:------|
| `bank_id` | `INT` PK | 1, 2, … |
| `bank_name_official` | `NVARCHAR(64)` NOT NULL | `"Bank of Scotland"` |
| `file_format` | `NVARCHAR(64)` NOT NULL | `"csv"` or `"excel"` |

<!-- {en:bank[5],table,name,column} -->
<!-- {nl:bank[5],tabel,naam,kolom} -->

### `bank_modality`

Maps an upload folder name to a `bank_id`.

<!-- {en:bank_modality[5],table,modality,column} -->
<!-- {nl:bank_modality[5],tabel,modaliteit,kolom} -->

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

<!-- {en:enable_connection[5],table,consent,column} -->
<!-- {nl:enable_connection[5],tabel,toestemming,kolom} -->

### `enable_redirect`

Last Enable Banking redirect payload per person.

<!-- {en:enable_redirect[5],table,redirect,column} -->
<!-- {nl:enable_redirect[5],tabel,omleiding,kolom} -->

### `consent_pending`

Short-lived callback tokens while a bank consent is in flight. Create this
table in SSMS if it is missing; the hub does not create it.

<!-- {en:consent_pending[5],table,consent,column} -->
<!-- {nl:consent_pending[5],tabel,toestemming,kolom} -->

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
| `hit` | `NVARCHAR(64)` NULL | `P:{term}` or `G:{term}`; NULL for the remainder |

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

`hit` is the keyword that won (`P:` personal or `G:` general). The remainder
leaves it NULL.

Unique `(person_id, year, bank_id, source_id)` with a filtered unique for
`bank_id IS NULL`, per table.

`counterparty_iban` is the payee / payer. It is not the person’s own account;
that is `account_id` → `account.iban`.

<!-- {en:transaction[5],bookings,table,country} -->
<!-- {nl:transactie[5],boekingen,tabel,land} -->

### `category_total`

Snapshot of category amounts per person/year (and optional bank).

| column | type |
|:-------|:-----|
| `person_id`, `year`, `bank_id` NULL | same grain as files |
| `category_id` | INT FK (104, not the label) |
| `amount` | `DECIMAL(18,2)` |

<!-- {en:category_total[5],table,total,column} -->
<!-- {nl:category_total[5],tabel,totaal,kolom} -->

### `uploaded_files`

One row per spreadsheet or bank CSV taken in for an account.

| column | type | notes |
|:-------|:-----|:------|
| `uploaded_file_id` | `INT` PK IDENTITY | |
| `account_id` | `INT` FK | → `dbo.account` |
| `file_name` | `NVARCHAR(256)` | as uploaded |
| `format` | `NVARCHAR(64)` NULL | parser that read it |

<!-- {en:uploaded_files[5],table,upload,column} -->
<!-- {nl:uploaded_files[5],tabel,uploaden,kolom} -->

### `egress_ip`

Egress addresses allowed for **every** country and center. Hand-edited in
SSMS; there is no UI for it. See `hub/sql/egress_ip.sql`.

| column | type | notes |
|:-------|:-----|:------|
| `egress_ip` | `VARCHAR(45)` PK | one address per row, IPv4 or IPv6 |

<!-- {en:egress_ip[5],table,ip,column} -->
<!-- {nl:egress_ip[5],tabel,ip,kolom} -->

### `visitor_ip`

Login attempts and other HTTP hits, so you can see who is knocking. See
`hub/sql/visitor_ip.sql`. `login_page = 1` is a login/OTP POST (written
immediately). `login_page = 0` is any other public HTTP hit (at most once
per UTC day).

| column | type | notes |
|:-------|:-----|:------|
| `visitor_id` | `INT` PK IDENTITY | |
| `egress_ip` | `VARCHAR(45)` | 45 fits a compressed IPv6 address (39) |
| `username` | `VARCHAR(64)` NOT NULL, default `''` | `''` when they did not log in |
| `login_page` | `BIT` NOT NULL, default `1` | `1` login POST; `0` other HTTP |
| `number_of_attempts` | `INT` NOT NULL, default `1` | incremented on collapse |
| `first_seen` | `DATETIME2` NOT NULL | UTC |
| `last_seen` | `DATETIME2` NOT NULL | UTC |
| `last_status` | `SMALLINT` NULL | last HTTP status |
| `last_path` | `VARCHAR(256)` NOT NULL, default `''` | URI without query string |
| Unique `(egress_ip, username, login_page)` | | repeats collapse |

Not recorded: loopback and LAN addresses, anything listed in
`dbo.egress_ip`, static `/assets` files, and — on a development hub
(`HUB_DEV_LOGIN`) — nothing at all.

<!-- {en:visitor_ip[5],table,ip,column} -->
<!-- {nl:visitor_ip[5],tabel,ip,kolom} -->

### `maaltijden_users`

Ordered list of meal logins (`/maaltijden`, port 8400). Login **`admin`**
is not a matrix row and occupies no bits in `code`; its only purpose is to
edit `dbo.maaltijden_extra` for the current week. Remaining people occupy
five bits each in `dbo.maaltijden_data.code` in list order after that skip
(first remaining person = bits 0–4). Matrix `N` must be ≤ 12 so `5N` fits
in `BIGINT`. See `maaltijden/sql/maaltijden.sql`.

| column | type | notes |
|:-------|:-----|:------|
| `id` | `INT` PK | convenient as 1, 2, …; gaps allowed |
| `user_login` | `VARCHAR(32)` | login name; **`admin`** is excluded from the matrix. Display title comes from `dbo.person` when it matches |
| `passphrase` | `VARCHAR(64)` NULL | login password, **plain text**. `NULL` = no password required |

<!-- {en:maaltijden_users[5],table,login,column} -->
<!-- {nl:maaltijden_users[5],tabel,inloggen,kolom} -->

### `maaltijden_data`

One row per day of a 365-day year (`id` 1 = 1 januari, 365 = 31 december).
There is no year column: week 12 of any year reads the same row. Leap-year
29 februari shares id 59 with 28 februari.

`code` packs every user’s marks for that day. Per user, five bits
(display order **O M A L P**; bit 4 is meal **L**):

| bit | meaning |
|:----|:--------|
| 0 | meal O: 0 = `x`, 1 = `v` |
| 1 | meal M: 0 = `x`, 1 = `v` (was lunch L) |
| 2 | meal A: 0 = `x`, 1 = `v` |
| 3 | meal P: 0 = `x`, 1 = `v` |
| 4 | meal L: 0 = `x`, 1 = `v` (was the A=`L` flag) |

Default `code` is 0 (every mark `x`).

| column | type | notes |
|:-------|:-----|:------|
| `id` | `INT` PK | day of year, 1–365 |
| `code` | `BIGINT` | `5 × N` bits, `N` = matrix people (not `admin`) |

<!-- {en:maaltijden_data[5],table,mark,column} -->
<!-- {nl:maaltijden_data[5],tabel,markering,kolom} -->

### `maaltijden_extra`

Seven rows, `id` 1 = zondag … 7 = zaterdag. Guest/extra counts for the
**current** week only. Zeroed when a new Sunday week begins
(`dbo.maaltijden_extra_week.week_start`). Only login **`admin`** may
change these numbers; other users see them in the extra row. See
`maaltijden/sql/maaltijden.sql`.

| column | type | notes |
|:-------|:-----|:------|
| `id` | `INT` IDENTITY PK | weekday order |
| `ochtend` | `INT` | extra count for meal O |
| `middag` | `INT` | extra count for meal M |
| `avond` | `INT` | extra count for meal A |
| `laat` | `INT` | extra count for meal L |
| `pakket` | `INT` | extra count for meal P |

<!-- {en:maaltijden_extra[5],table,extra,column} -->
<!-- {nl:maaltijden_extra[5],tabel,extra,kolom} -->

### `maaltijden_extra_week`

One row. `week_start` is the Sunday the extra numbers belong to. When today
is in a later week, extras are reset to 0.

| column | type | notes |
|:-------|:-----|:------|
| `week_start` | `DATE` | Sunday of the extra week |

---

<!-- {en:maaltijden_extra_week[5],table,week,column} -->
<!-- {nl:maaltijden_extra_week[5],tabel,week,kolom} -->

## Unit, Person, center, and country login rows

A login is a row in one of three tables, and which one it is decides the
access level:

| Row in | Access | Password |
|:-------|:-------|:---------|
| `dbo.unit` | that unit only | scrypt hash in `password_hash`, plus an SMS code when `mobile_phone` is set |
| `dbo.person` | that person only | scrypt hash in `password_hash`, plus an SMS code when `mobile_phone` is set |
| `dbo.center` | that center | derived formula (prefix + username) |
| `dbo.country` | every center in that country | derived formula (prefix + username) |

No login spans all countries. Country and center logins are gated by egress
IP; person logins are not. A country or center may sign in only from an
address listed in `dbo.egress_ip` or in its own `egress_ip` column — the
allowed set is the **sum** of the two, and an empty column admits nobody, so a
database with no addresses listed anywhere refuses every country and center
login.

A development hub (`HUB_DEV_LOGIN=1` in `hub/.env`, caller on loopback) skips
the gate and writes no `visitor_ip` rows: there the browser, client and hub
share one machine and no public address exists to list. Never set that flag
on the server.

---

<!-- {en:person[5],center[5],country[5],login[5],rows[5],access} -->
<!-- {nl:persoon[5],centrum[5],land[5],inloggen[5],rijen[5],toegang} -->

## Report labels from dim_category

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

-- header labels from dim_category.category_role (NL saldo/datum; UK later
-- balance/date on the same local_codes 22 and 23). equity / bank / source /
-- mirror stay coded matrix rows, not footers.
SELECT local_code, label, category_role
FROM dbo.dim_category
WHERE country_id = @country_id AND category_role IN ('balance', 'last_booked');
```

---

<!-- {en:report[5],labels[5],dim_category[5],category[5],amount} -->
<!-- {nl:rapport[5],bijschriften[5],dim_category[5],categorie[5],bedrag} -->

## Occasional DDL (run in SSMS; keep local and remote identical)

```sql
ALTER TABLE dbo.transaction_beheer
DROP CONSTRAINT ck_txn_beheer_cat;

ALTER TABLE dbo.transaction_beheer
ADD CONSTRAINT ck_txn_beheer_cat
CHECK ([category_id] >= 1000 AND [category_id] < 10000);

UPDATE dbo.dim_category
SET label = SUBSTRING(label, 4, LEN(label))
WHERE category_role IS NULL
  AND label LIKE '[0-9][0-9][0-9][0-9] %';
```

<!-- {en:ddl[5],ssms[5],local[5],remote[5],identical[5],constraint} -->
<!-- {nl:ddl[5],ssms[5],lokaal[5],extern[5],identiek[5],beperking} -->
