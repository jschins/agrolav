-- Add dbo.hub_ip.target. Existing rows become hub-wide ('B') allowlist.
-- Primary key becomes (ip, target) so one IP can serve several logins.
-- Does not DROP DATABASE.

USE agrolav
GO

IF OBJECT_ID(N'dbo.hub_ip', N'U') IS NULL
CREATE TABLE dbo.hub_ip (
    ip NVARCHAR(64) NOT NULL,
    target NVARCHAR(32) NOT NULL,
    CONSTRAINT pk_hub_ip PRIMARY KEY (ip, target)
)
GO

IF OBJECT_ID(N'dbo.hub_ip', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.hub_ip', N'target') IS NULL
    ALTER TABLE dbo.hub_ip ADD target NVARCHAR(32) NOT NULL
        CONSTRAINT df_hub_ip_target DEFAULT (N'B')
GO

IF OBJECT_ID(N'dbo.hub_ip', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.hub_ip', N'target') IS NOT NULL
    UPDATE dbo.hub_ip
    SET target = N'B'
    WHERE NULLIF(LTRIM(RTRIM(target)), N'') IS NULL
GO

IF OBJECT_ID(N'dbo.hub_ip', N'U') IS NOT NULL
   AND EXISTS (
        SELECT 1 FROM sys.key_constraints
        WHERE name = N'pk_hub_ip'
          AND parent_object_id = OBJECT_ID(N'dbo.hub_ip')
   )
    ALTER TABLE dbo.hub_ip DROP CONSTRAINT pk_hub_ip
GO

IF OBJECT_ID(N'dbo.hub_ip', N'U') IS NOT NULL
   AND NOT EXISTS (
        SELECT 1 FROM sys.key_constraints
        WHERE name = N'pk_hub_ip'
          AND parent_object_id = OBJECT_ID(N'dbo.hub_ip')
   )
    ALTER TABLE dbo.hub_ip ADD CONSTRAINT pk_hub_ip PRIMARY KEY (ip, target)
GO
