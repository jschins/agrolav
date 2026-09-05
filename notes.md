  ============================


  Fix properly from the process (which is authoritative), normalizing both files to the hub's actual 65-char key:
  
```
HKEY=$(sudo tr '\0' '\n' < /proc/$(sudo systemctl show agrolav-hub -p MainPID --value)/environ | sed -n 's/^CENTRALE_API_KEY=//p')
export HKEY
sudo -E python3 - <<'EOF'
import os
k = os.environ["HKEY"] + "\n"
for p in ("/etc/agrolav/hub.env", "/etc/agrolav/client.env"):
    keep = [l for l in open(p) if not l.startswith("CENTRALE_API_KEY=")]
    keep.append("CENTRALE_API_KEY=" + k)
    open(p, "w").writelines(keep)
EOF
sudo systemctl restart agrolav-hub agrolav-client
HKEY=$(sudo tr '\0' '\n' < /proc/$(sudo systemctl show agrolav-hub -p MainPID --value)/environ | sed -n 's/^CENTRALE_API_KEY=//p')
CKEY=$(sudo tr '\0' '\n' < /proc/$(sudo systemctl show agrolav-client -p MainPID --value)/environ | sed -n 's/^CENTRALE_API_KEY=//p')
echo "hub len=${#HKEY} sha=$(printf %s "$HKEY" | sha256sum | cut -c1-16)"
echo "cli len=${#CKEY} sha=$(printf %s "$CKEY" | sha256sum | cut -c1-16)"
[ "$HKEY" = "$CKEY" ] && echo MATCH || echo MISMATCH
curl -s -X POST http://127.0.0.1:8300/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"beheer","password":"STRING_beheer"}' | head -c 200
```

This removes every old CENTRALE_API_KEY= line from both files, writes the one true key, and restarts both — expect MATCH and a login JSON.

========================

172.24.48.1 is a private IP (RFC 1918 range), and it's the gateway address on your current LAN — not your public egress IP. The hub behind Caddy sees your public/NAT IP, not this private one.
See public egress IP following the output in

sudo journalctl -u agrolav-hub -f

=========================copy code

agrolav@agrolav:/opt/agrolav/client$ git fetch origin
agrolav@agrolav:/opt/agrolav$ git reset --hard origin/sqlserver
agrolav@agrolav:/opt/agrolav$ git clean -fd
agrolav@agrolav:/opt/agrolav$ cd shared
agrolav@agrolav:/opt/agrolav/shared$ uv sync
agrolav@agrolav:/opt/agrolav/shared$ cd ..
agrolav@agrolav:/opt/agrolav$ cd hub
agrolav@agrolav:/opt/agrolav/hub$ uv sync
agrolav@agrolav:/opt/agrolav/hub$ cd ..
agrolav@agrolav:/opt/agrolav$ cd client
agrolav@agrolav:/opt/agrolav/client$ uv sync
agrolav@agrolav:/opt/agrolav/client$ cd frontend
agrolav@agrolav:/opt/agrolav/client/frontend$ npm ci
agrolav@agrolav:/opt/agrolav/client/frontend$ npm run build
agrolav@agrolav:/opt/agrolav/client/frontend$ cd ..

agrolav@agrolav:/opt/agrolav/client$ cd ..
agrolav@agrolav:/opt/agrolav$ cd balance
agrolav@agrolav:/opt/agrolav/balance$ uv sync
agrolav@agrolav:/opt/agrolav/balance$ cd frontend
agrolav@agrolav:/opt/agrolav/balance/frontend$ npm ci
agrolav@agrolav:/opt/agrolav/balance/frontend$ npm run build
agrolav@agrolav:/opt/agrolav/balance/frontend$ cd ..

agrolav@agrolav:/opt/agrolav$ sudo systemctl reload caddy
agrolav@agrolav:/opt/agrolav$ sudo systemctl restart agrolav-hub
agrolav@agrolav:/opt/agrolav$ sudo systemctl restart agrolav-client
agrolav@agrolav:/opt/agrolav$ sudo systemctl restart agrolav-balance

edit: sudo nano (CTRL-O, enter, CTRL-X)
print: sudo cat

=====================environment variables on the remote

agrolav@agrolav:/opt/agrolav$ sudo cat /etc/agrolav/hub.env
HOST=127.0.0.1
PORT=8200
HUB_DATABASE_URL=DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=Agrolav_Hub_2026!;Encrypt=yes;TrustServerCertificate=yes
CENTRALE_API_KEY=b57ac888a83441516fe4e608c65ea8cdcbacab80ee4b43710dc417bcc421a2f4
ENABLEBANKING_REDIRECT_URL=https://expenses.apsurt.nl/api/consent/callback
HUB_CLIENT_URL=https://expenses.apsurt.nl
agrolav@agrolav:/opt/agrolav$ sudo cat /etc/agrolav/client.env
HOST=127.0.0.1
PORT=8300
SERVER_URL=http://127.0.0.1:8200
CLIENT_AUTH=1
CLIENT_SESSION_SECRET=SOME_OTHER_LONG_RANDOM_SECRET
CLIENT_COUNTRY=nederland
CENTRALE_API_KEY=b57ac888a83441516fe4e608c65ea8cdcbacab80ee4b43710dc417bcc421a2f4
PUBLIC_HUB_URL=https://expenses.apsurt.nl
agrolav@agrolav:/opt/agrolav$ sudo cat /etc/agrolav/balance.env
HOST=127.0.0.1
PORT=8100
HUB_DATABASE_URL=DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=Agrolav_Hub_2026!;Encrypt=yes;TrustServerCertificate=yes
agrolav@agrolav:/opt/agrolav$


==================copy database

1. in SSMS, right-click agrolav, click "tasks > backup" and save to disk via docker-mapping
2. see ## SQL #6-8 above:
3. powershell: scp -P 4523 C:/SQLBackups/agrolav20.bak agrolav@209.38.39.105:/tmp/
4. check on server (ssh agrolav@209.38.39.105 -p 4523): ls -lh /tmp/agrolav19.bak (NB server may lags 2 hours in summer, 1 in winter)
5. make folder [sudo docker exec MSSQL2022 mkdir -p /var/opt/mssql/backup] only if there is no folder
6. copy from server to docker
   sudo docker cp \
  /tmp/agrolav20.bak \
  MSSQL2022:/var/opt/mssql/backup/agrolav20.bak
7. Verify:
sudo docker exec SQLServer2022 \
  ls -lh /var/opt/mssql/backup/agrolav19.bak
8. Use SSMS connected to `209.38.39.105,1433` (`sa` login). First determine the logical file names:
```sql
USE MASTER
RESTORE FILELISTONLY
FROM DISK = '/var/opt/mssql/backup/agrolav19.bak';
```
Then restore (logical names `agrolav` / `agrolav_log`):
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
====================================delete test users


DELETE FROM dbo.category_term
WHERE person_id > 15;

DELETE FROM dbo.transaction_beheer
WHERE person_id > 15;

DELETE FROM dbo.transaction_nederland
WHERE person_id > 15;

DELETE FROM dbo.account
WHERE person_id > 15;

DELETE FROM dbo.enable_connection
WHERE person_id > 15;

DELETE FROM dbo.person
WHERE id > 15;

=========================================

ALTER TABLE dbo.person
DROP COLUMN updated_at;

ALTER TABLE dbo.person ADD password_hash NVARCHAR(256) NULL;
ALTER TABLE dbo.person ADD mobile_phone NVARCHAR(32) NULL;


GO

IF COL_LENGTH(N'dbo.country', N'egress_ip') IS NULL
    ALTER TABLE dbo.country ADD egress_ip VARCHAR(256) NULL;
GO

IF COL_LENGTH(N'dbo.center', N'egress_ip') IS NULL
    ALTER TABLE dbo.center ADD egress_ip VARCHAR(256) NULL;
GO

IF OBJECT_ID(N'dbo.visitor_ip', N'U') IS NULL
CREATE TABLE dbo.visitor_ip (
    visitor_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    egress_ip VARCHAR(32) NOT NULL,
    username VARCHAR(64) NULL,
    CONSTRAINT ux_visitor_ip_egress_user UNIQUE (egress_ip, username)
);
GO

IF OBJECT_ID(N'dbo.visitor_ip', N'U') IS NOT NULL
   AND NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'ux_visitor_ip_anon'
          AND object_id = OBJECT_ID(N'dbo.visitor_ip')
   )
    CREATE UNIQUE INDEX ux_visitor_ip_anon
        ON dbo.visitor_ip (egress_ip)
        WHERE username IS NULL;
GO


================simulate first-time login

DELETE FROM dbo.transaction_beheer
WHERE person_id < 10000;

UPDATE dbo.enable_connection
SET session_id = NULL, valid_until = NULL, created_at = NULL
WHERE person_id = (SELECT id FROM dbo.person WHERE username = 'sdog');

====================herlaad rafa

delete from dbo.account_balance_file where account_id = 5;
delete from dbo.transaction_nederland where account_id = 5;
UPDATE dbo.account 
SET format = NULL, balance = 0.0, last_booked = NULL WHERE person_id = 5;

============================insert categories

INSERT INTO dbo.dim_category
VALUES 
(1000,4,1000,'Gebouwen','False', NULL),
(1005,4,1005,'Verbouwingen','False', NULL),
(1010,4,1010,'Inventaris','False', NULL),
(1015,4,1015,'Autos','False', NULL),
(1051,4,1051,'Bank algemeen','False', NULL),
(1052,4,1052,'Spaarrekening','False', NULL),
(1053,4,1053,'Bank huishoudelijke dienst','False', NULL),
(1054,4,1054,'Bank FPU','False', NULL),
(1055,4,1055,'Bank FOH','False', NULL),
(1056,4,1056,'Bank residentie ddkg','False', NULL),
(1110,4,1110,'Kruisposten','False', NULL),
(1111,4,1111,'r/c K218','False', NULL),
(2000,4,2000,'Eigen vermogen','False', NULL),
(2050,4,2050,'Reserve Vergeer','False', NULL),
(2055,4,2055,'Reserve FF-OG','False', NULL),
(2500,4,2500,'Schulden particulieren','False', NULL)


UPDATE dbo.transaction_beheer SET category_id = 1000 WHERE category_id = 3300;
UPDATE dbo.category_term SET category_id = 1000 WHERE category_id = 3300;
DELETE FROM dbo.dim_category WHERE category_id = 3300;
UPDATE dbo.transaction_beheer SET category_id = 1000 WHERE category_id = 3350;
UPDATE dbo.category_term SET category_id = 1000 WHERE category_id = 3350;
DELETE FROM dbo.dim_category WHERE category_id = 3350;

