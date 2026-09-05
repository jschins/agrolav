# Environment variables, config files, and how the config gets lost

Authoritative inventory of every environment variable the three services read, the
files they live in (local and on the server `expenses.apsurt.nl`), and the ways this
configuration can silently disappear (e.g. `git reset --hard`, `git clean -fdx`,
fresh clones, or a config-source refactor).

Also see `deployment.md` for the full install procedure; this document is the
variable-by-variable reference and the "oh no, where did my config go" checklist.

> Values below are **placeholders**. Real secrets (SA password, `CENTRALE_API_KEY`,
> Twilio tokens, SSH password) live only in the local/server env files, never in git.

---

## 1. How each component loads configuration

The three apps load config **very differently**. This is the single most common
source of "it works locally but not on the server" confusion.

| App | Loads `.env` at all? | Where | Precedence |
|---|---|---|---|
| hub | Yes | `hub/.env`, then repo-root `/.env` (import-time `user_store._load_dotenv`, fills only **unset** vars) | 1. process env (systemd `EnvironmentFile`) · 2. `hub/.env` · 3. root `/.env` |
| client | **No** | nowhere — reads only `os.environ` | process env (systemd `EnvironmentFile`) only · **`client/.env` is inert** |
| balance | Yes | `balance/.env` (python-dotenv at import, `db._ensure_dotenv`) | 1. process env (systemd `EnvironmentFile`) · 2. `balance/.env` |

Consequences:

- On the server the systemd `EnvironmentFile` files under `/etc/agrolav` are **always
  the winner**; the copies under `/opt/agrolav/*/.env` only fill what the systemd file
  leaves unset (hub/balance) or do nothing at all (client).
- A pasted `client/.env` is decorative. `PUBLIC_HUB_URL` (and everything else) for the
  client must go into `/etc/agrolav/client.env`.
- The only committed template in the repo is `hub/.env.example`. There is none for
  `client` or `balance`.

---

## 2. Variables

### 2.1 Client (`client/app`) — browser-facing BFF, port 8300

Read in: `client/app/centrale_sync.py`, `client/app/main.py`, `client/app/auth.py`.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` | bind host (`main.py:1061`) |
| `PORT` | `8300` | bind port (`centrale_sync.py:83`, `main.py:1068`) |
| `SERVER_URL` | `http://127.0.0.1:8200` | **internal** BFF→hub API base (`centrale_sync.py:73`) |
| `PUBLIC_HUB_URL` | empty → falls back to internal `SERVER_URL` | the **single browser-facing** hub base used for the Add-person wizard link (`centrale_sync.py:64,55`). Set to `https://expenses.apsurt.nl` on the server |
| `CENTRALE_API_KEY` | empty | Bearer key the BFF uses when calling hub `/api/*`; must match hub byte-for-byte |
| `CENTRALE_SYNC` | on | `0`/`false`/`off`/`no` disables hub sync (`centrale_sync.py:75`) |
| `CLIENT_AUTH` | on | `0` disables browser login (`auth.py:42`) |
| `CLIENT_SESSION_SECRET` | insecure built-in default | cookie signing secret; **required long+random in production** (`auth.py:52`) |
| `CLIENT_COUNTRY` / `CLIENT_CENTER` / `CLIENT_ACCESS` / `CLIENT_PERSON` / `CLIENT_BOOTSTRAP_CENTER` | empty | bootstrap defaults for the SPA (`centrale_sync.py:252`–`297`) |
| `COMPUTERNAME` / `HOSTNAME` | OS value | used as a fallback machine label (`centrale_sync.py:851`) |

### 2.2 Hub (`hub/app`) — API + add-person wizard, port 8200

Read in: `hub/app/main.py`, `hub/app/core/single_client.py`, `hub/app/user_store.py`,
`hub/app/hub_ip.py`, `hub/app/person_otp.py`, `hub/app/runtime.py`,
`hub/app/app_config.py`.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `0.0.0.0` | bind host (`main.py:2677`) |
| `PORT` | `8200` | bind port (`main.py:2678`) |
| `HUB_DATABASE_URL` | empty | SQL Server connection string (`user_store.py:104`); identical format in balance |
| `CENTRALE_API_KEY` | empty | key other services use to reach hub `/api/*`. Resolved **`dbo.app_config` row first, then env** (`app_config.centrale_api_key`, `app_config.py:67`) |
| `ENABLEBANKING_REDIRECT_URL` | `https://deoudegracht.nl/banking-callback.html` | Enable Banking OAuth callback (`single_client.py:38`). On the server: `https://expenses.apsurt.nl/api/consent/callback` |
| `HUB_CLIENT_URL` | `http://127.0.0.1:8300` | base the wizard returns the browser to after OAuth (`main.py:20,30`). On the server: `https://expenses.apsurt.nl` |
| `HUB_DEV_LOGIN` | `0` | dev flag: skips the country/center IP gate for loopback and writes nothing to `dbo.visitor_ip` (`hub_ip.py:98`). **Never set on the server** |
| `MSSQL_SA_PASSWORD` | – | SA password used by SQL bootstrap/import scripts (`hub/.env.example`; not read by the app runtime) |
| `AGROLAV_SQL_DISK` | process cwd | scratch-root for on-disk JSON when SQL is not configured (`runtime.py:85`) |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM` | unset | person SMS OTP; **all three** must be set, else the hub prints the OTP to stdout (`person_otp.py:40`) |
| `HUB_OTP_SECRET` | insecure built-in default | JWT secret for `otp_token` (`person_otp.py:37`) |
| `ENABLEBANKING_APP_ID` / `ENABLEBANKING_KEY_PATH` | legacy | mentioned only in an error message (`core/enable_banking/__init__.py:39`). Real credentials now live per person in the DB (`single_client.py:236`) |

### 2.3 Balance (`balance/app`) — okres/balance web, port 8100

Read in: `balance/app/db.py`, `balance/app/main.py`, `balance/app/balance.py`.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` | bind host (`main.py:149`) |
| `PORT` | `8100` | bind port (`main.py:148`) |
| `HUB_DATABASE_URL` | empty | SQL Server connection string (`db.py:28`); same database as hub |
| `BALANCE_COUNTRY_ID` | empty | pin the active country when the request has no country subpath (`balance.py:134`) |
| `BALANCE_DIST` | built-in path | override for the static `dist` directory (`main.py:17`) |
| `CENTRALE_API_KEY` | empty | key for hub API calls when enabled (`main.py:44`) |

### 2.4 Caddy

- Repo `client/Caddyfile` injects the hub key with the placeholder
  `header_up Authorization "Bearer {$CENTRALE_API_KEY}"` on `/add-person*`,
  `/api/status` and `/api/local/*`. The placeholder resolves from Caddy's
  environment (`caddy run --environ`).
- On the server caddy has **no** `EnvironmentFile`, so the literal key was inlined
  into `/etc/caddy/Caddyfile` (matches the `<KEY>` form in `deployment.md` §14/14a).

---

## 3. Files

### 3.1 Local (this repo)

All `.env` files are gitignored (`.gitignore` line 10: `.env` matches at any depth).

| File | Committed? | Read by |
|---|---|---|
| `hub/.env.example` | yes | template only |
| `hub/.env` | no | hub (import-time dotenv) |
| `client/.env` | no | **nothing — inert** (client has no dotenv) |
| `balance/.env` | no | balance (python-dotenv) |
| `/.env` | no | hub (repo-root fallback candidate, usually absent) |

### 3.2 Server `agrolav@209.38.39.105` (ssh port 4523)

Everything under `/etc/agrolav` is root-only and **outside git**. Backup manually.

| File | Read by | Current variable names (values redacted) |
|---|---|---|
| `/etc/agrolav/hub.env` | systemd `EnvironmentFile` → agrolav-hub | `HOST`, `PORT`, `HUB_DATABASE_URL`, `CENTRALE_API_KEY`, `ENABLEBANKING_REDIRECT_URL`, `HUB_CLIENT_URL` |
| `/etc/agrolav/client.env` | systemd `EnvironmentFile` → agrolav-client | `HOST`, `PORT`, `SERVER_URL`, `CLIENT_AUTH`, `CLIENT_SESSION_SECRET`, `CLIENT_COUNTRY`, `CENTRALE_API_KEY`, `PUBLIC_HUB_URL` |
| `/etc/agrolav/balance.env` | systemd `EnvironmentFile` → agrolav-balance | `HOST`, `PORT`, `HUB_DATABASE_URL` |
| `/opt/agrolav/hub/.env` | hub import-time dotenv (fills unset only) | `MSSQL_SA_PASSWORD`, `HUB_DATABASE_URL`, `AGROLAV_SQL_DISK`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` (copied during setup; `HUB_DEV_LOGIN=1` was stripped in Sep 2026) |
| `/opt/agrolav/client/.env` | **nothing** | `CLIENT_SESSION_SECRET` (inert copy) |
| `/opt/agrolav/balance/.env` | balance python-dotenv | `HUB_DATABASE_URL`, `HOST`, `PORT` (duplicate of `balance.env`) |
| `/etc/caddy/Caddyfile` | caddy `run --environ --config` | routing + inlined `Authorization: Bearer <key>` |

Systemd units (what actually pins the config source):

```
agrolav-hub     EnvironmentFile=/etc/agrolav/hub.env      ExecStart=/home/agrolav/.local/bin/uv run hub
agrolav-client  EnvironmentFile=/etc/agrolav/client.env   ExecStart=/home/agrolav/.local/bin/uv run client
agrolav-balance EnvironmentFile=/etc/agrolav/balance.env  ExecStart=/opt/agrolav/balance/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
caddy           (no EnvironmentFile)                      ExecStart=/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile
```

---

## 4. How this configuration gets lost

The config is almost entirely **outside git**, which is exactly why `git` operations
hit it in surprising ways.

1. **Fresh clone / new machine.** `git clone` brings the code but *zero* `.env` files.
   Only `hub/.env.example` exists in the repo, and it documents a fraction of the
   variables (no `HOST`/`PORT`/`SERVER_URL`/`PUBLIC_HUB_URL`/`CENTRALE_API_KEY`/
   `HUB_CLIENT_URL`/`ENABLEBANKING_REDIRECT_URL`/`CLIENT_AUTH`/`BALANCE_COUNTRY_ID`…).
   A deploy built from the repo alone is therefore missing most config by design.

2. **`git reset --hard`** reverts only *tracked* files. It normally leaves gitignored
   `.env` files alone — **unless** the `.env` was ever committed (force-added with
   `git add -f`, or added before `.gitignore` covered it). In that case:
   - resetting to a commit *before* the file was tracked **deletes the file**;
   - resetting to a newer/older content **reverts it to the committed version**,
     silently restoring stale or wrong secrets;
   - `git checkout -- .` / `git restore .` do the same on the working tree.
   And even when `.env` survives, `git reset --hard` reverts the *code*: the app may
   return to an older config scheme (e.g. the `dbo.app_config`-based URL lookups) that
   no longer matches the env files you keep, so the server starts behaving like it did
   pre-refactor.

3. **`git clean -fdx`** — frequently run right after a botched `reset --hard` — deletes
   *ignored* files. This wipes every local `hub/.env`, `client/.env`, `balance/.env`
   and the built frontend dists in one go. This is the fastest way to lose everything.

4. **Server files are outside git entirely.** `/etc/agrolav/*.env`, `/opt/agrolav/*/.env`
   and `/etc/caddy/Caddyfile` survive every git operation, but are lost on a droplet
   reimage, a disk swap, a manual `rm`, or a "cleanup". There is no committed copy —
   the closest thing is the redacted template in `deployment.md` (§4, lines ~200–230).

5. **Config-source refactors leave env files stale** (this is exactly what happened with
   the add-person bug, Sep 2026): when hub URLs moved out of `dbo.app_config` into
   `PUBLIC_HUB_URL` / `HUB_CLIENT_URL` / `ENABLEBANKING_REDIRECT_URL`, the server env
   files still had neither, so the wizard silently fell back to `127.0.0.1` URLs. The
   code changed; the env files did not, and nothing in the repo documented the new
   variables for a quick diff.

6. **Copying `.env` between machines leaks assumptions.** Copying your local `hub/.env`
   to the server brought `HUB_DEV_LOGIN=1` (a dev-only flag) along — it had to be
   stripped manually. And copying `client/.env` gave false confidence: with no dotenv
   loader it changed nothing at all.

7. **`/etc/agrolav/*.env` are root-only and not in git**: if they are ever edited
   from a non-root shell via `sudo tee`/`sed`, a typo or a lost newline can silently
   drop a variable the running service never re-reads until its next restart.

### Restore / prevention checklist

- Local: `copy hub/.env.example hub/.env`, fill in the values from §2; create
  `client/.env` and `balance/.env` from the tables too. When in doubt, pull from
  `/etc/agrolav` on the server — it is the canonical copy.
- Server: keep a redacted backup of `/etc/agrolav/*.env`, `/opt/agrolav/*/.env` and
  `/etc/caddy/Caddyfile` (e.g. the `deployment.md` template) so a rebuild is not guesswork.
- Never set `HUB_DEV_LOGIN` on the server.
- After any `git reset --hard` / `git clean`, re-diff this table against the running
  processes: `systemctl show <unit> -p Environment` or `/proc/<MainPID>/environ`.
- `CENTRALE_API_KEY` must match byte-for-byte in the hub env (or `dbo.app_config`) and
  every caller (`client.env`, Caddy) — mismatch = silent 401s behind the proxy.