USE agrolav;
GO

IF OBJECT_ID(N'dbo.balance_journal', N'U') IS NULL
CREATE TABLE dbo.balance_journal (
    journal_id      INT           IDENTITY(1,1) PRIMARY KEY,
    country_id      INT           NOT NULL,
    year            INT           NOT NULL,
    date            DATE          NOT NULL,
    category_from   INT           NOT NULL,
    category_to     INT           NOT NULL,
    amount          DECIMAL(18,2) NOT NULL,
    description     NVARCHAR(512) NOT NULL,
    created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'ix_balance_journal_country_year'
      AND object_id = OBJECT_ID(N'dbo.balance_journal')
)
    CREATE NONCLUSTERED INDEX ix_balance_journal_country_year
        ON dbo.balance_journal (country_id, year);
GO

-- A hand-edited journal entry moves money from one balance category to another:
-- the FROM category decreases by [amount], the TO category increases by [amount].
-- (Confirmed intended sign convention.)
