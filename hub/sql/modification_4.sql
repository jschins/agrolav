-- modification 2: hand category. 3: hand description. 4: both.
-- Widen every dbo.transaction_* check so 4 can be stored.
-- A stored 3 that is also in dbo.category_hand was the previous "both"
-- and becomes 4. A 3 with no hand-category row stays 3.
--
-- SSMS: connect to database agrolav, then execute this file once.

USE agrolav;
GO

DECLARE @drop NVARCHAR(MAX) = N'';

SELECT @drop = @drop
    + N'ALTER TABLE ' + QUOTENAME(SCHEMA_NAME(t.schema_id)) + N'.' + QUOTENAME(t.name)
    + N' DROP CONSTRAINT ' + QUOTENAME(cc.name) + N';'
FROM sys.check_constraints cc
JOIN sys.tables t ON t.object_id = cc.parent_object_id
WHERE SCHEMA_NAME(t.schema_id) = N'dbo'
  AND t.name LIKE N'transaction[_]%'
  AND cc.definition LIKE N'%modification%'
  AND cc.definition NOT LIKE N'%(4)%';

IF @drop <> N''
    EXEC sp_executesql @drop;
GO

DECLARE @add NVARCHAR(MAX) = N'';

SELECT @add = @add
    + N'ALTER TABLE dbo.' + QUOTENAME(t.name)
    + N' ADD CONSTRAINT ' + QUOTENAME(N'ck_' + t.name + N'_mod')
    + N' CHECK (modification IN (-1, 0, 1, 2, 3, 4));'
FROM sys.tables t
WHERE SCHEMA_NAME(t.schema_id) = N'dbo'
  AND t.name LIKE N'transaction[_]%'
  AND NOT EXISTS (
      SELECT 1
      FROM sys.check_constraints cc
      WHERE cc.parent_object_id = t.object_id
        AND cc.definition LIKE N'%modification%'
        AND cc.definition LIKE N'%(4)%'
  );

IF @add <> N''
    EXEC sp_executesql @add;
GO

IF OBJECT_ID(N'dbo.category_hand', N'U') IS NOT NULL
BEGIN
    DECLARE @move NVARCHAR(MAX) = N'';

    SELECT @move = @move
        + N'UPDATE t SET t.modification = 4 FROM dbo.' + QUOTENAME(t.name) + N' t '
        + N'WHERE t.modification = 3 AND EXISTS ('
        + N'SELECT 1 FROM dbo.category_hand h '
        + N'JOIN dbo.person p ON p.id = h.person_id '
        + N'JOIN dbo.center n ON n.center_id = p.center_id '
        + N'WHERE h.person_id = t.person_id AND h.year = t.year AND h.source_id = t.source_id '
        + N'AND n.country_id = h.country_id);'
    FROM sys.tables t
    WHERE SCHEMA_NAME(t.schema_id) = N'dbo'
      AND t.name LIKE N'transaction[_]%';

    IF @move <> N''
        EXEC sp_executesql @move;
END
GO
