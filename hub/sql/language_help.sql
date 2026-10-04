-- Help-box placeholder.
-- term_lang1 is English (the key the screen looks up). term_lang2 is Dutch.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT N'Question about this program', N'Vraag over dit programma'
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.language l
    WHERE l.term_lang1 = N'Question about this program'
       OR l.term_lang2 = N'Vraag over dit programma'
);
GO
