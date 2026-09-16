-- Monthly meal counts for Export resultaat (person/center username).
-- Hub reads this; it does not CREATE the table.
--
-- SSMS: connect to database agrolav, then execute this file.
-- If an earlier version of this table exists, drop it first.

USE agrolav;
GO

IF OBJECT_ID(N'dbo.maaltijden_aantallen', N'U') IS NULL
CREATE TABLE dbo.maaltijden_aantallen (
    id INT IDENTITY(1,1) PRIMARY KEY,
    username nvarchar(128) NOT NULL,
    jaar INT NOT NULL,
    maand INT NOT NULL,
    ontbijt INT NOT NULL,
    koud INT NOT NULL,
    warm INT NOT NULL
);
GO
