-- Hand-made booking categories. A categorization wipe does not delete these
-- rows. Run this file in SSMS on database agrolav before using the menu item.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.category_hand', N'U') IS NULL
CREATE TABLE dbo.category_hand (
    country_id   INT            NOT NULL,
    person_id    INT            NOT NULL,
    year         INT            NOT NULL,
    source_id    NVARCHAR(128)  NOT NULL,
    category_id  INT            NOT NULL,
    CONSTRAINT PK_category_hand PRIMARY KEY (country_id, person_id, year, source_id)
);
GO
