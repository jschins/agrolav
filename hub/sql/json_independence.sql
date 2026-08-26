-- Tables still needed after phase_c.sql to stop depending on workspace JSON.
-- Does not DROP existing tables. Run against database agrolav in SSMS.
-- Private key PEM files stay on disk (not JSON, not SQL).
--
-- Already created by phase_c.sql (do not recreate here):
--   country, bank, dim_category, center, app_user, account,
--   category_term (general app_user_id NULL + personal app_user_id set),
--   type_abbreviation, transaction_nederland, transaction_uk,
--   category_total, account_balance_file
--
-- JSON these tables replace:
--   categories.json table_header_terms  -> dbo.table_header_term
--   categories.json typerules           -> dbo.type_rule
--   upload_acl.json bank modalities     -> dbo.bank_modality
--   upload_acl.json hub_ips             -> dbo.hub_ip
--   secret/profile.json + consent.json  -> dbo.enable_connection
--                                         dbo.enable_account
--                                         dbo.enable_redirect
--   category_totals.json account uid    -> dbo.enable_account.uid

USE agrolav
GO

IF OBJECT_ID(N'dbo.table_header_term', N'U') IS NULL
CREATE TABLE dbo.table_header_term (
    country_id INT NOT NULL,
    term_key NVARCHAR(64) NOT NULL,
    label NVARCHAR(128) NOT NULL,
    CONSTRAINT pk_table_header_term PRIMARY KEY (country_id, term_key),
    CONSTRAINT fk_table_header_term_country FOREIGN KEY (country_id)
        REFERENCES dbo.country (country_id)
)
GO

IF OBJECT_ID(N'dbo.type_rule', N'U') IS NULL
CREATE TABLE dbo.type_rule (
    country_id INT NOT NULL,
    bank_type NVARCHAR(64) NOT NULL,
    category_id INT NOT NULL,
    CONSTRAINT pk_type_rule PRIMARY KEY (country_id, bank_type),
    CONSTRAINT fk_type_rule_country FOREIGN KEY (country_id)
        REFERENCES dbo.country (country_id),
    CONSTRAINT fk_type_rule_category FOREIGN KEY (category_id)
        REFERENCES dbo.dim_category (category_id)
)
GO

IF OBJECT_ID(N'dbo.bank_modality', N'U') IS NULL
CREATE TABLE dbo.bank_modality (
    folder_name NVARCHAR(64) NOT NULL,
    bank_id INT NOT NULL,
    CONSTRAINT pk_bank_modality PRIMARY KEY (folder_name),
    CONSTRAINT fk_bank_modality_bank FOREIGN KEY (bank_id)
        REFERENCES dbo.bank (bank_id)
)
GO

IF OBJECT_ID(N'dbo.hub_ip', N'U') IS NULL
CREATE TABLE dbo.hub_ip (
    ip NVARCHAR(64) NOT NULL,
    CONSTRAINT pk_hub_ip PRIMARY KEY (ip)
)
GO

IF OBJECT_ID(N'dbo.enable_connection', N'U') IS NULL
CREATE TABLE dbo.enable_connection (
    connection_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    app_user_id INT NOT NULL,
    app_id NVARCHAR(128) NULL,
    aspsp NVARCHAR(64) NOT NULL,
    country_iso CHAR(2) NOT NULL,
    session_id NVARCHAR(256) NULL,
    valid_until DATETIME2 NULL,
    created_at DATETIME2 NULL,
    CONSTRAINT fk_enable_connection_user FOREIGN KEY (app_user_id)
        REFERENCES dbo.app_user (id),
    CONSTRAINT ux_enable_connection UNIQUE (app_user_id, aspsp, country_iso)
)
GO

IF OBJECT_ID(N'dbo.enable_account', N'U') IS NULL
CREATE TABLE dbo.enable_account (
    enable_account_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    connection_id INT NOT NULL,
    account_id INT NULL,
    uid NVARCHAR(128) NOT NULL,
    enabled BIT NOT NULL CONSTRAINT df_enable_account_enabled DEFAULT (1),
    identification_hash NVARCHAR(128) NULL,
    currency CHAR(3) NULL,
    CONSTRAINT fk_enable_account_connection FOREIGN KEY (connection_id)
        REFERENCES dbo.enable_connection (connection_id),
    CONSTRAINT fk_enable_account_account FOREIGN KEY (account_id)
        REFERENCES dbo.account (account_id),
    CONSTRAINT ux_enable_account_uid UNIQUE (connection_id, uid)
)
GO

IF OBJECT_ID(N'dbo.enable_redirect', N'U') IS NULL
CREATE TABLE dbo.enable_redirect (
    app_user_id INT NOT NULL PRIMARY KEY,
    last_redirect_input NVARCHAR(MAX) NULL,
    last_redirect_code NVARCHAR(256) NULL,
    last_redirect_code_at DATETIME2 NULL,
    CONSTRAINT fk_enable_redirect_user FOREIGN KEY (app_user_id)
        REFERENCES dbo.app_user (id)
)
GO
