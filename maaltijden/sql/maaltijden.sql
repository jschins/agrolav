-- Packed meal marks. You create and fill these; the app does not CREATE them.
-- maaltijden_data.id is the day of a 365-day year (1 = 1 januari, 365 = 31 december).
-- maaltijden_users.id is 1..N with no gaps. Each user occupies 5 bits in code
-- (user 1 = bits 0–4, user 2 = bits 5–9, …). N must be ≤ 12 so 5N fits in BIGINT.
-- passphrase NULL = no password; otherwise the login password is this value (plain text).
USE agrolav
GO

IF OBJECT_ID(N'dbo.maaltijden_users', N'U') IS NULL
CREATE TABLE dbo.maaltijden_users (
    id INT PRIMARY KEY,
    user_login VARCHAR(32) NOT NULL,
    passphrase VARCHAR(32) NULL
)
GO

IF OBJECT_ID(N'dbo.maaltijden_data', N'U') IS NULL
CREATE TABLE dbo.maaltijden_data (
    id INT PRIMARY KEY,
    code BIGINT NOT NULL
)
GO

IF NOT EXISTS (SELECT 1 FROM dbo.maaltijden_data)
INSERT INTO dbo.maaltijden_data (id, code)
SELECT
    n,
    0
FROM (
    SELECT TOP (365)
        ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS n
    FROM sys.all_objects
) AS x
GO

IF COL_LENGTH(N'dbo.maaltijden_users', N'passphrase') IS NULL
    ALTER TABLE dbo.maaltijden_users ADD passphrase VARCHAR(64) NULL
GO
