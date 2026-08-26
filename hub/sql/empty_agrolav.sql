-- Empty dbo in database agrolav. Does not DROP DATABASE.
-- SSMS: stay connected to agrolav, then run this.
-- Reload data with: cd hub && uv run python scripts/load_phase_c.py
-- (that script also empties tables; you do not need DROP DATABASE first.)

USE agrolav;
GO

DECLARE @sql nvarchar(max) = N'';

SELECT @sql = @sql + N'ALTER TABLE '
    + QUOTENAME(OBJECT_SCHEMA_NAME(parent_object_id))
    + N'.' + QUOTENAME(OBJECT_NAME(parent_object_id))
    + N' DROP CONSTRAINT ' + QUOTENAME(name) + N';'
FROM sys.foreign_keys;

IF @sql <> N''
    EXEC sp_executesql @sql;

SET @sql = N'';

SELECT @sql = @sql + N'DROP TABLE '
    + QUOTENAME(SCHEMA_NAME(schema_id)) + N'.' + QUOTENAME(name) + N';'
FROM sys.tables
WHERE is_ms_shipped = 0;

IF @sql <> N''
    EXEC sp_executesql @sql;
GO
