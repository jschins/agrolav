-- Monthly drilldown menu. Person and unit only.
-- term_lang1 is English (the key the screen looks up). term_lang2 is Dutch.
-- country / center / person / unit: 0 0 1 1.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (N'Monthly drilldown', N'Maandelijkse totalen')
) AS v(term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.language l
    WHERE l.term_lang1 = v.term_lang1 OR l.term_lang2 = v.term_lang2
);
GO

IF EXISTS (SELECT 1 FROM dbo.menu_item WHERE menu_id = N'monthly-drilldown')
    UPDATE dbo.menu_item
    SET country = 0, center = 0, person = 1, unit = 1
    WHERE menu_id = N'monthly-drilldown';
ELSE
    INSERT INTO dbo.menu_item (menu_id, country, center, person, unit)
    VALUES (N'monthly-drilldown', 0, 0, 1, 1);
GO
