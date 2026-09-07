# Passwords — where they live and how to change them

## The notion of "the password" here

The services do not read passwords from a database, a config UI, or a login
table. Every credential a machine needs at runtime is read from **environment
variables**, and every env variable whose value is a password lives in **one
gitignored file** — the repo root `C:\Coding\agrolav\.env` on a development
machine, `/opt/agrolav/.env` on the server. One password = one line = one
file. No secret may be duplicated in a second env file, a script, a
connection string elsewhere, or a markdown document.

Person login passwords are a different concept (end-user credentials, scrypt
hashed in `dbo.person` or derived by formula); see
[`authentication.md`](authentication.md) and
[`double_login.md`](double_login.md). This document is strictly about service
and server secrets.

The single file is read by hub, client, balance **and** Caddy (the server
Caddy unit gets it through `EnvironmentFile=/opt/agrolav/.env`). Because every
consumer reads the same file, a change is always made in exactly one place.

---

## Password requirements (length + symbols)

Every password in the root `.env` (the four below) follows the same rules:

- **Length**: at least **16 characters**. SQL Server's own rules require only
  8, but the current values are 16–32 (`secrets.token_hex(32)` gives 64 for
  the API key). Aim for 20+ for human-chosen ones.
- **Symbols**: contain **all four classes** — upper-case, lower-case, digit,
  and symbol. (SQL Server's `CHECK_POLICY` only *requires* three of the four
  classes; we require all four.) Allowed symbols:
  `! @ # $ % ^ & * ( ) _ - + =` .
- **Charset**: no spaces, no quotes (`'` `"`), and avoided inside `.env`
  values: `#` (starts a comment), `=` (separator), and `;` (used in
  connection strings) — unless you know the consumer handles them.

Example: `Agrolav_Hub_2026!` = 16 chars, all four classes — fine by these
rules, but it is a known demo value, so rotate to a random one
(`python -c "import secrets; print(secrets.token_urlsafe(24))"`) before relying
on it.

The SSH/`agrolav` password is *not* covered by these rules: the OS enforces
its own policy via PAM (and it lives in no `.env`). The derived user-login
passwords (`PREFIX + username`) also skip this rule set on purpose.

---

## The four passwords

### 1. SQL Server `sa` password

Single place: the root `.env` file, written twice because two variables
carry it — `MSSQL_SA_PASSWORD=<the password>` and the `PWD=<the password>`
field inside `HUB_DATABASE_URL=`.

Change it:

1. Connect with SSMS (see below) and run `ALTER LOGIN [sa] WITH PASSWORD = 'YourNewPassword';`
2. Edit the single root `.env`: set `MSSQL_SA_PASSWORD=` **and** the `PWD=`
   inside `HUB_DATABASE_URL=` to the same new password.
3. Restart the services that open DB connections: `sudo systemctl restart agrolav-hub agrolav-balance` (and re-run any SQL bootstrap/import script).

Already-open connections keep working until their service restarts, so edit
the file first, then restart.

SSMS: connect to `127.0.0.1,1433` (server) / `127.0.0.1,1433` (local Docker)
as `sa` with `MSSQL_SA_PASSWORD` from the root `.env`, database `agrolav`,
Encryption *Mandatory* + *Trust server certificate*.

### 2. `CENTRALE_API_KEY`

The Bearer token the client BFF, balance, and Caddy send when calling hub
`/api/*` paths. Single place: the root `.env` file. All consumers read the
same file, so there is no cross-file "must match" dance anymore.

Change it:

1. Generate a long random value, e.g. `python -c "import secrets; print(secrets.token_hex(32))"`.
2. Replace the `CENTRALE_API_KEY=` line in the root `.env` (local) or
   `/opt/agrolav/.env` (server).
3. Restart the readers: `sudo systemctl restart agrolav-hub agrolav-client agrolav-balance`
   and `sudo systemctl restart caddy` (reload is not enough).

If it is left empty, `require_api_key` is a no-op and the hub accepts
unkeyed calls.

### 3. `CLIENT_SESSION_SECRET`

Signs the browser session cookie of the BFF. Single place: the root `.env`.

Change it:

1. Replace the `CLIENT_SESSION_SECRET=` line in the root `.env`.
2. `sudo systemctl restart agrolav-client`.

Existing browser sessions are invalidated; everyone logs in again.

### 4. SSH login (the `agrolav` user)

**Not in the `.env` file — deliberately.** It is an operating-system account
password, not an application credential, so the apps never read it. It exists
only in the account system on the server (and in your own password manager).

Change it:

```bash
ssh -p 4523 agrolav@209.38.39.105
sudo passwd agrolav
```

Then close the other SSH sessions and log in with the new password (or keep
using keys; the password is only a fallback). **Do not** ever write this value
into `.env`, a markdown file, or git. Old shell/`sudo` tokens seen in earlier
notes are historical only.

---

## Other secrets in the same file

`HUB_OTP_SECRET`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`
(person SMS login) follow the same pattern: single line in the root `.env`,
changed there, then `sudo systemctl restart agrolav-hub`.

---

## Docker (local SQL Server)

The **one** container (`agrolav-sql`, compose project `agrolav`) is defined by
`docker-compose.sqlserver.yml` in the repo root. It does **not** read a
per-service env file. It interpolates the SA password from the same single
source:

```yaml
environment:
  ACCEPT_EULA: "Y"
  MSSQL_SA_PASSWORD: ${MSSQL_SA_PASSWORD:?set in the root /.env}
```

`${MSSQL_SA_PASSWORD}` resolves from the root `/.env` (that is exactly why the
file lives at the repository root — it is Compose’s default `.env` for the
project). Only that value reaches the container; no Twilio/session/API-key
secrets are put in its environment. The backup volume path
`${AGROLAV_SQL_DISK:-C:/SQLBackups}` is interpolated from the same file.

Changing the SA password therefore means one edit in `/.env`; a recreated
container initializes with the new value. (The container only reads the
variable at first initialization, so to change an already-running instance
you still run `ALTER LOGIN [sa] WITH PASSWORD = …` and update `/.env`
together — see the `sa` section above.)

### Why Docker Desktop shows two entries

Every container runs in its own **PID namespace**: inside the container its
main process is PID 1, while the host sees the same process with a different
global PID (`docker inspect` `State.Pid` holds the host-side PID of the
container's main process). Two containers can both have an internal PID 1
without colliding.

On Docker Desktop's *Containers* page the SQL setup appears as two rows that
share one PID: the compose-project group (`agrolav`) and the container itself
(`agrolav-sql`). Both rows showing the same PID confirms they are the **same
container** — the group row is just how Docker Desktop renders the compose
stack. `docker compose ls` reports `agrolav running(1)`, i.e. one single
container.

---

## User login passwords (initial value and storage)

Every user that can log into the app starts with the **formula password**:

```
initial password = "!@#$%^&*()_" + username
```

The prefix is the constant `PASSWORD_PREFIX = "!@#$%^&*()_"` in
`hub/app/user_store.py`, not a secret. For username `beheer` the initial
password is `!@#$%^&*()_beheer`. There is no per-user secret before the user
acts.

How the three login types handle it:

| Login | Stored in DB | Initial value | Can change it |
|---|---|---|---|
| Person | scrypt hash in `dbo.person.password_hash` (`NVARCHAR(256) NULL`) | the **hash** of the formula password is stored at creation (`default_password_hash`) | yes — **Set password** writes a new scrypt hash |
| Country | nothing (no `password_hash` column) | verified **directly** against the formula (`credentials_match`) | no |
| Center | nothing (no `password_hash` column) | verified **directly** against the formula | no |

Verification logic (`user_store.credentials_match`): a person is checked
against the stored scrypt hash; if the hash column is still `NULL` (e.g.
imported before the column existed) the formula password is accepted as a
fallback. Country and center logins are always checked against the formula,
so they lean on the egress-IP allowlist instead of a strong password.

Scripts create people with `default_password_hash(username)`, and the
set-password API rejects country/center sessions even when called directly.

---

## The rules

- All passwords live only in the root `.env` (local) / `/opt/agrolav/.env`
  (server). No password anywhere else.
- `.gitignore` excludes **exactly one** file because of passwords: `/.env`.
  Every other ignore rule exists for bulkiness or uselessness only.
- Per-service env files (`hub/.env`, `client/.env`, `balance/.env`,
  `/etc/agrolav/*.env`) contain only non-secret, machine-local settings.
- A tracked file must never contain a service password. Historical leaks
  (`.tmp_terms.py`, `.tmp_schema.py`, `notes.md`) were scrubbed; do not repeat
  them.
- Do not paste a real password into a doc, a script, or a commit message.

## Local start

```powershell
cd C:\Coding\agrolav\hub
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& .venv\Scripts\Activate.ps1
uv sync
uv run hub
```

`HUB_DEV_LOGIN=1` (in `hub/.env`) lets country/center logins through on
loopback and writes nothing to `dbo.visitor_ip`. Never set it on the server.


---

## Exposure: disk vs terminal

**Disk storage is the safer of the two places these secrets live.**

- **Server `/opt/agrolav/.env`** is `root:root 600`. Only root and the
  systemd-run services (hub, client, balance, Caddy — all run as root, no
  `User=` set) can read it. Attack surface is SSH brute-force on port 4523 and
  any public-facing FastAPI/Caddy process exploited for RCE/SSRF. To read the
  file an attacker already has to own a root process or have escalated locally
  — at that point `.env` is the prize, not the entry.
- **Local `C:\Coding\agrolav\.env`** is a plaintext file readable by your
  Windows user. Any malware/ransomware running as your user can read it. It is
  gitignored, so it never reaches git.

**The more realistic leak is the terminal/stdout**, not the disk: running
`cat`, `grep`, or `sed` on `.env` prints the values into your shell scrollback
and any pasted logs. That is how the values end up in nathan logs, pastebins,
or session transcripts.

- The single file is read by hub, client, balance **and** Caddy (the server
  Caddy unit gets it through `EnvironmentFile=/opt/agrolav/.env`). Because every
  consumer reads the same file, a change is always made in exactly one place.

**Hardening:**

- Keep `600` on the server `.env` and `/.env` in `.gitignore` on the local
  repo.
- Never echo `.env` to stdout, a shared command, or a pastebin. When you must
  inspect it, use `sudo grep <key-name> .env` and avoid dumping the whole
  file.
- Ensure no FastAPI route or static mount can resolve to `.env`. All services
  mount specific directories, never the repo root — keep it that way.
- Rotate weak/derivable secrets periodically (the server `CLIENT_SESSION_SECRET`
  is still a `<secret>` placeholder; rotate it) especially if a value was ever
  printed to a terminal/log.
- Optional defense-in-depth against local malware: encrypt the local `.env`
  (EFS/DPAPI) or move secrets to a manager; this is optional, not required.

---

# Root password of the server
```
ssh -p 4523 root@209.38.39.105
```
or 
```
ssh -p 4523 root@expenses.apsurt.nl
```
logs in as the root account on that Droplet. The root password is whatever was set when the Droplet was created (hosting provider default, or changed since). If you don't know it, you can reset it from your hosting provider's control panel — or just keep using agrolav with sudo.