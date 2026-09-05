BEGIN TRANSACTION;

ALTER TABLE dbo.transaction_uk
DROP CONSTRAINT fk_txn_uk_cat_calc;

ALTER TABLE dbo.transaction_uk
DROP CONSTRAINT ck_txn_uk_cat_calc;

EXEC sp_executesql N'
    EXEC sp_rename
        ''dbo.transaction_uk.cat_id_calculated'',
        ''category_id'',
        ''COLUMN'';
';

ALTER TABLE dbo.transaction_uk
ADD CONSTRAINT ck_txn_uk_cat_calc
CHECK (
    category_id >= 200
    AND category_id <= 299
);

ALTER TABLE dbo.transaction_uk
ADD CONSTRAINT fk_txn_uk_cat_calc
FOREIGN KEY (category_id)
REFERENCES dbo.dim_category(category_id);

COMMIT TRANSACTION;




ALTER TABLE dbo.transaction_uk
DROP CONSTRAINT fk_txn_uk_cat_set;

ALTER TABLE dbo.transaction_uk
DROP CONSTRAINT ck_txn_uk_cat_set;

ALTER TABLE dbo.transaction_uk
DROP COLUMN cat_id_set;


USE master;
ALTER DATABASE agrolav SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
DROP DATABASE agrolav;


==============================Tables and columns=====================

USE agrolav;

WITH TableRows AS
(
    SELECT
        t.object_id,
        t.name AS table_name,
        SUM(p.rows) AS row_count
    FROM sys.tables t
    JOIN sys.partitions p
        ON p.object_id = t.object_id
        AND p.index_id IN (0, 1)
    WHERE
        t.is_ms_shipped = 0
        AND SCHEMA_NAME(t.schema_id) = N'dbo'
    GROUP BY
        t.object_id,
        t.name
),
Columns AS
(
    SELECT
        t.object_id,
        c.column_id,
        c.name AS column_name,

        CASE
            WHEN pk.column_id IS NOT NULL THEN 1
            ELSE 0
        END AS is_pk,

        CASE
            WHEN fk.parent_column_id IS NOT NULL THEN 1
            ELSE 0
        END AS is_fk

    FROM sys.tables t

    JOIN sys.columns c
        ON c.object_id = t.object_id

    LEFT JOIN
    (
        SELECT
            ic.object_id,
            ic.column_id
        FROM sys.indexes i
        JOIN sys.index_columns ic
            ON ic.object_id = i.object_id
            AND ic.index_id = i.index_id
        WHERE i.is_primary_key = 1
    ) pk
        ON pk.object_id = c.object_id
        AND pk.column_id = c.column_id

    LEFT JOIN sys.foreign_key_columns fk
        ON fk.parent_object_id = c.object_id
        AND fk.parent_column_id = c.column_id

    WHERE
        t.is_ms_shipped = 0
        AND SCHEMA_NAME(t.schema_id) = N'dbo'
),
RankedColumns AS
(
    SELECT
        *,
        ROW_NUMBER() OVER
        (
            PARTITION BY object_id, is_fk
            ORDER BY column_id
        ) AS fk_number,

        ROW_NUMBER() OVER
        (
            PARTITION BY object_id
            ORDER BY column_id
        ) AS column_number
    FROM Columns
)
SELECT
    tr.table_name AS C1,
    tr.row_count AS C2,

    -- C3: Primary key
    MAX(CASE
        WHEN rc.is_pk = 1
        THEN rc.column_name
    END) AS C3,

    -- C4-C7: Foreign keys
    MAX(CASE WHEN rc.is_fk = 1 AND rc.fk_number = 1 THEN rc.column_name END) AS C4,
    MAX(CASE WHEN rc.is_fk = 1 AND rc.fk_number = 2 THEN rc.column_name END) AS C5,
    MAX(CASE WHEN rc.is_fk = 1 AND rc.fk_number = 3 THEN rc.column_name END) AS C6,
    MAX(CASE WHEN rc.is_fk = 1 AND rc.fk_number = 4 THEN rc.column_name END) AS C7,

    -- C8-C20: Remaining columns
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 1 THEN rc.column_name END) AS C8,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 2 THEN rc.column_name END) AS C9,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 3 THEN rc.column_name END) AS C10,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 4 THEN rc.column_name END) AS C11,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 5 THEN rc.column_name END) AS C12,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 6 THEN rc.column_name END) AS C13,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 7 THEN rc.column_name END) AS C14,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 8 THEN rc.column_name END) AS C15,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 9 THEN rc.column_name END) AS C16,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 10 THEN rc.column_name END) AS C17,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 11 THEN rc.column_name END) AS C18,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 12 THEN rc.column_name END) AS C19,
    MAX(CASE WHEN rc.is_pk = 0 AND rc.is_fk = 0 AND rc.column_number = 13 THEN rc.column_name END) AS C20

FROM TableRows tr
LEFT JOIN RankedColumns rc
    ON rc.object_id = tr.object_id

GROUP BY
    tr.table_name,
    tr.row_count

ORDER BY
    tr.table_name;


======================
