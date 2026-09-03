-- Administrator egress IPs: allowed for every country and every center.
-- Idempotent. Run on local and remote so they stay identical.
--
-- SSMS: connect to database agrolav, then execute this file.
--
-- A country/center login is allowed when its address is listed here or in its
-- own dbo.country.egress_ip / dbo.center.egress_ip column; the allowed set is
-- the sum of the two. An empty or NULL column admits nothing, so leaving both
-- empty refuses every country and center login. Person logins are not gated.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.administrator', N'U') IS NULL
CREATE TABLE dbo.administrator (
    egress_ip VARCHAR(32) NOT NULL PRIMARY KEY
);
GO

-- Put your own router WAN address here before you rely on the allowlists,
-- otherwise a country/center with an empty egress_ip column locks you out.
-- Read it from https://ifconfig.me on the machine you log in from.
--
-- IF NOT EXISTS (SELECT 1 FROM dbo.administrator WHERE egress_ip = '203.0.113.7')
--     INSERT INTO dbo.administrator (egress_ip) VALUES ('203.0.113.7');
-- GO

SELECT egress_ip FROM dbo.administrator ORDER BY egress_ip;
GO
