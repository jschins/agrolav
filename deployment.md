# Deployment Guide — Agrolav Production

This document describes how to deploy the Agrolav application to the production
server at `expenses.apsurt.nl`, including Git updates, Python/Node dependencies,
frontend builds, SQL Server configuration, database restoration, systemd services,
and the public reverse-proxy setup that exposes the hub's web pages.

It merges the older `Deployment Guide SQLserver.md` with the current
SQL-only, JSON-write-free architecture (branch `sqlserver`).

---

## Architecture overview

| piece | runs as | listens on | what it does |
|---|---|---|---|
| hub | systemd `agrolav-hub` | `127.0.0.1:8200` | FastAPI: sync/merge/calculation, SQL Server (agrolav-sql) only |
| client BFF | systemd `agrolav-client` | `127.0.0.1:8300` | Thin BFF: serves the frontend, proxies hub domain APIs, browser login |
| SQL Server | Docker `SQLServer2022` | `0.0.0.0:1433` | the only data store (`dbo.country/center/person/...`, `dbo.app_config`) |
| nginx | systemd | `80/443` | public site → client BFF; hub web pages → hub (see below) |

There is **no SQLite fallback** on this branch. If `HUB_DATABASE_URL` is unset the
hub refuses to start:

```
RuntimeError: HUB_DATABASE_URL is not set — SQL Server (agrolav-sql) is required
```

No `.json` files are written anywhere; the database is authoritative.

---

## 1. Log in to the production server

```bash
ssh agrolav@209.38.39.105 -p 4523
```

Application directory:

```bash
cd /opt/agrolav
```

---

## 2. Update the application from Git

The server tracks the `sqlserver` branch. Check the current state:

```bash
git status
git branch -vv
```

If the server should exactly match remote `origin/sqlserver` and there are no
server-side changes to preserve:

```bash
git fetch origin
git reset --hard origin/sqlserver
git clean -fd
```

**Warning:** `git clean -fd` deletes untracked files and directories **not** in
`.gitignore`. On this repo the following are gitignored and survive `clean -fd`:

`.venv/`, `node_modules/`, `client/frontend/dist/`, `workspaces/`,
`legacy/**/*`, `*.env`, `data/`, `secret/`, `*.pem`, `users.db`.

Verify:

```bash
git status
```

Expected:

```text
On branch sqlserver
Your branch is up to date with 'origin/sqlserver'.

nothing to commit, working tree clean
```

---

## 3. Install/update Python dependencies

The project uses `uv`. Each application depends on `banking-app-shared` (path
editable), so sync them in order:

```bash
cd /opt/agrolav

cd shared
uv sync

cd ../hub
uv sync

cd ../client
uv sync
```

The console scripts are installed by this step:

- `hub` → `app.main:run` (uvicorn, default `127.0.0.1:8200`)
- `client` → `app.main:run` (uvicorn, default `0.0.0.0:8300`)

---

## 4. Build the frontend

Install the exact dependencies and build:

```bash
cd /opt/agrolav/client/frontend
npm ci
npm run build
```

Verify the build contains recent changes:

```bash
grep -Ril "edit categories" \
  /opt/agrolav/client/frontend \
  --exclude-dir=node_modules
```

Expected:

```text
/opt/agrolav/client/frontend/src/App.tsx
/opt/agrolav/client/frontend/dist/assets/index-....js
```

---

# SQL Server

## 5. Check the SQL Server container

```bash
sudo docker ps
```

Expected container: `SQLServer2022`, with `0.0.0.0:1433->1433/tcp`.

If necessary:

```bash
sudo docker ps -a
```

---

## 6. Copy a `.bak` database backup to the server

From Windows, do **not** use a Windows path on the Linux host.

From Windows:

```powershell
scp -P 4523 C:/SQLBackups/agrolav19.bak agrolav@209.38.39.105:/tmp/
```

On the server:

```bash
ls -lh /tmp/agrolav19.bak
```

---

## 7. Copy the backup into the SQL Server container

```bash
sudo docker exec SQLServer2022 mkdir -p /var/opt/mssql/backup
sudo docker cp \
  /tmp/agrolav19.bak \
  SQLServer2022:/var/opt/mssql/backup/agrolav19.bak
```

Verify:

```bash
sudo docker exec SQLServer2022 \
  ls -lh /var/opt/mssql/backup/agrolav19.bak
```

---

## 8. Restore the SQL Server database

Use SSMS connected to `209.38.39.105,1433` (`sa` login). First determine the
logical file names:

```sql
USE MASTER
RESTORE FILELISTONLY
FROM DISK = '/var/opt/mssql/backup/agrolav19.bak';
```

Then restore (logical names `agrolav` / `agrolav_log`):

```sql
USE master;

ALTER DATABASE [agrolav]
SET SINGLE_USER
WITH ROLLBACK IMMEDIATE;

RESTORE DATABASE [agrolav]
FROM DISK = '/var/opt/mssql/backup/agrolav19.bak'
WITH
    REPLACE,
    RECOVERY;

ALTER DATABASE [agrolav]
SET MULTI_USER;
```

### 8a. Verify the tables the app needs

The hub auto-creates **only** `dbo.consent_pending`. Everything else must exist
already. If a `.bak` predates a table (e.g. `dbo.app_config`, `dbo.hub_ip`,
`dbo.category_term`, `dbo.table_header_term`, `dbo.type_rule`), the hub still
boots (only `dbo.person` is checked at startup) but fails at runtime when the
table is first used. After the restore, check:

```sql
USE agrolav;
SELECT name FROM sys.tables
WHERE name IN ('account','account_balance_file','app_config','bank',
 'bank_modality','category_term','category_total','center','consent_pending',
 'country','dim_category','enable_connection','enable_redirect','hub_ip',
 'person','table_header_term','type_abbreviation','type_rule',
 'transaction_nederland','transaction_uk')
ORDER BY name;
```

Schema sources in the repo:

- `hub/sql/phase_c.sql` — base schema (country/center/person/account/bank/
  dim_category/category_term/type_abbreviation/category_total/transactions).
- `hub/sql/json_independence.sql` — `table_header_term`, `type_rule`,
  `bank_modality`, `hub_ip`, `enable_connection`, `enable_redirect`
  (all with `IF OBJECT_ID() IS NULL` guards).
- `hub/app/user_store.py` — `dbo.consent_pending` (auto-created at startup).
- `dbo.app_config` — **never created by any script**; seed it if missing:

```sql
USE agrolav;
GO
IF OBJECT_ID(N'dbo.app_config', N'U') IS NULL
CREATE TABLE dbo.app_config (
    fieldName NVARCHAR(128) NOT NULL PRIMARY KEY,
    value     NVARCHAR(MAX) NULL
);
GO
```

---

## 9. Configure the SQL Server connection and app config

Edit:

```bash
sudo nano /etc/agrolav/hub.env
```

Recommended contents:

```text
HOST=127.0.0.1
PORT=8200
BOEKHOUDING_DATA_ROOT=/opt/agrolav/workspaces              # legacy, ignored
AGROLAV_SQL_DISK=/opt/agrolav/workspaces                    # flat read paths
HUB_DATABASE_URL=DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=YOUR_ACTUAL_PASSWORD;Encrypt=yes;TrustServerCertificate=yes
CENTRALE_API_KEY=SOME_LONG_RANDOM_SECRET                   # must match client.env
# HUB_CLIENT_URL=https://expenses.apsurt.nl                # optional; DB row wins on the server
# ENABLEBANKING_REDIRECT_URL=...                           # optional; DB rows win on the server
```

Notes:

- `AGROLAV_SQL_DISK` replaces the legacy `BOEKHOUDING_DATA_ROOT`; used only for
  a few read-only paths now.
- `HUB_CLIENT_URL` is overridden by the `PUBLIC_CLIENT_URL` dbo.app_config row
  when `RUN_ON_SERVER` is set.
- Do not commit this file to Git.

Edit the client BFF:

```bash
sudo nano /etc/agrolav/client.env
```

Recommended contents:

```text
HOST=127.0.0.1
PORT=8300
SERVER_URL=http://127.0.0.1:8200                            # BFF → hub (internal!)
CENTRALE_API_KEY=SOME_LONG_RANDOM_SECRET                    # must match hub.env
CLIENT_AUTH=1
CLIENT_SESSION_SECRET=SOME_OTHER_LONG_RANDOM_SECRET        # required for real deploys
CLIENT_COUNTRY=nederland                                    # a dbo.country key
# PUBLIC_HUB_URL=https://...                                # optional override of the DB row
```

Notes:

- `SERVER_URL` is the BFF's **bootstrap** to reach the hub — it cannot come from
  the database and must stay in env.
- `PUBLIC_HUB_URL` in env is only a local-dev override; on the server the
  `PUBLIC_HUB_URL` dbo.app_config row drives the browser links (via the hub's
  `GET /api/public-links`).
- `CLIENT_ACCESS` / `CLIENT_CENTER` / `CLIENT_PERSON` are only used when
  `CLIENT_AUTH` is off; ignore when auth is on.

Verify the connection string without leaking the password:

```bash
sudo grep '^HUB_DATABASE_URL=' /etc/agrolav/hub.env \
  | sed 's/PWD=[^;]*/PWD=***REDACTED***/'
```

### 9a. `dbo.app_config` rows

When `RUN_ON_SERVER` is set, the hub reads these addresses from the database
instead of the environment. Example for the production server:

```sql
USE agrolav;
GO
IF OBJECT_ID(N'dbo.app_config', N'U') IS NOT NULL
UPDATE dbo.app_config
SET value = CASE
  WHEN fieldName = N'LOCAL_ENABLEBANKING_REDIRECT_URL'  THEN N'https://expenses.apsurt.nl/api/consent/callback'
  WHEN fieldName = N'PRODUCTION_ENABLEBANKING_REDIRECT_URL' THEN N'https://expenses.apsurt.nl/api/consent/callback'
  WHEN fieldName = N'PUBLIC_HUB_URL'  THEN N'https://expenses.apsurt.nl'      -- Option B, or https://hub.expenses.apsurt.nl (Option A)
  WHEN fieldName = N'PUBLIC_CLIENT_URL' THEN N'https://expenses.apsurt.nl'
  ELSE value END
WHERE fieldName IN (N'RUN_ON_SERVER', N'LOCAL_ENABLEBANKING_REDIRECT_URL',
                    N'PRODUCTION_ENABLEBANKING_REDIRECT_URL',
                    N'PUBLIC_HUB_URL', N'PUBLIC_CLIENT_URL');
IF NOT EXISTS (SELECT 1 FROM dbo.app_config WHERE fieldName = N'RUN_ON_SERVER')
INSERT INTO dbo.app_config (fieldName, value) VALUES (N'RUN_ON_SERVER', N'True');
GO
```

| fieldName | purpose |
|---|---|
| `RUN_ON_SERVER` | truthy → hub operates in server mode (DB rows win over env) |
| `PRODUCTION_ENABLEBANKING_REDIRECT_URL` | Enable Banking callback on the server |
| `LOCAL_ENABLEBANKING_REDIRECT_URL` | fallback callback |
| `PUBLIC_HUB_URL` | browser-facing hub base → "Add person" / "Upload" links |
| `PUBLIC_CLIENT_URL` | wizard's "return to client" link |

`dbo.app_config` is cached per process — after changing rows, restart the hub
(and the client re-reads `/api/public-links` per request, cache on success).

---

# ODBC

## 10. Install the ODBC runtime + Microsoft driver

The first SQL attempt fails with `ImportError: libodbc.so.2` — install runtime:

```bash
sudo apt update
sudo apt install -y unixodbc
```

The server runs Ubuntu 24.04; install ODBC Driver 18:

```bash
curl -sSL -O \
  https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb
rm packages-microsoft-prod.deb
sudo apt update
sudo ACCEPT_EULA=Y apt install -y msodbcsql18
```

Verify:

```bash
odbcinst -q -d
```

Expected:

```text
[ODBC Driver 18 for SQL Server]
```

---

# Systemd services

## 11. Hub service

```bash
sudo systemctl cat agrolav-hub
```

Key settings:

```ini
[Service]
User=agrolav
WorkingDirectory=/opt/agrolav/hub
EnvironmentFile=/etc/agrolav/hub.env
ExecStart=/home/agrolav/.local/bin/uv run hub
Restart=always
```

Restart and check:

```bash
sudo systemctl restart agrolav-hub
sudo systemctl status agrolav-hub --no-pager
sudo journalctl -u agrolav-hub -n 50 --no-pager
```

Expected:

```text
Application startup complete.
Uvicorn running on http://127.0.0.1:8200
```

The startup line now reads `user store ready: sqlserver:dbo.person` — the old
`user store ready: /opt/agrolav/workspaces/users.db` (SQLite) no longer occurs.

### 11a. Verify the SQL Server environment is actually loaded

```bash
sudo systemctl show agrolav-hub -p MainPID
sudo tr '\0' '\n' < /proc/<MainPID>/environ \
  | grep '^HUB_DATABASE_URL=' \
  | sed 's/PWD=[^;]*/PWD=***REDACTED***/'
```

---

## 12. Client service

```bash
sudo systemctl cat agrolav-client
```

Key settings (mirrors the hub, in `/opt/agrolav/client`, env
`/etc/agrolav/client.env`, exec `uv run client`):

```text
User=agrolav
WorkingDirectory=/opt/agrolav/client
EnvironmentFile=/etc/agrolav/client.env
ExecStart=/home/agrolav/.local/bin/uv run client
Restart=always
```

Restart and check:

```bash
sudo systemctl restart agrolav-client
sudo systemctl status agrolav-client --no-pager
```

---

# Public URLs / reverse proxy

The frontend builds its "Add person" link as
`<PUBLIC_HUB_URL>/add-person?center=<ws>` and its "Upload" link as
`<PUBLIC_HUB_URL>/upload?t=<token>`. `<PUBLIC_HUB_URL>` comes from the
`PUBLIC_HUB_URL` row in `dbo.app_config` (delivered to the client BFF by the
hub's `GET /api/public-links`).

The hub's wizard pages call hub API paths relative to the page origin
(`/api/status`, `/api/local/...`, `/upload/api/...`, `/api/consent/callback`),
so whatever public URL you choose must route those paths to `127.0.0.1:8200`.

Choose one of the two options below.

## 13. Option A — own public host for the hub (recommended)

Give the hub its own nginx server block; every path proxies straight to the hub,
and the wizard just works.

### 13a. DNS

At the `apsurt.nl` registrar / DNS provider add an A record:

```text
host   hub.expenses.apsurt.nl     →    209.38.39.105
```

Verify resolution on the server:

```bash
dig +short hub.expenses.apsurt.nl
```

### 13b. nginx site

```bash
sudo tee /etc/nginx/sites-available/hub.expenses.apsurt.nl > /dev/null <<'EOF'
server {
    listen 80;
    server_name hub.expenses.apsurt.nl;
    location / {
        proxy_pass http://127.0.0.1:8200;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
sudo ln -s /etc/nginx/sites-available/hub.expenses.apsurt.nl /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 13c. TLS certificate (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx   # if not already installed
sudo certbot --nginx -d hub.expenses.apsurt.nl
```

Verify the wizard is reachable:

```bash
curl -I https://hub.expenses.apsurt.nl/add-person
```

→ expect `HTTP/1.1 200` (not a `{"detail":"Not Found"}` JSON).

### 13d. Point the app at the subdomain

```sql
UPDATE dbo.app_config SET value = N'https://hub.expenses.apsurt.nl'
WHERE fieldName = N'PUBLIC_HUB_URL';
```

`PUBLIC_CLIENT_URL` stays `https://expenses.apsurt.nl`. Restart both services so
the cached `dbo.app_config` / public-links refresh.

## 14. Option B — same domain, nginx path routing

Requires no extra DNS/cert. The client BFF has **no** `/add-person`, `/upload`,
`/api/status`, `/api/consent/callback`, or `/api/local/` routes, so these are
safe to forward to the hub:

```nginx
location = /add-person              { proxy_pass http://127.0.0.1:8200; }
location /upload                    { proxy_pass http://127.0.0.1:8200; }   # page + /upload/api/*
location = /api/status              { proxy_pass http://127.0.0.1:8200; }
location = /api/consent/callback    { proxy_pass http://127.0.0.1:8200; }
location /api/local/                { proxy_pass http://127.0.0.1:8200; }   # hub-only namespace
```

Add these to the existing `expenses.apsurt.nl` server block, then:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

`PUBLIC_HUB_URL` stays `https://expenses.apsurt.nl`. Verify:

```bash
curl -I https://expenses.apsurt.nl/add-person?center=nl_dkg
```

→ expect `HTTP/1.1 200`.

## 15. Hub IP allowlist

The hub has an optional IP gate (`dbo.hub_ip`, `target = 'B'` for the hub-wide
allowlist). Empty → no gate; browsers can reach the hub pages freely.

`127.0.0.1` is always included when a non-empty list exists (so the local client
BFF keeps working). If rows are added, include the public IPs that must reach the
wizard and the callback, e.g.:

```sql
INSERT INTO dbo.hub_ip (ip, target) VALUES (N'1.2.3.4', N'B');
```

**Note when behind nginx:** the hub reads the peer IP from the TCP connection
(`scope["client"][0]`), which is always `127.0.0.1` for nginx on the same host
— the B allowlist is therefore **effectively bypassed** for real browser requests.
If real-IP gating is needed, add `proxy_set_header X-Forwarded-For $remote_addr`
to the nginx location block and process it in the middleware (Starlette's
`ProxyHeadersMiddleware` or a custom reader).

---

# Frontend deployment

## 16. Rebuild the frontend after frontend changes

```bash
cd /opt/agrolav/client/frontend
npm ci
npm run build
sudo systemctl restart agrolav-client
```

Check what JS the public site serves:

```bash
curl -s https://expenses.apsurt.nl \
  | grep -oE 'src="[^"]+\.js[^"]*"' \
  | head -20
```

Verify a specific build contains a new string:

```bash
curl -s https://expenses.apsurt.nl/assets/index-<hash>.js \
  | grep -oi "edit categories"
```

---

# Troubleshooting

## 17. Git says up to date but the server looks old

```bash
git status
git branch -vv
git log --oneline --decorate -20
git fetch origin
git log --oneline HEAD..origin/sqlserver
```

To match remote exactly (discards local changes and untracked files — see §2):

```bash
git reset --hard origin/sqlserver
git clean -fd
```

## 18. The hub will not start

```bash
sudo journalctl -u agrolav-hub -n 50 --no-pager
```

- `HUB_DATABASE_URL is not set` → HUB_DATABASE_URL missing or not reaching the
  process (check via §11a).
- `dbo.person missing` → restore/migrate a DB that contains the base schema
  (`hub/scripts/migrate_person.py`, or load from scratch with
  `hub/scripts/load_phase_c.py` + `hub/sql/phase_c.sql`).
- `ImportError: libodbc.so.2` → run §10.

## 19. Old user/country data still showing

- SQL Server is now the only store; if the hub runs at all it is on SQL Server.
- Verify in SSMS:

```sql
SELECT * FROM dbo.country;
SELECT * FROM dbo.center;
SELECT * FROM dbo.person;
```

## 20. `add-person` returns `{"detail":"Not Found"}`

That JSON answer is the **client BFF** (port 8300): nginx sent `/add-person` to
the client, which has no such route. Route the hub's pages to `127.0.0.1:8200`
(option A §13 or option B §14) and confirm the `PUBLIC_HUB_URL` row matches the
URL the menu generates.

## 21. "edit categories" does not appear

The frontend build is stale — redo §16.

## 22. Missing table at runtime (e.g. `app_config`)

Confirm with §8a, then create the table (see the `app_config` DDL in §8a) and
seed the rows from §9a. Restart the hub afterwards (rows are cached).