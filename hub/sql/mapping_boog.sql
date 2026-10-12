-- dbo.mapping for country 6 (beheer_boog): the spaar source account.
--
-- The spaar pass reads dbo.mapping, counterparty empty, on the category
-- whose role is source (local code 1300). It does not read
-- dbo.dim_category.account_id. The mirror (local code 1301) stays unmapped.
--
-- The account is the one whose bookings contain "spaarrekening".
-- Exactly one such account is inserted. Several accounts are listed and
-- left unmapped.
--
-- SSMS: connect to database agrolav, then execute this file.
-- Then open the matrix again so the spaar rows are rebuilt.

USE agrolav;
GO

DECLARE @country_id int = 6;
DECLARE @source_id int;
DECLARE @username sysname;
DECLARE @table nvarchar(300);
DECLARE @sql nvarchar(max);
DECLARE @n int;

DECLARE @accounts TABLE (
    account_id int NOT NULL PRIMARY KEY
);

SELECT @source_id = category_id
FROM dbo.dim_category
WHERE country_id = @country_id
  AND local_code = 1300
  AND LOWER(LTRIM(RTRIM(ISNULL(category_role, N'')))) = N'source';

IF @source_id IS NULL
BEGIN
    RAISERROR(N'Country 6 has no source category with local_code 1300.', 16, 1);
    RETURN;
END

SELECT @username = username
FROM dbo.country
WHERE country_id = @country_id;

IF @username IS NULL
   OR @username LIKE N'%[^A-Za-z0-9_]%'
   OR LEFT(@username, 1) LIKE N'[0-9]'
BEGIN
    RAISERROR(N'Country 6 has no usable username for its transaction table.', 16, 1);
    RETURN;
END

SET @table = N'dbo.transaction_' + @username;

IF OBJECT_ID(@table, N'U') IS NULL
BEGIN
    RAISERROR(N'%s does not exist.', 16, 1, @table);
    RETURN;
END

SET @sql = N'
    SELECT DISTINCT t.account_id
    FROM ' + @table + N' t
    WHERE t.account_id IS NOT NULL
      AND LOWER(COALESCE(t.description, N'''')) LIKE N''%spaarrekening%''
';
INSERT INTO @accounts (account_id)
EXEC sp_executesql @sql;

SELECT @n = COUNT(*) FROM @accounts;

SELECT
    a.account_id,
    ac.iban,
    @source_id AS category_id,
    1300 AS local_code
FROM @accounts a
JOIN dbo.account ac ON ac.account_id = a.account_id;

IF @n = 0
BEGIN
    RAISERROR(
        N'No booking on %s has spaarrekening in description. No mapping row inserted.',
        16, 1, @table
    );
    RETURN;
END

IF @n > 1
BEGIN
    RAISERROR(
        N'%d accounts contain spaarrekening. No mapping row inserted.',
        16, 1, @n
    );
    RETURN;
END

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT @country_id, a.account_id, @source_id, NULL
FROM @accounts a
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.mapping m
    WHERE m.country_id = @country_id
      AND m.account_id = a.account_id
      AND m.category_id = @source_id
      AND m.counterparty_account_id IS NULL
);

SELECT m.country_id, m.account_id, m.category_id, m.counterparty_account_id
FROM dbo.mapping m
WHERE m.country_id = @country_id
  AND m.category_id = @source_id
  AND m.counterparty_account_id IS NULL;
GO
