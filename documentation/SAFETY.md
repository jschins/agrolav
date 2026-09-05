# Safety — logins and secrets on the droplet

Public site: `https://expenses.apsurt.nl`. Hub and client stay on the
droplet; Caddy is the only process on 80/443.

| What | Where it lives |
|:-----|:---------------|
| Logins | `dbo.country` / `dbo.center` / `dbo.person`. Person passwords are scrypt hashes on `dbo.person.password_hash`; country and center use the derived formula password. |
| Enable Banking PEM and session | `dbo.enable_connection` (`pem`, `app_id`, `session_id`, `valid_until`) |
| SQL connection, API key, Twilio, session cookie | `/etc/agrolav/hub.env` and `client.env` (systemd). Locally `hub/.env` / `client/.env`. Never git. |

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
scp -P 4523 C:\SQLBackups\agrolav.bak agrolav@<DROPLET_IP>:/tmp/
```

Use a key. Do not write the SSH password here.

---

## Do not

- Commit `*.env`, `*.pem`, or connection strings
- Put SSH passwords, API keys, or session secrets in git or in docs
- Serve hub/client on a public port
- Set `HUB_DEV_LOGIN` on the server
- Refresh data with `git pull` over workspaces or backups
