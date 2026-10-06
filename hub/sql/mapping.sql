-- dbo.mapping for countries 4 (beheer_sdog) and 5 (beheer_instudo).
--
-- Copies every dbo.mapping_banks row for those countries, with
-- counterparty_account_id NULL. Adds one row per leg of a Bereken
-- kruisposten pair, with the category_id written on that leg.
--
-- Does not change dbo.dim_category.category_role. The present code still
-- reads those values.
--
-- SSMS: connect to database agrolav, then execute this file.

USE agrolav;
GO

-- dbo.mapping_banks already owns the name pk_mapping. Free that name
-- before dbo.mapping is created.
IF EXISTS (
    SELECT 1
    FROM sys.key_constraints
    WHERE name = N'pk_mapping'
      AND parent_object_id = OBJECT_ID(N'dbo.mapping_banks')
)
    EXEC sp_rename N'dbo.mapping_banks.pk_mapping', N'pk_mapping_banks', N'INDEX';
GO

IF OBJECT_ID(N'dbo.mapping', N'U') IS NULL
    CREATE TABLE dbo.mapping (
        mapping_id INT IDENTITY(1, 1) NOT NULL
            CONSTRAINT pk_mapping PRIMARY KEY,
        country_id INT NOT NULL,
        account_id INT NOT NULL,
        category_id INT NOT NULL,
        counterparty_account_id INT NULL,
        CONSTRAINT fk_agrolav_mapping_country
            FOREIGN KEY (country_id) REFERENCES dbo.country (country_id),
        CONSTRAINT fk_agrolav_mapping_account
            FOREIGN KEY (account_id) REFERENCES dbo.account (account_id),
        CONSTRAINT fk_agrolav_mapping_category
            FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id),
        CONSTRAINT fk_agrolav_mapping_counterparty
            FOREIGN KEY (counterparty_account_id) REFERENCES dbo.account (account_id)
    );
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_mapping_bank' AND object_id = OBJECT_ID(N'dbo.mapping')
)
    CREATE UNIQUE INDEX ux_mapping_bank
        ON dbo.mapping (country_id, account_id, category_id)
        WHERE counterparty_account_id IS NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'ux_mapping_pair' AND object_id = OBJECT_ID(N'dbo.mapping')
)
    CREATE UNIQUE INDEX ux_mapping_pair
        ON dbo.mapping (country_id, account_id, counterparty_account_id, category_id)
        WHERE counterparty_account_id IS NOT NULL;
GO

-- A mapping_banks row whose account_id is not in dbo.account cannot be
-- copied. The foreign key rejects it, and that rejection stops the whole
-- insert. Those rows are listed here and left out of dbo.mapping.
SELECT m.country_id, m.account_id, m.category_id
FROM dbo.mapping_banks m
WHERE m.country_id IN (4, 5)
  AND NOT EXISTS (
      SELECT 1 FROM dbo.account a WHERE a.account_id = m.account_id
  );

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT m.country_id, m.account_id, m.category_id, NULL
FROM dbo.mapping_banks m
WHERE m.country_id IN (4, 5)
  AND EXISTS (
      SELECT 1 FROM dbo.account a WHERE a.account_id = m.account_id
  )
  AND EXISTS (
      SELECT 1 FROM dbo.country c WHERE c.country_id = m.country_id
  )
  AND EXISTS (
      SELECT 1
      FROM dbo.dim_category d
      WHERE d.category_id = m.category_id AND d.country_id = m.country_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM dbo.mapping x
      WHERE x.country_id = m.country_id
        AND x.account_id = m.account_id
        AND x.category_id = m.category_id
        AND x.counterparty_account_id IS NULL
  );
GO

-- Pair accounts: the bank post whose role is hd, unitNNNN, or userNNNN.
-- Cash and mirror rows on the same account are ignored here.

IF OBJECT_ID(N'tempdb..#pair_account') IS NOT NULL DROP TABLE #pair_account;
GO

SELECT
    m.country_id,
    m.account_id,
    n.center_id,
    LOWER(LTRIM(RTRIM(n.username))) AS center_name,
    CASE
        WHEN LOWER(LTRIM(RTRIM(n.username))) IN (N'sia', N'center_sia')
          OR LOWER(LTRIM(RTRIM(n.username))) LIKE N'%[_]sia' THEN N'sia'
        WHEN LOWER(LTRIM(RTRIM(n.username))) IN (N'sib', N'center_sib')
          OR LOWER(LTRIM(RTRIM(n.username))) LIKE N'%[_]sib' THEN N'sib'
        ELSE LOWER(LTRIM(RTRIM(n.username)))
    END AS center_side,
    LOWER(LTRIM(RTRIM(d.category_role))) AS role,
    CASE
        WHEN LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'unit[0-9][0-9][0-9][0-9]'
          OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'user[0-9][0-9][0-9][0-9]'
        THEN CAST(RIGHT(LTRIM(RTRIM(d.category_role)), 4) AS INT)
    END AS digits,
    UPPER(REPLACE(ISNULL(a.iban, N''), N' ', N'')) AS iban
INTO #pair_account
FROM dbo.mapping_banks m
JOIN dbo.dim_category d
  ON d.category_id = m.category_id AND d.country_id = m.country_id
JOIN dbo.account a ON a.account_id = m.account_id
JOIN dbo.person p ON p.id = a.person_id
JOIN dbo.center n ON n.center_id = p.center_id
WHERE m.country_id IN (4, 5)
  AND (
      LOWER(LTRIM(RTRIM(d.category_role))) = N'hd'
      OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'unit[0-9][0-9][0-9][0-9]'
      OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'user[0-9][0-9][0-9][0-9]'
  );
GO

-- Role row for cp, sia, sib, siasib: the category_id of the lowest local code.

IF OBJECT_ID(N'tempdb..#pair_role') IS NOT NULL DROP TABLE #pair_role;
GO

SELECT country_id, role, category_id
INTO #pair_role
FROM (
    SELECT
        d.country_id,
        LOWER(LTRIM(RTRIM(d.category_role))) AS role,
        d.category_id,
        ROW_NUMBER() OVER (
            PARTITION BY d.country_id, LOWER(LTRIM(RTRIM(d.category_role)))
            ORDER BY d.local_code, d.category_id
        ) AS n
    FROM dbo.dim_category d
    WHERE d.country_id IN (4, 5)
      AND LOWER(LTRIM(RTRIM(d.category_role))) IN (N'cp', N'sia', N'sib', N'siasib')
) ranked
WHERE n = 1;
GO

-- unitXX0X against the hd account in the same center.
-- The unit leg is local code XX0X + 10, stored as that category_id.
-- The hd leg is the cp category. unit1108 stores 11118 and 11200 for country 5.

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT u.country_id, u.account_id, cat.category_id, h.account_id
FROM #pair_account u
JOIN #pair_account h
  ON h.country_id = u.country_id
 AND h.center_id = u.center_id
 AND h.role = N'hd'
 AND h.account_id <> u.account_id
JOIN dbo.dim_category cat
  ON cat.country_id = u.country_id
 AND cat.local_code = u.digits + 10
JOIN #pair_role cp
  ON cp.country_id = u.country_id AND cp.role = N'cp'
WHERE u.role LIKE N'unit[0-9][0-9][0-9][0-9]'
  AND u.digits IS NOT NULL
  AND (u.digits / 10) % 10 = 0
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = u.country_id
        AND x.account_id = u.account_id
        AND x.category_id = cat.category_id
        AND x.counterparty_account_id = h.account_id
  );

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT u.country_id, h.account_id, cp.category_id, u.account_id
FROM #pair_account u
JOIN #pair_account h
  ON h.country_id = u.country_id
 AND h.center_id = u.center_id
 AND h.role = N'hd'
 AND h.account_id <> u.account_id
JOIN #pair_role cp
  ON cp.country_id = u.country_id AND cp.role = N'cp'
WHERE u.role LIKE N'unit[0-9][0-9][0-9][0-9]'
  AND u.digits IS NOT NULL
  AND (u.digits / 10) % 10 = 0
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = u.country_id
        AND x.account_id = h.account_id
        AND x.category_id = cp.category_id
        AND x.counterparty_account_id = u.account_id
  );
GO

-- A unit role whose third digit is not 0, such as unit1111.
-- The unit leg is the rc post with that local code (1111 for K218).
-- The hd leg is the cp category. This is the pair the xx0x rule does not write.

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT u.country_id, u.account_id, cat.category_id, h.account_id
FROM #pair_account u
JOIN #pair_account h
  ON h.country_id = u.country_id
 AND h.center_id = u.center_id
 AND h.role = N'hd'
 AND h.account_id <> u.account_id
JOIN dbo.dim_category cat
  ON cat.country_id = u.country_id
 AND cat.local_code = u.digits
 AND LOWER(LTRIM(RTRIM(cat.category_role))) = N'rc'
JOIN #pair_role cp
  ON cp.country_id = u.country_id AND cp.role = N'cp'
WHERE u.role LIKE N'unit[0-9][0-9][0-9][0-9]'
  AND u.digits IS NOT NULL
  AND (u.digits / 10) % 10 <> 0
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = u.country_id
        AND x.account_id = u.account_id
        AND x.category_id = cat.category_id
        AND x.counterparty_account_id = h.account_id
  );

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT u.country_id, h.account_id, cp.category_id, u.account_id
FROM #pair_account u
JOIN #pair_account h
  ON h.country_id = u.country_id
 AND h.center_id = u.center_id
 AND h.role = N'hd'
 AND h.account_id <> u.account_id
JOIN dbo.dim_category cat
  ON cat.country_id = u.country_id
 AND cat.local_code = u.digits
 AND LOWER(LTRIM(RTRIM(cat.category_role))) = N'rc'
JOIN #pair_role cp
  ON cp.country_id = u.country_id AND cp.role = N'cp'
WHERE u.role LIKE N'unit[0-9][0-9][0-9][0-9]'
  AND u.digits IS NOT NULL
  AND (u.digits / 10) % 10 <> 0
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = u.country_id
        AND x.account_id = h.account_id
        AND x.category_id = cp.category_id
        AND x.counterparty_account_id = u.account_id
  );
GO

-- Centrale SIa is NL84INGB0002801129. Centrale SIb is NL46INGB0001726568.

IF OBJECT_ID(N'tempdb..#centrale') IS NOT NULL DROP TABLE #centrale;
GO

SELECT n.country_id, a.account_id, UPPER(REPLACE(a.iban, N' ', N'')) AS iban
INTO #centrale
FROM dbo.account a
JOIN dbo.person p ON p.id = a.person_id
JOIN dbo.center n ON n.center_id = p.center_id
WHERE n.country_id IN (4, 5)
  AND UPPER(REPLACE(ISNULL(a.iban, N''), N' ', N'')) IN (
      N'NL84INGB0002801129', N'NL46INGB0001726568'
  );
GO

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT sib.country_id, sib.account_id, cp.category_id, sia.account_id
FROM #centrale sib
JOIN #centrale sia
  ON sia.country_id = sib.country_id
 AND sia.iban = N'NL84INGB0002801129'
JOIN #pair_role cp
  ON cp.country_id = sib.country_id AND cp.role = N'cp'
WHERE sib.iban = N'NL46INGB0001726568'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = sib.country_id
        AND x.account_id = sib.account_id
        AND x.category_id = cp.category_id
        AND x.counterparty_account_id = sia.account_id
  );

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT sia.country_id, sia.account_id, leg.category_id, sib.account_id
FROM #centrale sia
JOIN #centrale sib
  ON sib.country_id = sia.country_id
 AND sib.iban = N'NL46INGB0001726568'
JOIN #pair_role leg
  ON leg.country_id = sia.country_id AND leg.role = N'siasib'
WHERE sia.iban = N'NL84INGB0002801129'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = sia.country_id
        AND x.account_id = sia.account_id
        AND x.category_id = leg.category_id
        AND x.counterparty_account_id = sib.account_id
  );
GO

-- Centrale SIa against a unitNNNN in center SIa.
-- SIa is written to local NNNN. The unit is written to role sia.

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT sia.country_id, sia.account_id, cat.category_id, u.account_id
FROM #centrale sia
JOIN #pair_account u
  ON u.country_id = sia.country_id
 AND u.center_side = N'sia'
 AND u.role LIKE N'unit[0-9][0-9][0-9][0-9]'
 AND u.digits IS NOT NULL
JOIN dbo.dim_category cat
  ON cat.country_id = u.country_id AND cat.local_code = u.digits
WHERE sia.iban = N'NL84INGB0002801129'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = sia.country_id
        AND x.account_id = sia.account_id
        AND x.category_id = cat.category_id
        AND x.counterparty_account_id = u.account_id
  );

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT u.country_id, u.account_id, leg.category_id, sia.account_id
FROM #centrale sia
JOIN #pair_account u
  ON u.country_id = sia.country_id
 AND u.center_side = N'sia'
 AND u.role LIKE N'unit[0-9][0-9][0-9][0-9]'
 AND u.digits IS NOT NULL
JOIN #pair_role leg
  ON leg.country_id = u.country_id AND leg.role = N'sia'
WHERE sia.iban = N'NL84INGB0002801129'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = u.country_id
        AND x.account_id = u.account_id
        AND x.category_id = leg.category_id
        AND x.counterparty_account_id = sia.account_id
  );
GO

-- Centrale SIb against a unitNNNN in center SIb.
-- SIb is written to local NNNN. The unit is written to role sib.

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT sib.country_id, sib.account_id, cat.category_id, u.account_id
FROM #centrale sib
JOIN #pair_account u
  ON u.country_id = sib.country_id
 AND u.center_side = N'sib'
 AND u.role LIKE N'unit[0-9][0-9][0-9][0-9]'
 AND u.digits IS NOT NULL
JOIN dbo.dim_category cat
  ON cat.country_id = u.country_id AND cat.local_code = u.digits
WHERE sib.iban = N'NL46INGB0001726568'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = sib.country_id
        AND x.account_id = sib.account_id
        AND x.category_id = cat.category_id
        AND x.counterparty_account_id = u.account_id
  );

INSERT INTO dbo.mapping (country_id, account_id, category_id, counterparty_account_id)
SELECT u.country_id, u.account_id, leg.category_id, sib.account_id
FROM #centrale sib
JOIN #pair_account u
  ON u.country_id = sib.country_id
 AND u.center_side = N'sib'
 AND u.role LIKE N'unit[0-9][0-9][0-9][0-9]'
 AND u.digits IS NOT NULL
JOIN #pair_role leg
  ON leg.country_id = u.country_id AND leg.role = N'sib'
WHERE sib.iban = N'NL46INGB0001726568'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.mapping x
      WHERE x.country_id = u.country_id
        AND x.account_id = u.account_id
        AND x.category_id = leg.category_id
        AND x.counterparty_account_id = sib.account_id
  );
GO

DROP TABLE #pair_account;
DROP TABLE #pair_role;
DROP TABLE #centrale;
GO
