-- Transactions in dbo.transaction_beheer_sdog that explain Saldo vs Uitgaven
-- on the hd_sdog resultaat overview.
--
-- Saldo     = signed P&L (3000–4999) for person hd_sdog, role hd_sdog or remainder
-- Uitgaven  = amount < 0 on the 1053 bank account, except IBAN NL94INGB0006200605
--
-- Rows in both with the same amount cancel in the gap.
-- This lists rows in exactly one of the two sets.
--
-- SSMS: database agrolav. Set @year if you exported a year other than this one.

USE agrolav;
GO

DECLARE @year int = YEAR(GETDATE());
DECLARE @month_count int =
    CASE
        WHEN @year < YEAR(GETDATE()) THEN 12
        WHEN @year > YEAR(GETDATE()) THEN 0
        ELSE MONTH(GETDATE())
    END;
DECLARE @stichting nvarchar(32) = N'NL94INGB0006200605';

DECLARE @country_id int;
DECLARE @person_id int;
DECLARE @account_1053 int;
DECLARE @spaar_account int;

SELECT @country_id = country_id
FROM dbo.country
WHERE username = N'beheer_sdog' COLLATE Latin1_General_CI_AI;

SELECT @person_id = p.id
FROM dbo.person p
JOIN dbo.center n ON n.center_id = p.center_id
WHERE n.country_id = @country_id
  AND p.username = N'hd_sdog' COLLATE Latin1_General_CI_AI;

SELECT @account_1053 = m.account_id
FROM dbo.mapping_banks m
JOIN dbo.dim_category d
  ON d.category_id = m.category_id AND d.country_id = m.country_id
WHERE m.country_id = @country_id
  AND d.local_code = 1053;

SELECT @spaar_account = m.account_id
FROM dbo.mapping_banks m
JOIN dbo.dim_category d
  ON d.category_id = m.category_id AND d.country_id = m.country_id
WHERE m.country_id = @country_id
  AND LOWER(LTRIM(RTRIM(d.category_role))) = N'source';

IF OBJECT_ID(N'dbo.transaction_beheer_sdog', N'U') IS NULL
    RAISERROR(N'dbo.transaction_beheer_sdog is missing', 16, 1);

;WITH tagged AS (
    SELECT
        t.transaction_id,
        t.person_id,
        t.account_id,
        t.bank_id,
        t.category_id,
        d.local_code,
        d.label,
        d.category_role,
        t.amount,
        t.booked_on,
        t.counterparty_name,
        t.counterparty_iban,
        t.description,
        CAST(
            CASE
                WHEN t.person_id = @person_id
                 AND d.local_code BETWEEN 3000 AND 4999
                 AND t.booked_on IS NOT NULL
                 AND MONTH(t.booked_on) BETWEEN 1 AND @month_count
                 AND LOWER(LTRIM(RTRIM(ISNULL(d.category_role, N''))))
                     IN (N'hd_sdog', N'remainder')
                 AND NOT (
                        @spaar_account IS NOT NULL
                    AND t.account_id = @spaar_account
                    AND LOWER(COALESCE(t.description, N'')) LIKE N'%spaarrekening%'
                 )
                THEN 1 ELSE 0
            END AS bit
        ) AS in_saldo,
        CAST(
            CASE
                WHEN t.account_id = @account_1053
                 AND t.amount < 0
                 AND t.booked_on IS NOT NULL
                 AND MONTH(t.booked_on) BETWEEN 1 AND @month_count
                 AND REPLACE(REPLACE(UPPER(ISNULL(t.counterparty_iban, N'')), N' ', N''), N'-', N'')
                     <> @stichting
                THEN 1 ELSE 0
            END AS bit
        ) AS in_uitgaven
    FROM dbo.transaction_beheer_sdog t
    JOIN dbo.dim_category d
      ON d.category_id = t.category_id
     AND d.country_id = @country_id
    WHERE t.year = @year
)
SELECT
    CASE
        WHEN in_saldo = 1 AND in_uitgaven = 0 THEN N'saldo_only'
        WHEN in_saldo = 0 AND in_uitgaven = 1 THEN N'uitgaven_only'
    END AS bucket,
    CASE
        WHEN in_saldo = 1 AND in_uitgaven = 0 AND t.amount >= 0
            THEN N'P&L amount is not an outflow'
        WHEN in_saldo = 1 AND in_uitgaven = 0
             AND REPLACE(REPLACE(UPPER(ISNULL(t.counterparty_iban, N'')), N' ', N''), N'-', N'')
                 = @stichting
            THEN N'stichting IBAN (row Q, not Uitgaven)'
        WHEN in_saldo = 1 AND in_uitgaven = 0 AND t.account_id <> @account_1053
            THEN N'P&L not on the 1053 account'
        WHEN in_saldo = 0 AND in_uitgaven = 1
             AND LOWER(LTRIM(RTRIM(ISNULL(t.category_role, N''))))
                 NOT IN (N'hd_sdog', N'remainder')
            THEN N'1053 outflow booked outside hd_sdog/remainder P&L'
        WHEN in_saldo = 0 AND in_uitgaven = 1 AND t.person_id <> @person_id
            THEN N'1053 outflow for another person'
        WHEN in_saldo = 0 AND in_uitgaven = 1
            THEN N'1053 outflow excluded from Saldo'
        ELSE N'other'
    END AS why,
    t.transaction_id,
    t.booked_on,
    t.local_code,
    t.label,
    t.category_role,
    t.amount,
    t.account_id,
    t.bank_id,
    t.counterparty_name,
    t.counterparty_iban,
    t.description
FROM tagged t
WHERE t.in_saldo <> t.in_uitgaven
ORDER BY t.booked_on, t.transaction_id;

-- Totals (same filters as the resultaat overview)
SELECT
    SUM(CASE WHEN in_saldo = 1 THEN amount ELSE 0 END) AS saldo,
    SUM(CASE WHEN in_uitgaven = 1 THEN amount ELSE 0 END) AS uitgaven,
    SUM(CASE WHEN in_saldo = 1 THEN amount ELSE 0 END)
      - SUM(CASE WHEN in_uitgaven = 1 THEN amount ELSE 0 END) AS saldo_minus_uitgaven
FROM (
    SELECT
        CAST(
            CASE
                WHEN t.person_id = @person_id
                 AND d.local_code BETWEEN 3000 AND 4999
                 AND t.booked_on IS NOT NULL
                 AND MONTH(t.booked_on) BETWEEN 1 AND @month_count
                 AND LOWER(LTRIM(RTRIM(ISNULL(d.category_role, N''))))
                     IN (N'hd_sdog', N'remainder')
                 AND NOT (
                        @spaar_account IS NOT NULL
                    AND t.account_id = @spaar_account
                    AND LOWER(COALESCE(t.description, N'')) LIKE N'%spaarrekening%'
                 )
                THEN 1 ELSE 0
            END AS bit
        ) AS in_saldo,
        CAST(
            CASE
                WHEN t.account_id = @account_1053
                 AND t.amount < 0
                 AND t.booked_on IS NOT NULL
                 AND MONTH(t.booked_on) BETWEEN 1 AND @month_count
                 AND REPLACE(REPLACE(UPPER(ISNULL(t.counterparty_iban, N'')), N' ', N''), N'-', N'')
                     <> @stichting
                THEN 1 ELSE 0
            END AS bit
        ) AS in_uitgaven,
        CAST(t.amount AS decimal(19, 2)) AS amount
    FROM dbo.transaction_beheer_sdog t
    JOIN dbo.dim_category d
      ON d.category_id = t.category_id
     AND d.country_id = @country_id
    WHERE t.year = @year
) s;
