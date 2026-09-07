# Safety — logins and secrets on the droplet

Public site: `https://expenses.apsurt.nl`. Hub and client stay on the
droplet; Caddy is the only process on 80/443.

Secrets and passwords are managed in exactly one place per environment
([`passwords.md`](passwords.md) — the single secret file, how to change each
value, and the rules). This page is about operational procedure only.

The hub refuses to start without `HUB_DATABASE_URL`.

A database backup contains Enable Banking private keys. Encrypt backups
before they leave the box (`restic`, `borg`, or a tarball with `age`/`gpg`)
and send them only to a **private** bucket.

Do not put SSH passwords, API keys, or session secrets in git or in
markdown.

---

## On the droplet

Hub and client listen on `127.0.0.1:8200` and `:8300`. Do not open those
ports. Do not proxy database ports through Caddy.

```text
Browser → https://expenses.apsurt.nl
       → Caddy (TLS)
       → 127.0.0.1:8300  client
       → 127.0.0.1:8200  hub  (localhost only)
```

Caddy must forward `X-Forwarded-For` so country/center allowlists see the
caller’s public egress IP. See `client/Caddyfile`.

---

## Login strength

Person logins are hashed and can require an SMS one-time code when
`mobile_phone` is set. Country and center logins still derive their
password from the username, so they lean on the egress-IP allowlist: the
address must be listed in `dbo.administrator` or in that login’s own
`egress_ip` column, and an empty column admits nobody. Keep those lists
short.

Never set `HUB_DEV_LOGIN` on the droplet. It exists only so a developer’s
own machine, where everything is loopback, can log in without a public
address to list.

---

## Copy

From the PC, **SCP/SFTP over SSH only**. No email, no browser upload, no
public object URL, no git of secrets.

```powershell
scp -P 4523 C:\SQLBackups\local_backups\agrolav.bak agrolav@<DROPLET_IP>:/tmp/
```

Use a key. Do not write the SSH password here — it belongs in a password
manager only (see `passwords.md`).

---

## Do not

- Commit `*.env`, `*.pem`, or connection strings
- Put SSH passwords, API keys, or session secrets in git or in docs
- Put a password anywhere except the single secret file (see `passwords.md`)
- Serve hub/client on a public port
- Set `HUB_DEV_LOGIN` on the server
- Refresh data with `git pull` over workspaces or backups
- Leave `CENTRALE_API_KEY` empty on the server




---
## Hub API key (`CENTRALE_API_KEY`)
The hub is an **internal service**: other programs on the same machine
call it; browsers should not. On the droplet that hop is client →
`127.0.0.1:8200`. The public site is Caddy + the client; people log in
there. How to set the value: [`passwords.md`](passwords.md).
Hub `/api/*` routes do not check a browser session cookie. They only
check `Authorization: Bearer …` when `CENTRALE_API_KEY` is set. Missing
or empty, that check does nothing and the hub accepts unkeyed calls.
Anyone who can open TCP to the hub can then read and write data
(people, transactions, wipe-year, shutdown).
With the key set:
- Only callers that know the secret get in (client BFF, Caddy on a few
  paths). A direct `curl` to `:8200` gets `401`.
- The browser never holds it. The SPA talks to the client; the client
  adds the Bearer token when it calls the hub.
- `POST /api/auth/login` on the hub is keyed too, so password guessing
  against port 8200 needs the token first.
It is one shared machine secret, not per-user login. It does not replace
person/country/center passwords, SMS OTP, or the IP allowlist.
Caddy stamps `Authorization: Bearer {$CENTRALE_API_KEY}` onto
`/upload*`, `/add-person*`, `/api/status`, and `/api/local/*` so the
add-person wizard can call the hub without the key in the page. Those
public paths are therefore not locked by the key; Caddy supplies it for
every visitor. Their gates are Caddy routing, upload ACL, and the hub
IP allowlist.
On the droplet, keep the key set and keep `:8200` bound to localhost.