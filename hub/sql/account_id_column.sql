-- Replace dbo.category_term_account with a direct nullable dbo.category_term.account_id
-- 1) add the column, 2) backfill from the mapping table, 3) drop it, 4) FK + scoped unique index.
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.category_term') AND name = N'account_id'
)
BEGIN
    ALTER TABLE dbo.category_term ADD account_id int NULL;
END;
GO

IF OBJECT_ID(N'dbo.category_term_account', N'U') IS NOT NULL
BEGIN
    UPDATE t
    SET account_id = cta.account_id
    FROM dbo.category_term t
    JOIN dbo.category_term_account cta ON cta.term_id = t.term_id
    WHERE t.account_id IS NULL;

    DROP TABLE dbo.category_term_account;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE parent_object_id = OBJECT_ID(N'dbo.category_term') AND name = N'fk_ct_account'
)
BEGIN
    ALTER TABLE dbo.category_term
        ADD CONSTRAINT fk_ct_account FOREIGN KEY (account_id)
            REFERENCES dbo.account(account_id) ON DELETE CASCADE;
END;
GO
-- Person-modality uniqueness stays on the existing ux_category_term_personal
-- (account_id NULL rows). Account rows get their own filtered unique index;
-- SQL Server treats multiple NULLs as distinct, so the filtered index must
-- exclude NULL to avoid clashing with the person-modality key.
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_category_term_account' AND object_id = OBJECT_ID(N'dbo.category_term')
)
BEGIN
    CREATE UNIQUE INDEX ux_category_term_account
        ON dbo.category_term (category_id, person_id, account_id, term)
        WHERE account_id IS NOT NULL;
END;
GO
SELECT t.name AS table_name,
       c.name AS col,
       c.column_id
FROM sys.tables t
JOIN sys.columns c ON c.object_id = t.object_id
WHERE t.name IN (N'category_term', N'category_term_account')
ORDER BY t.name, c.column_id;