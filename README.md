# agrolav — household bookkeeping

Hub + client for `https://boekhouding.agrolav.nl` (Caddy on AWS Lightsail → Tailscale → home server).

```text
agrolav/
  hub/          :8200 — data API, refresh, upload, add-person
  client/       :8300 — BFF + React UI
  shared/       login access helpers (user_access)
  agrolav-sql   SQL Server — all data (persons, centers, countries, transactions, categories)
  deploy/       optional ops notes / Caddyfile samples
```

## Run (home server)

```powershell
cd C:\Coding\agrolav\hub
uv sync
uv run hub

# other terminal
cd C:\Coding\agrolav\client
uv sync
cd frontend
npm install
npm run build
cd ..
# production: set a real secret once on the machine
# [System.Environment]::SetEnvironmentVariable("CLIENT_SESSION_SECRET","…","Machine")
uv run client
```

Open `http://127.0.0.1:8300` (or `https://boekhouding.agrolav.nl` via Lightsail).

## Client config — none

There is **no** `client_config.json`. Defaults are hardcoded; override only with env vars:

| Variable | Default | Meaning |
|----------|---------|---------|
| `SERVER_URL` | `http://127.0.0.1:8200` | Hub URL |
| `PORT` | `8300` | Client listen port |
| `CLIENT_AUTH` | on | Browser login |
| `CLIENT_SESSION_SECRET` | insecure dev string | **Set in production** |
| `CENTRALE_API_KEY` | empty | Optional hub Bearer |
| `CENTRALE_SYNC` | on | Hub sync |
| `ENABLEBANKING_REDIRECT_URL` | `http://127.0.0.1:8200/api/consent/callback` | Exact callback registered with Enable Banking; set to the public HTTPS callback in production |

Logins live in SQL Server (dbo.country / dbo.center / dbo.person); the hub requires SQL.

## Public front door (already set up)

```text
Browser → https://boekhouding.agrolav.nl
       → Lightsail Caddy
       → Tailscale → 100.116.99.89:8300 (client)
                   → 127.0.0.1:8200 (hub → SQL agrolav-sql)
```

Bank data and PEMs stay on the home server. Lightsail only proxies HTTPS.

## Build frontend after UI changes

`client/frontend/dist/` is gitignored. On every machine that serves `:8300`:

```powershell
cd C:\Coding\agrolav\client\frontend
npm run build
```

Then restart the client.
