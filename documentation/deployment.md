# Deployment Guide — Agrolav Production

How to deploy Agrolav to `expenses.apsurt.nl`: Git updates, Python/Node
dependencies, frontend builds, SQL Server, database restore, systemd, and
Caddy.

---

## Architecture

| piece | runs as | listens on | what it does |
|---|---|---|---|
| hub | systemd `agrolav-hub` | `127.0.0.1:8200` | FastAPI: login, sync, calculation, SQL Server |
| client BFF | systemd `agrolav-client` | `127.0.0.1:8300` | Serves the frontend, proxies hub APIs, browser login |
| SQL Server | Docker `SQLServer2022` | `0.0.0.0:1433` | the only data store |
| Caddy | systemd `caddy` | `80/443` | public site → client BFF; selected hub paths → hub |

There is no SQLite fallback. If `HUB_DATABASE_URL` is unset the hub refuses
to start. Configuration lives in `/etc/agrolav/hub.env` and
`/etc/agrolav/client.env` (systemd `EnvironmentFile`). Do not put secrets in
git or in markdown.

Locally, the same knobs sit in `hub/.env` and `client/.env`. Set
`HUB_DEV_LOGIN=1` only on a developer’s own machine: then a loopback caller
skips the country/center IP gate and nothing is written to `dbo.visitor_ip`.
Never set that flag on the server.

---

## Local vs production

| knob | local | production (`expenses.apsurt.nl`) |
|---|---|---|
| `HUB_DEV_LOGIN` | `1` | unset |
| reverse proxy | none (or Caddy on loopback) | Caddy `80/443` |
| SQL Server | Docker on this PC | Docker `SQLServer2022` on the droplet |
| Enable Banking callback | `ENABLEBANKING_REDIRECT_URL` in `hub/.env`, often the deoudegracht relay | `https://expenses.apsurt.nl/api/consent/callback` |
| `HUB_CLIENT_URL` | empty → `http://127.0.0.1:8300` | `https://expenses.apsurt.nl` |
| `CENTRALE_API_KEY` | often empty | identical in `hub.env` and `client.env` |

Caddy must forward `X-Forwarded-For` / `X-Real-IP` (see the repo
`client/Caddyfile`). The hub then stores the caller’s **public** egress
address, not `127.0.0.1` from the proxy hop.

---

## 1. Log in to the production server

```bash
ssh agrolav@209.38.39.105 -p 4523
cd /opt/agrolav
```

---

## 2. Update the application from Git

The server tracks the `sqlserver` branch.

```bash
git status
git branch -vv
```

If the server should exactly match `origin/sqlserver` and there are no
server-side changes to preserve:

```bash
git fetch origin
git reset --hard origin/sqlserver
git clean -fd
```

**Warning:** `git clean -fd` deletes untracked files not in `.gitignore`.
Gitignored paths (`.venv/`, `node_modules/`, `client/frontend/dist/`,
`*.env`, `secret/`, `*.pem`) survive.

Expected: `On branch sqlserver` / `nothing to commit, working tree clean`.

---

## 3. Install/update Python dependencies

```bash
cd /opt/agrolav
cd shared && uv sync
cd ../hub && uv sync
cd ../client && uv sync
```

Console scripts: `hub` → uvicorn `:8200`, `client` → uvicorn `:8300`.

---

## 4. Build the frontend

```bash
cd /opt/agrolav/client/frontend
npm ci
npm run build
```

---

# SQL Server

## 5. Check the SQL Server container

```bash
sudo docker ps
```

Expected: `SQLServer2022`, `0.0.0.0:1433->1433/tcp`.

---

## 6. Copy a `.bak` to the server

From Windows:

```powershell
scp -P 4523 C:/SQLBackups/agrolav.bak agrolav@209.38.39.105:/tmp/
```

On the server: `ls -lh /tmp/agrolav.bak`.

---

## 7. Copy the backup into the container

```bash
sudo docker exec SQLServer2022 mkdir -p /var/opt/mssql/backup
sudo docker cp /tmp/agrolav.bak SQLServer2022:/var/opt/mssql/backup/agrolav.bak
sudo docker exec SQLServer2022 ls -lh /var/opt/mssql/backup/agrolav.bak
```

---

## 8. Restore

SSMS at `209.38.39.105,1433` (`sa`). Logical names:

```sql
USE MASTER
RESTORE FILELISTONLY
FROM DISK = '/var/opt/mssql/backup/agrolav.bak';
```

Then:

```sql
USE master;

ALTER DATABASE [agrolav]
SET SINGLE_USER
WITH ROLLBACK IMMEDIATE;

RESTORE DATABASE [agrolav]
FROM DISK = '/var/opt/mssql/backup/agrolav.bak'
WITH
    REPLACE,
    RECOVERY;

ALTER DATABASE [agrolav]
SET MULTI_USER;
```

### 8a. Verify tables the app needs

The hub auto-creates **only** `dbo.consent_pending`. Everything else must
exist already. After restore:

```sql
USE agrolav;
SELECT name FROM sys.tables
WHERE name IN (
  'account','administrator','bank','bank_modality','category_term',
  'category_total','center','consent_pending','country','dim_category',
  'enable_connection','enable_redirect','person','table_header_term',
  'type_abbreviation','type_rule','transaction_nederland','transaction_uk',
  'uploaded_files','visitor_ip'
)
ORDER BY name;
```

Then run the idempotent scripts so local and remote stay identical:

- `hub/sql/visitor_ip.sql`
- `hub/sql/administrator.sql`

and insert the production router WAN addresses into `dbo.administrator`
**before** country/center logins can succeed (empty `egress_ip` now admits
nobody). See `DATABASE.md`.

---

## 9. Configure env files

```bash
sudo nano /etc/agrolav/hub.env
```

```text
# Comments must be on their own line. systemd EnvironmentFile does NOT
# strip inline "# comment" text after a value.
HOST=127.0.0.1
PORT=8200
AGROLAV_SQL_DISK=/opt/agrolav/workspaces
HUB_DATABASE_URL=DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=YOUR_ACTUAL_PASSWORD;Encrypt=yes;TrustServerCertificate=yes
CENTRALE_API_KEY=SOME_LONG_RANDOM_SECRET
HUB_CLIENT_URL=https://expenses.apsurt.nl
ENABLEBANKING_REDIRECT_URL=https://expenses.apsurt.nl/api/consent/callback
# Never set HUB_DEV_LOGIN on the server.
```

```bash
sudo nano /etc/agrolav/client.env
```

```text
HOST=127.0.0.1
PORT=8300
SERVER_URL=http://127.0.0.1:8200
CENTRALE_API_KEY=SOME_LONG_RANDOM_SECRET
CLIENT_AUTH=1
CLIENT_SESSION_SECRET=SOME_OTHER_LONG_RANDOM_SECRET
```

Notes:

- `CENTRALE_API_KEY` must match **byte for byte** between hub and client.
- `SERVER_URL` is how the BFF reaches the hub; it cannot be omitted.
- `CLIENT_SESSION_SECRET` must be a long random string in production.
- Do not commit these files to Git.

Verify the connection string without leaking the password:

```bash
sudo grep '^HUB_DATABASE_URL=' /etc/agrolav/hub.env \
  | sed 's/PWD=[^;]*/PWD=***REDACTED***/'
```

---

# ODBC

## 10. Install the ODBC runtime + Microsoft driver

```bash
sudo apt update
sudo apt install -y unixodbc
curl -sSL -O \
  https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb
rm packages-microsoft-prod.deb
sudo apt update
sudo ACCEPT_EULA=Y apt install -y msodbcsql18
odbcinst -q -d
```

Expected: `[ODBC Driver 18 for SQL Server]`.

---

# Systemd services

## 11. Hub service

```bash
sudo systemctl cat agrolav-hub
sudo systemctl restart agrolav-hub
sudo systemctl status agrolav-hub --no-pager
sudo journalctl -u agrolav-hub -n 50 --no-pager
```

Expected: `Application startup complete.` /
`Uvicorn running on http://127.0.0.1:8200` /
`user store ready: sqlserver:dbo.person`.

Confirm the process actually has the URL:

```bash
sudo systemctl show agrolav-hub -p MainPID
sudo tr '\0' '\n' < /proc/<MainPID>/environ \
  | grep '^HUB_DATABASE_URL=' \
  | sed 's/PWD=[^;]*/PWD=***REDACTED***/'
```

## 12. Client service

```bash
sudo systemctl restart agrolav-client
sudo systemctl status agrolav-client --no-pager
```

---

# Public URLs / reverse proxy

The frontend builds Add person as `<hub>/add-person?center=<ws>` and Upload
as `<hub>/upload?t=<token>`. On production those pages are on the same
host as the client (`https://expenses.apsurt.nl`), routed to the hub.

The hub’s wizard pages call `/api/status`, `/api/local/...`,
`/upload/api/...`, `/api/consent/callback` relative to the page origin, so
those paths must reach `127.0.0.1:8200`.

Option B (Caddy, same domain) is deployed. Option A (own subdomain) is an
alternative that needs extra DNS + certificate.

## 13. Option A — own public host for the hub (nginx; not deployed)

DNS: `hub.expenses.apsurt.nl` → `209.38.39.105`.

```nginx
server {
    listen 80;
    server_name hub.expenses.apsurt.nl;
    location / {
        proxy_pass http://127.0.0.1:8200;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Then `certbot --nginx -d hub.expenses.apsurt.nl` and set
`HUB_CLIENT_URL` / public hub URL to that host. Restart both services.

## 14. Option B — same domain, path routing (Caddy; deployed)

The client BFF has **no** `/add-person`, `/upload`, `/api/status`,
`/api/consent/callback`, or `/api/local/` routes, so these are safe to
forward to the hub. Put them **before** the catch-all to `:8300`. Forward
the real client address so login allowlists and `dbo.visitor_ip` see the
router WAN, not loopback:

```caddy
boekhouding.agrolav.nl, expenses.apsurt.nl {
    encode gzip

    handle /api/consent/callback* {
        reverse_proxy 127.0.0.1:8200 {
            header_up X-Forwarded-For {http.request.remote.host}
            header_up X-Real-IP {http.request.remote.host}
        }
    }
    handle /upload* {
        reverse_proxy 127.0.0.1:8200 {
            header_up X-Forwarded-For {http.request.remote.host}
            header_up X-Real-IP {http.request.remote.host}
        }
    }
    handle /add-person* {
        reverse_proxy 127.0.0.1:8200 {
            header_up X-Forwarded-For {http.request.remote.host}
            header_up X-Real-IP {http.request.remote.host}
        }
    }
    handle /api/status {
        reverse_proxy 127.0.0.1:8200 {
            header_up X-Forwarded-For {http.request.remote.host}
            header_up X-Real-IP {http.request.remote.host}
        }
    }
    handle /api/local/* {
        reverse_proxy 127.0.0.1:8200 {
            header_up X-Forwarded-For {http.request.remote.host}
            header_up X-Real-IP {http.request.remote.host}
        }
    }
    reverse_proxy 127.0.0.1:8300 {
        header_up X-Forwarded-For {http.request.remote.host}
        header_up X-Real-IP {http.request.remote.host}
    }
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
curl -I https://expenses.apsurt.nl/add-person?center=nl_dkg
```

→ expect `HTTP/1.1 200`.

### 14a. API key and the proxied hub paths

When `CENTRALE_API_KEY` is empty, `require_api_key` is a no-op. If the key
is set, browser calls to hub paths would get 401. Inject it server-side
(the browser never sees it). `/api/consent/callback` is unkeyed (the bank
hits it). The client BFF already sends the key itself.

```caddy
@hub_paths {
    path /add-person*
    path /upload*
    path /api/status
    path /api/consent/callback*
    path /api/local/*
}
reverse_proxy @hub_paths 127.0.0.1:8200 {
    header_up Authorization "Bearer <KEY>"
    header_up X-Forwarded-For {http.request.remote.host}
    header_up X-Real-IP {http.request.remote.host}
}
```

The repo `client/Caddyfile` ships this with
`header_up Authorization "Bearer {$CENTRALE_API_KEY}"`, so the key comes from
Caddy's environment instead of the file. Give the Caddy service a
`CENTRALE_API_KEY` matching the hub (e.g. a systemd
`EnvironmentFile=/etc/agrolav/caddy.env`) and then reload Caddy.

### 14b. Consent — `REDIRECT_URI_NOT_ALLOWED`

The hub sends `ENABLEBANKING_REDIRECT_URL` to Enable Banking. That URL
must match the app registered for `dbo.enable_connection.app_id`. On
production it must be the public Caddy callback:

```text
https://expenses.apsurt.nl/api/consent/callback
```

The deoudegracht relay forwards the browser to `127.0.0.1:8200` and only
works when a hub runs on the browser’s own machine. Register the public
URL (exact, no trailing slash) in the Enable Banking Control Panel, then
restart the hub.

To verify:

```bash
curl -s -X POST -H "Authorization: Bearer $(sudo grep -oP '^CENTRALE_API_KEY=\K.*' /etc/agrolav/hub.env)" \
  'http://127.0.0.1:8200/api/local/nl_dkg/refresh/juleon?country=nederland' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); r=(d.get('results') or [{}])[0]; print('AUTH_URL:', repr(r.get('authorization_url'))); print('WARNINGS:', d.get('warnings'))"
```

A successful start returns an `https://...enablebanking.com/ais/start?...`
URL; after consent the bank returns to
`https://expenses.apsurt.nl/api/consent/callback`.

## 15. Country / center IP allowlist

There is no hub-wide TCP allowlist. Country and center logins are gated
by the **union** of:

- `dbo.administrator` (one public address per row; every country and center)
- that login’s own `egress_ip` column (comma-separated)

Empty / NULL admits **nobody**. Person logins are not IP-gated.

Attempted public addresses land in `dbo.visitor_ip` (`username = ''` when
refused). Administrator addresses, loopback, and LAN are not logged.

After a restore with empty `egress_ip` columns, insert the production WAN
addresses into `dbo.administrator` or no country/center login will work.
The Restrict IP access page edits only the country/center columns;
administrator rows are SSMS-only.

---

# Frontend deployment

## 16. Rebuild after frontend changes

```bash
cd /opt/agrolav/client/frontend
npm ci
npm run build
sudo systemctl restart agrolav-client
```

---

# Troubleshooting

## 17. Git says up to date but the server looks old

```bash
git fetch origin
git log --oneline HEAD..origin/sqlserver
git reset --hard origin/sqlserver
git clean -fd
```

## 18. The hub will not start

```bash
sudo journalctl -u agrolav-hub -n 50 --no-pager
```

- `HUB_DATABASE_URL is not set` → env not reaching the process (§11).
- `dbo.person missing` → restore a database that contains the schema
  (`hub/sql/phase_c.sql` is wipe-and-recreate; do not run it live).
- `ImportError: libodbc.so.2` → §10.

## 19. Old user/country data still showing

SQL Server is the only store. Check in SSMS:

```sql
SELECT * FROM dbo.country;
SELECT * FROM dbo.center;
SELECT * FROM dbo.person;
```

## 20. `add-person` returns `{"detail":"Not Found"}`

Caddy sent `/add-person` to the client BFF. Route hub pages to `:8200`
(§14).

## 21. "edit categories" does not appear

Stale frontend — redo §16.

## 22. Login refused from this IP

Country/center login. The hub log names the address:

```text
login refused: 'beheer' from '80.12.34.56' is listed in neither
dbo.administrator nor its own egress_ip (NULL)
```

Insert that public address into `dbo.administrator` or the login’s
`egress_ip`. If the log says `127.0.0.1`, Caddy is not forwarding
`X-Forwarded-For` — reload Caddy from the repo `Caddyfile`. If it says
`no usable client IP`, the BFF could not derive an address at all.

Follow live refusals with:

```bash
sudo journalctl -u agrolav-hub -f
```

## 23. Login always says "invalid username or password", but the hub works

Test the hub directly with the client’s key:

```bash
PID=$(sudo systemctl show agrolav-client -p MainPID --value)
curl -s -X POST http://127.0.0.1:8200/api/auth/login \
  -H "Authorization: Bearer $(sudo tr '\0' '\n' < /proc/$PID/environ | sed -n 's/^CENTRALE_API_KEY=//p')" \
  -H 'Content-Type: application/json' \
  -d '{"username":"beheer","password":"<pw>","client_ip":"127.0.0.1"}' | head -c 300
```

Common causes:

- **Inline comment in an env value.** systemd keeps `# ...` as part of the
  value. Comments only on their own lines; restart the client.
- **`CENTRALE_API_KEY` differs** between `hub.env` and `client.env`.
- **`CENTRALE_SYNC=0|false|off|no`** in `client.env` — the client refuses
  logins entirely.

To copy the hub’s key into both files (from the running process):

```bash
HKEY=$(sudo tr '\0' '\n' < /proc/$(sudo systemctl show agrolav-hub -p MainPID --value)/environ | sed -n 's/^CENTRALE_API_KEY=//p')
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
```

---

## Copy-paste: pull, build, restart

```bash
cd /opt/agrolav
git fetch origin
git reset --hard origin/sqlserver
git clean -fd
cd shared && uv sync && cd ../hub && uv sync && cd ../client && uv sync
cd /opt/agrolav/client/frontend && npm ci && npm run build
sudo systemctl restart agrolav-hub agrolav-client
```

## Copy-paste: local `.bak` onto the remote database

1. SSMS: right-click agrolav → Tasks → Backup (Docker mapping `C:/SQLBackups`).
2. PowerShell: `scp -P 4523 C:/SQLBackups/agrolav.bak agrolav@209.38.39.105:/tmp/`
3. SSH: `ls -lh /tmp/agrolav.bak`
4. `sudo docker cp /tmp/agrolav.bak SQLServer2022:/var/opt/mssql/backup/agrolav.bak`
5. Restore with the SQL in §8.
6. Run `hub/sql/visitor_ip.sql` and `hub/sql/administrator.sql` if those
   objects are missing after the restore.

The Docker container name on the droplet has been `SQLServer2022`; if a
host uses `MSSQL2022`, substitute that name in the `docker` commands.
