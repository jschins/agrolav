-- Compare the before list with the after list.
-- Run hub/sql/cp_rules_bookings.sql twice, once as N'before' and once as N'after'.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.cp_rule_booking_snap', N'U') IS NULL
   OR NOT EXISTS (SELECT 1 FROM dbo.cp_rule_booking_snap WHERE snap = N'before')
   OR NOT EXISTS (SELECT 1 FROM dbo.cp_rule_booking_snap WHERE snap = N'after')
BEGIN
    RAISERROR(N'Both snaps are required: N''before'' and N''after''.', 16, 1);
    RETURN;
END

;WITH compared AS (
    SELECT
        COALESCE(b.table_name, a.table_name) AS table_name,
        COALESCE(b.transaction_id, a.transaction_id) AS transaction_id,
        COALESCE(b.account_name, a.account_name) AS account_name,
        COALESCE(b.booked_on, a.booked_on) AS booked_on,
        COALESCE(b.amount, a.amount) AS amount,
        b.rule_name AS rule_before,
        a.rule_name AS rule_after,
        b.category_id AS category_before,
        a.category_id AS category_after,
        b.category_label AS label_before,
        a.category_label AS label_after,
        CASE
            WHEN b.transaction_id IS NULL THEN N'only after'
            WHEN a.transaction_id IS NULL THEN N'only before'
            WHEN b.category_id <> a.category_id THEN N'category changed'
            WHEN b.rule_name <> a.rule_name THEN N'rule changed'
            ELSE N'same'
        END AS change
    FROM (
        SELECT * FROM dbo.cp_rule_booking_snap WHERE snap = N'before'
    ) b
    FULL OUTER JOIN (
        SELECT * FROM dbo.cp_rule_booking_snap WHERE snap = N'after'
    ) a
      ON a.table_name = b.table_name
     AND a.transaction_id = b.transaction_id
)
SELECT change, COUNT(*) AS bookings
FROM compared
GROUP BY change
ORDER BY change;

;WITH compared AS (
    SELECT
        COALESCE(b.table_name, a.table_name) AS table_name,
        COALESCE(b.transaction_id, a.transaction_id) AS transaction_id,
        COALESCE(b.account_name, a.account_name) AS account_name,
        COALESCE(b.booked_on, a.booked_on) AS booked_on,
        COALESCE(b.amount, a.amount) AS amount,
        b.rule_name AS rule_before,
        a.rule_name AS rule_after,
        b.category_id AS category_before,
        a.category_id AS category_after,
        b.category_label AS label_before,
        a.category_label AS label_after,
        CASE
            WHEN b.transaction_id IS NULL THEN N'only after'
            WHEN a.transaction_id IS NULL THEN N'only before'
            WHEN b.category_id <> a.category_id THEN N'category changed'
            WHEN b.rule_name <> a.rule_name THEN N'rule changed'
            ELSE N'same'
        END AS change
    FROM (
        SELECT * FROM dbo.cp_rule_booking_snap WHERE snap = N'before'
    ) b
    FULL OUTER JOIN (
        SELECT * FROM dbo.cp_rule_booking_snap WHERE snap = N'after'
    ) a
      ON a.table_name = b.table_name
     AND a.transaction_id = b.transaction_id
)
SELECT
    change, table_name, transaction_id, account_name, booked_on, amount,
    rule_before, category_before, label_before,
    rule_after, category_after, label_after
FROM compared
WHERE change <> N'same'
ORDER BY change, table_name, booked_on, transaction_id;
GO
