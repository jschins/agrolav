-- Bookings that the rows in dbo.cp_rules categorize, with the category
-- stored on the booking at this moment.
--
-- Run this once with @snap = N'before'.
-- Then run hub/sql/cp_rules_reset_modification.sql.
-- Then Bereken kruisposten.
-- Then run this again with @snap = N'after'.
-- Then run hub/sql/cp_rules_compare.sql.
--
-- A pair is two bookings on different accounts, each naming the other's
-- IBAN, amounts opposite to the cent, dates the same day or one day apart,
-- and a dbo.cp_rules pair that fits those two banks.
-- A leg the rule does not write is closed with cp.
-- Geldautomaat is a booking of that type on the HD account, bank_id empty.
--
-- SSMS: connect to database agrolav, then execute this file.
-- @snap is N'after' for the second list. Set it back to N'before' for a new run.
-- The lists are kept in dbo.cp_rule_booking_snap. Drop that table when
-- the comparison is finished.

USE agrolav;
GO

DECLARE @snap nvarchar(20) = N'after';

IF @snap NOT IN (N'before', N'after')
BEGIN
    RAISERROR(N'@snap must be N''before'' or N''after''.', 16, 1);
    RETURN;
END

IF OBJECT_ID(N'dbo.cp_rule_booking_snap', N'U') IS NULL
    CREATE TABLE dbo.cp_rule_booking_snap (
        snap nvarchar(20) NOT NULL,
        table_name sysname NOT NULL,
        rule_name nvarchar(40) NOT NULL,
        transaction_id bigint NOT NULL,
        partner_transaction_id bigint NULL,
        account_id int NOT NULL,
        account_name nvarchar(64) NULL,
        person_username nvarchar(128) NULL,
        booked_on date NOT NULL,
        amount decimal(18, 2) NOT NULL,
        category_id int NOT NULL,
        category_label nvarchar(128) NULL,
        modification smallint NOT NULL,
        bank_type nvarchar(64) NULL,
        taken_at datetime2 NOT NULL,
        CONSTRAINT pk_cp_rule_booking_snap PRIMARY KEY (snap, table_name, transaction_id)
    );

DELETE FROM dbo.cp_rule_booking_snap WHERE snap = @snap;

DECLARE @country_id int;
DECLARE @username nvarchar(128);
DECLARE @qualified nvarchar(300);
DECLARE @sql nvarchar(max);

DECLARE countries CURSOR LOCAL FAST_FORWARD FOR
    SELECT country_id, username
    FROM dbo.country
    WHERE has_balance = 1
    ORDER BY country_id;

OPEN countries;
FETCH NEXT FROM countries INTO @country_id, @username;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @qualified = N'dbo.' + QUOTENAME(N'transaction_' + @username);
    IF OBJECT_ID(@qualified, N'U') IS NOT NULL
    BEGIN
        SET @sql = N'
INSERT INTO dbo.cp_rule_booking_snap (
    snap, table_name, rule_name, transaction_id, partner_transaction_id,
    account_id, account_name, person_username, booked_on, amount,
    category_id, category_label, modification, bank_type, taken_at
)
SELECT
    @snap, @table_name, picked.rule_name, picked.transaction_id, picked.partner_transaction_id,
    t.account_id, a.account_name, p.username, t.booked_on, t.amount,
    t.category_id, catlabel.label, t.modification, t.bank_type, SYSDATETIME()
FROM (
    SELECT
        hits.transaction_id,
        hits.partner_transaction_id,
        hits.rule_name,
        ROW_NUMBER() OVER (
            PARTITION BY hits.transaction_id
            ORDER BY hits.rule_name, hits.partner_transaction_id
        ) AS rn
    FROM (
        SELECT pair.left_id AS transaction_id, pair.right_id AS partner_transaction_id, pair.rule_name
        FROM #cp_rule_pair pair
        UNION ALL
        SELECT pair.right_id, pair.left_id, pair.rule_name
        FROM #cp_rule_pair pair
        UNION ALL
        SELECT g.transaction_id, NULL, N''geldautomaat''
        FROM #cp_rule_cash g
    ) hits
) picked
JOIN ' + @qualified + N' t ON t.transaction_id = picked.transaction_id
JOIN dbo.account a ON a.account_id = t.account_id
JOIN dbo.person p ON p.id = a.person_id
LEFT JOIN dbo.dim_category catlabel ON catlabel.category_id = t.category_id
WHERE picked.rn = 1;
';
        SET @sql = N'
IF OBJECT_ID(N''tempdb..#cp_rule_pair'') IS NOT NULL DROP TABLE #cp_rule_pair;
IF OBJECT_ID(N''tempdb..#cp_rule_cash'') IS NOT NULL DROP TABLE #cp_rule_cash;
CREATE TABLE #cp_rule_pair (
    left_id bigint NOT NULL,
    right_id bigint NOT NULL,
    rule_name nvarchar(40) NOT NULL
);
CREATE TABLE #cp_rule_cash (
    transaction_id bigint NOT NULL
);

;WITH iban AS (
    SELECT
        a.account_id,
        UPPER(REPLACE(REPLACE(REPLACE(a.iban, N'' '', N''''), CHAR(9), N''''), CHAR(10), N'''')) AS iban_key,
        CASE
            WHEN LOWER(LTRIM(RTRIM(n.username))) IN (N''sia'', N''center_sia'')
              OR LOWER(LTRIM(RTRIM(n.username))) LIKE N''%[_]sia'' THEN N''sia''
            WHEN LOWER(LTRIM(RTRIM(n.username))) IN (N''sib'', N''center_sib'')
              OR LOWER(LTRIM(RTRIM(n.username))) LIKE N''%[_]sib'' THEN N''sib''
            ELSE LOWER(LTRIM(RTRIM(n.username)))
        END AS center_key
    FROM dbo.account a
    JOIN dbo.person p ON p.id = a.person_id
    JOIN dbo.center n ON n.center_id = p.center_id
    WHERE n.country_id = @country_id
      AND a.iban IS NOT NULL
      AND LTRIM(RTRIM(a.iban)) <> N''''
),
cat AS (
    SELECT
        category_id,
        local_code,
        LOWER(LTRIM(RTRIM(ISNULL(category_role, N'''')))) AS role,
        account_id,
        assoc_cat_id
    FROM dbo.dim_category
    WHERE country_id = @country_id
),
bank AS (
    SELECT account_id, category_id, role, assoc_cat_id, center_key
    FROM (
        SELECT
            c.account_id, c.category_id, c.role, c.assoc_cat_id, i.center_key,
            ROW_NUMBER() OVER (
                PARTITION BY c.account_id
                ORDER BY CASE
                    WHEN c.role = N''hd'' THEN 0
                    WHEN c.role = N''unit'' OR c.role LIKE N''unit[0-9][0-9][0-9][0-9]'' THEN 1
                    ELSE 2
                END, c.category_id
            ) AS rn
        FROM cat c
        JOIN iban i ON i.account_id = c.account_id
        WHERE c.account_id IS NOT NULL
          AND c.role NOT IN (N''cash'', N''rc'', N''cp'', N''mirror'')
          AND (
                c.role IN (N''hd'', N''source'', N''bank'')
                OR c.role = N''unit''
                OR c.role LIKE N''unit[0-9][0-9][0-9][0-9]''
              )
    ) ranked
    WHERE rn = 1
),
tx AS (
    SELECT
        t.transaction_id, t.account_id, t.booked_on, t.amount,
        UPPER(REPLACE(REPLACE(REPLACE(ISNULL(t.counterparty_iban, N''''), N'' '', N''''), CHAR(9), N''''), CHAR(10), N'''')) AS cp_iban
    FROM ' + @qualified + N' t
    WHERE t.amount <> 0
      AND (t.bank_type IS NULL OR LOWER(t.bank_type) <> N''geldautomaat'')
),
named AS (
    SELECT tx.transaction_id, tx.account_id, tx.booked_on, tx.amount, other.account_id AS other_account_id
    FROM tx
    JOIN iban own ON own.account_id = tx.account_id
    CROSS APPLY (
        SELECT TOP (1) o.account_id
        FROM iban o
        WHERE o.iban_key = tx.cp_iban
          AND o.account_id <> tx.account_id
        ORDER BY o.account_id
    ) other
),
pair AS (
    SELECT
        a.transaction_id AS left_id,
        a.account_id AS left_account,
        b.transaction_id AS right_id,
        b.account_id AS right_account
    FROM named a
    JOIN named b
      ON b.account_id = a.other_account_id
     AND a.account_id = b.other_account_id
     AND a.transaction_id < b.transaction_id
     AND a.amount + b.amount = 0
     AND ABS(DATEDIFF(day, a.booked_on, b.booked_on)) <= 1
)
INSERT INTO #cp_rule_pair (left_id, right_id, rule_name)
SELECT pair.left_id, pair.right_id, hit.rule_name
FROM pair
JOIN bank bl ON bl.account_id = pair.left_account
JOIN bank br ON br.account_id = pair.right_account
CROSS APPLY (
    SELECT TOP (1) rule_name
    FROM (
    SELECT x.rule_name, x.leg
    FROM dbo.cp_rules x
    LEFT JOIN dbo.cp_rules y
      ON y.rule_name = x.rule_name
     AND y.leg <> x.leg
     AND y.other_role IS NOT NULL
    WHERE x.other_role IS NOT NULL
      AND (
            LOWER(LTRIM(RTRIM(x.booking_role))) = bl.role
            OR (LOWER(LTRIM(RTRIM(x.booking_role))) = N''unit''
                AND (bl.role = N''unit'' OR bl.role LIKE N''unit[0-9][0-9][0-9][0-9]''))
          )
      AND (
            LOWER(LTRIM(RTRIM(x.other_role))) = br.role
            OR (LOWER(LTRIM(RTRIM(x.other_role))) = N''unit''
                AND (br.role = N''unit'' OR br.role LIKE N''unit[0-9][0-9][0-9][0-9]''))
          )
      AND (
            x.same_center = 0
            OR (bl.center_key <> N'''' AND bl.center_key = br.center_key)
          )
      AND (
            (x.tie_booking IS NULL AND x.tie_other IS NULL)
            OR (
                CASE LOWER(LTRIM(RTRIM(x.tie_booking)))
                    WHEN N''category_id'' THEN bl.category_id
                    WHEN N''assoc_cat_id'' THEN bl.assoc_cat_id
                END
                =
                CASE LOWER(LTRIM(RTRIM(x.tie_other)))
                    WHEN N''category_id'' THEN br.category_id
                    WHEN N''assoc_cat_id'' THEN br.assoc_cat_id
                END
                AND CASE LOWER(LTRIM(RTRIM(x.tie_booking)))
                    WHEN N''category_id'' THEN bl.category_id
                    WHEN N''assoc_cat_id'' THEN bl.assoc_cat_id
                END IS NOT NULL
            )
          )
      AND (
            y.leg IS NULL
            OR LOWER(LTRIM(RTRIM(y.booking_role))) = br.role
            OR (LOWER(LTRIM(RTRIM(y.booking_role))) = N''unit''
                AND (br.role = N''unit'' OR br.role LIKE N''unit[0-9][0-9][0-9][0-9]''))
          )
      AND (
            y.leg IS NULL
            OR LOWER(LTRIM(RTRIM(y.other_role))) = bl.role
            OR (LOWER(LTRIM(RTRIM(y.other_role))) = N''unit''
                AND (bl.role = N''unit'' OR bl.role LIKE N''unit[0-9][0-9][0-9][0-9]''))
          )
      AND (
            y.leg IS NULL
            OR y.same_center = 0
            OR (bl.center_key <> N'''' AND bl.center_key = br.center_key)
          )
      AND (
            y.leg IS NULL
            OR (y.tie_booking IS NULL AND y.tie_other IS NULL)
            OR (
                CASE LOWER(LTRIM(RTRIM(y.tie_booking)))
                    WHEN N''category_id'' THEN br.category_id
                    WHEN N''assoc_cat_id'' THEN br.assoc_cat_id
                END
                =
                CASE LOWER(LTRIM(RTRIM(y.tie_other)))
                    WHEN N''category_id'' THEN bl.category_id
                    WHEN N''assoc_cat_id'' THEN bl.assoc_cat_id
                END
                AND CASE LOWER(LTRIM(RTRIM(y.tie_booking)))
                    WHEN N''category_id'' THEN br.category_id
                    WHEN N''assoc_cat_id'' THEN br.assoc_cat_id
                END IS NOT NULL
            )
          )
      AND (
            (LOWER(LTRIM(RTRIM(x.write_as))) = N''other.assoc_cat_id''
             AND EXISTS (SELECT 1 FROM cat t WHERE t.category_id = br.assoc_cat_id))
            OR (LOWER(LTRIM(RTRIM(x.write_as))) = N''role'' AND EXISTS (
                SELECT 1 FROM cat t
                WHERE t.role = LOWER(LTRIM(RTRIM(x.category_role)))
                  AND (
                        x.role_account IS NULL
                        OR (LOWER(LTRIM(RTRIM(x.role_account))) = N''booking'' AND t.account_id = bl.account_id)
                        OR (LOWER(LTRIM(RTRIM(x.role_account))) = N''other'' AND t.account_id = br.account_id)
                      )
                  AND (
                        x.role_assoc IS NULL
                        OR (LOWER(LTRIM(RTRIM(x.role_assoc))) = N''booking.category_id'' AND t.assoc_cat_id = bl.category_id)
                        OR (LOWER(LTRIM(RTRIM(x.role_assoc))) = N''booking.assoc_cat_id'' AND t.assoc_cat_id = bl.assoc_cat_id)
                        OR (LOWER(LTRIM(RTRIM(x.role_assoc))) = N''other.category_id'' AND t.assoc_cat_id = br.category_id)
                        OR (LOWER(LTRIM(RTRIM(x.role_assoc))) = N''other.assoc_cat_id'' AND t.assoc_cat_id = br.assoc_cat_id)
                      )
            ))
            OR EXISTS (SELECT 1 FROM cat t WHERE t.role = N''cp'')
          )
      AND (
            y.leg IS NULL
            OR (LOWER(LTRIM(RTRIM(y.write_as))) = N''other.assoc_cat_id''
                AND EXISTS (SELECT 1 FROM cat t WHERE t.category_id = bl.assoc_cat_id))
            OR (LOWER(LTRIM(RTRIM(y.write_as))) = N''role'' AND EXISTS (
                SELECT 1 FROM cat t
                WHERE t.role = LOWER(LTRIM(RTRIM(y.category_role)))
                  AND (
                        y.role_account IS NULL
                        OR (LOWER(LTRIM(RTRIM(y.role_account))) = N''booking'' AND t.account_id = br.account_id)
                        OR (LOWER(LTRIM(RTRIM(y.role_account))) = N''other'' AND t.account_id = bl.account_id)
                      )
                  AND (
                        y.role_assoc IS NULL
                        OR (LOWER(LTRIM(RTRIM(y.role_assoc))) = N''booking.category_id'' AND t.assoc_cat_id = br.category_id)
                        OR (LOWER(LTRIM(RTRIM(y.role_assoc))) = N''booking.assoc_cat_id'' AND t.assoc_cat_id = br.assoc_cat_id)
                        OR (LOWER(LTRIM(RTRIM(y.role_assoc))) = N''other.category_id'' AND t.assoc_cat_id = bl.category_id)
                        OR (LOWER(LTRIM(RTRIM(y.role_assoc))) = N''other.assoc_cat_id'' AND t.assoc_cat_id = bl.assoc_cat_id)
                      )
            ))
            OR EXISTS (SELECT 1 FROM cat t WHERE t.role = N''cp'')
          )
    UNION ALL
    SELECT x.rule_name, x.leg
    FROM dbo.cp_rules x
    WHERE x.other_role IS NOT NULL
      AND NOT EXISTS (
            SELECT 1 FROM dbo.cp_rules other_leg
            WHERE other_leg.rule_name = x.rule_name
              AND other_leg.leg <> x.leg
              AND other_leg.other_role IS NOT NULL
          )
      AND (
            LOWER(LTRIM(RTRIM(x.booking_role))) = br.role
            OR (LOWER(LTRIM(RTRIM(x.booking_role))) = N''unit''
                AND (br.role = N''unit'' OR br.role LIKE N''unit[0-9][0-9][0-9][0-9]''))
          )
      AND (
            LOWER(LTRIM(RTRIM(x.other_role))) = bl.role
            OR (LOWER(LTRIM(RTRIM(x.other_role))) = N''unit''
                AND (bl.role = N''unit'' OR bl.role LIKE N''unit[0-9][0-9][0-9][0-9]''))
          )
      AND (
            x.same_center = 0
            OR (bl.center_key <> N'''' AND bl.center_key = br.center_key)
          )
      AND (
            (x.tie_booking IS NULL AND x.tie_other IS NULL)
            OR (
                CASE LOWER(LTRIM(RTRIM(x.tie_booking)))
                    WHEN N''category_id'' THEN br.category_id
                    WHEN N''assoc_cat_id'' THEN br.assoc_cat_id
                END
                =
                CASE LOWER(LTRIM(RTRIM(x.tie_other)))
                    WHEN N''category_id'' THEN bl.category_id
                    WHEN N''assoc_cat_id'' THEN bl.assoc_cat_id
                END
                AND CASE LOWER(LTRIM(RTRIM(x.tie_booking)))
                    WHEN N''category_id'' THEN br.category_id
                    WHEN N''assoc_cat_id'' THEN br.assoc_cat_id
                END IS NOT NULL
            )
          )
      AND (
            (LOWER(LTRIM(RTRIM(x.write_as))) = N''other.assoc_cat_id''
             AND EXISTS (SELECT 1 FROM cat t WHERE t.category_id = bl.assoc_cat_id))
            OR (LOWER(LTRIM(RTRIM(x.write_as))) = N''role'' AND EXISTS (
                SELECT 1 FROM cat t
                WHERE t.role = LOWER(LTRIM(RTRIM(x.category_role)))
                  AND (
                        x.role_account IS NULL
                        OR (LOWER(LTRIM(RTRIM(x.role_account))) = N''booking'' AND t.account_id = br.account_id)
                        OR (LOWER(LTRIM(RTRIM(x.role_account))) = N''other'' AND t.account_id = bl.account_id)
                      )
                  AND (
                        x.role_assoc IS NULL
                        OR (LOWER(LTRIM(RTRIM(x.role_assoc))) = N''booking.category_id'' AND t.assoc_cat_id = br.category_id)
                        OR (LOWER(LTRIM(RTRIM(x.role_assoc))) = N''booking.assoc_cat_id'' AND t.assoc_cat_id = br.assoc_cat_id)
                        OR (LOWER(LTRIM(RTRIM(x.role_assoc))) = N''other.category_id'' AND t.assoc_cat_id = bl.category_id)
                        OR (LOWER(LTRIM(RTRIM(x.role_assoc))) = N''other.assoc_cat_id'' AND t.assoc_cat_id = bl.assoc_cat_id)
                      )
            ))
            OR EXISTS (SELECT 1 FROM cat t WHERE t.role = N''cp'')
          )
    ) oriented
    ORDER BY rule_name, leg
) hit;

INSERT INTO #cp_rule_cash (transaction_id)
SELECT t.transaction_id
FROM ' + @qualified + N' t
WHERE t.bank_id IS NULL
  AND LOWER(LTRIM(RTRIM(ISNULL(t.bank_type, N'''')))) = N''geldautomaat''
  AND EXISTS (
        SELECT 1
        FROM dbo.dim_category d
        WHERE d.country_id = @country_id
          AND d.account_id = t.account_id
          AND LOWER(LTRIM(RTRIM(ISNULL(d.category_role, N'''')))) = N''hd''
      )
  AND EXISTS (
        SELECT 1 FROM dbo.cp_rules r
        WHERE LOWER(LTRIM(RTRIM(r.rule_name))) = N''geldautomaat''
      );
' + @sql;
        EXEC sp_executesql
            @sql,
            N'@snap nvarchar(20), @table_name sysname, @country_id int',
            @snap = @snap,
            @table_name = @qualified,
            @country_id = @country_id;
    END
    FETCH NEXT FROM countries INTO @country_id, @username;
END
CLOSE countries;
DEALLOCATE countries;

SELECT
    snap, table_name, rule_name, transaction_id, partner_transaction_id,
    account_id, account_name, person_username, booked_on, amount,
    category_id, category_label, modification, bank_type
FROM dbo.cp_rule_booking_snap
WHERE snap = @snap
ORDER BY table_name, rule_name, booked_on, transaction_id;
GO
