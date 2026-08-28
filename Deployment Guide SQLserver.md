# Deployment Guide — Agrolav Production

This document describes how to deploy the Agrolav application to the production server at `expenses.apsurt.nl`, including Git updates, Python/Node dependencies, frontend builds, SQL Server configuration, database restoration, and systemd services.

---

## 1. Log in to the production server

```bash
ssh agrolav@209.38.39.105 -p 4523
```
use !ziQkpk3epcgpi70i4HvzeFa7hGukCbYi


Application directory:

```bash
cd /opt/agrolav
```

---

## 2. Update the application from Git

Check the current state:

```bash
git status
git branch -vv
```

If the server should exactly match the remote `sqlserver` branch and there are no server-side changes that need to be preserved:

```bash
git fetch origin
git reset --hard origin/sqlserver
git clean -fd
```

**Warning:** `git clean -fd` deletes untracked files and directories. Do not use it if the server contains files that are intentionally kept outside Git.

Check:

```bash
git status
```

Expected:

```text
On branch sqlserver
Your branch is up to date with 'origin/sqlserver'.

nothing to commit, working tree clean
```

---

## 3. Install/update Python dependencies

The project uses `uv`.

Run:

```bash
cd /opt/agrolav

cd shared
uv sync

cd ../hub
uv sync

cd ../client
uv sync
```

---

## 4. Build the frontend

Install the exact dependencies from `package-lock.json`:

```bash
cd /opt/agrolav/client/frontend
npm ci
```

Build the production frontend:

```bash
npm run build
```

Verify the build contains the expected recent changes:

```bash
grep -Ril "edit categories" \
  /opt/agrolav/client/frontend \
  --exclude-dir=node_modules
```

The expected result should include:

```text
/opt/agrolav/client/frontend/src/App.tsx
/opt/agrolav/client/frontend/dist/assets/index-....js
```

---

# SQL Server

## 5. Check the SQL Server container

SQL Server runs in Docker.

```bash
sudo docker ps
```

Expected:

```text
SQLServer2022
```

If necessary:

```bash
sudo docker ps -a
```

The container exposes SQL Server on port 1433:

```text
0.0.0.0:1433->1433/tcp
```

---

## 6. Copy a `.bak` database backup to the server

From a Windows machine, do **not** use a Windows path after logging into the Linux server.

For example, from Windows:

```powershell
scp -P 4523 C:/SQLBackups/agrolav19.bak agrolav@209.38.39.105:/tmp/
```

Then on the server:

```bash
ls -lh /tmp/agrolav19.bak
```

---

## 7. Copy the backup into the SQL Server container

Create a backup directory:

```bash
sudo docker exec SQLServer2022 mkdir -p /var/opt/mssql/backup
```

Copy the backup:

```bash
sudo docker cp \
  /tmp/agrolav19.bak \
  SQLServer2022:/var/opt/mssql/backup/agrolav19.bak
```

Verify:

```bash
sudo docker exec SQLServer2022 \
  ls -lh /var/opt/mssql/backup/agrolav19.bak
```

---

## 8. Restore the SQL Server database

The backup can be restored using SSMS.

First determine the logical file names:

```sql
USE MASTER
RESTORE FILELISTONLY
FROM DISK = '/var/opt/mssql/backup/agrolav19.bak';
```

For example, if the logical names are:

```text
agrolav
agrolav_log
```

restore with:

```sql
USE master;

ALTER DATABASE [agrolav]
SET SINGLE_USER
WITH ROLLBACK IMMEDIATE;

RESTORE DATABASE [agrolav]
FROM DISK = '/var/opt/mssql/backup/agrolav19.bak'
WITH
    REPLACE,
    RECOVERY;

ALTER DATABASE [agrolav]
SET MULTI_USER;
```

Verify the database:

```sql
USE agrolav;
SELECT name
FROM sys.databases
WHERE name = 'agrolav';
```

Verify the relevant tables:

```sql
USE agrolav;
SELECT *
FROM dbo.country;
```

Other important tables include:

```sql
SELECT *
FROM dbo.person;

SELECT *
FROM dbo.center;
```

---

# SQL Server connection from the Agrolav hub

## 9. Important: production originally used SQLite

The application supports two modes.

If `HUB_DATABASE_URL` is absent, the hub uses SQLite:

```text
/opt/agrolav/workspaces/users.db
```

If `HUB_DATABASE_URL` is present, it uses SQL Server.

This distinction is important when troubleshooting old production data.

The production environment originally contained:

```text
HOST=127.0.0.1
PORT=8200
BOEKHOUDING_DATA_ROOT=/opt/agrolav/workspaces
```

with no `HUB_DATABASE_URL`.

Therefore the application was reading the old SQLite database rather than the SQL Server database.

---

## 10. Configure the SQL Server connection

Edit:

```bash
sudo nano /etc/agrolav/hub.env
```

The file should contain:

```text
HOST=127.0.0.1
PORT=8200
BOEKHOUDING_DATA_ROOT=/opt/agrolav/workspaces
HUB_DATABASE_URL=DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=YOUR_ACTUAL_PASSWORD;Encrypt=yes;TrustServerCertificate=yes
```

Replace:

```text
YOUR_ACTUAL_PASSWORD
```

with the actual SQL Server `sa` password.

Do not commit this file to Git.

### Saving in nano

After editing:

```text
Ctrl+O
Enter
Ctrl+X
```

`Ctrl+O` saves the file.

`Ctrl+X` exits nano.

Verify the connection string without displaying the password:

```bash
sudo grep '^HUB_DATABASE_URL=' /etc/agrolav/hub.env \
  | sed 's/PWD=[^;]*/PWD=***REDACTED***/'
```

---

# ODBC

## 11. Install the ODBC runtime

The first SQL Server attempt failed with:

```text
ImportError: libodbc.so.2: cannot open shared object file
```

Install unixODBC:

```bash
sudo apt update
sudo apt install -y unixodbc
```

---

## 12. Install Microsoft ODBC Driver 18

The production server runs Ubuntu 24.04 (Noble).

Check:

```bash
lsb_release -a
```

Expected:

```text
Ubuntu 24.04
noble
```

Add the Microsoft repository:

```bash
curl -sSL -O \
  https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb
```

Install it:

```bash
sudo dpkg -i packages-microsoft-prod.deb
```

Remove the temporary package:

```bash
rm packages-microsoft-prod.deb
```

Update package lists:

```bash
sudo apt update
```

Install ODBC Driver 18:

```bash
sudo ACCEPT_EULA=Y apt install -y msodbcsql18
```

Verify:

```bash
odbcinst -q -d
```

Expected:

```text
[ODBC Driver 18 for SQL Server]
```

Check the unixODBC configuration:

```bash
odbcinst -j
```

The driver configuration is normally:

```text
/etc/odbcinst.ini
```

---

# Systemd services

## 13. Hub service

Check the service:

```bash
sudo systemctl cat agrolav-hub
```

The important parts are:

```ini
[Service]
User=agrolav
WorkingDirectory=/opt/agrolav/hub
EnvironmentFile=/etc/agrolav/hub.env
ExecStart=/home/agrolav/.local/bin/uv run hub
Restart=always
```

Restart:

```bash
sudo systemctl restart agrolav-hub
```

Check:

```bash
sudo systemctl status agrolav-hub --no-pager
```

Expected:

```text
Active: active (running)
```

Check logs:

```bash
sudo journalctl -u agrolav-hub -n 50 --no-pager
```

The hub should start successfully:

```text
Application startup complete.
Uvicorn running on http://127.0.0.1:8200
```

It should no longer show:

```text
user store ready: /opt/agrolav/workspaces/users.db
```

when SQL Server is configured.

---

## 14. Verify the SQL Server environment is actually loaded

Find the current main PID:

```bash
sudo systemctl show agrolav-hub -p MainPID
```

For example:

```text
MainPID=67267
```

Then:

```bash
sudo tr '\0' '\n' < /proc/67267/environ \
  | grep '^HUB_DATABASE_URL=' \
  | sed 's/PWD=[^;]*/PWD=***REDACTED***/'
```

This verifies that systemd passed `HUB_DATABASE_URL` to the running process.

---

## 15. Client service

Check:

```bash
sudo systemctl cat agrolav-client
```

Expected configuration is similar to:

```ini
[Service]
User=agrolav
WorkingDirectory=/opt/agrolav/client
EnvironmentFile=/etc/agrolav/client.env
ExecStart=/home/agrolav/.local/bin/uv run client
Restart=always
```

Restart:

```bash
sudo systemctl restart agrolav-client
```

Check:

```bash
sudo systemctl status agrolav-client --no-pager
```

---

# Frontend deployment

## 16. Rebuild the frontend after frontend changes

Whenever frontend source changes:

```bash
cd /opt/agrolav/client/frontend
npm ci
npm run build
```

Then restart the client:

```bash
sudo systemctl restart agrolav-client
```

Check what JavaScript the public site is actually serving:

```bash
curl -s https://expenses.apsurt.nl \
  | grep -oE 'src="[^"]+\.js[^"]*"' \
  | head -20
```

For example:

```text
src="/assets/index-DQ8GsFk0.js"
```

You can verify a specific build contains a new string:

```bash
curl -s https://expenses.apsurt.nl/assets/index-DQ8GsFk0.js \
  | grep -oi "edit categories"
```

If the string is present, the public site is serving that build.

---

# Troubleshooting

## 17. Git says the branch is up to date but the server looks old

Check:

```bash
git status
git branch -vv
git log --oneline --decorate -20
```

If the remote has changed:

```bash
git fetch origin
```

Then:

```bash
git log --oneline HEAD..origin/sqlserver
```

If production should exactly match the remote branch:

```bash
git reset --hard origin/sqlserver
```

Be careful: this discards local committed changes.

If there are unwanted untracked files:

```bash
git clean -fd
```

Be especially careful with `git clean -fd`, because it deletes untracked files.

---

## 18. If the application still shows old user/country data

Check whether SQL Server is configured:

```bash
sudo grep '^HUB_DATABASE_URL=' /etc/agrolav/hub.env \
  | sed 's/PWD=[^;]*/PWD=***REDACTED***/'
```

Check the hub logs:

```bash
sudo journalctl -u agrolav-hub -n 50 --no-pager
```

If the log says:

```text
user store ready: /opt/agrolav/workspaces/users.db
```

the hub is using SQLite.

If SQL Server is configured, verify the database directly in SSMS:

```sql
SELECT *
FROM dbo.country;

SELECT *
FROM dbo.center;

SELECT *
FROM dbo.person;
```

---

## 19. If "edit categories" does not appear

The frontend code