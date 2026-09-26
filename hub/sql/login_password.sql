-- Center and country logins store their own scrypt password.
-- Person and unit already have password_hash. Neither center nor country
-- stores a mobile phone.

IF COL_LENGTH(N'dbo.center', N'password_hash') IS NULL
    ALTER TABLE dbo.center ADD password_hash NVARCHAR(256) NULL;

IF COL_LENGTH(N'dbo.country', N'password_hash') IS NULL
    ALTER TABLE dbo.country ADD password_hash NVARCHAR(256) NULL;
