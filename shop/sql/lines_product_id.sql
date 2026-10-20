-- Replace slug with product_id FK → dbo.paper_books on line tables.
-- Table names are dbo.invoicelines / dbo.orderlines (no underscore).
-- Line rows must be empty (or are cleared here) before NOT NULL product_id is added.
--
-- SSMS: connect to database webshop, then execute this file.
-- After this, run:  shop\.venv\Scripts\python.exe scripts\load_paper_books.py

USE webshop;
GO

DELETE FROM dbo.orderlines;
GO
DELETE FROM dbo.invoicelines;
GO

IF COL_LENGTH(N'dbo.invoicelines', N'slug') IS NOT NULL
    ALTER TABLE dbo.invoicelines DROP COLUMN slug;
GO

IF COL_LENGTH(N'dbo.orderlines', N'slug') IS NOT NULL
    ALTER TABLE dbo.orderlines DROP COLUMN slug;
GO

IF COL_LENGTH(N'dbo.invoicelines', N'product_id') IS NULL
    ALTER TABLE dbo.invoicelines ADD product_id INT NOT NULL;
GO

IF COL_LENGTH(N'dbo.orderlines', N'product_id') IS NULL
    ALTER TABLE dbo.orderlines ADD product_id INT NOT NULL;
GO

IF OBJECT_ID(N'dbo.fk_invoicelines_paper_books', N'F') IS NULL
    ALTER TABLE dbo.invoicelines
        ADD CONSTRAINT fk_invoicelines_paper_books
        FOREIGN KEY (product_id) REFERENCES dbo.paper_books (product_id);
GO

IF OBJECT_ID(N'dbo.fk_orderlines_paper_books', N'F') IS NULL
    ALTER TABLE dbo.orderlines
        ADD CONSTRAINT fk_orderlines_paper_books
        FOREIGN KEY (product_id) REFERENCES dbo.paper_books (product_id);
GO

SELECT N'invoicelines' AS tbl, c.name, t.name AS type_name
FROM sys.columns c
JOIN sys.types t ON c.user_type_id = t.user_type_id
WHERE c.object_id = OBJECT_ID(N'dbo.invoicelines')
UNION ALL
SELECT N'orderlines', c.name, t.name
FROM sys.columns c
JOIN sys.types t ON c.user_type_id = t.user_type_id
WHERE c.object_id = OBJECT_ID(N'dbo.orderlines')
ORDER BY tbl, name;
GO
