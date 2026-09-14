-- Packed meal marks. You create and fill these; the app does not CREATE them.
-- maaltijden_data.id is the day of a 365-day year (1 = 1 januari, 365 = 31 december).
-- Login admin is not a matrix row (no bits in code); it only edits maaltijden_extra.
-- Remaining users occupy 5 bits each in list order. Display O M A L P;
-- bits 0..4 are O, M, A, P, L. Matrix N must be ≤ 12.
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

-- One row per weekday (id 1 = zondag … 7 = zaterdag).
-- ochtend=O, middag=M, avond=A, laat=L, pakket=P.
-- Zeroed when a new Sunday week begins (see dbo.maaltijden_extra_week).
IF OBJECT_ID(N'dbo.maaltijden_extra', N'U') IS NULL
CREATE TABLE dbo.maaltijden_extra (
    id INT IDENTITY(1,1) PRIMARY KEY,
    ochtend INT NOT NULL,
    middag INT NOT NULL,
    avond INT NOT NULL,
    laat INT NOT NULL,
    pakket INT NOT NULL
)
GO

IF NOT EXISTS (SELECT 1 FROM dbo.maaltijden_extra)
INSERT INTO dbo.maaltijden_extra (ochtend, middag, avond, laat, pakket)
VALUES
(0,0,0,0,0),
(0,0,0,0,0),
(0,0,0,0,0),
(0,0,0,0,0),
(0,0,0,0,0),
(0,0,0,0,0),
(0,0,0,0,0)
GO

IF OBJECT_ID(N'dbo.maaltijden_extra_week', N'U') IS NULL
CREATE TABLE dbo.maaltijden_extra_week (
    week_start DATE NOT NULL
)
GO
