-- Set modification = -1 and category_id to that country's remainder
-- on the bookings listed as snap N'before'.
-- The remainder is the dbo.dim_category row whose category_role is remainder.
-- Run hub/sql/cp_rules_bookings.sql with @snap = N'before' first.
-- A hand booking (modification 2, 3, or 4) is left as it is.
--
-- SSMS: connect to database agrolav, then execute this file.
-- Then Bereken kruisposten, then list again with @snap = N'after'.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.cp_rule_booking_snap', N'U') IS NULL
   OR NOT EXISTS (SELECT 1 FROM dbo.cp_rule_booking_snap WHERE snap = N'before')
BEGIN
    RAISERROR(N'Run hub/sql/cp_rules_bookings.sql with @snap = N''before'' first.', 16, 1);
    RETURN;
END

DECLARE @table_name sysname;
DECLARE @remainder_id int;
DECLARE @sql nvarchar(max);
DECLARE @updated int;

DECLARE tables CURSOR LOCAL FAST_FORWARD FOR
    SELECT DISTINCT table_name
    FROM dbo.cp_rule_booking_snap
    WHERE snap = N'before';

OPEN tables;
FETCH NEXT FROM tables INTO @table_name;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF OBJECT_ID(@table_name, N'U') IS NOT NULL
    BEGIN
        SET @remainder_id = NULL;
        SELECT TOP (1) @remainder_id = d.category_id
        FROM dbo.country c
        JOIN dbo.dim_category d ON d.country_id = c.country_id
        WHERE N'dbo.' + QUOTENAME(N'transaction_' + c.username) = @table_name
          AND LOWER(LTRIM(RTRIM(ISNULL(d.category_role, N'')))) = N'remainder'
        ORDER BY d.local_code, d.category_id;
        IF @remainder_id IS NULL
        BEGIN
            RAISERROR(N'No remainder category for %s.', 16, 1, @table_name);
            RETURN;
        END
        SET @sql = N'
UPDATE t
SET modification = -1,
    category_id = @remainder_id
FROM ' + @table_name + N' t
JOIN dbo.cp_rule_booking_snap s
  ON s.transaction_id = t.transaction_id
 AND s.snap = N''before''
 AND s.table_name = @table_name
WHERE t.modification NOT IN (2, 3, 4);
SET @updated = @@ROWCOUNT;
';
        EXEC sp_executesql
            @sql,
            N'@table_name sysname, @remainder_id int, @updated int OUTPUT',
            @table_name = @table_name,
            @remainder_id = @remainder_id,
            @updated = @updated OUTPUT;
        PRINT @table_name + N': ' + CONVERT(nvarchar(20), @updated)
            + N' bookings set to modification -1 and category ' + CONVERT(nvarchar(20), @remainder_id);
    END
    FETCH NEXT FROM tables INTO @table_name;
END
CLOSE tables;
DEALLOCATE tables;
GO
