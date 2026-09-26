-- Menu label and statement-search field labels.
-- term_lang1 is English (the key the screen looks up). term_lang2 is Dutch.
-- Also inserts the menu row. country/center/person/unit = 1 means visible.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (N'Search statements', N'Zoek in afschriften'),
    (N'Date from', N'Datum van'),
    (N'Date to', N'Datum tot'),
    (N'Text in description', N'Tekst in omschrijving'),
    (N'Text in name', N'Tekst in naam'),
    (N'Amount from', N'Bedrag van'),
    (N'Amount to', N'Bedrag tot'),
    (N'Account holder IBAN', N'IBAN rekeninghouder'),
    (N'Counterparty IBAN', N'IBAN tegenpartij'),
    (N'Search', N'Zoek'),
    (N'No bookings', N'Geen boekingen'),
    (N'Showing the first 500 bookings', N'Dit zijn de eerste 500 boekingen')
) AS v(term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.language l
    WHERE l.term_lang1 = v.term_lang1 OR l.term_lang2 = v.term_lang2
);
GO

INSERT INTO dbo.menu_item (menu_id, country, center, person, unit)
SELECT N'search-statements', 1, 1, 1, 1
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.menu_item WHERE menu_id = N'search-statements'
);
GO
