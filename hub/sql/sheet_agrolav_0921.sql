-- Actueel balance sheet from agrolav_0921, and equity versus the opening.
-- Run in SSMS on the instance that has agrolav_0921. Does not touch agrolav.

DECLARE @country_id int, @year int, @opening decimal(19,2), @user sysname, @sql nvarchar(max);

SELECT TOP (1)
    @country_id = d.country_id,
    @year = o.year,
    @opening = o.amount
FROM agrolav_0921.dbo.balance_opening o
JOIN agrolav_0921.dbo.dim_category d
  ON d.category_id = o.category_id
WHERE o.amount = 11718082.46
  AND LOWER(LTRIM(RTRIM(d.category_role))) IN (N'equity', N'never')
ORDER BY o.year DESC;

IF @country_id IS NULL
    THROW 50000, 'No equity opening of 11718082.46 in agrolav_0921.', 1;

SELECT @user = username
FROM agrolav_0921.dbo.country
WHERE country_id = @country_id;

IF OBJECT_ID(N'tempdb..#sheet') IS NOT NULL DROP TABLE #sheet;
CREATE TABLE #sheet (
    local_code int NULL,
    label nvarchar(200) NULL,
    side nvarchar(20) NOT NULL,
    sheet_amount decimal(19,2) NOT NULL
);

SET @sql = N'
WITH txn AS (
    SELECT *
    FROM agrolav_0921.dbo.' + QUOTENAME(N'transaction_' + @user) + N'
),
sign_of AS (
    SELECT category_id, local_code, label, category_role,
           CASE WHEN local_code = 1099 OR local_code BETWEEN 1000 AND 1999 THEN -1 ELSE 1 END AS sgn,
           CASE WHEN local_code = 1099 OR local_code BETWEEN 1000 AND 2999 THEN 1 ELSE 0 END AS on_sheet
    FROM agrolav_0921.dbo.dim_category
    WHERE country_id = @country_id
),
mirror_cat AS (
    SELECT category_id
    FROM sign_of
    WHERE LOWER(LTRIM(RTRIM(category_role))) = N''mirror''
),
bank AS (
    SELECT m.category_id, a.balance
    FROM agrolav_0921.dbo.mapping_banks m
    JOIN agrolav_0921.dbo.account a ON a.account_id = m.account_id
    JOIN sign_of d ON d.category_id = m.category_id
    WHERE m.country_id = @country_id
      AND m.category_id NOT IN (11019, 11021)
      AND d.category_id NOT IN (SELECT category_id FROM mirror_cat)
),
opening AS (
    SELECT o.category_id, o.amount
    FROM agrolav_0921.dbo.balance_opening o
    JOIN sign_of d ON d.category_id = o.category_id
    WHERE o.year = @year
),
mirror_sum AS (
    SELECT category_id, SUM(amount) AS amount
    FROM agrolav_0921.dbo.transaction_mirror
    WHERE country_id = @country_id AND year = @year
    GROUP BY category_id
),
journal_leg AS (
    SELECT j.category_from AS category_id,
           -sf.sgn * st.sgn * j.amount AS amount
    FROM agrolav_0921.dbo.journal j
    JOIN sign_of sf ON sf.category_id = j.category_from
    JOIN sign_of st ON st.category_id = j.category_to
    WHERE j.year = @year
      AND LOWER(LTRIM(RTRIM(ISNULL(sf.category_role, N'''')))) NOT IN (N''equity'', N''never'', N''profit'')
      AND LOWER(LTRIM(RTRIM(ISNULL(st.category_role, N'''')))) NOT IN (N''equity'', N''never'', N''profit'')
    UNION ALL
    SELECT j.category_to, j.amount
    FROM agrolav_0921.dbo.journal j
    JOIN sign_of sf ON sf.category_id = j.category_from
    JOIN sign_of st ON st.category_id = j.category_to
    WHERE j.year = @year
      AND LOWER(LTRIM(RTRIM(ISNULL(sf.category_role, N'''')))) NOT IN (N''equity'', N''never'', N''profit'')
      AND LOWER(LTRIM(RTRIM(ISNULL(st.category_role, N'''')))) NOT IN (N''equity'', N''never'', N''profit'')
),
journal_sum AS (
    SELECT category_id, SUM(amount) AS amount
    FROM journal_leg
    GROUP BY category_id
),
booking AS (
    SELECT t.category_id,
           SUM(CASE
                   WHEN d.local_code IN (1099, 1100) THEN t.amount
                   WHEN d.local_code BETWEEN 1000 AND 1999 THEN -t.amount
                   WHEN d.local_code BETWEEN 2000 AND 2999 THEN t.amount
                   ELSE 0
               END) AS amount
    FROM txn t
    JOIN sign_of d ON d.category_id = t.category_id
    WHERE t.year = @year
      AND t.bank_id IS NULL
      AND (d.local_code = 1099 OR d.local_code BETWEEN 1000 AND 2999)
      AND (d.category_role IS NULL OR LOWER(LTRIM(RTRIM(d.category_role))) IN (N''remainder'', N''mirror''))
      AND NOT EXISTS (
          SELECT 1
          FROM agrolav_0921.dbo.mapping_banks sm
          JOIN agrolav_0921.dbo.dim_category sd
            ON sd.category_id = sm.category_id AND sd.country_id = sm.country_id
          WHERE sm.country_id = @country_id
            AND sm.account_id = t.account_id
            AND LOWER(LTRIM(RTRIM(sd.category_role))) = N''source''
            AND LOWER(COALESCE(t.description, N'''')) LIKE N''%spaarrekening%''
      )
    GROUP BY t.category_id
),
verlies AS (
    SELECT
        ISNULL((
            SELECT SUM(t.amount)
            FROM txn t
            JOIN sign_of d ON d.category_id = t.category_id
            WHERE t.year = @year
              AND d.local_code BETWEEN 3000 AND 4999
              AND NOT EXISTS (
                  SELECT 1
                  FROM agrolav_0921.dbo.mapping_banks sm
                  JOIN agrolav_0921.dbo.dim_category sd
                    ON sd.category_id = sm.category_id AND sd.country_id = sm.country_id
                  WHERE sm.country_id = @country_id
                    AND sm.account_id = t.account_id
                    AND LOWER(LTRIM(RTRIM(sd.category_role))) = N''source''
                    AND LOWER(COALESCE(t.description, N'''')) LIKE N''%spaarrekening%''
              )
        ), 0)
        + ISNULL((
            SELECT SUM(j.amount)
            FROM journal_sum j
            JOIN sign_of d ON d.category_id = j.category_id
            WHERE d.local_code BETWEEN 3000 AND 4999
        ), 0)
        + ISNULL((
            SELECT SUM(m.amount)
            FROM mirror_sum m
            JOIN sign_of d ON d.category_id = m.category_id
            WHERE d.local_code BETWEEN 3000 AND 4999
        ), 0) AS amount
),
line AS (
    SELECT d.local_code, d.label,
           CASE WHEN d.local_code = 1099 OR d.local_code BETWEEN 1000 AND 1999
                THEN N''activa'' ELSE N''passiva'' END AS side,
           CAST(
               CASE WHEN b.category_id IS NOT NULL THEN b.balance
                    ELSE ISNULL(o.amount, 0) END
               + ISNULL(ms.amount, 0)
               + ISNULL(js.amount, 0)
               + CASE WHEN b.category_id IS NULL AND mc.category_id IS NULL
                      THEN ISNULL(bk.amount, 0) ELSE 0 END
           AS decimal(19,2)) AS sheet_amount
    FROM sign_of d
    LEFT JOIN bank b ON b.category_id = d.category_id
    LEFT JOIN opening o ON o.category_id = d.category_id
    LEFT JOIN mirror_sum ms ON ms.category_id = d.category_id
    LEFT JOIN journal_sum js ON js.category_id = d.category_id
    LEFT JOIN booking bk ON bk.category_id = d.category_id
    LEFT JOIN mirror_cat mc ON mc.category_id = d.category_id
    WHERE d.on_sheet = 1
      AND LOWER(LTRIM(RTRIM(ISNULL(d.category_role, N'''')))) NOT IN (N''equity'', N''never'', N''profit'')
)
INSERT INTO #sheet (local_code, label, side, sheet_amount)
SELECT local_code, label, side, sheet_amount
FROM line
WHERE sheet_amount <> 0
UNION ALL
SELECT NULL, N''Verlies'', N''passiva'', CAST(amount AS decimal(19,2))
FROM verlies;
';

EXEC sp_executesql @sql,
    N'@country_id int, @year int',
    @country_id = @country_id, @year = @year;

SELECT local_code, label, side, sheet_amount
FROM #sheet
ORDER BY side, local_code;

SELECT
    @opening AS opening_equity,
    SUM(CASE WHEN side = N'activa' THEN sheet_amount ELSE -sheet_amount END) AS actual_equity,
    SUM(CASE WHEN side = N'activa' THEN sheet_amount ELSE -sheet_amount END) - @opening AS difference
FROM #sheet;
