-- Who may see each category. 1 = country only … 5 = country, center,
-- person, work-unit, and HD. Existing rows stay visible to every login
-- until a tighter number is stored. Idempotent.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF COL_LENGTH(N'dbo.dim_category', N'visibility') IS NULL
    ALTER TABLE dbo.dim_category
        ADD visibility INT NOT NULL
            CONSTRAINT df_dim_category_visibility DEFAULT (5);
GO

IF OBJECT_ID(N'dbo.ck_dim_category_visibility', N'C') IS NULL
    ALTER TABLE dbo.dim_category
        ADD CONSTRAINT ck_dim_category_visibility CHECK (visibility BETWEEN 1 AND 5);
GO
