-- Bookings whose category was set by hand. Used to print that category bold.
-- A categorization wipe leaves modification >= 2 bookings in place.

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
