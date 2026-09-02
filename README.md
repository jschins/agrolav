# Agrolav

Household bookkeeping: hub `:8200`, client `:8300`, SQL Server database `agrolav`.
Logins are `dbo.country` / `dbo.center` / `dbo.person`. Bookings live in `dbo.transaction_*`.

Start locally with `uv run hub` (from `hub/`) and `uv run client` (from `client/`).

## Local vs server environment

Which URLs and disk paths the processes use is decided by **`dbo.app_config.RUN_ON_SERVER`** (truthy = server) plus a few environment variables. With no row, the hub is local.

### Process and disk paths

| | Local (`uv run`) | Server (frozen exe / production) |
|---|---|---|
| Hub project root | `hub/` (source tree) | Directory of the executable |
| Client project root | `client/` | PyInstaller `_MEIPASS` (bundled files) or the exe directory |
| Hub `data_root()` | `AGROLAV_SQL_DISK` if set, else the process **cwd** | Same rule; production usually sets `AGROLAV_SQL_DISK` |
| SQL backup volume | `AGROLAV_SQL_DISK` (default `C:/SQLBackups`) mounted at `/var/opt/mssql/backup` | Same env on the host that runs Docker SQL |
| Hub `.env` | `hub/.env`, then the repo `.env` | Same lookup; `HUB_DATABASE_URL` is required |

SQL Server is the live store. `data_root()` is only a leftover virtual root (ACL / logs). It is not a country/center/person folder tree.

### Network paths

| | Local | Server |
|---|---|---|
| Hub listen | `HOST` (default `0.0.0.0`) port `8200` | Same defaults unless systemd/env overrides |
| Client listen | `0.0.0.0:8300` (frozen laptop exe without auth: `127.0.0.1`) | `0.0.0.0:8300` behind Caddy |
| Client → hub | `SERVER_URL` or `http://127.0.0.1:8200` | `SERVER_URL` to the hub on localhost; browsers use the public URLs |
| Public hub / client URLs | `PUBLIC_HUB_URL` / `PUBLIC_CLIENT_URL` rows are **ignored**; links stay `http://127.0.0.1:8200` and `:8300` (`HUB_CLIENT_URL` can override the client return URL) | Those `dbo.app_config` rows are used |
| Enable Banking callback | env `ENABLEBANKING_REDIRECT_URL` wins, else `LOCAL_ENABLEBANKING_REDIRECT_URL` | `PRODUCTION_ENABLEBANKING_REDIRECT_URL` wins over env |
| SQL connection | `HUB_DATABASE_URL` in `hub/.env` → `127.0.0.1,1433` | Same variable pointing at the production SQL instance |

On the server, Caddy (`client/Caddyfile`) publishes the client on the public host and only forwards `/api/consent/callback*` and `/upload*` to the hub.
