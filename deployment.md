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
| Caddy | systemd (`caddy`) | `80/443` | public site → client BFF; hub web pages → hub (see §14) |

There is **no SQLite fallback** on this branch. If `HUB_DATABASE_URL` is unset the
hub refuses to start:

```
RuntimeError: HUB_DATABASE_URL is not set — SQL Server (agrolav-sql) is required
```

No `.json` files are written anywhere; the database is authoritative.

---

## A. Local dev vs APSURT production — at a glance

The same codebase drives both, but the environment-specific knobs are set in
two different places and **must stay consistent per environment**. The single
most important rule: **everything in `dbo.app_config` is resolved at runtime by
the hub based on the `RUN_ON_SERVER` row**, so a value that is correct for one
environment must not leak into the other.

### A1. The two config layers

| knob | local dev | APSURT production |
|---|---|---|
| repo branch | `sqlserver` (local working tree) | same branch, pulled on server |
| `RUN_ON_SERVER` (`dbo.app_config`) | `False` / absent | `True` |
| `dbo.app_config` rows (`PUBLIC_HUB_URL`, `PUBLIC_CLIENT_URL`, `*_ENABLEBANKING_REDIRECT_URL`, `CENTRALE_API_KEY`, …) | honoured only when they make sense for dev; local defaults otherwise | driven by the production rows |
| `hub.env` / `client.env` (systemd `EnvironmentFile`) | not used | on `/opt/agrolav` server only |
| reverse proxy | none (direct `127.0.0.1:8200/8300`) | Caddy on `80/443` → `8300` (client) + selected hub paths (see §14) |
| SQL Server | optional / local copy | Docker `SQLServer2022`, the single source of truth |
| Enable Banking callback | `https://deoudegracht.nl/banking-callback.html` relay (or your own test app) | must return to a **public** URL such as `https://expenses.apsurt.nl/api/consent/callback` |

### A2. How the hub decides (the `RUN_ON_SERVER` gate)

- `RUN_ON_SERVER` truthy → the hub reads the production rows and **public**
  URLs; e.g. `public_hub_url()`/`public_client_url()` return non-empty and
  `enablebanking_redirect_url()` returns `PRODUCTION_ENABLEBANKING_REDIRECT_URL`.
- `RUN_ON_SERVER` falsy / absent → the same rows are **ignored for public URLs**
  (they return `""`), and `enablebanking_redirect_url()` returns
  `LOCAL_ENABLEBANKING_REDIRECT_URL`. Local dev therefore never points browsers
  at production hostnames.

See `hub/app/app_config.py` (`running_on_server`, `public_hub_url`,
`public_client_url`, `enablebanking_redirect_url`, `centrale_api_key`).

### A3. Redirect / API-key handling differs

| concern | local dev | APSURT production |
|---|---|---|
| hub API key (`CENTRALE_API_KEY`) | often empty (key gate off) or a dev-only value | set identically in `hub.env` + `client.env` and, if the DB row is non-empty, overrides; Caddy injects it for the hub paths that browsers call (§14a) |
| consent callback destination | the deoudegracht relay (or local test app) — browser must reach the hub at `:8200` | the **public** `https://expenses.apsurt.nl/api/consent/callback` (Caddy-proxied); loopback callbacks break prod |
| `docker` pull / frontend build | `npm ci && npm run build` locally | same on server, then `systemctl restart agrolav-client` (§16) |

**Practical check when something works in dev but not in prod:** confirm
`RUN_ON_SERVER`, the `dbo.app_config` rows, and `hub.env`/`client.env` all point
at the same target. A mismatch is the #1 cause of "works locally, 404/401 on the
server".

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
# Comments must be on their own line. systemd EnvironmentFile does NOT
# strip inline "# comment" text after a value — it becomes part of the value.
HOST=127.0.0.1
PORT=8200
AGROLAV_SQL_DISK=/opt/agrolav/workspaces
HUB_DATABASE_URL=DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=YOUR_ACTUAL_PASSWORD;Encrypt=yes;TrustServerCertificate=yes
CENTRALE_API_KEY=SOME_LONG_RANDOM_SECRET
# HUB_CLIENT_URL=https://expenses.apsurt.nl
# ENABLEBANKING_REDIRECT_URL=...
```

Notes:

- `AGROLAV_SQL_DISK` replaces the legacy `BOEKHOUDING_DATA_ROOT`; used only for
  a few read-only paths now.
- `HUB_CLIENT_URL` is overridden by the `PUBLIC_CLIENT_URL` dbo.app_config row
  when `RUN_ON_SERVER` is set.
- `CENTRALE_API_KEY` must match `client.env` **byte for byte** (no quotes, no
  trailing spaces). It can instead be managed in the database (see below) — then
  `hub.env`/`client.env` can leave it out entirely.
- Do not commit this file to Git.

> **`CENTRALE_API_KEY` from the database (optional, single source of truth).**
> The hub reads a non-empty `dbo.app_config` row named exactly `CENTRALE_API_KEY`
> in preference to the environment variable; an empty row is ignored (env wins).
> When the row is empty — as on a fresh deploy — the hub requires no key at all:
>
> ```sql
> INSERT INTO dbo.app_config (fieldName, value) VALUES (N'CENTRALE_API_KEY', N'');
> ```
>
> Whenever the row gate for the API is set later, `client.env` (and Caddy §14a)
> must carry the same value; restart the hub to refresh the in-process cache.

Edit the client BFF:

```bash
sudo nano /etc/agrolav/client.env
```

Recommended contents:

```text
# systemd EnvironmentFile keeps inline "# ..." text as part of the value.
HOST=127.0.0.1
PORT=8300
SERVER_URL=http://127.0.0.1:8200
CENTRALE_API_KEY=SOME_LONG_RANDOM_SECRET
CLIENT_AUTH=1
CLIENT_SESSION_SECRET=SOME_OTHER_LONG_RANDOM_SECRET
CLIENT_COUNTRY=nederland
# PUBLIC_HUB_URL=https://...
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

The deployed host runs **Caddy** (listening on 80/443, own TLS); nginx is an
equivalent alternative where noted. Option B (Caddy) is the deployed setup;
Option A (nginx, own subdomain) is kept as an alternative that requires an
extra DNS record + certificate.

## 13. Option A — own public host for the hub (nginx; alternative, not deployed)

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

## 14. Option B — same domain, path routing (Caddy; deployed on this host)

Requires no extra DNS or certificate; Caddy (this host) terminates TLS itself.
The client BFF has **no** `/add-person`, `/upload`, `/api/status`,
`/api/consent/callback`, or `/api/local/` routes, so these are safe to forward
to the hub. Inside the existing `expenses.apsurt.nl` site block add, **u.v.m.
before** the catch-all `reverse_proxy 127.0.0.1:8300`:

```caddy
handle /add-person*     { reverse_proxy 127.0.0.1:8200 }
handle /upload*         { reverse_proxy 127.0.0.1:8200 }
handle /api/status      { reverse_proxy 127.0.0.1:8200 }
handle /api/consent/callback* { reverse_proxy 127.0.0.1:8200 }
handle /api/local/*     { reverse_proxy 127.0.0.1:8200 }
```

`handle` forwards the original path (no prefix stripping), which the hub's pages
need. Validate and reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

`PUBLIC_HUB_URL` stays `https://expenses.apsurt.nl`. Verify:

```bash
curl -I https://expenses.apsurt.nl/add-person?center=nl_dkg
```

→ expect `HTTP/1.1 200`.

nginx equivalent (only if the host used nginx instead of Caddy):

```nginx
location = /add-person              { proxy_pass http://127.0.0.1:8200; }
location /upload                    { proxy_pass http://127.0.0.1:8200; }   # page + /upload/api/*
location = /api/status              { proxy_pass http://127.0.0.1:8200; }
location = /api/consent/callback    { proxy_pass http://127.0.0.1:8200; }
location /api/local/                { proxy_pass http://127.0.0.1:8200; }   # hub-only namespace
```

### 14a. API key and the proxied hub paths

When `CENTRALE_API_KEY` is **empty** (as on a fresh server deploy), the hub's
`require_api_key` is a no-op and the plain block above works: the wizard pages
call `/api/status` and `/api/local/*` from the browser without credentials, and
the hub accepts them.

If `CENTRALE_API_KEY` is set — in `hub.env` or as a non-empty `CENTRALE_API_KEY`
`dbo.app_config` row (see §9 notes) — those browser calls would get 401. Caddy must
then inject the key for the five hub paths (added server-side; the browser never
sees it). The client BFF sends the key itself, and `/api/consent/callback`
is unkeyed (the bank's browser hits it), so both are unaffected:

```caddy
# only when CENTRALE_API_KEY is non-empty
# The { header_up ... } block MUST be on its own lines — Caddy's Caddyfile
# adapter rejects an inline "{ ... }" on the same line as reverse_proxy.
@hub_paths {
    path /add-person*
    path /upload*
    path /api/status
    path /api/consent/callback*
    path /api/local/*
}
reverse_proxy @hub_paths 127.0.0.1:8200 {
    header_up Authorization "Bearer <KEY>"
}
```

If you later set the key, restart the hub **and** re-add the injection, or the
wizard/upload pages break with 401.

### 14b. Hub IP allowlist gotcha (404 instead of 403/200)

The hub's `_HubIpAllowlistMiddleware` returns `Not Found` (404) — **not** 403 —
when a request's client IP isn't on the `dbo.hub_ip` allowlist (`target = 'B'`).
When the list is empty the gate is off and everything passes; when it is
non-empty only listed IPs (plus `127.0.0.1`) get through.

Behind Caddy/nginx the hub can see the **public** client IP rather than
`127.0.0.1` (observed on this host as `209.38.39.105:0`), so a proxied request
fails with a confusing `404 Not Found` even though the direct loopback request
succeeds. If the hub gate is enabled and you see 404 on public hub paths, add the
public IP to the allowlist:

```sql
INSERT INTO dbo.hub_ip (ip, target) VALUES (N'209.38.39.105', N'B');
```

(Better long-term: make the hub trust `X-Forwarded-For` from the local proxy and
route by real remote IP — not yet implemented.)

### 14c. Consent won't start — `REDIRECT_URI_NOT_ALLOWED`

When a person's bank consent refresh fails, the hub returns
`AUTH_URL: None` + a warning like:

```
juleon: consent renewal required — could not get authorization URL
(POST /auth failed: 400 ... "REDIRECT_URI_NOT_ALLOWED" ... redirect_url
 'https://.../api/consent/callback' must exactly match a URL registered for this
 app in the Enable Banking Control Panel ...)
```

The hub sends the Enable Banking `redirect_url` from `enablebanking_redirect_url()`
(`dbo.app_config`):
- **`PRODUCTION_ENABLEBANKING_REDIRECT_URL`** — used when `RUN_ON_SERVER` is truthy
- **`LOCAL_ENABLEBANKING_REDIRECT_URL`** — used locally (and fallback the other way)

The redirect the hub *sends* must match what the person's Enable Banking app
(`dbo.enable_connection.app_id`) is *registered* with. When they differ, the bank
returns `REDIRECT_URI_NOT_ALLOWED`. The env split keeps **local dev** and
**production** each using their own registered callback.

**Production must use the public Caddy callback.** The `deoudegracht.nl/banking-callback.html`
relay page forwards the browser to the hub at `127.0.0.1:8200` — that only works
when a hub runs locally on the browser's own machine, so it is **not** suitable for
production. On production the callback must land on the public domain:

```sql
UPDATE dbo.app_config SET value = N'https://expenses.apsurt.nl/api/consent/callback'
WHERE fieldName = N'PRODUCTION_ENABLEBANKING_REDIRECT_URL';
-- local dev keeps the relay callback
UPDATE dbo.app_config SET value = N'https://deoudegracht.nl/banking-callback.html'
WHERE fieldName = N'LOCAL_ENABLEBANKING_REDIRECT_URL';
```

After changing a row, restart the hub to clear the cached `dbo.app_config`. The
public URL must also be registered (exact, no trailing slash) in the Enable
Banking Control Panel for the app:

```
https://expenses.apsurt.nl/api/consent/callback
```

Caddy already routes `/api/consent/callback*` → the hub, so the bank's browser
hits the hub (the injected API key there is harmless — the callback is unkeyed).

To verify the auth URL now comes back, run a refresh and inspect
`results[0].authorization_url`, then confirm the browser is redirected to the
**public** domain after consent (not `127.0.0.1`):

```bash
curl -s -X POST -H "Authorization: Bearer $(sudo grep -oP '^CENTRALE_API_KEY=\K.*' /etc/agrolav/hub.env)" \
  'http://127.0.0.1:8200/api/local/nl_dkg/refresh/juleon?country=nederland' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); r=(d.get('results') or [{}])[0]; print('AUTH_URL:', repr(r.get('authorization_url'))); print('WARNINGS:', d.get('warnings'))"
```

A successful start returns a real `https://...enablebanking.com/ais/start?...` URL
and the bank redirect returns to `https://expenses.apsurt.nl/api/consent/callback`.

## 15. Hub IP allowlist

The hub has an optional IP gate (`dbo.hub_ip`, `target = 'B'` for the hub-wide
allowlist). Empty → no gate; browsers can reach the hub pages freely.

`127.0.0.1` is always included when a non-empty list exists (so the local client
BFF keeps working). If rows are added, include the public IPs that must reach the
wizard and the callback, e.g.:

```sql
INSERT INTO dbo.hub_ip (ip, target) VALUES (N'1.2.3.4', N'B');
```

**Note when behind Caddy/nginx:** the hub reads the peer IP from the TCP
connection (`scope["client"][0]`), which is always `127.0.0.1` for a same-host
proxy — the B allowlist is therefore **effectively bypassed** for real browser
requests. If real-IP gating is needed, forward `X-Forwarded-For`
(Caddy: `header_up X-Forwarded-For {remote_host}`; nginx:
`proxy_set_header X-Forwarded-For $remote_addr`) and process it in the
middleware (Starlette's `ProxyHeadersMiddleware` or a custom reader).

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

That JSON answer is the **client BFF** (port 8300): the reverse proxy (nginx or
Caddy) sent `/add-person` to the client, which has no such route. Route the hub's
pages to `127.0.0.1:8200` (option A §13 or option B §14) and confirm the
`PUBLIC_HUB_URL` row matches the URL the menu generates.

## 21. "edit categories" does not appear

The frontend build is stale — redo §16.

## 22. Missing table at runtime (e.g. `app_config`)

Confirm with §8a, then create the table (see the `app_config` DDL in §8a) and
seed the rows from §9a. Restart the hub afterwards (rows are cached).

## 23. Login always says "invalid username or password", but the hub itself works

Test the hub directly with the client's key first:

```bash
PID=$(sudo systemctl show agrolav-client -p MainPID --value)
curl -s -X POST http://127.0.0.1:8200/api/auth/login \
  -H "Authorization: Bearer $(sudo tr '\0' '\n' < /proc/$PID/environ | sed -n 's/^CENTRALE_API_KEY=//p')" \
  -H 'Content-Type: application/json' \
  -d '{"username":"beheer","password":"<pw>","client_ip":"127.0.0.1"}' | head -c 300
```

If that returns the user, check the env the client actually runs with:

```bash
PID=$(sudo systemctl show agrolav-client -p MainPID --value)
sudo tr '\0' '\n' < /proc/$PID/environ | sed -n 's/^SERVER_URL=//p; s/^CENTRALE_API_KEY=//p'
```

Common causes, in order:

- **Inline comment in an env value.** systemd `EnvironmentFile` does not strip
  `# ...` after a value, so `SERVER_URL=http://127.0.0.1:8200   # BFF` becomes
  literally `http://127.0.0.1:8200   # BFF`. The client then queries a broken
  URL, the hub answers 4xx, and the client reports "invalid username or password".
  Fix: comments only on their own lines, `sudo systemctl restart agrolav-client`.
- **`CENTRALE_API_KEY` differs** between `hub.env` and `client.env` → hub returns
  401 to the client. Make them identical and restart the client.
- **`CENTRALE_SYNC=0|false|off|no`** in `client.env` → the client refuses logins
  entirely (`authenticate` returns `None`).




  ============================


  Fix properly from the process (which is authoritative), normalizing both files to the hub's actual 65-char key:
  
```HKEY=$(sudo tr '\0' '\n' < /proc/$(sudo systemctl show agrolav-hub -p MainPID --value)/environ | sed -n 's/^CENTRALE_API_KEY=//p')
export HKEY
sudo -E python3 - <<'EOF'
import os
k = os.environ["HKEY"] + "\n"
for p in ("/etc/agrolav/hub.env", "/etc/agrolav/client.env"):
    keep = [l for l in open(p) if not l.startswith("CENTRALE_API_KEY=")]
    keep.append("CENTRALE_API_KEY=" + k)
    open(p, "w").writelines(keep)
EOF
sudo systemctl restart agrolav-hub agrolav-client
HKEY=$(sudo tr '\0' '\n' < /proc/$(sudo systemctl show agrolav-hub -p MainPID --value)/environ | sed -n 's/^CENTRALE_API_KEY=//p')
CKEY=$(sudo tr '\0' '\n' < /proc/$(sudo systemctl show agrolav-client -p MainPID --value)/environ | sed -n 's/^CENTRALE_API_KEY=//p')
echo "hub len=${#HKEY} sha=$(printf %s "$HKEY" | sha256sum | cut -c1-16)"
echo "cli len=${#CKEY} sha=$(printf %s "$CKEY" | sha256sum | cut -c1-16)"
[ "$HKEY" = "$CKEY" ] && echo MATCH || echo MISMATCH
curl -s -X POST http://127.0.0.1:8300/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"beheer","password":"!@#$%^&*()_beheer"}' | head -c 200```

This removes every old CENTRALE_API_KEY= line from both files, writes the one true key, and restarts both — expect MATCH and a login JSON.

