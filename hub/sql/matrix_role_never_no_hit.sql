-- Widen ck_dim_category_role. Idempotent.
-- Roles are assigned on dbo.dim_category.category_role, not by local_code.
--   never     = Eigen vermogen: no HIT, no journal
--   profit    = Verlies / resultaat plug: no HIT, no journal
--   source    = spaar source account: no HIT; journals allowed
--   mirror    = spaar mirror post: no HIT; journals allowed
--   no_hit    = other live bank posts: no HIT; journals allowed
--   remainder = unclassified / default HIT target
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = N'ck_dim_category_role'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
      AND (
          definition NOT LIKE N'%remainder%'
          OR definition NOT LIKE N'%profit%'
          OR definition NOT LIKE N'%category_role%'
      )
)
    ALTER TABLE dbo.dim_category DROP CONSTRAINT ck_dim_category_role;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = N'ck_dim_category_role'
      AND parent_object_id = OBJECT_ID(N'dbo.dim_category')
)
    ALTER TABLE dbo.dim_category ADD CONSTRAINT ck_dim_category_role CHECK (
        category_role IS NULL OR category_role IN (
            N'balance', N'last_booked', N'never', N'profit', N'no_hit', N'source', N'mirror', N'remainder'
        )
    );
GO

IF COL_LENGTH(N'dbo.dim_category', N'is_remainder') IS NOT NULL
    UPDATE dbo.dim_category SET category_role = N'remainder'
    WHERE is_remainder = 1 AND category_role IS NULL;
GO
