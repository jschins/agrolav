# SQL Server data volume — migration runbook

The production SQL Server (`MSSQL2022` on `expenses.apsurt.nl`) was created
**without** a volume for its data directory. The live `agrolav` database files
live only inside the container's writable layer. A `docker compose down` +
`up` (container recreation) therefore gives you an **empty SQL Server** with no
`agrolav` database.

The backup mount (`/opt/sql_backups:/var/opt/mssql/backup`) only persists
`.bak` files — it does **not** protect the live data.

This document migrates the live data onto a **named volume** so the database
survives future container recreations. The migration is done with the
established backup + restore workflow ([`deployment.md`](deployment.md)
§8b/§8), nothing is copied as raw `.mdf`/`.ldf` files.

---

## Why a named volume

- Docker `stop`/`start` keeps the same container → data stays.
- `docker compose down` + `up` **removes the container** and throws away its
  writable layer → data is gone unless it lives on a volume.
- A *named volume* is a Docker-managed folder that survives container removal.
  Mount it at the container's data path so SQL Server writes the databases
  there:
  ```yaml
  volumes:
    - mssql-data:/var/opt/mssql
  ```

The target state: `MSSQL2022` runs with `mssql-data:/var/opt/mssql` (live data)
**and** `/opt/sql_backups:/var/opt/mssql/backup` (backups) mounted.

---

## Phase 0 — Safety-net backup (no downtime)

Create a fresh `.bak` on the current container **before touching anything**:

```sql
BACKUP DATABASE [agrolav]
TO DISK = N'/var/opt/mssql/backup/agrolav.bak'
WITH INIT, COMPRESSION;
```

Run it from SSMS (never a `-P 'password'` on a shell command line). Verify it
exists and is non-trivial:

```bash
sudo ls -lh /opt/sql_backups/agrolav.bak
```

Claim ownership:
```bash
sudo chown agrolav:agrolav /opt/sql_backups/agrolav20260909_1039.bak
```

Pull a copy to Windows for good measure:

```powershell
scp -P 4523 agrolav@209.38.39.105:/opt/sql_backups/agrolav.bak C:/SQLBackups/remote_backups/agrolav.bak
```

**Keep this `.bak` until Phase 4 is verified.** It is the rollback path.

---

## Phase 1 — Server-side project env + compose file

All files here live on the server only (`/root/sqlserver/`, root-owned); they
are **not** in the git repo.

### 1a. `/root/sqlserver/.env`

One line, readable only by root. Keeps the password out of the compose file
(and out of `git diff`/`cat /root/sqlserver/docker-compose.yml`):

```
MSSQL_SA_PASSWORD=<current sa password>
```

Keep the **current** password for the migration — a fresh container reads this
at first init, and hub/balance only connect after Phase 3 with the credentials
from `/opt/agrolav/.env` ([`passwords.md`](passwords.md)). Rotating is a
separate follow-up (see Phase 6).

### 1b. `/root/sqlserver/docker-compose.yml`

Overwrite the file with:

```yaml
services:
  sqlserver:
    image: mcr.microsoft.com/mssql/server:2022-latest
    container_name: MSSQL2022
    restart: unless-stopped
    environment:
      ACCEPT_EULA: "Y"
      MSSQL_SA_PASSWORD: ${MSSQL_SA_PASSWORD:?set it in /root/sqlserver/.env}
    volumes:
      - mssql-data:/var/opt/mssql
      - /opt/sql_backups:/var/opt/mssql/backup
    ports:
      - "1433:1433"

volumes:
  mssql-data:
```

Notes:

- `restart: unless-stopped` — auto-starts the container on boot/crash, but
  respects an explicit `docker stop`.
- Compose interpolates `${MSSQL_SA_PASSWORD}` from an env file you choose.
  **Always pass `--env-file /root/sqlserver/.env` on every `docker compose`
  command.** Without it, Compose reads `.env` in the *current working
  directory* — running from `/opt/agrolav` would silently seed the container
  with the app env's SA password instead of this file's, which cost an
  afternoon of "Login failed" debugging. See the migration history in
  `notes.md` or git log for how this bit us.
- Do **not** use `docker compose down -v` anywhere — `-v` deletes the
  `mssql-data` volume, i.e. the database. It was wiped deliberately once,
  during migration, *before* `agrolav` was restored into it. Never again.

---

## Phase 2 — Downtime: swap the container

This is the only downtime window. Stop the apps that hold the DB open, remove
the old container (its writable layer is expendable now — the Phase 0 `.bak`
exists), and start a fresh container on the new volume.

```bash
sudo systemctl stop agrolav-hub agrolav-balance agrolav-client
```

```bash
sudo docker compose -f /root/sqlserver/docker-compose.yml --env-file /root/sqlserver/.env down
sudo docker compose -f /root/sqlserver/docker-compose.yml --env-file /root/sqlserver/.env up -d
```

The container is recreated exactly once here. Wait for SQL Server to finish
first-time initialization (signal: Docker copied the fresh empty volume, SQL
seeds the system databases). Watch the log until you see the canonical line:

```bash
sudo docker logs --tail 50 MSSQL2022
# ... "Recovery is complete. This is an informational message only."
```

Or loop `sqlcmd` until it answers (reads the password from the server `.env` so
it never appears in history; `!` avoids history-expansion in interactive bash):

```bash
set +H
PW=$(sudo grep '^MSSQL_SA_PASSWORD=' /root/sqlserver/.env | cut -d= -f2-)
for i in $(seq 1 120); do
  sudo docker exec MSSQL2022 /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$PW" -C -Q "SELECT 1" >/dev/null 2>&1 \
    && { echo "SQL ready after ~$((i*5))s"; break; }
  sleep 5
done
```

Connect check from Windows (optional now, SQL listens on `0.0.0.0:1433`):

```powershell
Test-NetConnection 209.38.39.105 -Port 1433
```

---

## Phase 3 — Restore `agrolav` into the new container

The `.bak` is on the new container's backup mount already
(`/opt/sql_backups` → `/var/opt/mssql/backup`). The container runs as uid
`10001` (`mssql`), so a backup that was `chown`ed to `agrolav` for `scp` must
be readable by that uid first — SQL Server otherwise fails with *Operating
system error 5 (Access is denied)*:

```bash
sudo chown 10001:10001 /opt/sql_backups/<your-backup>.bak
```

Confirm logical names, then restore. On a fresh instance no `SINGLE_USER`
dance is needed:

```sql
USE master;
RESTORE FILELISTONLY FROM DISK = N'/var/opt/mssql/backup/agrolav.bak';
```

```sql
USE master;
RESTORE DATABASE [agrolav]
FROM DISK = N'/var/opt/mssql/backup/agrolav.bak'
WITH REPLACE, RECOVERY;
```

Default restore paths land in `/var/opt/mssql/data`, which sits on the
`mssql-data` volume. If `FILELISTONLY` shows different logical names, restore
only the data/log rows with `MOVE` to `/var/opt/mssql/data/...`.

Verify the app's tables exist ([`deployment.md`](deployment.md) §8a):

```sql
USE agrolav;
SELECT name FROM sys.tables
WHERE name IN (
  'account','administrator','bank','bank_modality','category_term',
  'category_total','center','consent_pending','country','dim_category',
  'enable_connection','enable_redirect','person','table_header_term',
  'type_abbreviation','type_rule','transaction_nederland','transaction_uk',
  'uploaded_files','visitor_ip'
)
ORDER BY name;
```

Then run the idempotent scripts and re-add the production router WAN addresses
into `dbo.administrator` before country/center logins work (`deployment.md`
§8a, `DATABASE.md`).

Bring the apps back:

```bash
sudo systemctl start agrolav-hub agrolav-balance agrolav-client
sudo systemctl status agrolav-hub agrolav-balance agrolav-client
```

Smoke-test the client at `https://expenses.apsurt.nl` (hub 8200, client 8300,
balance 8100).

---

## Phase 4 — Verify the data really lives on the volume

```bash
sudo docker inspect MSSQL2022 --format '{{json .Mounts}}'
sudo docker volume ls | grep mssql
```

Expect a mount with `"Destination":"/var/opt/mssql"` backed by the
`mssql-data` volume. The old state (single bind mount to `/var/opt/mssql/backup`)
must be gone.

Prove survival across a recreation when convenient (with hub/balance stopped or
accepting a momentary gap):

```bash
sudo docker compose -f /root/sqlserver/docker-compose.yml restart
```

…then reconnect SSMS and confirm `agrolav` is still there. This passes because
`docker compose down`/`restart` never touches `mssql-data`.

Only after Phase 4 do you no longer need to keep the Phase 0 `.bak` on hand.

---

## Phase 5 — Rollback

If Phase 3 fails or the app smoke test is broken:

1. Restore the **old** compose file (no `mssql-data:` volume, backup mount only).
2. `sudo docker compose -f /root/sqlserver/docker-compose.yml down` + `up -d`.
3. Start the apps again, then restore the same `.bak` with the Phase 3 restore
   commands (that `.bak` is portable — it is a plain `.bak` made from the old
   container).

You lose nothing: the `.bak` is the source of truth in both directions.

---

## Phase 6 — Follow-ups (recommended, not part of this migration)

- **`sa` was rotated during the first migration** to the value now in
  `/root/sqlserver/.env` (and mirrored into `/opt/agrolav/.env`). The old
  long-token value is retired. Whenever the password is changed again:
  `ALTER LOGIN [sa]`, then update **both** env files — `/root/sqlserver/.env`
  (`MSSQL_SA_PASSWORD=`) and `/opt/agrolav/.env` (the `MSSQL_SA_PASSWORD=`
  line **and** the `PWD=` field inside `HUB_DATABASE_URL=`) — then restart
  the apps (`passwords.md` §`sa`).
- `restart: unless-stopped` is applied; confirm on next host reboot that
  `MSSQL2022` comes back on its own.
- **Memory: this host has 1.9 GiB and originally had no swap**, which is why
  the old `SQLServer2022` container died with `137` (host OOM-kill). Two
  mitigations are in place:
  - 2 GiB swap file: `fallocate -l 2G /swapfile && chmod 600 /swapfile &&
    mkswap /swapfile && swapon /swapfile`, persisted via
    `/swapfile none swap sw 0 0` in `/etc/fstab`. This prevents host OOM-kills.
  - SQL Server buffer pool capped (`max server memory` = 1024 MB) so the three
    Python services keep theirs:
    ```sql
    EXEC sp_configure 'show advanced options', 1; RECONFIGURE;
    EXEC sp_configure 'max server memory', 1024; RECONFIGURE;
    ```
  Watch `free -h` over time; if swap use stays high or the site feels slow,
  the long-term fix is raising the Droplet to 4 GB (SQL's comfort zone is
  2 GB+ by itself).
- The repo's `docker-compose.sqlserver.yml` (git) is a **different, local-only**
  file (container `agrolav-sql`, `C:/SQLBackups` bind). The server's
  `/root/sqlserver/docker-compose.yml` is authoritative for production; keep
  the two in sync deliberately if you ever touch either.

---

## Reference

| thing | location |
|---|---|
| deployed compose | `/root/sqlserver/docker-compose.yml` (server, root) |
| project env | `/root/sqlserver/.env` (server, root) |
| data volume | `sqlserver_mssql-data` (named volume) → `/var/opt/mssql` |
| backup mount | `/opt/sql_backups` → `/var/opt/mssql/backup` |
| SSMS endpoint | `209.38.39.105,1433`, login `sa`, DB `agrolav` |
| restore sources | [`deployment.md`](deployment.md) §8 / §8a / §8b |
| password policies | [`passwords.md`](passwords.md) |