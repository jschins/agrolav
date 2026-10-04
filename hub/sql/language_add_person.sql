-- Add-person form: Name and Username.
-- term_lang1 is English (the key the screen looks up). term_lang2 is Dutch.
-- The username hint is longer than VARCHAR(64), so it lives in dbo.language_long.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (N'Name', N'Naam'),
    (N'Username', N'Gebruikersnaam')
) AS v(term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.language l
    WHERE l.term_lang1 = v.term_lang1
       OR l.term_lang2 = v.term_lang2
);
GO

INSERT INTO dbo.language_long (term_key, term_lang1, term_lang2)
SELECT
    N'Username characters',
    N'Username may contain only letters, digits, underscores and hyphens',
    N'Gebruikersnaam mag alleen letters, cijfers, underscores en streepjes bevatten'
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.language_long l
    WHERE l.term_key = N'Username characters'
);
GO
