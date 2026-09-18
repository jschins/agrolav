-- Transactions that explain Saldo vs Resultaat on the hd_sdog resultaat sheet
-- AFTER Saldo includes 1053 Ontvangsten.
--
-- Saldo     = P&L (hd_sdog + remainder, 3000–4999) + incoming (amount > 0 on 1053)
--             A booking can sit in both, and then counts twice in Saldo.
-- Resultaat = Q+R+S = every signed amount on the 1053 account
--
-- gap_amount = (in_pnl + in_incoming - in_resultaat) * amount
-- Rows with gap_amount <> 0 are the difference.
--
-- Compared with the old Saldo-vs-Uitgaven list:
--   the six credits are STILL in the gap (now because they are in P&L and in
--   1053 incoming, but only once in Resultaat);
--   Miele-style 1053 outflows outside hd_sdog/remainder P&L are still in the gap.
--
-- SSMS: database agrolav. Set @year if you exported a different year.

USE agrolav;
GO

DECLARE @year int = YEAR(GETDATE());
DECLARE @month_count int =
    CASE
        WHEN @year < YEAR(GETDATE()) THEN 12
        WHEN @year > YEAR(GETDATE()) THEN 0
        ELSE MONTH(GETDATE())
    END;

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
        CAST(t.amount AS decimal(19, 2)) AS amount,
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
            END AS int
        ) AS in_pnl,
        CAST(
            CASE
                WHEN t.account_id = @account_1053
                 AND t.amount > 0
                 AND t.booked_on IS NOT NULL
                 AND MONTH(t.booked_on) BETWEEN 1 AND @month_count
                THEN 1 ELSE 0
            END AS int
        ) AS in_incoming,
        CAST(
            CASE
                WHEN t.account_id = @account_1053
                 AND t.booked_on IS NOT NULL
                 AND MONTH(t.booked_on) BETWEEN 1 AND @month_count
                THEN 1 ELSE 0
            END AS int
        ) AS in_resultaat
    FROM dbo.transaction_beheer_sdog t
    JOIN dbo.dim_category d
      ON d.category_id = t.category_id
     AND d.country_id = @country_id
    WHERE t.year = @year
)
SELECT
    (in_pnl + in_incoming) AS saldo_times,
    in_resultaat AS resultaat_times,
    CAST((in_pnl + in_incoming - in_resultaat) * amount AS decimal(19, 2)) AS gap_amount,
    CASE
        WHEN in_pnl = 1 AND in_incoming = 1 AND in_resultaat = 1
            THEN N'in P&L and 1053 Ontvangsten; only once in Resultaat (double count)'
        WHEN in_pnl = 1 AND in_incoming = 0 AND in_resultaat = 0
            THEN N'P&L not on the 1053 account'
        WHEN in_pnl = 1 AND in_incoming = 0 AND in_resultaat = 1
            THEN N'P&L on 1053 but not incoming (outflow already in Resultaat)'
        WHEN in_pnl = 0 AND in_incoming = 1 AND in_resultaat = 1
            THEN N'1053 incoming not in hd_sdog/remainder P&L'
        WHEN in_pnl = 0 AND in_incoming = 0 AND in_resultaat = 1 AND amount < 0
            THEN N'1053 outflow outside hd_sdog/remainder P&L'
        WHEN in_pnl = 0 AND in_incoming = 0 AND in_resultaat = 1
            THEN N'1053 movement outside P&L'
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
WHERE (in_pnl + in_incoming - in_resultaat) * amount <> 0
ORDER BY t.booked_on, t.transaction_id;

SELECT
    SUM(CAST((in_pnl + in_incoming) * amount AS decimal(19, 2))) AS saldo,
    SUM(CAST(in_resultaat * amount AS decimal(19, 2))) AS resultaat,
    SUM(CAST((in_pnl + in_incoming - in_resultaat) * amount AS decimal(19, 2))) AS saldo_minus_resultaat
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
            END AS int
        ) AS in_pnl,
        CAST(
            CASE
                WHEN t.account_id = @account_1053
                 AND t.amount > 0
                 AND t.booked_on IS NOT NULL
                 AND MONTH(t.booked_on) BETWEEN 1 AND @month_count
                THEN 1 ELSE 0
            END AS int
        ) AS in_incoming,
        CAST(
            CASE
                WHEN t.account_id = @account_1053
                 AND t.booked_on IS NOT NULL
                 AND MONTH(t.booked_on) BETWEEN 1 AND @month_count
                THEN 1 ELSE 0
            END AS int
        ) AS in_resultaat,
        CAST(t.amount AS decimal(19, 2)) AS amount
    FROM dbo.transaction_beheer_sdog t
    JOIN dbo.dim_category d
      ON d.category_id = t.category_id
     AND d.country_id = @country_id
    WHERE t.year = @year
) s;
