# Safety — logins and secret files on Digital Ocean

Public site: `https://expenses.apsurt.nl`. Hub and client stay on the
droplet; Caddy is the only process on 80/443.

Two kinds of secret, stored differently:

| What | After SQL Server cutover | Until then |
|:-----|:-------------------------|:-----------|
| Logins (`workspaces/users.db`) | `dbo.app_user` in SQL Server; remove the SQLite file from the web box | SQLite next to data, not in git |
| Enable Banking (`secret/*.pem`, `consent.json`) | **Stay files forever** | Same folders the hub already reads |

Do not load PEMs into SQL Server. A database backup would then hold bank
credentials. `personal_categories.json` can move to SQL later; `.pem`
files must not. Uploaded CSV/xlsx, `upload_acl.json`, and `upload.log`
also stay files (`DATABASE.md`).

`workspaces/` is gitignored. Never `git add` PEMs, `users.db`, or the
data tree.

---

## Copy to the droplet

From the PC, **SCP/SFTP over SSH only**. Same pattern as
`DEPLOYMENT_GUIDE.md`. No email, no browser upload of `secret/`, no
public Spaces URL, no git.

```powershell
scp -P 4523 -r C:\Coding\agrolav\workspaces agrolav@<DROPLET_IP>:/opt/agrolav/workspaces
```

Use a key. Do not put the SSH password in this repo or in markdown.

---

## On the droplet

Keep files under `BOEKHOUDING_DATA_ROOT` (e.g. `/opt/agrolav/workspaces`).
Hub and client listen on `127.0.0.1:8200` and `:8300`. Do not open those
ports. Do not proxy `/workspaces` or `*.pem` through Caddy.

```text
Browser → https://expenses.apsurt.nl
       → Caddy (TLS)
       → 127.0.0.1:8300  client
       → 127.0.0.1:8200  hub  (localhost only)
```

Permissions (hub service user owns the tree):

| path | mode |
|:-----|:-----|
| `secret/` directories | `700` |
| `*.pem`, `users.db` | `600` |

Prefer an encrypted DigitalOcean volume for this tree.

A secrets manager is extra machinery for PEM *files* the hub must read
from disk. A locked directory on the droplet plus encrypted backups is
the right level for this app.

---

## Backups

Encrypt before they leave the box (`restic`, `borg`, or a tarball with
`age`/`gpg`). Send only to a **private** Spaces bucket (or equivalent).
Unencrypted PEMs in object storage are a leak.

---

## Logins are weaker than the file format

Password currently equals username. Guessing a person folder is enough
to log in. Hash passwords (upload tokens already use scrypt) before the
host is public. After phase B, store hashes in SQL Server — not a copy
of `users.db` beside the web app.

---

## Do not

- Commit `workspaces/`, `*.pem`, `users.db`, or connection strings
- Put SSH passwords, API keys, or session secrets in git or in docs
- Serve hub/client on a public port
- Store Enable Banking keys in SQL Server
- Refresh data with `git pull` over `workspaces/`
