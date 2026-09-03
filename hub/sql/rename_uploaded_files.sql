-- Rename dbo.account_balance_file → dbo.uploaded_files
-- and account_balance_file_id → uploaded_file_id.
-- Idempotent. Run on local and remote so they stay identical.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.account_balance_file', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.uploaded_files', N'U') IS NULL
    EXEC sp_rename N'dbo.account_balance_file', N'uploaded_files';
GO

IF COL_LENGTH(N'dbo.uploaded_files', N'account_balance_file_id') IS NOT NULL
   AND COL_LENGTH(N'dbo.uploaded_files', N'uploaded_file_id') IS NULL
    EXEC sp_rename N'dbo.uploaded_files.account_balance_file_id', N'uploaded_file_id', N'COLUMN';
GO
