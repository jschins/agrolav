-- Phase C: country / categories / transactions.
-- Drops and recreates these tables inside database agrolav (does not DROP
-- DATABASE). Hub writes stay on JSON until cutover.
-- Run via hub/scripts/load_phase_c.py.
-- To empty tables in SSMS without dropping the database: empty_agrolav.sql.

IF OBJECT_ID(N'dbo.account_balance_file', N'U') IS NOT NULL DROP TABLE dbo.account_balance_file;
IF OBJECT_ID(N'dbo.account_balance', N'U') IS NOT NULL DROP TABLE dbo.account_balance;
IF OBJECT_ID(N'dbo.category_total', N'U') IS NOT NULL DROP TABLE dbo.category_total;
IF OBJECT_ID(N'dbo.[transaction]', N'U') IS NOT NULL DROP TABLE dbo.[transaction];
IF OBJECT_ID(N'dbo.transaction_nederland', N'U') IS NOT NULL DROP TABLE dbo.transaction_nederland;
IF OBJECT_ID(N'dbo.transaction_uk', N'U') IS NOT NULL DROP TABLE dbo.transaction_uk;
IF OBJECT_ID(N'dbo.transaction_stichtingen', N'U') IS NOT NULL DROP TABLE dbo.transaction_stichtingen;
IF OBJECT_ID(N'dbo.category_term', N'U') IS NOT NULL DROP TABLE dbo.category_term;
IF OBJECT_ID(N'dbo.type_abbreviation', N'U') IS NOT NULL DROP TABLE dbo.type_abbreviation;
IF OBJECT_ID(N'dbo.account', N'U') IS NOT NULL DROP TABLE dbo.account;
IF OBJECT_ID(N'dbo.app_user', N'U') IS NOT NULL DROP TABLE dbo.app_user;
IF OBJECT_ID(N'dbo.person', N'U') IS NOT NULL DROP TABLE dbo.person;
IF OBJECT_ID(N'dbo.center', N'U') IS NOT NULL DROP TABLE dbo.center;
IF OBJECT_ID(N'dbo.dim_category', N'U') IS NOT NULL DROP TABLE dbo.dim_category;
IF OBJECT_ID(N'dbo.bank', N'U') IS NOT NULL DROP TABLE dbo.bank;
IF OBJECT_ID(N'dbo.country', N'U') IS NOT NULL DROP TABLE dbo.country;

CREATE TABLE dbo.country (
    country_id INT NOT NULL PRIMARY KEY,
    name NVARCHAR(32) NOT NULL,
    currency_default CHAR(3) NOT NULL,
    CONSTRAINT ux_country_name UNIQUE (name)
);

CREATE TABLE dbo.bank (
    bank_id INT NOT NULL PRIMARY KEY,
    bank_name_official NVARCHAR(64) NOT NULL,
    file_format NVARCHAR(64) NOT NULL,
    CONSTRAINT ux_bank_official UNIQUE (bank_name_official)
);

CREATE TABLE dbo.dim_category (
    category_id INT NOT NULL PRIMARY KEY,
    country_id INT NOT NULL,
    local_code INT NOT NULL,
    label NVARCHAR(128) NOT NULL,
    is_remainder BIT NOT NULL CONSTRAINT df_dim_category_remainder DEFAULT (0),
    matrix_role NVARCHAR(32) NULL,
    CONSTRAINT fk_dim_category_country FOREIGN KEY (country_id) REFERENCES dbo.country (country_id),
    CONSTRAINT ux_dim_category_code UNIQUE (country_id, local_code),
    CONSTRAINT ux_dim_category_label UNIQUE (country_id, label),
    CONSTRAINT ck_dim_category_role CHECK (
        matrix_role IS NULL OR matrix_role IN (N'balance', N'last_booked')
    )
);

CREATE TABLE dbo.center (
    center_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    country_id INT NOT NULL,
    name NVARCHAR(64) NOT NULL,
    CONSTRAINT fk_center_country FOREIGN KEY (country_id) REFERENCES dbo.country (country_id),
    CONSTRAINT ux_center_name UNIQUE (country_id, name)
);


CREATE TABLE dbo.app_user (
    id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    username NVARCHAR(128) COLLATE Latin1_General_CI_AI NOT NULL,
    title NVARCHAR(256) NULL,
    country_id INT NOT NULL,
    center_id INT NULL,
    number_of_accounts INT NULL,
    created_at DATE NOT NULL,
    updated_at DATE NOT NULL,
    CONSTRAINT fk_app_user_country FOREIGN KEY (country_id) REFERENCES dbo.country (country_id),
    CONSTRAINT fk_app_user_center FOREIGN KEY (center_id) REFERENCES dbo.center (center_id),
    CONSTRAINT ck_app_user_pack CHECK (
        number_of_accounts IS NULL
        OR (center_id IS NOT NULL AND number_of_accounts >= 0)
    )
);
CREATE UNIQUE INDEX ux_app_user_username ON dbo.app_user (username);

-- number_of_accounts NULL  → country login (center_id NULL) or center login (center_id set)
-- number_of_accounts NOT NULL → person pack (username is the person folder)
-- format lives on dbo.account (bank csv / secret / excel), not on the login

CREATE TABLE dbo.account (
    account_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    app_user_id INT NOT NULL,
    iban NVARCHAR(64) NOT NULL,
    account_name NVARCHAR(64) NOT NULL,
    format NVARCHAR(64) NULL,
    balance DECIMAL(18, 2) NOT NULL CONSTRAINT df_account_balance DEFAULT (0),
    last_booked DATE NULL,
    CONSTRAINT fk_account_app_user FOREIGN KEY (app_user_id) REFERENCES dbo.app_user (id),
    CONSTRAINT ux_account_iban UNIQUE (app_user_id, iban)
);

CREATE TABLE dbo.category_term (
    term_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    category_id INT NOT NULL,
    app_user_id INT NULL,
    term NVARCHAR(256) NOT NULL,
    sort_order INT NOT NULL,
    CONSTRAINT fk_category_term_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id),
    CONSTRAINT fk_category_term_app_user FOREIGN KEY (app_user_id) REFERENCES dbo.app_user (id)
);

CREATE UNIQUE INDEX ux_category_term_catalog
    ON dbo.category_term (category_id, term)
    WHERE app_user_id IS NULL;

CREATE UNIQUE INDEX ux_category_term_personal
    ON dbo.category_term (category_id, app_user_id, term)
    WHERE app_user_id IS NOT NULL;

CREATE TABLE dbo.type_abbreviation (
    country_id INT NOT NULL,
    bank_type NVARCHAR(64) NOT NULL,
    abbreviation NVARCHAR(16) NOT NULL,
    CONSTRAINT pk_type_abbreviation PRIMARY KEY (country_id, bank_type),
    CONSTRAINT fk_type_abbreviation_country FOREIGN KEY (country_id) REFERENCES dbo.country (country_id)
);

-- One booking table per country folder. Category ids must stay in that
-- country's hundred-block (NL 100-199, UK 200-299).
CREATE TABLE dbo.transaction_nederland (
    transaction_id BIGINT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    app_user_id INT NOT NULL,
    account_id INT NOT NULL,
    year SMALLINT NOT NULL,
    bank_id INT NULL,
    source_id NVARCHAR(128) NOT NULL,
    amount DECIMAL(18, 2) NOT NULL,
    bank_type NVARCHAR(64) NULL,
    counterparty_name NVARCHAR(512) NULL,
    counterparty_iban NVARCHAR(64) NULL,
    description NVARCHAR(MAX) NULL,
    booked_on DATE NOT NULL,
    category_id INT NOT NULL,
    modification SMALLINT NOT NULL CONSTRAINT df_txn_nl_mod DEFAULT (-1),
    hit NVARCHAR(64) NULL,
    CONSTRAINT fk_txn_nl_app_user FOREIGN KEY (app_user_id) REFERENCES dbo.app_user (id),
    CONSTRAINT fk_txn_nl_account FOREIGN KEY (account_id) REFERENCES dbo.account (account_id),
    CONSTRAINT fk_txn_nl_bank FOREIGN KEY (bank_id) REFERENCES dbo.bank (bank_id),
    CONSTRAINT fk_txn_nl_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id),
    CONSTRAINT ck_txn_nl_year CHECK (year >= 1990 AND year <= 2100),
    CONSTRAINT ck_txn_nl_mod CHECK (modification IN (-1, 0, 1, 2, 3)),
    CONSTRAINT ck_txn_nl_cat CHECK (category_id BETWEEN 100 AND 199)
);

CREATE UNIQUE INDEX ux_txn_nl_consolidated
    ON dbo.transaction_nederland (app_user_id, year, source_id)
    WHERE bank_id IS NULL;

CREATE UNIQUE INDEX ux_txn_nl_bank
    ON dbo.transaction_nederland (app_user_id, year, bank_id, source_id)
    WHERE bank_id IS NOT NULL;

CREATE TABLE dbo.transaction_uk (
    transaction_id BIGINT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    app_user_id INT NOT NULL,
    account_id INT NOT NULL,
    year SMALLINT NOT NULL,
    bank_id INT NULL,
    source_id NVARCHAR(128) NOT NULL,
    amount DECIMAL(18, 2) NOT NULL,
    bank_type NVARCHAR(64) NULL,
    counterparty_name NVARCHAR(512) NULL,
    counterparty_iban NVARCHAR(64) NULL,
    description NVARCHAR(MAX) NULL,
    booked_on DATE NOT NULL,
    category_id INT NOT NULL,
    modification SMALLINT NOT NULL CONSTRAINT df_txn_uk_mod DEFAULT (-1),
    hit NVARCHAR(64) NULL,
    CONSTRAINT fk_txn_uk_app_user FOREIGN KEY (app_user_id) REFERENCES dbo.app_user (id),
    CONSTRAINT fk_txn_uk_account FOREIGN KEY (account_id) REFERENCES dbo.account (account_id),
    CONSTRAINT fk_txn_uk_bank FOREIGN KEY (bank_id) REFERENCES dbo.bank (bank_id),
    CONSTRAINT fk_txn_uk_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id),
    CONSTRAINT ck_txn_uk_year CHECK (year >= 1990 AND year <= 2100),
    CONSTRAINT ck_txn_uk_mod CHECK (modification IN (-1, 0, 1, 2, 3)),
    CONSTRAINT ck_txn_uk_cat CHECK (category_id BETWEEN 200 AND 299)
);

CREATE UNIQUE INDEX ux_txn_uk_consolidated
    ON dbo.transaction_uk (app_user_id, year, source_id)
    WHERE bank_id IS NULL;

CREATE UNIQUE INDEX ux_txn_uk_bank
    ON dbo.transaction_uk (app_user_id, year, bank_id, source_id)
    WHERE bank_id IS NOT NULL;


CREATE TABLE dbo.category_total (
    category_total_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    app_user_id INT NOT NULL,
    year SMALLINT NOT NULL,
    bank_id INT NULL,
    category_id INT NOT NULL,
    amount DECIMAL(18, 2) NOT NULL,
    CONSTRAINT fk_ct_app_user FOREIGN KEY (app_user_id) REFERENCES dbo.app_user (id),
    CONSTRAINT fk_ct_bank FOREIGN KEY (bank_id) REFERENCES dbo.bank (bank_id),
    CONSTRAINT fk_ct_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id)
);

CREATE UNIQUE INDEX ux_category_total_consolidated
    ON dbo.category_total (app_user_id, year, category_id)
    WHERE bank_id IS NULL;

CREATE UNIQUE INDEX ux_category_total_bank
    ON dbo.category_total (app_user_id, year, bank_id, category_id)
    WHERE bank_id IS NOT NULL;

CREATE TABLE dbo.account_balance_file (
    account_balance_file_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    account_id INT NOT NULL,
    file_name NVARCHAR(256) NOT NULL,
    format NVARCHAR(64) NULL,
    CONSTRAINT fk_abf_balance FOREIGN KEY (account_id) REFERENCES dbo.account (account_id)
);
