-- In-place cutover: mixed dbo.app_user logins -> dbo.person (people only).
-- country.name / center.name -> username.
-- Child columns app_user_id -> person_id.
-- Preserves bookings and accounts. Does not DROP DATABASE.
--
-- Stop the hub first. Run this once on the laptop, then on the VPS
-- (or BACKUP after the laptop run and restore on the VPS).
-- Do not run load_phase_c.py on live data after this.
--
-- SSMS: connect to database agrolav, then execute this file.
-- CLI:  cd hub && uv run python scripts/migrate_person.py
--
-- GO splits are required: SQL Server compiles each batch against the names
-- that exist before that batch runs.

USE agrolav;
GO

---------------------------------------------------------------------
-- Batch 1: app_user -> person, app_user_id -> person_id
---------------------------------------------------------------------
IF OBJECT_ID(N'dbo.app_user', N'U') IS NULL
BEGIN
    IF OBJECT_ID(N'dbo.person', N'U') IS NULL
        THROW 50001, N'dbo.app_user is missing and the database is not already migrated. Stop.', 1;
    PRINT N'batch 1 skipped: dbo.person already exists';
END
ELSE
BEGIN
    IF EXISTS (
        SELECT 1
        FROM dbo.account a
        INNER JOIN dbo.app_user u ON u.id = a.app_user_id
        WHERE u.number_of_accounts IS NULL
    )
        THROW 50002, N'account rows still point at a country/center login. Stop.', 1;

    IF EXISTS (
        SELECT 1
        FROM dbo.app_user
        WHERE number_of_accounts IS NOT NULL
          AND center_id IS NULL
    )
        THROW 50003, N'person pack rows have NULL center_id. Stop.', 1;

    IF EXISTS (
        SELECT name
        FROM dbo.center
        GROUP BY name
        HAVING COUNT(*) > 1
    )
        THROW 50004, N'center names are not globally unique; cannot UNIQUE(username). Stop.', 1;

    ALTER TABLE dbo.account DROP CONSTRAINT IF EXISTS fk_account_app_user;
    ALTER TABLE dbo.category_term DROP CONSTRAINT IF EXISTS fk_category_term_app_user;
    ALTER TABLE dbo.category_total DROP CONSTRAINT IF EXISTS fk_ct_app_user;
    ALTER TABLE dbo.transaction_nederland DROP CONSTRAINT IF EXISTS fk_txn_nl_app_user;
    ALTER TABLE dbo.transaction_uk DROP CONSTRAINT IF EXISTS fk_txn_uk_app_user;
    ALTER TABLE dbo.app_user DROP CONSTRAINT IF EXISTS fk_app_user_country;
    ALTER TABLE dbo.app_user DROP CONSTRAINT IF EXISTS fk_app_user_center;
    ALTER TABLE dbo.app_user DROP CONSTRAINT IF EXISTS ck_app_user_pack;

    DROP INDEX IF EXISTS ux_category_term_catalog ON dbo.category_term;
    DROP INDEX IF EXISTS ux_category_term_personal ON dbo.category_term;
    DROP INDEX IF EXISTS ux_txn_nl_consolidated ON dbo.transaction_nederland;
    DROP INDEX IF EXISTS ux_txn_nl_bank ON dbo.transaction_nederland;
    DROP INDEX IF EXISTS ux_txn_uk_consolidated ON dbo.transaction_uk;
    DROP INDEX IF EXISTS ux_txn_uk_bank ON dbo.transaction_uk;
    DROP INDEX IF EXISTS ux_category_total_consolidated ON dbo.category_total;
    DROP INDEX IF EXISTS ux_category_total_bank ON dbo.category_total;

    IF OBJECT_ID(N'dbo.enable_connection', N'U') IS NOT NULL
        ALTER TABLE dbo.enable_connection DROP CONSTRAINT IF EXISTS fk_enable_connection_user;
    IF OBJECT_ID(N'dbo.enable_redirect', N'U') IS NOT NULL
        ALTER TABLE dbo.enable_redirect DROP CONSTRAINT IF EXISTS fk_enable_redirect_user;
    IF OBJECT_ID(N'dbo.private_key', N'U') IS NOT NULL
        ALTER TABLE dbo.private_key DROP CONSTRAINT IF EXISTS fk_private_key_user;

    DELETE FROM dbo.app_user
    WHERE number_of_accounts IS NULL;

    UPDATE dbo.app_user
    SET title = username
    WHERE title IS NULL
       OR LTRIM(RTRIM(title)) = N'';

    ALTER TABLE dbo.app_user ALTER COLUMN title NVARCHAR(256) NOT NULL;
    ALTER TABLE dbo.app_user ALTER COLUMN center_id INT NOT NULL;
    ALTER TABLE dbo.app_user ALTER COLUMN number_of_accounts INT NOT NULL;

    EXEC sp_rename N'dbo.app_user', N'person';

    IF EXISTS (
        SELECT 1
        FROM sys.indexes
        WHERE name = N'ux_app_user_username'
          AND object_id = OBJECT_ID(N'dbo.person')
    )
        EXEC sp_rename N'dbo.person.ux_app_user_username', N'ux_person_username', N'INDEX';

    EXEC sp_rename N'dbo.account.app_user_id', N'person_id', N'COLUMN';
    EXEC sp_rename N'dbo.category_term.app_user_id', N'person_id', N'COLUMN';
    EXEC sp_rename N'dbo.category_total.app_user_id', N'person_id', N'COLUMN';
    EXEC sp_rename N'dbo.transaction_nederland.app_user_id', N'person_id', N'COLUMN';
    EXEC sp_rename N'dbo.transaction_uk.app_user_id', N'person_id', N'COLUMN';

    IF COL_LENGTH(N'dbo.enable_connection', N'app_user_id') IS NOT NULL
        EXEC sp_rename N'dbo.enable_connection.app_user_id', N'person_id', N'COLUMN';
    IF COL_LENGTH(N'dbo.enable_redirect', N'app_user_id') IS NOT NULL
        EXEC sp_rename N'dbo.enable_redirect.app_user_id', N'person_id', N'COLUMN';
    IF COL_LENGTH(N'dbo.private_key', N'app_user_id') IS NOT NULL
        EXEC sp_rename N'dbo.private_key.app_user_id', N'person_id', N'COLUMN';

    PRINT N'batch 1: dbo.person and person_id';
END
GO

---------------------------------------------------------------------
-- Batch 2: filtered indexes on person_id (column exists after batch 1)
---------------------------------------------------------------------
IF OBJECT_ID(N'dbo.person', N'U') IS NULL
    THROW 50007, N'dbo.person missing after batch 1. Stop.', 1;

IF COL_LENGTH(N'dbo.account', N'person_id') IS NULL
    THROW 50008, N'account.person_id missing after batch 1. Stop.', 1;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_category_term_catalog' AND object_id = OBJECT_ID(N'dbo.category_term')
)
BEGIN
    CREATE UNIQUE INDEX ux_category_term_catalog
        ON dbo.category_term (category_id, term)
        WHERE person_id IS NULL;
END

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_category_term_personal' AND object_id = OBJECT_ID(N'dbo.category_term')
)
BEGIN
    CREATE UNIQUE INDEX ux_category_term_personal
        ON dbo.category_term (category_id, person_id, term)
        WHERE person_id IS NOT NULL;
END

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_txn_nl_consolidated' AND object_id = OBJECT_ID(N'dbo.transaction_nederland')
)
BEGIN
    CREATE UNIQUE INDEX ux_txn_nl_consolidated
        ON dbo.transaction_nederland (person_id, year, source_id)
        WHERE bank_id IS NULL;
END

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_txn_nl_bank' AND object_id = OBJECT_ID(N'dbo.transaction_nederland')
)
BEGIN
    CREATE UNIQUE INDEX ux_txn_nl_bank
        ON dbo.transaction_nederland (person_id, year, bank_id, source_id)
        WHERE bank_id IS NOT NULL;
END

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_txn_uk_consolidated' AND object_id = OBJECT_ID(N'dbo.transaction_uk')
)
BEGIN
    CREATE UNIQUE INDEX ux_txn_uk_consolidated
        ON dbo.transaction_uk (person_id, year, source_id)
        WHERE bank_id IS NULL;
END

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_txn_uk_bank' AND object_id = OBJECT_ID(N'dbo.transaction_uk')
)
BEGIN
    CREATE UNIQUE INDEX ux_txn_uk_bank
        ON dbo.transaction_uk (person_id, year, bank_id, source_id)
        WHERE bank_id IS NOT NULL;
END

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_category_total_consolidated' AND object_id = OBJECT_ID(N'dbo.category_total')
)
BEGIN
    CREATE UNIQUE INDEX ux_category_total_consolidated
        ON dbo.category_total (person_id, year, category_id)
        WHERE bank_id IS NULL;
END

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_category_total_bank' AND object_id = OBJECT_ID(N'dbo.category_total')
)
BEGIN
    CREATE UNIQUE INDEX ux_category_total_bank
        ON dbo.category_total (person_id, year, bank_id, category_id)
        WHERE bank_id IS NOT NULL;
END
GO

---------------------------------------------------------------------
-- Batch 3: country.name / center.name -> username (sp_rename is a string)
---------------------------------------------------------------------
IF COL_LENGTH(N'dbo.country', N'name') IS NOT NULL
BEGIN
    ALTER TABLE dbo.country DROP CONSTRAINT IF EXISTS ux_country_name;
    EXEC sp_rename N'dbo.country.name', N'username', N'COLUMN';
END

IF COL_LENGTH(N'dbo.center', N'name') IS NOT NULL
BEGIN
    ALTER TABLE dbo.center DROP CONSTRAINT IF EXISTS ux_center_name;
    EXEC sp_rename N'dbo.center.name', N'username', N'COLUMN';
END
GO

---------------------------------------------------------------------
-- Batch 4: unique(username), cross-table check, FKs to dbo.person
---------------------------------------------------------------------
IF COL_LENGTH(N'dbo.country', N'username') IS NULL
    THROW 50009, N'country.username missing after batch 3. Stop.', 1;

IF COL_LENGTH(N'dbo.center', N'username') IS NULL
    THROW 50010, N'center.username missing after batch 3. Stop.', 1;

IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'ux_country_username')
    ALTER TABLE dbo.country ADD CONSTRAINT ux_country_username UNIQUE (username);

IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'ux_center_username')
    ALTER TABLE dbo.center ADD CONSTRAINT ux_center_username UNIQUE (username);

IF EXISTS (
    SELECT username
    FROM (
        SELECT username COLLATE Latin1_General_CI_AI AS username FROM dbo.country
        UNION ALL
        SELECT username COLLATE Latin1_General_CI_AI FROM dbo.center
        UNION ALL
        SELECT username COLLATE Latin1_General_CI_AI FROM dbo.person
    ) x
    GROUP BY username
    HAVING COUNT(*) > 1
)
    THROW 50005, N'username is not unique across country / center / person. Stop.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.person p
    INNER JOIN dbo.center n ON n.center_id = p.center_id
    WHERE p.country_id <> n.country_id
)
    THROW 50006, N'person.country_id does not match center.country_id. Stop.', 1;

IF OBJECT_ID(N'fk_person_country', N'F') IS NULL
    ALTER TABLE dbo.person WITH CHECK ADD CONSTRAINT fk_person_country
        FOREIGN KEY (country_id) REFERENCES dbo.country (country_id);
IF OBJECT_ID(N'fk_person_center', N'F') IS NULL
    ALTER TABLE dbo.person WITH CHECK ADD CONSTRAINT fk_person_center
        FOREIGN KEY (center_id) REFERENCES dbo.center (center_id);
IF OBJECT_ID(N'ck_person_accounts', N'C') IS NULL
    ALTER TABLE dbo.person WITH CHECK ADD CONSTRAINT ck_person_accounts
        CHECK (number_of_accounts >= 0);

IF OBJECT_ID(N'fk_account_person', N'F') IS NULL
    ALTER TABLE dbo.account WITH CHECK ADD CONSTRAINT fk_account_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id);
IF OBJECT_ID(N'fk_category_term_person', N'F') IS NULL
    ALTER TABLE dbo.category_term WITH CHECK ADD CONSTRAINT fk_category_term_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id);
IF OBJECT_ID(N'fk_ct_person', N'F') IS NULL
    ALTER TABLE dbo.category_total WITH CHECK ADD CONSTRAINT fk_ct_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id);
IF OBJECT_ID(N'fk_txn_nl_person', N'F') IS NULL
    ALTER TABLE dbo.transaction_nederland WITH CHECK ADD CONSTRAINT fk_txn_nl_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id);
IF OBJECT_ID(N'fk_txn_uk_person', N'F') IS NULL
    ALTER TABLE dbo.transaction_uk WITH CHECK ADD CONSTRAINT fk_txn_uk_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id);

IF OBJECT_ID(N'dbo.enable_connection', N'U') IS NOT NULL
   AND OBJECT_ID(N'fk_enable_connection_person', N'F') IS NULL
    ALTER TABLE dbo.enable_connection WITH CHECK ADD CONSTRAINT fk_enable_connection_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id);
IF OBJECT_ID(N'dbo.enable_redirect', N'U') IS NOT NULL
   AND OBJECT_ID(N'fk_enable_redirect_person', N'F') IS NULL
    ALTER TABLE dbo.enable_redirect WITH CHECK ADD CONSTRAINT fk_enable_redirect_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id);
IF OBJECT_ID(N'dbo.private_key', N'U') IS NOT NULL
   AND OBJECT_ID(N'fk_private_key_person', N'F') IS NULL
    ALTER TABLE dbo.private_key WITH CHECK ADD CONSTRAINT fk_private_key_person
        FOREIGN KEY (person_id) REFERENCES dbo.person (id);

PRINT N'migrated to dbo.person / country.username / center.username / person_id';
GO
