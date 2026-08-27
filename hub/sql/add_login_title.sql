-- Add dbo.country.title and dbo.center.title (sidebar heading).
-- Idempotent. Run after migrate_person.sql (username columns exist).
--
-- SSMS: connect to database agrolav, then execute this file.
-- CLI:  cd hub && uv run python scripts/add_login_title.py

USE agrolav;
GO

IF COL_LENGTH(N'dbo.country', N'title') IS NULL
    ALTER TABLE dbo.country ADD title NVARCHAR(256) NULL;
GO

IF COL_LENGTH(N'dbo.center', N'title') IS NULL
    ALTER TABLE dbo.center ADD title NVARCHAR(256) NULL;
GO

IF COL_LENGTH(N'dbo.country', N'title') IS NOT NULL
   AND COL_LENGTH(N'dbo.country', N'username') IS NOT NULL
    UPDATE dbo.country SET title = username WHERE title IS NULL OR LTRIM(RTRIM(title)) = N'';
GO

IF COL_LENGTH(N'dbo.center', N'title') IS NOT NULL
   AND COL_LENGTH(N'dbo.center', N'username') IS NOT NULL
    UPDATE dbo.center SET title = username WHERE title IS NULL OR LTRIM(RTRIM(title)) = N'';
GO

IF COL_LENGTH(N'dbo.country', N'title') IS NOT NULL
    ALTER TABLE dbo.country ALTER COLUMN title NVARCHAR(256) NOT NULL;
GO

IF COL_LENGTH(N'dbo.center', N'title') IS NOT NULL
    ALTER TABLE dbo.center ALTER COLUMN title NVARCHAR(256) NOT NULL;
GO
