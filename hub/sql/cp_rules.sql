-- How a cross-posting booking is categorized.
-- One row is one booking the rule knows by name. The other booking of that
-- pair is cp, the closing category. cp is not a row in this table.
-- A named write that cannot be found is cp as well.
-- A transfer that fits no rule stays as it is.
-- The category ids stay in dbo.dim_category.
--
-- booking_role "unit" means category_role unit and also unitNNNN.
-- Geldautomaat also accepts an empty role on the HD account when no cash row exists.
--
-- The hub does not create this table.
-- SSMS: connect to database agrolav, then execute this file.
-- Executing it again rebuilds the table and replaces the rows.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.cp_rules', N'U') IS NOT NULL
    DROP TABLE dbo.cp_rules;
GO

CREATE TABLE dbo.cp_rules (
        rule_name      NVARCHAR(40) NOT NULL,
        leg            TINYINT      NOT NULL,
        booking_role   NVARCHAR(20) NOT NULL,
        other_role     NVARCHAR(20) NULL,
        same_center    BIT          NOT NULL,
        tie_booking    NVARCHAR(40) NULL,
        tie_other      NVARCHAR(40) NULL,
        write_as       NVARCHAR(40) NOT NULL,
        category_role  NVARCHAR(20) NULL,
        role_account   NVARCHAR(20) NULL,
        role_assoc     NVARCHAR(40) NULL,
        CONSTRAINT pk_cp_rules PRIMARY KEY (rule_name, leg),
        CONSTRAINT ck_cp_rules_write_as CHECK (
            write_as IN (N'role', N'other.assoc_cat_id')
        ),
        CONSTRAINT ck_cp_rules_role_account CHECK (
            role_account IS NULL OR role_account IN (N'booking', N'other')
        ),
        CONSTRAINT ck_cp_rules_tie_booking CHECK (
            tie_booking IS NULL OR tie_booking IN (N'category_id', N'assoc_cat_id')
        ),
        CONSTRAINT ck_cp_rules_tie_other CHECK (
            tie_other IS NULL OR tie_other IN (N'category_id', N'assoc_cat_id')
        ),
        CONSTRAINT ck_cp_rules_role_assoc CHECK (
            role_assoc IS NULL OR role_assoc IN (
                N'booking.category_id',
                N'booking.assoc_cat_id',
                N'other.category_id',
                N'other.assoc_cat_id'
            )
        ),
        CONSTRAINT ck_cp_rules_shape CHECK (
            (
                write_as = N'other.assoc_cat_id'
                AND category_role IS NULL
                AND role_account IS NULL
                AND role_assoc IS NULL
            )
            OR
            (
                write_as = N'role'
                AND category_role IS NOT NULL
            )
        )
    );
GO

-- tie_booking = tie_other
--   the named field on this booking's bank equals the named field on the other bank.
-- write_as other.assoc_cat_id
--   the category is the row that field names on the other bank.
-- write_as role
--   the category is the dim_category row with that category_role.
--   role_account booking|other: that row's account_id is this bank's or the other's.
--   role_assoc: that row's assoc_cat_id equals the named field.

INSERT INTO dbo.cp_rules (
    rule_name, leg, booking_role, other_role, same_center,
    tie_booking, tie_other, write_as,
    category_role, role_account, role_assoc
) VALUES
-- Geldautomaat on the HD account is written to cash on that same account.
(N'geldautomaat', 1, N'hd', NULL, 0,
 NULL, NULL, N'role',
 N'cash', N'booking', NULL),

-- Work unit and its HD, same center.
-- The unit points at nothing here: the HD's assoc is the unit.
-- Unit booking → rc on the HD account whose assoc is the unit.
-- HD booking → cp.
(N'unit-hd', 1, N'unit', N'hd', 1,
 N'category_id', N'assoc_cat_id', N'role',
 N'rc', N'other', N'booking.category_id'),

-- Work unit and the source that unit points at, same center.
-- Unit booking → the category the source points at.
(N'source-unit', 1, N'unit', N'source', 1,
 N'assoc_cat_id', N'category_id', N'other.assoc_cat_id',
 NULL, NULL, NULL),
-- Source booking → rc on the unit account whose assoc is the unit's assoc.
-- Den Eker: 11104. When that rc is absent, this leg is cp (Keizersgracht: 1110).
(N'source-unit', 2, N'source', N'unit', 1,
 N'category_id', N'assoc_cat_id', N'role',
 N'rc', N'other', N'other.assoc_cat_id'),

-- Two sources. The siasib row names one account and points at the other source.
-- There is no tie between the two source rows themselves.
-- Booking on the siasib account → that siasib category. The other source → cp.
(N'source-source', 1, N'source', N'source', 0,
 NULL, NULL, N'role',
 N'siasib', N'booking', N'other.category_id'),
GO

SELECT
    rule_name, leg, booking_role, other_role, same_center,
    tie_booking, tie_other, write_as,
    category_role, role_account, role_assoc
FROM dbo.cp_rules
ORDER BY rule_name, leg;
GO
