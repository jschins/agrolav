-- Center Goedkeuring / Approval menu.
-- term_lang1 is English (the key the screen looks up). term_lang2 is Dutch.
-- Menu visible only for center login (country=0, center=1, person=0, unit=0).
--
-- SSMS: connect to database agrolav, then execute this file.
-- Assumes dbo.center already has details and fiat_date columns.

USE agrolav;
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (N'Approval', N'Goedkeuring'),
    (N'Approval given', N'Goedkeuring gegeven')
) AS v(term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.language l
    WHERE l.term_lang1 = v.term_lang1 OR l.term_lang2 = v.term_lang2
);
GO

IF EXISTS (SELECT 1 FROM dbo.menu_item WHERE menu_id = N'approval')
    UPDATE dbo.menu_item
    SET country = 0, center = 1, person = 0, unit = 0
    WHERE menu_id = N'approval';
ELSE
    INSERT INTO dbo.menu_item (menu_id, country, center, person, unit)
    VALUES (N'approval', 0, 1, 0, 0);
GO

SELECT menu_id, country, center, person, unit
FROM dbo.menu_item
WHERE menu_id = N'approval';
GO

SELECT term_lang1, term_lang2
FROM dbo.language
WHERE term_lang1 IN (N'Approval', N'Approval given');
GO
