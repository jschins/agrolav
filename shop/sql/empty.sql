-- Empty every shop table and reset the counters, so a fresh run starts clean.
-- The schema is left untouched; only rows are removed. Children are deleted first.
-- Run the whole file with app/run_sql.py, or paste it into SSMS on the webshop database.
USE webshop;
GO

DELETE FROM dbo.orderlines;
GO
DELETE FROM dbo.orders;
GO
DELETE FROM dbo.payments;
GO
DELETE FROM dbo.bookings;
GO
DELETE FROM dbo.reminders;
GO
DELETE FROM dbo.invoicelines;
GO
DELETE FROM dbo.invoices;
GO
DELETE FROM dbo.customers;
GO
DELETE FROM dbo.debtors;
GO
DELETE FROM dbo.address;
GO
DELETE FROM dbo.stock;
GO

-- Invoice ids (also debtor order ids) count from 100000; other counters start at 1.
-- On an emptied table the first next value is one past the number given, hence n-1.
DBCC CHECKIDENT (N'dbo.invoices', RESEED, 99999);
GO
DBCC CHECKIDENT (N'dbo.address', RESEED, 0);
GO
DBCC CHECKIDENT (N'dbo.debtors', RESEED, 0);
GO
DBCC CHECKIDENT (N'dbo.customers', RESEED, 0);
GO
DBCC CHECKIDENT (N'dbo.orderlines', RESEED, 0);
GO
DBCC CHECKIDENT (N'dbo.invoicelines', RESEED, 0);
GO
DBCC CHECKIDENT (N'dbo.payments', RESEED, 0);
GO
DBCC CHECKIDENT (N'dbo.reminders', RESEED, 0);
GO
