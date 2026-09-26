-- Which header-menu items a non-administrator may see.
-- An administrator sees every item the screen can offer; this table is not consulted.
-- country / center / person: 1 = visible for that login level, 0 = hidden.
-- Idempotent. Run on local and remote so they stay identical.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.menu_item', N'U') IS NULL
CREATE TABLE dbo.menu_item (
    menu_id VARCHAR(64) NOT NULL CONSTRAINT PK_menu_item PRIMARY KEY,
    country BIT NOT NULL,
    center  BIT NOT NULL,
    person  BIT NOT NULL,
    unit    BIT NOT NULL CONSTRAINT df_menu_item_unit DEFAULT (0)
);
GO

IF COL_LENGTH(N'dbo.menu_item', N'unit') IS NULL
    ALTER TABLE dbo.menu_item ADD unit BIT NOT NULL CONSTRAINT df_menu_item_unit DEFAULT (0);
GO

INSERT INTO dbo.menu_item (menu_id, country, center, person)
SELECT v.menu_id, v.country, v.center, v.person
FROM (VALUES
    ('add-person',              0, 0, 0),
    ('afschrijvingen',          1, 1, 1),
    ('back-to-matrix',          1, 1, 1),
    ('balance-sheet',           1, 1, 1),
    ('categories',              0, 0, 0),
    ('cross-postings',          0, 0, 0),
    ('download-ytd',            0, 0, 0),
    ('export-excel',            1, 0, 0),
    ('invalidate-consent',      0, 0, 0),
    ('ip-access',               0, 0, 0),
    ('journal',                 1, 1, 1),
    ('logout',                  1, 1, 1),
    ('prepare-consent',         0, 0, 0),
    ('recalculate-categories',  1, 1, 1),
    ('refresh',                 1, 1, 1),
    ('set-password',            1, 1, 1),
    ('small-expenses',          0, 0, 0),
    ('small-income',            0, 0, 0),
    ('terms',                   1, 1, 1),
    ('upload',                  0, 0, 0),
    ('wipe-year',               0, 0, 0)
) AS v(menu_id, country, center, person)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.menu_item m WHERE m.menu_id = v.menu_id
);
GO

SELECT menu_id, country, center, person, unit
FROM dbo.menu_item
ORDER BY menu_id;
GO
