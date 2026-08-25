-- Phase B: login rows only. Run against database agrolav.
IF OBJECT_ID(N'dbo.app_user', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.app_user (
        id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
        username NVARCHAR(128) COLLATE Latin1_General_CI_AI NOT NULL,
        title NVARCHAR(256) NULL,
        country NVARCHAR(32) NULL,
        center NVARCHAR(64) NULL,
        person NVARCHAR(128) NULL,
        format NVARCHAR(64) NULL,
        created_at DATE NOT NULL,
        updated_at DATE NOT NULL
    );
    CREATE UNIQUE INDEX ux_app_user_username ON dbo.app_user (username);
END;
GO
