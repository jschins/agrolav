-- Drop ck_dim_category_role. Idempotent.
-- category_role holds system stamps or a login username (Export resultaat).
-- Do not recreate the CHECK; hub/balance used to put it back and then fail
-- when a username was already stored.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = N'ck_dim_category_role'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
)
    ALTER TABLE dbo.dim_category DROP CONSTRAINT ck_dim_category_role;
GO

IF COL_LENGTH(N'dbo.dim_category', N'is_remainder') IS NOT NULL
    UPDATE dbo.dim_category SET category_role = N'remainder'
    WHERE is_remainder = 1 AND category_role IS NULL;
GO
