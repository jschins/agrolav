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

agrolav@agrolav:/opt/agrolav$ sudo systemctl daemon-reload
agrolav@agrolav:/opt/agrolav$ sudo systemctl reload caddy
agrolav@agrolav:/opt/agrolav$ sudo systemctl reload caddy
agrolav@agrolav:/opt/agrolav$ sudo systemctl restart agrolav-hub
agrolav@agrolav:/opt/agrolav$ sudo systemctl restart agrolav-client
agrolav@agrolav:/opt/agrolav$ sudo systemctl restart agrolav-balance

edit: sudo nano (CTRL-O, enter, CTRL-X)
print: sudo cat
rechten: 
agrolav@agrolav:/opt/agrolav$ ls -ld /opt/sql_backups
agrolav@agrolav:/opt/agrolav$ ls -la /opt/sql_backups
agrolav@agrolav:/opt/agrolav$ sudo chown 10001:10001 /opt/sql_backups
agrolav@agrolav:/opt/agrolav$ sudo chown 10001:10001 /opt/sql_backups/*
agrolav@agrolav:/opt/agrolav$ ls -ldn /opt/sql_backups
agrolav@agrolav:/opt/agrolav$ ls -lan /opt/sql_backups



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

==================remote database backup

DECLARE @path NVARCHAR(4000) = N'/var/opt/mssql/backup/agrolav_full_' +
        CONVERT(NVARCHAR(8), GETDATE(), 112) + '_' +
        REPLACE(CONVERT(NVARCHAR(8), GETDATE(), 108), ':', '') + '.bak';

BACKUP DATABASE agrolav
TO DISK = @path
WITH FORMAT, INIT, NAME = N'agrolav-full', COMPRESSION, STATS = 10;

-- Optional verify:
RESTORE VERIFYONLY FROM DISK = @path;

SELECT @path AS backup_path;

then copy the file to local disk (from terminal): 
PS C:\Coding\agrolav> scp -P 4523 agrolav@209.38.39.105:/opt/sql_backups/*.bak "C:\SQLBackups\remote_backups\"




ls -ld /opt/sql_backups
sudo -S docker exec -u 0 MSSQL2022 ls -ld /var/opt/mssql/backup



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






=====================================using pyodc
$ $tool = @'
#!/bin/bash
/opt/agrolav/balance/.venv/bin/python - <<'PY'
import pyodbc
cn = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=Agrolav_Hub_2026!;Encrypt=yes;TrustServerCertificate=yes", timeout=10)
cur = cn.cursor()
cur.execute("ALTER TABLE dbo.transaction_beheer_instudo DROP CONSTRAINT ck_txn_beheer_instudo_cat")
cur.execute("ALTER TABLE dbo.transaction_beheer_instudo ADD CONSTRAINT ck_txn_beheer_instudo_cat CHECK (category_id >= 10000 AND category_id < 20000)")
cn.commit()
cur.execute("""SELECT cc.definition FROM sys.check_constraints cc WHERE cc.name='ck_txn_beheer_instudo_cat'""")
print("new CHECK:", cur.fetchone()[0])
cn.close()
PY
'@
$b = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($tool))
$env:SSH_ASKPASS = "C:\Users\PCUSER~1\AppData\Local\Temp\opencode\askpass.cmd"
$env:SSH_ASKPASS_REQUIRE = "force"
ssh -p 4523 -o ConnectTimeout=15 agrolav@209.38.39.105 "printf '%s' '$b' | base64 -d > /tmp/agro_fix.sh; bash /tmp/agro_fix.sh"
new CHECK: ([category_id]>=(10000) AND [category_id]<(20000))


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

=================WHEN ADDING FIRST PERSON TO NEWLY CREATED COUNTRY with country_id = 5

INSERT INTO dbo.dim_category VALUES
(13997,	5,	3997,	'Overige kosten',	'True',	NULL),
(13998,	5,	3998,	'Balance',	'False',	'balance'),
(13999,	5,	3999,	'Updated',	'False	'last_booked');

ALTER TABLE dbo.transaction_beheer_instudo DROP CONSTRAINT ck_txn_beheer_instudo_cat;
ALTER TABLE dbo.transaction_beheer_instudo ADD CONSTRAINT ck_txn_beheer_instudo_cat CHECK (category_id >= 10000 AND category_id < 20000);

=================MAKE MAPPING AFTER HAVING DEFINED CATEGORIES

INSERT INTO dbo.dim_category VALUES
(11000, 5, 1000, 'Kas', 'False', NULL),
(11001, 5, 1001, 'Kas Administratie', 'False', NULL),
(11010, 5, 1010, 'Bank ING / Rekening Residentie (SIb)', 'False', NULL),
(11012, 5, 1012, 'Spaarrekening / Rekening Administratie (SIb)', 'False', NULL),
(11035, 5, 1035, 'Debiteuren', 'False', NULL),
(11050, 5, 1050, 'Gebouwen', 'False', NULL),
(11060, 5, 1060, 'Verbouwingen', 'False', NULL),
(11070, 5, 1070, 'Inventaris', 'False', NULL),
(11080, 5, 1080, 'Auto''s', 'False', NULL),
(11115, 5, 1115, 'Debiteuren', 'False', NULL),
(11200, 5, 1200, 'Kruisposten', 'False', NULL),
(11205, 5, 1205, 'Tijdelijke posten', 'False', NULL),
(11210, 5, 1210, 'Memoriaal rekening', 'False', NULL),
(11250, 5, 1250, 'Vraagposten', 'False', NULL),
(11100, 5, 1100, 'r/c SIb', 'False', NULL),
(11101, 5, 1101, 'r/c Aenstal', 'False', NULL),
(11102, 5, 1102, 'r/c CGP', 'False', NULL),
(11103, 5, 1103, 'r/c De Borcht', 'False', NULL),
(11104, 5, 1104, 'r/c Den Eker', 'False', NULL),
(11105, 5, 1105, 'r/c Hogeland', 'False', NULL),
(11106, 5, 1106, 'r/c Jan Luijken', 'False', NULL),
(11107, 5, 1107, 'r/c Leidenhoven', 'False', NULL),
(11108, 5, 1108, 'r/c Lepelenburg', 'False', NULL),
(11109, 5, 1109, 'r/c De Stade', 'False', NULL),
(11110, 5, 1110, 'r/c SVOa', 'False', NULL),
(12000, 5, 2000, 'Eigen vermogen', 'False', NULL),
(12050, 5, 2050, 'Reserves', 'False', NULL),
(12100, 5, 2100, 'Voorzieningen', 'False', NULL),
(12200, 5, 2200, 'Resultaat lopend boekjaar', 'False', NULL),
(12300, 5, 2300, 'Schulden banken', 'False', NULL),
(12301, 5, 2301, 'ING 80.00.94.263 (Euribor) STD', 'False', NULL),
(12400, 5, 2400, 'Schulden instellingen', 'False', NULL),
(12500, 5, 2500, 'Schulden particulieren', 'False', NULL),
(12600, 5, 2600, 'Crediteuren', 'False', NULL),
(13001, 5, 3001, 'Lonen', 'False', NULL),
(13002, 5, 3002, 'Afdrachten', 'False', NULL),
(13004, 5, 3004, 'Arbodienst e.d.', 'False', NULL),
(13005, 5, 3005, 'Vergoedingen', 'False', NULL),
(13006, 5, 3006, 'Vergoedingen overige', 'False', NULL),
(13009, 5, 3009, 'Pensioenen', 'False', NULL),
(13010, 5, 3010, 'Onderhoud, verbouwingen', 'False', NULL),
(13012, 5, 3012, 'Kleine inventaris', 'False', NULL),
(13015, 5, 3015, 'Kantoorartikelen en huisvesting', 'False', NULL),
(13020, 5, 3020, 'Belastingen', 'False', NULL),
(13025, 5, 3025, 'Verzekeringen', 'False', NULL),
(13030, 5, 3030, 'Energie, water', 'False', NULL),
(13040, 5, 3040, 'Levensmiddelen', 'False', NULL),
(13041, 5, 3041, 'Schoonmaak en overige administratie', 'False', NULL),
(13045, 5, 3045, 'Telefoon, tv, internet', 'False', NULL),
(13050, 5, 3050, 'Contributies, abonnementen, cultuur', 'False', NULL),
(13060, 5, 3060, 'Kosten activiteiten', 'False', NULL),
(13070, 5, 3070, 'Auto', 'False', NULL),
(13080, 5, 3080, 'Bankkosten en betaalde rente', 'False', NULL),
(13081, 5, 3081, 'Betaalde rente instellingen', 'False', NULL),
(13082, 5, 3082, 'Betaalde rente particulieren', 'False', NULL),
(13090, 5, 3090, 'Beurzen', 'False', NULL),
(13095, 5, 3095, 'Steun aan derden', 'False', NULL),
(13100, 5, 3100, 'Overige kosten', 'True', NULL),
(13105, 5, 3105, 'Afschr gebouwen', 'False', NULL),
(13110, 5, 3110, 'Afschr verbouwingen', 'False', NULL),
(13115, 5, 3115, 'Afschr inventaris', 'False', NULL),
(13120, 5, 3120, 'Afschr auto''s', 'False', NULL),
(13125, 5, 3125, 'Bijdrage SI centrale', 'False', NULL),
(13130, 5, 3130, 'Buitengewone lasten', 'False', NULL),
(14000, 5, 4000, 'Pensions', 'False', NULL),
(14010, 5, 4010, 'Logies, maaltijden', 'False', NULL),
(14015, 5, 4015, 'Bijdragen deelnemers', 'False', NULL),
(14020, 5, 4020, 'Huuropbrengensten', 'False', NULL),
(14050, 5, 4050, 'Subsidies', 'False', NULL),
(14060, 5, 4060, 'Aktes', 'False', NULL),
(14070, 5, 4070, 'Giften', 'False', NULL),
(14085, 5, 4085, 'Overige baten', 'False', NULL)

INSERT INTO dbo.mapping VALUES (5, 11100, 39),(5, 11104, 40),(5, 11106, 41),(5, 11107, 42),(5, 11108, 43);

because
39	24	NL46INGB0001726568	Stichting Instudo
40	24	NL93INGB0003150749	Den Eker
41	24	NL22INGB0004005627	Studiecentrum
42	24	NL63INGB0000776923	Leidenhoven College
43	24	NL61INGB0002843544	Lepelenburg

(11100, 5, 1100, 'r/c SIb', 'False', NULL),
(11104, 5, 1104, 'r/c Den Eker', 'False', NULL),
(11106, 5, 1106, 'r/c Jan Luijken', 'False', NULL),
(11107, 5, 1107, 'r/c Leidenhoven', 'False', NULL),
(11108, 5, 1108, 'r/c Lepelenburg', 'False', NULL),