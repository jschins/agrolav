# boekhouding-hub

Always-on hub; all data lives in SQL Server (agrolav-sql), not folders. See
[`../README.md`](../README.md) for the frontend and
[`../documentation/deployment.md`](../documentation/deployment.md) for
production.

**Centers and persons** are SQL Server rows (`dbo.center`, `dbo.person`);
the hub never creates folders on disk.

## Listen / client `SERVER_URL`

Default `HOST=0.0.0.0` `PORT=8200`. Allow inbound TCP **8200** on the host
firewall when clients on other machines need the hub.

The client has **no** `client_config.json`. Point it at the hub with env
`SERVER_URL` (default `http://127.0.0.1:8200`):

| Where the client runs | `SERVER_URL` |
|-----------------------|--------------|
| Same PC as the hub | `http://127.0.0.1:8200` (default) |
| Another PC on the home LAN | `http://<hub-lan-ip>:8200` |
| Another PC via [Tailscale](https://tailscale.com/) | `http://<hub-tailscale-ip>:8200` |

Start the hub on **8200** first, then the client on **8300**.

## Country / center IP allowlist

There is no hub-wide TCP gate. Country and center logins are allowed only
from addresses listed in `dbo.administrator` or in that login’s own
`egress_ip` column. The allowed set is the sum of the two; an empty column
admits nobody. Person logins are not IP-gated.

Attempted public addresses land in `dbo.visitor_ip`. Administrator
addresses, loopback, and LAN are not logged.

On a developer’s own machine set `HUB_DEV_LOGIN=1` in `hub/.env`: a
loopback caller skips the gate and nothing is written to `visitor_ip`.
Never set that flag on the server.

Schema: `hub/sql/administrator.sql` and `hub/sql/visitor_ip.sql`. The
Restrict IP access page edits only the country/center columns.

## Upload

Upload UI: `http://127.0.0.1:8200/upload` (or via Caddy `/upload` on
`https://expenses.apsurt.nl`). Filenames land on `dbo.uploaded_files`;
rows land on `dbo.transaction_*`.

## Run

```powershell
cd C:\Coding\agrolav\hub
uv sync
uv run hub
```

`HUB_DATABASE_URL` is required (`hub/.env`).

## Onefile

```powershell
cd C:\Coding\agrolav\hub
uv sync --group build
uv run python scripts/build_onefile.py
```

## Add person

Open `http://127.0.0.1:8200/add-person?center=<center>` (or from the client
**Add person** button).
