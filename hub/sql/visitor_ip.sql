-- Country/center login allowlists + visitor log.
-- Idempotent. You run this on local and remote so they stay identical.
--
-- SSMS: connect to database agrolav, then execute this file.
--
-- egress_ip is the "egress-IP" allowlist (comma-separated). Empty/NULL admits
-- nothing: a country/center login needs its address here or in dbo.administrator
-- (see administrator.sql), and the allowed set is the sum of the two.
-- dbo.hub_ip is replaced by dbo.visitor_ip. Login posts (login_page = 1) are
-- written immediately; other HTTP hits (login_page = 0) at most once per UTC
-- day. Drop hub_ip yourself after this succeeds, when you are ready.

USE agrolav;
GO

IF COL_LENGTH(N'dbo.country', N'egress_ip') IS NULL
    ALTER TABLE dbo.country ADD egress_ip VARCHAR(256) NULL;
GO

IF COL_LENGTH(N'dbo.center', N'egress_ip') IS NULL
    ALTER TABLE dbo.center ADD egress_ip VARCHAR(256) NULL;
GO

IF OBJECT_ID(N'dbo.visitor_ip', N'U') IS NULL
CREATE TABLE dbo.visitor_ip (
    visitor_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    egress_ip VARCHAR(45) NOT NULL,
    username VARCHAR(64) NOT NULL
        CONSTRAINT df_visitor_ip_username DEFAULT '',
    login_page BIT NOT NULL
        CONSTRAINT df_visitor_ip_login_page DEFAULT 1,
    number_of_attempts INT NOT NULL
        CONSTRAINT df_visitor_ip_attempts DEFAULT 1,
    first_seen DATETIME2 NOT NULL
        CONSTRAINT df_visitor_ip_first_seen DEFAULT SYSUTCDATETIME(),
    last_seen DATETIME2 NOT NULL
        CONSTRAINT df_visitor_ip_last_seen DEFAULT SYSUTCDATETIME(),
    last_status SMALLINT NULL,
    last_path VARCHAR(256) NOT NULL
        CONSTRAINT df_visitor_ip_last_path DEFAULT '',
    CONSTRAINT ux_visitor_ip_ip_user_page UNIQUE (egress_ip, username, login_page)
);
GO

-- 45 characters, not 32: a compressed IPv6 address runs to 39 and was being
-- stored truncated. Widening a VARCHAR needs no index rebuild.
IF COL_LENGTH(N'dbo.visitor_ip', N'egress_ip') < 45
    ALTER TABLE dbo.visitor_ip ALTER COLUMN egress_ip VARCHAR(45) NOT NULL;
GO

-- A refused login now writes username = '' instead of NULL, so one condition
-- is enough: UNIQUE (egress_ip, username). The filtered index below used to
-- add "at most one anonymous row per IP", which SQL Server already enforced
-- (it compares NULLs as equal, so a UNIQUE index admits only one of them).
-- Drop it first: a column named in a filtered index predicate cannot be
-- altered while the index exists.
IF EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'ux_visitor_ip_anon'
          AND object_id = OBJECT_ID(N'dbo.visitor_ip')
   )
    DROP INDEX ux_visitor_ip_anon ON dbo.visitor_ip;
GO

-- An IP with both a NULL row and an '' row would collide once NULL becomes '',
-- so drop the redundant NULL row before collapsing the rest.
DELETE anon
FROM dbo.visitor_ip AS anon
WHERE anon.username IS NULL
  AND EXISTS (
        SELECT 1 FROM dbo.visitor_ip AS named
        WHERE named.egress_ip = anon.egress_ip
          AND named.username = ''
  );
GO

UPDATE dbo.visitor_ip SET username = '' WHERE username IS NULL;
GO

-- Unique indexes/constraints on username must go before ALTER COLUMN.
IF EXISTS (
        SELECT 1 FROM sys.key_constraints
        WHERE name = N'ux_visitor_ip_egress_user'
          AND parent_object_id = OBJECT_ID(N'dbo.visitor_ip')
)
    ALTER TABLE dbo.visitor_ip DROP CONSTRAINT ux_visitor_ip_egress_user;
GO

IF EXISTS (
        SELECT 1 FROM sys.key_constraints
        WHERE name = N'ux_visitor_ip_ip_user'
          AND parent_object_id = OBJECT_ID(N'dbo.visitor_ip')
)
    ALTER TABLE dbo.visitor_ip DROP CONSTRAINT ux_visitor_ip_ip_user;
GO

IF EXISTS (
        SELECT 1 FROM sys.key_constraints
        WHERE name = N'ux_visitor_ip_ip_user_page'
          AND parent_object_id = OBJECT_ID(N'dbo.visitor_ip')
)
    ALTER TABLE dbo.visitor_ip DROP CONSTRAINT ux_visitor_ip_ip_user_page;
GO

IF COLUMNPROPERTY(OBJECT_ID(N'dbo.visitor_ip'), N'username', 'AllowsNull') = 1
    ALTER TABLE dbo.visitor_ip ALTER COLUMN username VARCHAR(64) NOT NULL;
GO

IF NOT EXISTS (
        SELECT 1 FROM sys.default_constraints
        WHERE name = N'df_visitor_ip_username'
          AND parent_object_id = OBJECT_ID(N'dbo.visitor_ip')
   )
    ALTER TABLE dbo.visitor_ip
        ADD CONSTRAINT df_visitor_ip_username DEFAULT '' FOR username;
GO

-- Existing rows are login attempts. Default 1 so the unique key can widen.
IF COL_LENGTH(N'dbo.visitor_ip', N'login_page') IS NULL
    ALTER TABLE dbo.visitor_ip ADD login_page BIT NOT NULL
        CONSTRAINT df_visitor_ip_login_page DEFAULT 1;
GO

IF COL_LENGTH(N'dbo.visitor_ip', N'number_of_attempts') IS NULL
    ALTER TABLE dbo.visitor_ip ADD number_of_attempts INT NOT NULL
        CONSTRAINT df_visitor_ip_attempts DEFAULT 1;
GO

IF COL_LENGTH(N'dbo.visitor_ip', N'first_seen') IS NULL
    ALTER TABLE dbo.visitor_ip ADD first_seen DATETIME2 NOT NULL
        CONSTRAINT df_visitor_ip_first_seen DEFAULT SYSUTCDATETIME();
GO

IF COL_LENGTH(N'dbo.visitor_ip', N'last_seen') IS NULL
    ALTER TABLE dbo.visitor_ip ADD last_seen DATETIME2 NOT NULL
        CONSTRAINT df_visitor_ip_last_seen DEFAULT SYSUTCDATETIME();
GO

IF COL_LENGTH(N'dbo.visitor_ip', N'last_status') IS NULL
    ALTER TABLE dbo.visitor_ip ADD last_status SMALLINT NULL;
GO

IF COL_LENGTH(N'dbo.visitor_ip', N'last_path') IS NULL
    ALTER TABLE dbo.visitor_ip ADD last_path VARCHAR(256) NOT NULL
        CONSTRAINT df_visitor_ip_last_path DEFAULT '';
GO

IF NOT EXISTS (
        SELECT 1 FROM sys.key_constraints
        WHERE name = N'ux_visitor_ip_ip_user_page'
          AND parent_object_id = OBJECT_ID(N'dbo.visitor_ip')
)
    ALTER TABLE dbo.visitor_ip
        ADD CONSTRAINT ux_visitor_ip_ip_user_page
        UNIQUE (egress_ip, username, login_page);
GO
