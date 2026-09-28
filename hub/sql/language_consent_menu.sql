-- Menu labels for center/country consent steps and Export zip
-- (term_lang1 English, term_lang2 Dutch).
-- Skip a row if the English key already exists.

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    ('Apply hand categorizations', 'Pas handmatige categorisaties toe'),
    ('Calculate opening balance', 'Bereken beginbalans'),
    ('Prepare consent', 'Bereid toestemming'),
    ('Invalidate consent', 'Verwijder toestemming'),
    ('Download YTD', 'YTD bankafschriften'),
    ('Journal', 'Journaal')
) AS v (term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
GO

UPDATE dbo.language
SET term_lang1 = N'Export zip',
    term_lang2 = N'Export zip'
WHERE term_lang1 = N'Export balance sheet';
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT N'Export zip', N'Export zip'
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language WHERE term_lang1 = N'Export zip'
);
GO
