-- Owner of an Enable Banking application key before any dbo.account rows exist.
-- Does not DROP DATABASE.

USE agrolav
GO

IF COL_LENGTH(N'dbo.enable_connection', N'person_id') IS NULL
    ALTER TABLE dbo.enable_connection ADD person_id INT NULL
GO

IF COL_LENGTH(N'dbo.enable_connection', N'person_id') IS NOT NULL
    UPDATE ec
    SET person_id = a.person_id
    FROM dbo.enable_connection ec
    INNER JOIN dbo.account a ON a.connection_id = ec.connection_id
    WHERE ec.person_id IS NULL
GO

IF COL_LENGTH(N'dbo.enable_connection', N'person_id') IS NOT NULL
   AND OBJECT_ID(N'fk_enable_connection_person', N'F') IS NULL
    ALTER TABLE dbo.enable_connection WITH CHECK ADD CONSTRAINT fk_enable_connection_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id)
GO
