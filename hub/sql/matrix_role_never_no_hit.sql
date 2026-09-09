-- Stamp booking rules on dbo.dim_category.matrix_role.
-- Idempotent. 2000 Eigen vermogen = never (no HIT, no journal).
-- 1051-1056 bank posts = no_hit (no HIT; journals allowed).
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = N'ck_dim_category_role'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
      AND definition NOT LIKE N'%never%'
)
    ALTER TABLE dbo.dim_category DROP CONSTRAINT ck_dim_category_role;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = N'ck_dim_category_role'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
)
    ALTER TABLE dbo.dim_category ADD CONSTRAINT ck_dim_category_role CHECK (
        matrix_role IS NULL OR matrix_role IN (N'balance', N'last_booked', N'never', N'no_hit')
    );
GO

UPDATE dbo.dim_category SET matrix_role = N'never'
WHERE local_code = 2000 AND matrix_role IS NULL;
GO

UPDATE dbo.dim_category SET matrix_role = N'no_hit'
WHERE local_code BETWEEN 1051 AND 1056 AND matrix_role IS NULL;
GO
