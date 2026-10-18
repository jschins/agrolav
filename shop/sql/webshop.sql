-- webshop: the shop's own database, a sibling of agrolav on the same server.
-- Tables carry no "shop_" prefix.
--
-- Two kinds of buyer share one dbo.address row:
--   debtors   -- companies buying on account; they have orders and invoices.
--   customers -- buyers paying online through Mollie; they have invoices only.
--
--   orders   : written the moment an account buyer orders on the website.
--   invoices : for a debtor, written alongside the order; for a customer,
--              written and paid at Mollie checkout.
--
-- Idempotent. Run once with an account allowed to create a database.
-- SSMS: connect to the server, then execute this file.

IF DB_ID(N'webshop') IS NULL
    EXEC(N'CREATE DATABASE webshop');
GO

USE webshop;
GO

-- One postal address, shared by debtors and customers.
IF OBJECT_ID(N'dbo.address', N'U') IS NULL
CREATE TABLE dbo.address (
    id          int             IDENTITY(1,1) NOT NULL,
    street      nvarchar(max)   NOT NULL,
    [number]    nvarchar(max)   NOT NULL,   -- text: "12", "12a", "12-3"
    postalcode  nvarchar(max)   NOT NULL,
    city        nvarchar(max)   NOT NULL,
    CONSTRAINT pk_address PRIMARY KEY (id)
);
GO

-- Account buyers. Both orders and invoices hang off a debtor.
IF OBJECT_ID(N'dbo.debtors', N'U') IS NULL
CREATE TABLE dbo.debtors (
    id          int             IDENTITY(1,1) NOT NULL,
    name        nvarchar(max)   NOT NULL,
    email       nvarchar(max)   NOT NULL,
    vat_number  nvarchar(max)   NOT NULL,
    code        nvarchar(max)   NOT NULL,   -- bestelcode: ship before payment
    address_id  int             NULL,
    iban        nvarchar(64)    NULL,       -- bank IBAN used to identify their payments
    CONSTRAINT pk_debtors PRIMARY KEY (id),
    CONSTRAINT fk_debtors_address FOREIGN KEY (address_id) REFERENCES dbo.address (id)
);
GO

-- Bring an already-created debtors table up to date.
IF COL_LENGTH(N'dbo.debtors', N'iban') IS NULL
    ALTER TABLE dbo.debtors ADD iban nvarchar(64) NULL;
GO

-- Buyers who pay online through Mollie. Invoices only, no orders.
IF OBJECT_ID(N'dbo.customers', N'U') IS NULL
CREATE TABLE dbo.customers (
    id          int             IDENTITY(1,1) NOT NULL,
    name        nvarchar(max)   NOT NULL,
    email       nvarchar(max)   NOT NULL,
    address_id  int             NULL,
    iban        nvarchar(64)    NULL,       -- bank IBAN used to identify their payments
    CONSTRAINT pk_customers PRIMARY KEY (id),
    CONSTRAINT fk_customers_address FOREIGN KEY (address_id) REFERENCES dbo.address (id)
);
GO

-- Bring an already-created customers table up to date.
IF COL_LENGTH(N'dbo.customers', N'iban') IS NULL
    ALTER TABLE dbo.customers ADD iban nvarchar(64) NULL;
GO

-- Invoices. A debtor or a customer owns the invoice, never both.
-- The number is derived from id (BDF-{id}); there is no number column.
-- An older table that still carried a number column is emptied and rebuilt.
IF OBJECT_ID(N'dbo.invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.invoices', N'number') IS NOT NULL
BEGIN
    IF OBJECT_ID(N'dbo.invoicelines', N'U') IS NOT NULL DROP TABLE dbo.invoicelines;
    DROP TABLE dbo.invoices;
END
GO

IF OBJECT_ID(N'dbo.invoices', N'U') IS NULL
CREATE TABLE dbo.invoices (
    id                  int             IDENTITY(100000,1) NOT NULL,
    token               nvarchar(64)    NULL,   -- secret for the customer's return page
    debtor_id           int             NULL,
    customer_id         int             NULL,
    mollie_id           nvarchar(128)   NULL,   -- a customer's Mollie payment
    mollie_settlement_id nvarchar(128)  NULL,   -- the payout that carried it
    ordered_at          nvarchar(40)    NOT NULL,
    due_on              nvarchar(20)    NOT NULL,
    payable_cents       int             NOT NULL,
    open_cents          int             NOT NULL,
    portokosten_cents   int             NULL,
    status              nvarchar(20)    NOT NULL
        CONSTRAINT df_invoices_status DEFAULT N'prepared',
    CONSTRAINT pk_invoices PRIMARY KEY (id),
    CONSTRAINT fk_invoices_debtor FOREIGN KEY (debtor_id) REFERENCES dbo.debtors (id),
    CONSTRAINT fk_invoices_customer FOREIGN KEY (customer_id) REFERENCES dbo.customers (id),
    CONSTRAINT ck_invoices_owner CHECK (
        (debtor_id IS NOT NULL AND customer_id IS NULL)
        OR (debtor_id IS NULL AND customer_id IS NOT NULL)
    )
);
GO

-- Bring an already-created invoices table up to date.
IF COL_LENGTH(N'dbo.invoices', N'mollie_id') IS NULL
    ALTER TABLE dbo.invoices ADD mollie_id nvarchar(128) NULL;
GO
IF COL_LENGTH(N'dbo.invoices', N'mollie_settlement_id') IS NULL
    ALTER TABLE dbo.invoices ADD mollie_settlement_id nvarchar(128) NULL;
GO
IF COL_LENGTH(N'dbo.invoices', N'token') IS NULL
    ALTER TABLE dbo.invoices ADD token nvarchar(64) NULL;
GO
-- The invoice lifecycle: prepared -> sent -> paid; a Mollie/customer invoice
-- stays 'customer' from creation on.
IF COL_LENGTH(N'dbo.invoices', N'status') IS NULL
    ALTER TABLE dbo.invoices ADD status nvarchar(20) NOT NULL
        CONSTRAINT df_invoices_status DEFAULT N'prepared';
GO
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_invoices_mollie' AND object_id = OBJECT_ID(N'dbo.invoices')
)
    CREATE UNIQUE INDEX ux_invoices_mollie ON dbo.invoices (mollie_id)
        WHERE mollie_id IS NOT NULL;
GO

IF OBJECT_ID(N'dbo.invoicelines', N'U') IS NULL
CREATE TABLE dbo.invoicelines (
    id                      int             IDENTITY(1,1) NOT NULL,
    invoice_id              int             NOT NULL,
    slug                    nvarchar(max)   NOT NULL,
    number_of_copies        int             NOT NULL,
    price_cents_per_copy    int             NOT NULL,
    CONSTRAINT pk_invoicelines PRIMARY KEY (id),
    CONSTRAINT fk_invoicelines_invoice FOREIGN KEY (invoice_id) REFERENCES dbo.invoices (id)
);
GO

-- Orders exist only for debtor purchases; their primary key is also their
-- invoice id. Rebuild the older independent-id orders table without carrying
-- old rows forward.
IF OBJECT_ID(N'dbo.orders', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.orders', N'invoice_id') IS NULL
BEGIN
    IF OBJECT_ID(N'dbo.orderlines', N'U') IS NOT NULL DROP TABLE dbo.orderlines;
    DROP TABLE dbo.orders;
END
GO

IF OBJECT_ID(N'dbo.orders', N'U') IS NULL
CREATE TABLE dbo.orders (
    invoice_id          int             NOT NULL,
    token               nvarchar(64)    NOT NULL,   -- 32 random hex digits
    email               nvarchar(max)   NOT NULL,
    status              nvarchar(40)    NOT NULL,
    amount_cents        int             NOT NULL,
    vat_cents           int             NOT NULL,
    created_at          nvarchar(80)    NOT NULL,
    debtor_id           int             NOT NULL,
    portokosten_cents   int             NULL,
    CONSTRAINT pk_orders PRIMARY KEY (invoice_id),
    CONSTRAINT uq_orders_token UNIQUE (token),
    CONSTRAINT fk_orders_invoice FOREIGN KEY (invoice_id) REFERENCES dbo.invoices (id),
    CONSTRAINT fk_orders_debtor FOREIGN KEY (debtor_id) REFERENCES dbo.debtors (id)
);
GO

-- Each order line uses the same invoice id as its parent order.
IF OBJECT_ID(N'dbo.orderlines', N'U') IS NULL
CREATE TABLE dbo.orderlines (
    id                      int             IDENTITY(1,1) NOT NULL,
    order_id                int             NOT NULL,
    slug                    nvarchar(max)   NOT NULL,
    number_of_copies        int             NOT NULL,
    price_cents_per_copy    int             NOT NULL,
    CONSTRAINT pk_orderlines PRIMARY KEY (id),
    CONSTRAINT fk_orderlines_order FOREIGN KEY (order_id) REFERENCES dbo.orders (invoice_id)
);
GO

-- A booking on the Boog account, matched to one invoice.
IF OBJECT_ID(N'dbo.payments', N'U') IS NULL
CREATE TABLE dbo.payments (
    id                  int             IDENTITY(1,1) NOT NULL,
    transaction_id      bigint          NOT NULL,
    invoice_number      nvarchar(40)    NOT NULL,
    amount_cents        int             NOT NULL,
    CONSTRAINT pk_payments PRIMARY KEY (id),
    CONSTRAINT uq_payments UNIQUE (transaction_id, invoice_number)
);
GO

IF OBJECT_ID(N'dbo.reminders', N'U') IS NULL
CREATE TABLE dbo.reminders (
    id              int             IDENTITY(1,1) NOT NULL,
    invoice_number  nvarchar(40)    NOT NULL,
    email           nvarchar(max)   NOT NULL,
    step            nvarchar(40)    NOT NULL,
    sent_at         nvarchar(40)    NOT NULL,
    CONSTRAINT pk_reminders PRIMARY KEY (id),
    CONSTRAINT uq_reminders UNIQUE (invoice_number, step)
);
GO

IF OBJECT_ID(N'dbo.stock', N'U') IS NULL
CREATE TABLE dbo.stock (
    slug        nvarchar(400)   NOT NULL,
    voorraad    int             NOT NULL,
    CONSTRAINT pk_stock PRIMARY KEY (slug)
);
GO
