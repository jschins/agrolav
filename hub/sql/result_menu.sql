-- Menu label for the profit/loss window (port 8500).
-- term_lang1 is English (the key the screen looks up). term_lang2 is Dutch.
-- Also inserts the menu row. country/center/person/unit = 1 means visible.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (N'Profit/Loss', N'Resultaat')
) AS v(term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.language l
    WHERE l.term_lang1 = v.term_lang1 OR l.term_lang2 = v.term_lang2
);
GO

INSERT INTO dbo.menu_item (menu_id, country, center, person, unit)
SELECT N'profit-loss', 1, 1, 1, 1
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.menu_item WHERE menu_id = N'profit-loss'
);
GO
