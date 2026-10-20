-- Rename stored invoice numbers from BDF-{id} to DBF-{id}.
-- invoices.id itself is unchanged; only payments/reminders keep the public string.
--
-- SSMS: connect to database webshop, then execute this file.

USE webshop;
GO

UPDATE dbo.payments
SET invoice_number = STUFF(invoice_number, 1, 3, N'DBF')
WHERE invoice_number LIKE N'BDF-%';
GO

UPDATE dbo.reminders
SET invoice_number = STUFF(invoice_number, 1, 3, N'DBF')
WHERE invoice_number LIKE N'BDF-%';
GO

SELECT N'payments' AS src, invoice_number FROM dbo.payments WHERE invoice_number LIKE N'DBF-%'
UNION ALL
SELECT N'reminders', invoice_number FROM dbo.reminders WHERE invoice_number LIKE N'DBF-%';
GO
