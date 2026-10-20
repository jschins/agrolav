-- Center Visibility / Zichtbaarheid menu (replaces Approval / Goedkeuring).
-- term_lang1 is English (the key the screen looks up). term_lang2 is Dutch.
-- Menu visible only for center login (country=0, center=1, person=0, unit=0).
--
-- Also renames dbo.center.details → visibility and dbo.person.details →
-- visibility (BIT NULL) when needed. Drop fiat_date if it is still present.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF COL_LENGTH(N'dbo.center', N'fiat_date') IS NOT NULL
    ALTER TABLE dbo.center DROP COLUMN fiat_date;
GO

-- Rename center.details → visibility when the old column is still there.
IF COL_LENGTH(N'dbo.center', N'details') IS NOT NULL
   AND COL_LENGTH(N'dbo.center', N'visibility') IS NULL
BEGIN
    EXEC sp_rename N'dbo.center.details', N'visibility', N'COLUMN';
END
GO

-- Ensure BIT NULL (sp_rename keeps the old type; alter if still not bit).
IF COL_LENGTH(N'dbo.center', N'visibility') IS NOT NULL
BEGIN
    DECLARE @type sysname =
        (SELECT t.name
         FROM sys.columns c
         JOIN sys.types t ON c.user_type_id = t.user_type_id
         WHERE c.object_id = OBJECT_ID(N'dbo.center') AND c.name = N'visibility');
    IF @type <> N'bit'
        ALTER TABLE dbo.center ALTER COLUMN visibility BIT NULL;
END
GO

IF COL_LENGTH(N'dbo.center', N'visibility') IS NULL
    ALTER TABLE dbo.center ADD visibility BIT NULL;
GO

-- Rename person.details → visibility when the old column is still there.
IF COL_LENGTH(N'dbo.person', N'details') IS NOT NULL
   AND COL_LENGTH(N'dbo.person', N'visibility') IS NULL
BEGIN
    EXEC sp_rename N'dbo.person.details', N'visibility', N'COLUMN';
END
GO

IF COL_LENGTH(N'dbo.person', N'visibility') IS NOT NULL
BEGIN
    DECLARE @person_vis_type sysname =
        (SELECT t.name
         FROM sys.columns c
         JOIN sys.types t ON c.user_type_id = t.user_type_id
         WHERE c.object_id = OBJECT_ID(N'dbo.person') AND c.name = N'visibility');
    IF @person_vis_type <> N'bit'
        ALTER TABLE dbo.person ALTER COLUMN visibility BIT NULL;
END
GO

IF COL_LENGTH(N'dbo.person', N'visibility') IS NULL
    ALTER TABLE dbo.person ADD visibility BIT NULL;
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (N'Visibility', N'Zichtbaarheid'),
    (N'Check for visibility', N'Aanvinken voor zichtbaarheid')
) AS v(term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.language l
    WHERE l.term_lang1 = v.term_lang1 OR l.term_lang2 = v.term_lang2
);
GO

IF EXISTS (SELECT 1 FROM dbo.menu_item WHERE menu_id = N'approval')
    DELETE FROM dbo.menu_item WHERE menu_id = N'approval';
GO

IF EXISTS (SELECT 1 FROM dbo.menu_item WHERE menu_id = N'visibility')
    UPDATE dbo.menu_item
    SET country = 0, center = 1, person = 0, unit = 0
    WHERE menu_id = N'visibility';
ELSE
    INSERT INTO dbo.menu_item (menu_id, country, center, person, unit)
    VALUES (N'visibility', 0, 1, 0, 0);
GO

SELECT menu_id, country, center, person, unit
FROM dbo.menu_item
WHERE menu_id = N'visibility';
GO

SELECT term_lang1, term_lang2
FROM dbo.language
WHERE term_lang1 IN (N'Visibility', N'Check for visibility');
GO
