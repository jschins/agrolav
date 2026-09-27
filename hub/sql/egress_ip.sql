-- Egress IPs allowed for every country and every center.
-- Idempotent. Run on local and remote so they stay identical.
--
-- SSMS: connect to database agrolav, then execute this file.
-- The former name of this table was dbo.administrator. This script renames
-- that table when it still has the egress_ip column, then creates
-- dbo.egress_ip if it is missing. It leaves a dbo.administrator that already
-- has a username column (the administrator login) untouched.
--
-- A country/center login is allowed when its address is listed here or in its
-- own dbo.country.egress_ip / dbo.center.egress_ip column; the allowed set is
-- the sum of the two. An empty or NULL column admits nothing, so leaving both
-- empty refuses every country and center login. Person logins are not gated.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.egress_ip', N'U') IS NULL
   AND OBJECT_ID(N'dbo.administrator', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.administrator', N'egress_ip') IS NOT NULL
   AND COL_LENGTH(N'dbo.administrator', N'username') IS NULL
    EXEC sp_rename N'dbo.administrator', N'egress_ip';
GO

-- 45 characters holds a compressed IPv6 address (39) with room to spare.
-- No dotted-quad CHECK constraint here on purpose: IPv6 stays usable, and the
-- hub validates every address with Python's ipaddress before querying.
IF OBJECT_ID(N'dbo.egress_ip', N'U') IS NULL
CREATE TABLE dbo.egress_ip (
    egress_ip VARCHAR(45) NOT NULL PRIMARY KEY
);
GO

IF COL_LENGTH(N'dbo.egress_ip', N'egress_ip') < 45
    ALTER TABLE dbo.egress_ip ALTER COLUMN egress_ip VARCHAR(45) NOT NULL;
GO

-- Put your own router WAN address here before you rely on the allowlists,
-- otherwise a country/center with an empty egress_ip column locks you out.
-- Read it from https://ifconfig.me on the machine you log in from.
--
-- IF NOT EXISTS (SELECT 1 FROM dbo.egress_ip WHERE egress_ip = '203.0.113.7')
--     INSERT INTO dbo.egress_ip (egress_ip) VALUES ('203.0.113.7');
-- GO

SELECT egress_ip FROM dbo.egress_ip ORDER BY egress_ip;
GO
