-- Menu labels for center/country consent steps (term_lang1 English, term_lang2 Dutch).
-- Skip a row if the English key already exists.

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    ('Prepare consent', 'Bereid toestemming'),
    ('Invalidate consent', 'Verwijder toestemming'),
    ('Download YTD', 'YTD bankafschriften'),
    ('Delete all transactions', 'Verwijder alle bankafschriften')
) AS v (term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
