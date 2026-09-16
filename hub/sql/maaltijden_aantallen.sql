-- Monthly meal counts for Export resultaat (person/center username).
-- Hub reads this; it does not CREATE the table.
--
-- SSMS: connect to database agrolav, then execute this file.

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
    warm INT NOT NULL,
    warm_hd INT NOT NULL
);
GO

IF COL_LENGTH(N'dbo.maaltijden_aantallen', N'warm_hd') IS NULL
    ALTER TABLE dbo.maaltijden_aantallen ADD warm_hd INT NOT NULL
        CONSTRAINT df_maaltijden_aantallen_warm_hd DEFAULT (0);
GO
