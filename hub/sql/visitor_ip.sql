-- Country/center login allowlists + visitor log.
-- Idempotent. You run this on local and remote so they stay identical.
--
-- SSMS: connect to database agrolav, then execute this file.
--
-- egress_ip is the "egress-IP" allowlist (comma-separated). Empty/NULL admits
-- nothing: a country/center login needs its address here or in dbo.administrator
-- (see administrator.sql), and the allowed set is the sum of the two.
-- dbo.hub_ip is replaced by dbo.visitor_ip (login attempts). Drop hub_ip yourself
-- after this succeeds, when you are ready.

USE agrolav;
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
