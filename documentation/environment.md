# Environment variables and config files

Authoritative inventory of every **non-secret** environment variable the
three services read and the files they live in (local and on the server
`expenses.apsurt.nl`), plus how the configuration can silently disappear.

Passwords and secret variables are **not** documented here — they live only
in the single secret file and are covered by
[`passwords.md`](passwords.md). This document covers layout and mechanics.

---

## 1. How each component loads configuration

| App | Loads `.env`? | Where | Precedence |
|---|---|---|---|
| hub | Yes | `hub/.env`, then repo-root `/.env` (import-time `user_store._load_dotenv`, fills only **unset** vars) | 1. process env (systemd `EnvironmentFile`) · 2. `hub/.env` · 3. root `/.env` · 4. built-in defaults |
| client | Yes | `client/.env`, then repo-root `/.env` (import-time `app/__init__._load_dotenv`, fills only **unset** vars) | same |
| balance | Yes | `balance/.env`, then repo-root `/.env` (import-time `db._ensure_dotenv`, `load_dotenv` fills unset only) | same |

Rules shared by all apps:

- Already-set values (systemd `EnvironmentFile` on the server, an exported
  variable, a local override) are **never overridden** by a `.env` file.
- The repo-root `/.env` is the single source for every **secret** variable,
  read by all three apps automatically — the loaders already walk up to it.
- Per-service `.env` files hold only non-secret, machine-local settings
  (`HOST`, `PORT`, `HUB_DEV_LOGIN`, …). They are optional; the app runs on
  built-in defaults without them.
- `client/.env` used to be inert (client had no dotenv loader). It is now
  read, but still must not contain secrets.

---

## 2. Non-secret variables

Secret variables (`HUB_DATABASE_URL`, `MSSQL_SA_PASSWORD`, `CENTRALE_API_KEY`,
`CLIENT_SESSION_SECRET`, `HUB_OTP_SECRET`, Twilio) are omitted on purpose.

### 2.1 Client (`client/app`) — browser-facing BFF, port 8300

Read in: `client/app/centrale_sync.py`, `client/app/main.py`, `client/app/auth.py`.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` | bind host (`main.py`) |
| `PORT` | `8300` | bind port (`centrale_sync.py`, `main.py`) |
| `SERVER_URL` | `http://127.0.0.1:8200` | **internal** BFF→hub API base (`centrale_sync.py`) |
| `PUBLIC_HUB_URL` | empty → falls back to internal `SERVER_URL` | the **single browser-facing** hub base used for the Add-person wizard link; set to `https://expenses.apsurt.nl` on the server |
| `CENTRALE_SYNC` | on | `0`/`false`/`off`/`no` disables hub sync (`centrale_sync.py`) |
| `CLIENT_AUTH` | on | `0` disables browser login (`auth.py`) |
| `CLIENT_COUNTRY` / `CLIENT_CENTER` / `CLIENT_ACCESS` / `CLIENT_PERSON` / `CLIENT_BOOTSTRAP_CENTER` | empty | bootstrap defaults for the SPA (`centrale_sync.py`) |
| `COMPUTERNAME` / `HOSTNAME` | OS value | fallback machine label (`centrale_sync.py`) |

### 2.2 Hub (`hub/app`) — API + add-person wizard, port 8200

Read in: `hub/app/main.py`, `hub/app/core/single_client.py`,
`hub/app/user_store.py`, `hub/app/hub_ip.py`, `hub/app/runtime.py`.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `0.0.0.0` | bind host (`main.py`) |
| `PORT` | `8200` | bind port (`main.py`) |
| `ENABLEBANKING_REDIRECT_URL` | `https://deoudegracht.nl/banking-callback.html` | Enable Banking OAuth callback; on the server `https://expenses.apsurt.nl/api/consent/callback` |
| `HUB_CLIENT_URL` | `http://127.0.0.1:8300` | base the wizard returns the browser to after OAuth; on the server `https://expenses.apsurt.nl` |
| `HUB_DEV_LOGIN` | `0` | dev flag: skips the country/center IP gate for loopback and writes nothing to `dbo.visitor_ip`. **Never set on the server** |
| `AGROLAV_SQL_DISK` | process cwd | scratch-root for on-disk JSON when SQL is not configured (`runtime.py`) |

### 2.3 Balance (`balance/app`) — okres/balance web, port 8100

Read in: `balance/app/db.py`, `balance/app/main.py`, `balance/app/balance.py`.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` | bind host (`main.py`) |
| `PORT` | `8100` | bind port (`main.py`) |
| `BALANCE_COUNTRY_ID` | empty | pin the active country when the request has no country subpath (`balance.py`) |
| `BALANCE_DIST` | built-in path | override for the static `dist` directory (`main.py`) |

### 2.4 Caddy

The server Caddy unit loads the repo-root `/opt/agrolav/.env` via
`EnvironmentFile`; the repo `client/Caddyfile` injects the hub key with the
placeholder `header_up Authorization "Bearer {$CENTRALE_API_KEY}"` on
`/add-person*`, `/api/status` and `/api/local/*`.

---

## 3. Files

### 3.1 Local (this repo)

| File | Committed? | Contains |
|---|---|---|
| `/.env` | no (gitignored by `/.env`) | **every password** — the single secret file |
| `hub/.env.example` | yes | non-secret example template |
| `hub/.env`, `client/.env`, `balance/.env` | no | non-secret machine-local settings |
| `documentation/passwords.md` | yes | where secrets live + how to change them |

### 3.2 Server `agrolav@209.38.39.105` (ssh port 4523)

Everything under `/etc/agrolav` and `/opt/agrolav/.env` is root-only and
**outside git**. Backup manually.

| File | Read by | Contains |
|---|---|---|
| `/opt/agrolav/.env` | hub, client, balance (dotenv loaders) + Caddy (`EnvironmentFile`) | **every password** — the single secret file |
| `/etc/agrolav/hub.env` | systemd `EnvironmentFile` → agrolav-hub | non-secret settings only |
| `/etc/agrolav/client.env` | systemd `EnvironmentFile` → agrolav-client | non-secret settings only |
| `/etc/agrolav/balance.env` | systemd `EnvironmentFile` → agrolav-balance | non-secret settings only |
| `/opt/agrolav/*/.env` | the apps’ import-time dotenv | non-secret machine-local settings |
| `/etc/caddy/Caddyfile` | caddy `run --environ --config` | routing + `Authorization: Bearer {$CENTRALE_API_KEY}` placeholder |

Systemd units (what pins the non-secret config source):

```
agrolav-hub     EnvironmentFile=/etc/agrolav/hub.env      ExecStart=/home/agrolav/.local/bin/uv run hub
agrolav-client  EnvironmentFile=/etc/agrolav/client.env   ExecStart=/home/agrolav/.local/bin/uv run client
agrolav-balance EnvironmentFile=/etc/agrolav/balance.env  ExecStart=/opt/agrolav/balance/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
caddy           EnvironmentFile=/opt/agrolav/.env         ExecStart=/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile
```

---

## 4. How this configuration gets lost

1. **Fresh clone / new machine.** `git clone` brings code but **zero** env
   files. The repo ships only `hub/.env.example` + this document + the
   passwords doc; a deploy from the repo alone has no secrets and most
   non-secret settings by design.
2. **`git reset --hard`** reverts only *tracked* files; it normally leaves the
   gitignored `.env` files alone — unless a `.env` was ever committed
   (force-added, or added before `.gitignore` covered it — that history was
   scrubbed and the files are ignored now).
3. **`git clean -fdx`** deletes every *ignored* file: all local per-service
   `.env` files, the root `/.env`, and the built frontend dists. This is the
   fastest way to lose everything local. The root `/.env` is the one file that
   truly matters; keep a copy (e.g. in a password manager).
4. **Server files are outside git.** `/opt/agrolav/.env`, `/etc/agrolav/*.env`
   and `/etc/caddy/Caddyfile` survive every git operation but are lost on a
   droplet reimage, a disk swap, a manual `rm`, or a "cleanup". There is no
   committed copy; the recovery path is the redacted shape in this document +
   `passwords.md` + re-entering the real values from wherever you keep them.
5. **Config-source refactors leave files stale** (e.g. the Add-person bug,
   Sep 2026): a variable moves or appears while the env files keep the old
   name, and the app silently falls back to a default. After any refactor,
   diff this table against the running processes
   (`systemctl show <unit> -p Environment` or `/proc/<MainPID>/environ`).

### Restore / prevention checklist

- Locally: the only file with real content is the root `/.env` (secrets) —
  keep it in your password manager. Per-service `.env` files are re-creatable
  from the tables in §2 and `hub/.env.example`.
- Server: keep a copy of `/opt/agrolav/.env` + the `/etc/agrolav/*.env` files
  (root-only, redacted if shared).
- Never set `HUB_DEV_LOGIN` on the server.
- Keep secrets in exactly one file per environment (see `passwords.md`).