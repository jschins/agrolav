-- Authenticator secret for the login that can sign in from anywhere.
-- Person when dbo.country.has_balance is not set.
-- Unit when dbo.country.has_balance is set.
-- Empty means password only. The hub does not create this column.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.person', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.person', N'totp_secret') IS NULL
    ALTER TABLE dbo.person ADD totp_secret NVARCHAR(64) NULL;
GO

IF OBJECT_ID(N'dbo.unit', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.unit', N'totp_secret') IS NULL
    ALTER TABLE dbo.unit ADD totp_secret NVARCHAR(64) NULL;
GO

SELECT
    COL_LENGTH(N'dbo.person', N'totp_secret') AS person_totp_secret,
    COL_LENGTH(N'dbo.unit', N'totp_secret') AS unit_totp_secret;
GO
