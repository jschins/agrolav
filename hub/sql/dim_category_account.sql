-- Nullable account_id and assoc_cat_id on dbo.dim_category.
-- This file does not write those values.
-- An existing assoc_category_id column is renamed to assoc_cat_id.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF COL_LENGTH(N'dbo.dim_category', N'account_id') IS NULL
    ALTER TABLE dbo.dim_category ADD account_id INT NULL;
GO

IF COL_LENGTH(N'dbo.dim_category', N'person_id') IS NOT NULL
   AND COL_LENGTH(N'dbo.dim_category', N'assoc_cat_id') IS NULL
   AND COL_LENGTH(N'dbo.dim_category', N'assoc_category_id') IS NULL
    EXEC sp_rename N'dbo.dim_category.person_id', N'assoc_cat_id', N'COLUMN';
GO

IF COL_LENGTH(N'dbo.dim_category', N'assoc_category_id') IS NOT NULL
   AND COL_LENGTH(N'dbo.dim_category', N'assoc_cat_id') IS NULL
    EXEC sp_rename N'dbo.dim_category.assoc_category_id', N'assoc_cat_id', N'COLUMN';
GO

IF COL_LENGTH(N'dbo.dim_category', N'assoc_cat_id') IS NULL
    ALTER TABLE dbo.dim_category ADD assoc_cat_id INT NULL;
GO

IF OBJECT_ID(N'dbo.fk_dim_category_person', N'F') IS NOT NULL
    ALTER TABLE dbo.dim_category DROP CONSTRAINT fk_dim_category_person;
GO

IF OBJECT_ID(N'dbo.fk_dim_category_account', N'F') IS NULL
    ALTER TABLE dbo.dim_category
        ADD CONSTRAINT fk_dim_category_account
            FOREIGN KEY (account_id) REFERENCES dbo.account (account_id);
GO

IF OBJECT_ID(N'dbo.fk_dim_category_assoc', N'F') IS NULL
    ALTER TABLE dbo.dim_category
        ADD CONSTRAINT fk_dim_category_assoc
            FOREIGN KEY (assoc_cat_id) REFERENCES dbo.dim_category (category_id);
GO
