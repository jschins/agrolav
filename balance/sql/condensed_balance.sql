IF OBJECT_ID(N'dbo.condensed_balance', N'U') IS NULL
CREATE TABLE dbo.condensed_balance (
    id INT IDENTITY(1,1) PRIMARY KEY,
    country_id INT NOT NULL,
    post_name VARCHAR(64) NOT NULL,
    sum_local_code VARCHAR(256) NULL,
    section_name VARCHAR(64) NOT NULL,
    CONSTRAINT fk_map_condensed_country FOREIGN KEY (country_id) REFERENCES dbo.country (country_id)
);

-- Beheer condensed posts. country_id is looked up by username so the seed
-- still works if it is not 4. Does not overwrite an existing map.
-- section_name is a comma-separated path: first part = side (Activa/Passiva),
-- optional second part = group. Posts whose post_name starts with "Totaal "
-- are totals: group-level when the path has a group, side-level otherwise.
INSERT INTO dbo.condensed_balance (country_id, post_name, sum_local_code, section_name)
SELECT c.country_id, v.post_name, v.sum_local_code, v.section_name
FROM dbo.country c
CROSS APPLY (VALUES
    (N'Gebouwen',             N'1000',                                          N'Activa, Vaste activa'),
    (N'Verbouwingen',         N'1005',                                          N'Activa, Vaste activa'),
    (N'Inventaris',           N'1010',                                          N'Activa, Vaste activa'),
    (N'Auto''s',              N'1015',                                          N'Activa, Vaste activa'),
    (N'Bank en Giro',         N'1051,1053,1054,1055,1056',                      N'Activa, Vlottende activa'),
    (N'Kapitaalrekening',     N'1052',                                          N'Activa, Vlottende activa'),
    (N'Debiteuren',           N'1110,1111',                                     N'Activa, Vlottende activa'),
    (N'Eigen vermogen',       N'2000,2100',                                     N'Passiva, Eigen vermogen en voorzieningen'),
    (N'Voorzieningen',        N'2050,2055',                                     N'Passiva, Eigen vermogen en voorzieningen'),
    (N'Langlopende schulden', N'2500',                                          N'Passiva, schulden'),
    (N'Kortlopende schulden', NULL,                                             N'Passiva, schulden'),
    (N'Totaal vaste activa',  N'1000,1005,1010,1015',                           N'Activa, Vaste activa'),
    (N'Totaal vlottende activa', N'1110,1111,1051,1052,1053,1054,1055,1056',    N'Activa, Vlottende activa'),
    (N'Totaal activa',        N'1000,1005,1010,1015,1110,1111,1051,1052,1053,1054,1055,1056', N'Activa'),
    (N'Totaal passiva',       N'2000,2050,2055,2100,2500',                      N'Passiva'),
    (N'Totaal eigen vermogen en voorzieningen', N'2000,2050,2055,2100',         N'Passiva, Eigen vermogen en voorzieningen'),
    (N'Totaal schulden',      N'2500',                                          N'Passiva, Schulden')
) v (post_name, sum_local_code, section_name)
WHERE c.username = N'beheer' COLLATE Latin1_General_CI_AI
  AND NOT EXISTS (
      SELECT 1 FROM dbo.condensed_balance m WHERE m.country_id = c.country_id
  );
