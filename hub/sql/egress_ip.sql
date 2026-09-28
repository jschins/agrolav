-- Shared login allowlist on dbo.administrator.egress_ip.
-- Idempotent. Run on local and remote so they stay identical.
--
-- SSMS: connect to database agrolav, then execute this file.
--
-- The hub no longer reads a separate IP table. Each administrator row's
-- egress_ip column is a comma-separated list, 256 characters long. At login
-- that list is united with the username's own egress_ip column
-- (dbo.country, dbo.center, or dbo.person). The gate runs only when
-- HUB_LOGIN_GATING=1. Value 0 skips the gate.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.administrator', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.administrator', N'egress_ip') IS NULL
    ALTER TABLE dbo.administrator ADD egress_ip VARCHAR(256) NULL;
GO

IF OBJECT_ID(N'dbo.administrator', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.administrator', N'egress_ip') IS NOT NULL
   AND COL_LENGTH(N'dbo.administrator', N'egress_ip') < 256
BEGIN
    DECLARE @nullable bit;
    SELECT @nullable = c.is_nullable
    FROM sys.columns c
    WHERE c.object_id = OBJECT_ID(N'dbo.administrator')
      AND c.name = N'egress_ip';
    IF @nullable = 1
        ALTER TABLE dbo.administrator ALTER COLUMN egress_ip VARCHAR(256) NULL;
    ELSE
        ALTER TABLE dbo.administrator ALTER COLUMN egress_ip VARCHAR(256) NOT NULL;
END
GO

SELECT egress_ip FROM dbo.administrator ORDER BY egress_ip;
GO
