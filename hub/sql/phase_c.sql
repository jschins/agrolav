-- Phase C: country / categories / transactions.
-- Drops and recreates these tables inside database agrolav (does not DROP
-- DATABASE). Hub writes stay on JSON until cutover.
-- Run via hub/scripts/load_phase_c.py.
-- Live databases already loaded: run hub/sql/migrate_person.sql instead
-- (load_phase_c.py would wipe bookings).
-- To empty tables in SSMS without dropping the database: empty_agrolav.sql.
--
-- Logins:
--   dbo.country.username  — country folder
--   dbo.center.username   — center folder, unique across all countries
--   dbo.person.username   — person folder
-- Usernames must not overlap the three tables (enforced in the hub, not SQL).

IF OBJECT_ID(N'dbo.v_account_connection_person', N'V') IS NOT NULL DROP VIEW dbo.v_account_connection_person;
IF OBJECT_ID(N'dbo.enable_account', N'U') IS NOT NULL DROP TABLE dbo.enable_account;
IF OBJECT_ID(N'dbo.enable_redirect', N'U') IS NOT NULL DROP TABLE dbo.enable_redirect;
IF OBJECT_ID(N'dbo.private_key', N'U') IS NOT NULL DROP TABLE dbo.private_key;
IF OBJECT_ID(N'dbo.enable_connection', N'U') IS NOT NULL DROP TABLE dbo.enable_connection;
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
IF OBJECT_ID(N'dbo.type_rule', N'U') IS NOT NULL DROP TABLE dbo.type_rule;
IF OBJECT_ID(N'dbo.table_header_term', N'U') IS NOT NULL DROP TABLE dbo.table_header_term;
IF OBJECT_ID(N'dbo.bank_modality', N'U') IS NOT NULL DROP TABLE dbo.bank_modality;
IF OBJECT_ID(N'dbo.hub_ip', N'U') IS NOT NULL DROP TABLE dbo.hub_ip;
IF OBJECT_ID(N'dbo.dim_category', N'U') IS NOT NULL DROP TABLE dbo.dim_category;
IF OBJECT_ID(N'dbo.bank', N'U') IS NOT NULL DROP TABLE dbo.bank;
IF OBJECT_ID(N'dbo.country', N'U') IS NOT NULL DROP TABLE dbo.country;

CREATE TABLE dbo.country (
    country_id INT NOT NULL PRIMARY KEY,
    username NVARCHAR(32) NOT NULL,
    title NVARCHAR(256) NOT NULL,
    currency_default CHAR(3) NOT NULL,
    CONSTRAINT ux_country_username UNIQUE (username)
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
    username NVARCHAR(64) NOT NULL,
    title NVARCHAR(256) NOT NULL,
    CONSTRAINT fk_center_country FOREIGN KEY (country_id) REFERENCES dbo.country (country_id),
    CONSTRAINT ux_center_username UNIQUE (username)
);

CREATE TABLE dbo.person (
    id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    username NVARCHAR(128) COLLATE Latin1_General_CI_AI NOT NULL,
    title NVARCHAR(256) NOT NULL,
    country_id INT NOT NULL,
    center_id INT NOT NULL,
    number_of_accounts INT NOT NULL CONSTRAINT df_person_accounts DEFAULT (0),
    created_at DATE NOT NULL,
    updated_at DATE NOT NULL,
    CONSTRAINT fk_person_country FOREIGN KEY (country_id) REFERENCES dbo.country (country_id),
    CONSTRAINT fk_person_center FOREIGN KEY (center_id) REFERENCES dbo.center (center_id),
    CONSTRAINT ck_person_accounts CHECK (number_of_accounts >= 0)
);
CREATE UNIQUE INDEX ux_person_username ON dbo.person (username);

-- format lives on dbo.account (csv layout / Enable ASPSP / excel), not on the login.
-- Bank-connected accounts share enable_connection; Excel accounts leave
-- connection_id / uid / identification_hash NULL.

CREATE TABLE dbo.enable_connection (
    connection_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    app_id NVARCHAR(128) NULL,
    session_id NVARCHAR(256) NULL,
    valid_until DATETIME2 NULL,
    created_at DATETIME2 NULL,
    pem NVARCHAR(MAX) NULL
);

CREATE TABLE dbo.account (
    account_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    person_id INT NOT NULL,
    iban NVARCHAR(64) NOT NULL,
    account_name NVARCHAR(64) NOT NULL,
    format NVARCHAR(64) NULL,
    balance DECIMAL(18, 2) NOT NULL CONSTRAINT df_account_balance DEFAULT (0),
    last_booked DATE NULL,
    connection_id INT NULL,
    uid NVARCHAR(128) NULL,
    identification_hash NVARCHAR(128) NULL,
    CONSTRAINT fk_account_person FOREIGN KEY (person_id) REFERENCES dbo.person (id),
    CONSTRAINT fk_account_connection FOREIGN KEY (connection_id)
        REFERENCES dbo.enable_connection (connection_id),
    CONSTRAINT ux_account_iban UNIQUE (person_id, iban),
    CONSTRAINT ck_account_connection_uid CHECK (
        (connection_id IS NULL AND uid IS NULL)
        OR (connection_id IS NOT NULL AND uid IS NOT NULL)
    )
);

CREATE UNIQUE INDEX ux_account_uid ON dbo.account (uid) WHERE uid IS NOT NULL;

CREATE VIEW dbo.v_account_connection_person
WITH SCHEMABINDING
AS
SELECT connection_id, person_id, COUNT_BIG(*) AS account_count
FROM dbo.account
WHERE connection_id IS NOT NULL
GROUP BY connection_id, person_id;

CREATE UNIQUE CLUSTERED INDEX ux_v_connection_one_person
    ON dbo.v_account_connection_person (connection_id);

CREATE TABLE dbo.category_term (
    term_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    category_id INT NOT NULL,
    person_id INT NULL,
    term NVARCHAR(256) NOT NULL,
    sort_order INT NOT NULL,
    CONSTRAINT fk_category_term_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id),
    CONSTRAINT fk_category_term_person FOREIGN KEY (person_id) REFERENCES dbo.person (id)
);

CREATE UNIQUE INDEX ux_category_term_catalog
    ON dbo.category_term (category_id, term)
    WHERE person_id IS NULL;

CREATE UNIQUE INDEX ux_category_term_personal
    ON dbo.category_term (category_id, person_id, term)
    WHERE person_id IS NOT NULL;

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
    person_id INT NOT NULL,
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
    CONSTRAINT fk_txn_nl_person FOREIGN KEY (person_id) REFERENCES dbo.person (id),
    CONSTRAINT fk_txn_nl_account FOREIGN KEY (account_id) REFERENCES dbo.account (account_id),
    CONSTRAINT fk_txn_nl_bank FOREIGN KEY (bank_id) REFERENCES dbo.bank (bank_id),
    CONSTRAINT fk_txn_nl_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id),
    CONSTRAINT ck_txn_nl_year CHECK (year >= 1990 AND year <= 2100),
    CONSTRAINT ck_txn_nl_mod CHECK (modification IN (-1, 0, 1, 2, 3)),
    CONSTRAINT ck_txn_nl_cat CHECK (category_id BETWEEN 100 AND 199)
);

CREATE UNIQUE INDEX ux_txn_nl_consolidated
    ON dbo.transaction_nederland (person_id, year, source_id)
    WHERE bank_id IS NULL;

CREATE UNIQUE INDEX ux_txn_nl_bank
    ON dbo.transaction_nederland (person_id, year, bank_id, source_id)
    WHERE bank_id IS NOT NULL;

CREATE TABLE dbo.transaction_uk (
    transaction_id BIGINT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    person_id INT NOT NULL,
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
    CONSTRAINT fk_txn_uk_person FOREIGN KEY (person_id) REFERENCES dbo.person (id),
    CONSTRAINT fk_txn_uk_account FOREIGN KEY (account_id) REFERENCES dbo.account (account_id),
    CONSTRAINT fk_txn_uk_bank FOREIGN KEY (bank_id) REFERENCES dbo.bank (bank_id),
    CONSTRAINT fk_txn_uk_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id),
    CONSTRAINT ck_txn_uk_year CHECK (year >= 1990 AND year <= 2100),
    CONSTRAINT ck_txn_uk_mod CHECK (modification IN (-1, 0, 1, 2, 3)),
    CONSTRAINT ck_txn_uk_cat CHECK (category_id BETWEEN 200 AND 299)
);

CREATE UNIQUE INDEX ux_txn_uk_consolidated
    ON dbo.transaction_uk (person_id, year, source_id)
    WHERE bank_id IS NULL;

CREATE UNIQUE INDEX ux_txn_uk_bank
    ON dbo.transaction_uk (person_id, year, bank_id, source_id)
    WHERE bank_id IS NOT NULL;

CREATE TABLE dbo.category_total (
    category_total_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    person_id INT NOT NULL,
    year SMALLINT NOT NULL,
    bank_id INT NULL,
    category_id INT NOT NULL,
    amount DECIMAL(18, 2) NOT NULL,
    CONSTRAINT fk_ct_person FOREIGN KEY (person_id) REFERENCES dbo.person (id),
    CONSTRAINT fk_ct_bank FOREIGN KEY (bank_id) REFERENCES dbo.bank (bank_id),
    CONSTRAINT fk_ct_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id)
);

CREATE UNIQUE INDEX ux_category_total_consolidated
    ON dbo.category_total (person_id, year, category_id)
    WHERE bank_id IS NULL;

CREATE UNIQUE INDEX ux_category_total_bank
    ON dbo.category_total (person_id, year, bank_id, category_id)
    WHERE bank_id IS NOT NULL;

CREATE TABLE dbo.account_balance_file (
    account_balance_file_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    account_id INT NOT NULL,
    file_name NVARCHAR(256) NOT NULL,
    format NVARCHAR(64) NULL,
    CONSTRAINT fk_abf_balance FOREIGN KEY (account_id) REFERENCES dbo.account (account_id)
);
