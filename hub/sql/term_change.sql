-- Pending term edits for incremental iRCfT.
-- Run once on agrolav. Term saves record a row here.
-- Recalculate → Incremental walks these rows and deletes them.
-- Recalculate → From scratch deletes the personal rows it has just re-scored.

IF OBJECT_ID(N'dbo.term_change', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.term_change (
        term_change_id INT IDENTITY(1, 1) NOT NULL CONSTRAINT PK_term_change PRIMARY KEY,
        category_id INT NOT NULL,
        person_id INT NULL,
        account_id INT NULL,
        term NVARCHAR(256) NOT NULL,
        added BIT NOT NULL
    );
END
GO
