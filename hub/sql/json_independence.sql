-- Tables still needed after phase_c.sql to stop depending on the hub's JSON data.
-- Does not DROP existing tables. Run against database agrolav in SSMS.
--
-- Already created by phase_c.sql (do not recreate here):
--   country, bank, dim_category, center, person, account,
--   category_term (catalog person_id NULL + personal person_id set),
--   type_abbreviation, transaction_nederland, transaction_uk,
--   category_total, uploaded_files
--
-- JSON / files these tables replace:
--   categories.json table_header_terms  -> dbo.country.language_id
--                                         dbo.language (term_lang1, term_lang2, …)
--   upload_acl.json bank modalities     -> dbo.bank_modality
--   upload_acl.json hub_ips             -> (removed; country/center.egress_ip + dbo.visitor_ip)
--   secret/profile.json + consent.json  -> dbo.enable_connection
--                                         dbo.account (uid, hash, connection_id, format=aspsp)
--                                         dbo.enable_redirect
--   secret/*.pem                        -> dbo.enable_connection.pem

USE agrolav
GO

IF COL_LENGTH(N'dbo.country', N'language_id') IS NULL
ALTER TABLE dbo.country ADD language_id INT NOT NULL
    CONSTRAINT df_country_language_id DEFAULT (1)
GO

IF OBJECT_ID(N'dbo.language', N'U') IS NULL
CREATE TABLE dbo.language (
    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    term_lang1 VARCHAR(64) NOT NULL,
    term_lang2 VARCHAR(64) NOT NULL,
    CONSTRAINT uq_language_term_lang1 UNIQUE (term_lang1),
    CONSTRAINT uq_language_term_lang2 UNIQUE (term_lang2)
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

IF OBJECT_ID(N'dbo.visitor_ip', N'U') IS NULL
CREATE TABLE dbo.visitor_ip (
    visitor_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    egress_ip VARCHAR(45) NOT NULL,
    username VARCHAR(64) NOT NULL
        CONSTRAINT df_visitor_ip_username DEFAULT '',
    CONSTRAINT ux_visitor_ip_ip_user UNIQUE (egress_ip, username)
)
GO

IF OBJECT_ID(N'dbo.enable_connection', N'U') IS NULL
CREATE TABLE dbo.enable_connection (
    connection_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    person_id INT NULL,
    app_id NVARCHAR(128) NULL,
    session_id NVARCHAR(256) NULL,
    valid_until DATETIME2 NULL,
    created_at DATETIME2 NULL,
    pem NVARCHAR(MAX) NULL,
    CONSTRAINT fk_enable_connection_person FOREIGN KEY (person_id)
        REFERENCES dbo.person (id)
)
GO

IF OBJECT_ID(N'dbo.enable_redirect', N'U') IS NULL
CREATE TABLE dbo.enable_redirect (
    person_id INT NOT NULL PRIMARY KEY,
    last_redirect_input NVARCHAR(MAX) NULL,
    last_redirect_code NVARCHAR(256) NULL,
    last_redirect_code_at DATETIME2 NULL,
    CONSTRAINT fk_enable_redirect_person FOREIGN KEY (person_id)
        REFERENCES dbo.person (id)
)
GO
