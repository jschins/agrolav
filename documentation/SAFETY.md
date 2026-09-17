# Safety

Public site: `https://expenses.apsurt.nl`. Caddy is the only process on
80/443. Hub, client, balance, and maaltijden bind to localhost. Secrets
live in one gitignored file ([`passwords.md`](passwords.md)). Do not put
passwords, API keys, or PEMs in git or in this file.

The issues below are the ones that actually matter for this project, in
rough order.

---

## 1. SQL Server is on the public internet

Docker `MSSQL2022` publishes **1433 on `0.0.0.0`**. SSMS can connect to
`209.38.39.105,1433` as `sa`. That is the whole database: bookings, person
hashes, country/center logins, **Enable Banking private keys**, IP
allowlists.

Anyone who guesses or leaks `sa` owns every secret in Agrolav. Firewall
1433 to known admin IPs, or bind SQL to localhost and tunnel. Do not leave
`sa` as the app login forever.

## 2. Enable Banking keys live in the database

`dbo.enable_connection.pem` is the bank API private key for a person. A
`.bak`, an SSMS export, or a stolen `sa` session is a bank credential
leak, not only an accounting leak.

Encrypt backups before they leave the machine (`restic`, `borg`, or a
tarball with `age`/`gpg`) and send them only to a **private** bucket.
`scripts/pull-remote-backup.ps1` must delete the droplet `.bak` after a
successful copy. Do not leave `agrolav.bak` under
`/opt/sql_backups/remote_backups/`. Copy with **SCP over SSH port 4523**
only — no email, no public object URL, no git.

## 3. Country and center passwords are not real passwords

Those logins still derive the password from the username. The gate is the
**egress-IP allowlist**: `dbo.administrator` union that row’s `egress_ip`.
Empty or NULL admits **nobody**. A listed IP plus the known formula is a
successful login.

Keep those lists short. After a restore, fill production WAN addresses
before anyone can log in as a country or center.

Never set `HUB_DEV_LOGIN` on the droplet. It skips the IP gate for
loopback and writes nothing to `dbo.visitor_ip`. It is only for a
developer’s own machine.

Person logins are hashed and can require SMS OTP when `mobile_phone` is
set. They are **not** IP-gated. A person without a phone is password-only.

## 4. An empty hub API key opens the internal API

Hub `/api/*` has no browser session. It only checks
`Authorization: Bearer …` when `CENTRALE_API_KEY` is set. Empty, that
check is a no-op: anyone who can open TCP to `:8200` can read and write
people, transactions, wipe a year, or shut the hub down.

On the droplet: keep the key set, keep `:8200` on **127.0.0.1**, restart
hub, client, **and Caddy** after a key change.

The browser must never hold this key. The SPA talks to the client; the
client adds the Bearer token.

## 5. Caddy injects that key onto public hub paths

Caddy stamps `Authorization: Bearer {$CENTRALE_API_KEY}` onto `/upload*`,
`/add-person*`, `/api/status`, and `/api/local/*`. Those URLs are on the
public site. The key does **not** stop a random visitor; Caddy supplies it
for them. Their real gates are Caddy routing, the upload ACL, and the
login IP allowlist. Do not add new public Caddy→hub paths without a gate
of their own.

`/api/consent/callback` is also public (Enable Banking redirect). Do not
proxy other hub routes through Caddy.

## 6. The balance sheet has no login

`/balance/{slug}` (slug = `dbo.country.username` with `has_balance = 1`)
is served to the browser with **no session and no API key**. Anyone who
can guess `beheer_sdog` (or another slug) and reach the site can read and
post the sheet. Treat those URLs as sensitive; do not advertise them; a
later lock would be a separate `BALANCE_API_KEY` plus a real login.

## 7. Maaltijden stores passphrases in plain text

`dbo.maaltijden_users.passphrase` is compared as stored. `NULL` means
**no password**. `/maaltijden` is on the public Caddy vhost. Use a
passphrase, not NULL, and do not reuse person or country passwords there.

## 8. You cannot see most attackers in SQL today

Until `hub/sql/visitor_ip.sql` is applied on the droplet and the hub is
restarted, `dbo.visitor_ip` only stores **login POSTs**, collapsed with
no timestamp. Port scans, `GET /`, `/.env`, WordPress probes never appear.
Caddy has **no access log** in the current `Caddyfile`. `dbo.administrator`
addresses are not logged on purpose.

After the new columns: `login_page = 1` is every login/OTP post
(immediate); `login_page = 0` is other HTTP, at most once per UTC day.

## 9. SSH is password login, services run as root

Port **4523**, user `agrolav`, plus `sudo`. Prefer a key and disable
password SSH when you can. systemd units run as **root** so they can read
`/opt/agrolav/.env` (`600`). That file is then the prize for any RCE in
hub, client, Caddy, or SQL.

Do not `cat` `.env` into a terminal, chat, or pastebin. Inspect with
`sudo grep KEYNAME /opt/agrolav/.env`.

---

## Shape of the public hop

```text
Browser → https://expenses.apsurt.nl
       → Caddy (TLS)
       → 127.0.0.1:8300  client
       → 127.0.0.1:8200  hub   (localhost only)
       → 127.0.0.1:8100  balance
       → 127.0.0.1:8400  maaltijden
```

Caddy must forward `X-Forwarded-For` so country/center allowlists and
`dbo.visitor_ip` see the caller’s public IP, not `127.0.0.1`. See
`client/Caddyfile`.

Do not open 8100/8200/8300/8400. Do not proxy 1433 through Caddy.

---

## Do not

- Commit `*.env`, `*.pem`, or connection strings
- Put a password anywhere except the single secret file
  ([`passwords.md`](passwords.md))
- Serve hub, client, balance, or maaltijden on a public port
- Set `HUB_DEV_LOGIN` on the server
- Leave `CENTRALE_API_KEY` empty on the server
- Leave a `.bak` on the droplet
- Refresh live workspaces or backups with `git pull`
- Trust `dbo.visitor_ip` as a complete attack log
