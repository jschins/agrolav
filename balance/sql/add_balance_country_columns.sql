INSERT INTO dbo.country VALUES (5, 'beheer_instudo', 'EUR', 'Beheer Instudo', 4, NULL);
INSERT INTO dbo.center VALUES (7, 5, 'beh_instudo', 'Beheer Instudo', NULL);

ALTER TABLE dbo.country ADD has_balance BIT NOT NULL
  CONSTRAINT DF_country_has_balance DEFAULT 0 WITH VALUES;
ALTER TABLE dbo.country DROP CONSTRAINT DF_country_has_balance;

UPDATE dbo.country SET has_balance = 1 WHERE country_id IN (4, 5);

ALTER TABLE dbo.balance_opening ADD country_id INT NOT NULL
    CONSTRAINT DF_balance_opening_country DEFAULT 4 WITH VALUES;
ALTER TABLE dbo.balance_opening DROP CONSTRAINT DF_balance_opening_country;

ALTER TABLE dbo.balance_journal ADD country_id INT NOT NULL
    CONSTRAINT DF_balance_journal_country DEFAULT 4 WITH VALUES;
ALTER TABLE dbo.balance_journal DROP CONSTRAINT DF_balance_journal_country;

ALTER TABLE dbo.balance_transaction ADD country_id INT NOT NULL
    CONSTRAINT DF_balance_transaction_country DEFAULT 4 WITH VALUES;
ALTER TABLE dbo.balance_transaction DROP CONSTRAINT DF_balance_transaction_country;

ALTER TABLE dbo.balance_opening DROP CONSTRAINT pk_balance_opening;
ALTER TABLE dbo.balance_opening ADD CONSTRAINT pk_balance_opening PRIMARY KEY (country_id, category_id, year);

CREATE NONCLUSTERED INDEX ix_balance_transaction_country_year
    ON dbo.balance_transaction (country_id, year);

CREATE NONCLUSTERED INDEX ix_balance_journal_country_year
    ON dbo.balance_journal (country_id, year);
