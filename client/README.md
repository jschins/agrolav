# boekhouding-client

Thin BFF + frontend. All data comes from the hub (no local center copies).
Frontend user guide: [`../README.md`](../README.md). Production:
[`../documentation/deployment.md`](../documentation/deployment.md).

## Configuration (no config file)

Defaults are hardcoded. Override only via environment variables when needed.

| Variable | Default | Meaning |
|----------|---------|---------|
| `SERVER_URL` | `http://127.0.0.1:8200` | Hub base URL (server-to-server API) |
| `PUBLIC_HUB_URL` | unset → `SERVER_URL` | Browser-facing hub base for the Add person / Upload links — **set to the public host in production** (e.g. `https://expenses.apsurt.nl`); on a dev machine leave unset to use `SERVER_URL` |
| `PORT` | `8300` | Client listen port |
| `CLIENT_AUTH` | on (`true`) | Browser login; set `0`/`false` to disable |
| `CLIENT_SESSION_SECRET` | insecure dev string | Cookie signing secret — **set in production** |
| `CENTRALE_API_KEY` | empty | Optional hub Bearer token (must match the hub) |
| `CENTRALE_SYNC` | on | Set `0`/`false` to disable hub sync |
| `CLIENT_BOOTSTRAP_CENTER` | first hub center / `dkg` | Center used before login (auth on) |
| `CLIENT_ACCESS` | `local` | Only when auth off |
| `CLIENT_CENTER` | empty | Only when auth off |
| `CLIENT_PERSON` | empty | Only when auth off |

There is **no** `client_config.json`.

### Multi-user login (default)

The client listens on **`0.0.0.0`** when auth is on. On the same machine as
the hub, leave `SERVER_URL` at `http://127.0.0.1:8200`.

Users live in SQL Server (`dbo.person` / `dbo.center` / `dbo.country`).
Person logins use a scrypt hash (`dbo.person.password_hash`) and an SMS
code when `mobile_phone` is set. Country and center use the derived
formula password and are IP-gated (see the hub README).

```powershell
cd ..\hub
uv run python scripts/user_admin.py list
```

## Run

```powershell
# hub must be running on :8200 first
cd C:\Coding\agrolav\client
uv sync
# optional for production:
# $env:CLIENT_SESSION_SECRET = "long-random-string"
uv run client
```

## Onefile build

```powershell
cd C:\Coding\agrolav\client
uv sync --group build
uv run python scripts/build_onefile.py
```

Output: `dist/boekhouding-client.exe`. Set `CLIENT_SESSION_SECRET` when
running the exe.

## Production

Caddy terminates HTTPS for `expenses.apsurt.nl` and proxies to this client
on `:8300`. Hub stays at `127.0.0.1:8200` on the same host. Caddy must
forward `X-Forwarded-For` (see `Caddyfile`) so the hub sees the caller’s
public egress IP. Set `CLIENT_SESSION_SECRET` and match
`CENTRALE_API_KEY` to the hub.
