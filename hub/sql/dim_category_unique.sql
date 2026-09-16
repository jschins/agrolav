-- dim_category: unique (country_id, local_code) as UQ_category_country_code;
-- drop unique (country_id, label). Idempotent.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF EXISTS (
    SELECT 1
    FROM sys.key_constraints
    WHERE name = N'ux_dim_category_label'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
)
    ALTER TABLE dbo.dim_category DROP CONSTRAINT ux_dim_category_label;
GO

IF EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'ux_dim_category_label'
      AND object_id = OBJECT_ID(N'dbo.dim_category')
      AND is_unique = 1
      AND is_primary_key = 0
)
    DROP INDEX ux_dim_category_label ON dbo.dim_category;
GO

IF EXISTS (
    SELECT 1
    FROM sys.key_constraints
    WHERE name = N'ux_dim_category_code'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
)
AND NOT EXISTS (
    SELECT 1
    FROM sys.key_constraints
    WHERE name = N'UQ_category_country_code'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
)
    EXEC sp_rename N'dbo.ux_dim_category_code', N'UQ_category_country_code', N'OBJECT';
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.key_constraints
    WHERE name = N'UQ_category_country_code'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
)
    ALTER TABLE dbo.dim_category
    ADD CONSTRAINT UQ_category_country_code UNIQUE (country_id, local_code);
GO
