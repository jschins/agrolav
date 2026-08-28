-- Move Enable Banking identity onto dbo.account and PEM onto
-- dbo.enable_connection. Drops dbo.enable_account and dbo.private_key.
-- Does not DROP DATABASE. Does not touch bookings.
--
--   cd hub
--   uv run python scripts/migrate_enable_onto_account.py
--
-- Idempotent. Stop the hub first.

USE agrolav
GO

SET ANSI_NULLS ON
SET QUOTED_IDENTIFIER ON
GO

IF COL_LENGTH(N'dbo.account', N'connection_id') IS NULL
    ALTER TABLE dbo.account ADD connection_id INT NULL
GO

IF COL_LENGTH(N'dbo.account', N'uid') IS NULL
    ALTER TABLE dbo.account ADD uid NVARCHAR(128) NULL
GO

IF COL_LENGTH(N'dbo.account', N'identification_hash') IS NULL
    ALTER TABLE dbo.account ADD identification_hash NVARCHAR(128) NULL
GO

IF COL_LENGTH(N'dbo.enable_connection', N'pem') IS NULL
    ALTER TABLE dbo.enable_connection ADD pem NVARCHAR(MAX) NULL
GO

IF OBJECT_ID(N'dbo.private_key', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.enable_connection', N'pem') IS NOT NULL
   AND COL_LENGTH(N'dbo.enable_connection', N'person_id') IS NOT NULL
    UPDATE ec
    SET pem = pk.pem,
        app_id = COALESCE(NULLIF(LTRIM(RTRIM(ec.app_id)), N''), pk.app_id)
    FROM dbo.enable_connection ec
    INNER JOIN dbo.private_key pk ON pk.person_id = ec.person_id
    WHERE ec.pem IS NULL
GO

IF OBJECT_ID(N'dbo.enable_account', N'U') IS NOT NULL
    UPDATE a
    SET
        connection_id = ea.connection_id,
        uid = ea.uid,
        identification_hash = ea.identification_hash,
        format = COALESCE(NULLIF(LTRIM(RTRIM(ec.aspsp)), N''), a.format)
    FROM dbo.account a
    INNER JOIN dbo.enable_account ea ON ea.account_id = a.account_id
    INNER JOIN dbo.enable_connection ec ON ec.connection_id = ea.connection_id
GO

IF OBJECT_ID(N'dbo.enable_account', N'U') IS NOT NULL
    DROP TABLE dbo.enable_account
GO

IF OBJECT_ID(N'dbo.private_key', N'U') IS NOT NULL
    DROP TABLE dbo.private_key
GO

IF OBJECT_ID(N'dbo.v_account_connection_person', N'V') IS NOT NULL
    DROP VIEW dbo.v_account_connection_person
GO

IF OBJECT_ID(N'fk_account_connection', N'F') IS NOT NULL
    ALTER TABLE dbo.account DROP CONSTRAINT fk_account_connection
GO

IF EXISTS (
    SELECT 1 FROM sys.key_constraints
    WHERE name = N'ux_enable_connection'
      AND parent_object_id = OBJECT_ID(N'dbo.enable_connection')
)
    ALTER TABLE dbo.enable_connection DROP CONSTRAINT ux_enable_connection
GO

IF OBJECT_ID(N'fk_enable_connection_person', N'F') IS NOT NULL
    ALTER TABLE dbo.enable_connection DROP CONSTRAINT fk_enable_connection_person
GO

IF COL_LENGTH(N'dbo.enable_connection', N'person_id') IS NOT NULL
    ALTER TABLE dbo.enable_connection DROP COLUMN person_id
GO

IF COL_LENGTH(N'dbo.enable_connection', N'country_iso') IS NOT NULL
    ALTER TABLE dbo.enable_connection DROP COLUMN country_iso
GO

IF COL_LENGTH(N'dbo.enable_connection', N'aspsp') IS NOT NULL
    ALTER TABLE dbo.enable_connection DROP COLUMN aspsp
GO

IF OBJECT_ID(N'fk_account_connection', N'F') IS NULL
    ALTER TABLE dbo.account WITH CHECK ADD CONSTRAINT fk_account_connection
        FOREIGN KEY (connection_id) REFERENCES dbo.enable_connection (connection_id)
GO

IF OBJECT_ID(N'ck_account_connection_uid', N'C') IS NULL
    ALTER TABLE dbo.account WITH CHECK ADD CONSTRAINT ck_account_connection_uid CHECK (
        (connection_id IS NULL AND uid IS NULL)
        OR (connection_id IS NOT NULL AND uid IS NOT NULL)
    )
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_account_uid' AND object_id = OBJECT_ID(N'dbo.account')
)
    CREATE UNIQUE INDEX ux_account_uid
        ON dbo.account (uid)
        WHERE uid IS NOT NULL
GO

CREATE VIEW dbo.v_account_connection_person
WITH SCHEMABINDING
AS
SELECT connection_id, person_id, COUNT_BIG(*) AS account_count
FROM dbo.account
WHERE connection_id IS NOT NULL
GROUP BY connection_id, person_id
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_v_connection_one_person'
      AND object_id = OBJECT_ID(N'dbo.v_account_connection_person')
)
    CREATE UNIQUE CLUSTERED INDEX ux_v_connection_one_person
        ON dbo.v_account_connection_person (connection_id)
GO
